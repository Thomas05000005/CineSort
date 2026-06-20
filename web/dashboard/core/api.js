/* core/api.js — Client HTTP pour l'API REST CineSort */

import { getToken, clearToken, awaitToken } from "./state.js";
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

/* --- V1.5.0 BUG #2 : Backoff exponentiel + dedup in-flight ---
 *
 * Symptome console : 4 retries en 30ms apres 401 -> avalanche 429 sur
 * settings/get_settings (x2), notifications_unread_count, probe_tools_status.
 *
 * Strategie :
 *  - Backoff : delais 100/200/400/800 ms, max 3 retries, UNIQUEMENT sur 5xx
 *    et erreurs reseau. PAS de retry sur 401 (auth) ni sur 429 (deja rate-limit,
 *    on laisse l'UI afficher le feedback).
 *  - Dedup : Map<key, Promise> ou key = method+url+hash(body). Tant qu'une
 *    requete identique est en vol, les appelants concurrents recoivent la
 *    MEME Promise => 1 seul appel reseau effectif.
 */
const _RETRY_DELAYS_MS = [100, 200, 400, 800];
const _MAX_RETRIES = 3;
const _inFlightRequests = new Map();

function _sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Hash FNV-1a 32-bit d'une chaine. Suffisant pour distinguer des bodies JSON
 * differents (collisions OK : pire cas = un appel manquant la dedup, pas un
 * bug fonctionnel).
 */
function _hashString(s) {
  if (!s) return "0";
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return h.toString(16);
}

function _dedupKey(method, url, body) {
  return `${method}|${url}|${_hashString(body || "")}`;
}

/**
 * Wrap d'un executor avec dedup in-flight. Si une requete identique est deja
 * en vol, retourne sa Promise. Sinon execute et libere a la fin (succes ou
 * echec).
 */
function _dedupExec(key, executor) {
  const existing = _inFlightRequests.get(key);
  if (existing) return existing;
  const p = executor().finally(() => {
    _inFlightRequests.delete(key);
  });
  _inFlightRequests.set(key, p);
  return p;
}

/**
 * Indique si un statut HTTP doit declencher un retry. PAS de retry sur 401
 * (auth, l'UI doit gerer) ni sur 429 (rate limit, on laisse l'UI feedback).
 */
