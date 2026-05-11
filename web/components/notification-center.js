/* components/notification-center.js — v7.6.0 Vague 9
 * Notification center : drawer ouvrant depuis la cloche top-bar.
 * Liste + filtre (all/unread/insight/event), mark-all-read, dismiss, clear-all.
 * Poll 30s pour le compteur non-lu. Toasts transitoires inchanges (NotifyService
 * cote Python gere les notifications desktop OS).
 *
 * API publique :
 *   window.NotificationCenter.open()
 *   window.NotificationCenter.close()
 *   window.NotificationCenter.toggle()
 *   window.NotificationCenter.refresh()
 *   window.NotificationCenter.getUnreadCount()  -> Promise<number>
 *   window.NotificationCenter.startPolling(intervalMs)
 *   window.NotificationCenter.stopPolling()
 */
(function () {
  "use strict";

  const POLL_MS = 30000;
  const DRAWER_ID = "v5-notif-drawer";
  const OVERLAY_ID = "v5-notif-overlay";

  let _pollTimer = null;
  let _filter = "all"; // all | unread | insight | event
  let _isOpen = false;
  let _cache = { items: [], unread: 0 };

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function _svg(inner, size) {
    const s = size || 16;
    return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
  }

  const ICON_CLOSE = _svg('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>');
  const ICON_CHECK = _svg('<polyline points="20 6 9 17 4 12"/>');
  const ICON_TRASH = _svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>');
  const ICON_BELL_OFF = _svg('<path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.888 17.888 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><line x1="1" y1="1" x2="23" y2="23"/>');

  const LEVEL_ICON = {
    info:    _svg('<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>', 18),
    success: _svg('<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>', 18),
    warning: _svg('<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>', 18),
    error:   _svg('<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>', 18),
  };

  function _formatRelative(ts) {
    if (!ts) return "";
    const diff = Date.now() / 1000 - Number(ts);
    if (diff < 60) return "a l'instant";
    if (diff < 3600) return `il y a ${Math.round(diff / 60)} min`;
    if (diff < 86400) return `il y a ${Math.round(diff / 3600)} h`;
    return `il y a ${Math.round(diff / 86400)} j`;
  }

  function _api(method, params) {
    if (window.apiCall && typeof window.apiCall === "function") {
      return window.apiCall(method, params || {});
    }
    if (window.api && typeof window.api[method] === "function") {
      const args = params ? Object.values(params) : [];
      return Promise.resolve(window.api[method].apply(window.api, args));
    }
    return Promise.reject(new Error("no api bridge"));
  }

  function _ensureOverlay() {
    let overlay = document.getElementById(OVERLAY_ID);
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.className = "v5-notif-overlay";
    overlay.setAttribute("aria-hidden", "true");
    overlay.addEventListener("click", close);
    document.body.appendChild(overlay);
    return overlay;
  }

  function _ensureDrawer() {
    let drawer = document.getElementById(DRAWER_ID);
    if (drawer) return drawer;
    drawer = document.createElement("aside");
    drawer.id = DRAWER_ID;
    drawer.className = "v5-notif-drawer";
    drawer.setAttribute("role", "complementary");
    drawer.setAttribute("aria-label", "Centre de notifications");
    drawer.setAttribute("aria-hidden", "true");
    document.body.appendChild(drawer);
    return drawer;
  }

  function _itemHtml(it) {
    const level = LEVEL_ICON[it.level] ? it.level : "info";
    const icon = LEVEL_ICON[level];
    const time = _formatRelative(it.created_ts);
    const category = it.category || "event";
    const cls = `v5-notif-item v5-notif-item--${level} ${it.read ? "is-read" : "is-unread"}`;
    return `
      <li class="${cls}" data-notif-id="${_esc(it.id)}" role="listitem">
        <div class="v5-notif-item-icon">${icon}</div>
        <div class="v5-notif-item-body">
          <div class="v5-notif-item-header">
            <span class="v5-notif-item-title">${_esc(it.title)}</span>
            <span class="v5-notif-item-time">${_esc(time)}</span>
          </div>
          ${it.body ? `<div class="v5-notif-item-text">${_esc(it.body)}</div>` : ""}
          <div class="v5-notif-item-meta">
            <span class="v5-notif-item-category v5-notif-cat--${_esc(category)}">${_esc(category)}</span>
          </div>
        </div>
        <button type="button" class="v5-notif-item-dismiss" data-notif-dismiss
                aria-label="Supprimer la notification">${ICON_CLOSE}</button>
      </li>
    `;
  }

  function _emptyHtml() {
    return `
      <div class="v5-notif-empty">
        <div class="v5-notif-empty-icon">${ICON_BELL_OFF}</div>
        <div class="v5-notif-empty-title">Aucune notification</div>
        <div class="v5-notif-empty-hint">Les evenements importants apparaitront ici.</div>
      </div>
    `;
  }

  function _buildHtml(items, unread) {
    const filtered = items.filter((it) => {
      if (_filter === "unread") return !it.read;
      if (_filter === "insight") return it.category === "insight";
      if (_filter === "event")  return it.category === "event";
      return true;
    });
    const listHtml = filtered.length
      ? `<ul class="v5-notif-list" role="list">${filtered.map(_itemHtml).join("")}</ul>`
      : _emptyHtml();
    const counter = unread > 0 ? `<span class="v5-notif-counter">${unread} non lue${unread > 1 ? "s" : ""}</span>` : "";

    return `
      <header class="v5-notif-header">
        <div class="v5-notif-header-title">
          <h2>Notifications</h2>
          ${counter}
        </div>
        <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost"
                data-notif-close aria-label="Fermer">${ICON_CLOSE}</button>
      </header>
      <div class="v5-notif-filters" role="tablist" aria-label="Filtrer">
        ${[
          ["all", "Toutes"],
          ["unread", "Non lues"],
          ["insight", "Insights"],
          ["event", "Evenements"],
        ].map(([f, label]) => `
          <button type="button"
                  class="v5-notif-filter ${f === _filter ? "is-active" : ""}"
                  data-notif-filter="${f}"
                  role="tab"
                  aria-selected="${f === _filter ? "true" : "false"}">${label}</button>
        `).join("")}
      </div>
      <div class="v5-notif-actions">
        <button type="button" class="v5-btn v5-btn--ghost v5-btn--sm" data-notif-mark-all ${unread ? "" : "disabled"}>
          ${ICON_CHECK}<span>Tout marquer lu</span>
        </button>
        <button type="button" class="v5-btn v5-btn--ghost v5-btn--sm v5-btn--danger-ghost" data-notif-clear-all ${items.length ? "" : "disabled"}>
          ${ICON_TRASH}<span>Tout effacer</span>
        </button>
      </div>
      <div class="v5-notif-body">${listHtml}</div>
    `;
  }

  function _bindDrawer(drawer) {
    drawer.addEventListener("click", (e) => {
      const closeBtn = e.target.closest("[data-notif-close]");
      if (closeBtn) { close(); return; }

      const filterBtn = e.target.closest("[data-notif-filter]");
      if (filterBtn) {
        _filter = filterBtn.dataset.notifFilter || "all";
        refresh();
        return;
      }

      const markAll = e.target.closest("[data-notif-mark-all]");
      if (markAll && !markAll.disabled) {
        _api("mark_all_notifications_read").then(() => refresh()).catch(() => {});
        return;
      }

      const clearAll = e.target.closest("[data-notif-clear-all]");
      if (clearAll && !clearAll.disabled) {
        _api("clear_notifications").then(() => refresh()).catch(() => {});
        return;
      }

      const dismiss = e.target.closest("[data-notif-dismiss]");
      if (dismiss) {
        e.stopPropagation();
        const item = dismiss.closest("[data-notif-id]");
        if (!item) return;
        const id = item.dataset.notifId;
        _api("dismiss_notification", { notification_id: id }).then(() => refresh()).catch(() => {});
        return;
      }

      const itemEl = e.target.closest("[data-notif-id]");
      if (itemEl) {
        const id = itemEl.dataset.notifId;
        _api("mark_notification_read", { notification_id: id }).then(() => refresh()).catch(() => {});
      }
    });
  }

  function refresh() {
    const drawer = _ensureDrawer();
    return _api("get_notifications", { unread_only: false, limit: 100 })
      .then((res) => {
        if (!res || !res.ok) return;
        _cache.items = res.notifications || [];
        _cache.unread = res.unread_count || 0;
        if (_isOpen) {
          drawer.innerHTML = _buildHtml(_cache.items, _cache.unread);
        }
        _updateBadge(_cache.unread);
      })
      .catch(() => { /* silent */ });
  }

  function _updateBadge(count) {
    if (window.TopBarV5 && typeof window.TopBarV5.setNotificationCount === "function") {
      window.TopBarV5.setNotificationCount(count);
    }
    // v7.6.0 Vague 10 : event pour les listeners externes (ex: bouton sidebar legacy)
    document.dispatchEvent(new CustomEvent("v5:notif-count", { detail: { count } }));
  }

  function open() {
    if (_isOpen) return;
    const overlay = _ensureOverlay();
    const drawer = _ensureDrawer();
    _bindDrawer(drawer);
    _isOpen = true;
    overlay.classList.add("is-open");
    overlay.setAttribute("aria-hidden", "false");
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("v5-notif-lock");
    refresh();
    // Focus le drawer pour a11y
    setTimeout(() => {
      const first = drawer.querySelector("[data-notif-close]");
      if (first) first.focus();
    }, 50);
  }

  function close() {
    if (!_isOpen) return;
    _isOpen = false;
    const overlay = document.getElementById(OVERLAY_ID);
    const drawer = document.getElementById(DRAWER_ID);
    if (overlay) {
      overlay.classList.remove("is-open");
      overlay.setAttribute("aria-hidden", "true");
    }
    if (drawer) {
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("v5-notif-lock");
  }

  function toggle() { _isOpen ? close() : open(); }

  function getUnreadCount() {
    return _api("get_notifications_unread_count")
      .then((res) => (res && res.ok) ? Number(res.count || 0) : 0)
      .catch(() => 0);
  }

  function startPolling(intervalMs) {
    stopPolling();
    const ms = Number(intervalMs) || POLL_MS;
    _pollTimer = window.setInterval(() => {
      getUnreadCount().then((n) => _updateBadge(n));
    }, ms);
    // Premier refresh immediat
    getUnreadCount().then((n) => _updateBadge(n));
  }

  function stopPolling() {
    if (_pollTimer) {
      window.clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  // ESC pour fermer
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && _isOpen) { close(); }
  });

  window.NotificationCenter = {
    open, close, toggle, refresh,
    getUnreadCount, startPolling, stopPolling,
  };

  // Auto-start polling + auto-wire to top-bar notif trigger si present
  document.addEventListener("DOMContentLoaded", () => {
    startPolling(POLL_MS);
  });
})();
