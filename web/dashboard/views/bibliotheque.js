/* views/bibliotheque.js — Phase 5 (spec 07-bibliotheque.md) : impl complete.
 *
 * Vue Bibliotheque finalisee :
 *  - Grille de posters TMDb + chips tier (6) + chips non-tier (5)
 *  - Recherche fuzzy + 12 options de tri (6 criteres x 2 directions)
 *  - Toggle Grille / Tableau dense (headers triables + colonnes Confiance/Taille/Source)
 *  - Selection multi + 4 actions bulk reellement cablees (analyser perceptuel,
 *    re-scanner, exporter, marquer pour suppression avec dangerConfirmModal)
 *  - Scroll infini (IntersectionObserver, batch 60) avec cache local par page
 *  - Inspecteur droit (right-panel) : recap film(s) selectionne(s)
 *  - Double-clic carte/ligne -> Modal Detail (mode C, navigate /film/:id)
 *  - Drawer "Avance" : 10 filtres detailles (cf library-advanced-drawer.js)
 *
 * Endpoints consommes (PR #299) :
 *   library/get_library_filtered(filters, sort, page, page_size)
 *   library/get_library_counters_by_chip(filters)
 *   library/mark_for_deletion_bulk(row_ids)
 *   library/export_films(row_ids, format)
 *   run/rescan_rows_bulk(row_ids)
 *   quality/analyze_perceptual_batch(run_id, row_ids)  (fallback bulk)
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { dangerConfirmModal } from "../components/modal.js";
import { renderFilmDetail } from "../components/film-detail.js";
import { showToast } from "../components/toast.js";
import {
  openLibraryAdvancedDrawer,
  ADVANCED_DRAWER_DEFAULTS,
} from "../components/library-advanced-drawer.js";
import * as rightPanel from "../components/right-panel.js";

const PAGE_SIZE = 60;
const LS_VIEW = "cinesort.bibliotheque.view";
const LS_TIER = "cinesort.bibliotheque.tier";
const LS_SORT = "cinesort.bibliotheque.sort";
const LS_ADV = "cinesort.bibliotheque.advanced";

const TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
  unknown: "Non identifié",
};

const TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject", "unknown"];

// 5 chips non-tier (combinables, AND avec le tier choisi).
const NON_TIER_CHIPS = [
  { key: "subs_missing_fr", label: "Sans subs FR" },
  { key: "unidentified", label: "Non identifiés" },
  { key: "recently_modified", label: "Modifiés récemment" },
  { key: "in_duplicates", label: "Dans doublons" },
  { key: "sagas_incomplete", label: "Sagas" },
];

// 6 criteres x 2 directions = 12 options.
const SORT_OPTIONS = [
  { value: "title", label: "Titre A→Z" },
  { value: "title_desc", label: "Titre Z→A" },
  { value: "year_desc", label: "Année (récent)" },
  { value: "year_asc", label: "Année (ancien)" },
  { value: "score_desc", label: "Score (meilleur)" },
  { value: "score_asc", label: "Score (pire)" },
  { value: "duration_desc", label: "Durée (long)" },
  { value: "duration_asc", label: "Durée (court)" },
  { value: "size_desc", label: "Taille fichier (gros)" },
  { value: "size_asc", label: "Taille fichier (petit)" },
  { value: "added_desc", label: "Date d'ajout (récent)" },
  { value: "added_asc", label: "Date d'ajout (ancien)" },
];

// Mapping clic header tableau -> sort suivant (toggle asc/desc)
const TABLE_HEADER_SORTS = {
  title: ["title", "title_desc"],
  year: ["year_asc", "year_desc"],
  tier: ["score_desc", "score_asc"], // tier = proxy score (pas de sort_by_tier backend)
  confidence: ["score_desc", "score_asc"], // confidence partage le sort score
  score: ["score_desc", "score_asc"],
  resolution: ["title", "title_desc"], // pas de sort backend par resolution -> fallback titre
  size: ["size_desc", "size_asc"],
  duration: ["duration_desc", "duration_asc"],
  source: ["title", "title_desc"], // pas de sort backend par source -> fallback titre
};

/* --- State --- */

let _state = null;
let _searchDebounce = null;
let _container = null;
let _abortController = null;
let _scrollObserver = null;
let _runId = null; // dernier run_id reçu (pour appel quality/analyze_perceptual_batch)

// Drag-select rectangulaire (spec 07 §5) : etat module-scope pour permettre
// le nettoyage lors d'un unmount et eviter les leak listeners window.
const _dragSelect = {
  active: false,       // true quand le rectangle est dessine (apres seuil)
  startX: 0,           // origine pageX
  startY: 0,           // origine pageY
  startScrollX: 0,     // window.scrollX au mousedown
  startScrollY: 0,     // window.scrollY au mousedown
  baseSelection: null, // Set<string> snapshot avant drag (additif si Ctrl)
  additive: false,     // Ctrl/Cmd ou Shift au mousedown
  overlay: null,       // element DOM overlay
  rafId: 0,            // requestAnimationFrame en cours
  // Move handlers binds (pour removeEventListener fiable)
  onMove: null,
  onUp: null,
  onKey: null,
};
const DRAG_THRESHOLD_PX = 5;

function _initState() {
  let adv = { ...ADVANCED_DRAWER_DEFAULTS };
  let advActive = false;
  try {
    const raw = localStorage.getItem(LS_ADV);
    if (raw) {
      const parsed = JSON.parse(raw);
      adv = { ...adv, ...parsed };
      advActive = true;
    }
  } catch (_e) { /* noop */ }
  return {
    rows: [],
    rowsByPage: new Map(), // cache pages: Map<int, row[]>
    total: 0,
    page: 1,
    pages: 1,
    byTier: {},
    counters: {}, // 11 compteurs library/get_library_counters_by_chip
    tierFilter: localStorage.getItem(LS_TIER) || "all",
    activeChips: new Set(), // non-tier chips actifs
    search: "",
    sort: localStorage.getItem(LS_SORT) || "title",
    viewMode: localStorage.getItem(LS_VIEW) || "grid",
    selected: new Set(),
    advanced: adv,
    advancedActive: advActive,
    loading: false,
    loadingMore: false, // batch suivant (scroll infini)
    error: null,
    focusedRowId: null, // pour inspecteur droit
  };
}

