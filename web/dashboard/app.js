/* app.js — Bootstrap dashboard CineSort v7.6.0 (V5B-01 : v5 active)
 *
 * Vague 5B : active le shell v5 (sidebar-v5 + top-bar-v5 + breadcrumb +
 * notification-center) et cable les 7 vues v5 ESM portees en V5bis.
 *
 * Coexistence : les vues v4 dashboard (jellyfin/plex/radarr/logs) restent
 * actives sur leurs routes ; V5C les portera ou supprimera.
 */

import { $$ } from "./core/dom.js";
import { hasToken, setToken, onClearToken } from "./core/state.js";

/* H1 fix : window.onerror global pour capturer les erreurs JS non-attrapees
 * (sinon : page blanche silencieuse). Affiche un toast minimaliste. */
(function _installGlobalErrorHandler() {
  let _errorBannerShown = false;
  function _showErrorBanner(msg) {
    if (_errorBannerShown) return;
    _errorBannerShown = true;
    try {
      // Cf issue #67 : construction DOM safe (createElement + textContent)
      // au lieu de innerHTML — empeche XSS via msg quand window.onerror
      // recoit un Error.message contenant du HTML/JS arbitraire.
      const banner = document.createElement("div");
      banner.style.cssText = "position:fixed;top:0;left:0;right:0;background:#DC2626;color:#fff;padding:8px 16px;z-index:99999;font-family:sans-serif;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,0.3);";

      const label = document.createElement("strong");
      label.textContent = "Erreur JS :";
      banner.appendChild(label);
      banner.appendChild(document.createTextNode(" " + String(msg || "Erreur inconnue").substring(0, 200) + " "));

      const closeBtn = document.createElement("button");
      closeBtn.style.cssText = "float:right;background:transparent;border:1px solid #fff;color:#fff;padding:2px 8px;border-radius:4px;cursor:pointer";
      closeBtn.textContent = "Fermer";
      closeBtn.addEventListener("click", () => {
        banner.remove();
        window.__cinesortErrorBannerShown = false;
        _errorBannerShown = false;
      });
      banner.appendChild(closeBtn);

      document.body.appendChild(banner);
      window.__cinesortErrorBannerShown = true;
      setTimeout(() => { _errorBannerShown = false; }, 5000);
    } catch (e) { /* dernier recours : console */ console.error("[error-banner failed]", e); }
  }
  window.addEventListener("error", (ev) => {
    console.error("[window.onerror]", ev.message, ev.filename, ev.lineno, ev.colno, ev.error);
    _showErrorBanner(ev.message);
  });
  window.addEventListener("unhandledrejection", (ev) => {
    console.error("[unhandledrejection]", ev.reason);
    _showErrorBanner(String(ev.reason));
  });
})();

/* --- Detection mode natif (pywebview desktop) via URL params ---
 * L'app desktop charge l'URL /dashboard/?ntoken=XXX&native=1
 * On recupere le token AVANT que le router ne redirige vers /login.
 */
(function _detectNativeBoot() {
  try {
    const params = new URLSearchParams(window.location.search);
    const ntoken = params.get("ntoken");
    const native = params.get("native") === "1";
    if (native) {
      window.__CINESORT_NATIVE__ = true;
      document.documentElement.classList.add("cinesort-native-pending");
    }
    if (ntoken) {
      setToken(ntoken, true);  // persist
      // Purger le token de l'URL pour ne pas le laisser dans l'historique.
      const url = new URL(window.location.href);
      url.searchParams.delete("ntoken");
      // Garder ?native=1 si present
      window.history.replaceState({}, "", url.pathname + (native ? "?native=1" : "") + window.location.hash);
    }
  } catch (e) {
    console.warn("[dash-boot] detection native echouee", e);
  }
})();

import { registerRoute, requireAuth, startRouter, navigateTo } from "./core/router.js";
import { apiPost, cachedGetSettings } from "./core/api.js";
import { initI18n, setLocale } from "./core/i18n.js";

// === Composants v5 shell ===
import * as sidebarV5 from "./components/sidebar-v5.js";
import * as topBarV5 from "./components/top-bar-v5.js";
import * as breadcrumb from "./components/breadcrumb.js";
import * as notifCenter from "./components/notification-center.js";

