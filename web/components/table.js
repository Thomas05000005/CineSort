/* components/table.js — Generic table renderer */

/**
 * Render rows into a tbody element.
 * @param {string} tbodyId   - ID of the <tbody>
 * @param {Object} config
 * @param {Array}  config.rows       - data array
 * @param {Array}  config.columns    - [{ render(row) → HTML string }]
 * @param {string} config.emptyTitle - title when no rows
 * @param {string} config.emptyHint  - hint when no rows
 * @param {Object} [config.emptyCta] - V2-07 : CTA actionnable {label, route?, onClick?, testId?, icon?}
 * @param {Function} config.onRowClick - click handler (row, tr)
 * @param {Function} config.rowClass  - returns extra classes for tr
 * @param {Function} config.rowAttrs  - returns data-* attrs { key: value }
 */
function renderGenericTable(tbodyId, config) {
  const tbody = $(tbodyId);
  if (!tbody) return;
  const rows = Array.isArray(config.rows) ? config.rows : [];
  const columns = Array.isArray(config.columns) ? config.columns : [];

  tbody.innerHTML = "";

  if (!rows.length) {
    const colspan = columns.length || 1;
    const title = config.emptyTitle || "Aucun element.";
    const hint = config.emptyHint || "";
    const cta = config.emptyCta || null;
    // V2-07 : si emptyCta + factory disponible → composant enrichi avec CTA.
    if (cta && typeof buildEmptyState === "function") {
      tbody.innerHTML = `<tr class="tbl-empty"><td colspan="${colspan}">${buildEmptyState({
        icon: cta.icon || "inbox",
        title,
        message: hint,
        ctaLabel: cta.label || "",
        ctaRoute: cta.route || "",
        testId: cta.testId || "",
      })}</td></tr>`;
      if (typeof bindEmptyStateCta === "function") {
        bindEmptyStateCta(tbody, typeof cta.onClick === "function" ? cta.onClick : null);
      }
    } else {
      tbody.innerHTML = `<tr class="tbl-empty"><td colspan="${colspan}">
        <div class="empty-state">
          <div class="empty-state__title">${escapeHtml(title)}</div>
          ${hint ? `<div class="empty-state__hint">${escapeHtml(hint)}</div>` : ""}
        </div>
      </td></tr>`;
    }
    scheduleTableLayoutRefresh();
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    const extraClass = config.rowClass ? config.rowClass(row) : "";
    if (extraClass) tr.className = extraClass;
    if (config.rowAttrs) {
      const attrs = config.rowAttrs(row);
      if (attrs && typeof attrs === "object") {
        for (const [k, v] of Object.entries(attrs)) tr.dataset[k] = String(v);
      }
    }
    tr.innerHTML = columns.map((col) => `<td>${col.render(row)}</td>`).join("");
    if (config.onRowClick) {
      tr.style.cursor = "pointer";
      tr.addEventListener("click", (e) => {
        if (e.target.closest("button,a,input,select")) return;
        config.onRowClick(row, tr, e);
      });
    }
    tbody.appendChild(tr);
  }
  scheduleTableLayoutRefresh();
}
