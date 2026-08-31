/* dashboard/components/notification-center.js — v7.6.0 Vague 9 (ES module)
 *
 * Drawer de notifications consomme via l'API REST (dashboard distant).
 *
 * Exports :
 *   openNotifications()
 *   closeNotifications()
 *   toggleNotifications()
 *   refreshNotifications()
 *   getUnreadCount() -> Promise<number>
 *   startNotificationPolling(intervalMs)
 *   stopNotificationPolling()
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
// LOT 5-D : « Tout effacer » est destructif (regle projet n3) — cf.
// _confirmerToutEffacer plus bas.
import { dangerConfirmModal } from "./modal.js";

const POLL_MS = 30000;
const DRAWER_ID = "v5-notif-drawer";
const OVERLAY_ID = "v5-notif-overlay";

let _pollTimer = null;
let _filter = "all";
let _isOpen = false;
let _cache = { items: [], unread: 0 };
// V2-C R4-MEM-2 : tracker les listeners attaches pour cleanup au close.
// Sans ca, chaque open() attache un nouveau click listener sur l'overlay
// (ou sur le drawer recree) → cumul O(n) listeners apres N open/close cycles.
let _overlayClickHandler = null;
let _drawerClickHandler = null;
// A11y WCAG 2.1.1 : handler keydown Enter/Space sur <li role=button>, tracke
// pour cleanup avec les autres listeners au closeNotifications().
let _drawerKeydownHandler = null;

function _svg(inner, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

const ICON_CLOSE = _svg('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>');
const ICON_CHECK = _svg('<polyline points="20 6 9 17 4 12"/>');
const ICON_TRASH = _svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/>');
const ICON_BELL_OFF = _svg('<path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.888 17.888 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><line x1="1" y1="1" x2="23" y2="23"/>');

const LEVEL_ICON = {
  info:    _svg('<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>', 18),
  success: _svg('<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>', 18),
  warning: _svg('<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/>', 18),
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

function _ensureOverlay() {
  // V2-C R4-MEM-2 : on recree systematiquement (closeNotifications a remove()).
  // Tracker le handler pour pouvoir l'enlever plus tard.
  let overlay = document.getElementById(OVERLAY_ID);
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  overlay.className = "v5-notif-overlay";
  overlay.setAttribute("aria-hidden", "true");
  _overlayClickHandler = () => closeNotifications();
  overlay.addEventListener("click", _overlayClickHandler);
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
  // A11y WCAG 2.1.1 : <li> est cliquable pour marquer-lu -> doit etre focusable
  // au clavier (tabindex=0) et expose comme button. aria-label decrit l'action.
  // Si deja lu, on ne propose pas l'action (pas de tabindex/role button).
  const a11yAttrs = it.read
    ? ""
    : ` tabindex="0" role="button" aria-label="Marquer comme lu: ${escapeHtml(it.title || "")}"`;
  return `
    <li class="${cls}" data-notif-id="${escapeHtml(it.id)}"${a11yAttrs}>
      <div class="v5-notif-item-icon">${icon}</div>
      <div class="v5-notif-item-body">
        <div class="v5-notif-item-header">
          <span class="v5-notif-item-title">${escapeHtml(it.title)}</span>
          <span class="v5-notif-item-time">${escapeHtml(time)}</span>
        </div>
        ${it.body ? `<div class="v5-notif-item-text">${escapeHtml(it.body)}</div>` : ""}
        <div class="v5-notif-item-meta">
          <span class="v5-notif-item-category v5-notif-cat--${escapeHtml(category)}">${escapeHtml(category)}</span>
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

/** LOT 5-D — « Tout effacer » derriere la confirmation de la regle projet n3.
 *
 * Les deux conditions du critere ecrit dans `dangerConfirmModal` sont reunies :
 * la perte est IRRECUPERABLE PAR L'APPLICATION (les notifications vivent en
 * memoire, `store.clear()` ne laisse ni undo ni corbeille) et la portee n'est
 * PAS une selection de l'utilisateur — le bouton efface TOUT, y compris ce que
 * le filtre courant ne montre pas. La suppression UNITAIRE, elle, reste
 * immediate : c'est une portee choisie.
 *
 * La liste vient de `_cache.items` (toutes les notifications), jamais du sous-
 * ensemble filtre : c'est justement l'ecart entre les deux qui surprend.
 * `countdownSeconds` n'est pas passe -> derive du nombre d'elements par
 * `gradedCountdownSeconds` (3 s au-dela de 50, comme l'exige la regle n3).
 */
