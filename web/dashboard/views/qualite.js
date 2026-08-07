/* views/qualite.js — Phase 5 (spec 10-qualite.md) — Vue Qualité complète.
 *
 * 6 sections (spec §1) :
 *  1. Distribution qualité (bargraph 5 tiers)
 *  2. À remplacer en priorité (grille 4×2 mini-posters Reject)
 *  3. Sagas incomplètes (cards + barre progression + lien TMDb)
 *  4. Subs FR manquants (banner)
 *  5. Décennies (histogramme horizontal cliquable)
 *  6. Évolution (graphique SVG line/area + KPIs delta + filtre période)
 *
 * + Drawer filtres globaux (décennie / genre / source / audio / période)
 * + Action "Re-calculer scores" (dangerConfirmModal + polling toast)
 * + Inspecteur droit contextuel par section sélectionnée
 *
 * Tous les endpoints sont consommés depuis PR #304 :
 *   - quality/get_films_by_tier(tier, limit)
 *   - library/get_incomplete_sagas()
 *   - library/get_films_by_decade(filters)  (fallback : get_global_stats.by_decade)
 *   - quality/get_history(period_days)
 *   - quality/recompute_all_scores()
 *   - quality/get_recompute_job_status(job_id)
 *
 * Route cible : /qualite (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import * as rightPanel from "../components/right-panel.js";
import { dangerConfirmModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";
import { openQualiteFiltersDrawer, emptyFilters } from "../components/qualite-filters-drawer.js";

/* --- Tier order + labels --------------------------------------------- */

const _TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject"];
const _TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
};

/* --- Module state ---------------------------------------------------- */
// État interne, recyclé par re-render (filtres globaux + section sélectionnée
// pour l'inspecteur droit + cache des données chargées).
const _state = {
  stats: null,
  rejectFilms: [],     // top 8 Reject
  sagas: [],           // sagas incomplètes
  history: null,       // { points, delta_score, delta_films, delta_reject, period_days }
  byDecade: {},        // { "1930": 12, ... }
  filters: emptyFilters(),
  inspectorSection: "overview",
  inspectorPayload: null,  // payload spécifique (tier / film / saga / décennie)
  recomputeJobId: null,
  recomputePollTimer: null,
  // Fix audit 2026-05-24 : timestamp du dernier toast de progression recompute
  // pour throttler les notifications (5s minimum entre 2 toasts identiques).
  recomputeLastToastTs: 0,
};

/* --- Normalize helpers ----------------------------------------------- */

function _normalizeTierDist(rawDist) {
  const out = {};
  for (const [k, v] of Object.entries(rawDist || {})) {
    out[String(k).toLowerCase()] = Number(v) || 0;
  }
  return out;
}

function _resolveTierDist(stats) {
  // AUDIT 2026-06-14 (R6-F) : la V1 (quality_reports) couvre TOUS les films
  // classes du dernier run ; la V2 (perceptuel) est PARTIELLE (analyse opt-in,
  // souvent quelques films seulement) et donc non representative de la
  // bibliotheque. On prend la V1 comme distribution complete, V2 seulement en
  // repli si la V1 est absente. Evite le faux "100% Bronze / X films classes".
  if (stats && stats.tier_distribution) {
    const v1 = _normalizeTierDist(stats.tier_distribution);
    const v1sum = _TIER_ORDER.reduce((s, t) => s + (v1[t] || 0), 0);
    if (v1sum > 0) return v1;
  }
  if (stats && stats.v2_tier_distribution && stats.v2_tier_distribution.counts) {
    return _normalizeTierDist(stats.v2_tier_distribution.counts);
  }
  return {};
}

function _resolveData(res) {
  // apiPost retourne {status, data}; data contient {ok, ...}.
  if (!res) return null;
  if (res.data) return res.data;
  return res;
}

function _isOk(res) {
  const d = _resolveData(res);
  return !!(d && d.ok !== false);
}

/* --- Renderers ------------------------------------------------------- */

function _renderSkeleton() {
  return `
    <section class="qualite-view qualite-view--loading" aria-busy="true">
      <div class="qualite-header"><div class="v5-skeleton qualite-title-skel"></div></div>
      <div class="qualite-section v5-skeleton qualite-section-skel"></div>
      <div class="qualite-section v5-skeleton qualite-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="qualite-view qualite-view--error" role="alert">
      <h2 class="qualite-error-title">La vue Qualité n'a pas pu se charger.</h2>
      <p>${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-qualite-retry>Réessayer</button>
    </section>
  `;
}

function _renderHeader(stats) {
  const avgScore = (stats && stats.summary && stats.summary.avg_score) || 0;
  const dist = _resolveTierDist(stats);
  const totalScored = _TIER_ORDER.reduce((s, t) => s + (dist[t] || 0), 0);
  // Fix audit 2026-05-24 : `summary.total_films` compte TOUS les films du run
  // (y compris ceux sans tier calcule), pas "X films classes". On utilise la
  // somme par tier pour afficher le vrai nombre de films classes.
  const total = totalScored;
  // Fix audit 2026-05-25 (v1.5.5) Vague J : NaN% quand dist n'a aucun
  // platinum/gold/silver (ex: 853 films tous en Reject -> dist={reject:853}).
  // `undefined + 0 + 0 = NaN`. On garde toutes les valeurs en `|| 0` ET on
  // verifie `Number.isFinite` en sortie pour blinder contre divisions douteuses.
  const _healthy = (dist.platinum || 0) + (dist.gold || 0) + (dist.silver || 0);
  const _healthRaw = totalScored > 0 ? (_healthy / totalScored) * 100 : 0;
  const healthPct = Number.isFinite(_healthRaw) ? Math.round(_healthRaw) : 0;

  // AUDIT 2026-06-11 (R4-P7) : genres retire du compte — le controle a ete
  // retire du drawer (les rows n'ont pas les genres TMDb, filtre sans effet).
  const activeFilterCount = (_state.filters.decades.length
    + _state.filters.sources.length
    + _state.filters.audio_languages.length);

  return `
    <header class="qualite-header">
      <h1 class="qualite-title">Qualité — Audit de la bibliothèque</h1>
      <p class="qualite-summary">
        <strong>${total}</strong> films classés ·
        Score moyen <strong>${avgScore}/100</strong> ·
        Santé globale <strong>${healthPct}%</strong>
      </p>
      <div class="qualite-controls" role="toolbar" aria-label="Actions Qualité">
        <button type="button" class="v5-btn v5-btn--secondary" data-qualite-action="filters">
          ▾ Filtres globaux${activeFilterCount > 0 ? ` <span class="qualite-filter-badge">${activeFilterCount}</span>` : ""}
        </button>
        <button type="button" class="v5-btn v5-btn--ghost" data-qualite-action="recompute">↻ Re-calculer les scores</button>
      </div>
    </header>
  `;
}

