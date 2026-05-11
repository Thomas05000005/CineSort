/* core/router.js — Hash router declaratif pour le dashboard SPA */

import { $, $$ } from "./dom.js";
import { hasToken, stopAllPolling } from "./state.js";
import { abortCurrent as abortCurrentNav } from "./nav-abort.js";

/**
 * Table de routes : { hash: { view, init, guard? } }
 * Populee par registerRoute().
 */
const _routes = new Map();
/** Routes paramétrées (ex: "/film/:id"). Compilees en regex au register. */
const _paramRoutes = [];
let _currentRoute = null;
let _notFoundHandler = null;
/** V2-C R4-MEM-4 : cleanup function de la vue actuelle (retournee par init() ou
 * unmount* exporte par la vue). Appelee avant chaque navigation pour stopper
 * timers/listeners et eviter les memory leaks. */
let _currentCleanup = null;

/**
 * Enregistre une route.
 * @param {string} hash - ex: "/login", "/status", "/film/:id"
 * @param {object} opts - { view: string, init: Function, guard?: Function }
 *
 * Support des patterns paramétrés "/film/:id" :
 *  - le segment ":nom" capture la valeur correspondante du hash
 *  - les params sont passés à init() via opts.params : init(el, { params })
 */
export function registerRoute(hash, opts) {
  if (hash.includes(":")) {
    const paramNames = [];
    const pattern = hash.replace(/:([A-Za-z_][\w]*)/g, (_m, name) => {
      paramNames.push(name);
      return "([^/#?]+)";
    });
    const re = new RegExp("^" + pattern + "$");
    _paramRoutes.push({ pattern: hash, regex: re, paramNames, opts });
  } else {
    _routes.set(hash, opts);
  }
}

/** Tente de matcher une route paramétrée. Retourne {opts, params} ou null. */
function _matchParamRoute(hashBase) {
  for (const r of _paramRoutes) {
    const m = hashBase.match(r.regex);
    if (m) {
      const params = {};
      r.paramNames.forEach((n, i) => { params[n] = decodeURIComponent(m[i + 1]); });
      return { opts: r.opts, params };
    }
  }
  return null;
}

/** Definit le handler pour les routes inconnues. */
export function setNotFound(fn) {
  _notFoundHandler = fn;
}