// === Vues v4 RESTAUREES (post-fix : la v5 perdait trop de fonctionnalites) ===
import { initLogin } from "./views/login.js";
import { initStatus } from "./views/status.js";          // /home + /status (dashboard complet)
import { initLibraryWorkflow, unmountLibrary } from "./views/library/library.js";  // /library
import { initQuality } from "./views/quality.js";        // /quality
// V7-fix : vue Processing v5 dediee (separe Bibliotheque "consulter" de
// Traitement "agir : scan/review/apply"). Avant : /processing aliasait
// /library, donc deux onglets sidebar montraient la meme chose.
import { initProcessing } from "../views/processing.js"; // /processing
// V7-fusion Phase 3 : vue QIJ consolidee remplace 5 vues separees
// (quality + logs + jellyfin + plex + radarr). Routes legacy gardees en alias.
// V2-C R4-MEM-4 : import des unmount* exposes pour cleanup au navigate.
import { initQij, unmountQij } from "./views/qij.js"; // /qij + alias /quality /logs /jellyfin /plex /radarr
import { initSettings, unmountSettings } from "./views/settings.js"; // /settings (dashboard v4 complet, 15 sections)
import { initHelp as initHelpV4 } from "./views/help.js"; // /help (FAQ v4)

// === Vues v5 conservees pour features uniques sans equivalent v4 ===
import { initFilmDetail } from "../views/film-detail.js"; // /film/:id (pas de page v4)

// === Vues v4 conservees (V5C les portera ou supprimera) ===
import { initJellyfin } from "./views/jellyfin.js";
import { initPlex } from "./views/plex.js";
import { initRadarr } from "./views/radarr.js";
import { initLogs } from "./views/logs.js";

// === Helpers UI legacy preserves ===
import { initKeyboard } from "./core/keyboard.js";
import { initDropHandlers } from "./core/drop.js";
import { initCommandPalette } from "./components/command-palette.js";
import { initCopyToClipboard } from "./components/copy-to-clipboard.js";
import { initAutoTooltip } from "./components/auto-tooltip.js";
import { initGlossaryTooltips } from "./components/glossary-tooltip.js";
import { decorateMainButtons } from "./components/shortcut-tooltip.js";
// Confetti : side-effect import (expose window.launchConfetti)
import "./components/confetti.js";

// V2-C R4-MEM-5 : purge des drafts review.js expires (TTL 30j) au boot.
// Module dedie dans core/ pour eviter d'importer ./views/review.js depuis app.js
// (interdit par test_v5c_cleanup — review.js fait partie des vues v4 retirees).
import { cleanupExpiredDrafts } from "./core/drafts-cleanup.js";

/* === Routes v5 ESM ======================================== */

registerRoute("/login", { view: "view-login", init: initLogin });
// Toutes les routes principales pointent vers les vues v4 RESTAUREES (post-fix V5).
// La v5 reste disponible (web/views/*) mais n'est plus active : elle perdait trop
// de fonctionnalites par rapport aux vues v4 originales (cf incident dashboard).
registerRoute("/home", { view: "view-status", guard: requireAuth, init: initStatus });
registerRoute("/library", { view: "view-library", guard: requireAuth, init: (el, opts) => { initLibraryWorkflow(el, opts); return unmountLibrary; } });
// V7-fix : /processing utilise la vraie vue v5 (stepper scan -> review -> apply)
// au lieu d'aliaser /library. Mount dedie #view-processing (vide dans index.html,
// initProcessing fait container.innerHTML lui-meme).
registerRoute("/processing", { view: "view-processing", guard: requireAuth, init: initProcessing });
// V7-fusion Phase 3 : route principale QIJ. Aliases /quality /logs /jellyfin /plex /radarr
// en bas pour la retrocompat (anciens liens externes + data-nav-route legacy).
// V2-C R4-MEM-4 : init() retourne le unmount pour que le router l'appelle au navigate.
registerRoute("/qij", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQij(el, opts); return unmountQij; } });
registerRoute("/quality", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQij(el, { ...opts, tab: "quality" }); return unmountQij; } });
registerRoute("/settings", { view: "view-settings", guard: requireAuth, init: (el, opts) => { initSettings(el, opts); return unmountSettings; } });
registerRoute("/help", { view: "view-help", guard: requireAuth, init: initHelpV4 });
registerRoute("/film/:id", {
  view: "view-film-detail",
  guard: requireAuth,
  init: (el, opts) => initFilmDetail(el, { filmId: opts && opts.params ? opts.params.id : undefined }),
});

