/* virtual-table.js — H-5 windowed rendering pour les grosses bibliothèques.
 *
 * En dessous du seuil (par defaut 500 lignes), comportement identique a un
 * tbody.innerHTML normal : zero overhead, zero risque pour les utilisateurs
 * typiques. Au-dessus, on rend uniquement la fenetre visible + un overscan,
 * encadree par 2 spacer rows pour preserver la hauteur totale du scroll.
 *
 * Conserve la compatibilite avec l'event delegation existante (les handlers
 * sont sur tbody, pas par <tr>).
 */
(function () {
  "use strict";

  const DEFAULT_THRESHOLD = 500;
  const DEFAULT_OVERSCAN = 10;
  const DEFAULT_ROW_HEIGHT_ESTIMATE = 44;

  function virtualizeTbody(tbody, rows, renderRowHtml, opts) {
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
      const viewportH = scrollEl.clientHeight || 600;

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

      const firstRow = tbody.querySelector("tr:not(.virt-spacer)");
      if (firstRow) {
        const measured = firstRow.getBoundingClientRect().height;
        if (measured > 0 && Math.abs(measured - rowHeight) > 4) {
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

  function _findScrollParent(el) {
    let cur = el ? el.parentElement : null;
    while (cur && cur !== document.body) {
      const overflow = window.getComputedStyle(cur).overflowY;
      if (overflow === "auto" || overflow === "scroll" || overflow === "overlay") return cur;
      cur = cur.parentElement;
    }
    return null;
  }

  function _cleanupVirtual(tbody) {
    if (tbody && typeof tbody._virtCleanup === "function") {
      tbody._virtCleanup();
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

  window.VirtualTable = { virtualizeTbody };
})();