function _confirmerToutEffacer() {
  const items = (_cache.items || []).map((it) => String((it && (it.title || it.body || it.id)) || ""));
  const n = items.length;
  dangerConfirmModal({
    title: `Effacer les ${n} notification${n > 1 ? "s" : ""} ?`,
    items,
    consequence:
      "Effacement definitif : le centre ne garde les notifications qu'en memoire, "
      + "il n'y a ni annulation ni corbeille. Le filtre affiche n'y change rien, "
      + "TOUT est efface — y compris les avertissements d'apply, seul canal qui "
      + "survit a la fermeture de l'ecran.",
    confirmLabel: "Tout effacer",
    onConfirm: () =>
      apiPost("runtime/clear_notifications").then(() => refreshNotifications()).catch(() => {}),
  });
}

function _bindDrawer(drawer) {
  // V2-C R4-MEM-2 : tracker le handler pour pouvoir le retirer si besoin
  // (sinon les listeners s'accumulaient car le drawer n'etait pas re-cree).
  _drawerClickHandler = (e) => {
    if (e.target.closest("[data-notif-close]")) { closeNotifications(); return; }

    const filterBtn = e.target.closest("[data-notif-filter]");
    if (filterBtn) {
      _filter = filterBtn.dataset.notifFilter || "all";
      refreshNotifications();
      return;
    }

    const markAll = e.target.closest("[data-notif-mark-all]");
    if (markAll && !markAll.disabled) {
      apiPost("runtime/mark_all_notifications_read").then(() => refreshNotifications()).catch(() => {});
      return;
    }

    const clearAll = e.target.closest("[data-notif-clear-all]");
    if (clearAll && !clearAll.disabled) {
      _confirmerToutEffacer();
      return;
    }

    const dismiss = e.target.closest("[data-notif-dismiss]");
    if (dismiss) {
      e.stopPropagation();
      const item = dismiss.closest("[data-notif-id]");
      if (!item) return;
      const id = item.dataset.notifId;
      apiPost("runtime/dismiss_notification", { notification_id: id }).then(() => refreshNotifications()).catch(() => {});
      return;
    }

    const itemEl = e.target.closest("[data-notif-id]");
    if (itemEl) {
      const id = itemEl.dataset.notifId;
      apiPost("runtime/mark_notification_read", { notification_id: id }).then(() => refreshNotifications()).catch(() => {});
    }
  };
  drawer.addEventListener("click", _drawerClickHandler);
  // A11y WCAG 2.1.1 (Keyboard) : permettre Enter/Space sur les <li> notifs
  // role=button pour marquer comme lu. Sans ca, utilisateurs clavier/SR
  // ne peuvent pas marquer une notif lue (seul le bouton supprimer leur etait
  // accessible). On reutilise _drawerClickHandler via dispatch click pour
  // garder la logique centralisee (filtres, dismiss, mark-as-read).
  _drawerKeydownHandler = (e) => {
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    const itemEl = e.target.closest("[data-notif-id][role='button']");
    if (!itemEl) return;
    // Ne pas declencher si focus est sur un bouton interne (dismiss)
    if (e.target.closest("[data-notif-dismiss]")) return;
    e.preventDefault();
    const id = itemEl.dataset.notifId;
    apiPost("runtime/mark_notification_read", { notification_id: id }).then(() => refreshNotifications()).catch(() => {});
  };
  drawer.addEventListener("keydown", _drawerKeydownHandler);
}

