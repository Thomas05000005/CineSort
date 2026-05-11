/* components/kpi-card.js — Carte KPI V6 (glass natif, ring SVG, gradient text, heroLayout)
 *
 * API compatible retrocompatible :
 *   - kpiCardHtml({ icon, label, value, trend, color, suffix, hero, sparkline, subtitle })
 *
 * API V6 enrichie :
 *   - kpiCardHtml({ ..., heroLayout: true })       → layout flex mockup (56px + meta + ring)
 *   - kpiCardHtml({ ..., gradientText: true })     → valeur en text gradient
 *   - kpiCardHtml({ ..., ring: { value, max, label } }) → ring SVG progress a droite
 *   - kpiCardHtml({ ..., meta: [{ v, l, pos|neg }] }) → meta items style hero
 */

import { escapeHtml } from "../core/dom.js";
import { sparklineSvg } from "./sparkline.js";

/* Icones SVG Lucide inline pour les KPIs */
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

/* Fleches tendance */
const _TREND = {
  up:     '<span class="kpi-trend kpi-trend-up" title="En hausse">↑</span>',
  down:   '<span class="kpi-trend kpi-trend-down" title="En baisse">↓</span>',
  stable: '<span class="kpi-trend kpi-trend-stable" title="Stable">→</span>',
};

/** Rend un ring SVG progress circulaire. value/max in [0..max]. */
function _ringSvg(ring) {
  const value = Math.max(0, Math.min(Number(ring.value || 0), Number(ring.max || 100)));
  const max = Number(ring.max || 100);
  const pct = max > 0 ? value / max : 0;
  const circumference = 2 * Math.PI * 60;
  const offset = circumference * (1 - pct);
  const label = ring.label != null ? escapeHtml(String(ring.label)) : `${Math.round(pct * 100)}%`;
  return `<div class="ring" aria-label="Progression ${label}">
    <svg width="140" height="140" viewBox="0 0 140 140">
      <circle cx="70" cy="70" r="60" class="ring-track"/>
      <circle cx="70" cy="70" r="60" class="ring-fill"
              stroke-dasharray="${circumference.toFixed(2)}"
              stroke-dashoffset="${offset.toFixed(2)}"/>
    </svg>
    <div class="ring-label">
      <strong>${label}</strong>
      <small>${escapeHtml(ring.sublabel || "progression")}</small>
    </div>
  </div>`;
}

/** Rend les meta items (hero layout). */
function _metaItemsHtml(meta) {
  if (!Array.isArray(meta) || meta.length === 0) return "";
  return `<div class="hero-meta">${meta.map((m) => {
    const cls = m.pos ? "v pos" : m.neg ? "v neg" : "v";
    return `<div class="meta-item"><span class="${cls}">${escapeHtml(String(m.v ?? "—"))}</span><span class="l">${escapeHtml(String(m.l ?? ""))}</span></div>`;
  }).join("")}</div>`;
}

/**
 * Genere le HTML d'une carte KPI.
 * @param {object} cfg
 * @param {string} cfg.icon    - cle dans _ICONS (film, star, award, etc.)
 * @param {string} cfg.label   - libelle du KPI
 * @param {string|number} cfg.value - valeur affichee
 * @param {string} [cfg.trend] - "up", "down", "stable" ou absent
 * @param {string} [cfg.color] - couleur CSS de la bordure gauche (defaut: accent)
 * @param {string} [cfg.suffix] - suffixe apres la valeur (%, pts, etc.)
 * @param {boolean} [cfg.hero] - mode hero (legacy, agrandit valeur + sparkline)
 * @param {boolean} [cfg.heroLayout] - V6 : layout flex hero-content (valeur 56px + meta + ring)
 * @param {boolean} [cfg.gradientText] - V6 : valeur en text gradient accent
 * @param {object} [cfg.ring] - V6 : { value, max, label, sublabel } pour ring SVG
 * @param {object[]} [cfg.meta] - V6 : [{ v, l, pos|neg }] meta items
 * @param {string} [cfg.heroLabel] - V6 : label discret au-dessus de la valeur hero
 * @returns {string} HTML
 */
