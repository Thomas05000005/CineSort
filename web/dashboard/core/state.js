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

/** Stocke le token dans le storage approprie. */
export function setToken(token, persist = false) {
  const val = String(token || "").trim();
  setPersistent(persist);
  try {
    sessionStorage.setItem(TOKEN_KEY, val);
    if (persist) localStorage.setItem(TOKEN_KEY, val);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* no-op */ }
}

/** Efface le token de tous les storages. */
export function clearToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(PERSIST_KEY);
  } catch { /* no-op */ }
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
