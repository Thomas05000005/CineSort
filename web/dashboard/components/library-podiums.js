// Dashboard Podiums : top release groups + codecs + sources.
// Backend : library/get_library_podiums (cinesort.ui.api.library_podiums_support).
//
// Usage :
//   import { renderLibraryPodiums } from "./components/library-podiums.js";
//   const html = renderLibraryPodiums(podiumsPayload);
//
// payload = { total_films, release_groups:[{name,count}...], codecs:[...],
//             sources:[...], coverage:{release_groups_pct, codecs_pct, sources_pct} }

import { escapeHtml } from "../core/dom.js";

function _renderTopList(items, emptyHint) {
  if (!items || items.length === 0) {
    return `<div class="text-muted" style="font-size:var(--fs-xs);padding:var(--sp-3) 0">${escapeHtml(emptyHint)}</div>`;
  }
  const maxCount = Math.max(...items.map((i) => i.count));
  let html = '<div class="podium-list">';
  items.forEach((item, idx) => {
    const pct = maxCount > 0 ? Math.round((item.count / maxCount) * 100) : 0;
    const rankBadge = idx < 3 ? ["🥇", "🥈", "🥉"][idx] : `${idx + 1}.`;
    html += `<div class="podium-row">
      <span class="podium-rank">${rankBadge}</span>
      <span class="podium-name">${escapeHtml(item.name)}</span>
      <div class="podium-bar-track"><div class="podium-bar-fill" style="width:${pct}%"></div></div>
      <span class="podium-count">${item.count}</span>
    </div>`;
  });
  html += "</div>";
  return html;
}

export function renderLibraryPodiums(payload) {
  if (!payload || payload.total_films === 0) {
    return ""; // pas de podiums si aucun film
  }
  const cov = payload.coverage || {};
  const totalFilms = payload.total_films || 0;
  let html = '<div class="card mt-4" data-stat="library-podiums">';
  html += `<h3>🏆 Podiums de la bibliothèque</h3>`;
  html += `<p class="text-muted" style="font-size:var(--fs-xs);margin-top:0">Top sur ${totalFilms} films scannés</p>`;
  html += '<div class="podium-grid">';

  // Release Groups
  html += '<div class="podium-block">';
  html += `<h4 class="podium-title">Release Groups <span class="text-muted" style="font-size:var(--fs-xs);font-weight:normal">(${(cov.release_groups_pct ?? 0).toFixed(0)}% scene)</span></h4>`;
  html += _renderTopList(payload.release_groups, "Aucun groupe scene détecté (fichiers renommés à la main ?)");
  html += "</div>";

  // Codecs
  html += '<div class="podium-block">';
  html += `<h4 class="podium-title">Codecs <span class="text-muted" style="font-size:var(--fs-xs);font-weight:normal">(${(cov.codecs_pct ?? 0).toFixed(0)}% probés)</span></h4>`;
  html += _renderTopList(payload.codecs, "Aucun codec détecté (probe en cours ?)");
  html += "</div>";

  // Sources
  html += '<div class="podium-block">';
  html += `<h4 class="podium-title">Sources <span class="text-muted" style="font-size:var(--fs-xs);font-weight:normal">(${(cov.sources_pct ?? 0).toFixed(0)}% détectées)</span></h4>`;
  html += _renderTopList(payload.sources, "Aucune source scene détectée");
  html += "</div>";

  html += "</div>"; // /grid
  html += "</div>"; // /card
  return html;
}
