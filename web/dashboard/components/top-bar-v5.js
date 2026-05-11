/* dashboard/components/top-bar-v5.js — v7.6.0 Vague 1 (ES module) */

import { escapeHtml } from "../core/dom.js";
import { t, onLocaleChange } from "../core/i18n.js";

// V6-02 : labels resolus via t() — l'id reste stable pour applique theme.
export const THEMES = [
  { id: "studio", labelKey: "topbar.themes.studio" },
  { id: "cinema", labelKey: "topbar.themes.cinema" },
  { id: "luxe",   labelKey: "topbar.themes.luxe" },
  { id: "neon",   labelKey: "topbar.themes.neon" },
];

function _themeLabel(theme) {
  return theme.labelKey ? t(theme.labelKey) : (theme.label || theme.id);
}

function _svg(pathContent, size = 18) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
}

const ICON_SEARCH = _svg('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>');
const ICON_BELL   = _svg('<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>');
const ICON_SUN    = _svg('<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>');

function _buildHtml(opts) {
  const title = opts.title || "";
  const subtitle = opts.subtitle || "";
  const currentTheme = opts.theme || "studio";
  const notifCount = Number(opts.notificationCount) || 0;

  return `
    <div class="v5-top-bar" data-v5-top-bar role="banner">
      <div class="v5-top-bar-title">
        <div class="v5-top-bar-title-main">${escapeHtml(title)}</div>
        ${subtitle ? `<div class="v5-top-bar-title-sub">${escapeHtml(subtitle)}</div>` : ""}
      </div>
      <div class="v5-top-bar-actions">
        <button type="button" class="v5-top-bar-search" data-v5-search-trigger
                aria-label="${escapeHtml(t("topbar.search_aria"))}">
          <span class="v5-top-bar-search-icon">${ICON_SEARCH}</span>
          <span class="v5-top-bar-search-label">${escapeHtml(t("topbar.search_label"))}</span>
          <kbd class="v5-top-bar-search-shortcut">Cmd+K</kbd>
        </button>
        <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost"
                data-v5-notif-trigger
                aria-label="${escapeHtml(t("topbar.notifications_aria", { count: notifCount }))}">
          <span class="v5-top-bar-notif-wrap">
            ${ICON_BELL}
            ${notifCount > 0 ? `<span class="v5-top-bar-notif-badge" data-v5-notif-badge>${notifCount > 99 ? "99+" : notifCount}</span>` : ""}
          </span>
        </button>
        <div class="v5-top-bar-theme-wrap">
          <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost"
                  data-v5-theme-trigger
                  aria-label="${escapeHtml(t("topbar.theme_change_aria"))}"
                  aria-haspopup="menu"
                  aria-expanded="false">${ICON_SUN}</button>
          <div class="v5-top-bar-theme-menu" data-v5-theme-menu role="menu" aria-hidden="true">
            ${THEMES.map((th, i) => `
              <button type="button"
                      class="v5-top-bar-theme-item ${th.id === currentTheme ? "is-active" : ""}"
                      data-theme="${escapeHtml(th.id)}"
                      role="menuitemradio"
                      tabindex="${i === 0 ? "0" : "-1"}"
                      aria-checked="${th.id === currentTheme ? "true" : "false"}">
                ${escapeHtml(_themeLabel(th))}
              </button>
            `).join("")}
          </div>
        </div>
      </div>
    </div>
  `;
}

