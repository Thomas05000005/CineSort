/* components/scan-banner.js — Banniere "scan en cours" persistante (top de page)
 *
 * mega-hotfix frontend_ui_polish (#6) : avant ce module, un utilisateur qui
 * lancait un scan puis naviguait vers une autre vue (Accueil, Bibliotheque...)
 * perdait toute trace visuelle du scan en cours. Au retour sur /traitement,
 * il devait re-attendre le polling (2-5s) avant de voir la progression. Cas
 * pire : l'utilisateur oubliait qu'un scan tournait et lancait des actions
 * concurrentes (apply, suppression de cache...).
 *
 * Cette banniere :
 *   - polle `run/get_dashboard` toutes les 5s (interval doux, pas bloquant)
 *   - s'affiche en TOP de page UNIQUEMENT si un run est dans un etat actif
 *     (RUNNING / PENDING / PAUSED / AWAITING_VALIDATION) ET si l'utilisateur
 *     n'est pas deja sur /traitement (sinon doublon avec le header de la vue)
 *   - clic sur la banniere => navigation vers /traitement#run-<id>
 *   - se masque automatiquement quand le run est DONE/FAILED/CANCELLED
 *
 * Comportement defensif :
 *   - si l'API echoue, on ne casse rien : la banniere reste cachee
 *   - si l'utilisateur n'est pas authentifie (login), on n'init pas du tout
 *   - le DOM est cree paresseusement au 1er render positif, jamais avant
 *
 * Backward compat : module isole, exporte init + stop, n'introduit aucune
 * dependance sur les vues existantes.
 */

import { apiPost } from "../core/api.js";
import { hasToken } from "../core/state.js";

const _POLL_MS = 5000;
const _ACTIVE_STATES = new Set([
  "RUNNING",
  "PENDING",
  "PAUSED",
  "AWAITING_VALIDATION",
]);
const _BANNER_ID = "cinesort-scan-banner";

let _timer = null;
let _bannerEl = null;
let _started = false;

function _ensureBanner() {
  if (_bannerEl && document.body.contains(_bannerEl)) return _bannerEl;
  const el = document.createElement("div");
  el.id = _BANNER_ID;
  el.setAttribute("role", "status");
  el.setAttribute("aria-live", "polite");
  // Styles inline minimaux pour ne pas dependre du chargement d'une CSS dediee
  // (la banniere doit fonctionner meme si une vue casse son CSS).
  el.style.cssText = [
    "position:fixed",
    "top:0",
    "left:0",
    "right:0",
    "z-index:9998", // sous l'error-banner global (99999) mais au-dessus du shell
    "background:linear-gradient(90deg,#2563eb,#1d4ed8)",
    "color:#fff",
    "padding:6px 16px",
    "font-family:system-ui,sans-serif",
    "font-size:13px",
    "box-shadow:0 2px 6px rgba(0,0,0,0.25)",
    "cursor:pointer",
    "display:none",
    "align-items:center",
    "gap:12px",
    "user-select:none",
  ].join(";");
  el.innerHTML = `
    <span aria-hidden="true" style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#fbbf24;box-shadow:0 0 8px #fbbf24;"></span>
    <strong style="font-weight:600">Scan en cours</strong>
    <span data-scan-banner-meta style="opacity:0.85"></span>
    <span style="margin-left:auto;font-size:12px;opacity:0.9">Cliquer pour ouvrir Traitement →</span>
  `;
  el.addEventListener("click", function onScanBannerClick() {
    const runId = el.dataset.runId || "";
    const target = runId ? `#/traitement#run-${encodeURIComponent(runId)}` : "#/traitement";
    if (window.location.hash !== target) {
      window.location.hash = target;
    }
  });
  document.body.appendChild(el);
  _bannerEl = el;
  return el;
}

function _hide() {
  if (_bannerEl) _bannerEl.style.display = "none";
}

function _show(status, runId, idx, total) {
  const el = _ensureBanner();
  el.dataset.runId = String(runId || "");
  const meta = el.querySelector("[data-scan-banner-meta]");
  if (meta) {
    const pct = (total > 0) ? Math.round((idx * 100) / total) : null;
    const parts = [String(status || "RUNNING")];
    if (total > 0) parts.push(`${idx}/${total}`);
    if (pct != null) parts.push(`${pct}%`);
    meta.textContent = parts.join(" · ");
  }
  el.style.display = "flex";
}

function _isOnTraitementRoute() {
  const h = String(window.location.hash || "");
  return h.startsWith("#/traitement");
}

async function _tick() {
  // Sur /traitement, la vue affiche deja le header run actif -> banniere
  // redondante, on la cache.
  if (_isOnTraitementRoute()) {
    _hide();
    return;
  }
  if (!hasToken()) {
    _hide();
    return;
  }
  try {
    const res = await apiPost("run/get_dashboard", { run_id: "latest" });
    const data = (res && res.data) || res || {};
    if (!data || data.ok === false) {
      _hide();
      return;
    }
    const runId = data.run_id;
    // Le status frais vient de get_status (kpis n'a pas le statut live).
    // On tente un appel get_status si on a un runId.
    let status = "";
    let idx = 0;
    let total = 0;
    if (runId) {
      try {
        const sres = await apiPost("run/get_status", { run_id: runId, last_log_index: 0 });
        const sd = (sres && sres.data) || sres || {};
        status = String(sd.status || "");
        idx = Number(sd.idx || 0);
        total = Number(sd.total || 0);
      } catch (_e) {
        // get_status en echec : on retombera sur kpis pour decider d'afficher ou non.
      }
    }
    if (_ACTIVE_STATES.has(status)) {
      _show(status, runId, idx, total);
    } else {
      _hide();
    }
  } catch (_e) {
    // Reseau down ou auth perdue : on cache la banniere proprement.
    _hide();
  }
}

/**
 * Initialise la banniere globale. Idempotent : un seul timer / un seul DOM
 * meme si initScanBanner est appele plusieurs fois (eg HMR).
 */
export function initScanBanner() {
  if (_started) return;
  _started = true;
  // Premier tick immediat puis poll regulier. Le 1er tick s'execute apres
  // un microtask pour laisser le boot finir et eviter une race avec le router.
  setTimeout(_tick, 0);
  _timer = setInterval(_tick, _POLL_MS);
  // Au hashchange, on re-evalue immediatement (utile quand l'utilisateur
  // arrive sur /traitement : on veut cacher la banniere tout de suite).
  window.addEventListener("hashchange", _tick);
}

/**
 * Arrete le polling et supprime la banniere du DOM (test ou logout).
 */
export function stopScanBanner() {
  if (_timer) {
    clearInterval(_timer);
    _timer = null;
  }
  window.removeEventListener("hashchange", _tick);
  if (_bannerEl && _bannerEl.parentNode) {
    _bannerEl.parentNode.removeChild(_bannerEl);
  }
  _bannerEl = null;
  _started = false;
}