// V7-fusion Phase 3 : routes legacy /jellyfin /plex /radarr /logs aliasent vers QIJ
// (avant : 4 vues v4 separees). On garde initJellyfin/Plex/Radarr/Logs imported pour
// compat (au cas ou un autre code les appelle), mais les routes pointent vers QIJ.
// V2-C R4-MEM-4 : init() retourne le unmount pour cleanup au navigate.
registerRoute("/jellyfin", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQij(el, { ...opts, tab: "integrations" }); return unmountQij; } });
registerRoute("/plex",     { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQij(el, { ...opts, tab: "integrations" }); return unmountQij; } });
registerRoute("/radarr",   { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQij(el, { ...opts, tab: "integrations" }); return unmountQij; } });
registerRoute("/logs",     { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQij(el, { ...opts, tab: "journal" }); return unmountQij; } });

// Alias compat /status -> /home (anciens liens, scripts externes)
registerRoute("/status", { view: "view-status", guard: requireAuth, init: initStatus });

/* === Mapping ID sidebar v5 -> route URL ==================== */

// V7-fusion Phase 3 : alias sidebar id -> route URL.
// "qij" sidebar -> /qij (vue consolidee Quality + Integrations + Journal).
// Items ancestraux (journal/jellyfin/plex/radarr) supprimes de la sidebar
// mais leurs ROUTES restent (pour ne pas casser les liens externes / data-nav-route legacy).
const SIDEBAR_ROUTE_ALIAS = {
  qij: "/qij",
};

function _routeFromSidebarId(routeId) {
  return SIDEBAR_ROUTE_ALIAS[routeId] || ("/" + routeId);
}