/* Section 1 — Distribution qualité */
function _renderDistributionSection(stats) {
  const dist = _resolveTierDist(stats);
  const total = _TIER_ORDER.reduce((s, t) => s + (dist[t] || 0), 0);
  if (total === 0) {
    return `
      <section class="qualite-section qualite-distribution qualite-empty">
        <h2 class="qualite-section-title">📊 Distribution Qualité</h2>
        <p class="qualite-empty-msg">Aucun film classé. Lance un scan pour calculer les tiers.</p>
      </section>
    `;
  }
  const rows = _TIER_ORDER.map((t) => {
    const count = dist[t] || 0;
    const pct = total > 0 ? Math.round((count / total) * 100) : 0;
    return `
      <div class="qualite-tier-row" data-qualite-tier="${escapeHtml(t)}" role="button" tabindex="0">
        <span class="qualite-tier-label">${escapeHtml(_TIER_LABELS[t])}</span>
        <div class="qualite-tier-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
          <span class="qualite-tier-fill qualite-tier-fill--${escapeHtml(t)}" style="--progress:${pct / 100}"></span>
        </div>
        <span class="qualite-tier-count">${count}</span>
        <span class="qualite-tier-pct">${pct}%</span>
      </div>
    `;
  }).join("");
  return `
    <section class="qualite-section qualite-distribution" aria-labelledby="qualite-distribution-title">
      <h2 id="qualite-distribution-title" class="qualite-section-title">📊 Distribution Qualité <span class="qualite-section-meta">${total} films</span></h2>
      <div class="qualite-tier-bars">${rows}</div>
    </section>
  `;
}

/* Section 2 — À remplacer en priorité (top 8 Reject) — Phase 5 */
function _renderRejectSection(stats) {
  const dist = _resolveTierDist(stats);
  const count = dist.reject || 0;
  const films = Array.isArray(_state.rejectFilms) ? _state.rejectFilms : [];

  if (count === 0) {
    return `
      <section class="qualite-section qualite-reject" aria-labelledby="qualite-reject-title">
        <h2 id="qualite-reject-title" class="qualite-section-title">🔴 À remplacer en priorité</h2>
        <p class="qualite-empty-msg">Aucun Reject — bravo !</p>
      </section>
    `;
  }

  const cards = films.slice(0, 8).map((f, idx) => {
    const rowId = String(f.row_id || "");
    const title = String(f.title || "(sans titre)");
    const year = f.year ? Number(f.year) : null;
    // Iter13 etape 4 (2026-06-10) : degradation visible. Quand le probe a
    // echoue (apres retry+breaker iter1-3), on AFFICHE EXPLICITEMENT
    // "Indisponible" plutot qu'un score Silver-cap trompeur. Le film reste
    // identifie et renommable (acquis racine C iter4) ; seule la mesure
    // qualite manque - et on le dit franchement a l'utilisateur.
    const qualityUnavailable = Boolean(f.quality_unavailable)
      || String(f.probe_quality || "").toUpperCase() === "FAILED";
    const score = (!qualityUnavailable && f.score_v2 != null)
      ? Math.round(Number(f.score_v2))
      : null;
    const poster = f.poster_url || "";
    const warningsCount = Array.isArray(f.warnings) ? f.warnings.length : 0;
    return `
      <button type="button" class="qualite-reject-card" data-qualite-reject-card="${escapeHtml(rowId)}" data-qualite-reject-index="${idx}" aria-label="${escapeHtml(title)} (${year || "?"})">
        <div class="qualite-reject-poster">
          ${poster
            ? `<img src="${escapeHtml(poster)}" alt="" loading="lazy" />`
            : `<div class="qualite-reject-poster-empty" aria-hidden="true">🎬</div>`}
          ${qualityUnavailable
            ? `<span class="qualite-reject-score qualite-reject-unavailable" title="Probe indisponible : qualite non mesuree">Indispo</span>`
            : (score != null ? `<span class="qualite-reject-score" title="Score V2">${score}</span>` : "")}
        </div>
        <div class="qualite-reject-meta">
          <span class="qualite-reject-title">${escapeHtml(title)}</span>
          <span class="qualite-reject-year">${year || "—"}</span>
          ${qualityUnavailable ? `<span class="qualite-reject-warnings" title="Qualite non verifiee">⚠ Qualite indisponible</span>` : (warningsCount > 0 ? `<span class="qualite-reject-warnings">⚠ ${warningsCount}</span>` : "")}
        </div>
      </button>
    `;
  }).join("");

  return `
    <section class="qualite-section qualite-reject" aria-labelledby="qualite-reject-title">
      <h2 id="qualite-reject-title" class="qualite-section-title">🔴 À remplacer en priorité <span class="qualite-section-meta">${count} films Reject</span></h2>
      ${films.length > 0
        ? `<div class="qualite-reject-grid">${cards}</div>`
        : `<p class="qualite-empty-msg">Chargement des films Reject…</p>`}
      <div class="qualite-actions">
        <a href="#/bibliotheque?filter=tier_reject" class="v5-btn v5-btn--ghost">→ Voir tous les Reject (${count})</a>
      </div>
    </section>
  `;
}

