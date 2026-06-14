/* components/film-detail.js — Modal Detail Film tri-mode (spec 06).
 *
 * Composant reutilisable consomme par 3 modes d'affichage :
 *
 *   Mode A — Inspecteur elargi  : injecte dans right-panel.setSections + setWidth(600)
 *   Mode B — Page standalone    : route /film/:id, mount dans un container plein-ecran
 *   Mode C — Modal overlay      : overlay 80vw cree dynamiquement + Esc/clic-backdrop
 *
 * Layout interne identique dans les 3 modes :
 *   Hero (poster + meta + score V2 + chemin)
 *   Synopsis repliable
 *   Alertes humanisees (alert-labels.js)
 *   Candidats TMDb avec mini-posters + bouton "Choisir"
 *   Onglets : Apercu / Analyse V2 / Historique / Renommage propose
 *   Actions principales (Valider, Analyser perceptuel, Ouvrir, Re-scan, Marquer suppression)
 *
 * Endpoints consommes (PR #303) :
 *   library/get_film_full(row_id)
 *   library/set_film_tmdb_candidate(run_id, row_id, tmdb_id)
 *   library/mark_for_deletion(run_id, row_id)
 *   library/mark_alert_ignored(row_id, alert_code)
 *   run/rescan_row(run_id, row_id)
 *   open_path(path)
 *   save_validation(run_id, decisions)
 *   analyze_perceptual_single(run_id, row_id) (relais perceptuel)
 *
 * Endpoints consommes (sprint orphelins #350) :
 *   quality/submit_score_feedback(run_id, row_id, user_tier, comment)
 *   quality/delete_score_feedback(feedback_id)
 *
 * API publique :
 *   renderFilmDetail({ mode, rowId, runId, container?, onClose? })
 *     -> Promise<void>
 *   closeFilmDetail()       ferme le mode C (overlay) actif
 */

import { escapeHtml, posterProxyUrl } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { labelsForFlags, countBySeverity } from "../core/alert-labels.js";
import { dangerConfirmModal, showModal, closeModal } from "./modal.js";
import { showToast } from "./toast.js";
import { openPerceptualModal } from "./perceptual-modal.js";
import * as rightPanel from "./right-panel.js";

const OVERLAY_ID = "filmDetailOverlay";

/* --- Module state (un seul film visible a la fois) --------------------- */

const _state = {
  mode: null,         // "A" | "B" | "C"
  rowId: null,
  runId: null,
  data: null,
  activeTab: "overview",
  containerEl: null,  // DOM cible (interieur)
  overlayEl: null,    // pour mode C
  onClose: null,
  showAllCandidates: false,
  loading: false,
  // sprint orphelins #350 : feedback utilisateur sur le scoring.
  // Apres soumission, on retient le feedback_id pour permettre annulation
  // (delete_score_feedback). Pas persiste cross-mount : la session courante
  // suffit, le calibration report agrege cote serveur.
  lastFeedback: null, // { id, user_tier, computed_tier } | null
};

/* ===========================================================
 * Formatters
 * =========================================================== */

function _formatDuration(min) {
  const m = Number(min) || 0;
  if (m <= 0) return "—";
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return h > 0 ? `${h}h${String(rest).padStart(2, "0")}` : `${rest} min`;
}

function _formatBytes(bytes) {
  const b = Number(bytes) || 0;
  if (b <= 0) return "—";
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} Ko`;
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} Go`;
}