function _bindEvents(root, opts) {
  const searchBtn = root.querySelector("[data-v5-search-trigger]");
  if (searchBtn) {
    searchBtn.addEventListener("click", () => {
      if (typeof opts.onSearchClick === "function") opts.onSearchClick();
    });
  }

  const notifBtn = root.querySelector("[data-v5-notif-trigger]");
  if (notifBtn) {
    notifBtn.addEventListener("click", () => {
      if (typeof opts.onNotifClick === "function") opts.onNotifClick();
    });
  }

  const themeBtn = root.querySelector("[data-v5-theme-trigger]");
  const themeMenu = root.querySelector("[data-v5-theme-menu]");
  if (themeBtn && themeMenu) {
    // V2-D (a11y) : helper unique pour synchroniser aria-expanded + aria-hidden + class.
    const setMenuOpen = (open) => {
      themeMenu.classList.toggle("is-open", !!open);
      themeMenu.setAttribute("aria-hidden", open ? "false" : "true");
      themeBtn.setAttribute("aria-expanded", open ? "true" : "false");
    };

    // V2-D (a11y) : focus le premier (ou l'item actif) quand le menu s'ouvre.
    const _focusFirstItem = () => {
      const items = Array.from(themeMenu.querySelectorAll("[data-theme]"));
      if (items.length === 0) return;
      const active = items.find((it) => it.classList.contains("is-active")) || items[0];
      // Roving tabindex : reset tous a -1, puis 0 sur l'actif.
      items.forEach((it) => it.setAttribute("tabindex", "-1"));
      active.setAttribute("tabindex", "0");
      try { active.focus(); } catch (e) { /* noop */ }
    };

    themeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const willOpen = !themeMenu.classList.contains("is-open");
      setMenuOpen(willOpen);
      if (willOpen) _focusFirstItem();
    });

    // V2-D (a11y) : navigation Arrow keys / Home / End / Enter dans le menu.
    themeMenu.addEventListener("keydown", (e) => {
      const items = Array.from(themeMenu.querySelectorAll("[data-theme]"));
      if (items.length === 0) return;
      const currentIdx = items.indexOf(document.activeElement);
      let nextIdx = -1;
      if (e.key === "ArrowDown") nextIdx = (currentIdx + 1) % items.length;
      else if (e.key === "ArrowUp") nextIdx = (currentIdx - 1 + items.length) % items.length;
      else if (e.key === "Home") nextIdx = 0;
      else if (e.key === "End") nextIdx = items.length - 1;
      else if (e.key === "Enter" || e.key === " ") {
        if (currentIdx >= 0) {
          e.preventDefault();
          items[currentIdx].click();
        }
        return;
      } else if (e.key === "Escape") {
        e.preventDefault();
        setMenuOpen(false);
        try { themeBtn.focus(); } catch (err) { /* noop */ }
        return;
      } else if (e.key === "Tab") {
        // Tab sort du menu et le ferme — comportement attendu d'un menu non modal.
        setMenuOpen(false);
        return;
      }
      if (nextIdx >= 0) {
        e.preventDefault();
        items.forEach((it) => it.setAttribute("tabindex", "-1"));
        items[nextIdx].setAttribute("tabindex", "0");
        try { items[nextIdx].focus(); } catch (err) { /* noop */ }
      }
    });

    themeMenu.querySelectorAll("[data-theme]").forEach((item) => {
      item.addEventListener("click", (e) => {
        // V7-fix : stopPropagation pour eviter que le document listener (bas)
        // ferme le menu au moment ou on clique un item — symptome user "rien
        // ne se passe au clic sur Luxe / Neon".
        e.stopPropagation();
        const theme = item.dataset.theme;
        console.log("[v5-topbar] theme item clicked:", theme);
        setTheme(theme);
        if (typeof opts.onThemeChange === "function") opts.onThemeChange(theme);
        setMenuOpen(false);
      });
    });
    document.addEventListener("click", () => {
      if (themeMenu.classList.contains("is-open")) {
        setMenuOpen(false);
      }
    });
  }
}

export function setNotificationCount(n) {
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
}