function _currentRouteId() {
  // Extrait l'id pour la sidebar (ex: "#/library" -> "library", "#/film/42" -> "film")
  const hash = (window.location.hash || "#/home").replace(/^#\//, "");
  const base = hash.split("?")[0].split("#")[0];
  const first = base.split("/")[0];
  // V7-fusion Phase 3 : routes legacy mapent vers "qij" (item sidebar consolide).
  if (["quality", "logs", "jellyfin", "plex", "radarr"].includes(first)) return "qij";
  // Inverse-mapping pour la sidebar (ex: "/qij?tab=xxx" -> "qij")
  for (const [sidebarId, route] of Object.entries(SIDEBAR_ROUTE_ALIAS)) {
    if (route === "/" + first || route.startsWith("/" + first + "?")) return sidebarId;
  }
  return first || "home";
}

/* === Mount shell v5 ====================================== */

async function _mountV5Shell() {
  const sidebarMount = document.getElementById("v5SidebarMount");
  const topBarMount = document.getElementById("v5TopBarMount");
  const breadcrumbMount = document.getElementById("v5BreadcrumbMount");

  // Sidebar v5 (8 entrees + integrations + footer About)
  sidebarV5.render(sidebarMount, {
    activeRoute: _currentRouteId(),
    onNavigate: (routeId) => navigateTo(_routeFromSidebarId(routeId)),
    onAboutClick: _openAboutModal,
  });

  // Theme initial depuis settings (fallback "luxe")
  // V2-B : cachedGetSettings dedup les 4+ appels paralleles au boot.
  const settingsRes = await cachedGetSettings().catch(() => ({ data: {} }));
  const settings = settingsRes && settingsRes.data ? settingsRes.data : {};
  const theme = settings.theme || "luxe";

  // Top-bar v5 (search + notif + theme switcher)
  topBarV5.render(topBarMount, {
    title: "CineSort",
    subtitle: "",
    theme,
    notificationCount: 0,
    onSearchClick: () => window.dispatchEvent(new CustomEvent("cinesort:command-palette")),
    onNotifClick: () => notifCenter.toggleNotifications(),
    onThemeChange: _applyTheme,
  });

  // Breadcrumb (initialement vide, mis a jour par le router via syncShell)
  if (breadcrumbMount && typeof breadcrumb.render === "function") {
    breadcrumb.render(breadcrumbMount, []);
  }

  // FAB Aide V3-08 (bouton flottant ?)
  if (typeof topBarV5.mountHelpFab === "function") {
    topBarV5.mountHelpFab({ onClick: () => navigateTo("/help") });
  }

  // Affichage du shell (le router le toggle ensuite selon /login vs autre)
  document.getElementById("app-shell").classList.remove("hidden");
}

// Cf issue #89 (audit-2026-05-12:m7n9) : listener attache au niveau module
// (executable une seule fois quand app.js est charge) plutot que dans
// _mountV5Shell qui pourrait — en cas de refactor futur — etre appele
// plusieurs fois et accumuler des listeners doublons sur le document.
// `topBarV5.updateNotificationBadge` est verifie avant appel : si le shell
// n'est pas encore monte, l'event est simplement ignore.
document.addEventListener("v5:notif-count", (ev) => {
  const n = (ev && ev.detail) ? Number(ev.detail.count) || 0 : 0;
  if (typeof topBarV5.updateNotificationBadge === "function") {
    topBarV5.updateNotificationBadge(n);
  }
});

/* === Sync sidebar/breadcrumb au changement de route ====== */

const ROUTE_BREADCRUMBS = {
  "/home":       [{ label: "Accueil" }],
  "/library":    [{ label: "Bibliotheque" }],
  "/processing": [{ label: "Traitement" }],
  // V7-fusion Phase 3 : QIJ + alias legacy.
  "/qij":        [{ label: "QIJ" }],
  "/quality":    [{ label: "QIJ", route: "/qij" }, { label: "Qualite" }],
  "/jellyfin":   [{ label: "QIJ", route: "/qij" }, { label: "Integrations" }, { label: "Jellyfin" }],
  "/plex":       [{ label: "QIJ", route: "/qij" }, { label: "Integrations" }, { label: "Plex" }],
  "/radarr":     [{ label: "QIJ", route: "/qij" }, { label: "Integrations" }, { label: "Radarr" }],
  "/logs":       [{ label: "QIJ", route: "/qij" }, { label: "Journal" }],
  "/settings":   [{ label: "Parametres" }],
  "/help":       [{ label: "Aide" }],
};

function _syncShellOnRoute() {
  const id = _currentRouteId();
  if (typeof sidebarV5.setActive === "function") sidebarV5.setActive(id);
  const breadcrumbMount = document.getElementById("v5BreadcrumbMount");
  if (breadcrumbMount && typeof breadcrumb.render === "function") {
    const hash = window.location.hash.replace(/^#/, "").split("?")[0].split("#")[0];
    const baseRoute = "/" + hash.split("/").slice(1, 2).join("/");
    const items = ROUTE_BREADCRUMBS[baseRoute] || [{ label: hash || "Accueil" }];
    breadcrumb.render(breadcrumbMount, items, {
      onNavigate: (route) => navigateTo(route),
    });
  }
}

window.addEventListener("hashchange", _syncShellOnRoute);

/* === Bootstrap ============================================ */

document.addEventListener("DOMContentLoaded", async () => {
  // V7-fix : bypass login DOIT etre evalue AVANT toute init suceptible de throw,
  // sinon une erreur d'init silencieuse empeche le bypass (et l'utilisateur voit
  // le login alors que le token est present).
  const isNative = !!window.__CINESORT_NATIVE__;
  if (isNative) document.body.classList.add("is-native");

  if (isNative && hasToken()) {
    if (!window.location.hash || window.location.hash === "#" || window.location.hash.includes("/login")) {
      window.location.hash = "#/home";
    }
  } else if (!hasToken() && !window.location.hash.includes("/login")) {
    window.location.hash = "#/login";
  }

  // Helpers UI legacy (clavier, drag&drop, palette, tooltips) — chacun isole
  // via try/catch pour qu'une init defaillante ne bloque pas les autres.
  try { initKeyboard(); } catch (e) { console.warn("[boot] initKeyboard", e); }
  try { initDropHandlers(); } catch (e) { console.warn("[boot] initDropHandlers", e); }
  try { initCommandPalette(); } catch (e) { console.warn("[boot] initCommandPalette", e); }
  try { initCopyToClipboard(); } catch (e) { console.warn("[boot] initCopyToClipboard", e); }
  try { initAutoTooltip(); } catch (e) { console.warn("[boot] initAutoTooltip", e); }
  try { initGlossaryTooltips(); } catch (e) { console.warn("[boot] initGlossaryTooltips", e); }
  try { decorateMainButtons(); } catch (e) { console.warn("[boot] decorateMainButtons", e); }
  // V2-C R4-MEM-5 : purge drafts review.js expires (TTL 30j) — cleanup global au boot.
  try { cleanupExpiredDrafts(); } catch (e) { console.warn("[boot] cleanupExpiredDrafts", e); }

  startRouter();

  // V6-01-fix : initialiser i18n AVANT le mount (sinon t() retourne les cles brutes)
  // Charge fr.json + locale stockee, sans bloquer >500ms.
  try {
    await initI18n();
  } catch (e) {
    console.warn("[boot] initI18n", e);
  }

  // Si on est authentifie, monter le shell v5 + initialiser les features
  if (hasToken()) {
    // V6-01-fix : synchroniser la locale depuis le setting backend si different
    try {
      const sres = await cachedGetSettings();
      const backendLocale = (sres && sres.data && sres.data.locale) || "fr";
      if (backendLocale && backendLocale !== "fr") {
        await setLocale(backendLocale);
      }
    } catch (e) { /* silencieux : i18n a deja FR par defaut */ }
    await _mountV5Shell();
    await _loadDashTheme();
    _syncShellOnRoute();
    await _initSidebarFeatures();
    await _initNotificationPolling();
    await _initDemoModeIfNeeded();
    await _checkUpdateBadge();
  }
});

/* === V3-04 : compteurs sidebar + V3-01 integrations + V1-13 update ====== */

// Cf issue #89 : stocker les interval IDs pour pouvoir les clear au logout.
// Sans ca, apres clearToken() les setInterval continuent a tourner (boucle
// 401 si fetch + leak memoire si listeners restent attaches).
let _sidebarCountersInterval = null;
let _updateBadgeInterval = null;
let _notificationFallbackInterval = null;

async function _initSidebarFeatures() {
  await _loadSidebarCounters();
  if (_sidebarCountersInterval == null) {
    _sidebarCountersInterval = setInterval(_loadSidebarCounters, 30000);
  }
  await _checkIntegrationNav();
  await _checkUpdateBadge();
}

async function _loadSidebarCounters() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("get_sidebar_counters");
    const data = (res && res.data && res.data.data) || (res && res.data) || {};
    if (typeof sidebarV5.updateSidebarBadges === "function") {
      sidebarV5.updateSidebarBadges(data);
    }
  } catch { /* silencieux */ }
}