/** Transforme une URL TMDb w92/w185/w342/w500 vers une autre taille. */
function _resizePosterUrl(url, targetSize) {
  if (!url) return null;
  const s = String(url);
  return s.replace(/\/t\/p\/w\d+\//, `/t/p/${targetSize}/`);
}

/* ===========================================================
 * Loader
 * =========================================================== */

async function _loadFilmFull(rowId, runId) {
  const params = { row_id: rowId };
  if (runId) params.run_id = runId;
  const res = await apiPost("library/get_film_full", params);
  const data = res && res.data ? res.data : res;
  if (!data || data.ok === false) {
    // Fix audit 2026-05-25 (v1.5.3) Vague F : prefere user_message (message UX clair)
    // avant de retomber sur message technique ou error. Evite l'affichage de
    // "Serveur indisponible (HTTP 500)" quand le backend a fourni un contrat propre.
    const userMsg = (data && data.user_message) || (data && data.message) || (data && data.error) || "Impossible de charger le film. Reessaye dans quelques instants.";
    throw new Error(userMsg);
  }
  return data;
}

/* ===========================================================
 * Skeleton + Error
 * =========================================================== */

function _renderSkeleton() {
  return `
    <div class="film-detail film-detail--loading" aria-busy="true">
      <div class="film-detail-hero film-detail-hero--skel">
        <div class="film-detail-poster v5-skeleton"></div>
        <div class="film-detail-meta">
          <div class="v5-skeleton" style="height:24px;width:60%;margin-bottom:8px;"></div>
          <div class="v5-skeleton" style="height:16px;width:40%;margin-bottom:8px;"></div>
          <div class="v5-skeleton" style="height:16px;width:80%;"></div>
        </div>
      </div>
      <div class="v5-skeleton" style="height:80px;margin-top:16px;"></div>
      <div class="v5-skeleton" style="height:120px;margin-top:16px;"></div>
    </div>
  `;
}

function _renderErrorState(msg) {
  return `
    <div class="film-detail film-detail--error" role="alert">
      <p class="film-detail-error-title">Impossible de charger le film.</p>
      <p class="film-detail-error-msg">${escapeHtml(msg || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--secondary" data-film-retry>Reessayer</button>
    </div>
  `;
}

/* ===========================================================
 * Hero
 * =========================================================== */

function _renderHero(data) {
  const row = data.row || {};
  const candidates = Array.isArray(row.candidates) ? row.candidates : [];
  const topCand = candidates[0] || {};
  const title = row.proposed_title || row.nfo_title || row.source_folder || topCand.title || "Film sans titre";
  const year = row.proposed_year || topCand.year || "";
  const runtime = data.runtime || topCand.runtime || null;
  const director = data.director || topCand.director || "";
  const genre = topCand.genre || (Array.isArray(topCand.genres) ? topCand.genres.join(", ") : "") || "";

  // Score V2
  const perc = data.perceptual || {};
  const gv2 = perc.global_score_v2 || {};
  const score = gv2.global_score != null ? Math.round(Number(gv2.global_score)) : null;
  const tier = String(gv2.global_tier || "unknown").toLowerCase();

  // Confidence
  const confidence = topCand.confidence != null
    ? Math.round(Number(topCand.confidence))
    : (row.confidence != null ? Math.round(Number(row.confidence)) : null);

  // Source d'identification (NFO / nom / TMDb...).
  // AUDIT 2026-06-13 (R5-I) : les rows exposent `proposed_source` (nfo/name/
  // tmdb), pas match_source/identification_source -> la stat affichait toujours
  // "—" alors que les films sont identifies (ex. par NFO). On lit la bonne cle.
  const _srcMap = { nfo: "NFO", name: "Nom de fichier", tmdb: "TMDb", imdb: "IMDb", unknown: "—" };
  const _rawSrc = String(row.match_source || row.identification_source || row.proposed_source || "").trim().toLowerCase();
  const source = _srcMap[_rawSrc] || (_rawSrc ? _rawSrc.toUpperCase() : "—");

  // Poster
  const posterUrl = data.poster_url || topCand.poster_url || null;
  // Fix audit 2026-05-24 (v1.5.2) : bouton refresh poster TMDb unitaire. Le
  // refresh bulk existait deja (vague A integrations) mais aucun moyen unitaire
  // depuis la fiche film. On greffe un bouton 🔄 absolument positionne au coin
  // du poster (mode A et B et C, layout identique via classe partagee).
  // tmdb_id resolu en priorite depuis le row puis topCand : sans tmdb_id on
  // n'affiche pas le bouton (impossible de cibler l'API).
  const tmdbIdForRefresh = row.chosen_tmdb_id || row.tmdb_id || topCand.tmdb_id || null;
  const refreshBtnHtml = tmdbIdForRefresh
    ? `<button type="button" class="film-detail-poster-refresh-btn"
              data-film-action="refresh-poster"
              data-tmdb-id="${escapeHtml(String(tmdbIdForRefresh))}"
              title="Rafraîchir le poster depuis TMDb"
              aria-label="Rafraîchir le poster depuis TMDb">🔄</button>`
    : "";
  // Iter12 ETAPE 2 : prioriser le proxy `/api/poster` (size w342 pour fiche film).
  // tmdbIdForRefresh est deja resolu plus haut depuis row/topCand. Fallback
  // sur `posterUrl` direct preserve backward compat (acquis 242cf339).
  const proxiedPosterUrl = posterProxyUrl(tmdbIdForRefresh, "w342");
  const posterSrc = proxiedPosterUrl || posterUrl || "";
  // AUDIT 2026-06-14 (R6-H) : onerror -> placeholder. Le proxy /api/poster peut
  // renvoyer un corps JSON (404 sans poster / 503 cle absente) au lieu d'une
  // image ; sans ce filet, l'<img> affiche une icone cassee.
  const posterInner = posterSrc
    ? `<img class="film-detail-poster" data-film-poster-img src="${escapeHtml(posterSrc)}" alt="${escapeHtml(title)}" loading="eager" onerror="this.onerror=null;this.replaceWith(Object.assign(document.createElement('div'),{className:'film-detail-poster film-detail-poster--placeholder',textContent:'🎬'}))">`
    : `<div class="film-detail-poster film-detail-poster--placeholder" aria-hidden="true">🎬</div>`;
  const posterHtml = `<div class="film-detail-poster-wrap">${posterInner}${refreshBtnHtml}</div>`;

  // Chemin + fichier
  // Compat ascendante : PlanRow expose `folder` (chemin) et `video` (nom fichier),
  // tandis que get_film_full historique utilisait `source_path` / `video_filename`.
  const sourcePath = row.source_path || row.source_folder || row.folder || "";
  const videoFilename = row.video_filename || row.video || "";
  const sizeStr = _formatBytes(row.size_bytes);

  // Score circle
  const scoreCircle = (typeof window !== "undefined" && window.ScoreV2 && typeof window.ScoreV2.scoreCircleHtml === "function" && score != null)
    ? window.ScoreV2.scoreCircleHtml({ score, tier })
    : (score != null ? `<div class="film-detail-score-fallback film-detail-tier-${escapeHtml(tier)}">${score}/100</div>` : "");

  const metaParts = [];
  if (year) metaParts.push(escapeHtml(String(year)));
  if (genre) metaParts.push(escapeHtml(genre));
  if (runtime) metaParts.push(_formatDuration(runtime));
  if (director) metaParts.push(`Réalisé par ${escapeHtml(director)}`);
  const metaLine = metaParts.join(" · ");

  const videoBlock = videoFilename
    ? `<div class="film-detail-file">📦 <span class="film-detail-file-name">${escapeHtml(videoFilename)}</span>${sizeStr !== "—" ? ` <span class="film-detail-file-size">(${escapeHtml(sizeStr)})</span>` : ""}</div>`
    : `<div class="film-detail-file film-detail-file--missing">⚠ Fichier vidéo non détecté
         <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-film-action="rescan">↻ Re-scanner</button>
       </div>`;

  return `
    <header class="film-detail-hero">
      ${posterHtml}
      <div class="film-detail-meta">
        <h2 id="film-detail-title" class="film-detail-title">
          ${escapeHtml(title)}${year ? ` <span class="film-detail-year">(${escapeHtml(String(year))})</span>` : ""}
        </h2>
        ${metaLine ? `<div class="film-detail-meta-line">${metaLine}</div>` : ""}
        <div class="film-detail-meta-stats">
          ${score != null ? `<div class="film-detail-score" data-film-action="open-analysis" title="Voir détail Score V2">${scoreCircle}</div>` : ""}
          ${confidence != null ? `<div class="film-detail-stat" title="Confiance globale que ce film est correctement identifié (titre + année)"><span class="film-detail-stat-label">Confiance d'identification</span><span class="film-detail-stat-value">${confidence}%</span></div>` : ""}
          <div class="film-detail-stat" title="Méthode d'identification du film"><span class="film-detail-stat-label">Identifié via</span><span class="film-detail-stat-value">${escapeHtml(source)}</span></div>
        </div>
        ${sourcePath ? `<div class="film-detail-path">📁 <span class="film-detail-path-text" title="${escapeHtml(sourcePath)}">${escapeHtml(sourcePath)}</span></div>` : ""}
        ${videoBlock}
      </div>
    </header>
  `;
}

/* ===========================================================
 * Synopsis (repliable)
 * =========================================================== */

function _renderSynopsis(data) {
  const overview = data.overview || (data.row && data.row.candidates && data.row.candidates[0] && data.row.candidates[0].overview) || "";
  if (!overview) return "";
  const long = String(overview).length > 200;
  const open = long ? "" : " open";
  return `
    <details class="film-detail-synopsis"${open}>
      <summary class="film-detail-synopsis-summary">Synopsis</summary>
      <p class="film-detail-synopsis-text">${escapeHtml(overview)}</p>
    </details>
  `;
}

/* ===========================================================
 * Alertes
 * =========================================================== */

function _renderAlerts(data) {
  const row = data.row || {};
  const perc = data.perceptual || {};
  const gv2 = perc.global_score_v2 || {};
  const rawFlags = [];
  if (Array.isArray(row.warning_flags)) rawFlags.push(...row.warning_flags);
  if (Array.isArray(gv2.warnings)) rawFlags.push(...gv2.warnings);
  // Spec 06 §3.3 : filtre les alertes deja ignorees (persiste backend via
  // film_modal.ignored_alerts ; get_film_full filtre deja row.warning_flags
  // mais pas gv2.warnings -> filtrage redondant cote front pour les 2 sources).
  const ignored = Array.isArray(row._ignored_alerts) ? new Set(row._ignored_alerts.map(String)) : null;
  const filteredFlags = ignored ? rawFlags.filter((f) => !ignored.has(String(f))) : rawFlags;
  const alerts = labelsForFlags(filteredFlags);
  if (alerts.length === 0) return "";
  const counts = countBySeverity(filteredFlags);
  const headIcon = counts.critical > 0 ? "🛑" : (counts.warning > 0 ? "⚠️" : "ℹ️");

  return `
    <section class="film-detail-alerts">
      <h3 class="film-detail-section-title">
        ${headIcon} ${alerts.length} alerte${alerts.length > 1 ? "s" : ""}
      </h3>
      <ul class="film-detail-alerts-list">
        ${alerts.map((a) => `
          <li class="film-detail-alert film-detail-alert--${escapeHtml(a.severity)}" data-alert-code="${escapeHtml(a.code)}">
            <div class="film-detail-alert-head">
              <span class="film-detail-alert-icon" aria-hidden="true">${escapeHtml(a.icon)}</span>
              <span class="film-detail-alert-label">${escapeHtml(a.label)}</span>
            </div>
            <div class="film-detail-alert-desc">${escapeHtml(a.description)}</div>
            ${a.action ? `
              <div class="film-detail-alert-action">
                <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
                        data-film-alert-action="${escapeHtml(a.action.kind)}"
                        data-film-alert-code="${escapeHtml(a.code)}">${escapeHtml(a.action.label)}</button>
              </div>` : ""}
          </li>
        `).join("")}
      </ul>
    </section>
  `;
}

/* ===========================================================
 * Candidats TMDb
 * =========================================================== */

function _renderCandidate(candidate, isChosen) {
  const tid = candidate.tmdb_id ? String(candidate.tmdb_id) : "";
  const tit = candidate.title || candidate.original_title || "—";
  const year = candidate.year || candidate.release_year || "";
  const genre = candidate.genre || (Array.isArray(candidate.genres) ? candidate.genres.join(", ") : "") || "";
  const conf = candidate.confidence != null
    ? Math.round(Number(candidate.confidence))
    : (candidate.score != null ? Math.round(Number(candidate.score) * 100) : null);
  const director = candidate.director || "";
  const overview = candidate.overview ? String(candidate.overview).slice(0, 120) : "";
  // Posters : on essaie w185 (taille spec), sinon le poster_url w92 de la facade.
  const rawPoster = candidate.poster_url || (candidate.poster_path ? `https://image.tmdb.org/t/p/w92${candidate.poster_path.startsWith("/") ? "" : "/"}${candidate.poster_path}` : null);
  const poster = _resizePosterUrl(rawPoster, "w185") || rawPoster;
  const posterHtml = poster
    ? `<img class="film-detail-candidate-poster" src="${escapeHtml(poster)}" alt="${escapeHtml(tit)}" loading="lazy" onerror="this.onerror=null;this.style.display='none'">`
    : `<div class="film-detail-candidate-poster film-detail-candidate-poster--placeholder" aria-hidden="true">🎬</div>`;

  const metaParts = [];
  if (genre) metaParts.push(escapeHtml(genre));
  if (director) metaParts.push(escapeHtml(director));
  const metaStr = metaParts.join(" · ");

  return `
    <article class="film-detail-candidate${isChosen ? " film-detail-candidate--chosen" : ""}" data-tmdb-id="${escapeHtml(tid)}">
      ${posterHtml}
      <div class="film-detail-candidate-info">
        <div class="film-detail-candidate-title">
          ${escapeHtml(tit)}${year ? ` <span class="film-detail-candidate-year">(${escapeHtml(String(year))})</span>` : ""}
        </div>
        ${metaStr ? `<div class="film-detail-candidate-meta">${metaStr}</div>` : ""}
        ${overview ? `<div class="film-detail-candidate-overview">${escapeHtml(overview)}${candidate.overview && candidate.overview.length > 120 ? "…" : ""}</div>` : ""}
      </div>
      <div class="film-detail-candidate-side">
        ${conf != null ? `<div class="film-detail-candidate-confidence">${conf}%</div>` : ""}
        ${isChosen
          ? `<span class="film-detail-candidate-chosen-badge">✓ Choisi</span>`
          : `<button type="button" class="v5-btn v5-btn--sm v5-btn--primary"
                     data-film-action="choose-candidate" data-tmdb-id="${escapeHtml(tid)}">Choisir</button>`}
      </div>
    </article>
  `;
}

function _renderCandidates(data) {
  const row = data.row || {};
  const candidates = Array.isArray(row.candidates) ? row.candidates : [];
  if (candidates.length === 0) return "";

  // Fix audit 2026-05-25 (v1.5.4) Vague I : garantir qu'UN SEUL candidat
  // est marque "Choisi" dans l'UI. Cause racine du bug "Avatar : De feu et
  // de cendres + Avatar 3 tous deux ✓ Choisi" : si deux candidates avaient
  // le meme tmdb_id ou si chosenId matchait plusieurs (cas degrade), tous
  // etaient highlightes. Priorite :
  //  1. cand.chosen === true (annotation backend canonique, Vague I)
  //  2. premier candidat dont tmdb_id matche row.chosen_tmdb_id / row.tmdb_id
  //  3. premier candidat (top score) en fallback
  // Une fois UN candidat marque, les suivants sont forces a NON choisis.
  const chosenId = row.chosen_tmdb_id || row.tmdb_id || (candidates[0] && candidates[0].tmdb_id);
  const backendMarkedIdx = candidates.findIndex((c) => c && c.chosen === true);
  let firstChosenIdx = backendMarkedIdx;
  if (firstChosenIdx < 0) {
    firstChosenIdx = candidates.findIndex((c) => c && String(c.tmdb_id) === String(chosenId));
  }
  if (firstChosenIdx < 0 && candidates.length > 0) {
    firstChosenIdx = 0; // fallback safe : premier candidat
  }

  const visibleCount = _state.showAllCandidates ? candidates.length : Math.min(3, candidates.length);
  const visible = candidates.slice(0, visibleCount);
  const more = candidates.length - visibleCount;

  return `
    <section class="film-detail-candidates">
      <h3 class="film-detail-section-title">🏷 Candidats TMDb (${candidates.length})</h3>
      <div class="film-detail-candidates-list">
        ${visible.map((c, idx) => _renderCandidate(c, idx === firstChosenIdx)).join("")}
      </div>
      ${more > 0
        ? `<button type="button" class="v5-btn v5-btn--ghost v5-btn--sm" data-film-action="expand-candidates">▾ Voir ${more} autre${more > 1 ? "s" : ""} candidat${more > 1 ? "s" : ""}</button>`
        : (_state.showAllCandidates && candidates.length > 3
          ? `<button type="button" class="v5-btn v5-btn--ghost v5-btn--sm" data-film-action="collapse-candidates">▴ Réduire</button>`
          : "")}
      <button type="button" class="v5-btn v5-btn--ghost v5-btn--sm" data-film-action="search-tmdb">🔍 Rechercher manuellement sur TMDb</button>
    </section>
  `;
}

/* ===========================================================
 * Onglets
 * =========================================================== */

const TABS = [
  { id: "overview", label: "Aperçu" },
  { id: "analysis", label: "Analyse V2" },
  { id: "history", label: "Historique" },
  { id: "rename", label: "Renommage proposé" },
];

function _renderTabsBar() {
  return `
    <div class="film-detail-tabs" role="tablist" aria-label="Onglets detail film">
      ${TABS.map((t) => `
        <button type="button"
                class="film-detail-tab${t.id === _state.activeTab ? " is-active" : ""}"
                data-film-tab="${escapeHtml(t.id)}"
                role="tab"
                aria-selected="${t.id === _state.activeTab ? "true" : "false"}">
          ${escapeHtml(t.label)}
        </button>
      `).join("")}
    </div>
    <div class="film-detail-tab-panel" data-film-tab-panel></div>
  `;
}

function _renderOverviewTab(data) {
  const probe = data.probe || {};
  // AUDIT 2026-06-14 (R7-2) : get_film_full renvoie le `metrics` brut -> les
  // caracteristiques techniques vivent SOUS probe.detected.* (plat), pas dans
  // probe.video/probe.audio/probe.subtitles. Avant, l'apercu affichait tout
  // vide ("Pistes audio: 0", Resolution/Codec/Bitrate absents). Le nombre de
  // sous-titres n'est pas dans metrics : on le lit sur la PlanRow (data.row).
  const det = probe.detected || {};
  const row = data.row || {};
  const resolution = det.resolution || (det.width && det.height ? `${det.width}×${det.height}` : "");
  const durMin = det.duration_s ? Math.round(Number(det.duration_s) / 60) : 0;
  const audioCount = Number(det.audio_tracks_count || 0);
  const subCount = Number(row.subtitle_count || 0);
  return `
    <div class="film-detail-overview">
      <dl class="film-detail-data-list">
        ${resolution ? `<dt>Résolution</dt><dd>${escapeHtml(resolution)}</dd>` : ""}
        ${det.video_codec ? `<dt>Codec</dt><dd>${escapeHtml(String(det.video_codec).toUpperCase())}</dd>` : ""}
        ${det.bitrate_kbps ? `<dt>Bitrate</dt><dd>${escapeHtml(String(det.bitrate_kbps))} kbps</dd>` : ""}
        ${durMin > 0 ? `<dt>Durée</dt><dd>${durMin} min</dd>` : ""}
        <dt>Pistes audio</dt><dd>${audioCount}</dd>
        <dt>Sous-titres</dt><dd>${subCount}</dd>
      </dl>
    </div>
  `;
}

function _renderAnalysisTab(data) {
  const perc = data.perceptual || {};
  const gv2 = perc.global_score_v2;
  if (!gv2) {
    return `
      <div class="film-detail-analysis-empty">
        <p>Aucune analyse perceptuelle pour ce film.</p>
        <button type="button" class="v5-btn v5-btn--primary v5-btn--sm" data-film-action="analyze-perceptual">
          ▶ Analyser perceptuel
        </button>
      </div>
    `;
  }
  const score = gv2.global_score != null ? Math.round(Number(gv2.global_score)) : null;
  const tier = String(gv2.global_tier || "unknown");
  return `
    <div class="film-detail-analysis">
      <p>Score V2 : <strong>${score != null ? score + "/100" : "—"}</strong> · Tier : <strong>${escapeHtml(tier)}</strong></p>
      <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-film-action="open-perceptual-modal">
        Voir l'analyse complète
      </button>
      ${_renderScoreFeedbackBlock(tier)}
    </div>
  `;
}

/* ===========================================================
 * Sprint orphelins #350 : Score feedback (thumbs up/down)
 * =========================================================== */

/**
 * Bloc de feedback utilisateur sur le scoring. Si `lastFeedback` est present
 * dans le state (apres soumission dans la session courante), affiche le tier
 * choisi + bouton "Annuler ce feedback". Sinon affiche les 5 boutons tier qui
 * declenchent submit_score_feedback.
 *
 * Design minimaliste (cf consigne issue #350) : pas de drawer, juste une rangee
 * de boutons sous le score, et un toast confirme la soumission. La calibration
 * report agregee est consultable en Parametres (deja existante).
 */
function _renderScoreFeedbackBlock(computedTier) {
  const fb = _state.lastFeedback;
  if (fb) {
    return `
      <div class="film-detail-feedback film-detail-feedback--submitted" role="region" aria-label="Feedback soumis">
        <p class="film-detail-feedback-status">
          ✓ Votre tier estimé : <strong>${escapeHtml(String(fb.user_tier || "—"))}</strong>
          ${fb.computed_tier ? `· Score auto : <em>${escapeHtml(String(fb.computed_tier))}</em>` : ""}
        </p>
        <button type="button"
                class="v5-btn v5-btn--ghost v5-btn--sm"
                data-film-action="delete-score-feedback">
          ↶ Annuler ce feedback
        </button>
      </div>
    `;
  }
  const tiers = [
    { v: "platinum", label: "Platinum", icon: "💎" },
    { v: "gold",     label: "Gold",     icon: "🥇" },
    { v: "silver",   label: "Silver",   icon: "🥈" },
    { v: "bronze",   label: "Bronze",   icon: "🥉" },
    { v: "reject",   label: "Reject",   icon: "✗" },
  ];
  const buttons = tiers.map((t) => {
    const isComputed = String(computedTier).toLowerCase() === t.v;
    return `<button type="button"
                     class="v5-btn v5-btn--ghost v5-btn--sm film-detail-feedback-btn${isComputed ? " is-computed" : ""}"
                     data-film-action="submit-score-feedback"
                     data-feedback-tier="${t.v}"
                     title="Selon vous, ce film mérite tier ${t.label}">
              ${t.icon} ${escapeHtml(t.label)}
            </button>`;
  }).join("");
  return `
    <div class="film-detail-feedback" role="region" aria-label="Feedback scoring">
      <p class="film-detail-feedback-prompt">
        Le score auto vous semble juste ? Indiquez votre estimation pour calibrer
        le scoring (votre feedback alimente le rapport de calibration).
      </p>
      <div class="film-detail-feedback-tiers" role="group" aria-label="Tier estime utilisateur">
        ${buttons}
      </div>
    </div>
  `;
}

function _renderHistoryTab(data) {
  const events = Array.isArray(data.history) ? data.history : [];
  if (events.length === 0) {
    return `<div class="film-detail-history-empty">Aucun historique pour ce film.</div>`;
  }
  return `
    <ul class="film-detail-history-list">
      ${events.slice(0, 30).map((ev) => {
        const date = ev.date || ev.ts || "";
        const type = String(ev.type || "event");
        const label = ev.label || ev.description || type;
        return `
          <li class="film-detail-history-event">
            <span class="film-detail-history-type">${escapeHtml(type)}</span>
            <span class="film-detail-history-label">${escapeHtml(label)}</span>
            <span class="film-detail-history-date">${escapeHtml(String(date))}</span>
          </li>
        `;
      }).join("")}
    </ul>
  `;
}

function _renderRenameTab(data) {
  const row = data.row || {};
  const current = row.source_path || row.source_folder || row.current_path || "";
  const proposed = row.proposed_path || row.proposed_folder || "";
  if (!proposed) {
    return `<div class="film-detail-rename-empty">Aucun renommage proposé pour ce film.</div>`;
  }
  if (current === proposed) {
    return `<div class="film-detail-rename-empty">Le chemin actuel correspond déjà au renommage proposé.</div>`;
  }
  const reason = row.rename_reason || (row.warning_flags && row.warning_flags.length > 0 ? "Normalisation selon le template configuré" : "Renommage standard");
  return `
    <div class="film-detail-rename-diff">
      <div class="film-detail-rename-row film-detail-rename-row--before">
        <span class="film-detail-rename-label">Avant</span>
        <code class="film-detail-rename-path">${escapeHtml(current || "—")}</code>
      </div>
      <div class="film-detail-rename-arrow" aria-hidden="true">→</div>
      <div class="film-detail-rename-row film-detail-rename-row--after">
        <span class="film-detail-rename-label">Après</span>
        <code class="film-detail-rename-path">${escapeHtml(proposed)}</code>
      </div>
      <div class="film-detail-rename-reason">
        <strong>Raison :</strong> ${escapeHtml(reason)}
      </div>
    </div>
  `;
}

function _renderTabPanel() {
  const panel = _state.containerEl && _state.containerEl.querySelector("[data-film-tab-panel]");
  if (!panel || !_state.data) return;
  switch (_state.activeTab) {
    case "overview": panel.innerHTML = _renderOverviewTab(_state.data); break;
    case "analysis": panel.innerHTML = _renderAnalysisTab(_state.data); break;
    case "history":  panel.innerHTML = _renderHistoryTab(_state.data); break;
    case "rename":   panel.innerHTML = _renderRenameTab(_state.data); break;
    default:         panel.innerHTML = "";
  }
  // Sprint orphelins #350 : _renderTabPanel remplace innerHTML donc les
  // listeners precedents (data-film-action dans le panel) sont perdus. On
  // re-bind uniquement le panel via une boucle ciblee pour ne pas double-bind
  // les actions globales (footer, alerts) deja attachees dans _bindEvents.
  panel.querySelectorAll("[data-film-action]").forEach((btn) => {
    if (btn.__filmActionBound) return;
    btn.__filmActionBound = true;
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      _handleAction(btn.dataset.filmAction, btn);
    });
  });
}