export function setTheme(theme) {
  const valid = THEMES.some((t) => t.id === theme);
  if (!valid) {
    console.warn("[v5-topbar] setTheme reject:", theme, "(not in THEMES list)");
    return;
  }
  console.log("[v5-topbar] setTheme apply:", theme);
  // V7-fix : appliquer sur <html> ET <body>. Certains styles legacy ciblent
  // body[data-theme] et d'autres tout element [data-theme]. Set des 2 pour
  // garantir l'application visuelle sur tous les themes (Luxe/Neon inclus).
  document.documentElement.setAttribute("data-theme", theme);
  document.body.setAttribute("data-theme", theme);
  try { localStorage.setItem("cinesort.theme", theme); } catch (e) { /* noop */ }
  // V7-debug : surveille pendant 2s qui ecrase data-theme apres notre set.
  // Si quelqu'un revert vers cinema/studio juste apres le click sur luxe/neon,
  // on aura le stack trace et la valeur reverted.
  try {
    const _watch = (target, label) => {
      const obs = new MutationObserver((muts) => {
        for (const m of muts) {
          if (m.attributeName === "data-theme") {
            const cur = target.getAttribute("data-theme");
            if (cur !== theme) {
              console.warn(`[v5-topbar][THEME-OVERRIDE] ${label} data-theme changed from "${theme}" to "${cur}" — caller stack:`);
              console.trace();
            }
          }
        }
      });
      obs.observe(target, { attributes: true, attributeFilter: ["data-theme"] });
      setTimeout(() => obs.disconnect(), 2000);
    };
    _watch(document.documentElement, "<html>");
    _watch(document.body, "<body>");
  } catch (e) { /* noop */ }
  const root = document.querySelector("[data-v5-top-bar]");
  if (root) {
    root.querySelectorAll(".v5-top-bar-theme-item").forEach((it) => {
      const isActive = it.dataset.theme === theme;
      it.classList.toggle("is-active", isActive);
      it.setAttribute("aria-checked", isActive ? "true" : "false");
    });
  }
}

// V6-02 : etat dernier render pour re-render au changement de locale.
let _lastTbContainer = null;
let _lastTbOpts = null;

export function render(container, opts = {}) {
  if (!container) return;
  _lastTbContainer = container;
  _lastTbOpts = opts;
  container.innerHTML = _buildHtml(opts);
  _bindEvents(container, opts);
}

// V6-02 : re-render au changement de locale (preserve l'etat theme/notif).
onLocaleChange(() => {
  if (_lastTbContainer && _lastTbContainer.isConnected) {
    render(_lastTbContainer, _lastTbOpts || {});
  }
});

/* ============================================================
   V3-08 — FAB Aide (Help Floating Action Button)
   Bouton flottant coin bas-droit qui ouvre la vue Aide.
   ============================================================ */

export function mountHelpFab(opts = {}) {
  if (document.getElementById("v5HelpFab")) return;
  const btn = document.createElement("button");
  btn.id = "v5HelpFab";
  btn.type = "button";
  btn.className = "v5-help-fab";
  btn.setAttribute("aria-label", t("topbar.help_fab_aria"));
  btn.title = t("topbar.help_fab_title");
  btn.textContent = "?";
  btn.addEventListener("click", () => {
    if (typeof opts.onClick === "function") {
      opts.onClick();
    } else {
      window.location.hash = "#/help";
    }
  });
  document.body.appendChild(btn);
}

export function unmountHelpFab() {
  const el = document.getElementById("v5HelpFab");
  if (el) el.remove();
}

/* ============================================================
   V7.6.0 Notification Center — mise a jour dynamique du badge
   Met a jour le compteur de la cloche apres l'init (ex: nouvel
   evenement push depuis le centre de notifications).
   ============================================================ */

export function updateNotificationBadge(count) {
  const n = Number(count) || 0;
  const wrap = document.querySelector("[data-v5-top-bar] .v5-top-bar-notif-wrap");
  if (wrap) {
    let badge = wrap.querySelector("[data-v5-notif-badge]");
    if (n > 0) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "v5-top-bar-notif-badge";
        badge.setAttribute("data-v5-notif-badge", "");
        wrap.appendChild(badge);
      }
      badge.textContent = n > 99 ? "99+" : String(n);
    } else if (badge) {
      badge.remove();
    }
  }
  const btn = document.querySelector("[data-v5-notif-trigger]");
  if (btn) btn.setAttribute("aria-label", t("topbar.notifications_aria", { count: n }));
}
