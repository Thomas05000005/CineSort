/* components/skeleton.js — Placeholders de chargement animes (D1) */

/**
 * HTML d'un placeholder texte multi-lignes.
 * @param {number} lines - nombre de lignes (defaut 3)
 */
export function skeletonLinesHtml(lines = 3) {
  const widths = ["skeleton--line-md", "skeleton--line-lg", "skeleton--line-sm", "skeleton--line-md"];
  let html = "<div>";
  for (let i = 0; i < lines; i++) {
    html += `<div class="skeleton skeleton--line ${widths[i % widths.length]}"></div>`;
  }
  html += "</div>";
  return html;
}

/**
 * HTML d'une grille de N cartes KPI pulsantes.
 * @param {number} count - nombre de KPIs (defaut 4)
 */
export function skeletonKpiGridHtml(count = 4) {
  let html = '<div class="skeleton-grid">';
  for (let i = 0; i < count; i++) html += '<div class="skeleton skeleton--kpi"></div>';
  html += "</div>";
  return html;
}

/**
 * HTML d'un bloc cards generique (KPI + quelques lignes).
 */
export function skeletonViewHtml() {
  return skeletonKpiGridHtml(4) + skeletonLinesHtml(3);
}
