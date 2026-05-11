/* dashboard/components/sidebar-v5.js — v7.6.0 Vague 1 (ES module) — V5A-01 enrichi V1-V4
 * Version dashboard du composant sidebar v5. Parite exacte avec desktop.
 *
 * Enrichissements V5A-01 :
 *   - V3-04 : badges sidebar dynamiques (data-badge-key + updateSidebarBadges)
 *   - V3-01 : integrations toujours visibles + etat desactive (markIntegrationState)
 *   - V1-12 : bouton "A propos" dans le footer (onAboutClick)
 *   - V1-13 : badge "•" sur item Parametres si MAJ disponible (setUpdateBadge)
 *   - V1-14 : entree "Aide" dans la nav
 *   - V4-09 : aria-current="page" pour navigation (a la place de role=tab/aria-selected)
 */

import { escapeHtml } from "../core/dom.js";
import { t, onLocaleChange } from "../core/i18n.js";

const STORAGE_KEY = "cinesort.sidebar.collapsed";

// V6-02 : labels resolus dynamiquement via t() pour reactivite locale.
// On expose les ids stables; les labels sont calcules au render et
// re-render sur onLocaleChange.
export const NAV_ITEMS = [
  { id: "home",         labelKey: "sidebar.nav.home",        shortcut: "Alt+1",
    svg: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>' },
  { id: "processing",   labelKey: "sidebar.nav.processing",  shortcut: "Alt+2", badgeKey: "application",
    svg: '<polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>' },
  { id: "library",      labelKey: "sidebar.nav.library",     shortcut: "Alt+3", badgeKey: "validation",
    svg: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>' },
  // V7-fusion Phase 3 : QIJ remplace 5 items distincts (Quality, Journal,
  // Jellyfin, Plex, Radarr). Acces aux 3 sous-vues via tabs internes.
  { id: "qij",          labelKey: "sidebar.nav.qij",         shortcut: "Alt+4", badgeKey: "quality",
    svg: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>' },
  { id: "settings",     labelKey: "sidebar.nav.settings",    shortcut: "Alt+5",
    svg: '<circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 10v6M4.22 4.22l4.24 4.24m7.08 7.08l4.24 4.24M1 12h6m10 0h6M4.22 19.78l4.24-4.24m7.08-7.08l4.24-4.24"/>' },
  // V1-14 : entree Aide.
  { id: "help",         labelKey: "sidebar.nav.help",        shortcut: "Alt+6",
    svg: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>' },
];

// Compat ascendante : champ `label` resolu dynamiquement.
function _navItemLabel(item) {
  return item.labelKey ? t(item.labelKey) : (item.label || item.id);
}

function _svgIcon(pathContent) {
  return `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
}

export function isCollapsed() {
  try { return localStorage.getItem(STORAGE_KEY) === "1"; } catch (e) { return false; }
}

function setCollapsedState(collapsed) {
  try { localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0"); } catch (e) { /* noop */ }
}

function _buildItemHtml(item, active) {
  // V4-09 : aria-current="page" pour navigation (pas role=tab/aria-selected qui releve de listbox/tablist).
  const ariaCurrent = active ? 'aria-current="page"' : '';
  const label = _navItemLabel(item);
  // V3-04 : badge dynamique si l'item declare un badgeKey.
  const badge = item.badgeKey
    ? `<span class="v5-sidebar-badge" data-badge-key="${escapeHtml(item.badgeKey)}" role="status" aria-live="polite" aria-label="${escapeHtml(t("sidebar.counter_aria", { label }))}"></span>`
    : '';
  return `
    <button type="button" class="v5-sidebar-item ${active ? "is-active" : ""}"
            data-route="${escapeHtml(item.id)}"
            data-shortcut="${escapeHtml(item.shortcut)}"
            ${ariaCurrent}
            tabindex="${active ? "0" : "-1"}"
            title="${escapeHtml(t("sidebar.title_with_shortcut", { label, shortcut: item.shortcut }))}">
      <span class="v5-sidebar-icon">${_svgIcon(item.svg)}</span>
      <span class="v5-sidebar-label">${escapeHtml(label)}</span>
      <span class="v5-sidebar-shortcut">${escapeHtml(item.shortcut)}</span>
      ${badge}
    </button>
  `;
}

function _buildHtml(activeRoute, collapsed) {
  const items = NAV_ITEMS.map((it) => _buildItemHtml(it, it.id === activeRoute)).join("");
  const collapseAction = collapsed ? t("sidebar.expand") : t("sidebar.collapse");
  return `
    <aside class="v5-sidebar ${collapsed ? "is-collapsed" : ""}" data-v5-sidebar
           role="navigation" aria-label="${escapeHtml(t("sidebar.aria_label"))}">
      <div class="v5-sidebar-brand">
        <div class="v5-sidebar-logo" aria-hidden="true">CS</div>
        <div class="v5-sidebar-brand-text">
          <div class="v5-sidebar-brand-name">${escapeHtml(t("sidebar.brand_name"))}</div>
          <div class="v5-sidebar-brand-desc">${escapeHtml(t("sidebar.brand_desc"))}</div>
        </div>
      </div>
      <nav class="v5-sidebar-nav">${items}</nav>
      <div class="v5-sidebar-footer">
        <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost" data-v5-about-btn
                aria-label="${escapeHtml(t("sidebar.about_aria"))}" title="${escapeHtml(t("sidebar.about"))}">
          ${_svgIcon('<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>')}
        </button>
        <button type="button" class="v5-sidebar-collapse-btn" data-v5-collapse-btn
                aria-label="${escapeHtml(t("sidebar.collapse_expand", { action: collapseAction }))}">
          ${_svgIcon(collapsed ? '<polyline points="9 18 15 12 9 6"/>' : '<polyline points="15 18 9 12 15 6"/>')}
        </button>
      </div>
    </aside>
  `;
}

function _bindEvents(root, opts) {
  const onNavigate = typeof opts.onNavigate === "function" ? opts.onNavigate : null;
  const onAboutClick = typeof opts.onAboutClick === "function" ? opts.onAboutClick : null;

  root.querySelectorAll(".v5-sidebar-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const route = btn.dataset.route;
      if (onNavigate) onNavigate(route);
      setActive(route);
    });
    btn.addEventListener("keydown", (e) => {
      const all = Array.from(root.querySelectorAll(".v5-sidebar-item"));
      const idx = all.indexOf(btn);
      if (e.key === "ArrowDown" && idx < all.length - 1) { e.preventDefault(); all[idx + 1].focus(); }
      else if (e.key === "ArrowUp" && idx > 0) { e.preventDefault(); all[idx - 1].focus(); }
      else if (e.key === "Home") { e.preventDefault(); all[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); all[all.length - 1].focus(); }
    });
  });

  // V1-12 : bouton "A propos" cliquable.
  const aboutBtn = root.querySelector("[data-v5-about-btn]");
  if (aboutBtn && onAboutClick) aboutBtn.addEventListener("click", onAboutClick);

  const collapseBtn = root.querySelector("[data-v5-collapse-btn]");
  if (collapseBtn) collapseBtn.addEventListener("click", toggleCollapsed);
}

export function setActive(routeId) {
  const root = document.querySelector("[data-v5-sidebar]");
  if (!root) return;
  root.querySelectorAll(".v5-sidebar-item").forEach((btn) => {
    const active = btn.dataset.route === routeId;
    btn.classList.toggle("is-active", active);
    // V4-09 : aria-current pour navigation.
    if (active) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
    btn.setAttribute("tabindex", active ? "0" : "-1");
  });
}

export function toggleCollapsed() {
  const root = document.querySelector("[data-v5-sidebar]");
  if (!root) return;
  const nowCollapsed = !root.classList.contains("is-collapsed");
  root.classList.toggle("is-collapsed", nowCollapsed);
  setCollapsedState(nowCollapsed);
  const btn = root.querySelector("[data-v5-collapse-btn]");
  if (btn) {
    const action = nowCollapsed ? t("sidebar.expand") : t("sidebar.collapse");
    btn.setAttribute("aria-label", t("sidebar.collapse_expand", { action }));
  }
}

/** V3-04 — Met a jour les badges sidebar avec un mapping {key: count}. */
export function updateSidebarBadges(counters) {
  document.querySelectorAll(".v5-sidebar-badge[data-badge-key]").forEach((el) => {
    const key = el.dataset.badgeKey;
    const v = Number((counters || {})[key] || 0);
    el.textContent = v > 0 ? String(v) : "";
    el.classList.toggle("v5-sidebar-badge--active", v > 0);
  });
}

/** V3-01 — Marque un item integration comme desactive (visuel grise + redirige settings au clic). */
export function markIntegrationState(itemId, enabled, label) {
  const el = document.querySelector(`.v5-sidebar-item[data-route="${itemId}"]`);
  if (!el) return;
  el.classList.toggle("v5-sidebar-item--disabled", !enabled);
  if (!enabled) {
    el.setAttribute("title", t("sidebar.integration_disabled_title", { label }));
    el.setAttribute("aria-disabled", "true");
  } else {
    el.removeAttribute("aria-disabled");
  }
}

/** V1-13 — Affiche un badge "•" sur l'item Parametres si MAJ dispo. */
export function setUpdateBadge(itemId, available, latestVersion) {
  const el = document.querySelector(`.v5-sidebar-item[data-route="${itemId}"]`);
  if (!el) return;
  let badge = el.querySelector(".v5-sidebar-update-badge");
  if (available) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "v5-sidebar-update-badge";
      badge.textContent = "•";
      el.appendChild(badge);
    }
    badge.title = t("sidebar.update_badge_title", { version: latestVersion });
  } else {
    if (badge) badge.remove();
  }
}

// V6-02 : etat du dernier render conserve pour re-render au changement de locale.
let _lastContainer = null;
let _lastOpts = null;

export function render(container, opts = {}) {
  if (!container) return;
  _lastContainer = container;
  _lastOpts = opts;
  const activeRoute = opts.activeRoute || "home";
  const collapsed = isCollapsed();
  container.innerHTML = _buildHtml(activeRoute, collapsed);
  _bindEvents(container, opts);
}

// V6-02 : re-render automatique quand la locale change.
onLocaleChange(() => {
  if (_lastContainer && _lastContainer.isConnected) {
    render(_lastContainer, _lastOpts || {});
  }
});
