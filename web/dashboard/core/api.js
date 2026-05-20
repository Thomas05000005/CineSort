/* core/api.js — Client HTTP pour l'API REST CineSort */

import { getToken, clearToken } from "./state.js";
import { isCacheable, saveSnapshot, loadSnapshot, formatStaleness } from "./cache.js";

/* --- Indicateur de connexion (C8) ---------------------------- */
let _connFailureStreak = 0;
const _CONN_FAIL_THRESHOLD = 2;

function _setConnStatus(cls) {
  const dot = document.getElementById("dashConnStatus");
  if (!dot) return;
  dot.classList.remove("conn-dot--ok", "conn-dot--warn", "conn-dot--error", "conn-dot--unknown");
  dot.classList.add(cls);
  const labels = {
    "conn-dot--ok": "Connecte",
    "conn-dot--warn": "Lenteur reseau",
    "conn-dot--error": "Deconnecte",
    "conn-dot--unknown": "Statut inconnu",
  };
  dot.setAttribute("title", labels[cls] || "");
  dot.setAttribute("aria-label", labels[cls] || "");
}

function _noteSuccess() {
  _connFailureStreak = 0;
  _setConnStatus("conn-dot--ok");
}

function _noteFailure() {
  _connFailureStreak += 1;
  _setConnStatus(_connFailureStreak >= _CONN_FAIL_THRESHOLD ? "conn-dot--error" : "conn-dot--warn");
}

/**
 * URL de base de l'API, auto-detectee depuis l'origine de la page.
 * En dev, le dashboard est servi par le meme serveur que l'API.
 */
function baseUrl() {
  return window.location.origin;
}

/**
 * Detecte si on tourne en mode pywebview desktop local. 4 signaux
 * independants — UN SEUL suffit pour considerer qu'on est en natif :
 *   1) flag __CINESORT_NATIVE__ pose par l'IIFE detection
 *   2) window.pywebview.api : signature pywebview FIABLE (toujours injectee
 *      par pywebview quand js_api est present, perdure aux refresh)
 *   3) hostname 127.0.0.1 / localhost : on est en local, login web n'a aucun sens
 *   4) flag persiste en localStorage (survit aux redemarrage / cache wipe)
 *
 * Utilise pour BYPASS le redirect /login sur 401 — un 401 en mode local
 * est un bug serveur (token mal passe), pas une raison de remettre l'user
 * sur un ecran login qui n'a pas de sens en desktop.
 */
function _isNativeMode() {
  if (typeof window === "undefined") return false;
  if (window.__CINESORT_NATIVE__) return true;
  if (window.pywebview && window.pywebview.api) return true;
  const host = window.location && window.location.hostname;
  if (host === "127.0.0.1" || host === "localhost") return true;
  try { if (localStorage.getItem("cinesort.native") === "1") return true; } catch { /* no-op */ }
  return false;
}

/**
 * Appel GET generique avec gestion auth et erreurs.
 * @returns {Promise<{status: number, data: any}>}
 */
export async function apiGet(path) {
  const token = getToken();
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const _t0 = performance.now();
  const resp = await fetch(`${baseUrl()}${path}`, { method: "GET", headers });

  if (resp.status === 401) {
    // Mode pywebview desktop : un 401 ne doit JAMAIS purger le token ni
    // rediriger vers /login (l'origine est garantie par le bridge natif).
    // On remonte le 401 a l'appelant qui decidera (retry, message d'erreur, etc.).
    if (_isNativeMode()) {
      console.warn("[dash-api] GET %s -> 401 (mode natif : pas de redirect login)", path);
      return { status: 401, data: { ok: false, message: "Authentification refusee par le backend." } };
    }
    clearToken();
    window.location.hash = "#/login";
    return { status: 401, data: { ok: false, message: "Clé d'accès invalide." } };
  }
  if (resp.status === 429) {
    return { status: 429, data: { ok: false, message: "Trop de tentatives. Reessayez dans 60 secondes." } };
  }
  if (resp.status >= 500) {
    console.error("[dash-api] GET %s -> %d (serveur indisponible)", path, resp.status);
    _noteFailure();
    return { status: resp.status, data: { ok: false, message: `Serveur indisponible (HTTP ${resp.status}). Reessayez dans quelques instants.` } };
  }

  const data = await resp.json().catch(() => ({ ok: false, message: "Reponse invalide." }));
  if (resp.status >= 400) {
    console.warn("[dash-api] GET %s -> %d", path, resp.status);
    _noteFailure();
  } else {
    _noteSuccess();
  }
  return { status: resp.status, data };
}

