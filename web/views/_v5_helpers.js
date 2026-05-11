/* _v5_helpers.js — Module shared pour les vues v5 portees (V5bis-00)
 *
 * Pattern : ES modules + REST apiPost (compatible SPA dashboard distant
 * ET pywebview natif via le serveur REST local).
 *
 * Compat : tant que web/views/*.js IIFE coexiste, ce module ne casse rien
 * (les vues IIFE n'importent rien). Quand V5C supprimera l'ancienne
 * couche, ce helper restera la base unique.
 *
 * Format de reponse normalise par apiPost :
 *   { ok: bool, data: any, status: number, error?: string }
 *   - ok = true ssi status 200 et data?.ok !== false
 *   - data = payload metier (ce que retourne CineSortApi)
 *   - status = code HTTP (REST) ou 0 (fallback pywebview)
 */

import { apiPost as _spaApiPost, apiGet as _spaApiGet } from "../dashboard/core/api.js";
import { escapeHtml as _escapeHtml, $, $$, el } from "../dashboard/core/dom.js";

/* ============================================================
   apiPost : wrapper REST + fallback pywebview
   ============================================================ */

/**
 * Wrapper apiPost compatible SPA + pywebview legacy.
 * Prefere le client REST (qui marche partout). Fallback window.pywebview.api
 * pour les migrations partielles (a supprimer en V5C).
 *
 * @param {string} method - nom de la methode CineSortApi
 * @param {object} [params] - parametres en kwargs (objet, pas array)
 * @returns {Promise<{ok: boolean, data: any, status: number, error?: string}>}
 */
export async function apiPost(method, params) {
  try {
    const res = await _spaApiPost(method, params || {});
    return _normalizeRestResponse(res);
  } catch (e) {
    // Si REST indisponible mais pywebview natif present, on bascule
    if (typeof window !== "undefined" && window.pywebview?.api?.[method]) {
      try {
        const args = _kwargsToPositional(method, params);
        const res = await window.pywebview.api[method](...args);
        return _normalizePywebviewResponse(res);
      } catch (e2) {
        return { ok: false, data: null, status: 0, error: String(e2) };
      }
    }
    return { ok: false, data: null, status: 0, error: String(e) };
  }
}

/** Helper apiGet (pour /api/health, /api/spec). */
export async function apiGet(path) {
  try {
    const res = await _spaApiGet(path);
    return _normalizeRestResponse(res);
  } catch (e) {
    return { ok: false, data: null, status: 0, error: String(e) };
  }
}

/** Convertit les kwargs en positional pour pywebview (si necessaire).
 * Ce helper est imparfait — prefere REST qui passe nativement les kwargs. */
function _kwargsToPositional(method, params) {
  if (!params || typeof params !== "object") return [];
  return Object.values(params);
}

/** Normalise la reponse REST { status, data } vers { ok, data, status }. */
function _normalizeRestResponse(res) {
  const status = Number(res?.status || 0);
  const data = res?.data ?? null;
  // ok = HTTP 2xx ET data.ok !== false (si data porte un champ ok)
  const httpOk = status >= 200 && status < 300;
  const dataOk = data && typeof data === "object" && "ok" in data ? data.ok !== false : true;
  const ok = httpOk && dataOk;
  const error = ok ? undefined : (data?.message || data?.error || `HTTP ${status}`);
  return { ok, data, status, error };
}

/** Normalise la reponse pywebview (valeur brute) vers { ok, data, status }. */
function _normalizePywebviewResponse(res) {
  // Si pywebview retourne deja { ok, data }, on respecte.
  if (res && typeof res === "object" && "ok" in res) {
    return { ok: res.ok !== false, data: res.data ?? res, status: 0, error: res.error || res.message };
  }
  return { ok: true, data: res, status: 0 };
}

/* ============================================================
   DOM helpers (re-export depuis dashboard/core/dom.js)
   ============================================================ */

export const escapeHtml = _escapeHtml;
export { $, $$, el };

