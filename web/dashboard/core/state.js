/* core/state.js — Gestion du token et de l'etat global du dashboard */

const TOKEN_KEY = "cinesort.dashboard.token";
const PERSIST_KEY = "cinesort.dashboard.persist";

/** Retourne true si l'utilisateur a coche "Rester connecte". */
export function isPersistent() {
  try { return localStorage.getItem(PERSIST_KEY) === "1"; }
  catch { return false; }
}

/** Active ou desactive la persistence du token. */
export function setPersistent(value) {
  try {
    if (value) localStorage.setItem(PERSIST_KEY, "1");
    else localStorage.removeItem(PERSIST_KEY);
  } catch { /* no-op */ }
}

/** Recupere le token depuis sessionStorage ou localStorage. */
export function getToken() {
  try {
    // Essayer d'abord sessionStorage (prioritaire)
    const session = sessionStorage.getItem(TOKEN_KEY);
    if (session) return session;
    // Sinon localStorage si persistant
    if (isPersistent()) return localStorage.getItem(TOKEN_KEY) || "";
    return "";
  } catch { return ""; }
}

/* Token urlsafe : alphabet base64url (RFC 4648), longueur 1..128.
 * Le rest_api_token CineSort est garanti urlsafe 32 chars ASCII (cf MEMORY).
 * Ce filtre rejette tout token pollue par :
 *  - BOM UTF-8 (U+FEFF) injecte par PowerShell sur settings.json
 *  - URL-decode automatique de %EF%BB%BF dans ?ntoken=... au boot natif
 *  - Em-dash (U+2014) ou guillemets typographiques copies-colles
 *  - Whitespace non-ASCII (U+00A0 nbsp, etc.)
 * Sans ce filtre, le token pollue entre en storage et casse tous les
 * fetch() suivants avec "String contains non ISO-8859-1 code point" sur
 * le header Authorization (TypeError silencieux qui rejette la promise).
 */
const _URLSAFE_TOKEN_RE = /^[A-Za-z0-9_\-]{1,128}$/;

/** Stocke le token dans le storage approprie.
 *  Refuse silencieusement (avec log console) tout token non-urlsafe-ASCII
 *  pour eviter la salve de TypeError sur le header Authorization. */
export function setToken(token, persist = false) {
  const raw = String(token || "").trim();
  if (raw && !_URLSAFE_TOKEN_RE.test(raw)) {
    try {
      const codepoints = [...raw].slice(0, 8).map((c) =>
        "U+" + c.charCodeAt(0).toString(16).padStart(4, "0").toUpperCase(),
      );
      console.error(
        "[state] setToken: token non-urlsafe REJETE (len=" + raw.length + "), " +
        "premiers codepoints=" + codepoints.join(",") +
        ". Causes possibles: BOM UTF-8 (settings.json PowerShell), em-dash, guillemets typographiques.",
      );
    } catch { /* no-op */ }
    // On NE persiste PAS le token pollue. L'appelant verra l'absence de token
    // (401 propre au prochain apiPost) plutot qu'un crash fetch silencieux.
    return;
  }
  const val = raw;
  setPersistent(persist);
  try {
    sessionStorage.setItem(TOKEN_KEY, val);
    if (persist) localStorage.setItem(TOKEN_KEY, val);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* no-op */ }
  // V1.5.0 fix bug #1 : signaler que le token est pret pour debloquer
  // les requetes apiPost/apiGet qui attendaient awaitToken().
  if (val) markTokenReady();
}

/* --- Coordination boot : token-ready gate -----------------------
 *
 * Bug #1 console v1.5.0 : au boot natif, 4 endpoints (get_dashboard,
 * get_global_stats, get_settings, get_update_info) partaient en parallele
 * AVANT que _detectNativeBoot ait fini d'injecter le ntoken via setToken().
 * Resultat : 4x HTTP 401 silencieux puis nouvelle salve une fois le token
 * present. Cf MEMORY BUG CONSOLE #1.
 *
 * Solution : un gate Promise unique. apiPost / apiGet appellent
 * awaitToken() avant de lire getToken(). Tant que markTokenReady() ou
 * markTokenAbsent() n'est pas invoque, les requetes attendent (avec un
 * deadline de 2s pour ne jamais hang).
 *
 *  - markTokenReady()  -> token disponible, debloque immediatement.
 *  - markTokenAbsent() -> on sait qu'aucun token ne viendra (mode web
 *                         sans login), debloque pour que la 401 normale
 *                         declenche le redirect /login.
 */
const _AWAIT_TOKEN_DEADLINE_MS = 2000;
// FIX 2026-06-05 (boot natif sans token storage) : en mode natif sans
// token en sessionStorage/localStorage (cache wipe, premier reload sans
// ntoken), markTokenAbsent debloquait IMMEDIATEMENT awaitToken comme
// markTokenReady -> les 4 fetchs initiaux partaient SANS Bearer -> 5x 401
// garantis. On separe maintenant les 2 etats : markTokenAbsent attend un
// delai supplementaire pour laisser pywebview injecter le token via une
// route alternative (ex: pywebview.api.get_token() retry depuis la WebView).
const _ABSENT_GRACE_NATIVE_MS = 800;
let _tokenReadyResolved = false;
let _tokenReadyResolve = null;
const _tokenReadyPromise = new Promise((resolve) => {
  _tokenReadyResolve = resolve;
});
// Safety deadline : si rien ne signale (cas degrade), on debloque
// apres 2s pour ne pas hang indefiniment les requetes au boot.
setTimeout(() => {
  if (!_tokenReadyResolved) {
    _tokenReadyResolved = true;
    try { _tokenReadyResolve && _tokenReadyResolve(); } catch { /* no-op */ }
  }
}, _AWAIT_TOKEN_DEADLINE_MS);

