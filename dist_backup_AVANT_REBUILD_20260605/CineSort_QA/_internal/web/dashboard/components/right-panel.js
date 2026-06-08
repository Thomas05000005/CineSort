/* dashboard/components/right-panel.js — Phase 2 (Shell 3 zones, spec 04)
 *
 * Inspecteur droit persistant. Chaque vue peut injecter ses propres sections via
 * setSections(). L'inspecteur est replieable, redimensionnable (280-480px), et
 * persiste son etat (visible/replie + largeur) dans localStorage.
 *
 * API publique :
 *   render(mountEl)              -> structure HTML initiale
 *   setSections(sections)        -> [{ title, html }] -> remplace le contenu
 *   setExpanded(bool)            -> deploie/replie
 *   isExpanded()                 -> bool
 *   setWidth(px)                 -> 280 <= px <= 480
 *   reset()                      -> vide le contenu (entre 2 nav)
 *   adaptToRoute(routeHash)      -> applique l'etat par defaut spec 04
 */

import { escapeHtml } from "../core/dom.js";

const STORAGE_KEY_EXPANDED = "cinesort.rightpanel.expanded";
const STORAGE_KEY_WIDTH = "cinesort.rightpanel.width";

const MIN_WIDTH = 280;
// Spec 06 Modal Detail Film : mode A inspecteur elargi peut aller jusqu'a 600px
// pour afficher le hero + candidats TMDb confortablement. Avant : 480.
const MAX_WIDTH = 600;
const DEFAULT_WIDTH = 360;

// Spec 02 §0 (Mode A inspecteur elargi) : pour la modal perceptuelle on
// elargit le panneau jusqu'a 600px, au-dela du resize manuel normal.
// Borne haute aussi par 50% de window.innerWidth.
const EXPANDED_MAX_WIDTH = 600;

// Spec 04 §4 : inspecteur par defaut par route.
// Replie sur Accueil/Parametres/Aide (vues synthese / config), visible sur les
// vues expertes (Traitement, Bibliotheque, Qualite, Historique).
const DEFAULT_EXPANDED_BY_ROUTE = {
  "/accueil": false,
  "/home": false,
  "/status": false,
  "/parametres": false,
  "/settings": false,
  "/aide": false,
  "/help": false,
  "/login": false,
  "/traitement": true,
  "/processing": true,
  "/bibliotheque": true,
  "/library": true,
  "/qualite": true,
  "/historique": true,
  "/qij": true,
};

let _mountEl = null;
let _root = null;
let _sectionsEl = null;
let _isResizing = false;
let _resizeStartX = 0;
let _resizeStartWidth = 0;

function _readStorageBool(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    if (v === null) return fallback;
    return v === "1";
  } catch (_e) {
    return fallback;
  }
}

function _readStorageNumber(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    if (v === null) return fallback;
    const n = parseInt(v, 10);
    if (Number.isNaN(n)) return fallback;
    return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, n));
  } catch (_e) {
    return fallback;
  }
}

function _writeStorage(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch (_e) {
    /* noop : private mode, quota exceeded, etc. */
  }
}

function _buildHtml() {
  return `
    <div class="v5-right-panel" data-v5-right-panel>
      <div class="v5-right-panel-handle" data-v5-right-panel-handle aria-hidden="true"></div>
      <header class="v5-right-panel-header">
        <button type="button" class="v5-right-panel-toggle" data-v5-right-panel-toggle
                aria-label="Replier ou deployer l'inspecteur" aria-expanded="true">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
               stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
        </button>
        <span class="v5-right-panel-title">Inspecteur</span>
      </header>
      <div class="v5-right-panel-body" data-v5-right-panel-body>
        <div class="v5-right-panel-empty">
          Selectionnez un element pour afficher ses details ici.
        </div>
      </div>
    </div>
  `;
}

function _attachHandlers() {
  if (!_root) return;
  const toggleBtn = _root.querySelector("[data-v5-right-panel-toggle]");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      setExpanded(!isExpanded());
    });
  }
  const handle = _root.querySelector("[data-v5-right-panel-handle]");
  if (handle) {
    handle.addEventListener("pointerdown", _onResizeStart);
  }
}

function _onResizeStart(ev) {
  if (!_root) return;
  _isResizing = true;
  _resizeStartX = ev.clientX;
  _resizeStartWidth = _root.offsetWidth || DEFAULT_WIDTH;
  document.body.style.userSelect = "none";
  document.body.style.cursor = "col-resize";
  window.addEventListener("pointermove", _onResizeMove);
  window.addEventListener("pointerup", _onResizeEnd, { once: true });
  ev.preventDefault();
}

