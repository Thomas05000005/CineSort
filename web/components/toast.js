/* components/toast.js — Toasts globaux desktop (D5)
 *
 * Empile bottom-right, auto-dismiss apres `duration` ms (defaut 4 s).
 * Charge avant les vues. Expose window.toast(opts).
 */

(function () {
  let _container = null;

  function _ensureContainer() {
    if (_container && document.body.contains(_container)) return _container;
    _container = document.createElement("div");
    _container.id = "toast-container";
    _container.setAttribute("aria-live", "polite");
    _container.setAttribute("aria-atomic", "false");
    document.body.appendChild(_container);
    return _container;
  }

  function _icon(type) {
    if (type === "success") return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    if (type === "error") return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
    if (type === "warn") return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  }

  /**
   * Affiche un toast.
   * @param {{type?:"info"|"success"|"warn"|"error", text:string, duration?:number, actionLabel?:string, onAction?:Function}} opts
   */
  function toast(opts) {
    const { type = "info", text = "", duration = 4000, actionLabel = "", onAction = null } = opts || {};
    if (!text) return;
    const root = _ensureContainer();
    const node = document.createElement("div");
    node.className = `toast toast--${type}`;
    node.setAttribute("role", "status");
    const actionBtn = actionLabel ? `<button class="toast__action" type="button">${actionLabel}</button>` : "";
    node.innerHTML = `<span class="toast__icon">${_icon(type)}</span><span class="toast__text"></span>${actionBtn}<button class="toast__close" aria-label="Fermer" type="button">×</button>`;
    node.querySelector(".toast__text").textContent = text;
    root.appendChild(node);

    const close = () => {
      node.classList.add("toast--out");
      setTimeout(() => node.remove(), 220);
    };
    node.querySelector(".toast__close").addEventListener("click", close);
    if (actionLabel && typeof onAction === "function") {
      node.querySelector(".toast__action").addEventListener("click", () => {
        try { onAction(); } catch (e) { console.error("[toast action]", e); }
        close();
      });
    }
    /* Duree etendue si action presente (donner le temps de cliquer). */
    setTimeout(close, Math.max(1500, actionLabel ? Math.max(8000, duration) : duration));
  }

  window.toast = toast;
})();
