/* components/scraping-status.js — Pastilles NFO/TMDb/Sous-titres (dashboard, ES module). */

import { escapeHtml } from "../core/dom.js";

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

export function scrapingStatusHtml(row, settings) {
  if (!row) return "";
  const nfo = _nfoState(row);
  const tmdb = _tmdbState(row);
  const subs = _subtitleState(row, settings);
  return `<span class="scrape-status" aria-label="Statut scraping"
    ><span class="scrape-pill scrape-pill--${nfo.state}" data-tip="${escapeHtml(nfo.label)}"></span
    ><span class="scrape-pill scrape-pill--${tmdb.state}" data-tip="${escapeHtml(tmdb.label)}"></span
    ><span class="scrape-pill scrape-pill--${subs.state}" data-tip="${escapeHtml(subs.label)}"></span
  ></span>`;
}
