/* components/sidebar-v5.js — v7.6.0 Vague 1
 * Sidebar 240px collapsable 64px, 7 entrees principales selon sitemap v5.
 * Icones Lucide (inline SVG). Keyboard nav. State persistance localStorage.
 *
 * API publique :
 *   window.SidebarV5.render(container, opts)
 *   window.SidebarV5.setActive(routeId)
 *   window.SidebarV5.toggleCollapsed()
 *   window.SidebarV5.isCollapsed()
 *
 * Activation : cette sidebar n'est PAS montee automatiquement. Vague 2+ s'en
 * chargera (apres refonte vues). Cette version livre uniquement le composant.
 */
(function () {
  "use strict";

  const STORAGE_KEY = "cinesort.sidebar.collapsed";

  /** 7 entrees sitemap v5 (cf NOTES_RECHERCHE_v7_6_0.md A1) */
  const NAV_ITEMS = [
    {
      id: "home",
      label: "Accueil",
      shortcut: "Alt+1",
      svg: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    },
    {
      id: "processing",
      label: "Traitement",
      shortcut: "Alt+2",
      svg: '<polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    },
    {
      id: "library",
      label: "Bibliothèque",
      shortcut: "Alt+3",
      svg: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    },
    {
      id: "quality",
      label: "Qualité",
      shortcut: "Alt+4",
      svg: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    },
    {
      id: "journal",
      label: "Journal",
      shortcut: "Alt+5",
      svg: '<path d="M3 3v18h18"/><path d="M7 16l4-4 4 4 5-5"/>',
    },
    {
      id: "integrations",
      label: "Intégrations",
      shortcut: "Alt+6",
      svg: '<path d="M17 22v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 22v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    },
    {
      id: "settings",
      label: "Paramètres",
      shortcut: "Alt+7",
      svg: '<circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 10v6M4.22 4.22l4.24 4.24m7.08 7.08l4.24 4.24M1 12h6m10 0h6M4.22 19.78l4.24-4.24m7.08-7.08l4.24-4.24"/>',
    },
  ];

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function _svgIcon(pathContent) {
    return `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
  }

  function isCollapsed() {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch (e) {
      return false;
    }
  }

  function setCollapsedState(collapsed) {
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    } catch (e) { /* noop */ }
  }

  function _buildItemHtml(item, active) {
    return `
      <button
        type="button"
        class="v5-sidebar-item ${active ? "is-active" : ""}"
        data-route="${_esc(item.id)}"
        data-shortcut="${_esc(item.shortcut)}"
        role="tab"
        aria-selected="${active ? "true" : "false"}"
        tabindex="${active ? "0" : "-1"}"
        title="${_esc(item.label)} (${_esc(item.shortcut)})"
      >
        <span class="v5-sidebar-icon">${_svgIcon(item.svg)}</span>
        <span class="v5-sidebar-label">${_esc(item.label)}</span>
        <span class="v5-sidebar-shortcut">${_esc(item.shortcut)}</span>
      </button>
    `;
  }

  function _buildHtml(activeRoute, collapsed) {
    const items = NAV_ITEMS.map((it) => _buildItemHtml(it, it.id === activeRoute)).join("");
    return `
      <aside class="v5-sidebar ${collapsed ? "is-collapsed" : ""}" data-v5-sidebar
             role="navigation" aria-label="Navigation CineSort v5">
        <div class="v5-sidebar-brand">
          <div class="v5-sidebar-logo" aria-hidden="true">CS</div>
          <div class="v5-sidebar-brand-text">
            <div class="v5-sidebar-brand-name">CineSort</div>
            <div class="v5-sidebar-brand-desc">Organisation de films</div>
          </div>
        </div>

        <nav class="v5-sidebar-nav" role="tablist">
          ${items}
        </nav>

        <div class="v5-sidebar-footer">
          <button type="button" class="v5-sidebar-collapse-btn" data-v5-collapse-btn
                  aria-label="${collapsed ? "Deployer" : "Reduire"} la sidebar">
            ${_svgIcon(collapsed ? '<polyline points="9 18 15 12 9 6"/>' : '<polyline points="15 18 9 12 15 6"/>')}
          </button>
        </div>
      </aside>
    `;
  }

  function _bindEvents(root, opts) {
    const onNavigate = typeof opts.onNavigate === "function" ? opts.onNavigate : null;

    // Click sur items
    root.querySelectorAll(".v5-sidebar-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const route = btn.dataset.route;
        if (onNavigate) onNavigate(route);
        else if (typeof window.navigateTo === "function") window.navigateTo(route);
        setActive(route);
      });
      btn.addEventListener("keydown", (e) => {
        // Fleches haut/bas pour cycler
        const all = Array.from(root.querySelectorAll(".v5-sidebar-item"));
        const idx = all.indexOf(btn);
        if (e.key === "ArrowDown" && idx < all.length - 1) {
          e.preventDefault();
          all[idx + 1].focus();
        } else if (e.key === "ArrowUp" && idx > 0) {
          e.preventDefault();
          all[idx - 1].focus();
        } else if (e.key === "Home") {
          e.preventDefault();
          all[0].focus();
        } else if (e.key === "End") {
          e.preventDefault();
          all[all.length - 1].focus();
        }
      });
    });

    // Collapse button
    const collapseBtn = root.querySelector("[data-v5-collapse-btn]");
    if (collapseBtn) {
      collapseBtn.addEventListener("click", () => {
        toggleCollapsed();
      });
    }
  }

  function setActive(routeId) {
    const root = document.querySelector("[data-v5-sidebar]");
    if (!root) return;
    root.querySelectorAll(".v5-sidebar-item").forEach((btn) => {
      const active = btn.dataset.route === routeId;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
      btn.setAttribute("tabindex", active ? "0" : "-1");
    });
  }

  function toggleCollapsed() {
    const root = document.querySelector("[data-v5-sidebar]");
    if (!root) return;
    const nowCollapsed = !root.classList.contains("is-collapsed");
    root.classList.toggle("is-collapsed", nowCollapsed);
    setCollapsedState(nowCollapsed);
    const btn = root.querySelector("[data-v5-collapse-btn]");
    if (btn) btn.setAttribute("aria-label", nowCollapsed ? "Deployer la sidebar" : "Reduire la sidebar");
  }

  /**
   * Render la sidebar dans un conteneur.
   * @param {HTMLElement} container
   * @param {{ activeRoute?: string, onNavigate?: function }} opts
   */
  function render(container, opts) {
    if (!container) return;
    opts = opts || {};
    const activeRoute = opts.activeRoute || "home";
    const collapsed = isCollapsed();
    container.innerHTML = _buildHtml(activeRoute, collapsed);
    _bindEvents(container, opts);
  }

  window.SidebarV5 = {
    render,
    setActive,
    toggleCollapsed,
    isCollapsed,
    NAV_ITEMS,
  };
})();