export function kpiCardHtml(cfg) {
  const icon = _ICONS[cfg.icon] || "";
  const label = escapeHtml(cfg.label || "");
  const value = escapeHtml(String(cfg.value ?? "—"));
  const suffix = cfg.suffix ? `<span class="kpi-suffix">${escapeHtml(cfg.suffix)}</span>` : "";
  const trend = _TREND[cfg.trend] || "";
  const borderColor = cfg.color || "var(--accent)";
  const heroCls = cfg.hero ? " kpi-card--hero" : "";

  /* --- V6 : heroLayout mockup-style --- */
  if (cfg.heroLayout) {
    const heroLabel = cfg.heroLabel ? `<div class="hero-label">${escapeHtml(cfg.heroLabel)}</div>` : "";
    const valueCls = cfg.gradientText ? "hero-value" : "hero-value hero-value--solid";
    const metaHtml = _metaItemsHtml(cfg.meta);
    const ringHtml = cfg.ring ? _ringSvg(cfg.ring) : "";
    const extra = cfg.cardClass ? ` ${escapeHtml(cfg.cardClass)}` : "";
    // Workflow strip (5 etapes cliquables)
    let workflowHtml = "";
    if (Array.isArray(cfg.workflowSteps) && cfg.workflowSteps.length) {
      workflowHtml = `<div class="workflow-strip">${cfg.workflowSteps.map((s) => {
        const state = s.state || "";
        const cls = ["workflow-step"];
        if (state === "done") cls.push("done");
        if (state === "active") cls.push("active");
        const href = s.href ? ` data-nav-route="${escapeHtml(s.href)}"` : "";
        return `<div class="${cls.join(" ")}"${href}>${escapeHtml(s.label)}</div>`;
      }).join("")}</div>`;
    }
    return `<div class="kpi-card kpi-card--hero${extra}" style="border-left-color:${borderColor}">
      <h3><span class="live-dot"></span> ${label}</h3>
      <div class="hero-content">
        <div class="hero-primary">
          ${heroLabel}
          <div class="${valueCls}">${value}${suffix}</div>
          ${metaHtml}
        </div>
        ${ringHtml}
      </div>
      ${workflowHtml}
    </div>`;
  }

  /* --- Legacy : hero sparkline --- */
  const sparkline = (cfg.hero && Array.isArray(cfg.sparkline) && cfg.sparkline.length >= 2)
    ? `<div class="kpi-sparkline">${sparklineSvg(cfg.sparkline, { w: 140, h: 32, color: borderColor })}</div>`
    : "";
  const subtitle = cfg.subtitle ? `<div class="kpi-subtitle">${escapeHtml(cfg.subtitle)}</div>` : "";
  const valueCls = cfg.gradientText ? "kpi-value kpi-value--gradient" : "kpi-value";

  return `<div class="kpi-card${heroCls}" style="border-left-color:${borderColor}">
    <div class="kpi-header">
      <span class="kpi-icon">${icon}</span>
      <span class="kpi-label">${label}</span>
    </div>
    <div class="${valueCls}">${value}${suffix} ${trend}</div>
    ${subtitle}
    ${sparkline}
  </div>`;
}

/**
 * Genere le HTML d'une grille de KPIs. Si la 1ere carte est `hero`, la grille
 * bascule en layout F-pattern (2fr 1fr 1fr 1fr).
 * @param {object[]} cards - tableau de configs kpiCardHtml
 * @returns {string} HTML
 */
export function kpiGridHtml(cards) {
  const gridCls = cards[0] && cards[0].hero ? "kpi-grid kpi-grid--hero" : "kpi-grid";
  return `<div class="${gridCls}">${cards.map(kpiCardHtml).join("")}</div>`;
}