function _isRetryableStatus(status) {
  return status >= 500 && status < 600;
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
 * Construit la valeur "Bearer <token>" pour le header Authorization en
 * VERIFIANT que le token est 100% ASCII. Les headers HTTP transitent par
 * fetch() dans une representation ISO-8859-1 ; tout codepoint > 0xFF
 * declenche un TypeError "String contains non ISO-8859-1 code point"
 * silencieux qui fait rejeter la promise fetch et casse l'Accueil.
 *
 * Causes connues d'un token pollue (cf MEMORY cinesort_settings_utf8_bom) :
 *  - BOM UTF-8 (U+FEFF) ajoute par PowerShell quand il ecrit settings.json
 *  - Em-dash (U+2014) ou guillemets typographiques copies-colles
 *  - URL-decode automatique de %EF%BB%BF dans ?ntoken=... au boot natif
 *
 * Si le token contient un caractere non-ASCII, on omet le header (la requete
 * partira sans Authorization -> 401 propre cote serveur, geree par l'UI)
 * plutot que de laisser fetch() crasher. On logge le codepoint exact pour
 * faciliter le diag cote backend (token corrompu vs config defaillante).
 *
 * @param {string|null} token
 * @returns {string|null} "Bearer <token>" si safe, null sinon
 */
function _safeBearer(token) {
  // ITER15 5.2 : reduire verbosite token en mode natif+localhost. En desktop
  // (pywebview, bind 127.0.0.1), le bypass loopback cote serveur rend ces
  // diagnostics largement bruyants pour la console F12. En mode web/LAN, on
  // garde le niveau ERROR : la c'est un vrai bug auth a investiguer.
  // GARDE-FOU : ce changement n'affecte PAS l'auth (matrice iter5/iter14
  // no/wrong→401, valid→200, loopback bypass — strictement identique).
  let _isQuietContext = false;
  try {
    if (typeof window !== "undefined") {
      const _isNative = window.__CINESORT_NATIVE__ === true;
      const _host = window.location && window.location.hostname;
      const _isLocalhost = _host === "127.0.0.1" || _host === "localhost";
      _isQuietContext = _isNative && _isLocalhost;
    }
  } catch { /* no-op */ }
  const _log = _isQuietContext ? console.debug : console.error;
  // DEBUG VERBOSE 2026-06-08 : signaler explicitement l absence de token au boot.
  if (!token) {
    try { _log("[dash-api] _safeBearer: token absent ou vide (token=%o)", token); } catch { /* no-op */ }
    return null;
  }
  // FIX 2026-06-07 (faux 429 TMDb test) : avant d'abdiquer, on tente une
  // normalisation defensive du token. Le cas dominant identifie en prod est
  // un BOM UTF-8 (U+FEFF) prefixe par PowerShell quand il a ecrit settings.json
  // (cf MEMORY cinesort_settings_utf8_bom). On strippe aussi les espaces
  // typographiques courants (NBSP U+00A0) qui resultent d'un copy-paste.
  // Sans cette normalisation, le header etait OMIS silencieusement -> 5 pings
  // de l'Accueil generaient 5x 401 -> rate-limiter sature -> faux 429 au 1er
  // click "Tester" sur Parametres.
  let normalized = token;
  // Strip BOM eventuels (debut/n'importe ou) + NBSP -> espace simple.
  if (/[﻿ ]/.test(normalized)) {
    // DEBUG VERBOSE 2026-06-08 : avant de normaliser, logger ce qui declenche la branche (BOM ou NBSP detecte).
    try {
      var preCps = [];
      for (var k = 0; k < normalized.length; k++) {
        preCps.push("U+" + normalized.charCodeAt(k).toString(16).padStart(4, "0").toUpperCase());
      }
      _log("[dash-api] _safeBearer BOM/NBSP detecte AVANT normalisation len=%d codepoints=%o", normalized.length, preCps);
    } catch (_e) { /* no-op */ }
    normalized = normalized.replace(/﻿/g, "").replace(/ /g, " ").trim();
  }
  for (let i = 0; i < normalized.length; i++) {
    const cp = normalized.charCodeAt(i);
    if (cp > 127) {
      // DEBUG VERBOSE 2026-06-08 : dump TOUS les codepoints du token rejete
      // (pas seulement le premier non-ASCII). Identifie la nature exacte de
      // la corruption (BOM seul, em-dash insere, double encoding, etc.).
      try {
        var allCps = [];
        var nonAscii = [];
        for (var j = 0; j < normalized.length; j++) {
          var c = normalized.charCodeAt(j);
          allCps.push("U+" + c.toString(16).padStart(4, "0").toUpperCase());
          if (c > 127) nonAscii.push({ pos: j, codepoint: "U+" + c.toString(16).padStart(4, "0").toUpperCase() });
        }
        _log(
          "[dash-api] _safeBearer REJECT token non-ASCII U+" +
            cp.toString(16).padStart(4, "0").toUpperCase() +
            " pos=" + i + " len=" + normalized.length + " (Authorization OMIS)",
        );
        _log("[dash-api] _safeBearer rejected token full codepoints=%o", allCps);
        _log("[dash-api] _safeBearer rejected token non-ASCII positions=%o", nonAscii);
      } catch (_e) { /* no-op */ }
      return null;
    }
  }
  return "Bearer " + normalized;
}

/**
 * Appel GET generique avec gestion auth et erreurs.
 * V1.5.0 BUG #2 : dedup in-flight + backoff exp sur 5xx (3 retries max).
 * @returns {Promise<{status: number, data: any}>}
 */
export function apiGet(path) {
  const url = `${baseUrl()}${path}`;
  const key = _dedupKey("GET", url, "");
  return _dedupExec(key, () => _apiGetImpl(path, url));
}

async function _apiGetImpl(path, url) {
  // V1.5.0 fix bug #1 : attendre que le token soit injecte avant de
  // partir (sinon salve de 401 au boot natif - cf state.js awaitToken).
  await awaitToken();
  const token = getToken();
  const headers = {};
  const bearer = _safeBearer(token);
  if (bearer) headers["Authorization"] = bearer;

  // V1.5.0 BUG #2 : boucle retry avec backoff exp. PAS de retry sur 401/429.
  let lastResp = null;
  for (let attempt = 0; attempt <= _MAX_RETRIES; attempt++) {
    let resp;
    try {
      resp = await fetch(url, { method: "GET", headers });
    } catch (err) {
      // Erreur reseau : retry si attempts restants, sinon propage
      if (attempt < _MAX_RETRIES) {
        await _sleep(_RETRY_DELAYS_MS[attempt]);
        continue;
      }
      _noteFailure();
      throw err;
    }

    // 5xx -> retry avec backoff (sauf si dernier essai)
    if (_isRetryableStatus(resp.status) && attempt < _MAX_RETRIES) {
      lastResp = resp;
      await _sleep(_RETRY_DELAYS_MS[attempt]);
      continue;
    }
    lastResp = resp;
    break;
  }

  const resp = lastResp;

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
    // PAS de retry sur 429 : on laisse l'UI feedback (cf V1.5.0 BUG #2).
    return { status: 429, data: { ok: false, message: "Trop de tentatives. Reessayez dans 60 secondes." } };
  }
  if (resp.status >= 500) {
    console.error("[dash-api] GET %s -> %d (serveur indisponible, %d retries epuises)", path, resp.status, _MAX_RETRIES);
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
 * V1.5.0 BUG #2 : dedup in-flight + backoff exp sur 5xx (3 retries max).
 * Note : on ne dedup PAS quand un opts.signal externe est fourni (l'appelant
 * controle son cycle de vie, et 2 appelants distincts pourraient l'abort
 * indirectement). Le timeoutMs interne reste dedupable.
 * @param {string} method - nom de la methode API
 * @param {object} params - parametres JSON
 * @param {object} [opts] - options : { signal?: AbortSignal, timeoutMs?: number }
 *                          - signal : permet a l'appelant d'abort manuellement
 *                          - timeoutMs : abort auto apres ce delai (anti memory leak)
 * @returns {Promise<{status: number, data: any}>}
 */
export function apiPost(method, params = {}, opts = {}) {
  const url = `${baseUrl()}/api/${method}`;
  const body = JSON.stringify(params);
  // FIX 2026-06-05 (avalanche boot natif) : auparavant, la presence d'un
  // opts.signal externe DESACTIVAIT la dedup in-flight. Resultat : accueil.js
  // partait 4 fetchs concurrents avec un signal partage, et la dedup centrale
  // etait court-circuitee -> settings/get_settings tire 2 fois (boot shell +
  // accueil), get_dashboard 2 fois, etc. Salve 401/429 garantie au boot a froid.
  //
  // Nouvelle strategie : on dedup TOUJOURS. Si un signal externe est fourni,
  // on l'observe pour pouvoir abort le fetch quand TOUS les callers concurrents
  // ont abort. Le signal effectif passe au fetch est compose via _composeSignal.
  const key = _dedupKey("POST", url, body);
  return _dedupExec(key, () => _apiPostImpl(method, params, opts, url, body));
}

/**
 * Compose un AbortSignal "any-of" sans depender de AbortSignal.any (pas
 * universellement dispo). Le signal resultant est abort des qu'UN des
 * signaux d'entree est abort. Renvoie le signal du nouveau controller.
 * Utilise par _apiPostImpl quand l'appelant fournit son propre opts.signal
 * et qu'on veut ajouter un timeout interne.
 */
function _composeSignal(signals) {
  const real = signals.filter(Boolean);
  if (real.length === 0) return null;
  if (real.length === 1) return real[0];
  const ctrl = new AbortController();
  const onAbort = () => { try { ctrl.abort(); } catch { /* no-op */ } };
  for (const s of real) {
    if (s.aborted) { onAbort(); break; }
    try { s.addEventListener("abort", onAbort, { once: true }); } catch { /* no-op */ }
  }
  return ctrl.signal;
}

async function _apiPostImpl(method, params, opts, url, body) {
  // V1.5.0 fix bug #1 : attendre que le token soit injecte avant de
  // partir. Au boot natif, _detectNativeBoot pose le token de maniere
  // synchrone mais les modules ES qui font Promise.all (accueil.js)
  // peuvent partir AVANT setToken si le browser parse hors-ordre.
  // awaitToken() resout immediatement si markTokenReady() a deja ete
  // appele, sinon attend (deadline 2s max - cf state.js).
  await awaitToken();
  const token = getToken();
  const headers = { "Content-Type": "application/json" };
  const bearer = _safeBearer(token);
  if (bearer) headers["Authorization"] = bearer;

  // V2-C R4-MEM-3 + fix 2026-06-05 : support timeout via AbortSignal.timeout.
  // Si signal externe ET timeoutMs : on COMPOSE les deux (abort si un seul
  // est abort). Avant le fix, le signal externe avait priorite et ecrasait
  // le timeout.
  let timeoutSignal = null;
  if (opts.timeoutMs) {
    if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
      timeoutSignal = AbortSignal.timeout(opts.timeoutMs);
    } else {
      const ctrl = new AbortController();
      setTimeout(() => ctrl.abort(), opts.timeoutMs);
      timeoutSignal = ctrl.signal;
    }
  }
  const signal = _composeSignal([opts.signal || null, timeoutSignal]);

  // V1.5.0 BUG #2 : boucle retry avec backoff exp. PAS de retry sur 401/429.
  let resp = null;
  for (let attempt = 0; attempt <= _MAX_RETRIES; attempt++) {
    try {
      resp = await fetch(url, {
        method: "POST",
        headers,
        body,
        signal,
      });
    } catch (err) {
      // AbortError (timeout ou abort manuel) : pas un echec serveur, on remonte
      // tel quel pour que l'appelant decide quoi faire (silencieux ou retry).
      if (err && (err.name === "AbortError" || err.name === "TimeoutError")) {
        throw err;
      }
      // Erreur reseau : retry avec backoff si attempts restants.
      if (attempt < _MAX_RETRIES) {
        await _sleep(_RETRY_DELAYS_MS[attempt]);
        continue;
      }
      _noteFailure();
      throw err;
    }

    // 5xx -> retry avec backoff (sauf si dernier essai).
    if (_isRetryableStatus(resp.status) && attempt < _MAX_RETRIES) {
      await _sleep(_RETRY_DELAYS_MS[attempt]);
      continue;
    }
    break;
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
    // PAS de retry sur 429 : on laisse l'UI feedback (cf V1.5.0 BUG #2).
    return { status: 429, data: { ok: false, message: "Trop de tentatives. Reessayez dans 60 secondes." } };
  }
  if (resp.status === 409) {
    // R6-HTTP409-003 : message dedie + flag _conflict pour permettre aux
    // call-sites d'afficher un toast "operation en cours" specifique plutot
    // qu'un banner d'erreur generique. Backward-compat : data.ok === false
    // reste lisible comme avant.
    const data = await resp.json().catch(() => ({}));
    return {
      status: 409,
      data: {
        ok: false,
        message: data.message || "Operation deja en cours. Reessayez dans quelques instants.",
        _conflict: true,
      },
    };
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

/* ---------- VN-C.1 (batch 2) : seuils confidence unifies ----------
 *
 * Backend expose les seuils via settings.get_confidence_thresholds :
 *     POST /api/settings/get_confidence_thresholds
 *     -> { ok: true, thresholds: { high: 85, medium: 60, low: 0 } }
 *
 * Source unique : cinesort/domain/confidence_thresholds.py. Avant VN-C.1,
 * les seuils 85/60 etaient hardcode dans traitement.js + lib-validation.js
 * et incoherents avec le backend (75/50 quality_score, 80/60 core).
 *
 * Strategie :
 *  - Cache module-level (les seuils ne changent que via deploiement code,
 *    pas de TTL necessaire). Premier appel : un round-trip HTTP.
 *  - Fallback safe : si l'endpoint repond pas (ancien backend), on garde
 *    les valeurs DEFAULT 85/60 (= les anciennes hardcoded UI).
 */
const _CONF_DEFAULTS = Object.freeze({ high: 85, medium: 60, low: 0 });
let _confThresholdsCache = null;
let _confThresholdsInFlight = null;

/**
 * Retourne les seuils confidence (high / medium / low) via /api/settings/get_confidence_thresholds.
 * Cache module-level + dedup des requetes paralleles. Retourne TOUJOURS un objet
 * { high, medium, low } (fallback DEFAULTS si backend KO).
 * @returns {Promise<{high: number, medium: number, low: number}>}
 */
export function fetchConfidenceThresholds() {
  if (_confThresholdsCache) return Promise.resolve(_confThresholdsCache);
  if (_confThresholdsInFlight) return _confThresholdsInFlight;
  _confThresholdsInFlight = apiPost("settings/get_confidence_thresholds")
    .then((resp) => {
      const t = resp && resp.data && resp.data.thresholds;
      if (t && Number.isFinite(t.high) && Number.isFinite(t.medium)) {
        _confThresholdsCache = {
          high: Number(t.high),
          medium: Number(t.medium),
          low: Number.isFinite(t.low) ? Number(t.low) : 0,
        };
      } else {
        _confThresholdsCache = { ..._CONF_DEFAULTS };
      }
      return _confThresholdsCache;
    })
    .catch(() => {
      _confThresholdsCache = { ..._CONF_DEFAULTS };
      return _confThresholdsCache;
    })
    .finally(() => { _confThresholdsInFlight = null; });
  return _confThresholdsInFlight;
}

/**
 * Variante synchrone : retourne les seuils si deja fetched, sinon les
 * DEFAULTS (85/60). Utile pour les rendus init avant fetch async.
 */
export function getConfidenceThresholdsSync() {
  return _confThresholdsCache || { ..._CONF_DEFAULTS };
}

/**
 * Teste la connexion : GET /api/health (pas d'auth requise,
 * mais on envoie le token pour verifier qu'il est valide via un POST).
 * Retourne { ok, version, active_run_id? } ou { ok: false, message }.
 */
export async function testConnection(token) {
  const headers = {
    "Content-Type": "application/json",
  };
  const bearer = _safeBearer(token);
  if (bearer) {
    headers["Authorization"] = bearer;
  } else if (token) {
    // Token non vide mais non-ASCII : on retourne une erreur explicite
    // plutot que de tenter le fetch (qui crasherait en TypeError).
    return { ok: false, message: "Clé d'accès invalide (caractères non autorisés)." };
  }

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
