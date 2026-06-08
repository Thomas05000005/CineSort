/* components/auto-tooltip.js — Ajoute title automatique sur cellules tronquees. */

function _maybeAddTitle(el) {
  if (!el) return;
  if (el.scrollWidth > el.clientWidth + 1) {
    if (!el.hasAttribute("title")) el.setAttribute("title", (el.textContent || "").trim());
  } else if (el.hasAttribute("title") && el.dataset.autotip === "1") {
    el.removeAttribute("title");
  }
  el.dataset.autotip = "1";
}

export function refreshAutoTooltips(root) {
  const scope = root || document;
  scope.querySelectorAll("table td, [data-truncate]").forEach(_maybeAddTitle);
}

let _t = null;
export function scheduleAutoTooltips() {
  clearTimeout(_t);
  _t = setTimeout(() => refreshAutoTooltips(), 80);
}

export function initAutoTooltip() {
  scheduleAutoTooltips();
  const obs = new MutationObserver(scheduleAutoTooltips);
  obs.observe(document.body, { childList: true, subtree: true });
  // Compat global
  if (typeof window !== "undefined") {
    window.refreshAutoTooltips = refreshAutoTooltips;
    window.scheduleAutoTooltips = scheduleAutoTooltips;
  }
}
