/* core/format.js — Helpers de formatage partages locale-aware (V6-04, R4-I18N-3).
 *
 * Charge avant les vues. Toutes les fonctions exposees sur window pour
 * compatibilite avec le pattern <script src> non-module du desktop.
 *
 * Locale-aware via Intl.* + lecture localStorage("cinesort_locale") (defaut "fr").
 * Ne depend PAS du module ES core/i18n.js (script global, pas d'import).
 *
 * API publique exposee sur window (compat 100% + nouveaux helpers V6-04) :
 *   - fmtDurationSec(s)   : compat — "1h 23m" / "23m 5s" / "45s" / "—"
 *   - fmtEta(s)           : compat — alias de fmtDurationSec
 *   - fmtSpeed(v)         : compat — locale-aware (FR ',' / EN '.')
 *   - fmtDateTime(ts)     : compat — datetime court
 *   - fmtFileSize(b)      : compat — "12 Ko" (FR) / "12 KB" (EN)
 *
 *   - formatDate(t)       : NEW — date courte locale
 *   - formatDateTime(t)   : NEW — alias de fmtDateTime (signature identique)
 *   - formatRelative(t)   : NEW — "il y a 5 min" via Intl.RelativeTimeFormat
 *   - formatNumber(n)     : NEW — "1 234" / "1,234"
 *   - formatBytes(b, d)   : NEW — alias de fmtFileSize avec decimals configurables
 *   - formatDuration(s)   : NEW — alias de fmtDurationSec
 *   - formatPercent(n, d) : NEW — "87 %" / "87%"
 */

