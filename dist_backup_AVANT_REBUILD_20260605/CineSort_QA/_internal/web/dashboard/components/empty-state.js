/* dashboard/components/empty-state.js — V2-07 EmptyState (ES module mirror)
 *
 * Variante ES module du composant web/components/empty-state.js (qui est un
 * script global pour l'app desktop). Memes APIs (buildEmptyState +
 * bindEmptyStateCta) et memes classes CSS, pour rester visuellement coherent
 * entre desktop et dashboard distant.
 */

import { escapeHtml } from "../core/dom.js";

const _ICONS = {
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  film:    '<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>',
  search:  '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  alert:   '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><polyline points="3 3 3 8 8 8"/><path d="M12 7v5l3 2"/>',
  library: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
};

function _iconHtml(name) {
  const path = _ICONS[name];
  if (!path) return "";
  return `<span class="empty-state__icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${path}</svg></span>`;
}

/**
 * @param {object} opts
 * @param {string} [opts.icon]      Nom d'icone (inbox, film, search, alert, history, library)
 * @param {string} opts.title       Titre court
 * @param {string} [opts.message]   Description
 * @param {string} [opts.ctaLabel]  Texte du bouton CTA
 * @param {string} [opts.ctaRoute]  Route hash (ex: "/library#step-analyse")
 * @param {string} [opts.variant]   'card' (defaut) | 'inline' | 'fullscreen'
 * @param {string} [opts.testId]    data-testid pose sur le bouton CTA
 * @returns {string} HTML markup
 */
export function buildEmptyState(opts) {
  const o = opts || {};
  const variant = o.variant === "inline" || o.variant === "fullscreen" ? o.variant : "card";
  const iconHtml = o.icon ? _iconHtml(o.icon) : "";
  const title = String(o.title || "").trim();
  const message = String(o.message || "").trim();
  const ctaLabel = String(o.ctaLabel || "").trim();
  const ctaRoute = String(o.ctaRoute || "").trim();
  const testId = String(o.testId || "").trim();

  const ctaHtml = ctaLabel
    ? `<button type="button" class="btn btn-primary empty-state__cta"`
      + (ctaRoute ? ` data-nav-route="${escapeHtml(ctaRoute)}"` : "")
      + (testId ? ` data-testid="${escapeHtml(testId)}"` : "")
      + `>${escapeHtml(ctaLabel)}</button>`
    : "";

  return [
    `<div class="empty-state empty-state--${variant}">`,
    iconHtml,
    title ? `<div class="empty-state__title">${escapeHtml(title)}</div>` : "",
    message ? `<div class="empty-state__message">${escapeHtml(message)}</div>` : "",
    ctaHtml,
    "</div>",
  ].join("");
}

/**
 * Bind handlers CTA apres insertion HTML.
 * @param {HTMLElement|Document|null} root  Conteneur parent
 * @param {Function} [defaultAction]        Callback fallback si pas de data-nav-route
 */
export function bindEmptyStateCta(root, defaultAction) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root.querySelectorAll(".empty-state__cta").forEach((btn) => {
    if (btn.dataset.cinesortEmptyStateBound === "1") return;
    btn.dataset.cinesortEmptyStateBound = "1";
    btn.addEventListener("click", () => {
      const route = btn.dataset.navRoute || "";
      if (route) {
        if (typeof window !== "undefined" && window.location) {
          window.location.hash = route.startsWith("#") ? route : "#" + route;
        }
        return;
      }
      if (typeof defaultAction === "function") defaultAction();
    });
  });
}
