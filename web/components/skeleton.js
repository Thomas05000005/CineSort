/* components/skeleton.js — Placeholders de chargement animes (port dashboard).
 * Expose des helpers globaux (pas d'ES module cote desktop).
 */
(function () {
  "use strict";

  function skeletonLinesHtml(lines) {
    const n = Number.isFinite(+lines) ? +lines : 3;
    const widths = ["skeleton--line-md", "skeleton--line-lg", "skeleton--line-sm", "skeleton--line-md"];
    let html = '<div class="skeleton-lines">';
    for (let i = 0; i < n; i++) {
      html += `<div class="skeleton skeleton--line ${widths[i % widths.length]}"></div>`;
    }
    html += "</div>";
    return html;
  }

  function skeletonKpiGridHtml(count) {
    const n = Number.isFinite(+count) ? +count : 4;
    let html = '<div class="skeleton-grid">';
    for (let i = 0; i < n; i++) html += '<div class="skeleton skeleton--kpi"></div>';
    html += "</div>";
    return html;
  }

  function skeletonViewHtml() {
    return skeletonKpiGridHtml(4) + skeletonLinesHtml(3);
  }

  window.skeletonLinesHtml = skeletonLinesHtml;
  window.skeletonKpiGridHtml = skeletonKpiGridHtml;
  window.skeletonViewHtml = skeletonViewHtml;
})();