/* ===========================================================
 * Actions principales
 * =========================================================== */

function _renderActions(data) {
  const d = data || {};
  // AUDIT 2026-06-14 (R7-12) : actions d'annulation des corrections manuelles,
  // affichees seulement si l'etat le justifie (flags get_film_full).
  const overrideBtn = d.has_tmdb_override
    ? `<button type="button" class="v5-btn v5-btn--secondary" data-film-action="clear-override" title="Annuler le choix manuel et revenir au match TMDb automatique">↩ Revenir au match auto</button>`
    : "";
  const deleteBtn = d.is_marked_for_deletion
    ? `<button type="button" class="v5-btn v5-btn--secondary" data-film-action="unmark-delete">↩ Annuler le marquage suppression</button>`
    : `<button type="button" class="v5-btn v5-btn--danger" data-film-action="mark-delete">🗑 Marquer pour suppression</button>`;
  return `
    <footer class="film-detail-actions">
      <button type="button" class="v5-btn v5-btn--primary" data-film-action="validate">✓ Valider</button>
      <button type="button" class="v5-btn v5-btn--secondary" data-film-action="analyze-perceptual">▶ Analyser perceptuel</button>
      <button type="button" class="v5-btn v5-btn--secondary" data-film-action="open-folder">📂 Ouvrir dossier</button>
      <button type="button" class="v5-btn v5-btn--secondary" data-film-action="rescan">↻ Re-scanner</button>
      ${overrideBtn}
      ${deleteBtn}
    </footer>
  `;
}