async function _checkIntegrationNav() {
  if (!hasToken()) return;
  try {
    const res = await cachedGetSettings();
    const s = (res && res.data) || {};
    if (typeof sidebarV5.markIntegrationState === "function") {
      sidebarV5.markIntegrationState("jellyfin", !!s.jellyfin_enabled, "Jellyfin");
      sidebarV5.markIntegrationState("plex", !!s.plex_enabled, "Plex");
      sidebarV5.markIntegrationState("radarr", !!s.radarr_enabled, "Radarr");
    }
  } catch { /* silencieux */ }
}

/** V1-13 : badge "•" sur item Settings si MAJ disponible (cache backend). */
async function _checkUpdateBadge() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("get_update_info");
    const data = (res && res.data) || {};
    if (data.update_available && typeof sidebarV5.setUpdateBadge === "function") {
      sidebarV5.setUpdateBadge("settings", true, data.latest_version);
    }
  } catch { /* silencieux */ }
}

// Re-check une fois par heure (cache backend, pas d'appel reseau).
// Cf issue #89 : stocker l'ID pour clear au logout.
_updateBadgeInterval = setInterval(_checkUpdateBadge, 3600000);

/* === V7.6.0 Notification center — polling 30s ============= */

async function _initNotificationPolling() {
  if (typeof notifCenter.startNotificationPolling === "function") {
    notifCenter.startNotificationPolling(30000);
    return;
  }
  // Fallback : polling manuel via get_notifications_unread_count.
  // Cf issue #89 : check hasToken() au debut de chaque tick + stocker l'ID
  // pour clear au logout (evite boucle 401 + leak).
  if (_notificationFallbackInterval != null) return;
  _notificationFallbackInterval = setInterval(async () => {
    if (!hasToken()) return;
    try {
      const res = await apiPost("get_notifications_unread_count");
      const count = (res && res.data && res.data.count) || (res && res.count) || 0;
      if (typeof topBarV5.updateNotificationBadge === "function") {
        topBarV5.updateNotificationBadge(count);
      }
    } catch { /* silencieux */ }
  }, 30000);
}