/* Section 3 — Sagas incomplètes — Phase 5 */
function _renderSagasSection() {
  const sagas = Array.isArray(_state.sagas) ? _state.sagas : [];
  if (sagas.length === 0) {
    return `
      <section class="qualite-section qualite-sagas" aria-labelledby="qualite-sagas-title">
        <h2 id="qualite-sagas-title" class="qualite-section-title">⚠️ Sagas incomplètes</h2>
        <p class="qualite-empty-msg">Aucune saga incomplète détectée.</p>
      </section>
    `;
  }

  const cards = sagas.slice(0, 12).map((saga, idx) => {
    const cid = saga.collection_id ? Number(saga.collection_id) : null;
    const name = String(saga.name || "Saga sans nom");
    const total = Number(saga.total_films_in_collection || 0);
    const owned = Number(saga.owned_count || 0);
    const missing = Number(saga.missing_count || 0);
    const pct = total > 0 ? Math.round((owned / total) * 100) : 0;
    const missingFilms = Array.isArray(saga.missing_films) ? saga.missing_films : [];
    const ownedFilms = Array.isArray(saga.owned_films) ? saga.owned_films : [];

    const missingPreview = missingFilms.slice(0, 3).map((f) => {
      const t = String(f.title || "?");
      const y = f.year ? Number(f.year) : null;
      return `<li>${escapeHtml(t)}${y ? ` <span class="qualite-saga-year">(${y})</span>` : ""}</li>`;
    }).join("");
    const moreMissing = missingFilms.length > 3
      ? `<li class="qualite-saga-more">… et ${missingFilms.length - 3} autre${missingFilms.length - 3 > 1 ? "s" : ""}</li>`
      : "";

    return `
      <article class="qualite-saga-card" data-qualite-saga-index="${idx}" tabindex="0">
        <header class="qualite-saga-header">
          <h3 class="qualite-saga-name">${escapeHtml(name)}</h3>
          <span class="qualite-saga-counts">${owned} / ${total} <span class="qualite-saga-missing-pill">${missing} manquant${missing > 1 ? "s" : ""}</span></span>
        </header>
        <div class="qualite-saga-progress" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="${pct}% complet">
          <span class="qualite-saga-progress-fill" style="--progress:${pct / 100}"></span>
        </div>
        ${missingPreview ? `
          <details class="qualite-saga-details">
            <summary>Voir les films manquants (${missingFilms.length})</summary>
            <ul class="qualite-saga-list qualite-saga-list--missing">${missingPreview}${moreMissing}</ul>
            ${ownedFilms.length > 0 ? `
              <p class="qualite-saga-owned-title">Présents (${ownedFilms.length}) :</p>
              <ul class="qualite-saga-list qualite-saga-list--owned">${ownedFilms.slice(0, 3).map((f) => `<li>${escapeHtml(String(f.title || "?"))}${f.year ? ` <span class="qualite-saga-year">(${Number(f.year)})</span>` : ""}</li>`).join("")}${ownedFilms.length > 3 ? `<li class="qualite-saga-more">… et ${ownedFilms.length - 3} autre${ownedFilms.length - 3 > 1 ? "s" : ""}</li>` : ""}</ul>
            ` : ""}
          </details>
        ` : ""}
        <div class="qualite-saga-actions">
          ${cid
            ? `<a href="https://www.themoviedb.org/collection/${cid}" target="_blank" rel="noopener noreferrer" class="v5-btn v5-btn--ghost qualite-saga-tmdb">→ Voir sur TMDb</a>`
            : `<span class="qualite-saga-no-tmdb">Pas d'ID TMDb</span>`}
        </div>
      </article>
    `;
  }).join("");

  return `
    <section class="qualite-section qualite-sagas" aria-labelledby="qualite-sagas-title">
      <h2 id="qualite-sagas-title" class="qualite-section-title">⚠️ Sagas incomplètes <span class="qualite-section-meta">${sagas.length} saga${sagas.length > 1 ? "s" : ""}</span></h2>
      <div class="qualite-saga-cards">${cards}</div>
    </section>
  `;
}

/* Section 4 — Subs FR manquants (banner) */
function _renderSubsSection(stats) {
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const subsInsight = insights.find((i) => String(i.type || i.code || "").includes("subs_missing"));
  const count = subsInsight && subsInsight.count != null ? Number(subsInsight.count) : null;
  const lsugs = stats && stats.librarian && stats.librarian.suggestions;
  // R8-050 (F5) : la source réelle est librarian.suggestions id="missing_subtitles"
  // (le producteur d'insights n'émet PAS subs_missing). AVANT : .includes("subs_missing")
  // ne matchait jamais l'id "missing_subtitles" -> section « Subs FR manquants » toujours « — ».
  const subsLs = Array.isArray(lsugs)
    ? lsugs.find((s) => { const id = String(s.id || ""); return id.includes("subtitle") || id.includes("subs_missing"); })
    : null;
  const finalCount = count != null ? count : (subsLs && subsLs.count != null ? Number(subsLs.count) : null);
  return `
    <section class="qualite-section qualite-subs" aria-labelledby="qualite-subs-title">
      <h2 id="qualite-subs-title" class="qualite-section-title">💬 Subs FR manquants <span class="qualite-section-meta">${finalCount != null ? finalCount + " films" : "—"}</span></h2>
      <div class="qualite-subs-banner">
        <p>${finalCount != null && finalCount > 0
          ? `<strong>${finalCount} films</strong> n'ont pas de sous-titres FR détectés.`
          : "Tous les films ont des sous-titres FR détectés."}</p>
        <div class="qualite-actions">
          <button type="button" class="v5-btn v5-btn--secondary" data-qualite-action="configure-subs">⚙ Configurer recherche subs</button>
          <a href="#/bibliotheque?filter=subs_missing_fr" class="v5-btn v5-btn--ghost">→ Voir la liste</a>
        </div>
      </div>
    </section>
  `;
}

/* Section 5 — Décennies (histogramme cliquable) — Phase 5 */
function _renderDecadesSection(stats) {
  // Priorise byDecade depuis l'endpoint dédié (get_films_by_decade)
  // sinon fallback sur stats.by_decade (enrichi par get_global_stats).
  const fromState = _state.byDecade && Object.keys(_state.byDecade).length > 0 ? _state.byDecade : null;
  const fromStats = stats && (stats.by_decade || (stats.summary && stats.summary.by_decade));
  const byDecade = fromState || fromStats;

  if (!byDecade || typeof byDecade !== "object" || Object.keys(byDecade).length === 0) {
    return `
      <section class="qualite-section qualite-decades" aria-labelledby="qualite-decades-title">
        <h2 id="qualite-decades-title" class="qualite-section-title">📅 Décennies</h2>
        <p class="qualite-empty-msg">Aucune donnée par décennie disponible.</p>
      </section>
    `;
  }
  const entries = Object.entries(byDecade)
    .filter(([d]) => d && d !== "unknown")
    .sort(([a], [b]) => String(a).localeCompare(String(b)));
  const maxN = entries.reduce((m, [, v]) => Math.max(m, Number(v) || 0), 0);

  return `
    <section class="qualite-section qualite-decades" aria-labelledby="qualite-decades-title">
      <h2 id="qualite-decades-title" class="qualite-section-title">📅 Décennies <span class="qualite-section-meta">${entries.length} décennie${entries.length > 1 ? "s" : ""}</span></h2>
      <div class="qualite-decades-list">
        ${entries.map(([decade, n]) => {
          const count = Number(n) || 0;
          const pct = maxN > 0 ? Math.round((count / maxN) * 100) : 0;
          return `
            <button type="button" class="qualite-decade-row" data-qualite-decade="${escapeHtml(decade)}">
              <span class="qualite-decade-label">${escapeHtml(decade)}s : ${count}</span>
              <div class="qualite-decade-bar"><span class="qualite-decade-fill" style="width:${pct}%"></span></div>
              <span class="qualite-decade-count">${count}</span>
            </button>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

/* Section 6 — Évolution (SVG line + KPIs delta + filtre période) — Phase 5
 * Phase 6 (spec 10 §6) : captions dates aux extrémités, tooltips au survol des
 * points, labels axe X (dates) et axe Y (scores graduations).
 */
function _renderEvolutionSection() {
  const hist = _state.history;
  const period = _normalizePeriodDays(hist && hist.period_days != null ? hist.period_days : _state.filters.period_days);
  const points = Array.isArray(hist && hist.points) ? hist.points : [];
  const validPoints = points.filter((p) => p && p.avg_score != null);

  const deltaScore = hist && hist.delta_score != null ? Number(hist.delta_score) : 0;
  const deltaFilms = hist && hist.delta_films != null ? Number(hist.delta_films) : 0;
  const deltaReject = hist && hist.delta_reject != null ? Number(hist.delta_reject) : 0;

  const fmtDelta = (v) => `${v > 0 ? "+" : ""}${v}`;
  const iconFor = (v, inverted = false) => {
    if (v === 0) return "→";
    const positive = inverted ? v < 0 : v > 0;
    return positive ? "📈" : "📉";
  };

  const chartSvg = _renderEvolutionChart(validPoints);

  const periodBtns = [7, 30, 90, 0].map((p) => {
    const active = Number(p) === Number(period) ? "qualite-period-btn--active" : "";
    const label = p === 0 ? "Tout" : `${p}j`;
    return `<button type="button" class="qualite-period-btn ${active}" data-qualite-period="${p}">${label}</button>`;
  }).join("");

  // Caption : "entre 5 avril et 5 mai" si filtre 30j (spec §6 — format français lisible)
  const captionText = validPoints.length > 0
    ? _buildEvolutionCaption(validPoints, period)
    : "";

  return `
    <section class="qualite-section qualite-evolution" aria-labelledby="qualite-evolution-title">
      <h2 id="qualite-evolution-title" class="qualite-section-title">
        📈 Évolution
        <span class="qualite-section-meta">${period === 0 ? "Tout l'historique" : `${period} derniers jours`}</span>
      </h2>
      <div class="qualite-period-switch" role="tablist" aria-label="Période d'évolution">${periodBtns}</div>
      <dl class="qualite-evolution-kpis">
        <div><dt>Δ Score moyen</dt><dd>${fmtDelta(deltaScore)} ${iconFor(deltaScore)}</dd></div>
        <div><dt>Δ Films classifiés</dt><dd>${fmtDelta(deltaFilms)} ${iconFor(deltaFilms)}</dd></div>
        <div><dt>Δ Reject</dt><dd class="${deltaReject < 0 ? "qualite-kpi-good" : (deltaReject > 0 ? "qualite-kpi-bad" : "")}">${fmtDelta(deltaReject)} ${iconFor(deltaReject, true)}</dd></div>
      </dl>
      <div class="qualite-evolution-chart">${chartSvg}</div>
      ${validPoints.length === 0
        ? `<p class="qualite-empty-msg">Aucune mesure disponible sur la période.</p>`
        : `<p class="qualite-evolution-caption">${escapeHtml(captionText)}</p>`}
    </section>
  `;
}

/* Formate une date ISO "2026-05-05" en "5 mai 2026" (libellé court "5 mai" si même année). */
function _formatDateFr(isoDate, includeYear = false) {
  if (!isoDate || typeof isoDate !== "string") return "";
  const m = isoDate.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return isoDate;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const months = ["janvier", "février", "mars", "avril", "mai", "juin",
                  "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
  const monthLabel = months[month - 1] || `m${month}`;
  return includeYear ? `${day} ${monthLabel} ${year}` : `${day} ${monthLabel}`;
}

/* Construit la caption "N points entre <date1> et <date2>" en format français. */
function _buildEvolutionCaption(validPoints, period) {
  if (!validPoints || validPoints.length === 0) return "";
  const first = validPoints[0].date || "";
  const last = validPoints[validPoints.length - 1].date || "";
  // Inclure année dans la borne de début si bornes traversent plusieurs années
  const firstYear = (first.match(/^(\d{4})/) || [])[1];
  const lastYear = (last.match(/^(\d{4})/) || [])[1];
  const includeYear = firstYear && lastYear && firstYear !== lastYear;
  const startLabel = _formatDateFr(first, includeYear) || first;
  const endLabel = _formatDateFr(last, true) || last;
  const n = validPoints.length;
  const periodLabel = period === 0 ? "tout l'historique" : `${period}j`;
  return `${n} point${n > 1 ? "s" : ""} de mesure entre ${startLabel} et ${endLabel} (${periodLabel})`;
}

function _renderEvolutionChart(validPoints) {
  if (!Array.isArray(validPoints) || validPoints.length === 0) {
    return `<svg class="qualite-evolution-svg" viewBox="0 0 100 50" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="25" x2="100" y2="25" stroke="var(--text-2)" stroke-dasharray="2 2"/></svg>`;
  }
  // Marges étendues pour accueillir les labels d'axes (gauche pour Y, bas pour X)
  const w = 100;
  const h = 50;
  const padTop = 3;
  const padRight = 3;
  const padBottom = 9;   // place pour labels axe X (dates)
  const padLeft = 10;    // place pour labels axe Y (scores)

  const innerW = w - padLeft - padRight;
  const innerH = h - padTop - padBottom;

  const xs = validPoints.map((_, i) => padLeft + (i / Math.max(1, validPoints.length - 1)) * innerW);
  const ys = validPoints.map((p) => Number(p.avg_score) || 0);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 100);
  const range = Math.max(1, maxY - minY);
  const toSvgY = (v) => padTop + (1 - (Number(v) - minY) / range) * innerH;
  const pts = xs.map((x, i) => `${x.toFixed(2)},${toSvgY(ys[i]).toFixed(2)}`);
  const lineD = "M " + pts.join(" L ");
  const baselineY = h - padBottom;
  const areaD = lineD + ` L ${xs[xs.length - 1].toFixed(2)},${baselineY.toFixed(2)} L ${xs[0].toFixed(2)},${baselineY.toFixed(2)} Z`;

  // Axe Y : 3 graduations (min / mid / max)
  const yTicks = [minY, (minY + maxY) / 2, maxY].map((v) => ({
    y: toSvgY(v).toFixed(2),
    label: Math.round(v),
  }));

  const yAxisLabels = yTicks.map((t) =>
    `<text x="${(padLeft - 1).toFixed(2)}" y="${t.y}" class="qualite-evolution-axis-label" text-anchor="end" dominant-baseline="middle">${t.label}</text>`
  ).join("");

  // Axe X : labels date début + date fin (+ milieu si assez de place)
  const firstDate = validPoints[0].date || "";
  const lastDate = validPoints[validPoints.length - 1].date || "";
  const xAxisLabels = [];
  if (firstDate) {
    xAxisLabels.push(
      `<text x="${xs[0].toFixed(2)}" y="${(h - 1).toFixed(2)}" class="qualite-evolution-axis-label" text-anchor="start">${escapeHtml(_formatDateFr(firstDate))}</text>`
    );
  }
  if (validPoints.length >= 3) {
    const midIdx = Math.floor(validPoints.length / 2);
    const midDate = validPoints[midIdx].date || "";
    if (midDate) {
      xAxisLabels.push(
        `<text x="${xs[midIdx].toFixed(2)}" y="${(h - 1).toFixed(2)}" class="qualite-evolution-axis-label" text-anchor="middle">${escapeHtml(_formatDateFr(midDate))}</text>`
      );
    }
  }
  if (lastDate && lastDate !== firstDate) {
    xAxisLabels.push(
      `<text x="${xs[xs.length - 1].toFixed(2)}" y="${(h - 1).toFixed(2)}" class="qualite-evolution-axis-label" text-anchor="end">${escapeHtml(_formatDateFr(lastDate))}</text>`
    );
  }

  // Ligne baseline axe X
  const baseline = `<line x1="${padLeft}" y1="${baselineY.toFixed(2)}" x2="${(w - padRight).toFixed(2)}" y2="${baselineY.toFixed(2)}" class="qualite-evolution-axis"/>`;

  // Cercles + tooltips (title attribute) sur chaque point
  const circles = validPoints.map((p, i) => {
    const x = xs[i].toFixed(2);
    const y = toSvgY(ys[i]).toFixed(2);
    const dateLabel = _formatDateFr(p.date || "", true);
    const score = Math.round(ys[i]);
    const filmsCount = p.count_films != null ? Number(p.count_films) : null;
    const tooltip = `${dateLabel || p.date || ""} — Score ${score}/100${filmsCount != null ? ` — ${filmsCount} films` : ""}`;
    return `<circle cx="${x}" cy="${y}" r="0.9" class="qualite-evolution-point" data-qualite-point-index="${i}"><title>${escapeHtml(tooltip)}</title></circle>`;
  }).join("");

  return `
    <svg class="qualite-evolution-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Graphique d'évolution du score moyen, ${validPoints.length} points entre ${escapeHtml(_formatDateFr(firstDate, true))} et ${escapeHtml(_formatDateFr(lastDate, true))}">
      <path d="${areaD}" fill="var(--accent)" fill-opacity="0.15"/>
      <path d="${lineD}" fill="none" stroke="var(--accent)" stroke-width="0.8" stroke-linejoin="round"/>
      ${baseline}
      ${yAxisLabels}
      ${xAxisLabels.join("")}
      ${circles}
    </svg>
  `;
}

function _renderQualite(stats) {
  return `
    <section class="qualite-view">
      ${_renderHeader(stats)}
      ${_renderDistributionSection(stats)}
      ${_renderRejectSection(stats)}
      ${_renderSagasSection()}
      ${_renderSubsSection(stats)}
      ${_renderDecadesSection(stats)}
      ${_renderEvolutionSection()}
    </section>
  `;
}

/* --- Inspector content (spec §5) -------------------------------------- */

function _dominantTier(dist) {
  // LOTC-M3 : max init a 0 (comparaison stricte) -> tous compteurs a 0 =
  // "—" au lieu d'un "Platinum" fictif (1er tier de _TIER_ORDER).
  let max = 0;
  let dom = "—";
  for (const t of _TIER_ORDER) {
    const v = dist[t] || 0;
    if (v > max) { max = v; dom = t; }
  }
  return dom;
}

function _buildInspectorSections() {
  const stats = _state.stats || {};
  const dist = _resolveTierDist(stats);
  const total = _TIER_ORDER.reduce((s, t) => s + (dist[t] || 0), 0);
  const overview = {
    title: "Vue d'ensemble",
    html: `
      <dl class="qualite-inspector-dl">
        <div><dt>Films classés</dt><dd>${total}</dd></div>
        <div><dt>Score moyen</dt><dd>${(stats.summary && stats.summary.avg_score) || "—"}/100</dd></div>
        <div><dt>Tier dominant</dt><dd>${_TIER_LABELS[_dominantTier(dist)] || "—"}</dd></div>
      </dl>
    `,
  };

  let contextual = null;
  switch (_state.inspectorSection) {
    case "distribution": {
      const tier = _state.inspectorPayload && _state.inspectorPayload.tier;
      const tierLabel = tier ? _TIER_LABELS[tier] || tier : "?";
      // Top 10 / bottom 10 reposent sur cache _state.rejectFilms si tier=reject,
      // sinon on annonce un chargement à la demande.
      const films = (_state.inspectorPayload && _state.inspectorPayload.films) || [];
      contextual = {
        title: `Tier ${escapeHtml(tierLabel)}`,
        html: films.length > 0
          ? `<ul class="qualite-inspector-list">${films.slice(0, 10).map((f) => {
              // Iter13 etape 4 : afficher "Indisponible" si probe FAILED.
              const unavailable = Boolean(f.quality_unavailable)
                || String(f.probe_quality || "").toUpperCase() === "FAILED";
              const scoreLabel = unavailable
                ? `<span class="qualite-inspector-score qualite-reject-unavailable" title="Probe indisponible">Indisponible</span>`
                : `<span class="qualite-inspector-score">${f.score_v2 != null ? Math.round(Number(f.score_v2)) : "—"}/100</span>`;
              return `<li><strong>${escapeHtml(String(f.title || "?"))}</strong>${f.year ? ` <span class="qualite-saga-year">(${Number(f.year)})</span>` : ""} ${scoreLabel}</li>`;
            }).join("")}</ul>`
          : `<p class="qualite-empty-msg">Aucun film dans ce tier.</p>`,
      };
      break;
    }
    case "reject_card": {
      const film = _state.inspectorPayload && _state.inspectorPayload.film;
      if (film) {
        const warningsList = Array.isArray(film.warnings) && film.warnings.length > 0
          ? `<ul class="qualite-inspector-warnings">${film.warnings.slice(0, 5).map((w) => `<li>${escapeHtml(String(w))}</li>`).join("")}</ul>`
          : `<p class="qualite-empty-msg">Aucun warning</p>`;
        contextual = {
          title: escapeHtml(String(film.title || "Film")),
          html: `
            <dl class="qualite-inspector-dl">
              <div><dt>Année</dt><dd>${film.year || "—"}</dd></div>
              <div><dt>Score V2</dt><dd>${(Boolean(film.quality_unavailable) || String(film.probe_quality || "").toUpperCase() === "FAILED")
                ? `<span class="qualite-reject-unavailable" title="Probe indisponible apres retry+breaker">Indisponible</span>`
                : (film.score_v2 != null ? Math.round(Number(film.score_v2)) + "/100" : "—")}</dd></div>
              <div><dt>Tier</dt><dd>${(Boolean(film.quality_unavailable) || String(film.probe_quality || "").toUpperCase() === "FAILED")
                ? `<span title="Qualite non verifiee : tier base sur le nom seul">${escapeHtml(_TIER_LABELS[String(film.tier || "").toLowerCase()] || film.tier || "—")} <em>(estime)</em></span>`
                : escapeHtml(_TIER_LABELS[String(film.tier || "").toLowerCase()] || film.tier || "—")}</dd></div>
            </dl>
            <p class="qualite-inspector-warnings-title">Warnings :</p>
            ${warningsList}
            <div class="qualite-actions">
              <button type="button" class="v5-btn v5-btn--primary" data-qualite-action="open-film" data-qualite-row-id="${escapeHtml(String(film.row_id || ""))}">Ouvrir la fiche détail</button>
            </div>
          `,
        };
      }
      break;
    }
    case "saga": {
      const saga = _state.inspectorPayload && _state.inspectorPayload.saga;
      if (saga) {
        const owned = Array.isArray(saga.owned_films) ? saga.owned_films : [];
        const missing = Array.isArray(saga.missing_films) ? saga.missing_films : [];
        const cid = saga.collection_id;
        contextual = {
          title: escapeHtml(String(saga.name || "Saga")),
          html: `
            <p>${owned.length} possédés · ${missing.length} manquants</p>
            <p class="qualite-inspector-warnings-title">Possédés :</p>
            <ul class="qualite-inspector-list">${owned.slice(0, 10).map((f) => `<li>${escapeHtml(String(f.title || "?"))}${f.year ? ` (${Number(f.year)})` : ""}</li>`).join("")}</ul>
            <p class="qualite-inspector-warnings-title">Manquants :</p>
            <ul class="qualite-inspector-list">${missing.slice(0, 10).map((f) => `<li>${escapeHtml(String(f.title || "?"))}${f.year ? ` (${Number(f.year)})` : ""}</li>`).join("")}</ul>
            ${cid ? `<div class="qualite-actions"><a href="https://www.themoviedb.org/collection/${Number(cid)}" target="_blank" rel="noopener noreferrer" class="v5-btn v5-btn--ghost">→ TMDb</a></div>` : ""}
          `,
        };
      }
      break;
    }
    case "decade": {
      const decade = _state.inspectorPayload && _state.inspectorPayload.decade;
      const count = (_state.byDecade && _state.byDecade[decade]) || 0;
      contextual = {
        title: `Décennie ${escapeHtml(String(decade || "?"))}s`,
        html: `
          <p><strong>${count}</strong> film${count > 1 ? "s" : ""} de cette décennie.</p>
          <div class="qualite-actions">
            <a href="#/bibliotheque?filter=decade_${escapeHtml(String(decade || ""))}" class="v5-btn v5-btn--ghost">→ Voir dans Bibliothèque</a>
          </div>
        `,
      };
      break;
    }
    case "evolution": {
      const hist = _state.history;
      const rows = Array.isArray(hist && hist.points) ? hist.points : [];
      contextual = {
        title: "Historique des mesures",
        html: rows.length > 0
          ? `<table class="qualite-inspector-table"><thead><tr><th>Date</th><th>Score</th><th>Films</th></tr></thead><tbody>${rows.slice(-15).map((p) => `<tr><td>${escapeHtml(p.date || "")}</td><td>${p.avg_score != null ? Math.round(Number(p.avg_score)) : "—"}</td><td>${p.count_films != null ? Number(p.count_films) : "—"}</td></tr>`).join("")}</tbody></table>`
          : `<p class="qualite-empty-msg">Aucun point disponible.</p>`,
      };
      break;
    }
    default:
      contextual = {
        title: "Détail par section",
        html: `<p class="qualite-empty-msg">Clique sur un tier, un Reject, une saga, une décennie ou la section Évolution pour voir le détail ici.</p>`,
      };
  }

  return [
    overview,
    contextual,
    {
      title: "Action longue",
      html: `
        <button type="button" class="v5-btn v5-btn--ghost" data-qualite-action="recompute" style="width:100%">↻ Re-calculer tous les scores</button>
        <p class="qualite-empty-msg" style="margin-top:var(--sp-2);">Utile après modification du profil qualité (Paramètres &gt; Profils Qualité). Durée : 5-10 minutes.</p>
      `,
    },
  ];
}

function _updateInspector() {
  if (typeof rightPanel.setSections !== "function") return;
  try {
    rightPanel.setSections(_buildInspectorSections());
  } catch (err) {
    console.warn("[qualite] setSections inspector failed:", err);
  }
}

/* --- Data loaders ----------------------------------------------------- */

async function _loadRejectFilms(signal) {
  try {
    const res = await apiPost("quality/get_films_by_tier", { tier: "reject", limit: 8 }, { signal });
    const data = _resolveData(res);
    if (data && data.ok !== false && Array.isArray(data.films)) {
      _state.rejectFilms = data.films;
    } else {
      _state.rejectFilms = [];
    }
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    console.warn("[qualite] get_films_by_tier failed:", err);
    _state.rejectFilms = [];
  }
}

async function _loadSagas(signal) {
  try {
    const res = await apiPost("library/get_incomplete_sagas", {}, { signal });
    const data = _resolveData(res);
    if (data && data.ok !== false && Array.isArray(data.sagas)) {
      _state.sagas = data.sagas;
    } else {
      _state.sagas = [];
    }
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    console.warn("[qualite] get_incomplete_sagas failed:", err);
    _state.sagas = [];
  }
}

async function _loadByDecade(signal, filters) {
  try {
    const payload = filters && Object.keys(filters).length > 0 ? { filters } : {};
    const res = await apiPost("library/get_films_by_decade", payload, { signal });
    const data = _resolveData(res);
    if (data && data.ok !== false && data.by_decade) {
      _state.byDecade = data.by_decade;
    } else {
      _state.byDecade = {};
    }
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    console.warn("[qualite] get_films_by_decade failed:", err);
    _state.byDecade = {};
  }
}

// AUDIT 2026-06-11 (R4-P8) : `x || 30` avalait period_days=0 ('Tout', supporté
// backend 0=all par quality/get_history) -> la période 'Tout' renvoyait
// toujours 30 jours. 0 est une valeur VALIDE ; seuls null/undefined/NaN/<0
// retombent sur 30.
function _normalizePeriodDays(value) {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : 30;
}

async function _loadHistory(signal, periodDays) {
  try {
    const res = await apiPost("quality/get_history", { period_days: _normalizePeriodDays(periodDays) }, { signal });
    const data = _resolveData(res);
    if (data && data.ok !== false) {
      _state.history = data;
    } else {
      _state.history = null;
    }
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    console.warn("[qualite] get_history failed:", err);
    _state.history = null;
  }
}

/* --- Events ----------------------------------------------------------- */

// LOTC-C1 : la CSP (script-src 'self') bloque les 'onerror' inline -> filet
// jaquettes Reject via listener 'error' delegue en phase capture (les events
// error des <img> ne bouillonnent pas), meme pattern que la grille
// Bibliotheque (R6-H). Fonction nommee -> re-bind apres re-render = no-op.
function _onPosterError(ev) {
  const img = ev.target;
  if (!img || img.tagName !== "IMG" || typeof img.closest !== "function") return;
  if (!img.closest(".qualite-reject-poster")) return;
  img.style.display = "none";
}

function _bindEvents(container) {
  container.addEventListener("error", _onPosterError, true); // LOTC-C1

  container.querySelectorAll("[data-qualite-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const action = btn.dataset.qualiteAction;
      switch (action) {
        case "filters":
          _openFiltersDrawer(container);
          break;
        case "recompute":
          _confirmRecompute();
          break;
        case "configure-subs":
          navigateTo("/parametres#analyse-subs");
          break;
        case "open-film": {
          const rid = btn.dataset.qualiteRowId;
          if (rid) navigateTo(`/film/${encodeURIComponent(rid)}`);
          break;
        }
        default:
          break;
      }
    });
  });

  // Clic sur tier bar -> sélection inspecteur + navigation Bibliothèque
  container.querySelectorAll("[data-qualite-tier]").forEach((row) => {
    const handler = (navAlso) => {
      const tier = row.dataset.qualiteTier;
      _state.inspectorSection = "distribution";
      _state.inspectorPayload = { tier, films: tier === "reject" ? _state.rejectFilms : [] };
      _updateInspector();
      if (navAlso) {
        navigateTo(`/bibliotheque?filter=tier_${encodeURIComponent(tier)}`);
      }
    };
    row.addEventListener("click", () => handler(true));
    row.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        handler(true);
      }
    });
    row.style.cursor = "pointer";
  });

  // Clic sur card Reject -> inspecteur (mode C) avec warnings/score V2
  // Fix audit 2026-06-07 : la navigation immediate vers /film/:id demontait la
  // vue Qualite et rendait le contexte inspecteur 'reject_card' invisible.
  // L'inspecteur expose desormais un bouton 'Ouvrir la fiche' pour naviguer.
  container.querySelectorAll("[data-qualite-reject-card]").forEach((card) => {
    card.addEventListener("click", () => {
      const idx = Number(card.dataset.qualiteRejectIndex);
      const film = _state.rejectFilms[idx];
      if (!film) return;
      _state.inspectorSection = "reject_card";
      _state.inspectorPayload = { film };
      _updateInspector();
    });
  });

  // Clic sur saga card -> inspecteur
  container.querySelectorAll("[data-qualite-saga-index]").forEach((card) => {
    card.addEventListener("click", (ev) => {
      // Ne pas trigger si clic sur lien TMDb interne
      if (ev.target && (ev.target.closest("a") || ev.target.closest("details") || ev.target.closest("summary"))) {
        return;
      }
      const idx = Number(card.dataset.qualiteSagaIndex);
      const saga = _state.sagas[idx];
      if (!saga) return;
      _state.inspectorSection = "saga";
      _state.inspectorPayload = { saga };
      _updateInspector();
    });
  });

  // Clic sur décennie -> inspecteur + nav
  container.querySelectorAll("[data-qualite-decade]").forEach((row) => {
    row.addEventListener("click", () => {
      const decade = row.dataset.qualiteDecade;
      _state.inspectorSection = "decade";
      _state.inspectorPayload = { decade };
      _updateInspector();
      navigateTo(`/bibliotheque?filter=decade_${encodeURIComponent(decade)}`);
    });
  });

  // Switch période (Évolution)
  container.querySelectorAll("[data-qualite-period]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const newPeriod = Number(btn.dataset.qualitePeriod);
      _state.filters.period_days = newPeriod;
      const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;
      await _loadHistory(signal, newPeriod);
      _rerender(container);
      _state.inspectorSection = "evolution";
      _updateInspector();
    });
  });

  // Click sur section Evolution (whole) -> inspecteur historique tableau
  const evoSection = container.querySelector(".qualite-evolution");
  if (evoSection) {
    evoSection.addEventListener("click", (ev) => {
      // N'override pas si clic sur bouton interne
      if (ev.target && (ev.target.closest("[data-qualite-period]") || ev.target.closest("[data-qualite-action]"))) return;
      _state.inspectorSection = "evolution";
      _state.inspectorPayload = null;
      _updateInspector();
    });
  }

  const retryBtn = container.querySelector("[data-qualite-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initQualite(container));
}

/* --- Filters drawer --------------------------------------------------- */

function _openFiltersDrawer(container) {
  openQualiteFiltersDrawer({
    initial: _state.filters,
    onReset: () => {
      _state.filters = emptyFilters();
    },
    onApply: async (newFilters) => {
      _state.filters = newFilters;
      const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;
      // Re-charger les sections impactees par les filtres
      // Fix audit 2026-05-24 : Reject + Sagas etaient absents -> filtres ignores
      // pour ces 2 podiums. _loadRejectFilms/_loadSagas n'acceptent que (signal)
      // aujourd'hui, mais on les inclut pour re-fetch coherent au prochain
      // appel apres maj des filtres globaux (la signature backend pourra
      // accepter les filtres plus tard sans changer l'appelant).
      try {
        await Promise.all([
          _loadByDecade(signal, newFilters),
          _loadHistory(signal, _normalizePeriodDays(newFilters.period_days)),
          _loadRejectFilms(signal),
          _loadSagas(signal),
        ]);
      } catch (_e) { /* abort */ }
      _rerender(container);
      showToast({ type: "info", text: "Filtres appliqués", duration: 2000 });
    },
  });
}

/* --- Recompute ------------------------------------------------------- */

function _confirmRecompute() {
  const total = (_state.stats && _state.stats.summary && _state.stats.summary.total_films) || 0;
  const eta = total > 0 ? `Durée estimée : ~${Math.max(1, Math.round(total / 100))} minute${total > 100 ? "s" : ""}` : "Durée estimée : 5-10 minutes";

  dangerConfirmModal({
    title: "Re-calculer tous les scores ?",
    consequence: `Cette opération va re-scorer ${total > 0 ? total + " " : ""}films classés à partir du profil de qualité actuel. ${eta}. Aucune modification sur les fichiers du disque. Réversible.`,
    confirmLabel: "Lancer le re-calcul",
    cancelLabel: "Annuler",
    // Regle n3 : delai derive du nombre de films par la modale
    // (`gradedCountdownSeconds`), et non recalcule ici.
    itemCount: total,
    onConfirm: async () => {
      await _startRecompute();
    },
  });
}

async function _startRecompute() {
  let res;
  try {
    res = await apiPost("quality/recompute_all_scores", {});
  } catch (err) {
    showToast({ type: "error", text: `Re-calcul impossible : ${err && err.message ? err.message : err}` });
    return;
  }
  const data = _resolveData(res);
  if (!data || data.ok === false) {
    showToast({ type: "error", text: (data && (data.message || data.error)) || "Re-calcul impossible" });
    return;
  }
  const jobId = data.job_id;
  const total = data.total || 0;
  _state.recomputeJobId = jobId;
  showToast({ type: "info", text: `Re-calcul lancé (${total} films)`, duration: 2500 });
  _pollRecompute(jobId, total);
}

function _pollRecompute(jobId, total) {
  if (_state.recomputePollTimer) {
    clearInterval(_state.recomputePollTimer);
    _state.recomputePollTimer = null;
  }
  const tick = async () => {
    let res;
    try {
      res = await apiPost("quality/get_recompute_job_status", { job_id: jobId });
    } catch (err) {
      console.warn("[qualite] poll recompute err:", err);
      return;
    }
    const data = _resolveData(res);
    if (!data || data.ok === false) {
      clearInterval(_state.recomputePollTimer);
      _state.recomputePollTimer = null;
      showToast({ type: "error", text: (data && (data.message || data.error)) || "Polling impossible" });
      return;
    }
    const status = data.status;
    const progress = Number(data.progress || 0);
    const totalJob = Number(data.total || total || 0);
    if (status === "running" || status === "pending") {
      // Fix audit 2026-05-24 : avant, on emettait un toast à chaque tick (2s)
      // -> spam visuel pour un re-calcul de plusieurs minutes. On throttle à
      // 5s minimum entre deux toasts de progression.
      const now = Date.now();
      if (!_state.recomputeLastToastTs || now - _state.recomputeLastToastTs >= 5000) {
        _state.recomputeLastToastTs = now;
        showToast({ type: "info", text: `Re-calcul ${progress}/${totalJob}…`, duration: 1500 });
      }
      return;
    }
    // Terminé
    clearInterval(_state.recomputePollTimer);
    _state.recomputePollTimer = null;
    if (status === "done") {
      // AUDIT 2026-06-14 (R7-11) : tenir compte des echecs metier (data.errors)
      // -> ne plus afficher un toast vert "N/N" quand des films ont echoue.
      const errs = Number(data.errors || 0);
      if (errs >= totalJob && totalJob > 0) {
        showToast({ type: "error", text: `Re-calcul : ${errs}/${totalJob} en échec (vérifiez ffprobe/médias).`, duration: 6000 });
      } else if (errs > 0) {
        showToast({ type: "warn", text: `Scores re-calculés : ${totalJob - errs}/${totalJob} OK, ${errs} échec(s).`, duration: 6000 });
      } else {
        showToast({ type: "success", text: `✓ Scores re-calculés (${progress}/${totalJob})`, duration: 4500 });
      }
    } else if (status === "failed") {
      showToast({ type: "error", text: `Re-calcul échoué : ${data.error || "erreur inconnue"}` });
    } else if (status === "cancelled") {
      showToast({ type: "warn", text: "Re-calcul annulé" });
    } else {
      showToast({ type: "info", text: `Re-calcul ${status}` });
    }
  };
  _state.recomputePollTimer = setInterval(tick, 2000);
  // Tick immédiat pour fluidité
  tick();
}

/* --- Rerender helper ------------------------------------------------- */

function _rerender(container) {
  if (!container) return;
  container.innerHTML = _renderQualite(_state.stats || {});
  _bindEvents(container);
  _updateInspector();
}

/* --- Entrypoint ------------------------------------------------------- */

export async function initQualite(container) {
  if (!container) return;
  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;

  // 1) get_global_stats : socle
  let res = null;
  try {
    res = await apiPost("run/get_global_stats", {}, { signal });
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }
  if (!_isOk(res)) {
    const data = _resolveData(res);
    container.innerHTML = _renderError((data && (data.message || data.error)) || "Erreur de chargement.");
    _bindEvents(container);
    return;
  }
  _state.stats = _resolveData(res);

  // 2) Endpoints supplémentaires en parallèle (silent fail individuel)
  try {
    await Promise.allSettled([
      _loadRejectFilms(signal),
      _loadSagas(signal),
      _loadByDecade(signal, _state.filters),
      _loadHistory(signal, _normalizePeriodDays(_state.filters.period_days)),
    ]);
  } catch (err) {
    if (err && err.name === "AbortError") return;
  }

  _rerender(container);
}

export function unmountQualite() {
  if (_state.recomputePollTimer) {
    clearInterval(_state.recomputePollTimer);
    _state.recomputePollTimer = null;
  }
  _state.recomputeJobId = null;
  _state.inspectorSection = "overview";
  _state.inspectorPayload = null;
}

/* --- Test hooks (exportés pour tests Phase 5) ------------------------ */
// Permet aux tests unitaires de vérifier l'état sans toucher au DOM.
export const __testing__ = {
  state: _state,
  TIER_ORDER: _TIER_ORDER,
  TIER_LABELS: _TIER_LABELS,
  resolveTierDist: _resolveTierDist,
  renderEvolutionChart: _renderEvolutionChart,
  formatDateFr: _formatDateFr,
  buildEvolutionCaption: _buildEvolutionCaption,
  renderRejectSection: _renderRejectSection,
  renderSagasSection: _renderSagasSection,
  renderDecadesSection: _renderDecadesSection,
  renderEvolutionSection: _renderEvolutionSection,
  renderHeader: _renderHeader,
  buildInspectorSections: _buildInspectorSections,
};