/* ============================================================
   Pattern d'init standardise : skeleton -> load -> render | error
   ============================================================ */

const _SKELETON_TEMPLATES = {
  default: `<div class="v5-skeleton">${"<div class=\"v5-skeleton-row\"></div>".repeat(5)}</div>`,
  table: `<div class="v5-skeleton-table">${"<div class=\"v5-skeleton-row\"></div>".repeat(10)}</div>`,
  grid: `<div class="v5-skeleton-grid">${"<div class=\"v5-skeleton-card\"></div>".repeat(8)}</div>`,
  form: `<div class="v5-skeleton-form">${"<div class=\"v5-skeleton-field\"></div>".repeat(6)}</div>`,
};

/** Affiche un skeleton generique pendant le chargement.
 * @param {HTMLElement} container - cible
 * @param {"default"|"table"|"grid"|"form"} [type="default"]
 */
export function renderSkeleton(container, type) {
  if (!container) return;
  const t = type || "default";
  container.innerHTML = _SKELETON_TEMPLATES[t] || _SKELETON_TEMPLATES.default;
}

/** Affiche un etat d'erreur avec bouton "Reessayer" optionnel.
 * @param {HTMLElement} container - cible
 * @param {Error|string|object} error - erreur a afficher
 * @param {Function} [retryFn] - callback de retry
 */
export function renderError(container, error, retryFn) {
  if (!container) return;
  const msg = error?.message || error?.error || error || "Erreur inconnue";
  container.innerHTML = `
    <div class="v5-error-state" role="alert">
      <h3>Une erreur est survenue</h3>
      <p>${escapeHtml(String(msg))}</p>
      ${retryFn ? `<button type="button" class="v5-btn v5-btn--primary" data-v5-retry>Reessayer</button>` : ""}
    </div>
  `;
  if (retryFn) {
    container.querySelector("[data-v5-retry]")?.addEventListener("click", retryFn);
  }
}

/** Wrapper standard pour init de vue : skeleton -> load -> render | error.
 *
 * @param {HTMLElement} container - conteneur DOM
 * @param {Function} loader - async () => data (peut throw)
 * @param {Function} renderer - (container, data) => void
 * @param {object} [opts] - { skeletonType }
 */
export async function initView(container, loader, renderer, opts) {
  if (!container) return;
  const o = opts || {};
  renderSkeleton(container, o.skeletonType || "default");
  try {
    const data = await loader();
    renderer(container, data);
  } catch (e) {
    renderError(container, e, () => initView(container, loader, renderer, opts));
  }
}

/* ============================================================
   Utilitaires metier
   ============================================================ */

/** Detecte si on tourne en pywebview natif (flag pose par app.js au boot). */
export function isNativeMode() {
  return typeof window !== "undefined" && !!window.__CINESORT_NATIVE__;
}

/** Format une taille en bytes vers o/Ko/Mo/Go/To (FR) ou B/KB/MB/GB/TB (EN), locale-aware (V6-04). */
export function formatSize(bytes) {
  // V6-04 : delegue a window.formatBytes (locale-aware via core/format.js).
  if (typeof window !== "undefined" && typeof window.formatBytes === "function") {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return "—";
    return window.formatBytes(n, 1);
  }
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return "—";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  const decimals = v < 10 && i > 0 ? 1 : 0;
  return `${v.toFixed(decimals)} ${units[i]}`;
}

/** Format ms -> "X s" / "X min Y s" / "X h Y min" lisible. */
export function formatDuration(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const totalSec = Math.round(n / 1000);
  if (totalSec < 60) return `${totalSec} s`;
  const totalMin = Math.floor(totalSec / 60);
  const remSec = totalSec % 60;
  if (totalMin < 60) {
    return remSec > 0 ? `${totalMin} min ${remSec} s` : `${totalMin} min`;
  }
  const hours = Math.floor(totalMin / 60);
  const remMin = totalMin % 60;
  return remMin > 0 ? `${hours} h ${remMin} min` : `${hours} h`;
}
