/* components/home-charts.js — v7.6.0 Vague 2
 * Charts SVG de la Home :
 *   - DonutChart : distribution 5 tiers (Platinum/Gold/Silver/Bronze/Reject)
 *   - LineChart  : tendance score moyen 30 derniers jours
 *
 * API publique :
 *   window.HomeCharts.renderDonut(container, data)
 *   window.HomeCharts.renderLine(container, points)
 */
(function () {
  "use strict";

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  const TIER_COLORS = {
    platinum: "var(--tier-platinum-solid)",
    gold:     "var(--tier-gold-solid)",
    silver:   "var(--tier-silver-solid)",
    bronze:   "var(--tier-bronze-solid)",
    reject:   "var(--tier-reject-solid)",
    unknown:  "var(--tier-unknown-solid)",
  };

  const TIER_LABELS = {
    platinum: "Platinum",
    gold:     "Gold",
    silver:   "Silver",
    bronze:   "Bronze",
    reject:   "Reject",
    unknown:  "Indetermine",
  };

  /* ===========================================================
   * Donut chart — distribution tiers
   * =========================================================== */

  /**
   * @param {HTMLElement} container
   * @param {{ counts: Object<string, number>, percentages: Object<string, number>, total: number }} data
   */
  function renderDonut(container, data) {
    if (!container) return;
    if (!data || !data.counts) {
      container.innerHTML = `<div class="v5-chart-empty">Aucune donnée.</div>`;
      return;
    }
    const counts = data.counts;
    const total = Number(data.scored_total || data.total || 0);
    if (total === 0) {
      container.innerHTML = `<div class="v5-chart-empty">Aucun film classe.</div>`;
      return;
    }

    const size = 180;
    const cx = size / 2;
    const cy = size / 2;
    const r = 70;
    const stroke = 22;

    // Ordre des tiers (visuel : platinum en haut)
    const order = ["platinum", "gold", "silver", "bronze", "reject"];
    let cumulativeAngle = -Math.PI / 2;  // start top
    const arcs = [];

    for (const tier of order) {
      const count = Number(counts[tier] || 0);
      if (count === 0) continue;
      const sweep = (count / total) * 2 * Math.PI;
      const start = cumulativeAngle;
      const end = cumulativeAngle + sweep;
      const largeArc = sweep > Math.PI ? 1 : 0;
      const x1 = cx + r * Math.cos(start);
      const y1 = cy + r * Math.sin(start);
      const x2 = cx + r * Math.cos(end);
      const y2 = cy + r * Math.sin(end);
      const d = `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
      arcs.push({
        tier,
        d,
        color: TIER_COLORS[tier],
        pct: Number(data.percentages?.[tier] || 0),
        count,
      });
      cumulativeAngle = end;
    }

    const arcsSvg = arcs.map((a) => `
      <path class="v5-donut-arc" d="${a.d}"
            stroke="${a.color}" stroke-width="${stroke}" fill="none"
            stroke-linecap="butt"
            data-tier="${_esc(a.tier)}"
            data-count="${a.count}" data-pct="${a.pct}">
        <title>${_esc(TIER_LABELS[a.tier])} : ${a.count} (${a.pct.toFixed(1)}%)</title>
      </path>
    `).join("");

    const legend = arcs.map((a) => `
      <li class="v5-donut-legend-item">
        <span class="v5-donut-legend-swatch" style="background: ${a.color}"></span>
        <span class="v5-donut-legend-label">${_esc(TIER_LABELS[a.tier])}</span>
        <span class="v5-donut-legend-value v5u-tabular-nums">${a.count} <span class="v5u-text-muted">(${a.pct.toFixed(0)}%)</span></span>
      </li>
    `).join("");

    container.innerHTML = `
      <div class="v5-donut-wrap">
        <svg class="v5-donut-svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"
             role="img" aria-label="Distribution tiers qualite">
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
                  stroke="var(--surface-2)" stroke-width="${stroke}"/>
          ${arcsSvg}
          <text x="${cx}" y="${cy - 4}" text-anchor="middle" class="v5-donut-total">${total}</text>
          <text x="${cx}" y="${cy + 14}" text-anchor="middle" class="v5-donut-total-label">films</text>
        </svg>
        <ul class="v5-donut-legend" role="list">${legend}</ul>
      </div>
    `;
  }

  /* ===========================================================
   * Line chart — tendance 30 jours
   * =========================================================== */

  /**
   * @param {HTMLElement} container
   * @param {Array<{ date, avg_score, count }>} points
   */
  function renderLine(container, points) {
    if (!container) return;
    if (!Array.isArray(points) || points.length === 0) {
      container.innerHTML = `<div class="v5-chart-empty">Pas assez de données.</div>`;
      return;
    }

    const w = 560;
    const h = 160;
    const padX = 32;
    const padY = 20;
    const valid = points.map((p) => (p.avg_score != null ? Number(p.avg_score) : null));
    const scored = valid.filter((v) => v != null);
    if (scored.length < 2) {
      container.innerHTML = `<div class="v5-chart-empty">Trop peu de points (${scored.length}).</div>`;
      return;
    }

    const minScore = Math.max(0, Math.min(...scored) - 5);
    const maxScore = Math.min(100, Math.max(...scored) + 5);
    const range = Math.max(1, maxScore - minScore);

    // Coordonnees
    const coords = points.map((p, i) => {
      if (p.avg_score == null) return null;
      const x = padX + (i / (points.length - 1)) * (w - 2 * padX);
      const y = padY + (1 - (p.avg_score - minScore) / range) * (h - 2 * padY);
      return { x, y, score: p.avg_score, date: p.date, count: p.count };
    });

    // Polyline : joint uniquement les points valides consecutifs
    const path = _buildSmoothPath(coords);

    // Zone colorée sous la courbe
    const fillPath = _buildAreaPath(coords, h - padY);

    // Points (cercles)
    const dots = coords.filter(Boolean).map((c) => `
      <circle class="v5-line-dot" cx="${c.x.toFixed(2)}" cy="${c.y.toFixed(2)}" r="3"
              data-date="${_esc(c.date)}" data-score="${c.score}">
        <title>${_esc(c.date)} : score ${c.score} (${c.count} films)</title>
      </circle>
    `).join("");

    // Axes
    const yTicks = [minScore, (minScore + maxScore) / 2, maxScore].map((v) => {
      const y = padY + (1 - (v - minScore) / range) * (h - 2 * padY);
      return `<text class="v5-line-axis-label" x="4" y="${y.toFixed(2)}" dominant-baseline="middle">${Math.round(v)}</text>`;
    }).join("");

    const first = points[0]?.date || "";
    const last = points[points.length - 1]?.date || "";

    // Delta
    const firstScored = scored[0];
    const lastScored = scored[scored.length - 1];
    const delta = lastScored - firstScored;
    const deltaClass = delta > 0 ? "v5-line-delta--up" : (delta < 0 ? "v5-line-delta--down" : "v5-line-delta--flat");
    const deltaLabel = (delta > 0 ? "+" : "") + delta.toFixed(1) + " pts";

    container.innerHTML = `
      <div class="v5-line-wrap">
        <div class="v5-line-header">
          <span class="v5-line-title">Score moyen (30j)</span>
          <span class="v5-line-delta ${deltaClass}">${deltaLabel}</span>
        </div>
        <svg class="v5-line-svg" viewBox="0 0 ${w} ${h}" width="100%" height="${h}"
             role="img" aria-label="Tendance score moyen 30 derniers jours">
          <defs>
            <linearGradient id="v5LineGradient" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.35"/>
              <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
            </linearGradient>
          </defs>
          ${yTicks}
          <path class="v5-line-fill" d="${fillPath}" fill="url(#v5LineGradient)"/>
          <path class="v5-line-path" d="${path}" fill="none"
                stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          ${dots}
        </svg>
        <div class="v5-line-footer">
          <span>${_esc(first)}</span>
          <span>${_esc(last)}</span>
        </div>
      </div>
    `;
  }

  function _buildSmoothPath(coords) {
    let path = "";
    let started = false;
    coords.forEach((c) => {
      if (!c) {
        started = false;
        return;
      }
      if (!started) {
        path += `M ${c.x.toFixed(2)} ${c.y.toFixed(2)}`;
        started = true;
      } else {
        path += ` L ${c.x.toFixed(2)} ${c.y.toFixed(2)}`;
      }
    });
    return path;
  }

  function _buildAreaPath(coords, yBase) {
    const valid = coords.filter(Boolean);
    if (valid.length < 2) return "";
    let p = `M ${valid[0].x.toFixed(2)} ${yBase.toFixed(2)}`;
    valid.forEach((c) => { p += ` L ${c.x.toFixed(2)} ${c.y.toFixed(2)}`; });
    p += ` L ${valid[valid.length - 1].x.toFixed(2)} ${yBase.toFixed(2)} Z`;
    return p;
  }

  window.HomeCharts = {
    renderDonut,
    renderLine,
  };
})();