/** Signale que le token est pret (apres setToken au boot ou apres login).
 *  Idempotent : safe a appeler plusieurs fois. */
export function markTokenReady() {
  if (_tokenReadyResolved) return;
  _tokenReadyResolved = true;
  try { _tokenReadyResolve && _tokenReadyResolve(); } catch { /* no-op */ }
}

/**
 * Signale que le boot est termine SANS token.
 *
 * - En mode web pre-login : debloque immediatement (la 401 declenchera
 *   le redirect vers /login).
 * - En mode natif : on differe le deblocage d'_ABSENT_GRACE_NATIVE_MS
 *   pour laisser une chance a un setToken differe (pywebview qui injecte
 *   le ntoken via un canal alternatif, retry de _detectNativeBoot, etc.).
 *   Si rien n'arrive, le safety deadline (2s) finit par debloquer.
 *
 * @param {{ native?: boolean }} [opts] - si native === true, applique le delai
 */
export function markTokenAbsent(opts) {
  const isNative = !!(opts && opts.native);
  if (!isNative) {
    markTokenReady();
    return;
  }
  if (_tokenReadyResolved) return;
  try {
    console.warn("[state] markTokenAbsent (natif) : aucun token en storage, deblocage differe %dms", _ABSENT_GRACE_NATIVE_MS);
  } catch { /* no-op */ }
  setTimeout(() => {
    if (!_tokenReadyResolved) {
      _tokenReadyResolved = true;
      try { _tokenReadyResolve && _tokenReadyResolve(); } catch { /* no-op */ }
    }
  }, _ABSENT_GRACE_NATIVE_MS);
}

/** Retourne une Promise qui resout quand le token est pret OU quand le
 *  deadline (2s) est atteint. A utiliser dans apiPost/apiGet pour eviter
 *  la salve 401 du boot. */
export function awaitToken() {
  if (_tokenReadyResolved) return Promise.resolve();
  return _tokenReadyPromise;
}

/** Indique si le token-ready gate a deja resolved (token pret ou expire). */
export function isTokenGateResolved() {
  return _tokenReadyResolved;
}

/* Cf issue #89 : permet aux modules qui creent des setInterval/AbortController
 * de s'enregistrer pour cleanup au logout. Evite les boucles 401 + leaks
 * apres clearToken().
 */
const _onClearCallbacks = new Set();

/** Enregistre une callback appelee a chaque clearToken(). Retourne un
 *  identifiant qu'on peut passer a removeOnClearToken pour desinscrire.
 */
export function onClearToken(cb) {
  _onClearCallbacks.add(cb);
  return cb;
}

/** Desinscrit une callback precedemment enregistree. */
export function removeOnClearToken(cb) {
  _onClearCallbacks.delete(cb);
}

/** Efface le token de tous les storages. Invoque les callbacks enregistrees
 *  via onClearToken (pour cleanup des intervals/listeners).
 */
export function clearToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(PERSIST_KEY);
  } catch { /* no-op */ }
  // Notifier les modules pour qu'ils cleanup leurs intervals/listeners.
  for (const cb of _onClearCallbacks) {
    try { cb(); } catch (e) { /* silencieux : un cleanup ne doit pas bloquer le logout */ }
  }
}

/** Retourne true si un token est present. */
export function hasToken() {
  return getToken().length > 0;
}

/* --- Event timestamp (refresh auto apres apply/scan) ------- */

let _lastEventTs = null;

/**
 * Compare le last_event_ts recu du health endpoint avec la valeur locale.
 * Retourne true si l'evenement a change (= il faut rafraichir les donnees).
 */
export function checkEventChanged(serverTs) {
  if (serverTs == null) return false;
  if (_lastEventTs === null) {
    _lastEventTs = serverTs;
    return false;           // premier appel, pas de changement
  }
  if (serverTs !== _lastEventTs) {
    _lastEventTs = serverTs;
    return true;            // evenement cote serveur → refresh
  }
  return false;
}

/* --- Settings timestamp (sync temps reel) ------------------- */

let _lastSettingsTs = null;

/**
 * Compare le last_settings_ts recu du health endpoint avec la valeur locale.
 * Retourne true si les settings ont change cote serveur.
 */
export function checkSettingsChanged(serverTs) {
  if (serverTs == null) return false;
  if (_lastSettingsTs === null) {
    _lastSettingsTs = serverTs;
    return false;
  }
  if (serverTs !== _lastSettingsTs) {
    _lastSettingsTs = serverTs;
    return true;
  }
  return false;
}

/* --- Polling timers ---------------------------------------- */

const _timers = new Map();

/**
 * Demarre un polling periodique. S'arrete automatiquement quand
 * l'onglet perd le focus (document.hidden) et reprend au retour.
 */
export function startPolling(name, fn, intervalMs) {
  stopPolling(name);
  let inFlight = false;

  const tick = async () => {
    if (document.hidden || inFlight) return;
    inFlight = true;
    try { await fn(); }
    catch (err) { console.warn(`[polling:${name}]`, err); }
    finally { inFlight = false; }
  };

  const id = setInterval(tick, intervalMs);
  _timers.set(name, id);
  // Premier tick immediat
  tick();
}

/** Arrete un polling nomme. */
export function stopPolling(name) {
  const id = _timers.get(name);
  if (id !== undefined) {
    clearInterval(id);
    _timers.delete(name);
  }
}

/** Arrete tous les pollings actifs. */
export function stopAllPolling() {
  for (const [name] of _timers) stopPolling(name);
}
