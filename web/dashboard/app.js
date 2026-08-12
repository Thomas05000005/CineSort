/* app.js — Bootstrap dashboard CineSort v7.6.0 (V5B-01 : v5 active)
 *
 * Vague 5B : active le shell v5 (sidebar-v5 + top-bar-v5 + breadcrumb +
 * notification-center) et cable les 7 vues v5 ESM portees en V5bis.
 *
 * Coexistence : les vues v4 dashboard (jellyfin/plex/radarr/logs) restent
 * actives sur leurs routes ; V5C les portera ou supprimera.
 */

// Marker tres haut dans le module pour savoir si app.js a parse et execute.
// Si window.__APP_JS_LOADED reste undefined apres boot, le module n a pas
// reussi a charger (import casse, parse error, CSP block).
window.__APP_JS_LOADED = "parse-start";

import { $$ } from "./core/dom.js";
import { hasToken, setToken, onClearToken, markTokenReady, markTokenAbsent } from "./core/state.js";

window.__APP_JS_LOADED = "imports-done";

/* H1 fix : window.onerror global pour capturer les erreurs JS non-attrapees
 * (sinon : page blanche silencieuse). Affiche un toast minimaliste. */
(function _installGlobalErrorHandler() {
  let _errorBannerShown = false;
  function _showErrorBanner(msg) {
    if (_errorBannerShown) return;
    _errorBannerShown = true;
    try {
      // Fix audit 2026-06-07 UX : message generique francais actionable a la place
      // du brut technique (TypeError, NetworkError...). Details internes restent
      // logges console + data-attribute pour copy-debug. Memoire user : pas de
      // jargon, pas d'Error 500, action explicite (recharger).
      const banner = document.createElement("div");
      banner.style.cssText = "position:fixed;top:0;left:0;right:0;background:#DC2626;color:#fff;padding:8px 16px;z-index:99999;font-family:sans-serif;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,0.3);";
      banner.dataset.cinesortErrorDetails = String(msg || "").substring(0, 400);

      const label = document.createElement("strong");
      label.textContent = "Une erreur inattendue est survenue.";
      banner.appendChild(label);
      banner.appendChild(document.createTextNode(" Recharger la page ? "));

      const reloadBtn = document.createElement("button");
      reloadBtn.style.cssText = "margin-left:8px;background:#fff;border:1px solid #fff;color:#DC2626;padding:2px 10px;border-radius:4px;cursor:pointer;font-weight:600";
      reloadBtn.textContent = "Recharger";
      reloadBtn.addEventListener("click", () => {
        try { window.location.reload(); } catch (e) { /* noop */ }
      });
      banner.appendChild(reloadBtn);

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
  // Fix audit 2026-05-25 (v1.5.4) Vague I : enrichir la banniere avec
  // filename:line:col (et 1ere frame de stack quand dispo). En mode natif
  // pywebview, DevTools est inaccessible, donc le seul moyen de pinpoint
  // le site coupable d'une erreur est de l'inscrire dans la banniere.
  function _formatLocation(ev) {
    try {
      const stackFirstFrame = (ev && ev.error && typeof ev.error.stack === "string")
        ? (ev.error.stack.split("\n").find((l) => l && l.trim() && !/^Error/i.test(l)) || "").trim()
        : "";
      if (stackFirstFrame) return stackFirstFrame.substring(0, 180);
      const file = (ev && ev.filename) ? String(ev.filename).split("/").pop() : "?";
      const line = (ev && ev.lineno != null) ? ev.lineno : "?";
      const col = (ev && ev.colno != null) ? ev.colno : "?";
      return `${file}:${line}:${col}`;
    } catch (_e) { return ""; }
  }
  window.addEventListener("error", (ev) => {
    console.error("[window.onerror]", ev.message, ev.filename, ev.lineno, ev.colno, ev.error);
    // Fix audit 2026-06-07 UX critical : details internes (loc, message brut)
    // restent en console + data-attribute du banner pour copy-debug, banner
    // affiche un message generique francais actionable.
    const loc = _formatLocation(ev);
    _showErrorBanner(loc ? `${ev.message} | ${loc}` : ev.message);
  });
  window.addEventListener("unhandledrejection", (ev) => {
    console.error("[unhandledrejection]", ev.reason);
    const reason = ev.reason;
    let loc = "";
    try {
      if (reason && typeof reason.stack === "string") {
        const frame = reason.stack.split("\n").find((l) => l && l.trim() && !/^Error/i.test(l)) || "";
        loc = frame.trim().substring(0, 180);
      }
    } catch (_e) { /* noop */ }
    const msg = String(reason && reason.message ? reason.message : reason);
    _showErrorBanner(loc ? `${msg} | ${loc}` : msg);
  });
})();

/* --- Detection mode natif (pywebview desktop) ---
 * 3 sources, par ordre de fiabilite croissante :
 *   1) ?native=1 dans l'URL (boot initial fourni par app.py)
 *   2) flag persiste en localStorage (survit aux refresh / WebView2 cache)
 *   3) window.chrome.webview present (signature WebView2 injectee par l'host
 *      WebView2 quand la page tourne dans une app native, perdure meme apres
 *      perte des query string).
 * Une seule source = mode natif. On persiste le flag pour les boots suivants
 * (au cas ou WebView2 reload sans la query).
 */
const NATIVE_FLAG_KEY = "cinesort.native";
(function _detectNativeBoot() {
  try {
    const params = new URLSearchParams(window.location.search);
    const ntoken = params.get("ntoken");
    const nativeFromQuery = params.get("native") === "1";
    let nativeFromStorage = false;
    try { nativeFromStorage = localStorage.getItem(NATIVE_FLAG_KEY) === "1"; } catch { /* no-op */ }
    const nativeFromWebView2 = !!(window.chrome && window.chrome.webview);
    const native = nativeFromQuery || nativeFromStorage || nativeFromWebView2;
    if (native) {
      window.__CINESORT_NATIVE__ = true;
      document.documentElement.classList.add("cinesort-native-pending");
      try { localStorage.setItem(NATIVE_FLAG_KEY, "1"); } catch { /* no-op */ }
    }
    if (ntoken) {
      setToken(ntoken, true);  // persist (setToken appelle markTokenReady en interne)
      // Purger le token de l'URL pour ne pas le laisser dans l'historique.
      const url = new URL(window.location.href);
      url.searchParams.delete("ntoken");
      // Quand on a un ntoken valide en boot natif, on force /accueil pour
      // eviter que le router envoie vers /login. Sans ce fix :
      //   - si hash vide : currentHash() retourne "/login" par defaut
      //   - si hash = "#/login" (restore webview2 cache) : le router reste
      //     sur la page login meme avec un token valide
      // On considere que /login n'a aucun sens en mode natif puisque le
      // token est deja fourni. On garde le hash uniquement s'il pointe
      // vers une page valide (pas /login).
      const currentHash = window.location.hash;
      const targetHash = (!currentHash || currentHash === "#/login")
        ? "#/accueil"
        : currentHash;
      // Garder ?native=1 si present
      window.history.replaceState({}, "", url.pathname + (native ? "?native=1" : "") + targetHash);
    } else {
      // V1.5.0 fix bug #1 : pas de ntoken dans l'URL. Soit on a deja un
      // token en storage (boot natif sur reload WebView2 cache, ou mode
      // web avec token persiste "Rester connecte"), soit on n'en aura
      // jamais (mode web pre-login). Dans tous les cas, on debloque les
      // requetes apiPost/apiGet pour qu'elles partent avec le token
      // actuel (ou sans, et echouent proprement avec 401 -> redirect
      // login en mode web).
      try {
        const hasStored = !!(sessionStorage.getItem("cinesort.dashboard.token")
                          || (localStorage.getItem("cinesort.dashboard.persist") === "1"
                              && localStorage.getItem("cinesort.dashboard.token")));
        if (hasStored) {
          markTokenReady();
        } else {
          // FIX 2026-06-05 : en mode natif sans token, on differe le deblocage
          // pour eviter la salve 401 sur les 4 fetchs initiaux (un retry de
          // setToken peut arriver via pywebview entre temps). En mode web,
          // c'est immediat (la 401 redirige vers /login normalement).
          const _nativeBoot = !!(window.__CINESORT_NATIVE__
                              || (window.chrome && window.chrome.webview)
                              || (window.location && (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost")));
          markTokenAbsent({ native: _nativeBoot });
        }
      } catch {
        markTokenAbsent();
      }
    }
  } catch (e) {
    console.warn("[dash-boot] detection native echouee", e);
    // En cas d'erreur de detection, on debloque les requetes pour eviter
    // un hang. Le deadline 2s dans state.js sert de filet de secours.
    try { markTokenAbsent(); } catch { /* no-op */ }
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
// Phase 2 (spec 04 Shell 3 zones) : inspecteur droit persistant.
import * as rightPanel from "./components/right-panel.js";

// === Vues v5 actives (refonte 2026-05 : alias legacy migres en redirections) ===
import { initLogin } from "./views/login.js";
// Phase 3.1 (spec 05-accueil.md) : nouvelle vue Accueil refondue. Active sur
// /accueil ; les anciennes routes /home /status /qij redirigent vers /accueil.
import { initAccueil, unmountAccueil } from "./views/accueil.js";        // /accueil (nouvelle UI)
// V7-fix : vue Processing v5 dediee (separe Bibliotheque "consulter" de
// Traitement "agir : scan/review/apply"). /processing reste fonctionnelle :
// elle est utilisee en INTERNE par traitement.js et qij.js comme etape stepper.
import { initProcessing, unmountProcessing } from "./views/processing.js"; // /processing (usage interne stepper)
// Phase 3.1-D (spec 11-parametres.md) : nouvelle vue Paramètres avec sub-sidebar
// 10 categories. Active sur /parametres ; /settings redirige vers /parametres
// (preservation du fragment de section).
import { initParametres, unmountParametres } from "./views/parametres.js"; // /parametres (nouvelle UI)
// Phase 3.5 (spec 12-aide.md) : nouvelle vue Aide refondue (5 sections + recherche).
// Active sur /aide ; /help et /logs redirigent vers /aide (le diagnostic +
// journal sont integres dans la vue Aide).
import { initAide, unmountAide } from "./views/aide.js"; // /aide (nouvelle UI)
// Phase 3.3 (spec 01-doublons.md) : vue Doublons refondue. Active sur /doublons.
import { initDoublons, unmountDoublons } from "./views/doublons.js"; // /doublons (nouvelle UI)
// Phase 3.4 (spec 09-historique.md) : nouvelle vue Historique refondue
// (timeline groupee par jour + filtres + inspecteur 5 onglets).
import { initHistorique, unmountHistorique, initRunDetailPage, unmountRunDetailPage } from "./views/historique.js"; // /historique (nouvelle UI) + /run/:id (page standalone)
import { initStatistiques, unmountStatistiques } from "./views/statistiques.js"; // /statistiques (vague C)
// Phase 3.4 (spec 10-qualite.md) : nouvelle vue Qualité audit transverse
// (6 sections + filtres + re-calcul scores).
import { initQualite, unmountQualite } from "./views/qualite.js"; // /qualite (nouvelle UI)
// Phase 3.3 (spec 08-traitement.md) : nouvelle vue Traitement workflow 5 etapes
// (Analyse / Verification / Validation / Doublons / Apply). PR squelette : le
// contenu detaille de chaque etape reutilise temporairement la vue legacy.
import { initTraitement, unmountTraitement } from "./views/traitement.js"; // /traitement
// Phase 3.2 (spec 07-bibliotheque.md) : nouvelle Bibliothèque (squelette).
// La grille de posters + scroll infini + bulk actions seront portes en PRs
// incrementales 3.2-A/B/C. La vue legacy /library reste accessible.
import { initBibliotheque, unmountBibliotheque } from "./views/bibliotheque.js"; // /bibliotheque

// === Vues v5 conservees pour features uniques sans equivalent v4 ===
// D1 (R8 seam #3) : la vue standalone views/film-detail.js (jumeau buggé R8-053/054/055)
// est SUPPRIMÉE. La route /film/:id est servie par le COMPOSANT (mode B = page standalone,
// conçu pour /film/:id) — flux d'id identique (route id -> row_id -> library/get_film_full),
// donc 0 lien mort et 0 changement d'appelant (home-widgets/qualite/historique).
import { renderFilmDetail } from "./components/film-detail.js";

// === Helpers UI legacy preserves ===
import { initKeyboard } from "./core/keyboard.js";
import { initDropHandlers } from "./core/drop.js";
import { initCommandPalette } from "./components/command-palette.js";
import { initCopyToClipboard } from "./components/copy-to-clipboard.js";
import { initAutoTooltip } from "./components/auto-tooltip.js";
import { initGlossaryTooltips } from "./components/glossary-tooltip.js";
import { decorateMainButtons } from "./components/shortcut-tooltip.js";
// mega-hotfix frontend_ui_polish (#6) : banniere globale "scan en cours" pour
// que l'utilisateur ne perde plus de vue qu'un scan tourne quand il navigue
// hors de la vue Traitement.
import { initScanBanner } from "./components/scan-banner.js";
// Confetti : side-effect import (expose window.launchConfetti)
import "./components/confetti.js";

// V2-C R4-MEM-5 : purge des drafts review.js expires (TTL 30j) au boot.
// Module dedie dans core/ pour eviter d'importer ./views/review.js depuis app.js
// (interdit par test_v5c_cleanup — review.js fait partie des vues v4 retirees).
import { cleanupExpiredDrafts } from "./core/drafts-cleanup.js";

/* === Routes v5 ESM ======================================== */

registerRoute("/login", { view: "view-login", init: initLogin });

// === Helper : redirection rétrocompat vers route canonique FR =============
// Extrait le fragment de section depuis le hash courant et redirige vers la
// route canonique en preservant ce fragment (ex: "#/library#step-analyse" ->
// "#/bibliotheque#step-analyse"). Aucun unmount : la navigation suivante va
// re-router immediatement vers la cible.
function _legacyRedirect(legacyName, canonicalRoute) {
  return (_el, _opts) => {
    const currentHash = (typeof window !== "undefined" && window.location && window.location.hash) || "";
    const re = new RegExp(`^#/${legacyName}(?:#(.+))?$`);
    const sectionMatch = currentHash.match(re);
    const fragment = sectionMatch && sectionMatch[1] ? `#${sectionMatch[1]}` : "";
    window.location.hash = `#${canonicalRoute}${fragment}`;
  };
}

// === Routes canoniques FR (refonte 2026-05-17 spec 04 Shell 3 zones) ======
registerRoute("/film/:id", {
  view: "view-film-detail",
  guard: requireAuth,
  // D1 : rendu par le composant (mode B), plus la vue standalone supprimée.
  init: (el, opts) =>
    renderFilmDetail({ mode: "B", rowId: opts && opts.params ? opts.params.id : undefined, container: el }),
});
// /processing reste fonctionnelle : utilisee en INTERNE par traitement.js et
// qij.js comme etape stepper du workflow (scan -> review -> apply). Mount
// dedie #view-processing (vide dans index.html, initProcessing fait
// container.innerHTML lui-meme).
// E7-ter (revue Lot E) : cleanup retourne en SYNCHRONE (pattern des routes
// canoniques) — le .then du router sur un init async pouvait ecraser le
// cleanup d'une autre vue si l'utilisateur naviguait avant la resolution.
registerRoute("/processing", {
  view: "view-processing",
  guard: requireAuth,
  init: (el, opts) => {
    initProcessing(el, opts).catch((e) => console.error("[processing] init:", e));
    return unmountProcessing;
  },
});

// === Alias rétrocompat : redirections vers routes canoniques FR ===========
// Les anciennes URLs (/home /status /library /quality /help /logs /jellyfin
// /plex /radarr /qij /settings) restent registrees pour les bookmarks et liens
// externes deja partages, mais elles redirigent toutes immediatement vers la
// nouvelle route canonique en preservant le fragment de section/ancre.
// La vue ciblee s'affichera apres la navigation (re-routage).
registerRoute("/home",     { view: "view-status",   guard: requireAuth, init: _legacyRedirect("home", "/accueil") });
registerRoute("/status",   { view: "view-status",   guard: requireAuth, init: _legacyRedirect("status", "/accueil") });
registerRoute("/qij",      { view: "view-qij",      guard: requireAuth, init: _legacyRedirect("qij", "/accueil") });
registerRoute("/library",  { view: "view-library",  guard: requireAuth, init: _legacyRedirect("library", "/bibliotheque") });
registerRoute("/quality",  { view: "view-qij",      guard: requireAuth, init: _legacyRedirect("quality", "/qualite") });
registerRoute("/help",     { view: "view-help",     guard: requireAuth, init: _legacyRedirect("help", "/aide") });
// /logs redirige vers /aide#diagnostic (journal integre dans la vue Aide).
registerRoute("/logs",     { view: "view-qij",      guard: requireAuth, init: (_el, _opts) => {
  window.location.hash = "#/aide#diagnostic";
} });
// /jellyfin /plex /radarr : redirigent vers /parametres avec ancre integrations.
registerRoute("/jellyfin", { view: "view-qij",      guard: requireAuth, init: (_el, _opts) => {
  window.location.hash = "#/parametres#integrations-jellyfin";
} });
registerRoute("/plex",     { view: "view-qij",      guard: requireAuth, init: (_el, _opts) => {
  window.location.hash = "#/parametres#integrations-plex";
} });
registerRoute("/radarr",   { view: "view-qij",      guard: requireAuth, init: (_el, _opts) => {
  window.location.hash = "#/parametres#integrations-radarr";
} });
// /settings : redirection deja active depuis le commit 0280f2a. Conserve le
// même pattern pour homogeneite (helper _legacyRedirect).
registerRoute("/settings", { view: "view-settings", guard: requireAuth, init: _legacyRedirect("settings", "/parametres") });

// Phase 2-B (spec 04 Shell 3 zones) : routes francaises canoniques.
// Les anciennes URLs (/home /library /processing /settings /help) restent en
// alias rétrocompat pour les bookmarks et les liens externes deja partages.
// Phase 3.1 : /accueil cable la nouvelle vue refondue (spec 05-accueil.md).
registerRoute("/accueil", { view: "view-status", guard: requireAuth, init: (el, opts) => { initAccueil(el, opts); return unmountAccueil; } });
// Phase 3.3 : /traitement cable la nouvelle vue refondue (spec 08).
registerRoute("/traitement", { view: "view-processing", guard: requireAuth, init: (el, opts) => { initTraitement(el, opts); return unmountTraitement; } });
// Phase 3.2 : /bibliotheque cable la nouvelle grille refondue (spec 07).
registerRoute("/bibliotheque", { view: "view-library", guard: requireAuth, init: (el, opts) => { initBibliotheque(el, opts); return unmountBibliotheque; } });
// Phase 3.4 : /historique cable la nouvelle vue Historique refondue (spec 09).
// La vue cherche un mount point #view-historique ; on garde view-qij comme
// container car le view-historique n'existe pas dans le DOM, et initHistorique
// remplit le container avec son propre HTML.
registerRoute("/historique", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initHistorique(el, opts); return unmountHistorique; } });
// Phase 5 : page standalone /run/:id (vue complete d'un run, 4 onglets en grand).
// Reutilise le mount point view-qij car aucun view-run-detail dans le DOM ;
// initRunDetailPage remplit le container avec son propre HTML.
registerRoute("/run/:id", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initRunDetailPage(el, opts); return unmountRunDetailPage; } });
// Phase 3.4 : /qualite cable la nouvelle vue Qualité refondue (spec 10).
registerRoute("/qualite", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initQualite(el, opts); return unmountQualite; } });
// Vague C : trois analyses qui existaient cote backend et qu'aucun code du
// dashboard n'appelait. Meme mount point que les autres vues « pleine page »
// (view-qij) : la vue remplit elle-meme son container.
registerRoute("/statistiques", { view: "view-qij", guard: requireAuth, init: (el, opts) => { initStatistiques(el, opts); return unmountStatistiques; } });

// Phase 3.1-D : /parametres cable la nouvelle vue refondue (spec 11-parametres.md).
registerRoute("/parametres", { view: "view-settings", guard: requireAuth, init: (el, opts) => { initParametres(el, opts); return unmountParametres; } });
// Phase 3.5 : /aide cable la nouvelle vue refondue (spec 12-aide.md).
registerRoute("/aide", { view: "view-help", guard: requireAuth, init: (el, opts) => { initAide(el, opts); return unmountAide; } });
// Phase 3.3 : /doublons cable la nouvelle vue refondue (spec 01-doublons.md).
registerRoute("/doublons", { view: "view-library", guard: requireAuth, init: (el, opts) => { initDoublons(el, opts); return unmountDoublons; } });

/* === Mapping ID sidebar v5 -> route URL ==================== */

// V7-fusion Phase 3 puis Phase 2-B (refonte 2026-05-17) :
// - sidebar id "home"        -> route /accueil (alias /home /status)
// - sidebar id "processing"  -> route /traitement (alias /processing)
// - sidebar id "library"     -> route /bibliotheque (alias /library)
// - sidebar id "quality"     -> route /qualite (alias /quality, ex tab QIJ)
// - sidebar id "history"     -> route /historique (alias /qij, ex tab QIJ)
// - sidebar id "settings"    -> route /parametres (alias /settings)
// - sidebar id "help"        -> route /aide (alias /help)
const SIDEBAR_ROUTE_ALIAS = {
  home: "/accueil",
  processing: "/traitement",
  library: "/bibliotheque",
  doublons: "/doublons",  // AUDIT 2026-06-13 (R5-E) : entree menu Doublons.
  quality: "/qualite",
  history: "/historique",
  statistiques: "/statistiques",
  settings: "/parametres",
  help: "/aide",
  // Compat ascendante : si la sidebar utilise encore l'id "qij" (v7-fusion),
  // on route vers /qualite par defaut (entree principale post-split).
  qij: "/qualite",
};

function _routeFromSidebarId(routeId) {
  return SIDEBAR_ROUTE_ALIAS[routeId] || ("/" + routeId);
}

// Mapping inverse : route URL -> id sidebar pour highlight l'entree active.
// Couvre les routes francaises (canoniques) ET les anciennes routes (rétrocompat).
const _ROUTE_TO_SIDEBAR_ID = {
  accueil: "home", home: "home", status: "home",
  traitement: "processing", processing: "processing",
  bibliotheque: "library", library: "library",
  doublons: "doublons",  // AUDIT 2026-06-13 (R5-E) : highlight l'entree Doublons.
  qualite: "quality", quality: "quality",
  historique: "history", logs: "history",
  parametres: "settings", settings: "settings",
  aide: "help", help: "help",
  // Routes integrations legacy : pas d'entree dediee dans la nouvelle sidebar,
  // on highlight Paramètres (où les integrations vivent en spec 11).
  jellyfin: "settings", plex: "settings", radarr: "settings",
  // /qij legacy : highlight Qualité (entree principale post-split).
  qij: "quality",
};

function _currentRouteId() {
  // Extrait l'id pour la sidebar (ex: "#/library" -> "library", "#/film/42" -> "film")
  const hash = (window.location.hash || "#/accueil").replace(/^#\//, "");
  const base = hash.split("?")[0].split("#")[0];
  const first = base.split("/")[0];
  return _ROUTE_TO_SIDEBAR_ID[first] || first || "home";
}

/* === Mount shell v5 ====================================== */

async function _mountV5Shell() {
  // Robustesse : afficher le shell EN PREMIER. Sans cela, si un render
  // plante en cours de route (sidebar, topbar, rightPanel), app-shell reste
  // .hidden -> fenetre noire vide. Mieux vaut un shell incomplet visible
  // qu'un noir total.
  const appShell = document.getElementById("app-shell");
  if (appShell) appShell.classList.remove("hidden");

  const sidebarMount = document.getElementById("v5SidebarMount");
  const topBarMount = document.getElementById("v5TopBarMount");
  const breadcrumbMount = document.getElementById("v5BreadcrumbMount");
  const rightPanelMount = document.getElementById("v5RightPanelMount");

  // Chaque render est isole dans try/catch : un crash dans un composant
  // ne doit pas empecher l'instanciation des autres ni du router/views.

  // Sidebar v5 (8 entrees + integrations + footer About)
  try {
    sidebarV5.render(sidebarMount, {
      activeRoute: _currentRouteId(),
      onNavigate: (routeId) => navigateTo(_routeFromSidebarId(routeId)),
      onAboutClick: _openAboutModal,
    });
  } catch (e) { console.warn("[shell] sidebarV5.render", e); }

  // Theme initial depuis settings (fallback "luxe")
  // V2-B : cachedGetSettings dedup les 4+ appels paralleles au boot.
  let theme = "luxe";
  try {
    const settingsRes = await cachedGetSettings().catch(() => ({ data: {} }));
    const settings = settingsRes && settingsRes.data ? settingsRes.data : {};
    theme = settings.theme || "luxe";
  } catch (e) { console.warn("[shell] cachedGetSettings", e); }

  // Top-bar v5 (search + notif + theme switcher)
  // FIX 2026-06-07 : fetch unread count AVANT render pour eviter le flash
  // "cloche sans badge" pendant ~3s (delai anti-avalanche de startNotificationPolling).
  // En cas d'echec (backend KO, 401 token), on retombe sur 0 — le polling
  // mettra a jour le badge au prochain tick.
  let initialNotifCount = 0;
  try {
    if (typeof notifCenter.getUnreadCount === "function") {
      initialNotifCount = await notifCenter.getUnreadCount().catch(() => 0);
    }
  } catch (e) { console.warn("[shell] notifCenter.getUnreadCount", e); }
  try {
    topBarV5.render(topBarMount, {
      title: "CineSort",
      subtitle: "",
      theme,
      notificationCount: initialNotifCount,
      onSearchClick: () => window.dispatchEvent(new CustomEvent("cinesort:command-palette")),
      onNotifClick: () => notifCenter.toggleNotifications(),
      onThemeChange: _applyTheme,
    });
  } catch (e) { console.warn("[shell] topBarV5.render", e); }

  // Breadcrumb (initialement vide, mis a jour par le router via syncShell)
  try {
    if (breadcrumbMount && typeof breadcrumb.render === "function") {
      breadcrumb.render(breadcrumbMount, []);
    }
  } catch (e) { console.warn("[shell] breadcrumb.render", e); }

  // Phase 2 (spec 04) : inspecteur droit. Etat adaptatif par route au hashchange.
  try {
    if (rightPanelMount) {
      rightPanel.render(rightPanelMount);
      const _syncRightPanelToRoute = () => {
        const hash = (window.location.hash || "#/accueil").replace(/^#/, "");
        rightPanel.adaptToRoute(hash.split("#")[0]);
      };
      window.addEventListener("hashchange", _syncRightPanelToRoute);
      _syncRightPanelToRoute();
    }
  } catch (e) { console.warn("[shell] rightPanel.render", e); }

  // FAB Aide V3-08 (bouton flottant ?)
  try {
    if (typeof topBarV5.mountHelpFab === "function") {
      topBarV5.mountHelpFab({ onClick: () => navigateTo("/aide") });
    }
  } catch (e) { console.warn("[shell] mountHelpFab", e); }
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

// Cf #92 quick win #2 : refresh immediat des badges sidebar apres un undo.
// Sans ca, les compteurs restent stales jusqu'au tick 30s de l'interval,
// donnant l'impression que l'undo n'a pas fonctionne (perte de confiance).
//
// Ultra-audit 2026-08-03 (N01) : ce listener etait ORPHELIN — aucun module
// n'emettait plus `cinesort:undo` depuis la migration ESM, donc les badges
// restaient bien stales jusqu'au tick 30 s. Les deux proprietaires reels de
// l'undo (views/traitement.js `_onUndoExecute` et views/historique.js
// `_doUndoApply`) emettent desormais l'evenement apres un undo REUSSI.
window.addEventListener("cinesort:undo", () => {
  // Best-effort : si la fonction n'est pas encore declaree (avant boot
  // complet), l'event est juste ignore.
  if (typeof _loadSidebarCounters === "function") {
    _loadSidebarCounters().catch(() => { /* silencieux */ });
  }
});

// Ultra-audit 2026-08-03 (N09) : `cinesort:refresh` etait dispatche a DEUX
// endroits (F5 dans core/keyboard.js, entree « Rafraichir la vue » de la
// palette Ctrl+K) et ecoute a ZERO. La palette se fermait sans rien
// rafraichir, alors que son hint annonce « Equivalent F5 ».
//
// Fusion main <- PR #873 : les deux branches avaient corrige ce meme defaut,
// chacune de son cote — ce lot posait l'auditeur ICI (`currentRoute()` +
// navigateTo), la revue post-merge le posait dans `core/keyboard.js`
// (`_refreshCurrentView`, au plus pres du dispatch). Les garder tous les deux
// aurait fait DEUX `navigateTo` par F5, donc deux hashchange synchrones, donc
// un double cleanup + double init() de la vue : double refetch reseau, et le
// second remontage annulant les requetes du premier (abortCurrentNav). On ne
// garde donc que celui de core/keyboard.js, deja sur main, dont l'auditeur est
// une reference de module NOMMEE (addEventListener idempotent sur un double
// initKeyboard) et qui preserve la query du hash courant.
// L'unicite est verrouillee par `test_un_seul_auditeur_de_cinesort_refresh`.

/* === Sync sidebar/breadcrumb au changement de route ====== */

const ROUTE_BREADCRUMBS = {
  // === Routes FR canoniques (refonte 2026-05-17 spec 04 Shell 3 zones) ===
  "/accueil":      [{ label: "Accueil" }],
  "/traitement":   [{ label: "Traitement" }],
  "/bibliotheque": [{ label: "Bibliothèque" }],
  "/qualite":      [{ label: "Qualité" }],
  "/historique":   [{ label: "Historique" }],
  "/parametres":   [{ label: "Paramètres" }],
  "/aide":         [{ label: "Aide" }],
  // /processing reste fonctionnelle (usage interne stepper traitement/qij).
  "/processing":   [{ label: "Traitement" }],
  // Routes alias (/home /status /library /quality /help /logs /jellyfin /plex
  // /radarr /qij /settings) sont des REDIRECTIONS immediates : leur breadcrumb
  // n'est jamais rendu car la navigation est re-routee avant le sync shell.
  // Aucune entree necessaire ici.
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

window.__APP_JS_LOADED = "module-end-reached";

document.addEventListener("DOMContentLoaded", async () => {
  window.__APP_JS_LOADED = "domcontentloaded-fired";
  // V7-fix : bypass login DOIT etre evalue AVANT toute init suceptible de throw,
  // sinon une erreur d'init silencieuse empeche le bypass (et l'utilisateur voit
  // le login alors que le token est present).
  // Detection 4 signaux (= router._isNativeMode / api._isNativeMode) :
  //   1. window.__CINESORT_NATIVE__ (pose par l'IIFE _detectNativeBoot)
  //   2. window.pywebview.api (signature pywebview FIABLE)
  //   3. hostname 127.0.0.1 / localhost (signal local infaillible)
  //   4. localStorage cinesort.native (persiste aux refresh)
  // Une seule source suffit. Critique pour decider du mount du shell V5.
  const _isNativeMode = () => {
    if (window.__CINESORT_NATIVE__) return true;
    if (window.pywebview && window.pywebview.api) return true;
    const host = window.location && window.location.hostname;
    if (host === "127.0.0.1" || host === "localhost") return true;
    try { if (localStorage.getItem("cinesort.native") === "1") return true; } catch { /* no-op */ }
    return false;
  };
  const isNative = _isNativeMode();
  if (isNative) {
    document.body.classList.add("is-native");
    window.__CINESORT_NATIVE__ = true;  // homogeneise pour le router/api downstream

    // Fix audit 2026-05-24 : WebView2 sans handler on_new_window_request bloque
    // silencieusement target="_blank" et window.open(). Les boutons GitHub /
    // TMDb / docs (aide.js, about.js, qualite.js) ne faisaient rien en natif.
    // On intercepte tous les clicks sur liens externes et on les delegue au
    // backend qui appelle webbrowser.open() pour ouvrir dans le navigateur OS.
    document.addEventListener("click", (e) => {
      const a = e.target.closest("a[href]");
      if (!a) return;
      const href = a.getAttribute("href") || "";
      // Liens externes uniquement (http/https hors notre origin)
      if (!/^https?:\/\//i.test(href)) return;
      try {
        const url = new URL(href, window.location.href);
        if (url.origin === window.location.origin) return; // lien interne, laisser
      } catch { /* URL invalide -> laisser navigation naturelle */ return; }
      e.preventDefault();
      // Appel REST silencieux (pas de toast - juste ouvre)
      apiPost("runtime/open_external_url", { url: href }).catch(() => { /* silent */ });
    }, true);
  }

  // Mode natif desktop (pywebview) : JAMAIS d'ecran login.
  // Le token est passe via ?ntoken=XXX au boot (cf _detectNativeBoot).
  // Si manquant, les appels API echoueront proprement avec 401 plutot
  // que bloquer l'utilisateur sur un ecran de connexion qui n'a pas de
  // sens en local (le bridge pywebview garantit deja l'origine).
  if (isNative) {
    if (!window.location.hash || window.location.hash === "#" || window.location.hash.includes("/login")) {
      window.location.hash = "#/accueil";
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
  // mega-hotfix frontend_ui_polish (#6) : banniere persistante "scan en cours".
  try { initScanBanner(); } catch (e) { console.warn("[boot] initScanBanner", e); }
  // V2-C R4-MEM-5 : purge drafts review.js expires (TTL 30j) — cleanup global au boot.
  try { cleanupExpiredDrafts(); } catch (e) { console.warn("[boot] cleanupExpiredDrafts", e); }

  // CRITIQUE : retirer .hidden de app-shell IMMEDIATEMENT en mode natif,
  // AVANT toute init async qui pourrait hang (initI18n, cachedGetSettings).
  // Sans ca, si un await bloque, app-shell reste hidden -> fenetre noire.
  // En mode natif, il n y a pas de raison d'attendre.
  if (isNative) {
    const _appShell = document.getElementById("app-shell");
    if (_appShell) _appShell.classList.remove("hidden");
    const _loginView = document.getElementById("view-login");
    if (_loginView) _loginView.classList.add("hidden");
  }

  startRouter();

  // V6-01-fix : initialiser i18n AVANT le mount (sinon t() retourne les cles brutes)
  // Charge fr.json + locale stockee, sans bloquer >500ms.
  // Promise.race avec timeout : si initI18n hang (network/file), on continue
  // sans bloquer le rendu du shell.
  // Fix audit 2026-05-25 (v1.5.5) Vague J : meme si on continue apres timeout
  // 1500ms, on garde la reference a la promesse pour qu'elle resolve en
  // arriere-plan et notify les observers (sidebar re-render avec les vrais
  // labels FR). Sans ca, en cas de boot lent, la sidebar restait avec les
  // cles brutes (sidebar.brand_name) jusqu'a un refresh manuel.
  const _i18nBoot = initI18n();
  try {
    await Promise.race([
      _i18nBoot,
      new Promise((resolve) => setTimeout(resolve, 1500)),
    ]);
  } catch (e) {
    console.warn("[boot] initI18n", e);
  }
  // Continue en arriere-plan : si timeout 1500ms expire mais le fetch finit
  // par reussir, _notifyObservers() dans initI18n re-render les composants.
  _i18nBoot.catch((e) => console.warn("[boot] initI18n background", e));

  // Si on est authentifie OU en mode natif desktop, monter le shell v5.
  // Le mode natif n'a pas besoin de token UI : le bridge pywebview garantit
  // l'origine et le serveur REST accepte le ntoken via URL/Bearer header.
  // Sans ce mount en natif, l'utilisateur voit une fenetre noire (sidebar
  // et top-bar pas instancies) si setToken a fail silencieusement au boot.
  if (hasToken() || isNative) {
    // V6-01-fix : synchroniser la locale depuis le setting backend si different
    // Timeout 1.5s : si l'appel API hang, on continue sans bloquer.
    try {
      const sres = await Promise.race([
        cachedGetSettings(),
        new Promise((resolve) => setTimeout(() => resolve({ data: {} }), 1500)),
      ]);
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
    // Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 3) : detecter ffprobe absent
    // au boot et afficher un banner persistant. Sans ffprobe le scoring est
    // casse -> l'utilisateur doit le savoir AVANT de lancer un scan qui sera
    // 100% en FAILED. Best-effort : try/catch silent.
    try { await _checkProbeToolsBoot(); } catch (e) { console.warn("[boot] probe tools check", e); }
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
  // Fix bug "polling sidebar 30s tourne meme onglet cache" :
  // BILAN_CORRECTIONS.md:846 annoncait visibility toggle, jamais implemente.
  // Pause le polling quand document.hidden, reprend au focus + reload immediat.
  if (!window.__cinesort_sidebar_visibility_bound__) {
    window.__cinesort_sidebar_visibility_bound__ = true;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        if (_sidebarCountersInterval != null) {
          clearInterval(_sidebarCountersInterval);
          _sidebarCountersInterval = null;
        }
      } else {
        _loadSidebarCounters();
        if (_sidebarCountersInterval == null) {
          _sidebarCountersInterval = setInterval(_loadSidebarCounters, 30000);
        }
      }
    });
  }
  await _checkIntegrationNav();
  await _checkUpdateBadge();
}

async function _loadSidebarCounters() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("run/get_sidebar_counters");
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

/** Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 3) : banner persistant si
 * ffprobe est introuvable au boot. Sans ffprobe, le scoring est casse :
 * probe.duration_s manquant -> tous les films en confidence basse -> UX HS.
 *
 * Le banner est non bloquant (icone + texte + bouton Paramètres) et se
 * dissimule des qu'on quitte la page ou via la croix. Idempotent : si deja
 * affiche, on ne re-cree pas.
 */
async function _checkProbeToolsBoot() {
  if (!hasToken() && !window.__CINESORT_NATIVE__) return;
  if (document.getElementById("ffprobe-missing-banner")) return; // deja affiche
  let payload = null;
  try {
    const res = await apiPost("runtime/get_probe_tools_status", {});
    payload = (res && res.data) || {};
  } catch { return; /* silencieux : si l'endpoint est KO on ne bloque rien */ }
  const tools = (payload && payload.tools) || {};
  const ffprobe = tools.ffprobe || {};
  if (ffprobe.available) return; // tout va bien
  try {
    // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high DV-005 : utilise une
    // classe CSS dediee (.ffprobe-banner) avec tokens du design system
    // (--sev-warning-*, --radius-sm, --sp-3) au lieu de styles inline en dur.
    // Icone alignee dans .ffprobe-banner__icon, variante sev-warning.
    // DV-001 z-index 150 conserve (entre contenu et chrome).
    const banner = document.createElement("div");
    banner.id = "ffprobe-missing-banner";
    banner.className = "ffprobe-banner ffprobe-banner--warning";
    banner.setAttribute("role", "alert");
    const icon = document.createElement("span");
    icon.className = "ffprobe-banner__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "⚠";
    banner.appendChild(icon);
    const title = document.createElement("strong");
    title.className = "ffprobe-banner__title";
    title.textContent = "ffprobe introuvable.";
    banner.appendChild(title);
    const msg = document.createElement("span");
    msg.className = "ffprobe-banner__msg";
    msg.textContent = "Le scoring qualite ne fonctionnera pas. Installe-le via winget (winget install ffmpeg) ou via Paramètres > Outils > Auto-install.";
    banner.appendChild(msg);
    const settingsBtn = document.createElement("a");
    settingsBtn.className = "ffprobe-banner__action";
    settingsBtn.href = "#/parametres";
    settingsBtn.textContent = "Ouvrir Paramètres";
    banner.appendChild(settingsBtn);
    const closeBtn = document.createElement("button");
    closeBtn.className = "ffprobe-banner__close";
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Fermer le bandeau");
    closeBtn.textContent = "Fermer";
    closeBtn.addEventListener("click", () => { banner.remove(); });
    banner.appendChild(closeBtn);
    document.body.appendChild(banner);
  } catch (e) { console.warn("[ffprobe banner] failed", e); }
}

/** V1-13 : badge "•" sur item Settings si MAJ disponible (cache backend). */
async function _checkUpdateBadge() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("runtime/get_update_info");
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
  // FIX 2026-06-05 (avalanche boot natif) : exclusion mutuelle stricte.
  // Si notifCenter.startNotificationPolling existe, on l'utilise EXCLUSIVEMENT
  // et on early-return AVANT toute condition pour empecher le fallback de
  // se demarrer en parallele (sinon : double polling sur l'unread_count -> 429).
  if (typeof notifCenter.startNotificationPolling === "function") {
    // S'assurer qu'aucun fallback precedemment cree ne survive.
    if (_notificationFallbackInterval != null) {
      clearInterval(_notificationFallbackInterval);
      _notificationFallbackInterval = null;
    }
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
      const res = await apiPost("runtime/get_notifications_unread_count");
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
    const statsRes = await apiPost("run/get_global_stats");
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
      // R8-072 (F5) : data-effects RETIRÉ — aucun CSS ne consommait dataset.effects
      // (effects_mode = fantôme cosmétique sans effet visuel ni contrôle UI).
      const root = document.documentElement;
      // Fix audit 2026-05-26 (v1.5.6) Vague L (theme-1) :
      // Avant : v||50 traitait 0 comme "valeur absente" et le remplacait par 50.
      // Du coup, l'utilisateur qui voulait DESACTIVER un effet (glow=0,
      // animation=0, light=0) voyait quand meme une intensite a 50% appliquee.
      // v??50 garde 0 (valeur legitime de l'utilisateur) et ne replace que les
      // null/undefined (valeur reellement absente) par 50.
      const _map = (v, lo, hi) => lo + ((v ?? 50) - 0) * (hi - lo) / 100;
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
  navigateTo("/parametres");
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