/* ===========================================================
 * Render principal
 * =========================================================== */

function _renderAll() {
  if (!_state.containerEl || !_state.data) return;
  const data = _state.data;
  // Fix audit 2026-05-25 (v1.5.3) Vague H : role="dialog"+aria-modal sur l'article
  // (mode C overlay) pour annoncer la modale aux AT. Mode A/B = embed donc juste region.
  const isOverlay = _state.mode === "C";
  const dlgAttrs = isOverlay
    ? 'role="dialog" aria-modal="true" aria-labelledby="film-detail-title"'
    : 'role="region" aria-labelledby="film-detail-title"';
  _state.containerEl.innerHTML = `
    <article class="film-detail film-detail--mode-${escapeHtml(_state.mode || "B")}" ${dlgAttrs}>
      ${_renderHero(data)}
      ${_renderSynopsis(data)}
      ${_renderAlerts(data)}
      ${_renderCandidates(data)}
      ${_renderTabsBar()}
      ${_renderActions(data)}
    </article>
  `;
  _bindEvents();
  _renderTabPanel();
}

/* ===========================================================
 * Event handlers
 * =========================================================== */

function _bindEvents() {
  const root = _state.containerEl;
  if (!root) return;

  // Onglets
  root.querySelectorAll("[data-film-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.activeTab = btn.dataset.filmTab;
      // Re-render seulement la barre + panel
      root.querySelectorAll("[data-film-tab]").forEach((b) => {
        const isActive = b.dataset.filmTab === _state.activeTab;
        b.classList.toggle("is-active", isActive);
        b.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      _renderTabPanel();
    });
  });

  // Actions principales
  root.querySelectorAll("[data-film-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      _handleAction(btn.dataset.filmAction, btn);
    });
  });

  // Actions sur alertes
  root.querySelectorAll("[data-film-alert-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      _handleAlertAction(btn.dataset.filmAlertAction, btn.dataset.filmAlertCode);
    });
  });

  // Retry chargement
  const retry = root.querySelector("[data-film-retry]");
  if (retry) retry.addEventListener("click", () => _reload());
}