/**
 * Appel POST generique vers /api/{method} avec body JSON.
 * @param {string} method - nom de la methode API
 * @param {object} params - parametres JSON
 * @param {object} [opts] - options : { signal?: AbortSignal, timeoutMs?: number }
 *                          - signal : permet a l'appelant d'abort manuellement
 *                          - timeoutMs : abort auto apres ce delai (anti memory leak)
 * @returns {Promise<{status: number, data: any}>}
 */
export async function apiPost(method, params = {}, opts = {}) {
  const token = getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // V2-C R4-MEM-3 : support timeout via AbortSignal.timeout. Si timeoutMs et
  // signal sont fournis, le signal explicite a priorite (l'appelant decide).
  let signal = opts.signal || null;
  if (!signal && opts.timeoutMs) {
    if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
      signal = AbortSignal.timeout(opts.timeoutMs);
    } else {
      // Fallback : controller manuel + setTimeout pour vieux navigateurs.
      const ctrl = new AbortController();
      setTimeout(() => ctrl.abort(), opts.timeoutMs);
      signal = ctrl.signal;
    }
  }

  const _t0 = performance.now();
  let resp;
  try {
    resp = await fetch(`${baseUrl()}/api/${method}`, {
      method: "POST",
      headers,
      body: JSON.stringify(params),
      signal,
    });
  } catch (err) {
    // AbortError (timeout ou abort manuel) : pas un echec serveur, on remonte
    // tel quel pour que l'appelant decide quoi faire (silencieux ou retry).
    if (err && (err.name === "AbortError" || err.name === "TimeoutError")) {
      throw err;
    }
    _noteFailure();
    throw err;
  }

  if (resp.status === 401) {
    if (_isNativeMode()) {
      console.warn("[dash-api] POST /api/%s -> 401 (mode natif : pas de redirect login)", method);
      return { status: 401, data: { ok: false, message: "Authentification refusee par le backend." } };
    }
    clearToken();
    window.location.hash = "#/login";
    return { status: 401, data: { ok: false, message: "Clé d'accès invalide." } };
  }
  if (resp.status === 429) {
    return { status: 429, data: { ok: false, message: "Trop de tentatives. Reessayez dans 60 secondes." } };
  }
  if (resp.status >= 500) {
    console.error("[dash-api] POST /api/%s -> %d (serveur indisponible)", method, resp.status);
    _noteFailure();
    /* J14 : fallback cache si disponible */
    const cached = loadSnapshot(method);
    if (cached) {
      return { status: resp.status, data: { ...cached.data, _offline: true, _stale_age: formatStaleness(cached.ageSeconds) } };
    }
    return { status: resp.status, data: { ok: false, message: `Serveur indisponible (HTTP ${resp.status}). Reessayez dans quelques instants.` } };
  }

  const data = await resp.json().catch(() => ({ ok: false, message: "Reponse invalide." }));
  if (resp.status >= 400) {
    console.warn("[dash-api] POST /api/%s -> %d", method, resp.status);
    _noteFailure();
  } else {
    _noteSuccess();
    /* J14 : sauvegarde snapshot si cacheable */
    if (isCacheable(method) && data && data.ok !== false) {
      saveSnapshot(method, data);
    }
    /* V2-B : invalidation automatique du cache get_settings sur save_settings.
     * Defensif : meme si l'appelant oublie, le cache reste coherent. */
    if ((method === "save_settings" || method === "settings/save_settings") && data && data.ok !== false) {
      invalidateSettingsCache();
    }
  }
  return { status: resp.status, data };
}