function _onResizeMove(ev) {
  if (!_isResizing || !_root) return;
  const delta = _resizeStartX - ev.clientX;
  // Si l'inspecteur est en mode elargi (Mode A perceptuelle), autoriser jusqu'a
  // EXPANDED_MAX_WIDTH ; sinon cap a MAX_WIDTH (480) comme avant.
  const expanded = _root.classList.contains("is-mode-expanded");
  const upper = expanded ? EXPANDED_MAX_WIDTH : MAX_WIDTH;
  const newWidth = Math.max(MIN_WIDTH, Math.min(upper, _resizeStartWidth + delta));
  _root.style.width = `${newWidth}px`;
}

function _onResizeEnd() {
  if (!_isResizing) return;
  _isResizing = false;
  document.body.style.userSelect = "";
  document.body.style.cursor = "";
  window.removeEventListener("pointermove", _onResizeMove);
  if (_root) {
    const w = parseInt(_root.style.width, 10);
    if (!Number.isNaN(w)) {
      _writeStorage(STORAGE_KEY_WIDTH, w);
    }
  }
}

export function render(mountEl) {
  if (!mountEl) return;
  _mountEl = mountEl;
  _mountEl.innerHTML = _buildHtml();
  _root = _mountEl.querySelector("[data-v5-right-panel]");
  _sectionsEl = _mountEl.querySelector("[data-v5-right-panel-body]");
  if (!_root) return;

  const expanded = _readStorageBool(STORAGE_KEY_EXPANDED, true);
  const width = _readStorageNumber(STORAGE_KEY_WIDTH, DEFAULT_WIDTH);
  _root.style.width = `${width}px`;
  _root.classList.toggle("is-collapsed", !expanded);
  const toggleBtn = _root.querySelector("[data-v5-right-panel-toggle]");
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", expanded ? "true" : "false");

  _attachHandlers();
}

export function setSections(sections) {
  if (!_sectionsEl) return;
  if (!Array.isArray(sections) || sections.length === 0) {
    _sectionsEl.innerHTML = `<div class="v5-right-panel-empty">Selectionnez un element pour afficher ses details ici.</div>`;
    return;
  }
  const html = sections
    .map((section) => {
      const title = section.title ? `<h3 class="v5-right-panel-section-title">${escapeHtml(section.title)}</h3>` : "";
      const body = section.html != null ? String(section.html) : "";
      return `<section class="v5-right-panel-section">${title}<div class="v5-right-panel-section-body">${body}</div></section>`;
    })
    .join("");
  _sectionsEl.innerHTML = html;
}

export function isExpanded() {
  if (!_root) return false;
  return !_root.classList.contains("is-collapsed");
}

export function setExpanded(expanded) {
  if (!_root) return;
  const wasExpanded = isExpanded();
  if (wasExpanded === expanded) return;
  _root.classList.toggle("is-collapsed", !expanded);
  _writeStorage(STORAGE_KEY_EXPANDED, expanded ? 1 : 0);
  const toggleBtn = _root.querySelector("[data-v5-right-panel-toggle]");
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
}

export function setWidth(px) {
  if (!_root) return;
  // Spec 02 §0 : autoriser jusqu'a EXPANDED_MAX_WIDTH (600) pour Mode A.
  // Capped par 50% de window.innerWidth pour rester utilisable sur petits ecrans.
  const winLimit = typeof window !== "undefined" && window.innerWidth
    ? Math.floor(window.innerWidth * 0.5)
    : EXPANDED_MAX_WIDTH;
  const upper = Math.min(EXPANDED_MAX_WIDTH, Math.max(MAX_WIDTH, winLimit));
  const w = Math.max(MIN_WIDTH, Math.min(upper, Math.round(px)));
  _root.style.width = `${w}px`;
  _writeStorage(STORAGE_KEY_WIDTH, w);
}

/**
 * Spec 02 §0 : largeur normale (DEFAULT_WIDTH) ou elargie (EXPANDED_MAX_WIDTH).
 * Utilise par la Modal Perceptuelle Mode A pour le toggle bouton ▶/◀.
 */
export function setExpandedWidth(isExpanded) {
  if (!_root) return;
  if (isExpanded) {
    setWidth(EXPANDED_MAX_WIDTH);
    _root.classList.add("is-mode-expanded");
  } else {
    setWidth(DEFAULT_WIDTH);
    _root.classList.remove("is-mode-expanded");
  }
}

/** Spec 02 §0 : verifie si l'inspecteur est en mode elargi (>= MAX_WIDTH). */
export function isExpandedWidth() {
  if (!_root) return false;
  return (_root.offsetWidth || 0) > MAX_WIDTH;
}

export function reset() {
  setSections([]);
}

export function adaptToRoute(routeHash) {
  if (!_root) return;
  const base = String(routeHash || "").split("#")[0];
  if (!(base in DEFAULT_EXPANDED_BY_ROUTE)) {
    return;
  }
  const stored = _readStorageBool(STORAGE_KEY_EXPANDED, null);
  if (stored !== null) {
    setExpanded(stored);
    return;
  }
  setExpanded(DEFAULT_EXPANDED_BY_ROUTE[base]);
}