/** Retourne le hash normalise (sans le #). */
function currentHash() {
  const h = window.location.hash.replace(/^#/, "") || "/login";
  return h;
}

/** Navigue vers une route. Supporte le fragment : "/library#step-validation". */
export function navigateTo(hash) {
  console.log("[dash-router] -> %s", hash);
  const target = `#${hash}`;
  if (window.location.hash === target) {
    // Meme hash : forcer le resolve manuellement (scroll vers fragment par ex)
    try { window.dispatchEvent(new HashChangeEvent("hashchange")); } catch { /* noop */ }
  } else {
    window.location.hash = target;
  }
}

/** Resout et active la route correspondant au hash courant. */
function resolve() {
  const hash = currentHash();
  // Support fragment : /library#step-analyse => base route = /library, fragment = step-analyse
  const hashBaseLookup = hash.includes("#") ? hash.split("#")[0] : hash;
  let route = _routes.get(hashBaseLookup);
  let routeParams = null;

  // Fallback : tenter un match paramétré ("/film/:id")
  if (!route) {
    const matched = _matchParamRoute(hashBaseLookup);
    if (matched) {
      route = matched.opts;
      routeParams = matched.params;
    }
  }

  if (!route) {
    // Route inconnue : redirect login ou notFound
    if (_notFoundHandler) _notFoundHandler(hash);
    else navigateTo("/login");
    return;
  }

  // Guard : si la route necessite un token et qu'il n'y en a pas
  if (route.guard && !route.guard()) {
    navigateTo("/login");
    return;
  }

  // V2-C R4-MEM-4 : appeler le cleanup de la vue precedente avant de switch.
  // 2 sources possibles :
  //  1. cleanup function retournee par init() (convention nouvelle)
  //  2. unmount() exporte par la vue, lie via opts.unmount (convention legacy)
  // Aucune erreur si la vue n'expose rien — best-effort.
  if (typeof _currentCleanup === "function") {
    try { _currentCleanup(); }
    catch (err) { console.warn("[router] unmount error:", err); }
    _currentCleanup = null;
  }

  // V2-C R4-MEM-6 : abort tous les fetchs en cours associes a la nav precedente
  // (ceux passes via getNavSignal()). Anti-leak si user navigate vite.
  try { abortCurrentNav(); } catch { /* noop */ }

  // Arreter les pollings de la vue precedente
  stopAllPolling();

  // Toggle login plein ecran vs shell avec sidebar
  const isLogin = hash === "/login";
  const shell = $("app-shell");
  const loginView = $("view-login");
  if (shell) shell.classList.toggle("hidden", isLogin);
  if (loginView) loginView.classList.toggle("hidden", !isLogin);

  // Masquer toutes les vues dans le shell, afficher la bonne
  if (!isLogin) {
    $$(".main .view").forEach((el) => el.classList.remove("active"));
    const viewEl = $(route.view);
    if (viewEl) viewEl.classList.add("active");
  }

  // Mettre a jour la nav active (matching par prefixe pour les sous-hash comme /library#step-validation)
  const hashBase = hash.split("#")[0];
  $$(".nav-btn").forEach((btn) => {
    const routeAttr = btn.dataset.route || "";
    const isExact = routeAttr === hash;
    const isParent = !routeAttr.includes("#") && routeAttr === hashBase;
    const isActive = isExact || isParent;
    btn.classList.toggle("active", isActive);
    // V4-09 : aria-current="page" pour navigation (aria-selected reserve aux listbox/grid/tab)
    if (isActive) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
  });

  _currentRoute = hash;

  // Topbar : mettre a jour le titre et le sous-titre
  const titles = {
    "/status": { t: "Accueil", s: "Vue d'ensemble — état du serveur, KPIs et actions rapides" },
    "/library": { t: "Bibliothèque", s: "Workflow complet : analyse → validation → application" },
    "/quality": { t: "Qualité", s: "Scoring CinemaLux, distribution et règles personnalisées" },
    "/jellyfin": { t: "Jellyfin", s: "Intégration serveur média Jellyfin" },
    "/plex": { t: "Plex", s: "Intégration serveur média Plex" },
    "/radarr": { t: "Radarr", s: "Candidats d'upgrade et synchronisation" },
    "/logs": { t: "Journaux", s: "Logs live + historique des runs" },
    "/settings": { t: "Paramètres", s: "Configuration complète de CineSort" },
  };
  const info = titles[hashBase] || { t: hashBase, s: "" };
  const titleEl = $("topbarTitle");
  const subEl = $("topbarSubtitle");
  if (titleEl) titleEl.textContent = info.t;
  if (subEl) subEl.textContent = info.s;

  // Appeler l'init de la vue (avec params si route paramétrée)
  if (route.init) {
    try {
      const viewEl = $(route.view);
      const result = routeParams
        ? route.init(viewEl, { params: routeParams })
        : route.init(viewEl);
      // V2-C R4-MEM-4 : si init retourne une fonction (sync ou async), c'est
      // le cleanup. On le sauvegarde pour appel au prochain navigate. Pour les
      // vues async qui retournent une Promise<Function>, on attend la resolve.
      if (typeof result === "function") {
        _currentCleanup = result;
      } else if (result && typeof result.then === "function") {
        result.then((maybeCleanup) => {
          if (typeof maybeCleanup === "function") _currentCleanup = maybeCleanup;
        }).catch(() => { /* deja loggue par l'init */ });
      } else if (route.unmount && typeof route.unmount === "function") {
        // Convention legacy : la route declare son propre unmount via opts.
        _currentCleanup = route.unmount;
      }
    }
    catch (err) { console.error(`[router] init error for ${hash}:`, err); }
  }

  // Si la hash contient un fragment #step-xxx, scroller vers cette section apres init
  const fragment = hash.includes("#") ? hash.split("#").slice(1).join("#") : "";
  if (fragment) {
    setTimeout(() => {
      const target = document.getElementById(fragment) ||
                     document.querySelector(`[data-lib-section="${fragment.replace("step-", "")}"]`);
      if (target && target.scrollIntoView) target.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
  }
}

/** Guard standard : necessite un token valide. */
export function requireAuth() {
  return hasToken();
}

/** Demarre le router (ecoute hashchange). */
export function startRouter() {
  window.addEventListener("hashchange", resolve);
  resolve();
}

/** Retourne la route courante. */
export function currentRoute() {
  return _currentRoute;
}

/** Masque ou affiche un bouton nav par selecteur CSS. */
export function setNavVisible(selector, visible) {
  const btn = document.querySelector(selector);
  if (btn) btn.classList.toggle("hidden", !visible);
}
