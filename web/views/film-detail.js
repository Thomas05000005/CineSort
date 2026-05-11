/* views/film-detail.js — v7.6.0 Vague 4 (ES module — porte V5bis-06)
 *
 * Page film standalone (route /film/:row_id).
 *
 * Structure :
 *   - Hero band : poster flou backdrop + poster + metadata + cercle V2 + actions
 *   - 4 onglets : Apercu | Analyse V2 | Historique | Comparaison
 *   - Drawer mobile (V3-06, export only — sera cable par V5C)
 *
 * API publique (ES module) :
 *   await initFilmDetail(container, opts)
 *     opts.filmId : id du film (sinon extrait du hash "#/film/<id>")
 *   mountFilmDetailDrawer(parent, opts) — drawer mode mobile
 *
 * Migration V5bis-06 :
 *   - IIFE -> ES module (exports nommes)
 *   - bridge legacy -> apiPost REST (kwargs)
 *   - V2-04 Promise.allSettled : get_film_full + get_film_history en parallele
 *   - V2-08 skeleton state preserve (custom hero + tabs)
 *   - V3-06 drawer mobile preserve en export
 */
import { apiPost, escapeHtml, renderError } from "./_v5_helpers.js";

const _state = {
  rowId: null,
  data: null,
  activeTab: "overview",
  containerRef: null,
};

function _svg(pathContent, size) {
  const s = size || 16;
  return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
}

const ICON_BACK = '<polyline points="15 18 9 12 15 6"/>';
const ICON_COMPARE = '<rect x="3" y="3" width="7" height="18"/><rect x="14" y="3" width="7" height="18"/>';
const ICON_REFRESH = '<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>';

/* ===========================================================
 * Loaders
 * =========================================================== */

/** V2-04 : fetch consolide film + history en parallele.
 * Si get_film_history echoue, on conserve data.history (deja fourni par get_film_full).
 */
async function _loadFilmFull(filmId) {
  const results = await Promise.allSettled([
    apiPost("get_film_full", { row_id: filmId }),
    apiPost("get_film_history", { film_id: filmId }),
  ]);
  const fullRes = results[0];
  const histRes = results[1];

  if (fullRes.status !== "fulfilled" || !fullRes.value.ok) {
    const reason = fullRes.status === "fulfilled"
      ? (fullRes.value.error || fullRes.value.data?.message || "Film introuvable")
      : String(fullRes.reason);
    throw new Error(reason);
  }

  const data = fullRes.value.data || {};
  if (histRes.status === "fulfilled" && histRes.value.ok && histRes.value.data) {
    const hd = histRes.value.data;
    if (Array.isArray(hd.events)) data.history = hd.events;
    else if (Array.isArray(hd)) data.history = hd;
  }
  return data;
}