async function _handleAction(action, btn) {
  if (!_state.data) return;
  const row = _state.data.row || {};
  const runId = _state.runId || _state.data.run_id;
  const rowId = _state.rowId || _state.data.row_id;

  switch (action) {
    case "open-analysis":
      _state.activeTab = "analysis";
      _renderAll();
      break;

    case "expand-candidates":
      _state.showAllCandidates = true;
      _renderAll();
      break;

    case "collapse-candidates":
      _state.showAllCandidates = false;
      _renderAll();
      break;

    case "choose-candidate": {
      const tid = btn.dataset.tmdbId;
      if (!tid) return;
      await _chooseCandidate(tid, btn);
      break;
    }

    case "validate":
      await _validateFilm(btn, runId, rowId);
      break;

    case "analyze-perceptual":
    case "open-perceptual-modal":
      openPerceptualModal({ rowId, runId, rowTitle: row.proposed_title || row.nfo_title || "" });
      break;

    case "open-folder":
      await _openFolder(row);
      break;

    case "rescan":
      await _rescanRow(btn, runId, rowId);
      break;

    case "mark-delete":
      _markForDeletionWithConfirm(row, runId, rowId);
      break;

    case "unmark-delete":
      // R7-12 : annule le marquage pour suppression.
      try {
        const r = await apiPost("library/unmark_for_deletion", { run_id: runId, row_id: rowId });
        const d = (r && r.data) || r || {};
        if (d.ok === false) { showToast({ type: "error", text: d.message || "Annulation impossible." }); break; }
        showToast({ type: "success", text: "Marquage suppression annulé." });
        _reload();
      } catch (e) { showToast({ type: "error", text: String(e && e.message ? e.message : e) }); }
      break;

    case "clear-override":
      // R7-12 : revient au match TMDb automatique.
      try {
        const r = await apiPost("library/clear_tmdb_override", { run_id: runId, row_id: rowId });
        const d = (r && r.data) || r || {};
        if (d.ok === false) { showToast({ type: "error", text: d.message || "Annulation impossible." }); break; }
        showToast({ type: "success", text: "Choix manuel annulé (retour au match auto)." });
        _reload();
      } catch (e) { showToast({ type: "error", text: String(e && e.message ? e.message : e) }); }
      break;

    case "search-tmdb":
      _openTmdbManualSearchModal(rowId, runId);
      break;

    case "submit-score-feedback": {
      const userTier = btn && btn.dataset ? btn.dataset.feedbackTier : null;
      if (!userTier) return;
      await _submitScoreFeedback(userTier, runId, rowId, btn);
      break;
    }

    case "delete-score-feedback":
      await _deleteScoreFeedback(btn);
      break;

    case "refresh-poster": {
      // Fix audit 2026-05-24 (v1.5.2) : refresh poster TMDb unitaire.
      const tid = btn && btn.dataset ? btn.dataset.tmdbId : null;
      if (!tid) return;
      await _refreshPosterUnit(parseInt(tid, 10), btn);
      break;
    }

    default:
      console.warn("[film-detail] action inconnue :", action);
  }
}

/* ===========================================================
 * Score feedback handlers (sprint orphelins #350)
 * =========================================================== */

async function _submitScoreFeedback(userTier, runId, rowId, btn) {
  if (!runId || !rowId) {
    showToast({ type: "warn", text: "Run ou film introuvable pour ce feedback." });
    return;
  }
  // Petite modale optionnelle pour saisir un commentaire libre. Si l'utilisateur
  // valide vide ou annule la modale, on soumet quand meme (le commentaire est
  // optionnel cote backend).
  const proceed = (comment) => _doSubmitScoreFeedback(userTier, runId, rowId, comment, btn);
  showModal({
    title: `Tier estimé : ${userTier}`,
    body: `
      <p>Optionnel : pourquoi pensez-vous que ce film mérite tier <strong>${escapeHtml(userTier)}</strong> ?</p>
      <label class="film-detail-feedback-comment-field">
        <span>Commentaire (max 500 caractères)</span>
        <textarea data-film-feedback-comment rows="3" maxlength="500"
                  placeholder="Ex : encodage suspect, mauvaise piste audio..."></textarea>
      </label>
    `,
    actions: [
      { label: "Annuler", cls: "", onClick: () => {} },
      {
        label: "Envoyer le feedback",
        cls: "btn-primary",
        onClick: () => {
          const ta = document.querySelector("[data-film-feedback-comment]");
          const comment = ta && ta.value ? String(ta.value).trim() : "";
          try { closeModal(); } catch (_e) { /* noop */ }
          void proceed(comment || null);
        },
      },
    ],
  });
}

