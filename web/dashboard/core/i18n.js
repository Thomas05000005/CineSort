/* core/i18n.js — Infrastructure i18n frontend (V6-01, Polish Total v7.7.0).
 *
 * Module ESM exposant :
 *   - t(key, params?)            : lookup avec fallback `key` si manquant + interpolation {{var}}
 *   - setLocale(locale)          : charge le JSON correspondant (fetch /locales/<locale>.json)
 *   - getLocale()                : locale active
 *   - getAvailableLocales()      : liste des locales supportees ["fr", "en"]
 *   - onLocaleChange(callback)   : observer pattern (pour vues qui re-render)
 *   - unsubscribeLocaleChange(cb): retrait observer (cleanup)
 *
 * Stockage : localStorage.cinesort_locale (defaut "fr").
 * Convention de cle : category.subcategory.detail (ex. settings.tmdb.api_key_label).
 * Interpolation : t("settings.saved_at", { time: "12:34" }) -> "Sauvegarde a 12:34".
 *
 * Compatibilite 100% : si t("missing.key") -> retourne "missing.key" (pas de crash).
 * Zero dependance externe (fetch + JSON natifs).
 *
 * Convention pour V6-02/03/04/05/06 : appeler `t("...")` partout dans les vues,
 * meme si la cle n'existe pas encore — elle sera ajoutee en V6-02 (extraction).
 */

const SUPPORTED_LOCALES = Object.freeze(["fr", "en"]);
const DEFAULT_LOCALE = "fr";
const STORAGE_KEY = "cinesort_locale";
const INTERPOLATION_RE = /\{\{\s*([A-Za-z0-9_\-]+)\s*\}\}/g;

// Etat module — un singleton par window. Les sous-vues importent toutes le meme.
const _state = {
  locale: DEFAULT_LOCALE,
  messages: {
    fr: null,   // null = pas encore charge ; {} = charge mais vide ; { ... } = charge ok
    en: null,
  },
  observers: new Set(),
  bootPromise: null,
};

/* ------------------------------------------------------------------------- */
/* Helpers internes                                                          */
/* ------------------------------------------------------------------------- */

function _readStoredLocale() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw && SUPPORTED_LOCALES.includes(raw)) return raw;
  } catch { /* localStorage indisponible (mode prive, etc.) */ }
  return DEFAULT_LOCALE;
}

function _persistLocale(locale) {
  try { localStorage.setItem(STORAGE_KEY, locale); }
  catch { /* no-op */ }
}

function _lookupDotted(messages, key) {
  if (!messages || typeof key !== "string" || !key) return null;
  const parts = key.split(".");
  let node = messages;
  for (const part of parts) {
    if (node == null || typeof node !== "object") return null;
    node = node[part];
    if (node === undefined) return null;
  }
  return typeof node === "string" ? node : null;
}

function _interpolate(template, params) {
  if (!params) return template;
  return template.replace(INTERPOLATION_RE, (match, name) => {
    if (Object.prototype.hasOwnProperty.call(params, name)) {
      return String(params[name]);
    }
    return match;   // variable manquante : laisse tel quel (visible)
  });
}

async function _fetchLocale(locale) {
  // Sert depuis /locales/<locale>.json — handler REST cf rest_server.py.
  // Cache-control geree cote serveur. Pas de cache local : on reload a chaque
  // setLocale pour permettre l'edition des JSON sans hard-refresh.
  const url = `/locales/${encodeURIComponent(locale)}.json`;
  try {
    const resp = await fetch(url, { method: "GET", credentials: "same-origin" });
    if (!resp.ok) {
      console.warn(`[i18n] fetch ${url} failed: HTTP ${resp.status}`);
      return {};
    }
    const data = await resp.json();
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      console.warn(`[i18n] ${url} did not return an object`);
      return {};
    }
    return data;
  } catch (err) {
    console.warn(`[i18n] fetch ${url} error:`, err);
    return {};
  }
}