function _extractFilmIdFromHash() {
  if (typeof window === "undefined" || !window.location) return null;
  const m = window.location.hash.match(/^#\/film\/([^/?]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/* ===========================================================
 * Formatters
 * =========================================================== */

function _formatDuration(sec) {
  const s = Number(sec) || 0;
  if (s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h${String(m).padStart(2, "0")}` : `${m} min`;
}

function _formatBytes(bytes) {
  // V6-04 : delegue a window.formatBytes (locale-aware) si dispo.
  if (typeof window.formatBytes === "function") {
    const b = Number(bytes) || 0;
    if (b <= 0) return "—";
    return window.formatBytes(b, 2);
  }
  const b = Number(bytes) || 0;
  if (b <= 0) return "—";
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} Ko`;
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} Go`;
}

/* ===========================================================
 * Skeleton (V2-08)
 * =========================================================== */

function _renderFilmDetailSkeleton(container) {
  container.innerHTML = `
    <div class="v5-film-detail-skeleton" aria-busy="true" aria-live="polite">
      <div class="v5-skeleton-hero"></div>
      <div class="v5-skeleton-tabs"></div>
      <div class="v5-skeleton-content">
        ${"<div class='v5-skeleton-row'></div>".repeat(6)}
      </div>
    </div>
  `;
}

/* ===========================================================
 * HERO BAND
 * =========================================================== */

function _buildHero(data) {
  const row = data.row || {};
  const perc = data.perceptual || {};
  const gv2 = perc.global_score_v2 || {};
  const title = row.proposed_title || row.nfo_title || row.source_folder || "Film sans titre";
  const origTitle = row.nfo_original_title || "";
  const year = row.proposed_year || "";
  const candidates = row.candidates || [];
  const director = candidates[0]?.director || "";
  const probe = data.probe || {};
  const video = probe.video || {};
  const duration = _formatDuration(probe.duration_s);

  const tier = String(gv2.global_tier || "unknown").toLowerCase();
  const score = gv2.global_score != null ? Math.round(Number(gv2.global_score)) : null;

  const scoreCircleHtml = (typeof window !== "undefined" && window.ScoreV2 && window.ScoreV2.scoreCircleHtml && score != null)
    ? window.ScoreV2.scoreCircleHtml({ score, tier })
    : (score != null ? `<div class="v5-film-score-fallback tier-${escapeHtml(tier)}">${score}/100</div>` : "");

  const backdropStyle = data.poster_url
    ? `background-image: url('${escapeHtml(data.poster_url)}')`
    : "";
  const posterHtml = data.poster_url
    ? `<img class="v5-film-poster" src="${escapeHtml(data.poster_url)}" alt="${escapeHtml(title)}" loading="eager"/>`
    : `<div class="v5-film-poster v5-film-poster--placeholder">${_svg('<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/>', 40)}</div>`;

  const resolution = video.width && video.height
    ? `${video.width}×${video.height}`
    : (row.resolution || "—");
  const codec = String(video.codec || "—").toUpperCase();

  return `
    <header class="v5-film-hero">
      <div class="v5-film-hero-backdrop" style="${backdropStyle}"></div>
      <div class="v5-film-hero-inner">
        <button type="button" class="v5-film-back" data-v5-film-back aria-label="Retour bibliotheque">
          ${_svg(ICON_BACK, 18)}
          <span>Bibliothèque</span>
        </button>
        <div class="v5-film-hero-body">
          ${posterHtml}
          <div class="v5-film-hero-content">
            <h1 class="v5-film-title">
              ${escapeHtml(title)}
              ${year ? `<span class="v5-film-year">(${escapeHtml(year)})</span>` : ""}
            </h1>
            ${origTitle && origTitle !== title
              ? `<div class="v5-film-subtitle v5u-text-muted">${escapeHtml(origTitle)}</div>` : ""}
            <div class="v5-film-meta-row">
              ${director ? `<span class="v5-film-meta-item">${escapeHtml(director)}</span>` : ""}
              <span class="v5-film-meta-item">${escapeHtml(duration)}</span>
              <span class="v5-film-meta-item">${escapeHtml(resolution)}</span>
              <span class="v5-film-meta-item">${escapeHtml(codec)}</span>
            </div>
            <div class="v5-film-hero-actions">
              <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-v5-film-rescan>
                ${_svg(ICON_REFRESH, 14)}
                Re-analyser
              </button>
              <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-v5-film-compare>
                ${_svg(ICON_COMPARE, 14)}
                Comparer
              </button>
            </div>
          </div>
          <div class="v5-film-hero-score">
            ${scoreCircleHtml}
          </div>
        </div>
      </div>
    </header>
  `;
}

/* ===========================================================
 * TABS
 * =========================================================== */

export const TABS = [
  { id: "overview",   label: "Aperçu" },
  { id: "analysis",   label: "Analyse V2" },
  { id: "history",    label: "Historique" },
  { id: "comparison", label: "Comparaison" },
];

function _buildTabs(activeTab) {
  return `
    <div class="v5-film-tabs" role="tablist" aria-label="Onglets film">
      ${TABS.map((t) => `
        <button type="button" class="v5-film-tab ${t.id === activeTab ? 'is-active' : ''}"
                data-v5-film-tab="${escapeHtml(t.id)}"
                role="tab" aria-selected="${t.id === activeTab ? 'true' : 'false'}"
                tabindex="${t.id === activeTab ? '0' : '-1'}">
          ${escapeHtml(t.label)}
        </button>
      `).join("")}
    </div>
    <div class="v5-film-tab-panel" data-v5-film-tab-panel></div>
  `;
}

function _renderTabPanel() {
  const root = _state.containerRef;
  if (!root) return;
  const panel = root.querySelector("[data-v5-film-tab-panel]");
  if (!panel) return;
  const data = _state.data;
  if (!data) { panel.innerHTML = ""; return; }

  switch (_state.activeTab) {
    case "overview":   panel.innerHTML = _renderOverviewTab(data); break;
    case "analysis":   _renderAnalysisTab(panel, data); break;
    case "history":    panel.innerHTML = _renderHistoryTab(data); break;
    case "comparison": panel.innerHTML = _renderComparisonTab(data); break;
    default:           panel.innerHTML = "";
  }
}

/* --- Overview tab --- */

function _renderOverviewTab(data) {
  const row = data.row || {};
  const probe = data.probe || {};
  const video = probe.video || {};
  const audioTracks = Array.isArray(probe.audio) ? probe.audio : [];
  const subtitles = Array.isArray(probe.subtitles) ? probe.subtitles : [];
  const candidates = row.candidates || [];
  const topCandidate = candidates[0] || {};

  const perc = data.perceptual || {};
  const gv2 = perc.global_score_v2 || {};
  const warnings = (gv2.warnings || []).slice(0, 3);

  return `
    <div class="v5-film-overview">
      <section class="v5-film-section">
        <h2 class="v5-film-section-title">Source</h2>
        <dl class="v5-film-data-list">
          <dt>Chemin</dt><dd class="v5u-text-muted v5-film-path">${escapeHtml(row.source_path || "—")}</dd>
          <dt>Taille</dt><dd>${escapeHtml(_formatBytes(row.size_bytes))}</dd>
          <dt>Conteneur</dt><dd>${escapeHtml(probe.container_format || "—")}</dd>
          ${row.edition ? `<dt>Edition</dt><dd>${escapeHtml(row.edition)}</dd>` : ""}
          ${row.tmdb_collection_name
            ? `<dt>Collection</dt><dd>${escapeHtml(row.tmdb_collection_name)}</dd>` : ""}
        </dl>
      </section>

      <section class="v5-film-section">
        <h2 class="v5-film-section-title">Video</h2>
        <dl class="v5-film-data-list">
          <dt>Codec</dt><dd>${escapeHtml(String(video.codec || "—").toUpperCase())}</dd>
          <dt>Resolution</dt><dd>${escapeHtml(video.width || "—")}×${escapeHtml(video.height || "—")}</dd>
          <dt>HDR</dt><dd>${_hdrLabel(video)}</dd>
          <dt>Bitrate</dt><dd>${video.bitrate_kbps ? `${video.bitrate_kbps} kbps` : "—"}</dd>
          <dt>Framerate</dt><dd>${video.fps ? `${Number(video.fps).toFixed(2)} fps` : "—"}</dd>
          <dt>Bit depth</dt><dd>${video.bit_depth || "—"} bits</dd>
        </dl>
      </section>

      <section class="v5-film-section">
        <h2 class="v5-film-section-title">Audio (${audioTracks.length})</h2>
        ${audioTracks.length > 0 ? `
          <ul class="v5-film-audio-list">
            ${audioTracks.slice(0, 5).map((a) => `
              <li>
                <span class="v5-film-audio-codec">${escapeHtml(String(a.codec || "?").toUpperCase())}</span>
                <span class="v5-film-audio-meta">${escapeHtml(a.channels || "?")} ch · ${escapeHtml(a.language || "?")}</span>
                ${a.title ? `<span class="v5u-text-muted">${escapeHtml(a.title)}</span>` : ""}
              </li>
            `).join("")}
          </ul>
        ` : `<div class="v5u-text-muted">Aucune piste audio.</div>`}
      </section>

      <section class="v5-film-section">
        <h2 class="v5-film-section-title">Sous-titres (${subtitles.length})</h2>
        ${subtitles.length > 0 ? `
          <ul class="v5-film-sub-list">
            ${subtitles.slice(0, 8).map((s) => `
              <li>${escapeHtml(String(s.language || "?"))} · ${escapeHtml(s.format || "srt")}${s.external ? " (externe)" : ""}</li>
            `).join("")}
          </ul>
        ` : `<div class="v5u-text-muted">Aucun sous-titre.</div>`}
      </section>

      ${topCandidate.tmdb_id ? `
        <section class="v5-film-section">
          <h2 class="v5-film-section-title">TMDb</h2>
          <dl class="v5-film-data-list">
            <dt>ID</dt><dd>${escapeHtml(topCandidate.tmdb_id)}</dd>
            <dt>Confiance</dt><dd>${escapeHtml(topCandidate.confidence_label || "?")}</dd>
            ${topCandidate.overview ? `<dt>Synopsis</dt><dd class="v5-film-synopsis">${escapeHtml(topCandidate.overview)}</dd>` : ""}
          </dl>
        </section>
      ` : ""}

      ${warnings.length > 0 ? `
        <section class="v5-film-section">
          <h2 class="v5-film-section-title">Warnings top</h2>
          <ul class="v5-film-warnings-list">
            ${warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}
          </ul>
        </section>
      ` : ""}
    </div>
  `;
}

function _hdrLabel(video) {
  if (!video) return "—";
  if (video.has_hdr10_plus) return "HDR10+";
  if (video.has_dv) {
    const prof = video.dv_profile ? ` Profile ${escapeHtml(video.dv_profile)}` : "";
    return "Dolby Vision" + prof;
  }
  if (video.has_hdr10) return "HDR10";
  return "SDR";
}

/* --- Analysis V2 tab --- */

function _renderAnalysisTab(panel, data) {
  const perc = data.perceptual || {};
  const gv2 = perc.global_score_v2;
  if (!gv2 || typeof gv2 !== "object") {
    panel.innerHTML = `
      <div class="v5-film-analysis-empty">
        <p>Ce film n'a pas encore d'analyse V2.</p>
        <button type="button" class="v5-btn v5-btn--primary v5-btn--sm" data-v5-film-rescan>
          Lancer l'analyse perceptuelle
        </button>
      </div>
    `;
    return;
  }

  if (typeof window !== "undefined" && typeof window.renderScoreV2Container === "function") {
    panel.innerHTML = window.renderScoreV2Container(gv2);
    if (typeof window.bindScoreV2Events === "function") {
      window.bindScoreV2Events(panel);
    }
  } else {
    panel.innerHTML = `<div class="v5u-text-muted">Composant score-v2 indisponible.</div>`;
  }
}

/* --- History tab --- */

function _renderHistoryTab(data) {
  const events = data.history || [];
  if (!events.length) {
    return `<div class="v5u-text-muted v5u-p-4">Aucun historique pour ce film.</div>`;
  }
  return `
    <div class="v5-film-timeline">
      ${events.slice(0, 50).map((ev) => {
        const date = ev.date || ev.ts || "";
        const type = String(ev.type || "event");
        const label = ev.label || ev.description || type;
        const delta = ev.score_delta;
        const deltaHtml = (delta != null && Number(delta) !== 0)
          ? `<span class="v5-film-timeline-delta ${delta > 0 ? 'is-up' : 'is-down'}">${delta > 0 ? '+' : ''}${Number(delta).toFixed(1)}</span>`
          : "";
        return `
          <div class="v5-film-timeline-event">
            <div class="v5-film-timeline-dot v5-film-timeline-dot--${escapeHtml(type)}"></div>
            <div class="v5-film-timeline-content">
              <div class="v5-film-timeline-header">
                <span class="v5-film-timeline-type">${escapeHtml(type)}</span>
                <span class="v5-film-timeline-date v5u-text-muted">${escapeHtml(date)}</span>
                ${deltaHtml}
              </div>
              <div class="v5-film-timeline-label">${escapeHtml(label)}</div>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

/* --- Comparison tab --- */

function _renderComparisonTab(_data) {
  return `
    <div class="v5-film-comparison-empty">
      <p>Selectionnez un autre fichier pour comparer la qualite perceptuelle.</p>
      <p class="v5u-text-muted">La fonction de comparaison utilise le moteur LPIPS §11 + les criteres V2.</p>
      <button type="button" class="v5-btn v5-btn--secondary" data-v5-film-pick-compare>
        Choisir un fichier a comparer
      </button>
    </div>
  `;
}

/* ===========================================================
 * Event binding
 * =========================================================== */

function _bindEvents(root) {
  const backBtn = root.querySelector("[data-v5-film-back]");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      if (typeof window !== "undefined" && typeof window.navigateTo === "function") {
        window.navigateTo("library");
      } else if (typeof window !== "undefined") {
        window.location.hash = "library";
      }
    });
  }

  root.querySelectorAll("[data-v5-film-rescan]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!_state.data) return;
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Analyse en cours...";
      try {
        const runId = _state.data.run_id;
        const rowId = _state.data.row_id || _state.rowId;
        await apiPost("analyze_perceptual_single", { run_id: runId, row_id: rowId });
        await _loadAndRender(_state.rowId);
      } catch (e) {
        console.error("[film-detail] rescan:", e);
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  });

  root.querySelectorAll("[data-v5-film-compare]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.activeTab = "comparison";
      _renderTabs(root);
      _renderTabPanel();
    });
  });

  root.querySelectorAll("[data-v5-film-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabId = btn.dataset.v5FilmTab;
      _state.activeTab = tabId;
      _renderTabs(root);
      _renderTabPanel();
    });
    btn.addEventListener("keydown", (e) => {
      const tabs = Array.from(root.querySelectorAll("[data-v5-film-tab]"));
      const idx = tabs.indexOf(btn);
      if (e.key === "ArrowRight" && idx < tabs.length - 1) {
        e.preventDefault();
        tabs[idx + 1].focus();
        tabs[idx + 1].click();
      } else if (e.key === "ArrowLeft" && idx > 0) {
        e.preventDefault();
        tabs[idx - 1].focus();
        tabs[idx - 1].click();
      }
    });
  });
}

function _renderTabs(root) {
  const tabsWrap = root.querySelector(".v5-film-tabs-wrap");
  if (!tabsWrap) return;
  tabsWrap.innerHTML = _buildTabs(_state.activeTab);
  root.querySelectorAll("[data-v5-film-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.activeTab = btn.dataset.v5FilmTab;
      _renderTabs(root);
      _renderTabPanel();
    });
  });
}

/* ===========================================================
 * Mount / Refresh
 * =========================================================== */

async function _loadAndRender(rowId) {
  _state.rowId = rowId;
  const container = _state.containerRef;
  if (!container) return;

  _renderFilmDetailSkeleton(container);
  let data = null;
  try {
    data = await _loadFilmFull(rowId);
  } catch (e) {
    renderError(container, e, () => _loadAndRender(rowId));
    _state.data = null;
    return;
  }
  _state.data = data;

  container.innerHTML = `
    <article class="v5-film-detail">
      ${_buildHero(_state.data)}
      <div class="v5-film-tabs-wrap">${_buildTabs(_state.activeTab)}</div>
    </article>
  `;
  _bindEvents(container);
  _renderTabPanel();
}

/** Init la vue Film standalone.
 *
 * @param {HTMLElement} container - cible DOM
 * @param {object} [opts] - options
 * @param {string} [opts.filmId] - id du film (sinon extrait du hash)
 */
export async function initFilmDetail(container, opts) {
  if (!container) return;
  const o = opts || {};
  const filmId = o.filmId || _extractFilmIdFromHash();
  if (!filmId) {
    renderError(container, "Film ID manquant");
    return;
  }
  _state.containerRef = container;
  _state.activeTab = "overview";
  await _loadAndRender(filmId);
}

/** Demonte la vue (libere les references DOM). */
export function unmountFilmDetail() {
  if (_state.containerRef) {
    _state.containerRef.innerHTML = "";
  }
  _state.containerRef = null;
  _state.rowId = null;
  _state.data = null;
}

/* ===========================================================
 * V3-06 — Mobile drawer mode (Phase A : export only, non cable)
 * Phase B branchera _shouldUseDrawerMode() depuis le router pour
 * ouvrir un drawer slide-up (max-width: 767px) plutot qu'une page
 * complete sur mobile.
 * =========================================================== */

export function shouldUseDrawerMode() {
  return typeof window !== "undefined" && window.matchMedia
    && window.matchMedia("(max-width: 767px)").matches;
}

/** Monte la vue dans un drawer slide-up (mobile mode).
 *
 * @param {HTMLElement} parent - parent (defaut: document.body)
 * @param {object} opts - { filmId }
 * @returns {Promise<HTMLElement|null>} le drawer DOM
 */
export function mountFilmDetailDrawer(parent, opts) {
  const o = opts || {};
  const filmId = o.filmId || _extractFilmIdFromHash();
  if (!filmId) return Promise.resolve(null);
  const host = parent || document.body;
  const drawer = document.createElement("div");
  drawer.className = "v5-drawer v5-drawer--bottom v5-film-drawer";
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  drawer.setAttribute("aria-label", "Detail film");
  drawer.innerHTML = `
    <div class="v5-drawer-handle" aria-hidden="true"></div>
    <div class="v5-drawer-header">
      <button type="button" class="v5-btn v5-btn--icon" id="v5BtnCloseFilmDrawer" aria-label="Fermer">×</button>
    </div>
    <div class="v5-drawer-body" id="v5FilmDrawerBody"></div>
  `;
  host.appendChild(drawer);
  const body = drawer.querySelector("#v5FilmDrawerBody");
  return initFilmDetail(body, { filmId }).then(() => {
    drawer.querySelector("#v5BtnCloseFilmDrawer")?.addEventListener("click", () => {
      unmountFilmDetail();
      drawer.remove();
    });
    return drawer;
  });
}

/* Expose interne pour tests structuraux uniquement (pas d'usage runtime). */
export const __testing = { _state, TABS, _extractFilmIdFromHash };
