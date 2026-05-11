/* components/home-widgets.js — v7.6.0 Vague 2
 * Widgets de la Home overview-first :
 *   - KpiGrid  : 5 cards KPI en grid avec stagger animation
 *   - InsightCard : card insight actionnable (severity + count + filter_hint)
 *   - PosterCarousel : bandeau horizontal posters TMDb
 *
 * API publique :
 *   window.HomeWidgets.renderKpiGrid(container, kpis)
 *   window.HomeWidgets.renderInsights(container, insights, onActionCallback)
 *   window.HomeWidgets.renderPosterCarousel(container, items)
 */
(function () {
  "use strict";

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function _svg(pathContent, size) {
    const s = size || 18;
    return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
  }

  const ICONS = {
    "activity":       '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "alert-triangle": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "alert-circle":   '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
    "film":           '<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>',
    "award":          '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
    "bar-chart":      '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "trend-up":       '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
    "trend-down":     '<polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/>',
    "check":          '<polyline points="20 6 9 17 4 12"/>',
    "x":              '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "library":        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  };

  function _icon(name, size) {
    return _svg(ICONS[name] || ICONS["alert-circle"], size || 18);
  }

  /* ===========================================================
   * KPI Grid
   * =========================================================== */

  /**
   * Render KPI grid.
   * @param {HTMLElement} container
   * @param {Array<{ id, label, value, trend?, suffix?, icon?, tier? }>} kpis
   */
  function renderKpiGrid(container, kpis) {
    if (!container) return;
    if (!Array.isArray(kpis) || kpis.length === 0) {
      container.innerHTML = "";
      return;
    }
    let html = '<div class="v5-kpi-grid" role="list">';
    kpis.forEach((k, idx) => {
      const trendHtml = _renderTrend(k.trend);
      const tierClass = k.tier ? `v5-kpi-card--tier-${_esc(k.tier)}` : "";
      const suffix = k.suffix ? `<span class="v5-kpi-suffix">${_esc(k.suffix)}</span>` : "";
      const iconHtml = k.icon ? `<div class="v5-kpi-icon">${_icon(k.icon, 20)}</div>` : "";
      html += `
        <article class="v5-kpi-card ${tierClass} stagger-item" role="listitem" style="--order: ${idx}">
          <header class="v5-kpi-header">
            ${iconHtml}
            <span class="v5-kpi-label">${_esc(k.label)}</span>
          </header>
          <div class="v5-kpi-body">
            <span class="v5-kpi-value v5u-tabular-nums">${_esc(k.value)}</span>${suffix}
            ${trendHtml}
          </div>
        </article>
      `;
    });
    html += "</div>";
    container.innerHTML = html;
  }

  function _renderTrend(trend) {
    if (!trend) return "";
    const val = String(trend).trim();
    if (!val) return "";
    let cls = "v5-kpi-trend v5-kpi-trend--flat";
    let icon = "";
    if (val.startsWith("↑") || val.startsWith("+") || /^trend_up/.test(val)) {
      cls = "v5-kpi-trend v5-kpi-trend--up";
      icon = _icon("trend-up", 12);
    } else if (val.startsWith("↓") || val.startsWith("-") || /^trend_down/.test(val)) {
      cls = "v5-kpi-trend v5-kpi-trend--down";
      icon = _icon("trend-down", 12);
    }
    return `<span class="${cls}">${icon}<span>${_esc(val)}</span></span>`;
  }

  /* ===========================================================
   * Insight Cards
   * =========================================================== */

  /**
   * Render insights list.
   * @param {HTMLElement} container
   * @param {Array<{ type, severity, count, label, filter_hint?, icon? }>} insights
   * @param {function} onAction - callback(insight) quand "Voir" est clique
   */
  function renderInsights(container, insights, onAction) {
    if (!container) return;
    if (!Array.isArray(insights) || insights.length === 0) {
      container.innerHTML = `<div class="v5-insight-empty">Aucune alerte. Tout va bien.</div>`;
      return;
    }
    const cards = insights.map((it, idx) => _insightCardHtml(it, idx)).join("");
    container.innerHTML = `<div class="v5-insight-list" role="list">${cards}</div>`;

    container.querySelectorAll("[data-insight-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.dataset.insightAction);
        const it = insights[idx];
        if (it && typeof onAction === "function") onAction(it);
      });
    });
    container.querySelectorAll("[data-insight-dismiss]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".v5-insight-card");
        if (card) card.classList.add("is-dismissed");
      });
    });
  }

  function _insightCardHtml(it, idx) {
    const sev = String(it.severity || "info").toLowerCase();
    const icon = _icon(it.icon || "alert-circle", 16);
    const canAction = !!it.filter_hint;
    return `
      <article class="v5-insight-card v5-insight-card--${_esc(sev)} stagger-item"
               role="listitem" style="--order: ${idx}"
               data-insight-type="${_esc(it.type)}">
        <span class="v5-insight-icon">${icon}</span>
        <span class="v5-insight-label">${_esc(it.label)}</span>
        <div class="v5-insight-actions">
          ${canAction ? `<button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-insight-action="${idx}">Voir</button>` : ""}
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost v5-btn--icon"
                  data-insight-dismiss="${idx}"
                  aria-label="Masquer cette alerte">${_icon("x", 14)}</button>
        </div>
      </article>
    `;
  }

  /* ===========================================================
   * Poster Carousel
   * =========================================================== */

  /**
   * Render poster carousel (recent additions).
   * @param {HTMLElement} container
   * @param {Array<{ row_id, title, year, poster_url?, tier, score }>} items
   */
  function renderPosterCarousel(container, items) {
    if (!container) return;
    if (!Array.isArray(items) || items.length === 0) {
      container.innerHTML = `<div class="v5-poster-empty">Aucun film recent.</div>`;
      return;
    }
    const cards = items.map((it, idx) => _posterCardHtml(it, idx)).join("");
    container.innerHTML = `<div class="v5-poster-carousel v5-scroll" role="list">${cards}</div>`;

    container.querySelectorAll("[data-poster-film]").forEach((card) => {
      card.addEventListener("click", () => {
        const rowId = card.dataset.posterFilm;
        if (typeof window.navigateTo === "function") window.navigateTo("film/" + rowId);
        else window.location.hash = "film/" + rowId;
      });
    });
  }

  function _posterCardHtml(it, idx) {
    const tier = String(it.tier || "unknown").toLowerCase();
    const score = it.score != null ? Math.round(Number(it.score)) : "?";
    const year = it.year ? ` (${_esc(it.year)})` : "";
    const posterStyle = it.poster_url
      ? `background-image: url('${_esc(it.poster_url)}')`
      : "";
    return `
      <article class="v5-poster-card stagger-item" role="listitem"
               style="--order: ${idx}"
               data-poster-film="${_esc(it.row_id || "")}"
               tabindex="0"
               aria-label="${_esc(it.title || "Film")} ${_esc(year)}, score ${_esc(score)}">
        <div class="v5-poster-image" style="${posterStyle}">
          ${!it.poster_url ? `<div class="v5-poster-placeholder">${_icon("film", 32)}</div>` : ""}
        </div>
        <div class="v5-poster-meta">
          <div class="v5-poster-title v5u-truncate">${_esc(it.title || "?")}${year}</div>
          <div class="v5-poster-score">
            <span class="v5-badge v5-badge--tier-${_esc(tier)}">${_esc(score)}</span>
          </div>
        </div>
      </article>
    `;
  }

  window.HomeWidgets = {
    renderKpiGrid,
    renderInsights,
    renderPosterCarousel,
  };
})();
