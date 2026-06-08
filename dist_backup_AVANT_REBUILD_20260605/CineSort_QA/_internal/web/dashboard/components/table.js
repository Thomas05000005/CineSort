/* components/table.js — Table generique sortable pour le dashboard */

import { escapeHtml } from "../core/dom.js";

/**
 * Genere le HTML d'une table sortable.
 *
 * @param {object} config
 * @param {Array<{key:string, label:string, sortable?:boolean, render?:Function}>} config.columns
 * @param {Array<object>} config.rows - donnees brutes
 * @param {string} [config.id] - id du <table>
 * @param {string} [config.emptyText] - texte si aucune ligne
 * @param {boolean} [config.clickable] - true pour ajouter data-row-idx sur les <tr>
 * @returns {string} HTML complet (wrapper + table)
 */
export function tableHtml(config) {
  const { columns = [], rows = [], id = "", emptyText = "Aucune donnée.", clickable = false } = config;

  if (!columns.length) return `<p class="text-muted">${escapeHtml(emptyText)}</p>`;

  let html = '<div class="table-wrap">';
  html += `<table${id ? ` id="${escapeHtml(id)}"` : ""}>`;

  // Header
  // V2-D (a11y) : aria-sort="none" + tabindex="0" + role="button" (sur columnheader)
  // permettent navigation clavier + activation Space/Enter (cf attachSort).
  html += "<thead><tr>";
  for (const col of columns) {
    const sortAttr = col.sortable
      ? ` class="th-sortable" data-sort-key="${escapeHtml(col.key)}" aria-sort="none" tabindex="0" role="columnheader" scope="col"`
      : ' role="columnheader" scope="col"';
    html += `<th${sortAttr}>${escapeHtml(col.label)}</th>`;
  }
  html += "</tr></thead>";

  // Body
  html += "<tbody>";
  if (rows.length === 0) {
    html += `<tr><td colspan="${columns.length}" class="text-muted" style="text-align:center">${escapeHtml(emptyText)}</td></tr>`;
  } else {
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const rowAttr = clickable ? ` data-row-idx="${i}" class="tr-clickable"` : "";
      html += `<tr${rowAttr}>`;
      for (const col of columns) {
        const raw = row[col.key];
        const cell = col.render ? col.render(raw, row) : escapeHtml(String(raw ?? ""));
        html += `<td>${cell}</td>`;
      }
      html += "</tr>";
    }
  }
  html += "</tbody></table></div>";
  return html;
}

/**
 * Attache le tri client sur les headers sortable d'une table.
 * @param {string} tableId - id du <table>
 * @param {Array<object>} rows - tableau source (sera re-trie sur place)
 * @param {Function} rerender - fonction appelee apres tri pour re-generer le tbody
 */
export function attachSort(tableId, rows, rerender) {
  const table = document.getElementById(tableId);
  if (!table) return;

  let currentKey = null;
  let currentDir = 0; // 0=none, 1=asc, -1=desc

  // V2-D (a11y) : un seul handler partage par click et keydown (Space/Enter).
  const _doSort = (th) => {
    const key = th.dataset.sortKey;
    if (key === currentKey) {
      currentDir = currentDir === 1 ? -1 : currentDir === -1 ? 0 : 1;
    } else {
      currentKey = key;
      currentDir = 1;
    }

    // Reset indicateurs
    table.querySelectorAll(".th-sortable").forEach((h) => {
      h.classList.remove("sort-asc", "sort-desc");
      h.setAttribute("aria-sort", "none");
    });
    if (currentDir === 1) {
      th.classList.add("sort-asc");
      th.setAttribute("aria-sort", "ascending");
    } else if (currentDir === -1) {
      th.classList.add("sort-desc");
      th.setAttribute("aria-sort", "descending");
    }

    // Trier
    if (currentDir !== 0) {
      rows.sort((a, b) => {
        const va = a[currentKey] ?? "";
        const vb = b[currentKey] ?? "";
        if (typeof va === "number" && typeof vb === "number") return (va - vb) * currentDir;
        return String(va).localeCompare(String(vb), "fr") * currentDir;
      });
    }

    rerender();
  };

  table.querySelectorAll(".th-sortable").forEach((th) => {
    th.addEventListener("click", () => _doSort(th));
    // V2-D (WCAG 2.1.1) : Space et Enter activent le tri pour les utilisateurs
    // clavier seul (lecteur d'ecran, pas de souris). preventDefault sur Space
    // evite le scroll de la page.
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        _doSort(th);
      }
    });
  });
}
