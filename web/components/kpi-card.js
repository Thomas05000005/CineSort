/* components/kpi-card.js — Carte KPI avec icone, valeur, tendance (port dashboard).
 * Expose des helpers globaux desktop.
 */
(function () {
  "use strict";

  function _esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  const _ICONS = {
    film:     '<svg viewBox="0 0 24 24" width="20" height="20"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/><line x1="17" y1="17" x2="22" y2="17"/></svg>',
    star:     '<svg viewBox="0 0 24 24" width="20" height="20"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
    award:    '<svg viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/></svg>',
    activity: '<svg viewBox="0 0 24 24" width="20" height="20"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    clock:    '<svg viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    check:    '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    tool:     '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    server:   '<svg viewBox="0 0 24 24" width="20" height="20"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
    folder:   '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  };

  const _TREND = {
    up:     '<span class="kpi-trend kpi-trend-up" title="En hausse">↑</span>',
    down:   '<span class="kpi-trend kpi-trend-down" title="En baisse">↓</span>',
    stable: '<span class="kpi-trend kpi-trend-stable" title="Stable">→</span>',
  };

  function kpiCardHtml(cfg) {
    cfg = cfg || {};
    const icon = _ICONS[cfg.icon] || "";
    const label = _esc(cfg.label || "");
    const value = _esc(String(cfg.value == null ? "—" : cfg.value));
    const suffix = cfg.suffix ? `<span class="kpi-suffix">${_esc(cfg.suffix)}</span>` : "";
    const trend = _TREND[cfg.trend] || "";
    const borderColor = cfg.color || "var(--accent)";
    const heroCls = cfg.hero ? " kpi-card--hero" : "";
    let sparkline = "";
    if (cfg.hero && Array.isArray(cfg.sparkline) && cfg.sparkline.length >= 2) {
      // Prefere la fonction globale si dispo, sinon fallback vide.
      const svg = (typeof window.sparklineSvg === "function")
        ? window.sparklineSvg(cfg.sparkline, { w: 140, h: 32, color: borderColor })
        : "";
      sparkline = svg ? `<div class="kpi-sparkline">${svg}</div>` : "";
    }
    const subtitle = cfg.subtitle ? `<div class="kpi-subtitle">${_esc(cfg.subtitle)}</div>` : "";
    return `<div class="kpi-card${heroCls}" style="border-left-color:${borderColor}">
      <div class="kpi-header">
        <span class="kpi-icon">${icon}</span>
        <span class="kpi-label">${label}</span>
      </div>
      <div class="kpi-value">${value}${suffix} ${trend}</div>
      ${subtitle}
      ${sparkline}
    </div>`;
  }

  function kpiGridHtml(cards) {
    const list = Array.isArray(cards) ? cards : [];
    const gridCls = list[0] && list[0].hero ? "kpi-grid kpi-grid--hero" : "kpi-grid";
    return `<div class="${gridCls}">${list.map(kpiCardHtml).join("")}</div>`;
  }

  window.kpiCardHtml = kpiCardHtml;
  window.kpiGridHtml = kpiGridHtml;
})();