export function refreshNotifications() {
  const drawer = _ensureDrawer();
  return apiPost("runtime/get_notifications", { unread_only: false, limit: 100 })
    .then((res) => {
      // Fix audit 2026-05-25 (v1.5.3) Vague F : payload imbrique dans res.data
      const _payload = (res && res.data) || res || {};
      if (!_payload.ok) return;
      // Fix audit 2026-05-25 (v1.5.3) Vague F : payload imbrique dans res.data
      _cache.items = _payload.notifications || [];
      // Fix audit 2026-05-25 (v1.5.3) Vague F : payload imbrique dans res.data
      _cache.unread = _payload.unread_count || 0;
      if (_isOpen) {
        drawer.innerHTML = _buildHtml(_cache.items, _cache.unread);
      }
      _updateBadge(_cache.unread);
    })
    .catch(() => {});
}

function _updateBadge(count) {
  // Publique via event (pas d'import direct de top-bar pour eviter le couplage)
  document.dispatchEvent(new CustomEvent("v5:notif-count", { detail: { count } }));
}

export function openNotifications() {
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
  refreshNotifications();
  setTimeout(() => {
    const first = drawer.querySelector("[data-notif-close]");
    if (first) first.focus();
  }, 50);
}

export function closeNotifications() {
  if (!_isOpen) return;
  _isOpen = false;
  const overlay = document.getElementById(OVERLAY_ID);
  const drawer = document.getElementById(DRAWER_ID);
  // V2-C R4-MEM-2 : retirer overlay+drawer du DOM (et leurs listeners) au lieu
  // de juste cacher la visibilite. Sinon chaque open() rajoutait un listener
  // sur l'overlay/drawer existant → cumul de listeners zombie sur sessions
  // longues. Le pattern ensure*() recree au prochain openNotifications().
  if (overlay) {
    if (_overlayClickHandler) {
      overlay.removeEventListener("click", _overlayClickHandler);
      _overlayClickHandler = null;
    }
    overlay.remove();
  }
  if (drawer) {
    if (_drawerClickHandler) {
      drawer.removeEventListener("click", _drawerClickHandler);
      _drawerClickHandler = null;
    }
    if (_drawerKeydownHandler) {
      drawer.removeEventListener("keydown", _drawerKeydownHandler);
      _drawerKeydownHandler = null;
    }
    drawer.remove();
  }
  document.body.classList.remove("v5-notif-lock");
}

export function toggleNotifications() { _isOpen ? closeNotifications() : openNotifications(); }

export function getUnreadCount() {
  // Fix audit 2026-05-24 : apiPost retourne soit { ok, data: { count } } selon
  // la facade (la plupart des endpoints v7+), soit { ok, count } a plat selon
  // d'autres (legacy). On normalise pour supporter les 2 shapes — avant on ne
  // regardait que res.count et le compteur restait bloque a 0 quand le
  // backend renvoyait { ok: true, data: { count: 12 } }.
  return apiPost("runtime/get_notifications_unread_count")
    .then((res) => {
      const data = (res && res.data) || res || {};
      const count = Number(data.count || 0);
      return (res && res.ok !== false) ? count : 0;
    })
    .catch(() => 0);
}

export function startNotificationPolling(intervalMs) {
  stopNotificationPolling();
  const ms = Number(intervalMs) || POLL_MS;
  _pollTimer = window.setInterval(() => {
    getUnreadCount().then((n) => _updateBadge(n));
  }, ms);
  // FIX 2026-06-05 (avalanche boot natif) : on DIFFERE le tick initial de
  // 3s au lieu de tirer immediatement. Sans ca, l'appel get_notifications_unread_count
  // partait a t=0 en concurrence avec les 4 fetchs initiaux d'accueil.js +
  // les 2 fetchs cachedGetSettings du shell -> 7 requetes simultanees au
  // boot sur un backend qui rate-limit a 5/s -> 429 garanti.
  // Le delai 3s laisse le boot se stabiliser (token+ shell + accueil rendus).
  window.setTimeout(() => {
    if (_pollTimer == null) return; // stop entre temps
    getUnreadCount().then((n) => _updateBadge(n));
  }, 3000);
}

export function stopNotificationPolling() {
  if (_pollTimer) {
    window.clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

// ESC close (guard pour les tests node sans DOM)
if (typeof document !== "undefined") {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && _isOpen) { closeNotifications(); }
  });
}