// Cf issue #89 : cleanup central des intervals au logout. Appele par
// clearToken() via le mecanisme onClearToken (state.js).
onClearToken(() => {
  if (_sidebarCountersInterval != null) {
    clearInterval(_sidebarCountersInterval);
    _sidebarCountersInterval = null;
  }
  if (_updateBadgeInterval != null) {
    clearInterval(_updateBadgeInterval);
    _updateBadgeInterval = null;
  }
  if (_notificationFallbackInterval != null) {
    clearInterval(_notificationFallbackInterval);
    _notificationFallbackInterval = null;
  }
});

/* === V3-05 : demo wizard premier-run ====================== */

async function _initDemoModeIfNeeded() {
  if (!hasToken()) return;
  try {
    const settingsRes = await cachedGetSettings();
    const settings = (settingsRes && settingsRes.data) || {};
    const statsRes = await apiPost("get_global_stats");
    const stats = (statsRes && statsRes.data) || {};
    const { showDemoWizardIfFirstRun, renderDemoBanner } = await import("./views/demo-wizard.js");
    await showDemoWizardIfFirstRun(settings, stats);
    await renderDemoBanner();
  } catch (err) {
    console.warn("[v5 boot] init demo", err);
  }
}

/* === Theme ================================================ */

async function _loadDashTheme() {
  if (!hasToken()) return;
  try {
    const res = await cachedGetSettings();
    if (res && res.data) {
      const s = res.data;
      document.body.dataset.theme = s.theme || "luxe";
      document.body.dataset.animation = s.animation_level || "moderate";
      document.documentElement.dataset.effects = s.effects_mode || "restraint";
      const root = document.documentElement;
      const _map = (v, lo, hi) => lo + ((v || 50) - 0) * (hi - lo) / 100;
      root.style.setProperty("--animation-speed", _map(s.effect_speed, 0.3, 3));
      root.style.setProperty("--glow-intensity", _map(s.glow_intensity, 0, 0.5));
      root.style.setProperty("--light-intensity", _map(s.light_intensity, 0, 0.3));
      root.style.setProperty("--effect-opacity", _map(s.light_intensity, 0, 0.08));
    }
  } catch { /* silencieux */ }
}

async function _applyTheme(theme) {
  // V7-fix : (1) appliquer sur <html> ET <body> pour couvrir tous les selecteurs CSS.
  // (2) merger avec les settings existants au lieu de remplacer (sinon les autres
  // settings sont ecrases par save_settings({theme}) qui contient SEULEMENT theme).
  document.documentElement.setAttribute("data-theme", theme);
  document.body.setAttribute("data-theme", theme);
  try {
    // V2-B : cachedGetSettings beneficie du cache warm si le boot vient juste
    // de finir. apiPost("settings/save_settings") invalide le cache automatiquement.
    const cur = await cachedGetSettings();
    const merged = { ...((cur && cur.data) || {}), theme };
    await apiPost("settings/save_settings", { settings: merged });
  } catch { /* silencieux : le visuel est deja applique */ }
}

/* === A propos modal ====================================== */

function _openAboutModal() {
  // La modale About v4 est auto-init via about.js (DOMContentLoaded).
  // Elle expose window.openAboutModal si chargee.
  if (typeof window.openAboutModal === "function") {
    window.openAboutModal();
  } else {
    // Fallback : trigger programmatique du bouton legacy s'il existe
    const legacyBtn = document.getElementById("btnDashAbout");
    if (legacyBtn) legacyBtn.click();
    else console.info("[v5] About modal pas encore portee");
  }
}

/* === V3-01 : redirige clic sur integration desactivee vers Settings ====== */

document.addEventListener("click", (ev) => {
  const item = ev.target.closest(".v5-sidebar-item--disabled");
  if (!item) return;
  ev.preventDefault();
  ev.stopPropagation();
  navigateTo("/settings");
}, true);

/* === Compat helpers (anciens listeners externes) ========= */
// Conservation de hookNav pour le HTML ".nav-btn" si jamais des scripts legacy
// l'attendent encore (ex: tests E2E). Sans erreur si la sidebar v5 est mountee.
function hookNav() {
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const route = btn.dataset.route;
      if (route) navigateTo(route);
    });
  });
}
// Appel conditionnel : aucun .nav-btn dans le shell v5, no-op normalement.
document.addEventListener("DOMContentLoaded", hookNav);
