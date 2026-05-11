/* dashboard/components/breadcrumb.js — v7.6.0 Vague 1 (ES module) */

import { escapeHtml } from "../core/dom.js";

const CHEVRON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';

function _buildHtml(items) {
  if (!Array.isArray(items) || items.length === 0) return "";
  const parts = [];
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const isLast = i === items.length - 1;
    if (isLast || !it.route) {
      parts.push(`
        <span class="v5-breadcrumb-current" aria-current="${isLast ? "page" : "false"}">
          ${escapeHtml(it.label)}
        </span>
      `);
    } else {
      parts.push(`
        <a class="v5-breadcrumb-link" href="#${escapeHtml(it.route)}" data-route="${escapeHtml(it.route)}">
          ${escapeHtml(it.label)}
        </a>
      `);
    }
    if (!isLast) parts.push(`<span class="v5-breadcrumb-sep" aria-hidden="true">${CHEVRON}</span>`);
  }
  return `<nav class="v5-breadcrumb" data-v5-breadcrumb aria-label="Fil d'Ariane">${parts.join("")}</nav>`;
}

export function render(container, items, opts = {}) {
  if (!container) return;
  container.innerHTML = _buildHtml(items);
  const onNavigate = typeof opts.onNavigate === "function" ? opts.onNavigate : null;
  container.querySelectorAll(".v5-breadcrumb-link").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const route = link.dataset.route;
      if (onNavigate) onNavigate(route);
      else window.location.hash = route;
    });
  });
}
