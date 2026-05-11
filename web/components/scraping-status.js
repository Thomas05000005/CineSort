/* components/scraping-status.js — Pastilles NFO/TMDb/Sous-titres (F2)
 *
 * Retourne 3 pastilles colorees :
 *   - NFO    : vert si present+coherent, orange present incoherent, gris absent
 *   - TMDb   : vert si confiance >= 80, orange 50-79, rouge <50 ou absent
 *   - Subs   : vert si toutes langues attendues presentes, orange partiel, rouge absent
 *
 * Usage :
 *   scrapingStatusHtml(row, settings)
 */

function _nfoState(row) {
  if (!row.nfo_path) return { state: "missing", label: "NFO absent" };
  const flags = row.warning_flags || [];
  if (flags.some((f) => f === "nfo_incoherent" || f === "nfo_title_mismatch" || f === "nfo_year_mismatch")) {
    return { state: "warn", label: "NFO incoherent" };
  }
  return { state: "ok", label: "NFO OK" };
}

function _tmdbState(row) {
  const conf = Number(row.confidence || 0);
  const src = String(row.proposed_source || row.source || "");
  if (!row.tmdb_id && src !== "tmdb") {
    return { state: "missing", label: "TMDb absent" };
  }
  if (conf >= 80) return { state: "ok", label: `TMDb OK (${conf}%)` };
  if (conf >= 50) return { state: "warn", label: `TMDb moyen (${conf}%)` };
  return { state: "missing", label: `TMDb faible (${conf}%)` };
}

function _subtitleState(row, settings) {
  const expected = (settings && settings.subtitle_expected_languages) || ["fr"];
  const langs = row.subtitle_languages || [];
  const missing = row.subtitle_missing_langs || [];
  if (langs.length === 0) return { state: "missing", label: "Aucun sous-titre" };
  if (missing.length === 0) return { state: "ok", label: `Sous-titres : ${langs.join(", ")}` };
  return { state: "warn", label: `Manque : ${missing.join(", ")}` };
}

/**
 * @param {object} row - PlanRow (avec nfo_path, confidence, subtitle_*, warning_flags...)
 * @param {object} [settings] - settings globaux (subtitle_expected_languages)
 * @returns {string} HTML des 3 pastilles
 */
function scrapingStatusHtml(row, settings) {
  if (!row) return "";
  const nfo = _nfoState(row);
  const tmdb = _tmdbState(row);
  const subs = _subtitleState(row, settings);
  return `<span class="scrape-status" aria-label="Statut scraping"
    ><span class="scrape-pill scrape-pill--${nfo.state}" data-tip="${_escape(nfo.label)}"></span
    ><span class="scrape-pill scrape-pill--${tmdb.state}" data-tip="${_escape(tmdb.label)}"></span
    ><span class="scrape-pill scrape-pill--${subs.state}" data-tip="${_escape(subs.label)}"></span
  ></span>`;
}

function _escape(s) {
  return String(s).replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;" })[c]);
}

if (typeof window !== "undefined") {
  window.scrapingStatusHtml = scrapingStatusHtml;
}
