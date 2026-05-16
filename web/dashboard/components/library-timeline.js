// Dashboard Timeline : films ajoutes par mois (histogramme).
// Backend : library/get_library_timeline (cinesort.ui.api.library_timeline_support).
//
// payload = { total_films, source: "jellyfin"|"filesystem"|"mixed",
//             films_with_date_pct, months: [{month: "YYYY-MM", count}, ...] }

import { escapeHtml } from "../core/dom.js";

const _MONTH_LABELS_FR = {
  "01": "Jan", "02": "Fev", "03": "Mar", "04": "Avr",
  "05": "Mai", "06": "Juin", "07": "Juil", "08": "Aout",
  "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
};

function _shortMonthLabel(yyyymm) {
  if (!yyyymm) return "";
  const parts = String(yyyymm).split("-");
  if (parts.length !== 2) return yyyymm;
  const [year, month] = parts;
  return `${_MONTH_LABELS_FR[month] || month} ${year.slice(2)}`;
}

function _sourceLabel(source) {
  if (source === "jellyfin") return "Jellyfin DateCreated";
  if (source === "filesystem") return "mtime fichier";
  if (source === "mixed") return "mixte (Jellyfin + mtime)";
  return source;
}

export function renderLibraryTimeline(payload) {
  if (!payload || payload.total_films === 0 || !payload.months || payload.months.length === 0) {
    return "";
  }
  const months = payload.months;
  const maxCount = Math.max(1, ...months.map((m) => m.count));
  const totalAdded = months.reduce((s, m) => s + m.count, 0);
  const cov = payload.films_with_date_pct ?? 0;
  const source = payload.source || "filesystem";

  let html = '<div class="card mt-4" data-stat="library-timeline">';
  html += `<h3>📅 Films ajoutés par mois</h3>`;
  html += `<p class="text-muted" style="font-size:var(--fs-xs);margin-top:0">`;
  html += `${totalAdded} films sur ${months.length} mois `;
  html += `(${cov.toFixed(0)}% des films ont une date — source: ${escapeHtml(_sourceLabel(source))})`;
  html += `</p>`;
  html += '<div class="timeline-bars">';
  for (const m of months) {
    const pct = Math.round((m.count / maxCount) * 100);
    const heightStyle = `height:${pct}%`;
    const tooltip = `${_shortMonthLabel(m.month)} : ${m.count} films`;
    html += `<div class="timeline-bar-col" title="${escapeHtml(tooltip)}">`;
    html += `<div class="timeline-bar-value">${m.count > 0 ? m.count : ""}</div>`;
    html += `<div class="timeline-bar-track">`;
    html += `<div class="timeline-bar-fill" style="${heightStyle}"></div>`;
    html += `</div>`;
    html += `<div class="timeline-bar-label">${escapeHtml(_shortMonthLabel(m.month))}</div>`;
    html += `</div>`;
  }
  html += "</div>";
  html += "</div>";
  return html;
}
