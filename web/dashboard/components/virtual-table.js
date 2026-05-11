/* dashboard/components/virtual-table.js — V5-01 windowing pour grosses bibliotheques.
 *
 * Module ESM equivalent de web/components/virtual-table.js (IIFE) adapte au
 * dashboard distant (imports ES modules).
 *
 * Pattern : IntersectionObserver implicite via scrollEl + requestAnimationFrame.
 * Render uniquement la fenetre visible (~30-50 rows + overscan), encadree par
 * 2 spacer rows pour preserver la hauteur totale du scroll. Hauteur de row
 * mesuree 1x au premier render et reaffinee si l'estimation differe.
 *
 * Pour les listes <= seuil, fallback transparent vers tbody.innerHTML simple :
 * zero overhead, zero risque pour les utilisateurs typiques.
 *
 * Compatibilite : conserve l'event delegation sur tbody (handlers actifs sur
 * les rows visibles uniquement, pas les spacers).
 *
 * Cible : scroll fluide 60fps sur 10k rows (vs freeze 5-10s avant).
 */

const DEFAULT_THRESHOLD = 500;
const DEFAULT_OVERSCAN = 10;
const DEFAULT_ROW_HEIGHT_ESTIMATE = 44;
const ROW_HEIGHT_TOLERANCE_PX = 4;
const FALLBACK_VIEWPORT_H = 600;

/**
 * Virtualise le rendu d'un tbody avec windowing.
 *
 * @param {HTMLElement} tbody - element tbody a virtualiser
 * @param {Array<object>} rows - donnees brutes
 * @param {Function} renderRowHtml - (row, index) => string HTML pour 1 row
 * @param {object} [opts]
 * @param {number} [opts.threshold=500] - en dessous, fallback innerHTML simple
 * @param {number} [opts.overscan=10] - rows en buffer haut/bas
 * @param {number} [opts.rowHeight=44] - estimation initiale (sera reaffinee)
 * @param {number} [opts.colspan=9] - colspan des spacer rows
 * @param {Function} [opts.afterRender] - callback ([startIdx, endIdx]) post-render
 * @returns {{destroy:Function, scrollToIndex:Function, getVisibleRange:Function, isVirtualized:boolean}}
 */
export function virtualizeTbody(tbody, rows, renderRowHtml, opts) {
  opts = opts || {};
  if (!tbody) return _noop();

  const threshold = opts.threshold || DEFAULT_THRESHOLD;
  const overscan = opts.overscan || DEFAULT_OVERSCAN;
  const colspan = String(opts.colspan || 9);

  _cleanupVirtual(tbody);

  if (!Array.isArray(rows) || rows.length <= threshold) {
    tbody.innerHTML = rows.map(renderRowHtml).join("");
    if (typeof opts.afterRender === "function") opts.afterRender([0, rows.length]);
    return _noop();
  }

  const scrollEl = _findScrollParent(tbody);
  if (!scrollEl) {
    // Aucun parent scrollable detecte, fallback safe
    tbody.innerHTML = rows.map(renderRowHtml).join("");
    if (typeof opts.afterRender === "function") opts.afterRender([0, rows.length]);
    return _noop();
  }

  let rowHeight = opts.rowHeight || DEFAULT_ROW_HEIGHT_ESTIMATE;
  let visibleStart = -1;
  let visibleEnd = -1;
  let rafId = null;

  function renderWindow() {
    const scrollTop = scrollEl.scrollTop;
    const viewportH = scrollEl.clientHeight || FALLBACK_VIEWPORT_H;

    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
    const visibleCount = Math.ceil(viewportH / rowHeight) + overscan * 2;
    const end = Math.min(rows.length, start + visibleCount);

    if (start === visibleStart && end === visibleEnd) return;
    visibleStart = start;
    visibleEnd = end;

    const topSpacerHeight = start * rowHeight;
    const bottomSpacerHeight = (rows.length - end) * rowHeight;

    const html = [];
    if (topSpacerHeight > 0) {
      html.push(`<tr class="virt-spacer" data-virt="top" aria-hidden="true" style="height:${topSpacerHeight}px"><td colspan="${colspan}"></td></tr>`);
    }
    for (let i = start; i < end; i++) {
      html.push(renderRowHtml(rows[i], i));
    }
    if (bottomSpacerHeight > 0) {
      html.push(`<tr class="virt-spacer" data-virt="bottom" aria-hidden="true" style="height:${bottomSpacerHeight}px"><td colspan="${colspan}"></td></tr>`);
    }
    tbody.innerHTML = html.join("");

    // Reaffine la hauteur si l'estimation est trop loin (pour les colonnes denses).
    const firstRow = tbody.querySelector("tr:not(.virt-spacer)");
    if (firstRow) {
      const measured = firstRow.getBoundingClientRect().height;
      if (measured > 0 && Math.abs(measured - rowHeight) > ROW_HEIGHT_TOLERANCE_PX) {
        rowHeight = measured;
      }
    }

    if (typeof opts.afterRender === "function") opts.afterRender([start, end]);
  }

  function onScroll() {
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      renderWindow();
    });
  }

  function destroy() {
    scrollEl.removeEventListener("scroll", onScroll);
    if (rafId) cancelAnimationFrame(rafId);
    tbody._virtCleanup = null;
  }

  function scrollToIndex(idx) {
    if (idx < 0 || idx >= rows.length) return;
    scrollEl.scrollTop = idx * rowHeight;
    renderWindow();
  }

  scrollEl.addEventListener("scroll", onScroll, { passive: true });
  tbody._virtCleanup = destroy;

  renderWindow();

  return {
    destroy,
    scrollToIndex,
    getVisibleRange: () => [visibleStart, visibleEnd],
    isVirtualized: true,
  };
}

/**
 * Cleanup explicite si on remplace le tbody (filtre, switch run, unmount).
 * @param {HTMLElement} tbody
 */
export function destroyVirtualization(tbody) {
  _cleanupVirtual(tbody);
}

function _findScrollParent(el) {
  let cur = el ? el.parentElement : null;
  while (cur && cur !== document.body) {
    const overflow = (typeof window !== "undefined" && window.getComputedStyle)
      ? window.getComputedStyle(cur).overflowY
      : "";
    if (overflow === "auto" || overflow === "scroll" || overflow === "overlay") return cur;
    cur = cur.parentElement;
  }
  return null;
}

function _cleanupVirtual(tbody) {
  if (tbody && typeof tbody._virtCleanup === "function") {
    try { tbody._virtCleanup(); } catch { /* noop */ }
    tbody._virtCleanup = null;
  }
}

function _noop() {
  return {
    destroy: () => {},
    scrollToIndex: () => {},
    getVisibleRange: () => [0, 0],
    isVirtualized: false,
  };
}