async function _doSubmitScoreFeedback(userTier, runId, rowId, comment, btn) {
  if (btn) { btn.disabled = true; }
  try {
    const params = { run_id: runId, row_id: rowId, user_tier: userTier };
    if (comment) params.comment = comment;
    const res = await apiPost("quality/submit_score_feedback", params);
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec envoi feedback.");
    }
    _state.lastFeedback = {
      id: data.feedback_id != null ? Number(data.feedback_id) : null,
      user_tier: String(data.user_tier || userTier),
      computed_tier: String(data.computed_tier || ""),
    };
    showToast({ type: "success", text: "Feedback enregistré. Merci !" });
    _renderTabPanel();
  } catch (e) {
    console.error("[film-detail] submit_score_feedback:", e);
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
    if (btn) { btn.disabled = false; }
  }
}

async function _deleteScoreFeedback(btn) {
  const fb = _state.lastFeedback;
  if (!fb || fb.id == null) {
    showToast({ type: "warn", text: "Aucun feedback à supprimer." });
    return;
  }
  if (btn) { btn.disabled = true; }
  try {
    const res = await apiPost("quality/delete_score_feedback", { feedback_id: fb.id });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec suppression feedback.");
    }
    _state.lastFeedback = null;
    showToast({ type: "success", text: "Feedback annulé." });
    _renderTabPanel();
  } catch (e) {
    console.error("[film-detail] delete_score_feedback:", e);
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
    if (btn) { btn.disabled = false; }
  }
}

// Fix audit 2026-05-24 (v1.5.2) : refresh poster TMDb unitaire. Appelle
// integrations/get_tmdb_posters avec force_refresh:true pour bypass le cache,
// puis met a jour <img src> in-place sans full reload de la fiche. Loading
// state via opacity sur l'img + spin sur le bouton.
async function _refreshPosterUnit(tmdbId, btn) {
  if (!tmdbId || Number.isNaN(tmdbId)) return;
  const root = _state.containerEl;
  const img = root ? root.querySelector("[data-film-poster-img]") : null;
  const originalLabel = btn ? btn.textContent : "🔄";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳";
    btn.setAttribute("aria-busy", "true");
  }
  if (img) img.style.opacity = "0.5";
  try {
    const res = await apiPost("integrations/get_tmdb_posters", {
      tmdb_ids: [tmdbId],
      size: "w185",
      force_refresh: true,
    });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec refresh poster.");
    }
    // AUDIT 2026-06-14 (R7-17) : get_tmdb_posters renvoie ok:true +
    // reason:"tmdb_not_configured" (pas ok:false) quand la cle manque. Sans ce
    // test, on tombait sur le throw generique "Reessayer ?" (incite a reessayer
    // en vain). Message precis + sortie propre.
    if (data.reason === "tmdb_not_configured") {
      if (img) img.style.opacity = "1";
      showToast({ type: "warn", text: "Clé TMDb non configurée (Paramètres ▸ TMDb)." });
      return;
    }
    // La facade peut retourner soit { posters: { "<id>": "<url>" } }, soit
    // { results: [ { tmdb_id, poster_url } ] }. On gere les 2 shapes.
    let newUrl = null;
    if (data.posters && typeof data.posters === "object") {
      newUrl = data.posters[String(tmdbId)] || data.posters[tmdbId] || null;
    }
    if (!newUrl && Array.isArray(data.results)) {
      const match = data.results.find((r) => Number(r && r.tmdb_id) === Number(tmdbId));
      if (match) newUrl = match.poster_url || match.url || null;
    }
    if (!newUrl) {
      throw new Error("Poster introuvable dans la réponse.");
    }
    // Cache-bust pour forcer le rechargement visuel meme si l'URL est identique.
    const bust = newUrl + (newUrl.includes("?") ? "&" : "?") + "_ts=" + Date.now();
    if (img) {
      img.src = bust;
      img.style.opacity = "1";
    }
    // Memorise pour les re-renders ulterieurs (changement d'onglet, etc.).
    if (_state.data) _state.data.poster_url = newUrl;
    showToast({ type: "success", text: "Poster rafraîchi depuis TMDb." });
  } catch (e) {
    console.error("[film-detail] refresh-poster:", e);
    if (img) img.style.opacity = "1";
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalLabel || "🔄";
      btn.removeAttribute("aria-busy");
    }
  }
}

async function _chooseCandidate(tmdbId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "..."; }
  try {
    const runId = _state.runId || (_state.data && _state.data.run_id);
    const rowId = _state.rowId || (_state.data && _state.data.row_id);
    const res = await apiPost("library/set_film_tmdb_candidate", {
      run_id: runId,
      row_id: rowId,
      tmdb_id: parseInt(tmdbId, 10),
    });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec changement candidat.");
    }
    showToast({ type: "success", text: "Candidat changé. Renommage mis à jour." });
    await _reload();
  } catch (e) {
    console.error("[film-detail] choose-candidate:", e);
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
    if (btn) { btn.disabled = false; btn.textContent = "Choisir"; }
  }
}

/* ===========================================================
 * Recherche manuelle TMDb (Spec 06 3.4)
 * =========================================================== */

const TMDB_SEARCH_OVERLAY_ID = "tmdbManualSearchOverlay";

function _closeTmdbManualSearchModal() {
  const overlay = document.getElementById(TMDB_SEARCH_OVERLAY_ID);
  if (!overlay) return;
  if (overlay._escHandler) {
    document.removeEventListener("keydown", overlay._escHandler);
  }
  const previous = overlay._previouslyFocused;
  overlay.remove();
  if (previous && typeof previous.focus === "function") {
    try { previous.focus(); } catch (e) { /* noop */ }
  }
}

function _renderTmdbSearchResults(results) {
  if (!Array.isArray(results) || results.length === 0) {
    return `<p class="tmdb-manual-search-empty">Aucun résultat. Essayez avec un titre différent ou ajoutez l'année.</p>`;
  }
  return `
    <ul class="tmdb-manual-search-results" role="list">
      ${results.map((r) => {
        const tid = parseInt(r.tmdb_id, 10);
        if (!tid) return "";
        const title = escapeHtml(r.title || "(sans titre)");
        const year = r.year ? escapeHtml(String(r.year)) : "—";
        const origTitle = r.original_title && r.original_title !== r.title
          ? `<span class="tmdb-manual-search-orig">(${escapeHtml(r.original_title)})</span>`
          : "";
        const overview = r.overview ? escapeHtml(String(r.overview)) : "";
        const overviewBlock = overview
          ? `<p class="tmdb-manual-search-overview">${overview}</p>`
          : "";
        const vote = (r.vote_average && Number(r.vote_average) > 0)
          ? `<span class="tmdb-manual-search-vote">★ ${Number(r.vote_average).toFixed(1)}</span>`
          : "";
        const posterUrl = r.poster_url ? escapeHtml(String(r.poster_url)) : "";
        const posterBlock = posterUrl
          ? `<img class="tmdb-manual-search-poster" src="${posterUrl}" alt="Affiche ${title}" loading="lazy" width="92" height="138" onerror="this.onerror=null;this.style.display='none'">`
          : `<div class="tmdb-manual-search-poster tmdb-manual-search-poster--empty" aria-hidden="true">🎞</div>`;
        return `
          <li class="tmdb-manual-search-item" data-tmdb-id="${tid}">
            ${posterBlock}
            <div class="tmdb-manual-search-meta">
              <div class="tmdb-manual-search-title">${title} <span class="tmdb-manual-search-year">(${year})</span> ${vote}</div>
              ${origTitle}
              ${overviewBlock}
            </div>
            <button type="button" class="v5-btn v5-btn--primary v5-btn--sm" data-tmdb-pick="${tid}">Choisir</button>
          </li>
        `;
      }).join("")}
    </ul>
  `;
}