function _notifyObservers() {
  for (const cb of _state.observers) {
    try { cb(_state.locale); }
    catch (err) { console.warn("[i18n] observer error:", err); }
  }
}

/* ------------------------------------------------------------------------- */
/* API publique                                                              */
/* ------------------------------------------------------------------------- */

/**
 * Lookup d'un message avec interpolation {{var}}.
 *
 * @param {string} key - Cle dot-separee, ex. "settings.tmdb.api_key_label".
 * @param {Object<string,*>} [params] - Variables interpolees ({ time: "12:34" }).
 * @returns {string} Message traduit, ou `key` si introuvable (fallback).
 *
 * Aucun crash : la fonction retombe toujours sur la cle, jamais sur null/undefined.
 */
export function t(key, params) {
  if (typeof key !== "string" || !key) return "";
  const msgs = _state.messages[_state.locale] || null;
  let template = _lookupDotted(msgs, key);
  // Fallback locale par defaut si manquant dans la locale active
  if (template == null && _state.locale !== DEFAULT_LOCALE) {
    template = _lookupDotted(_state.messages[DEFAULT_LOCALE], key);
  }
  if (template == null) return key;
  return _interpolate(template, params || null);
}

/**
 * Change la locale active et charge le JSON correspondant si necessaire.
 *
 * @param {"fr"|"en"} locale
 * @returns {Promise<void>} Promesse resolue apres chargement et notification observers.
 *
 * Locale invalide -> Promise resolue, aucun changement, warn console.
 */
export async function setLocale(locale) {
  const normalized = String(locale || "").trim().toLowerCase();
  if (!SUPPORTED_LOCALES.includes(normalized)) {
    console.warn(`[i18n] ignored invalid locale "${locale}"`);
    return;
  }
  // Charger si pas encore en cache
  if (_state.messages[normalized] == null) {
    _state.messages[normalized] = await _fetchLocale(normalized);
  }
  if (normalized !== _state.locale) {
    _state.locale = normalized;
    _persistLocale(normalized);
    _notifyObservers();
  }
}

/** Retourne la locale active (defaut: "fr"). */
export function getLocale() {
  return _state.locale;
}

/** Retourne la liste figee des locales supportees. */
export function getAvailableLocales() {
  return SUPPORTED_LOCALES.slice();
}

/**
 * Enregistre un callback appele a chaque changement de locale.
 *
 * @param {(locale: string) => void} callback
 * @returns {() => void} Fonction de desabonnement.
 */
export function onLocaleChange(callback) {
  if (typeof callback !== "function") {
    return () => { /* no-op */ };
  }
  _state.observers.add(callback);
  return () => _state.observers.delete(callback);
}

/**
 * Retire explicitement un observer (alternative au retour de onLocaleChange).
 * @param {Function} callback
 */
export function unsubscribeLocaleChange(callback) {
  _state.observers.delete(callback);
}

/**
 * Initialise le module au boot du dashboard. A appeler UNE fois depuis app.js.
 * Lit la locale persistee dans localStorage et charge le JSON correspondant +
 * toujours la locale FR par defaut (fallback messages).
 *
 * @returns {Promise<string>} La locale active apres init.
 */
export async function initI18n() {
  if (_state.bootPromise) return _state.bootPromise;
  _state.bootPromise = (async () => {
    const stored = _readStoredLocale();
    // Toujours pre-charger FR (fallback). En meme temps, charger la locale stored.
    const tasks = [_fetchLocale(DEFAULT_LOCALE)];
    if (stored !== DEFAULT_LOCALE) tasks.push(_fetchLocale(stored));
    const results = await Promise.all(tasks);
    _state.messages[DEFAULT_LOCALE] = results[0];
    if (stored !== DEFAULT_LOCALE) _state.messages[stored] = results[1];
    _state.locale = stored;
    return _state.locale;
  })();
  return _state.bootPromise;
}

// Exports nommes uniquement — pas de default export pour eviter les confusions
// avec un usage `import t from ...`.
