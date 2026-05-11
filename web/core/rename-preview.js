/* core/rename-preview.js — Preview du nouveau chemin apres rename (F4)
 *
 * Port JS simplifie de cinesort/domain/naming.py : applique le template aux
 * champs disponibles (title, year, resolution, video_codec, tmdb_tag, edition,
 * series, season, episode). Nettoie les separateurs orphelins.
 *
 * Note : version approximative cote frontend — le backend reste autoritaire
 * au moment de l'apply. Utilise uniquement pour previsualisation UI.
 */

const _VAR_RE = /\{([a-zA-Z][a-zA-Z0-9_-]*)\}/g;

/**
 * Construit le contexte de variables depuis un row + decision.
 */
function _buildContext(row, decision) {
  const d = decision || {};
  const title = String(d.title || row.proposed_title || "").trim();
  const year = Number(d.year || row.proposed_year || 0) || 0;
  const edition = row.edition || "";
  const tmdbId = row.tmdb_id || (Array.isArray(row.candidates) && row.candidates[0] && row.candidates[0].tmdb_id) || 0;
  const probe = row.probe || {};
  const video = (probe.video || row.video_detail || {}) || {};

  return {
    title,
    year: year > 0 ? String(year) : "",
    resolution: row.resolution || video.resolution_label || "",
    video_codec: row.video_codec || video.codec || "",
    hdr: row.hdr || "",
    audio_codec: row.audio_codec || "",
    channels: row.channels || "",
    quality: row.quality_label || "",
    score: row.score != null ? String(Math.round(Number(row.score))) : "",
    tmdb_id: tmdbId ? String(tmdbId) : "",
    tmdb_tag: tmdbId ? `{tmdb-${tmdbId}}` : "",
    edition: edition,
    "edition-tag": edition ? `{edition-${edition}}` : "",
    series: row.tv_series_name || "",
    season: row.tv_season != null ? String(row.tv_season).padStart(2, "0") : "",
    episode: row.tv_episode != null ? String(row.tv_episode).padStart(2, "0") : "",
    ep_title: row.tv_episode_title || "",
    container: row.container || "",
    bitrate: row.bitrate_kbps != null ? String(row.bitrate_kbps) : "",
    source: row.proposed_source || "",
    original_title: row.original_title || "",
  };
}

function _cleanupOrphans(s) {
  /* Supprime [], (), {} vides et les espaces/tirets orphelins */
  let out = s
    .replace(/\[\s*\]/g, "")
    .replace(/\(\s*\)/g, "")
    .replace(/\s+-\s+-\s+/g, " - ")
    .replace(/\s{2,}/g, " ")
    .replace(/^\s*-\s*/, "")
    .replace(/\s*-\s*$/, "")
    .trim();
  return out;
}

/**
 * Applique un template aux donnees d'un row.
 * @param {string} template
 * @param {object} ctx - contexte (de _buildContext)
 * @returns {string}
 */
function _applyTemplate(template, ctx) {
  const rendered = String(template || "{title} ({year})").replace(_VAR_RE, (_match, key) => {
    return ctx[key] != null ? String(ctx[key]) : "";
  });
  return _cleanupOrphans(rendered);
}

/**
 * Calcule le nouveau chemin apres rename.
 * @param {object} row
 * @param {object} decision
 * @param {object} settings - settings globaux (naming_movie_template, etc.)
 * @returns {string} nouveau chemin relatif ou vide si insuffisant
 */
function computeNewPath(row, decision, settings) {
  const s = settings || {};
  const ctx = _buildContext(row, decision);
  if (!ctx.title) return "";

  const isTv = row.kind === "tv_episode" && ctx.series;
  const template = isTv
    ? (s.naming_tv_template || "{series} ({year})/Saison {season}/S{season}E{episode} - {ep_title}")
    : (s.naming_movie_template || "{title} ({year})");

  return _applyTemplate(template, ctx);
}

/**
 * Rendu HTML compact pour la table validation : "<old> → <new>"
 * ou juste "<new>" si chemin court.
 */
function renamePreviewHtml(row, decision, settings) {
  const newPath = computeNewPath(row, decision, settings);
  if (!newPath) return "";
  const oldBase = (row.folder || "").split(/[\\/]/).pop() || "";
  if (oldBase && oldBase === newPath) {
    return '<span class="rename-preview rename-preview--noop" data-tip="Deja conforme">✓ Conforme</span>';
  }
  const escape = window.escapeHtml || ((s) => String(s).replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c]));
  return `<span class="rename-preview" data-tip="${escape(newPath)}">→ ${escape(newPath)}</span>`;
}

if (typeof window !== "undefined") {
  window.computeNewPath = computeNewPath;
  window.renamePreviewHtml = renamePreviewHtml;
}