async function _runTmdbManualSearch(overlay) {
  const input = overlay.querySelector("[data-tmdb-search-query]");
  const yearInput = overlay.querySelector("[data-tmdb-search-year]");
  const submitBtn = overlay.querySelector("[data-tmdb-search-submit]");
  const resultsBox = overlay.querySelector("[data-tmdb-search-results]");
  if (!input || !resultsBox) return;
  const query = String(input.value || "").trim();
  if (query.length < 2) {
    resultsBox.innerHTML = `<p class="tmdb-manual-search-empty">Tapez au moins 2 caractères.</p>`;
    return;
  }
  let year = null;
  if (yearInput && yearInput.value) {
    const y = parseInt(yearInput.value, 10);
    if (!Number.isNaN(y) && y > 1870 && y < 2100) year = y;
  }
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Recherche..."; }
  resultsBox.innerHTML = `<p class="tmdb-manual-search-loading">Recherche en cours...</p>`;
  try {
    const res = await apiPost("library/search_tmdb", { query, year });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec recherche TMDb.");
    }
    resultsBox.innerHTML = _renderTmdbSearchResults(data.results || []);
  } catch (e) {
    console.error("[film-detail] search_tmdb:", e);
    resultsBox.innerHTML = `<p class="tmdb-manual-search-error">Erreur : ${escapeHtml(e.message || String(e))}</p>`;
  } finally {
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "🔍 Rechercher"; }
  }
}

async function _pickTmdbManualResult(tmdbId, btn) {
  if (!tmdbId) return;
  if (btn) { btn.disabled = true; btn.textContent = "..."; }
  try {
    await _chooseCandidate(tmdbId, null);
    _closeTmdbManualSearchModal();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "Choisir"; }
  }
}

function _openTmdbManualSearchModal(_rowId, _runId) {
  _closeTmdbManualSearchModal();
  const row = (_state.data && _state.data.row) || {};
  const defaultQuery = row.proposed_title || row.nfo_title || row.source_folder || "";
  const defaultYear = row.proposed_year || row.nfo_year || "";

  const overlay = document.createElement("div");
  overlay.id = TMDB_SEARCH_OVERLAY_ID;
  overlay.className = "modal-overlay tmdb-manual-search-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Recherche manuelle TMDb");
  overlay.innerHTML = `
    <div class="modal-card card tmdb-manual-search-card">
      <div class="modal-header">
        <h3>🔍 Recherche manuelle TMDb</h3>
        <button type="button" class="modal-close-btn" data-tmdb-search-close aria-label="Fermer">&times;</button>
      </div>
      <div class="modal-body tmdb-manual-search-body">
        <form data-tmdb-search-form class="tmdb-manual-search-form">
          <label class="tmdb-manual-search-field">
            <span>Titre du film</span>
            <input type="text" data-tmdb-search-query value="${escapeHtml(String(defaultQuery))}" placeholder="Ex : Inception" autocomplete="off">
          </label>
          <label class="tmdb-manual-search-field tmdb-manual-search-field--year">
            <span>Année (optionnel)</span>
            <input type="number" data-tmdb-search-year min="1870" max="2100" value="${escapeHtml(String(defaultYear || ""))}" placeholder="2010">
          </label>
          <button type="submit" class="v5-btn v5-btn--primary v5-btn--sm" data-tmdb-search-submit>🔍 Rechercher</button>
        </form>
        <div class="tmdb-manual-search-results-box" data-tmdb-search-results>
          <p class="tmdb-manual-search-hint">Tapez un titre puis cliquez sur Rechercher.</p>
        </div>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn" data-tmdb-search-close>Fermer</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay._previouslyFocused = document.activeElement;

  overlay._escHandler = (ev) => {
    if (ev.key === "Escape") {
      ev.stopPropagation();
      _closeTmdbManualSearchModal();
    }
  };
  document.addEventListener("keydown", overlay._escHandler);
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) _closeTmdbManualSearchModal();
  });
  overlay.querySelectorAll("[data-tmdb-search-close]").forEach((b) => {
    b.addEventListener("click", _closeTmdbManualSearchModal);
  });

  const form = overlay.querySelector("[data-tmdb-search-form]");
  if (form) {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      _runTmdbManualSearch(overlay);
    });
  }

  const resultsBox = overlay.querySelector("[data-tmdb-search-results]");
  if (resultsBox) {
    resultsBox.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-tmdb-pick]");
      if (!btn) return;
      ev.preventDefault();
      const tid = parseInt(btn.dataset.tmdbPick, 10);
      _pickTmdbManualResult(tid, btn);
    });
  }

  const queryInput = overlay.querySelector("[data-tmdb-search-query]");
  if (queryInput) {
    try { queryInput.focus(); queryInput.select(); } catch (e) { /* noop */ }
    if (String(queryInput.value || "").trim().length >= 2) {
      _runTmdbManualSearch(overlay);
    }
  }
}

async function _validateFilm(btn, runId, rowId) {
  if (btn) { btn.disabled = true; btn.textContent = "Validation..."; }
  try {
    const decisions = { [rowId]: { ok: true } };
    const res = await apiPost("run/save_validation", { run_id: runId, decisions });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec validation.");
    }
    showToast({ type: "success", text: "Film validé pour le prochain apply." });
  } catch (e) {
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "✓ Valider"; }
  }
}

async function _openFolder(row) {
  // Compat ascendante : PlanRow expose `folder` (champ canonique).
  const path = row.source_path || row.source_folder || row.current_path || row.folder || "";
  if (!path) {
    showToast({ type: "warn", text: "Aucun chemin de dossier disponible." });
    return;
  }
  try {
    const res = await apiPost("open_path", { path });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Ouverture refusée.");
    }
    showToast({ type: "success", text: "Dossier ouvert dans l'explorateur." });
  } catch (e) {
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
  }
}

async function _rescanRow(btn, runId, rowId) {
  if (btn) {
    btn.disabled = true;
    btn.dataset.originalText = btn.textContent;
    btn.textContent = "↻ Analyse en cours...";
  }
  try {
    const res = await apiPost("run/rescan_row", { run_id: runId, row_id: rowId });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec rescan.");
    }
    showToast({ type: "success", text: "Re-scan terminé. Mise à jour de la fiche..." });
    await _reload();
  } catch (e) {
    showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.dataset.originalText || "↻ Re-scanner";
    }
  }
}

function _markForDeletionWithConfirm(row, runId, rowId) {
  const title = row.proposed_title || row.nfo_title || row.source_folder || "Ce film";
  const year = row.proposed_year || "";
  const path = row.source_path || row.source_folder || "";
  dangerConfirmModal({
    title: "Confirmer le marquage suppression ?",
    items: [`${title}${year ? ` (${year})` : ""}`, path].filter(Boolean),
    consequence: "Le dossier sera déplacé vers _user_marked_for_deletion/ au prochain apply. Réversible via Undo.",
    countdownSeconds: 0,
    confirmLabel: "✗ Confirmer le marquage",
    onConfirm: async () => {
      try {
        const res = await apiPost("library/mark_for_deletion", { run_id: runId, row_id: rowId });
        const data = res && res.data ? res.data : res;
        if (!data || data.ok === false) {
          throw new Error((data && (data.message || data.error)) || "Echec marquage.");
        }
        showToast({ type: "success", text: "Film marqué pour suppression." });
      } catch (e) {
        showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
      }
    },
  });
}

async function _handleAlertAction(kind, code) {
  const row = (_state.data && _state.data.row) || {};
  const rowId = _state.rowId || (_state.data && _state.data.row_id);
  switch (kind) {
    case "ignore": {
      try {
        const res = await apiPost("library/mark_alert_ignored", { row_id: rowId, alert_code: code });
        const data = res && res.data ? res.data : res;
        if (!data || data.ok === false) {
          throw new Error((data && (data.message || data.error)) || "Echec ignore.");
        }
        const wasAlready = !!data.already_ignored;
        showToast({
          type: "success",
          text: wasAlready ? "Alerte déjà ignorée." : "Alerte ignorée.",
        });
        // Persistance cote front : memorise l'alerte ignoree pour que les
        // prochains _renderAlerts() ne la ré-affichent plus (et que le filtre
        // backend via film_modal.list_ignored_alerts soit doublement protege).
        if (_state.data && _state.data.row) {
          const ignored = Array.isArray(_state.data.row._ignored_alerts)
            ? _state.data.row._ignored_alerts.slice()
            : [];
          if (!ignored.includes(code)) ignored.push(code);
          _state.data.row._ignored_alerts = ignored;
          if (Array.isArray(_state.data.row.warning_flags)) {
            _state.data.row.warning_flags = _state.data.row.warning_flags.filter((f) => f !== code);
          }
        }
        // Retire l'alerte du DOM avec une transition fade-out + update du count.
        const li = _state.containerEl && _state.containerEl.querySelector(`[data-alert-code="${code}"]`);
        if (li) {
          li.style.transition = "opacity 220ms ease, max-height 220ms ease, margin 220ms ease, padding 220ms ease";
          li.style.opacity = "0";
          li.style.maxHeight = "0";
          li.style.marginTop = "0";
          li.style.marginBottom = "0";
          li.style.paddingTop = "0";
          li.style.paddingBottom = "0";
          li.style.overflow = "hidden";
          setTimeout(() => {
            const parent = li.parentNode;
            li.remove();
            if (parent) {
              const remaining = parent.querySelectorAll("[data-alert-code]").length;
              const section = parent.parentElement;
              const titleEl = section && section.querySelector(".film-detail-section-title");
              if (remaining === 0 && section) {
                section.remove();
              } else if (titleEl) {
                // CodeQL js/xss-through-dom : icon vient du DOM (textContent),
                // donc on utilise textContent au lieu d'innerHTML pour eviter
                // toute reinterpretation HTML d'un caractere accidentel.
                const icon = titleEl.textContent.trim().split(" ")[0] || "ℹ️";
                titleEl.textContent = `${icon} ${remaining} alerte${remaining > 1 ? "s" : ""}`;
              }
            }
          }, 240);
        }
      } catch (e) {
        showToast({ type: "error", text: "L'action n'a pas pu être effectuée. Réessayer ?" });
      }
      break;
    }
    case "rescan": {
      const runId = _state.runId || (_state.data && _state.data.run_id);
      await _rescanRow(null, runId, rowId);
      break;
    }
    case "config_subs":
      window.location.hash = "#/parametres";
      break;
    case "open_duplicates":
      window.location.hash = "#/doublons";
      break;
    case "open_film":
      // Deja sur le film -> no-op
      break;
    default:
      console.warn("[film-detail] alert action inconnue :", kind, code);
  }
  void row;  // unused for now
}

/* ===========================================================
 * Mount / Modes
 * =========================================================== */

function _renderInto(html) {
  if (_state.containerEl) {
    _state.containerEl.innerHTML = html;
    const retry = _state.containerEl.querySelector("[data-film-retry]");
    if (retry) retry.addEventListener("click", () => _reload());
  }
}

async function _reload() {
  if (!_state.rowId) return;
  _state.loading = true;
  _renderInto(_renderSkeleton());
  try {
    _state.data = await _loadFilmFull(_state.rowId, _state.runId);
    _state.loading = false;
    _renderAll();
  } catch (e) {
    _state.loading = false;
    _state.data = null;
    _renderInto(_renderErrorState(e && (e.message || String(e))));
  }
}

function _ensureModeAContainer() {
  rightPanel.setWidth(600);
  rightPanel.setExpanded(true);
  // On utilise setSections pour creer une seule section avec notre HTML.
  // _state.containerEl pointe vers le body de la section apres setSections.
  rightPanel.setSections([{ title: "Détail film", html: '<div data-film-detail-mount></div>' }]);
  // Recuperer le node injecte.
  const mount = document.querySelector("[data-film-detail-mount]");
  return mount;
}

function _ensureModeCOverlay() {
  // Ferme overlay precedent s'il existe
  const existing = document.getElementById(OVERLAY_ID);
  if (existing) existing.remove();
  const overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  overlay.className = "film-detail-modal-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Détail film");
  overlay.innerHTML = `
    <div class="film-detail-modal" role="document">
      <button type="button" class="film-detail-modal-close" data-film-modal-close aria-label="Fermer">✕</button>
      <div class="film-detail-modal-body" data-film-detail-mount></div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay._previouslyFocused = document.activeElement;

  // Esc + clic backdrop ferment
  // Fix audit 2026-05-25 (v1.5.3) Vague H : focus trap Tab/Shift+Tab pour conformite WCAG 2.4.3
  // Le keydown handler gere Escape (deja existant) ET le piegeage du focus dans la modale.
  const _focusableSel = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
  overlay._escHandler = (ev) => {
    if (ev.key === "Escape") {
      ev.stopPropagation();
      closeFilmDetail();
      return;
    }
    if (ev.key === "Tab") {
      const focusables = Array.from(overlay.querySelectorAll(_focusableSel))
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (ev.shiftKey && active === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && active === last) {
        ev.preventDefault();
        first.focus();
      }
    }
  };
  document.addEventListener("keydown", overlay._escHandler);
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) closeFilmDetail();
  });
  const closeBtn = overlay.querySelector("[data-film-modal-close]");
  if (closeBtn) closeBtn.addEventListener("click", closeFilmDetail);

  _state.overlayEl = overlay;
  return overlay.querySelector("[data-film-detail-mount]");
}

