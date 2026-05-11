/* components/breadcrumb.js — v7.6.0 Vague 1
 * Breadcrumb pour vues nested (ex: Bibliotheque > Film / Parametres > Sources).
 *
 * API publique :
 *   window.BreadcrumbV5.render(container, items)
 *   items = [{ label, route? }, ...]  (dernier item pas cliquable)
 */
(function () {
  "use strict";

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  const CHEVRON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';

  function _buildHtml(items) {
    if (!Array.isArray(items) || items.length === 0) return "";
    const parts = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const isLast = i === items.length - 1;
      if (isLast || !it.route) {
        parts.push(`
          <span class="v5-breadcrumb-current" aria-current="${isLast ? "page" : "false"}">
            ${_esc(it.label)}
          </span>
        `);
      } else {
        parts.push(`
          <a class="v5-breadcrumb-link" href="#${_esc(it.route)}" data-route="${_esc(it.route)}">
            ${_esc(it.label)}
          </a>
        `);
      }
      if (!isLast) {
        parts.push(`<span class="v5-breadcrumb-sep" aria-hidden="true">${CHEVRON}</span>`);
      }
    }
    return `
      <nav class="v5-breadcrumb" data-v5-breadcrumb aria-label="Fil d'Ariane">
        ${parts.join("")}
      </nav>
    `;
  }

  function _bindEvents(root) {
    root.querySelectorAll(".v5-breadcrumb-link").forEach((link) => {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const route = link.dataset.route;
        if (typeof window.navigateTo === "function") window.navigateTo(route);
        else window.location.hash = route;
      });
    });
  }

  /**
   * Render breadcrumb.
   * @param {HTMLElement} container
   * @param {Array<{ label: string, route?: string }>} items
   */
  function render(container, items) {
    if (!container) return;
    container.innerHTML = _buildHtml(items);
    _bindEvents(container);
  }

  window.BreadcrumbV5 = {
    render,
  };
})();