/* --- Cache get_settings (V2-B / H13) -------------------------
 *
 * Au boot, le dashboard appelle get_settings depuis 4+ endpoints
 * (theme, sidebar features, notif, demo). Chaque appel = ~50ms HTTP
 * round-trip => ~200ms latence inutile + 4x charge serveur.
 *
 * cachedGetSettings() :
 *  - Premier appel  -> reel apiPost("settings/get_settings"), cache la reponse.
 *  - Appels concurrents (avant fin du premier) -> retournent la MEME
 *    Promise (singleton in-flight) => 1 seule requete reseau pour N sites.
 *  - Appels suivants (< CACHE_TTL_MS) -> reponse cachee directe.
 *  - Invalidation explicite : invalidateSettingsCache() (a appeler
 *    apres save_settings ou si health.last_settings_ts change).
 *
 * Compatibilite : signature publique apiPost("settings/get_settings") inchangee,
 * les appelants peuvent migrer site par site vers cachedGetSettings().
 */
const _SETTINGS_CACHE_TTL_MS = 30000;  // 30s safe
let _settingsCachePayload = null;       // { status, data } resultat cache
let _settingsCacheTs = 0;               // ms epoch
let _settingsInFlight = null;           // Promise pendante de la requete en cours

/**
 * Recupere les settings avec cache memoire + dedup des requetes paralleles.
 * Signature de retour identique a apiPost("settings/get_settings") => drop-in.
 * @returns {Promise<{status: number, data: any}>}
 */
export function cachedGetSettings() {
  const now = Date.now();
  // Cache hit valide
  if (_settingsCachePayload && (now - _settingsCacheTs) < _SETTINGS_CACHE_TTL_MS) {
    return Promise.resolve(_settingsCachePayload);
  }
  // Requete deja en vol -> renvoyer la MEME promise (dedup parallele)
  if (_settingsInFlight) {
    return _settingsInFlight;
  }
  // Nouvelle requete
  _settingsInFlight = apiPost("settings/get_settings")
    .then((resp) => {
      // Cacher uniquement les reponses 2xx (pas de cache d'erreur 5xx)
      if (resp && resp.status >= 200 && resp.status < 300) {
        _settingsCachePayload = resp;
        _settingsCacheTs = Date.now();
      }
      return resp;
    })
    .finally(() => {
      _settingsInFlight = null;
    });
  return _settingsInFlight;
}

/**
 * Invalide le cache get_settings. A appeler apres save_settings reussi
 * ou quand health.last_settings_ts change cote serveur.
 */
export function invalidateSettingsCache() {
  _settingsCachePayload = null;
  _settingsCacheTs = 0;
  // Note : on ne tue PAS _settingsInFlight si une requete est en cours,
  // car elle vient juste de partir et la donnee va etre fraiche.
}

/* Invalidation auto au retour focus : si l'utilisateur a ete inactif
 * un long moment, les settings ont pu changer cote desktop pywebview.
 * On ne supprime pas le cache si le doc reste visible. */
if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      // Au retour focus, age > 30s deja mais on force au cas ou
      const age = Date.now() - _settingsCacheTs;
      if (age > _SETTINGS_CACHE_TTL_MS) {
        invalidateSettingsCache();
      }
    }
  });
}

/**
 * Teste la connexion : GET /api/health (pas d'auth requise,
 * mais on envoie le token pour verifier qu'il est valide via un POST).
 * Retourne { ok, version, active_run_id? } ou { ok: false, message }.
 */
export async function testConnection(token) {
  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`,
  };

  // On valide le token via un POST authentifie sur la facade settings.
  // Issue #233 : avant le refactor #84 PR 10, l'endpoint etait /api/get_settings.
  // Il a ete deplace sous /api/settings/get_settings (split en 5 facades).
  // L'ancien path retourne 404, ce qui cassait silencieusement le flow de login.
  const resp = await fetch(`${baseUrl()}/api/settings/get_settings`, {
    method: "POST",
    headers,
    body: "{}",
  });

  if (resp.status === 401) {
    return { ok: false, message: "Clé d'accès invalide." };
  }
  if (resp.status === 429) {
    return { ok: false, message: "Trop de tentatives. Reessayez dans 60 secondes." };
  }
  if (resp.status >= 500) {
    return { ok: false, message: `Serveur indisponible (HTTP ${resp.status}). Reessayez dans quelques instants.` };
  }

  // Si le POST passe, on recupere aussi le health pour la version
  const healthResp = await fetch(`${baseUrl()}/api/health`);
  const health = await healthResp.json().catch(() => ({}));

  return { ok: true, version: health.version || "?", active_run_id: health.active_run_id || null };
}
