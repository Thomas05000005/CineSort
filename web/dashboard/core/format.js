/* core/format.js — Helpers de formatage partages locale-aware (V6-04, R4-I18N-3).
 *
 * Module ESM. Toutes les fonctions de formatage utilisent Intl.* + getLocale()
 * de i18n.js pour produire un rendu adapte a la locale active (FR ou EN).
 *
 * API publique (compatibilite 100% avec V5 + nouveaux helpers V6-04) :
 *   - fmtDate(ts)          : compat — datetime court "01/02/2026 14:30" (FR) / "2/1/2026, 2:30 PM" (EN)
 *   - fmtDuration(seconds) : compat — "45s" / "12m 5s" / "1h 23m" (memes labels FR/EN)
 *   - fmtBytes(bytes)      : compat — "12 Ko" (FR) / "12 KB" (EN)
 *   - fmtSpeed(speed)      : compat — "1,2 films/s" (FR) / "1.2 films/s" (EN)
 *
 *   - formatDate(t)        : NEW — date courte "04/05/2026" (FR) / "5/4/2026" (EN)
 *   - formatDateTime(t)    : NEW — date+heure courte
 *   - formatRelative(t)    : NEW — "il y a 5 min" (FR) / "5 min ago" (EN)
 *   - formatNumber(n)      : NEW — "1 234" (FR) / "1,234" (EN)
 *   - formatBytes(b, dec)  : NEW — alias plus explicite de fmtBytes (decimals configurables)
 *   - formatDuration(sec)  : NEW — alias de fmtDuration (signature identique)
 *   - formatPercent(n, d)  : NEW — "87 %" (FR avec NBSP) / "87%" (EN sans espace)
 *
 * Convention timestamps : `t` peut etre Unix seconds (int/float), ms (>= 1e12),
 * ou ISO string. Detecte automatiquement.
 *
 * Inspires de web/core/format.js (desktop). Resout R4-I18N-3.
 */

import { getLocale } from "./i18n.js";

const _LOCALE_MAP = Object.freeze({ fr: "fr-FR", en: "en-US" });
const _DASH = "—";

/* ------------------------------------------------------------------------- */
/* Helpers internes                                                          */
/* ------------------------------------------------------------------------- */

function _intlLocale() {
  const code = getLocale();
  return _LOCALE_MAP[code] || _LOCALE_MAP.fr;
}

/**
 * Normalise un input de timestamp vers un objet Date.
 * Accepte : Unix seconds (n < 1e11), Unix ms (n >= 1e11), ISO string.
 * Retourne null si invalide.
 */