/* --- Helpers --- */

function _tierBadge(tier) {
  const t = String(tier || "unknown").toLowerCase();
  const label = TIER_LABELS[t] || t;
  return `<span class="bibliotheque-tier-badge bibliotheque-tier-badge--${t}" title="Tier ${label}">${escapeHtml(label)}</span>`;
}

function _formatScore(score) {
  if (score == null || score === 0) return "—";
  return `${Math.round(score)}/100`;
}

function _formatConfidence(c) {
  if (c == null) return "—";
  const n = Number(c);
  if (!Number.isFinite(n) || n <= 0) return "—";
  return `${Math.round(n)}%`;
}

function _formatSize(bytes) {
  const n = Number(bytes || 0);
  if (!n) return "—";
  if (n >= 1024 * 1024 * 1024) return `${(n / (1024 * 1024 * 1024)).toFixed(1)} Go`;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(0)} Mo`;
  return `${n} o`;
}

function _formatSource(src) {
  const s = String(src || "").trim();
  if (!s || s === "unknown") return "—";
  return s.toUpperCase();
}

function _totalSize(rows) {
  return rows.reduce((sum, r) => sum + Number(r.size_bytes || 0), 0);
}

function _totalDuration(rows) {
  return rows.reduce((sum, r) => sum + Number(r.duration_min || 0), 0);
}

function _tierDistribution(rows) {
  const dist = {};
  rows.forEach((r) => {
    const t = String(r.tier_v2 || "unknown").toLowerCase();
    dist[t] = (dist[t] || 0) + 1;
  });
  return dist;
}

/* --- Rendering --- */

function _renderSkeleton() {
  return `
    <section class="bibliotheque-view bibliotheque-view--loading" aria-busy="true">
      <div class="bibliotheque-header"><div class="v5-skeleton bibliotheque-title-skel"></div></div>
      <div class="bibliotheque-section v5-skeleton bibliotheque-section-skel"></div>
    </section>
  `;
}

function _renderHeader() {
  const total = _state.total;
  const visible = _state.rows.length;
  return `
    <header class="bibliotheque-header">
      <div class="bibliotheque-header-top">
        <h1 class="bibliotheque-title">Bibliothèque</h1>
        <p class="bibliotheque-summary">
          <strong>${total}</strong> film${total > 1 ? "s" : ""} ·
          ${visible} chargé${visible > 1 ? "s" : ""}
        </p>
      </div>
      <div class="bibliotheque-toolbar" role="toolbar" aria-label="Actions Bibliothèque">
        <input type="search" class="v5-input bibliotheque-search"
               placeholder="🔍 Rechercher un film…"
               value="${escapeHtml(_state.search)}"
               data-bibliotheque-search>
        <select class="v5-input bibliotheque-sort" data-bibliotheque-sort aria-label="Trier">
          ${SORT_OPTIONS.map((o) => `<option value="${o.value}"${o.value === _state.sort ? " selected" : ""}>${escapeHtml(o.label)}</option>`).join("")}
        </select>
        <div class="bibliotheque-view-toggle" role="group" aria-label="Mode d'affichage">
          <button type="button"
                  class="v5-btn v5-btn--ghost${_state.viewMode === "grid" ? " is-active" : ""}"
                  data-bibliotheque-view="grid" title="Grille de posters" aria-pressed="${_state.viewMode === "grid"}">▦</button>
          <button type="button"
                  class="v5-btn v5-btn--ghost${_state.viewMode === "table" ? " is-active" : ""}"
                  data-bibliotheque-view="table" title="Tableau dense" aria-pressed="${_state.viewMode === "table"}">≡</button>
        </div>
        <button type="button" class="v5-btn v5-btn--secondary${_state.advancedActive ? " is-active" : ""}" data-bibliotheque-action="filters">▾ Avancé${_state.advancedActive ? " •" : ""}</button>
      </div>
    </header>
  `;
}

function _chipCount(key) {
  const c = _state.counters || {};
  if (key === "all") {
    // Total = somme des 6 tiers (counters sont scoped aux filters appliques).
    return TIER_ORDER.reduce((a, k) => a + (Number(c[k]) || 0), 0);
  }
  return Number(c[key] || 0);
}

function _renderTierChips() {
  const chips = [
    `<button type="button" class="bibliotheque-chip${_state.tierFilter === "all" ? " is-active" : ""}" data-bibliotheque-tier="all">
       Tous <span class="bibliotheque-chip-count">${_chipCount("all")}</span>
     </button>`,
  ];
  for (const t of TIER_ORDER) {
    const n = _chipCount(t);
    chips.push(`<button type="button"
                        class="bibliotheque-chip bibliotheque-chip--tier-${t}${_state.tierFilter === t ? " is-active" : ""}"
                        data-bibliotheque-tier="${t}">
                  ${escapeHtml(TIER_LABELS[t] || t)} <span class="bibliotheque-chip-count">${n}</span>
                </button>`);
  }
  return `
    <div class="bibliotheque-chips bibliotheque-chips--tier" role="group" aria-label="Filtres tier">
      ${chips.join("")}
    </div>
  `;
}

function _renderNonTierChips() {
  const chips = NON_TIER_CHIPS.map((c) => {
    const n = _chipCount(c.key);
    const active = _state.activeChips.has(c.key);
    return `<button type="button"
                    class="bibliotheque-chip bibliotheque-chip--nontier${active ? " is-active" : ""}"
                    data-bibliotheque-chip="${c.key}">
              ${escapeHtml(c.label)} <span class="bibliotheque-chip-count">${n}</span>
            </button>`;
  }).join("");
  return `
    <div class="bibliotheque-chips bibliotheque-chips--nontier" role="group" aria-label="Filtres complementaires">
      ${chips}
    </div>
  `;
}

function _renderBulkToolbar() {
  const n = _state.selected.size;
  if (n === 0) return "";
  return `
    <div class="bibliotheque-bulk-toolbar" role="region" aria-label="Actions groupées">
      <span class="bibliotheque-bulk-count">✓ ${n} film${n > 1 ? "s" : ""} sélectionné${n > 1 ? "s" : ""}</span>
      <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-bulk="perceptual">▶ Analyser perceptuel</button>
      <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-bulk="rescan">↻ Re-scanner</button>
      <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-bulk="export">📤 Exporter…</button>
      <button type="button" class="v5-btn v5-btn--danger" data-bibliotheque-bulk="delete">🗑 Marquer pour suppression</button>
      <button type="button" class="v5-btn v5-btn--ghost" data-bibliotheque-bulk="clear">Annuler sélection</button>
    </div>
  `;
}

function _renderFilmCard(row) {
  const rowId = String(row.row_id || "");
  const title = String(row.title || "Sans titre");
  const year = row.year ? `<span class="bibliotheque-card-year">${row.year}</span>` : "";
  const resolution = row.resolution ? `<span class="bibliotheque-card-meta">${escapeHtml(row.resolution)}</span>` : "";
  const score = _formatScore(row.score_v2);
  const warningsCount = Array.isArray(row.warnings) ? row.warnings.length : 0;
  const warningBadge = warningsCount > 0
    ? `<span class="bibliotheque-card-warn" title="${warningsCount} alerte(s)">⚠ ${warningsCount}</span>`
    : "";
  const poster = row.poster_url
    ? `<img class="bibliotheque-card-poster-img" src="${escapeHtml(row.poster_url)}" alt="${escapeHtml(title)}" loading="lazy">`
    : `<div class="bibliotheque-card-poster-placeholder" aria-hidden="true">🎬</div>`;
  const selected = _state.selected.has(rowId);
  return `
    <article class="bibliotheque-card${selected ? " is-selected" : ""}"
             data-row-id="${escapeHtml(rowId)}"
             tabindex="0"
             role="button"
             aria-pressed="${selected}"
             aria-label="${escapeHtml(title)} ${row.year || ""}">
      <div class="bibliotheque-card-poster">
        ${poster}
        ${_tierBadge(row.tier_v2)}
        ${warningBadge}
        <label class="bibliotheque-card-check" onclick="event.stopPropagation()">
          <input type="checkbox" data-bibliotheque-select="${escapeHtml(rowId)}"${selected ? " checked" : ""} aria-label="Sélectionner">
        </label>
      </div>
      <div class="bibliotheque-card-info">
        <div class="bibliotheque-card-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
        <div class="bibliotheque-card-line">
          ${year}
          ${resolution}
          <span class="bibliotheque-card-score">${score}</span>
        </div>
      </div>
    </article>
  `;
}

function _renderTableHeader() {
  const cols = [
    { key: "_sel", label: "" },
    { key: "title", label: "Titre" },
    { key: "year", label: "Année" },
    { key: "tier", label: "Tier" },
    { key: "confidence", label: "Confiance" },
    { key: "score", label: "Score" },
    { key: "resolution", label: "Résolution" },
    { key: "size", label: "Taille" },
    { key: "duration", label: "Durée" },
    { key: "source", label: "Source" },
  ];
  return `<tr>${cols.map((c) => {
    if (c.key === "_sel") return `<th aria-label="Sélection"></th>`;
    const isSortable = TABLE_HEADER_SORTS[c.key] != null;
    const [asc, desc] = TABLE_HEADER_SORTS[c.key] || [];
    const isActive = _state.sort === asc || _state.sort === desc;
    const arrow = isActive ? (_state.sort === asc ? " ▲" : " ▼") : "";
    if (!isSortable) return `<th>${escapeHtml(c.label)}</th>`;
    return `<th class="bibliotheque-table-sortable${isActive ? " is-active" : ""}" data-bibliotheque-thsort="${c.key}" tabindex="0" role="button" aria-sort="${isActive ? (_state.sort === asc ? "ascending" : "descending") : "none"}">${escapeHtml(c.label)}${arrow}</th>`;
  }).join("")}</tr>`;
}

function _renderTableRow(row) {
  const rowId = String(row.row_id || "");
  const selected = _state.selected.has(rowId);
  const warningsCount = Array.isArray(row.warnings) ? row.warnings.length : 0;
  const warn = warningsCount > 0 ? ` <span class="bibliotheque-table-warn">⚠${warningsCount}</span>` : "";
  return `
    <tr class="bibliotheque-table-row${selected ? " is-selected" : ""}" data-row-id="${escapeHtml(rowId)}">
      <td><input type="checkbox" data-bibliotheque-select="${escapeHtml(rowId)}"${selected ? " checked" : ""}></td>
      <td class="bibliotheque-table-title">${escapeHtml(row.title || "Sans titre")}${warn}</td>
      <td>${row.year || "—"}</td>
      <td>${_tierBadge(row.tier_v2)}</td>
      <td>${_formatConfidence(row.confidence)}</td>
      <td>${_formatScore(row.score_v2)}</td>
      <td>${escapeHtml(row.resolution || "—")}</td>
      <td>${_formatSize(row.size_bytes)}</td>
      <td>${row.duration_min ? `${row.duration_min} min` : "—"}</td>
      <td>${escapeHtml(_formatSource(row.proposed_source))}</td>
    </tr>
  `;
}

function _renderGrid() {
  if (_state.rows.length === 0 && !_state.loading) {
    return `
      <div class="bibliotheque-empty">
        <p>Aucun film ne correspond à ces filtres.</p>
        <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-reset>Effacer les filtres</button>
      </div>
    `;
  }
  if (_state.viewMode === "table") {
    return `
      <div class="bibliotheque-table-wrap">
        <table class="bibliotheque-table bibliotheque-table-sortable">
          <thead>${_renderTableHeader()}</thead>
          <tbody>${_state.rows.map(_renderTableRow).join("")}</tbody>
        </table>
      </div>
    `;
  }
  return `<div class="bibliotheque-grid">${_state.rows.map(_renderFilmCard).join("")}</div>`;
}

function _renderInfiniteSentinel() {
  if (_state.rows.length >= _state.total) {
    if (_state.total > 0) {
      return `<div class="bibliotheque-infinite-end">Fin de la liste (${_state.total} film${_state.total > 1 ? "s" : ""})</div>`;
    }
    return "";
  }
  return `
    <div class="bibliotheque-infinite-sentinel" data-bibliotheque-sentinel
         aria-live="polite" aria-busy="${_state.loadingMore ? "true" : "false"}">
      ${_state.loadingMore ? "Chargement…" : "Faites défiler pour charger plus"}
    </div>
  `;
}

function _renderBody() {
  if (_state.loading && _state.rows.length === 0) {
    return `<div class="bibliotheque-section bibliotheque-loading">Chargement…</div>`;
  }
  if (_state.error) {
    return `<div class="bibliotheque-section bibliotheque-error">${escapeHtml(_state.error)}</div>`;
  }
  return `
    ${_renderGrid()}
    ${_renderInfiniteSentinel()}
  `;
}

function _render() {
  if (!_container) return;
  _container.innerHTML = `
    <section class="bibliotheque-view">
      ${_renderHeader()}
      ${_renderTierChips()}
      ${_renderNonTierChips()}
      ${_renderBulkToolbar()}
      <section class="bibliotheque-section">${_renderBody()}</section>
    </section>
  `;
  _bindEvents(_container);
  _setupScrollObserver();
  _updateInspector();
}

/* --- Inspecteur droit --- */

function _updateInspector() {
  if (typeof rightPanel.setSections !== "function") return;
  const selectedIds = Array.from(_state.selected);
  // Cas selection multi : recap + agregats
  if (selectedIds.length > 1) {
    const selectedRows = _state.rows.filter((r) => _state.selected.has(String(r.row_id)));
    const totalDuration = _totalDuration(selectedRows);
    const totalSize = _totalSize(selectedRows);
    const dist = _tierDistribution(selectedRows);
    const distHtml = Object.entries(dist)
      .sort((a, b) => b[1] - a[1])
      .map(([t, n]) => `<li>${escapeHtml(TIER_LABELS[t] || t)} : <strong>${n}</strong></li>`)
      .join("");
    rightPanel.setSections([
      {
        title: `${selectedIds.length} films sélectionnés`,
        html: `
          <ul class="bibliotheque-inspector-aggregates">
            <li>Durée totale : <strong>${Math.round(totalDuration / 60)} h ${totalDuration % 60} min</strong></li>
            <li>Taille totale : <strong>${_formatSize(totalSize)}</strong></li>
          </ul>
          <h4>Distribution Tier</h4>
          <ul class="bibliotheque-inspector-tierdist">${distHtml}</ul>
          <h4>Actions suggérées</h4>
          <ul class="bibliotheque-inspector-actions">
            <li>▶ Analyser perceptuel sur ${selectedIds.length} films</li>
            <li>↻ Re-scanner ${selectedIds.length} films</li>
            <li>📤 Exporter la liste</li>
            <li>🗑 Marquer pour suppression</li>
          </ul>
        `,
      },
    ]);
    return;
  }
  // Cas selection mono : detail film focused
  const focused = selectedIds[0] || _state.focusedRowId;
  if (!focused) {
    rightPanel.reset();
    return;
  }
  const row = _state.rows.find((r) => String(r.row_id) === String(focused));
  if (!row) {
    rightPanel.reset();
    return;
  }
  // Stub FilmDetail mode A : poster + meta + alertes (le composant FilmDetail
  // est livre par un agent parallele ; en attendant on rend une carte resume).
  const poster = row.poster_url
    ? `<img class="bibliotheque-inspector-poster" src="${escapeHtml(row.poster_url)}" alt="${escapeHtml(row.title)}">`
    : `<div class="bibliotheque-inspector-poster bibliotheque-inspector-poster--placeholder">🎬</div>`;
  const warningsHtml = Array.isArray(row.warnings) && row.warnings.length > 0
    ? `<ul class="bibliotheque-inspector-warnings">${row.warnings.map((w) => `<li>⚠ ${escapeHtml(w)}</li>`).join("")}</ul>`
    : "<p class=\"bibliotheque-inspector-empty\">Aucune alerte.</p>";
  rightPanel.setSections([
    {
      title: row.title || "Film",
      html: `
        ${poster}
        <dl class="bibliotheque-inspector-meta">
          <dt>Année</dt><dd>${row.year || "—"}</dd>
          <dt>Tier</dt><dd>${_tierBadge(row.tier_v2)}</dd>
          <dt>Score</dt><dd>${_formatScore(row.score_v2)}</dd>
          <dt>Confiance</dt><dd>${_formatConfidence(row.confidence)}</dd>
          <dt>Résolution</dt><dd>${escapeHtml(row.resolution || "—")}</dd>
          <dt>Taille</dt><dd>${_formatSize(row.size_bytes)}</dd>
          <dt>Durée</dt><dd>${row.duration_min ? `${row.duration_min} min` : "—"}</dd>
          <dt>Source</dt><dd>${escapeHtml(_formatSource(row.proposed_source))}</dd>
        </dl>
        <button type="button" class="v5-btn v5-btn--primary" data-bibliotheque-inspect-open="${escapeHtml(String(row.row_id))}">Ouvrir le détail complet</button>
      `,
    },
    {
      title: "Alertes",
      html: warningsHtml,
    },
  ]);
  const openBtn = document.querySelector(`[data-bibliotheque-inspect-open]`);
  if (openBtn) {
    openBtn.addEventListener("click", () => {
      const rid = openBtn.dataset.bibliothequeInspectOpen;
      if (rid) navigateTo(`/film/${encodeURIComponent(rid)}`);
    });
  }
}

/* --- Data --- */

function _buildFilters({ includeAdvanced = true } = {}) {
  const filters = {};
  if (_state.tierFilter && _state.tierFilter !== "all") {
    filters.tier_v2 = [_state.tierFilter];
  }
  if (_state.search) {
    filters.search = _state.search;
  }
  if (_state.activeChips.size > 0) {
    filters.chips = Array.from(_state.activeChips);
  }
  if (includeAdvanced && _state.advancedActive) {
    const adv = _state.advanced || {};
    if (adv.year_min && adv.year_min > 1900) filters.year_min = adv.year_min;
    if (adv.year_max && adv.year_max < 2025) filters.year_max = adv.year_max;
    if (adv.duration_min && adv.duration_min > 0) filters.duration_min = adv.duration_min;
    if (adv.duration_max && adv.duration_max < 600) filters.duration_max = adv.duration_max;
    if (adv.size_min_gb && adv.size_min_gb > 0) filters.size_min = Math.round(adv.size_min_gb * 1024 * 1024 * 1024);
    if (adv.size_max_gb && adv.size_max_gb < 200) filters.size_max = Math.round(adv.size_max_gb * 1024 * 1024 * 1024);
    if (Array.isArray(adv.resolution) && adv.resolution.length) filters.resolution = adv.resolution;
    if (Array.isArray(adv.codec) && adv.codec.length) filters.codec = adv.codec;
    if (Array.isArray(adv.source) && adv.source.length) filters.source = adv.source;
    if (Array.isArray(adv.audio_languages) && adv.audio_languages.length) filters.audio_languages = adv.audio_languages;
    if (Array.isArray(adv.subtitle_languages) && adv.subtitle_languages.length) filters.subtitle_languages = adv.subtitle_languages;
    if (typeof adv.confidence_min === "number" && adv.confidence_min > 0) filters.confidence_min = adv.confidence_min;
    if (typeof adv.confidence_max === "number" && adv.confidence_max < 100) filters.confidence_max = adv.confidence_max;
    if (adv.added_after) {
      const t = Date.parse(adv.added_after);
      if (Number.isFinite(t)) filters.added_after = t / 1000;
    }
    if (adv.added_before) {
      const t = Date.parse(adv.added_before);
      if (Number.isFinite(t)) filters.added_before = t / 1000;
    }
  }
  return filters;
}

async function _fetchCounters() {
  // Compteurs scoped sur les filtres actifs hors tier/chips (sinon les compteurs
  // tier/chip seraient toujours egaux a la valeur du chip actif). On envoie donc
  // les filtres advanced + search mais SANS tier_v2 ni chips.
  const filters = _buildFilters({ includeAdvanced: true });
  delete filters.tier_v2;
  delete filters.chips;
  try {
    const res = await apiPost("library/get_library_counters_by_chip", { filters });
    if (!res || res.ok === false) return;
    const data = res.data || res;
    _state.counters = data.counts || {};
  } catch (_e) {
    /* silencieux : les chips affichent "0" */
  }
}

async function _fetchLibrary({ append = false } = {}) {
  if (_abortController && !append) {
    _abortController.abort();
  }
  if (!append) {
    _abortController = new AbortController();
    _state.loading = true;
    _state.error = null;
    _state.rowsByPage = new Map();
    _state.rows = [];
    _state.page = 1;
  } else {
    _state.loadingMore = true;
  }
  _render();

  const signal = _abortController ? _abortController.signal : undefined;
  const filters = _buildFilters();
  const targetPage = append ? _state.page + 1 : 1;

  if (_state.rowsByPage.has(targetPage)) {
    const cached = _state.rowsByPage.get(targetPage);
    if (append) {
      _state.rows = _state.rows.concat(cached);
      _state.page = targetPage;
    } else {
      _state.rows = cached.slice();
    }
    _state.loading = false;
    _state.loadingMore = false;
    _render();
    return;
  }

  try {
    const res = await apiPost(
      "library/get_library_filtered",
      {
        filters,
        sort: _state.sort,
        page: targetPage,
        page_size: PAGE_SIZE,
      },
      { signal },
    );
    if (!res || res.ok === false) {
      _state.error = (res && (res.message || res.error)) || "Erreur de chargement.";
      _state.loading = false;
      _state.loadingMore = false;
      _render();
      return;
    }
    const data = res.data || res;
    const newRows = data.rows || [];
    _runId = data.run_id || _runId;
    _state.total = data.total || 0;
    _state.pages = data.pages || 1;
    _state.byTier = (data.stats && data.stats.by_tier) || _state.byTier;
    _state.rowsByPage.set(targetPage, newRows);
    if (append) {
      _state.rows = _state.rows.concat(newRows);
      _state.page = targetPage;
    } else {
      _state.rows = newRows;
      _state.page = 1;
    }
    _state.loading = false;
    _state.loadingMore = false;
    _render();

    if (!append) {
      void _fetchCounters().then(() => _render());
    }
  } catch (err) {
    if (err && err.name === "AbortError") return;
    _state.error = err ? String(err.message || err) : "Erreur réseau";
    _state.loading = false;
    _state.loadingMore = false;
    _render();
  }
}

/* --- Scroll infini (IntersectionObserver) --- */

function _setupScrollObserver() {
  if (_scrollObserver) {
    _scrollObserver.disconnect();
    _scrollObserver = null;
  }
  const sentinel = _container && _container.querySelector("[data-bibliotheque-sentinel]");
  if (!sentinel) return;
  if (typeof IntersectionObserver === "undefined") return;
  _scrollObserver = new IntersectionObserver(
    (entries) => {
      const entry = entries[0];
      if (entry && entry.isIntersecting && !_state.loading && !_state.loadingMore) {
        if (_state.rows.length < _state.total) {
          void _fetchLibrary({ append: true });
        }
      }
    },
    { root: null, rootMargin: "120px", threshold: 0.1 },
  );
  _scrollObserver.observe(sentinel);
}

/* --- Drag-select rectangulaire (spec 07 §5) ---
 *
 * Comportement :
 *  - mousedown sur la grille en dehors d'une carte demarre un drag
 *  - mousemove > DRAG_THRESHOLD_PX dessine l'overlay et met a jour la selection
 *  - mouseup commit la selection (carte intersectee => _state.selected)
 *  - Esc annule (restaure baseSelection, supprime overlay)
 *  - Ctrl/Cmd ou Shift au mousedown : drag additif (preserve la selection)
 *  - Seuil de 5px : protege le clic simple / double-clic sur carte
 */

function _resetDragSelect() {
  if (_dragSelect.overlay && _dragSelect.overlay.parentNode) {
    _dragSelect.overlay.parentNode.removeChild(_dragSelect.overlay);
  }
  if (_dragSelect.rafId) {
    cancelAnimationFrame(_dragSelect.rafId);
    _dragSelect.rafId = 0;
  }
  if (_dragSelect.onMove) {
    window.removeEventListener("mousemove", _dragSelect.onMove);
  }
  if (_dragSelect.onUp) {
    window.removeEventListener("mouseup", _dragSelect.onUp);
  }
  if (_dragSelect.onKey) {
    window.removeEventListener("keydown", _dragSelect.onKey);
  }
  _dragSelect.active = false;
  _dragSelect.overlay = null;
  _dragSelect.onMove = null;
  _dragSelect.onUp = null;
  _dragSelect.onKey = null;
  _dragSelect.baseSelection = null;
}

function _dragSelectRect(curX, curY) {
  const x1 = Math.min(_dragSelect.startX, curX);
  const y1 = Math.min(_dragSelect.startY, curY);
  const x2 = Math.max(_dragSelect.startX, curX);
  const y2 = Math.max(_dragSelect.startY, curY);
  return { left: x1, top: y1, right: x2, bottom: y2, width: x2 - x1, height: y2 - y1 };
}

function _dragSelectApplyOverlay(rect) {
  if (!_dragSelect.overlay) return;
  const o = _dragSelect.overlay;
  // L'overlay est en position fixed -> coords viewport (rect en pageX/pageY).
  o.style.left = `${rect.left - window.scrollX}px`;
  o.style.top = `${rect.top - window.scrollY}px`;
  o.style.width = `${rect.width}px`;
  o.style.height = `${rect.height}px`;
}

function _dragSelectIntersect(rect) {
  // rect est en coords page (pageX/pageY). getBoundingClientRect retourne du
  // viewport -> on convertit en page en ajoutant scrollX/scrollY.
  if (!_container) return;
  const cards = _container.querySelectorAll(".bibliotheque-card[data-row-id]");
  const base = _dragSelect.baseSelection || new Set();
  // Reconstruit selection a partir de base + cartes intersectees.
  const next = new Set(base);
  cards.forEach((card) => {
    const cr = card.getBoundingClientRect();
    const cardLeft = cr.left + window.scrollX;
    const cardTop = cr.top + window.scrollY;
    const cardRight = cardLeft + cr.width;
    const cardBottom = cardTop + cr.height;
    const intersects = !(
      cardRight < rect.left ||
      cardLeft > rect.right ||
      cardBottom < rect.top ||
      cardTop > rect.bottom
    );
    const rowId = card.dataset.rowId;
    if (!rowId) return;
    if (intersects) {
      next.add(rowId);
      card.classList.add("is-selected");
      card.setAttribute("aria-pressed", "true");
    } else if (!base.has(rowId)) {
      // Pas dans le rectangle et pas dans la base -> retire l'effet visuel.
      card.classList.remove("is-selected");
      card.setAttribute("aria-pressed", "false");
    }
  });
  _state.selected = next;
}

function _onDragSelectMouseDown(ev) {
  // Bouton gauche uniquement, pas sur une carte/input/bouton/etc.
  if (ev.button !== 0) return;
  // Si le clic est sur (ou descend d') une carte, un input, ou un bouton, on
  // laisse le comportement natif (clic carte, checkbox, etc.) prendre le pas.
  const target = ev.target;
  if (!target || typeof target.closest !== "function") return;
  if (
    target.closest(".bibliotheque-card") ||
    target.closest("input") ||
    target.closest("button") ||
    target.closest("a") ||
    target.closest("label")
  ) {
    return;
  }
  const grid = _container && _container.querySelector(".bibliotheque-grid");
  if (!grid || !grid.contains(target)) return;

  _dragSelect.startX = ev.pageX;
  _dragSelect.startY = ev.pageY;
  _dragSelect.startScrollX = window.scrollX;
  _dragSelect.startScrollY = window.scrollY;
  _dragSelect.additive = !!(ev.ctrlKey || ev.metaKey || ev.shiftKey);
  _dragSelect.baseSelection = _dragSelect.additive
    ? new Set(_state.selected)
    : new Set();
  _dragSelect.active = false; // bascule a true apres franchissement du seuil

  _dragSelect.onMove = (mv) => _onDragSelectMouseMove(mv);
  _dragSelect.onUp = (mu) => _onDragSelectMouseUp(mu);
  _dragSelect.onKey = (kv) => _onDragSelectKey(kv);
  window.addEventListener("mousemove", _dragSelect.onMove);
  window.addEventListener("mouseup", _dragSelect.onUp);
  window.addEventListener("keydown", _dragSelect.onKey);
}

function _onDragSelectMouseMove(ev) {
  const dx = ev.pageX - _dragSelect.startX;
  const dy = ev.pageY - _dragSelect.startY;
  if (!_dragSelect.active) {
    if (Math.abs(dx) < DRAG_THRESHOLD_PX && Math.abs(dy) < DRAG_THRESHOLD_PX) return;
    _dragSelect.active = true;
    // Cree l'overlay au franchissement du seuil seulement (evite flash sur clic simple).
    const overlay = document.createElement("div");
    overlay.className = "bibliotheque-drag-overlay";
    overlay.setAttribute("aria-hidden", "true");
    overlay.style.position = "fixed";
    overlay.style.pointerEvents = "none";
    overlay.style.zIndex = "9999";
    document.body.appendChild(overlay);
    _dragSelect.overlay = overlay;
    // Empeche la selection de texte pendant le drag.
    document.body.style.userSelect = "none";
  }
  if (_dragSelect.rafId) cancelAnimationFrame(_dragSelect.rafId);
  _dragSelect.rafId = requestAnimationFrame(() => {
    const rect = _dragSelectRect(ev.pageX, ev.pageY);
    _dragSelectApplyOverlay(rect);
    _dragSelectIntersect(rect);
  });
}

function _onDragSelectMouseUp(ev) {
  const wasActive = _dragSelect.active;
  if (wasActive) {
    // Commit final : recalcule a la position finale.
    const rect = _dragSelectRect(ev.pageX, ev.pageY);
    _dragSelectIntersect(rect);
  }
  document.body.style.userSelect = "";
  _resetDragSelect();
  if (wasActive) {
    // Re-render uniquement si un drag effectif a eu lieu (pour rafraichir la
    // bulk toolbar et l'inspecteur droit). Pas de re-render pour un clic simple
    // -> evite de casser le double-clic sur carte.
    _render();
  }
}

function _onDragSelectKey(ev) {
  if (ev.key === "Escape" && _dragSelect.active) {
    // Restaure la base selection.
    if (_dragSelect.baseSelection) {
      _state.selected = new Set(_dragSelect.baseSelection);
    } else {
      _state.selected = new Set();
    }
    document.body.style.userSelect = "";
    _resetDragSelect();
    _render();
  }
}

/* --- Event handlers --- */

function _bindEvents(container) {
  const retryBtn = container.querySelector("[data-bibliotheque-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initBibliotheque(container));

  const resetBtn = container.querySelector("[data-bibliotheque-reset]");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      _state.tierFilter = "all";
      _state.search = "";
      _state.activeChips.clear();
      _state.advancedActive = false;
      _state.advanced = { ...ADVANCED_DRAWER_DEFAULTS };
      localStorage.setItem(LS_TIER, "all");
      localStorage.removeItem(LS_ADV);
      _fetchLibrary();
    });
  }

  const search = container.querySelector("[data-bibliotheque-search]");
  if (search) {
    search.addEventListener("input", (ev) => {
      const val = ev.target.value || "";
      if (_searchDebounce) clearTimeout(_searchDebounce);
      _searchDebounce = setTimeout(() => {
        _state.search = val.trim();
        _fetchLibrary();
      }, 250);
    });
  }

  const sort = container.querySelector("[data-bibliotheque-sort]");
  if (sort) {
    sort.addEventListener("change", (ev) => {
      _state.sort = ev.target.value || "title";
      localStorage.setItem(LS_SORT, _state.sort);
      _fetchLibrary();
    });
  }

  container.querySelectorAll("[data-bibliotheque-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.viewMode = btn.dataset.bibliothequeView;
      localStorage.setItem(LS_VIEW, _state.viewMode);
      _render();
    });
  });

  container.querySelectorAll("[data-bibliotheque-tier]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.tierFilter = btn.dataset.bibliothequeTier;
      localStorage.setItem(LS_TIER, _state.tierFilter);
      _fetchLibrary();
    });
  });

  container.querySelectorAll("[data-bibliotheque-chip]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.bibliothequeChip;
      if (_state.activeChips.has(key)) _state.activeChips.delete(key);
      else _state.activeChips.add(key);
      _fetchLibrary();
    });
  });

  container.querySelectorAll("[data-bibliotheque-thsort]").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.bibliothequeThsort;
      const pair = TABLE_HEADER_SORTS[col];
      if (!pair) return;
      const [asc, desc] = pair;
      _state.sort = _state.sort === asc ? desc : asc;
      localStorage.setItem(LS_SORT, _state.sort);
      _fetchLibrary();
    });
  });

  container.querySelectorAll("[data-bibliotheque-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const action = btn.dataset.bibliothequeAction;
      if (action === "filters") {
        openLibraryAdvancedDrawer({
          initial: _state.advanced,
          onApply: (drawerState) => {
            _state.advanced = drawerState;
            _state.advancedActive = true;
            try { localStorage.setItem(LS_ADV, JSON.stringify(drawerState)); } catch (_e) { /* noop */ }
            _fetchLibrary();
          },
          onReset: () => {
            _state.advanced = { ...ADVANCED_DRAWER_DEFAULTS };
            _state.advancedActive = false;
            try { localStorage.removeItem(LS_ADV); } catch (_e) { /* noop */ }
            _fetchLibrary();
          },
        });
      }
    });
  });

  container.querySelectorAll("[data-bibliotheque-select]").forEach((checkbox) => {
    checkbox.addEventListener("click", (ev) => ev.stopPropagation());
    checkbox.addEventListener("change", (ev) => {
      const rowId = ev.target.dataset.bibliothequeSelect;
      if (ev.target.checked) _state.selected.add(rowId);
      else _state.selected.delete(rowId);
      _render();
    });
  });

  // Spec 06 : clic carte -> mode A (inspecteur droit), double-clic -> mode C (overlay).
  container.querySelectorAll(".bibliotheque-card").forEach((card) => {
    card.addEventListener("click", () => {
      const rowId = card.dataset.rowId;
      if (rowId) renderFilmDetail({ mode: "A", rowId });
    });
    card.addEventListener("dblclick", () => {
      const rowId = card.dataset.rowId;
      if (rowId) renderFilmDetail({ mode: "C", rowId });
      if (rowId) {
        // Clic simple : focus inspecteur (cf spec 06 mode A)
        _state.focusedRowId = rowId;
        _updateInspector();
      }
    });
    card.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      const rowId = card.dataset.rowId;
      if (rowId) _openFilmDetailModal(rowId);
    });
    card.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        const rowId = card.dataset.rowId;
        if (rowId) renderFilmDetail({ mode: "A", rowId });
        if (rowId) {
          _state.focusedRowId = rowId;
          _updateInspector();
        }
      } else if (ev.key === " ") {
        ev.preventDefault();
        const rowId = card.dataset.rowId;
        if (rowId) {
          if (_state.selected.has(rowId)) _state.selected.delete(rowId);
          else _state.selected.add(rowId);
          _render();
        }
      }
    });
  });

  container.querySelectorAll(".bibliotheque-table-row").forEach((tr) => {
    tr.addEventListener("click", (ev) => {
      if (ev.target.tagName === "INPUT") return;
      const rowId = tr.dataset.rowId;
      if (rowId) renderFilmDetail({ mode: "A", rowId });
    });
    tr.addEventListener("dblclick", (ev) => {
      if (ev.target.tagName === "INPUT") return;
      const rowId = tr.dataset.rowId;
      if (rowId) renderFilmDetail({ mode: "C", rowId });
      if (rowId) {
        _state.focusedRowId = rowId;
        _updateInspector();
      }
    });
    tr.addEventListener("dblclick", () => {
      const rowId = tr.dataset.rowId;
      if (rowId) _openFilmDetailModal(rowId);
    });
    tr.addEventListener("mouseenter", () => {
      const rowId = tr.dataset.rowId;
      if (rowId) {
        _state.focusedRowId = rowId;
        _updateInspector();
      }
    });
  });

  container.querySelectorAll("[data-bibliotheque-bulk]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.bibliothequeBulk;
      if (action === "clear") {
        _state.selected.clear();
        _render();
        return;
      }
      _handleBulkAction(action);
    });
  });

  // Drag-select rectangulaire (spec 07 §5) : un seul listener sur la grille,
  // les listeners window sont (re)installes au mousedown via _onDragSelectMouseDown.
  const grid = container.querySelector(".bibliotheque-grid");
  if (grid) {
    grid.addEventListener("mousedown", _onDragSelectMouseDown);
  }
}

function _openFilmDetailModal(rowId) {
  // Mode C : overlay (Modal Film). Fallback navigate /film/:id si la modal n'est
  // pas encore livree par l'agent parallele.
  navigateTo(`/film/${encodeURIComponent(rowId)}`);
}

/* --- Bulk actions cablees --- */

function _handleBulkAction(action) {
  const ids = Array.from(_state.selected);
  if (ids.length === 0) return;
  if (action === "delete") {
    _confirmBulkDelete(ids);
    return;
  }
  if (action === "perceptual") {
    void _bulkPerceptual(ids);
    return;
  }
  if (action === "rescan") {
    void _bulkRescan(ids);
    return;
  }
  if (action === "export") {
    void _bulkExport(ids);
    return;
  }
}

async function _bulkPerceptual(rowIds) {
  if (!_runId) {
    showToast({ type: "warn", text: "Aucun run actif." });
    return;
  }
  try {
    const res = await apiPost("quality/analyze_perceptual_batch", {
      run_id: _runId,
      row_ids: rowIds,
    });
    if (res && res.ok !== false) {
      showToast({ type: "success", text: `Analyse perceptuelle lancée sur ${rowIds.length} films.` });
    } else {
      showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur perceptuelle." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
  }
}

async function _bulkRescan(rowIds) {
  try {
    const res = await apiPost("run/rescan_rows_bulk", { row_ids: rowIds });
    if (res && res.ok !== false) {
      const jobId = res.job_id || (res.data && res.data.job_id) || "?";
      showToast({ type: "success", text: `Re-scan lancé (job ${jobId}) sur ${rowIds.length} films.` });
    } else {
      showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur re-scan." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
  }
}

async function _bulkExport(rowIds) {
  try {
    const res = await apiPost("library/export_films", { row_ids: rowIds, format: "csv" });
    if (res && res.ok !== false) {
      const filePath = res.file_path || (res.data && res.data.file_path);
      showToast({
        type: "success",
        text: filePath
          ? `Export CSV de ${rowIds.length} films : ${filePath}`
          : `Export CSV de ${rowIds.length} films terminé.`,
        duration: 8000,
      });
    } else {
      showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur export." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
  }
}

function _confirmBulkDelete(rowIds) {
  // P0 #233 : dangerConfirmModal (au lieu de window.confirm legacy + alert > 50).
  // La modale gere elle-meme : items 5 max visibles + "et N autres", countdown
  // anti-clic-reflexe 3s si bulk > 50.
  const n = rowIds.length;
  const items = rowIds.map((id) => {
    const r = _state.rows.find((row) => String(row.row_id) === String(id));
    return r ? `${r.title}${r.year ? ` (${r.year})` : ""}` : String(id);
  });
  dangerConfirmModal({
    title: `Confirmer la suppression de ${n} film${n > 1 ? "s" : ""} ?`,
    items,
    consequence:
      "Ils seront déplacés vers _user_marked_for_deletion/ au prochain apply (réversible via Undo).",
    countdownSeconds: n > 50 ? 3 : 0,
    confirmLabel: "✗ Confirmer la suppression",
    onConfirm: async () => {
      try {
        const res = await apiPost("library/mark_for_deletion_bulk", { row_ids: rowIds });
        if (res && res.ok !== false) {
          showToast({
            type: "success",
            text: `${n} film${n > 1 ? "s" : ""} marqué${n > 1 ? "s" : ""} pour suppression.`,
          });
          _state.selected.clear();
          _fetchLibrary();
        } else {
          showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur marquage." });
        }
      } catch (err) {
        showToast({ type: "error", text: String(err && err.message ? err.message : err) });
      }
    },
  });
}

/* --- Entrypoint --- */

export async function initBibliotheque(container) {
  if (!container) return;
  _container = container;
  _state = _initState();
  _state.loading = true;
  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;
  void signal;
  await _fetchLibrary();
}

export function unmountBibliotheque() {
  if (_abortController) {
    try { _abortController.abort(); } catch (_e) { /* noop */ }
    _abortController = null;
  }
  if (_searchDebounce) {
    clearTimeout(_searchDebounce);
    _searchDebounce = null;
  }
  if (_scrollObserver) {
    _scrollObserver.disconnect();
    _scrollObserver = null;
  }
  // Drag-select : nettoyage listeners window + overlay residuel.
  _resetDragSelect();
  document.body.style.userSelect = "";
  _container = null;
  _state = null;
}