(function () {
  "use strict";

  var SUPPORTED = ["fr", "en"];
  var DEFAULT_LOCALE = "fr";
  var LOCALE_MAP = { fr: "fr-FR", en: "en-US" };
  var DASH = "—";

  function _readLocale() {
    try {
      var raw = window.localStorage && window.localStorage.getItem("cinesort_locale");
      if (raw && SUPPORTED.indexOf(raw) !== -1) return raw;
    } catch (e) { /* localStorage indisponible */ }
    return DEFAULT_LOCALE;
  }

  function _intlLocale() {
    return LOCALE_MAP[_readLocale()] || LOCALE_MAP.fr;
  }

  function _toDate(input) {
    if (input == null || input === "") return null;
    if (input instanceof Date) {
      return isNaN(input.getTime()) ? null : input;
    }
    if (typeof input === "number") {
      if (!isFinite(input) || input <= 0) return null;
      var ms = input >= 1e11 ? input : input * 1000;
      var d = new Date(ms);
      return isNaN(d.getTime()) ? null : d;
    }
    if (typeof input === "string") {
      var t = input.trim();
      if (!t) return null;
      if (/^\d+(\.\d+)?$/.test(t)) return _toDate(Number(t));
      var d2 = new Date(t);
      return isNaN(d2.getTime()) ? null : d2;
    }
    return null;
  }

  /* ----------------------------------------------------------------------- */
  /* Compat (v5)                                                              */
  /* ----------------------------------------------------------------------- */

  function fmtDurationSec(s) {
    var n = Number(s || 0);
    if (!isFinite(n) || n <= 0) return DASH;
    var h = Math.floor(n / 3600);
    var m = Math.floor((n % 3600) / 60);
    var r = Math.floor(n % 60);
    if (h > 0) return h + "h " + m + "m";
    if (m > 0) return m + "m " + r + "s";
    return r + "s";
  }

  function fmtEta(s) {
    return fmtDurationSec(s);
  }

  function fmtSpeed(v) {
    var n = Number(v || 0);
    if (!isFinite(n)) return "0";
    try {
      return new Intl.NumberFormat(_intlLocale(), {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(n);
    } catch (e) {
      return n.toFixed(2);
    }
  }

  function fmtDateTime(ts) {
    var d = _toDate(ts);
    if (!d) return DASH;
    try {
      return new Intl.DateTimeFormat(_intlLocale(), {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(d);
    } catch (e) {
      return DASH;
    }
  }

  function fmtFileSize(bytes) {
    return formatBytes(bytes, 2);
  }

  /* ----------------------------------------------------------------------- */
  /* V6-04 (locale-aware)                                                     */
  /* ----------------------------------------------------------------------- */

  function formatDate(t) {
    var d = _toDate(t);
    if (!d) return DASH;
    try {
      return new Intl.DateTimeFormat(_intlLocale(), { dateStyle: "short" }).format(d);
    } catch (e) {
      return DASH;
    }
  }

  function formatDateTime(t) {
    return fmtDateTime(t);
  }

  function formatRelative(t) {
    var d = _toDate(t);
    if (!d) return DASH;
    var diffMs = d.getTime() - Date.now();
    var absSec = Math.abs(diffMs / 1000);
    var fmt;
    try {
      fmt = new Intl.RelativeTimeFormat(_intlLocale(), { numeric: "auto" });
    } catch (e) {
      return DASH;
    }
    var units = [
      [60, "second"],
      [3600, "minute"],
      [86400, "hour"],
      [86400 * 7, "day"],
      [86400 * 30, "week"],
      [86400 * 365, "month"],
      [Infinity, "year"],
    ];
    var unit = "second";
    var divisor = 1;
    for (var i = 0; i < units.length; i++) {
      if (absSec < units[i][0]) {
        unit = units[i][1];
        divisor = i === 0 ? 1 : units[i - 1][0];
        break;
      }
    }
    var value = Math.round(diffMs / 1000 / divisor);
    try {
      return fmt.format(value, unit);
    } catch (e) {
      return DASH;
    }
  }

  function formatNumber(n) {
    var v = Number(n);
    if (!isFinite(v)) return "0";
    try {
      return new Intl.NumberFormat(_intlLocale()).format(v);
    } catch (e) {
      return String(v);
    }
  }

  function formatBytes(bytes, decimals) {
    var b = Number(bytes);
    if (!isFinite(b) || b <= 0) return "0";
    var dec = (decimals == null) ? 1 : decimals;
    var code = _readLocale();
    var units = code === "en"
      ? ["B", "KB", "MB", "GB", "TB"]
      : ["o", "Ko", "Mo", "Go", "To"];
    var i = 0;
    var n = b;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i += 1;
    }
    var maxDec = i <= 1 ? 0 : dec;
    try {
      var numFmt = new Intl.NumberFormat(_intlLocale(), {
        maximumFractionDigits: maxDec,
        minimumFractionDigits: 0,
      });
      return numFmt.format(n) + " " + units[i];
    } catch (e) {
      return n.toFixed(maxDec) + " " + units[i];
    }
  }

  function formatDuration(s) {
    return fmtDurationSec(s);
  }

  function formatPercent(n, decimals) {
    var v = Number(n);
    if (!isFinite(v)) return "0%";
    var dec = (decimals == null) ? 0 : decimals;
    try {
      var numFmt = new Intl.NumberFormat(_intlLocale(), {
        maximumFractionDigits: dec,
        minimumFractionDigits: 0,
      });
      var sep = _readLocale() === "en" ? "" : " ";
      return numFmt.format(v) + sep + "%";
    } catch (e) {
      return v.toFixed(dec) + "%";
    }
  }

  /* Expose globalement pour compat scripts non-module */
  window.fmtDurationSec = fmtDurationSec;
  window.fmtEta = fmtEta;
  window.fmtSpeed = fmtSpeed;
  window.fmtDateTime = fmtDateTime;
  window.fmtFileSize = fmtFileSize;
  window.formatDate = formatDate;
  window.formatDateTime = formatDateTime;
  window.formatRelative = formatRelative;
  window.formatNumber = formatNumber;
  window.formatBytes = formatBytes;
  window.formatDuration = formatDuration;
  window.formatPercent = formatPercent;
})();
