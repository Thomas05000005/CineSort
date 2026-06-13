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

// Fix audit 2026-05-25 (v1.5.5) Vague J : fallback hardcode minimal pour les
// cles critiques de la sidebar/topbar. Si fetch des locales JSON foire (404,
// timeout, bundle PyInstaller sans dossier locales/), on affiche au moins
// un texte humain au lieu de cles brutes type "sidebar.brand_name".
// Cle = chemin dotted complet, valeur = traduction FR.
const _FALLBACK_FR = Object.freeze({
  "sidebar.brand_name": "CineSort",
  "sidebar.brand_desc": "Organisation de films",
  "sidebar.nav.home": "Accueil",
  "sidebar.nav.processing": "Traitement",
  "sidebar.nav.library": "Bibliothèque",
  "sidebar.nav.doublons": "Doublons",
  "sidebar.nav.quality": "Qualité",
  "sidebar.nav.history": "Historique",
  "sidebar.nav.qij": "QIJ",
  "sidebar.nav.settings": "Parametres",
  "sidebar.nav.help": "Aide",
  "sidebar.aria_label": "Navigation CineSort",
  "sidebar.about": "A propos",
  "sidebar.about_aria": "A propos de CineSort",
  "sidebar.collapse": "Reduire",
  "sidebar.expand": "Deployer",
  "sidebar.collapse_expand": "{{action}} la sidebar",
  "sidebar.title_with_shortcut": "{{label}} ({{shortcut}})",
  "sidebar.counter_aria": "Compteur {{label}}",
  "sidebar.integration_disabled_title": "{{label}} desactive",
  "sidebar.update_badge_title": "MAJ disponible : {{version}}",
  "topbar.search_label": "Rechercher",
});

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

// Fix audit 2026-05-26 (v1.5.6) Vague L (i18n-1) :
// retry exponentiel sur le fetch des locales. Avant, _fetchLocale retournait
// {} silencieusement sur la premiere erreur reseau, et initI18n n'avait aucun
// retry : l'utilisateur restait coince avec les cles brutes (modulo le
// fallback hardcode minimal) jusqu'a refresh page. On essaie maintenant
// 3 fois avec backoff 500ms / 1500ms / 4500ms avant d'abandonner.
const _FETCH_RETRY_DELAYS_MS = [500, 1500, 4500];

async function _fetchLocaleOnce(locale) {
  const url = `/locales/${encodeURIComponent(locale)}.json`;
  const resp = await fetch(url, { method: "GET", credentials: "same-origin" });
  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  const data = await resp.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("not an object");
  }
  return data;
}

async function _sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function _fetchLocale(locale) {
  // Sert depuis /locales/<locale>.json — handler REST cf rest_server.py.
  // Cache-control geree cote serveur. Pas de cache local : on reload a chaque
  // setLocale pour permettre l'edition des JSON sans hard-refresh.
  const url = `/locales/${encodeURIComponent(locale)}.json`;
  let lastErr = null;
  for (let attempt = 0; attempt < _FETCH_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      return await _fetchLocaleOnce(locale);
    } catch (err) {
      lastErr = err;
      const delay = _FETCH_RETRY_DELAYS_MS[attempt];
      console.warn(`[i18n] fetch ${url} attempt ${attempt + 1}/${_FETCH_RETRY_DELAYS_MS.length} failed:`, err);
      // Sur la derniere tentative on ne dort pas inutilement.
      if (attempt < _FETCH_RETRY_DELAYS_MS.length - 1) {
        await _sleep(delay);
      }
    }
  }
  console.warn(`[i18n] fetch ${url} gave up after ${_FETCH_RETRY_DELAYS_MS.length} attempts. last error:`, lastErr);
  return {};
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
  // Fix audit 2026-05-25 (v1.5.5) Vague J : si rien charge encore (race au
  // boot : sidebar render avant que /locales/fr.json soit fetched) OU si
  // fetch a echoue (404, timeout, bundle sans locales/), on consulte le
  // dictionnaire FR minimal hardcode. Empeche d'afficher "sidebar.brand_name"
  // brut a l'utilisateur, meme dans le pire scenario reseau.
  if (template == null && Object.prototype.hasOwnProperty.call(_FALLBACK_FR, key)) {
    template = _FALLBACK_FR[key];
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
    try {
      const results = await Promise.all(tasks);
      _state.messages[DEFAULT_LOCALE] = results[0];
      if (stored !== DEFAULT_LOCALE) _state.messages[stored] = results[1];
      _state.locale = stored;
      // Fix audit 2026-05-25 (v1.5.5) Vague J : notifier les observers au boot
      // egalement (pas seulement dans setLocale). Sinon, si app.js timeout sur
      // initI18n (Promise.race 1500ms) et mount la sidebar avec les fallbacks
      // hardcodes/cles brutes, la promesse de fetch peut resoudre APRES le
      // mount et la sidebar reste avec le rendu degrade jusqu'au prochain
      // setLocale(). Avec ce notify, les composants observers re-render avec
      // les vrais messages des JSON des qu'ils arrivent.
      _notifyObservers();
      return _state.locale;
    } catch (err) {
      // Fix audit 2026-05-24 : si le fetch echoue (reseau lent, fichier absent,
      // timeout 1500ms cote app.js), on reset bootPromise pour permettre un
      // retry au prochain appel a initI18n. Sinon toutes les t() retournent
      // les cles brutes ('sidebar.nav.home' au lieu de 'Accueil') jusqu'au
      // refresh page.
      _state.bootPromise = null;
      throw err;
    }
  })();
  return _state.bootPromise;
}

/**
 * Fix audit 2026-05-26 (v1.5.6) Vague L (i18n-1) :
 * Force le rechargement des messages d'une locale (ou la locale active si
 * non specifiee). Reset les messages caches AVANT le fetch pour que t()
 * retombe sur les fallbacks pendant la nouvelle requete (au lieu de servir
 * potentiellement un vieux JSON corrompu/incomplet).
 *
 * @param {string} [locale] - locale a recharger ; defaut: la locale active.
 * @returns {Promise<boolean>} true si le rechargement a abouti a un objet non-vide.
 */
export async function reloadLocale(locale) {
  const target = String(locale || _state.locale || DEFAULT_LOCALE).trim().toLowerCase();
  if (!SUPPORTED_LOCALES.includes(target)) {
    console.warn(`[i18n] reloadLocale: ignored invalid locale "${locale}"`);
    return false;
  }
  // Reset AVANT fetch pour que t() tombe sur les fallbacks pendant le retry.
  _state.messages[target] = null;
  const data = await _fetchLocale(target);
  _state.messages[target] = data;
  if (target === _state.locale) {
    _notifyObservers();
  }
  return Boolean(data && Object.keys(data).length);
}

// Exports nommes uniquement — pas de default export pour eviter les confusions
// avec un usage `import t from ...`.
