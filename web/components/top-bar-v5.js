/* components/top-bar-v5.js — v7.6.0 Vague 1
 * Top bar : search trigger (Cmd+K) + notifications bell + theme switch.
 * Icones Lucide inline SVG.
 *
 * API publique :
 *   window.TopBarV5.render(container, opts)
 *   window.TopBarV5.setNotificationCount(n)
 *   window.TopBarV5.setTheme(theme)  // studio | cinema | luxe | neon
 */
(function () {
  "use strict";

  const THEMES = [
    { id: "studio", label: "Studio" },
    { id: "cinema", label: "Cinema" },
    { id: "luxe",   label: "Luxe" },
    { id: "neon",   label: "Neon" },
  ];

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function _svg(pathContent, size) {
    const s = size || 18;
    return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
  }

  const ICON_SEARCH = _svg('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>');
  const ICON_BELL   = _svg('<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>');
  const ICON_SUN    = _svg('<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>', 18);

  function _buildHtml(opts) {
    const title = opts.title || "";
    const subtitle = opts.subtitle || "";
    const currentTheme = opts.theme || "studio";
    const notifCount = Number(opts.notificationCount) || 0;

    return `
      <div class="v5-top-bar" data-v5-top-bar role="banner">
        <div class="v5-top-bar-title">
          <div class="v5-top-bar-title-main">${_esc(title)}</div>
          ${subtitle ? `<div class="v5-top-bar-title-sub">${_esc(subtitle)}</div>` : ""}
        </div>

        <div class="v5-top-bar-actions">
          <button type="button" class="v5-top-bar-search" data-v5-search-trigger
                  aria-label="Ouvrir la recherche (Cmd+K)"
                  title="Rechercher ou executer une action">
            <span class="v5-top-bar-search-icon">${ICON_SEARCH}</span>
            <span class="v5-top-bar-search-label">Rechercher...</span>
            <kbd class="v5-top-bar-search-shortcut">Cmd+K</kbd>
          </button>

          <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost"
                  data-v5-notif-trigger
                  aria-label="Notifications (${notifCount} non lues)">
            <span class="v5-top-bar-notif-wrap">
              ${ICON_BELL}
              ${notifCount > 0 ? `<span class="v5-top-bar-notif-badge" data-v5-notif-badge>${notifCount > 99 ? "99+" : notifCount}</span>` : ""}
            </span>
          </button>

          <div class="v5-top-bar-theme-wrap">
            <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost"
                    data-v5-theme-trigger
                    aria-label="Changer de theme"
                    aria-haspopup="menu">
              ${ICON_SUN}
            </button>
            <div class="v5-top-bar-theme-menu" data-v5-theme-menu role="menu" aria-hidden="true">
              ${THEMES.map((t) => `
                <button type="button"
                        class="v5-top-bar-theme-item ${t.id === currentTheme ? "is-active" : ""}"
                        data-theme="${_esc(t.id)}"
                        role="menuitemradio"
                        aria-checked="${t.id === currentTheme ? "true" : "false"}">
                  ${_esc(t.label)}
                </button>
              `).join("")}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function _bindEvents(root, opts) {
    // Search trigger
    const searchBtn = root.querySelector("[data-v5-search-trigger]");
    if (searchBtn) {
      searchBtn.addEventListener("click", () => {
        if (typeof opts.onSearchClick === "function") opts.onSearchClick();
        else if (window.CommandPalette && typeof window.CommandPalette.open === "function") {
          window.CommandPalette.open();
        }
      });
    }

    // Notif trigger — v7.6.0 Vague 9 : ouvre le NotificationCenter par defaut
    const notifBtn = root.querySelector("[data-v5-notif-trigger]");
    if (notifBtn) {
      notifBtn.addEventListener("click", () => {
        if (typeof opts.onNotifClick === "function") {
          opts.onNotifClick();
          return;
        }
        if (window.NotificationCenter && typeof window.NotificationCenter.toggle === "function") {
          window.NotificationCenter.toggle();
        }
      });
    }

    // Theme dropdown
    const themeBtn = root.querySelector("[data-v5-theme-trigger]");
    const themeMenu = root.querySelector("[data-v5-theme-menu]");
    if (themeBtn && themeMenu) {
      themeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = themeMenu.classList.toggle("is-open");
        themeMenu.setAttribute("aria-hidden", isOpen ? "false" : "true");
      });
      themeMenu.querySelectorAll("[data-theme]").forEach((item) => {
        item.addEventListener("click", () => {
          const theme = item.dataset.theme;
          setTheme(theme);
          if (typeof opts.onThemeChange === "function") opts.onThemeChange(theme);
          themeMenu.classList.remove("is-open");
          themeMenu.setAttribute("aria-hidden", "true");
        });
      });
      // Close on outside click
      document.addEventListener("click", () => {
        if (themeMenu.classList.contains("is-open")) {
          themeMenu.classList.remove("is-open");
          themeMenu.setAttribute("aria-hidden", "true");
        }
      });
    }
  }

  /** Update notification count badge */
  function setNotificationCount(n) {
    const root = document.querySelector("[data-v5-top-bar]");
    if (!root) return;
    const wrap = root.querySelector(".v5-top-bar-notif-wrap");
    if (!wrap) return;
    const count = Number(n) || 0;
    const existing = wrap.querySelector("[data-v5-notif-badge]");
    if (count <= 0) {
      if (existing) existing.remove();
    } else {
      const label = count > 99 ? "99+" : String(count);
      if (existing) existing.textContent = label;
      else {
        const badge = document.createElement("span");
        badge.className = "v5-top-bar-notif-badge";
        badge.setAttribute("data-v5-notif-badge", "");
        badge.textContent = label;
        wrap.appendChild(badge);
      }
    }
    const btn = root.querySelector("[data-v5-notif-trigger]");
    if (btn) btn.setAttribute("aria-label", `Notifications (${count} non lues)`);
  }

  /** Update active theme */
  function setTheme(theme) {
    const valid = THEMES.some((t) => t.id === theme);
    if (!valid) return;
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("cinesort.theme", theme); } catch (e) { /* noop */ }
    // Update active state in menu
    const root = document.querySelector("[data-v5-top-bar]");
    if (root) {
      root.querySelectorAll(".v5-top-bar-theme-item").forEach((it) => {
        const isActive = it.dataset.theme === theme;
        it.classList.toggle("is-active", isActive);
        it.setAttribute("aria-checked", isActive ? "true" : "false");
      });
    }
  }

  /**
   * Render top bar.
   * @param {HTMLElement} container
   * @param {{
   *   title?: string,
   *   subtitle?: string,
   *   theme?: string,
   *   notificationCount?: number,
   *   onSearchClick?: function,
   *   onNotifClick?: function,
   *   onThemeChange?: function,
   * }} opts
   */
  function render(container, opts) {
    if (!container) return;
    opts = opts || {};
    container.innerHTML = _buildHtml(opts);
    _bindEvents(container, opts);
  }

  window.TopBarV5 = {
    render,
    setNotificationCount,
    setTheme,
    THEMES,
  };
})();
