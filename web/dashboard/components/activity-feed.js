/* components/activity-feed.js — Flux d'activite recente (events du dernier run).
 *
 * Reutilise les classes .activity-feed / .activity-item / .activity-icon.
 *
 * Usage :
 *   import { activityFeedHtml } from "../components/activity-feed.js";
 *   container.innerHTML = activityFeedHtml([
 *     { icon: "ok", title: "Inception (2010) • 1080p BluRay", time: "il y a 2 min" },
 *     ...
 *   ]);
 */

import { escapeHtml } from "../core/dom.js";

const _ICON_GLYPH = {
  ok:   "✓",
  warn: "!",
  err:  "✕",
  info: "i",
};

/**
 * @typedef {Object} ActivityEvent
 * @property {"ok"|"warn"|"err"|"info"} [icon] - type d'icone (defaut: info)
 * @property {string} title   - titre principal (film ou action)
 * @property {string} [time]  - horodatage relatif (ex: "il y a 2 min")
 * @property {string} [glyph] - override manuel du glyph interieur
 */

/**
 * Rend un feed d'activite.
 * @param {ActivityEvent[]} events
 * @param {object} [opts]
 * @param {string} [opts.emptyMessage] - message si aucun event
 * @returns {string} HTML
 */
export function activityFeedHtml(events, opts = {}) {
  if (!Array.isArray(events) || events.length === 0) {
    return `<p class="text-muted">${escapeHtml(opts.emptyMessage || "Aucune activite recente.")}</p>`;
  }
  const items = events.map((e) => {
    const iconKind = ["ok", "warn", "err", "info"].includes(e.icon) ? e.icon : "info";
    const glyph = escapeHtml(e.glyph || _ICON_GLYPH[iconKind]);
    const title = escapeHtml(e.title || "");
    const time = e.time ? `<div class="time">${escapeHtml(e.time)}</div>` : "";
    return `<div class="activity-item">
      <div class="activity-icon ${iconKind}">${glyph}</div>
      <div class="activity-text">
        <div class="title">${title}</div>
        ${time}
      </div>
    </div>`;
  }).join("");
  return `<div class="activity-feed">${items}</div>`;
}