function _toDate(input) {
  if (input == null || input === "") return null;
  if (input instanceof Date) {
    return Number.isNaN(input.getTime()) ? null : input;
  }
  if (typeof input === "number") {
    if (!Number.isFinite(input) || input <= 0) return null;
    // Heuristique : > 1e11 = millisecondes, sinon secondes.
    const ms = input >= 1e11 ? input : input * 1000;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed) return null;
    // Si c'est numeric-only on tente seconds/ms.
    if (/^\d+(\.\d+)?$/.test(trimmed)) {
      return _toDate(Number(trimmed));
    }
    const d = new Date(trimmed);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

/* ------------------------------------------------------------------------- */
/* API compat (V5)                                                           */
/* ------------------------------------------------------------------------- */

/**
 * Compat V5 : datetime court.
 * Locale FR -> "01/02/2026 14:30". Locale EN -> "2/1/2026, 2:30 PM".
 */
export function fmtDate(ts) {
  const d = _toDate(ts);
  if (!d) return _DASH;
  try {
    return new Intl.DateTimeFormat(_intlLocale(), {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return _DASH;
  }
}

/**
 * Compat V5 : duree humaine, labels (s/m/h) volontairement uniformes
 * cross-locale (jargon technique court). Pour Intl.RelativeTimeFormat
 * humainement traduit, voir formatRelative().
 */
export function fmtDuration(seconds) {
  const s = Math.round(Number(seconds) || 0);
  if (s <= 0) return _DASH;
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}min ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/**
 * Compat V5 : taille en octets, suffixes localises.
 * FR : "12 Ko" / "3,4 Mo" / "1,23 Go" / "1,23 To"
 * EN : "12 KB" / "3.4 MB" / "1.23 GB" / "1.23 TB"
 */
export function fmtBytes(bytes) {
  return formatBytes(bytes);
}

/**
 * Compat V5 : vitesse films/s.
 * FR : "1,2 films/s". EN : "1.2 films/s".
 */
export function fmtSpeed(speed) {
  const v = Number(speed) || 0;
  if (v <= 0) return _DASH;
  const formatted = new Intl.NumberFormat(_intlLocale(), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(v);
  return `${formatted} films/s`;
}

/* ------------------------------------------------------------------------- */
/* API V6-04 (locale-aware)                                                  */
/* ------------------------------------------------------------------------- */

/**
 * Date format court : "04/05/2026" (FR) ou "5/4/2026" (EN).
 * @param {number|string|Date} t Timestamp (sec, ms, ISO) ou Date.
 * @returns {string} Date formatee, ou "—" si invalide.
 */
export function formatDate(t) {
  const d = _toDate(t);
  if (!d) return _DASH;
  try {
    return new Intl.DateTimeFormat(_intlLocale(), { dateStyle: "short" }).format(d);
  } catch {
    return _DASH;
  }
}

/**
 * Datetime : date courte + heure courte.
 * FR : "04/05/2026 12:34". EN : "5/4/2026, 12:34 PM".
 * @param {number|string|Date} t
 * @returns {string}
 */
export function formatDateTime(t) {
  const d = _toDate(t);
  if (!d) return _DASH;
  try {
    return new Intl.DateTimeFormat(_intlLocale(), {
      dateStyle: "short",
      timeStyle: "short",
    }).format(d);
  } catch {
    return _DASH;
  }
}

/**
 * Format relatif "il y a 5 min" (FR) / "5 min ago" (EN) via Intl.RelativeTimeFormat.
 * Selectionne automatiquement l'unite (sec/min/h/jour/sem/mois/annee).
 * @param {number|string|Date} t
 * @returns {string}
 */
export function formatRelative(t) {
  const d = _toDate(t);
  if (!d) return _DASH;
  const diffMs = d.getTime() - Date.now();
  const absSec = Math.abs(diffMs / 1000);
  const fmt = new Intl.RelativeTimeFormat(_intlLocale(), { numeric: "auto" });
  const units = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [86400 * 7, "day"],
    [86400 * 30, "week"],
    [86400 * 365, "month"],
    [Infinity, "year"],
  ];
  let value = diffMs / 1000;
  let unit = "second";
  let divisor = 1;
  for (let i = 0; i < units.length; i++) {
    const [threshold, u] = units[i];
    if (absSec < threshold) {
      unit = u;
      // diviseur de l'unite precedente (sec=1, min=60, h=3600, ...)
      divisor = i === 0 ? 1 : units[i - 1][0];
      break;
    }
  }
  value = Math.round(value / divisor);
  try {
    return fmt.format(value, unit);
  } catch {
    return _DASH;
  }
}

/**
 * Number format : "1 234" (FR avec NBSP) / "1,234" (EN).
 * @param {number} n
 * @returns {string}
 */
export function formatNumber(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "0";
  try {
    return new Intl.NumberFormat(_intlLocale()).format(v);
  } catch {
    return String(v);
  }
}

/**
 * Bytes format avec separateur decimal locale-aware + suffixes FR/EN.
 * FR : "1,5 Ko" / "2,3 Mo" / "4,5 Go". EN : "1.5 KB" / "2.3 MB" / "4.5 GB".
 * @param {number} bytes Taille en octets.
 * @param {number} [decimals=1] Nombre max de decimales (sauf Ko qui restent entiers).
 * @returns {string}
 */
export function formatBytes(bytes, decimals = 1) {
  const b = Number(bytes);
  if (!Number.isFinite(b) || b <= 0) return "0";
  const code = getLocale();
  const units = code === "en"
    ? ["B", "KB", "MB", "GB", "TB"]
    : ["o", "Ko", "Mo", "Go", "To"];
  let i = 0;
  let n = b;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  // Ko/KB restent entiers (lisibilite), au-dela on autorise les decimales.
  const maxDec = i <= 1 ? 0 : decimals;
  const numFmt = new Intl.NumberFormat(_intlLocale(), {
    maximumFractionDigits: maxDec,
    minimumFractionDigits: 0,
  });
  return `${numFmt.format(n)} ${units[i]}`;
}

/**
 * Duree en secondes, format court technique (signature identique a fmtDuration).
 * Conserve les labels s/m/h pour stabilite tests + UX.
 * @param {number} seconds
 * @returns {string}
 */
export function formatDuration(seconds) {
  return fmtDuration(seconds);
}

/**
 * Pourcentage : "87 %" (FR avec NBSP) / "87%" (EN sans espace).
 * @param {number} n Valeur 0-100 (NB : pas 0-1 ; on est cote UI).
 * @param {number} [decimals=0]
 * @returns {string}
 */
export function formatPercent(n, decimals = 0) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "0%";
  const numFmt = new Intl.NumberFormat(_intlLocale(), {
    maximumFractionDigits: decimals,
    minimumFractionDigits: 0,
  });
  const formatted = numFmt.format(v);
  // FR : NBSP (U+00A0) entre nombre et %. EN : pas d'espace.
  const sep = getLocale() === "en" ? "" : " ";
  return `${formatted}${sep}%`;
}
