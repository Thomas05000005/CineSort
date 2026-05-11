/* components/empty-state.js — Empty state builders
 *
 * Historique :
 *   - D8       : icones SVG Lucide (buildEmptyStateHtml + buildTableEmptyRow)
 *   - V2-07    : factory enrichie buildEmptyState + bindEmptyStateCta (CTA actionnable)
 *
 * Les fonctions historiques (buildEmptyStateHtml, buildTableEmptyRow) restent
 * intactes pour ne pas casser les usages existants. La nouvelle factory ajoute
 * le support d'un CTA et de variantes (card / inline / fullscreen).
 */

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

function buildEmptyStateHtml(title, hint, opts) {
  const t = escapeHtml(String(title || "").trim());
  const h = escapeHtml(String(hint || "").trim());
  const iconName = (opts && opts.icon) || "inbox";
  return [
    '<div class="empty-state">',
    _iconHtml(iconName),
    t ? `<div class="empty-state__title">${t}</div>` : "",
    h ? `<div class="empty-state__hint">${h}</div>` : "",
    "</div>",
  ].join("");
}

function buildTableEmptyRow(colspan, title, hint, opts) {
  const c = Math.max(1, parseInt(colspan || 1, 10) || 1);
  return `<tr class="tbl-empty"><td colspan="${c}">${buildEmptyStateHtml(title, hint, opts)}</td></tr>`;
}

/**
 * V2-07 : factory empty state enrichie avec CTA actionnable.
 *
 * @param {object} opts
 * @param {string} [opts.icon]      Nom d'icone (inbox, film, search, alert, history, library)
 * @param {string} opts.title       Titre court (ex: "Aucun film analyse")
 * @param {string} [opts.message]   Description (ex: "Lancez un scan pour commencer.")
 * @param {string} [opts.ctaLabel]  Texte du bouton CTA
 * @param {string} [opts.ctaRoute]  Route hash (ex: "home", "library#step-analyse")
 * @param {string} [opts.variant]   'card' (defaut) | 'inline' | 'fullscreen'
 * @param {string} [opts.testId]    data-testid optionnel pose sur le bouton CTA
 * @returns {string} HTML markup
 */
function buildEmptyState(opts) {
  const o = opts || {};
  const variant = o.variant === "inline" || o.variant === "fullscreen" ? o.variant : "card";
  const iconHtml = o.icon ? _iconHtml(o.icon) : "";
  const title = String(o.title || "").trim();
  const message = String(o.message || "").trim();
  const ctaLabel = String(o.ctaLabel || "").trim();
  const ctaRoute = String(o.ctaRoute || "").trim();
  const testId = String(o.testId || "").trim();

  const ctaHtml = ctaLabel
    ? `<button type="button" class="btn btn--primary empty-state__cta"`
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
 * V2-07 : bind handlers CTA apres insertion HTML.
 *
 * Pour chaque bouton .empty-state__cta trouve dans `root` :
 *   - si data-nav-route est defini, navigue vers `#<route>` (ou via window.navigateTo)
 *   - sinon execute defaultAction si fournie
 *
 * @param {HTMLElement|Document|null} root  Conteneur parent (acceptee si null)
 * @param {Function} [defaultAction]        Callback fallback si pas de data-nav-route
 */
function bindEmptyStateCta(root, defaultAction) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root.querySelectorAll(".empty-state__cta").forEach((btn) => {
    if (btn.dataset.cinesortEmptyStateBound === "1") return;
    btn.dataset.cinesortEmptyStateBound = "1";
    btn.addEventListener("click", () => {
      const route = btn.dataset.navRoute || "";
      if (route) {
        if (typeof window.navigateTo === "function") {
          // navigateTo accepte des routes sans le prefixe "#"
          const cleanRoute = route.startsWith("#") ? route.slice(1) : route;
          window.navigateTo(cleanRoute.startsWith("/") ? cleanRoute.slice(1) : cleanRoute);
        } else if (typeof window !== "undefined" && window.location) {
          window.location.hash = route.startsWith("#") ? route : "#" + route;
        }
        return;
      }
      if (typeof defaultAction === "function") defaultAction();
    });
  });
}
