/* components/sparkline.js — Mini-courbe SVG inline (I12)
 *
 * Pur SVG, pas de dependance. Couleur degrade selon direction finale.
 * Usage :
 *   sparklineSvg([10, 25, 20, 30, 50], { w: 80, h: 24 })
 *   -> "<svg ...><polyline ...></svg>"
 */

/**
 * Genere un sparkline SVG inline.
 * @param {number[]} values - serie de valeurs numeriques (ordre chronologique).
 * @param {object} opts
 * @param {number} [opts.w=80] - largeur en px.
 * @param {number} [opts.h=24] - hauteur en px.
 * @param {string} [opts.color] - couleur CSS (override auto).
 * @param {boolean} [opts.fill=true] - remplit sous la courbe avec un gradient.
 * @param {boolean} [opts.dotLast=true] - affiche un cercle sur le dernier point.
 * @returns {string} markup SVG pret a injecter.
 */
function sparklineSvg(values, opts = {}) {
  const w = Number(opts.w) || 80;
  const h = Number(opts.h) || 24;
  const fill = opts.fill !== false;
  const dotLast = opts.dotLast !== false;
  const pad = 2;

  const vals = (values || []).filter((v) => Number.isFinite(Number(v))).map(Number);
  if (vals.length < 2) {
    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><line x1="${pad}" y1="${h / 2}" x2="${w - pad}" y2="${h / 2}" stroke="var(--text-muted)" stroke-width="1" stroke-dasharray="2 3"/></svg>`;
  }

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const dx = (w - 2 * pad) / (vals.length - 1);

  const points = vals.map((v, i) => {
    const x = pad + i * dx;
    const y = h - pad - ((v - min) / range) * (h - 2 * pad);
    return { x: +x.toFixed(2), y: +y.toFixed(2) };
  });

  /* Couleur auto selon direction finale */
  let color = opts.color;
  if (!color) {
    const first = vals[0];
    const last = vals[vals.length - 1];
    if (last > first * 1.05) color = "var(--success, #34D399)";
    else if (last < first * 0.95) color = "var(--danger, #F87171)";
    else color = "var(--accent, #60A5FA)";
  }

  const polyline = points.map((p) => `${p.x},${p.y}`).join(" ");
  const areaPath = fill
    ? `<path d="M ${points[0].x},${h} L ${polyline.split(" ").join(" L ")} L ${points[points.length - 1].x},${h} Z" fill="${color}" opacity="0.15"/>`
    : "";
  const dot = dotLast
    ? `<circle cx="${points[points.length - 1].x}" cy="${points[points.length - 1].y}" r="2" fill="${color}"/>`
    : "";

  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true" preserveAspectRatio="none">${areaPath}<polyline points="${polyline}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>${dot}</svg>`;
}

/* Version globale pour le desktop (scripts non-module). */
if (typeof window !== "undefined") {
  window.sparklineSvg = sparklineSvg;
}
