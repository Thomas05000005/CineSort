/* components/auto-tooltip.js — Pose title natif sur cellules tronquees (E4)
 *
 * Scan periodique des elements .tbl td et data-truncate : si le scrollWidth
 * depasse le clientWidth, on pose title = textContent pour avoir un tooltip
 * natif au hover. Combine avec le CSS [data-tip] pour les tooltips stylises.
 */

function _maybeAddTitle(el) {
  if (!el) return;
  if (el.scrollWidth > el.clientWidth + 1) {
    if (!el.hasAttribute("title")) el.setAttribute("title", el.textContent.trim());
  } else if (el.hasAttribute("title") && el.dataset.autotip === "1") {
    el.removeAttribute("title");
  }
  el.dataset.autotip = "1";
}

function refreshAutoTooltips(root) {
  const scope = root || document;
  scope.querySelectorAll(".tbl td, [data-truncate]").forEach(_maybeAddTitle);
}

/* Auto-refresh apres chaque rendu de table (debounce). */
let _t = null;
function scheduleAutoTooltips() {
  clearTimeout(_t);
  _t = setTimeout(() => refreshAutoTooltips(), 80);
}

window.refreshAutoTooltips = refreshAutoTooltips;
window.scheduleAutoTooltips = scheduleAutoTooltips;

document.addEventListener("DOMContentLoaded", () => {
  scheduleAutoTooltips();
  /* Observe les modifications de DOM (ajout de lignes, navigation vues) */
  const obs = new MutationObserver(scheduleAutoTooltips);
  obs.observe(document.body, { childList: true, subtree: true });
});