/**
 * Point d'entree unique du composant.
 *
 * @param {object} opts
 * @param {"A"|"B"|"C"} opts.mode - mode d'affichage
 * @param {string} opts.rowId - id du row
 * @param {string} [opts.runId] - id du run (optionnel pour mode B legacy)
 * @param {HTMLElement} [opts.container] - DOM cible (mode B uniquement)
 * @param {Function} [opts.onClose] - callback de fermeture (mode C)
 */
export async function renderFilmDetail(opts) {
  const { mode, rowId, runId, container, onClose } = opts || {};
  if (!mode || !rowId) {
    console.warn("[film-detail] mode + rowId requis", opts);
    return;
  }
  _state.mode = mode;
  _state.rowId = String(rowId);
  _state.runId = runId || null;
  _state.activeTab = "overview";
  _state.showAllCandidates = false;
  _state.onClose = onClose || null;
  // Reset feedback session par film charge (sprint orphelins #350).
  _state.lastFeedback = null;

  if (mode === "A") {
    _state.containerEl = _ensureModeAContainer();
  } else if (mode === "C") {
    _state.containerEl = _ensureModeCOverlay();
  } else if (mode === "B") {
    _state.containerEl = container || null;
  }

  if (!_state.containerEl) {
    console.warn("[film-detail] container manquant pour mode", mode);
    return;
  }

  await _reload();
}

/** Ferme le mode C overlay (no-op pour A et B). */
export function closeFilmDetail() {
  if (_state.overlayEl) {
    if (_state.overlayEl._escHandler) {
      document.removeEventListener("keydown", _state.overlayEl._escHandler);
    }
    const prev = _state.overlayEl._previouslyFocused;
    _state.overlayEl.remove();
    _state.overlayEl = null;
    if (prev && typeof prev.focus === "function") {
      try { prev.focus(); } catch (_e) { /* noop */ }
    }
  }
  if (typeof _state.onClose === "function") {
    try { _state.onClose(); } catch (_e) { /* noop */ }
  }
  _state.mode = null;
  _state.containerEl = null;
  _state.data = null;
  _state.rowId = null;
  _state.runId = null;
}

/* Expose pour tests structuraux. */
export const __testing = { _state, TABS };
