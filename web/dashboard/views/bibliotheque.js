/* views/bibliotheque.js — Phase 5 (spec 07-bibliotheque.md) : impl complete.
 *
 * Vue Bibliotheque finalisee :
 *  - Grille de posters TMDb + chips tier (6) + chips non-tier (5)
 *  - Recherche fuzzy + 12 options de tri (6 criteres x 2 directions)
 *  - Toggle Grille / Tableau dense (headers triables + colonnes Confiance/Taille/Source)
 *  - Selection multi + 5 actions bulk reellement cablees (analyser perceptuel,
 *    re-scanner, recharger posters TMDb, exporter, marquer pour suppression avec dangerConfirmModal)
 *  - Scroll infini (IntersectionObserver, batch 60) avec cache local par page
 *  - Inspecteur droit (right-panel) : recap film(s) selectionne(s)
 *  - Double-clic carte/ligne -> Modal Detail (mode C, navigate /film/:id)
 *  - Drawer "Avance" : 10 filtres detailles (cf library-advanced-drawer.js)
 *  - Smart Playlists (issue #350) : panneau discret save/list/delete des filtres
 *
 * Endpoints consommes (PR #299) :
 *   library/get_library_filtered(filters, sort, page, page_size)
 *   library/get_library_counters_by_chip(filters)
 *   library/mark_for_deletion_bulk(row_ids)
 *   library/export_films(row_ids, format)
 *   run/rescan_rows_bulk(row_ids)
 *   quality/analyze_perceptual_batch(run_id, row_ids)  (fallback bulk)
 *
 * Endpoints consommes (sprint orphelins #350) :
 *   library/get_smart_playlists()
 *   library/save_smart_playlist(name, filters)
 *   library/delete_smart_playlist(playlist_id)
 *   integrations/get_tmdb_posters(tmdb_ids, size) — recharger posters batch
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { dangerConfirmModal, showModal, closeModal } from "../components/modal.js";
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
let _abortController = null;      // AbortController des fetchs library/* (lifecycle data)
let _eventsController = null;     // AbortController des listeners DOM (lifecycle vue)
let _eventsBound = false;         // garde idempotence delegation container-level
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
    // Smart playlists (issue #350) : presets backend + custom utilisateur.
    playlists: [],
    playlistsLoaded: false,
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
      <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-bulk="refresh-posters" title="Recharger les posters TMDb">🖼 Posters TMDb</button>
      <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-bulk="export">📤 Exporter…</button>
      <button type="button" class="v5-btn v5-btn--danger" data-bibliotheque-bulk="delete">🗑 Marquer pour suppression</button>
      <button type="button" class="v5-btn v5-btn--ghost" data-bibliotheque-bulk="clear">Annuler sélection</button>
    </div>
  `;
}

/* --- Smart playlists (sprint orphelins #350) ---
 *
 * Panneau discret sous les chips qui :
 *  - Liste les playlists presets backend + custom utilisateur (lecture seule
 *    pour les presets, X pour supprimer les custom).
 *  - Bouton "Enregistrer les filtres actuels" qui demande un nom et persiste
 *    via save_smart_playlist(name, filters_current).
 *  - Clic sur une playlist applique ses filtres (tier_v2 -> tierFilter,
 *    warnings -> activeChips, year_min/max -> advanced).
 *
 * Pas un Drawer car les playlists sont fonctionnelles plus que prominentes :
 * un summary collapsible suffit pour ne pas voler de pixels au workflow
 * principal.
 */

function _renderPlaylistsPanel() {
  const list = Array.isArray(_state.playlists) ? _state.playlists : [];
  const itemsHtml = list.length === 0
    ? `<li class="bibliotheque-playlist-empty">Aucune playlist enregistrée. Appliquez des filtres puis cliquez sur Enregistrer.</li>`
    : list.map((p) => {
        const id = String(p.id || "");
        const name = String(p.name || "Sans nom");
        const isPreset = !!p.preset || id.startsWith("_preset_");
        const cls = `bibliotheque-playlist${isPreset ? " bibliotheque-playlist--preset" : " bibliotheque-playlist--custom"}`;
        const deleteBtn = isPreset
          ? ""
          : `<button type="button"
                       class="bibliotheque-playlist-delete"
                       data-bibliotheque-playlist-delete="${escapeHtml(id)}"
                       title="Supprimer cette playlist"
                       aria-label="Supprimer ${escapeHtml(name)}">×</button>`;
        return `
          <li class="${cls}">
            <button type="button"
                    class="bibliotheque-playlist-apply"
                    data-bibliotheque-playlist-apply="${escapeHtml(id)}"
                    title="Appliquer les filtres de cette playlist">
              ${isPreset ? "★" : "▸"} ${escapeHtml(name)}
            </button>
            ${deleteBtn}
          </li>
        `;
      }).join("");
  return `
    <details class="bibliotheque-playlists" data-bibliotheque-playlists-panel>
      <summary class="bibliotheque-playlists-summary">
        <span class="bibliotheque-playlists-icon" aria-hidden="true">📌</span>
        <span class="bibliotheque-playlists-label">Playlists enregistrées</span>
        <span class="bibliotheque-playlists-count">(${list.length})</span>
      </summary>
      <div class="bibliotheque-playlists-body">
        <ul class="bibliotheque-playlists-list" role="list">
          ${itemsHtml}
        </ul>
        <div class="bibliotheque-playlists-actions">
          <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-bibliotheque-playlist-save>
            💾 Enregistrer les filtres actuels
          </button>
        </div>
      </div>
    </details>
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
      ${_renderPlaylistsPanel()}
      ${_renderBulkToolbar()}
      <section class="bibliotheque-section">${_renderBody()}</section>
    </section>
  `;
  // Audit C17 P0 #7 : _bindEvents() est idempotent (delegation sur container,
  // les listeners survivent a innerHTML). Seul _bindGridDragSelect() est
  // re-execute par render car la grille est recreee.
  _bindEvents(_container);
  _bindGridDragSelect();
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
  // Cas selection mono : delegue au composant FilmDetail mode A (spec 06).
  // Le composant gere lui-meme : mount dans right-panel, poster + meta + score
  // V2 + alertes + candidats TMDb + onglets + actions. Plus de rendu local.
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
  // renderFilmDetail mode A : pas besoin de container, le composant cree son
  // propre mount data-film-detail-mount dans la section right-panel via
  // setSections (cf components/film-detail.js::_ensureModeAContainer).
  void renderFilmDetail({
    mode: "A",
    rowId: String(row.row_id),
    runId: _runId || null,
  });
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

/* --- Event delegation (audit C17 P0 #7) ---
 *
 * Avant : 12 boucles container.querySelectorAll(...).forEach(addEventListener)
 * a chaque _render() -> DOM thrashing sur 10k films.
 *
 * Apres : 6 listeners poses UNE SEULE FOIS sur container (lifecycle vue), qui
 * dispatchent via evt.target.closest("[data-X]"). _render() recree le sous-arbre
 * via innerHTML mais les listeners sur container survivent. Cleanup au unmount
 * via _eventsController.abort().
 *
 * data-bibliotheque-search/sort restent direct (input/select uniques) car le
 * gain de delegation est negligeable mais on les attache aussi au container
 * pour beneficier de l'AbortController unique.
 */

function _bindEvents(container) {
  // Listeners sur container = poses 1 seule fois par mount (delegation).
  // Sont conserves entre les _render() puisque _container.innerHTML ne touche
  // que les enfants. Toggle via _eventsBound pour idempotence.
  if (_eventsBound) return;
  _eventsBound = true;

  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;

  // --- click delegation ----------------------------------------------------
  container.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!t || typeof t.closest !== "function") return;

    // Retry button
    if (t.closest("[data-bibliotheque-retry]")) {
      initBibliotheque(container);
      return;
    }
    // Reset filters
    if (t.closest("[data-bibliotheque-reset]")) {
      _state.tierFilter = "all";
      _state.search = "";
      _state.activeChips.clear();
      _state.advancedActive = false;
      _state.advanced = { ...ADVANCED_DRAWER_DEFAULTS };
      localStorage.setItem(LS_TIER, "all");
      localStorage.removeItem(LS_ADV);
      _fetchLibrary();
      return;
    }
    // Toggle vue grille/tableau
    const viewBtn = t.closest("[data-bibliotheque-view]");
    if (viewBtn) {
      _state.viewMode = viewBtn.dataset.bibliothequeView;
      localStorage.setItem(LS_VIEW, _state.viewMode);
      _render();
      return;
    }
    // Filtre tier
    const tierBtn = t.closest("[data-bibliotheque-tier]");
    if (tierBtn) {
      _state.tierFilter = tierBtn.dataset.bibliothequeTier;
      localStorage.setItem(LS_TIER, _state.tierFilter);
      _fetchLibrary();
      return;
    }
    // Chip non-tier
    const chipBtn = t.closest("[data-bibliotheque-chip]");
    if (chipBtn) {
      const key = chipBtn.dataset.bibliothequeChip;
      if (_state.activeChips.has(key)) _state.activeChips.delete(key);
      else _state.activeChips.add(key);
      _fetchLibrary();
      return;
    }
    // Tri colonne tableau
    const thBtn = t.closest("[data-bibliotheque-thsort]");
    if (thBtn) {
      const col = thBtn.dataset.bibliothequeThsort;
      const pair = TABLE_HEADER_SORTS[col];
      if (!pair) return;
      const [asc, desc] = pair;
      _state.sort = _state.sort === asc ? desc : asc;
      localStorage.setItem(LS_SORT, _state.sort);
      _fetchLibrary();
      return;
    }
    // Action drawer (filtres avances)
    const actBtn = t.closest("[data-bibliotheque-action]");
    if (actBtn) {
      ev.preventDefault();
      const action = actBtn.dataset.bibliothequeAction;
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
      return;
    }
    // Checkbox selection : stopPropagation pour eviter le focus inspecteur
    if (t.closest("[data-bibliotheque-select]")) {
      ev.stopPropagation();
      return;
    }
    // Smart playlists (issue #350) : apply / delete / save
    const applyPlaylistBtn = t.closest("[data-bibliotheque-playlist-apply]");
    if (applyPlaylistBtn) {
      _applyPlaylist(applyPlaylistBtn.dataset.bibliothequePlaylistApply);
      return;
    }
    const deletePlaylistBtn = t.closest("[data-bibliotheque-playlist-delete]");
    if (deletePlaylistBtn) {
      ev.preventDefault();
      ev.stopPropagation();
      _confirmDeletePlaylist(deletePlaylistBtn.dataset.bibliothequePlaylistDelete);
      return;
    }
    if (t.closest("[data-bibliotheque-playlist-save]")) {
      _promptSavePlaylist();
      return;
    }

    // Bulk action
    const bulkBtn = t.closest("[data-bibliotheque-bulk]");
    if (bulkBtn) {
      const action = bulkBtn.dataset.bibliothequeBulk;
      if (action === "clear") {
        _state.selected.clear();
        _render();
        return;
      }
      _handleBulkAction(action);
      return;
    }
    // Carte film : focus inspecteur (Spec 06)
    const card = t.closest(".bibliotheque-card");
    if (card && card.dataset.rowId) {
      _state.focusedRowId = card.dataset.rowId;
      _updateInspector();
      return;
    }
    // Ligne tableau : focus inspecteur (sauf clic sur input checkbox)
    const tr = t.closest(".bibliotheque-table-row");
    if (tr && t.tagName !== "INPUT" && tr.dataset.rowId) {
      _state.focusedRowId = tr.dataset.rowId;
      _updateInspector();
    }
  }, opts);

  // --- dblclick delegation -------------------------------------------------
  container.addEventListener("dblclick", (ev) => {
    const t = ev.target;
    if (!t || typeof t.closest !== "function") return;
    const card = t.closest(".bibliotheque-card");
    if (card && card.dataset.rowId) {
      ev.preventDefault();
      renderFilmDetail({ mode: "C", rowId: card.dataset.rowId, runId: _runId || null });
      return;
    }
    const tr = t.closest(".bibliotheque-table-row");
    if (tr && t.tagName !== "INPUT" && tr.dataset.rowId) {
      renderFilmDetail({ mode: "C", rowId: tr.dataset.rowId, runId: _runId || null });
    }
  }, opts);

  // --- keydown delegation (cartes : Enter focus, Space toggle select) ------
  container.addEventListener("keydown", (ev) => {
    const t = ev.target;
    if (!t || typeof t.closest !== "function") return;
    const card = t.closest(".bibliotheque-card");
    if (!card || !card.dataset.rowId) return;
    const rowId = card.dataset.rowId;
    if (ev.key === "Enter") {
      _state.focusedRowId = rowId;
      _updateInspector();
    } else if (ev.key === " ") {
      ev.preventDefault();
      if (_state.selected.has(rowId)) _state.selected.delete(rowId);
      else _state.selected.add(rowId);
      _render();
    }
  }, opts);

  // --- mouseover delegation (table-row : hover focus inspecteur) -----------
  // mouseenter ne bubble pas -> mouseover + closest gere le hover en delegation.
  // Fix audit 2026-05-24 : throttle via requestAnimationFrame pour eviter le
  // flood d'updates inspector quand la souris balaye rapidement la table
  // (mouseover fire a chaque pixel). 1 update / frame max suffit largement.
  let _hoverRaf = null;
  container.addEventListener("mouseover", (ev) => {
    if (_hoverRaf) return;
    const t = ev.target;
    if (!t || typeof t.closest !== "function") return;
    _hoverRaf = requestAnimationFrame(() => {
      _hoverRaf = null;
      const tr = t.closest(".bibliotheque-table-row");
      if (!tr || !tr.dataset.rowId) return;
      // Anti-flood : ne refocus que si on change de ligne.
      if (_state.focusedRowId === tr.dataset.rowId) return;
      _state.focusedRowId = tr.dataset.rowId;
      _updateInspector();
    });
  }, opts);

  // --- input delegation (search debounced) ---------------------------------
  container.addEventListener("input", (ev) => {
    const inp = ev.target.closest && ev.target.closest("[data-bibliotheque-search]");
    if (!inp) return;
    const val = inp.value || "";
    if (_searchDebounce) clearTimeout(_searchDebounce);
    _searchDebounce = setTimeout(() => {
      _state.search = val.trim();
      _fetchLibrary();
    }, 250);
  }, opts);

  // --- change delegation (sort select + checkbox selection) ----------------
  container.addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t || typeof t.closest !== "function") return;
    const sort = t.closest("[data-bibliotheque-sort]");
    if (sort) {
      _state.sort = sort.value || "title";
      localStorage.setItem(LS_SORT, _state.sort);
      _fetchLibrary();
      return;
    }
    const check = t.closest("[data-bibliotheque-select]");
    if (check) {
      const rowId = check.dataset.bibliothequeSelect;
      if (check.checked) _state.selected.add(rowId);
      else _state.selected.delete(rowId);
      _render();
    }
  }, opts);

}

/**
 * Bind direct du listener mousedown sur .bibliotheque-grid (drag-select).
 *
 * La grille est recreee a chaque _render() (innerHTML), donc on re-bind. Mais
 * grace au signal partage de _eventsController, tous les listeners poses entre
 * deux renders sont abort()es au unmount (pas de leak).
 * Pas un point chaud perf : 1 seul listener, pas une boucle sur N elements.
 */
function _bindGridDragSelect() {
  if (!_container) return;
  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;
  const grid = _container.querySelector(".bibliotheque-grid");
  if (grid) {
    grid.addEventListener("mousedown", _onDragSelectMouseDown, opts);
  }
}

/* --- Bulk actions cablees --- */

function _handleBulkAction(action) {
  const ids = Array.from(_state.selected);
  if (ids.length === 0) return;
  // Fix audit 2026-05-24 : avant aucun disable -> double-clic = 2 appels backend
  // en parallele (perceptual lance 2x, posters refresh 2x, delete affiche 2 modales).
  // Maintenant : disable tous les boutons bulk pendant l'action async, restore au fin.
  if (_state.bulkInFlight) {
    return; // ignore le 2eme click pendant que le 1er est en cours
  }
  _state.bulkInFlight = true;
  const bulkBtns = Array.from(document.querySelectorAll("[data-biblio-bulk-action]"));
  bulkBtns.forEach((b) => { b.disabled = true; b.dataset.bulkPending = "1"; });
  const release = () => {
    _state.bulkInFlight = false;
    bulkBtns.forEach((b) => { b.disabled = false; delete b.dataset.bulkPending; });
  };

  const wrap = (promise) => promise.finally(release);

  if (action === "delete") {
    // delete passe par une modale + confirmation ; le release est fait dans
    // _confirmBulkDelete via onConfirm/onCancel (cf signature).
    _confirmBulkDelete(ids, release);
    return;
  }
  if (action === "perceptual") {
    void wrap(_bulkPerceptual(ids));
    return;
  }
  if (action === "rescan") {
    void wrap(_bulkRescan(ids));
    return;
  }
  if (action === "export") {
    void wrap(_bulkExport(ids));
    return;
  }
  if (action === "refresh-posters") {
    void wrap(_bulkRefreshPosters(ids));
    return;
  }
  // Action inconnue : release immediat pour eviter blocage permanent.
  release();
}

/* Sprint orphelins #350 : recharger les posters TMDb des films selectionnes.
 *
 * On collecte les tmdb_id presents (les films non-identifies sont ignores), on
 * appelle integrations/get_tmdb_posters(tmdb_ids, size="w185") et on patche les
 * rows en memoire avec les nouveaux poster_url. Pas de re-fetch library.
 *
 * Pas d'UI gallery a ce stade (cf consigne issue #350 : un bouton simple suffit).
 */
async function _bulkRefreshPosters(rowIds) {
  // Mapping rowId -> tmdb_id et inverse pour le patch d'apres reponse.
  const tmdbByRow = new Map();
  rowIds.forEach((rid) => {
    const r = _state.rows.find((row) => String(row.row_id) === String(rid));
    if (r && r.tmdb_id) {
      const tid = parseInt(r.tmdb_id, 10);
      if (Number.isFinite(tid) && tid > 0) tmdbByRow.set(String(rid), tid);
    }
  });
  if (tmdbByRow.size === 0) {
    showToast({ type: "warn", text: "Aucun film identifié TMDb dans la sélection." });
    return;
  }
  const tmdbIds = Array.from(new Set(Array.from(tmdbByRow.values())));
  // Backend cap : 20 IDs max par appel (cf tmdb_support.get_tmdb_posters).
  // On previent l'utilisateur si la selection depasse pour eviter l'illusion
  // que tout a ete traite alors que seuls les 20 premiers le sont.
  if (tmdbIds.length > 20) {
    showToast({
      type: "warn",
      text: `Seuls les 20 premiers films identifiés sur ${tmdbIds.length} seront rechargés (limite TMDb).`,
      duration: 6000,
    });
  }
  try {
    const res = await apiPost("integrations/get_tmdb_posters", { tmdb_ids: tmdbIds, size: "w185" });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Erreur TMDb posters.");
    }
    // La reponse est typiquement {ok, posters: {<tmdb_id>: <url>}} (cf
    // _get_tmdb_posters_impl dans cinesort/ui/api/tmdb_support.py). Tolere
    // aussi `data.urls` au cas ou la shape change.
    const map = data.posters || data.urls || {};
    let patched = 0;
    tmdbByRow.forEach((tid, rid) => {
      const url = map[String(tid)] || map[tid];
      if (!url) return;
      const r = _state.rows.find((row) => String(row.row_id) === String(rid));
      if (r) {
        r.poster_url = String(url);
        patched += 1;
      }
    });
    if (patched > 0) {
      _render();
      showToast({ type: "success", text: `${patched} poster${patched > 1 ? "s" : ""} TMDb rechargé${patched > 1 ? "s" : ""}.` });
    } else {
      showToast({ type: "warn", text: "Aucun poster reçu (TMDb a peut-être un cache vide pour ces IDs)." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
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

// Formats d'export proposes a l'utilisateur (Spec 07 §07.4.4). Le backend
// (library_actions_support.export_films) accepte "csv" | "json" | "ndjson".
const EXPORT_FORMATS = [
  { value: "csv", label: "CSV (.csv) — tableur" },
  { value: "json", label: "JSON (.json) — objet unique" },
  { value: "ndjson", label: "NDJSON (.ndjson) — 1 film par ligne" },
];

function _openExportFormatPicker(rowIds) {
  // Mini-modal selecteur de format (3 options) avant l'appel export_films.
  // Utilise le composant showModal partage plutot qu'un window.prompt natif
  // pour respecter le theme + la11y (focus trap, Esc, ARIA dialog).
  const n = rowIds.length;
  const optionsHtml = EXPORT_FORMATS.map(
    (f, i) =>
      `<label class="bibliotheque-export-format-option">
         <input type="radio" name="bibliotheque-export-format" value="${escapeHtml(f.value)}"${i === 0 ? " checked" : ""}>
         <span>${escapeHtml(f.label)}</span>
       </label>`,
  ).join("");
  const body = `
    <p>Choisir le format d'export pour <strong>${n}</strong> film${n > 1 ? "s" : ""} :</p>
    <div class="bibliotheque-export-format-list" role="radiogroup" aria-label="Format d'export">
      ${optionsHtml}
    </div>
  `;
  showModal({
    title: "Exporter la sélection",
    body,
    actions: [
      { label: "Annuler", cls: "", onClick: () => {} },
      {
        label: "Exporter",
        cls: "btn-primary",
        onClick: () => {
          const sel = document.querySelector(
            'input[name="bibliotheque-export-format"]:checked',
          );
          const fmt = (sel && sel.value) || "csv";
          // showModal ferme automatiquement apres onClick, mais on rappelle
          // closeModal par securite (idempotent) au cas ou.
          try { closeModal(); } catch (_e) { /* noop */ }
          void _doExport(rowIds, fmt);
        },
      },
    ],
  });
}

async function _doExport(rowIds, fmt) {
  const fmtUpper = String(fmt || "csv").toUpperCase();
  try {
    const res = await apiPost("library/export_films", {
      row_ids: rowIds,
      format: fmt,
    });
    if (res && res.ok !== false) {
      const filePath = res.file_path || (res.data && res.data.file_path);
      showToast({
        type: "success",
        text: filePath
          ? `Export ${fmtUpper} de ${rowIds.length} films : ${filePath}`
          : `Export ${fmtUpper} de ${rowIds.length} films terminé.`,
        duration: 8000,
      });
    } else {
      showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur export." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
  }
}

async function _bulkExport(rowIds) {
  // Spec 07 (Fix 100%) : selecteur format CSV / JSON / NDJSON avant l'export
  // au lieu d'un format CSV hardcode.
  if (!Array.isArray(rowIds) || rowIds.length === 0) return;
  _openExportFormatPicker(rowIds);
}

function _confirmBulkDelete(rowIds, releaseBulkLock = null) {
  // P0 #233 : dangerConfirmModal (au lieu de window.confirm legacy + alert > 50).
  // La modale gere elle-meme : items 5 max visibles + "et N autres", countdown
  // anti-clic-reflexe 3s si bulk > 50.
  // Fix audit 2026-05-24 : countdownSeconds: 3 minimum (feedback actions_dangereuses).
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
    countdownSeconds: 3,
    confirmLabel: "✗ Confirmer la suppression",
    onConfirm: async () => {
      try {
        const res = await apiPost("library/mark_for_deletion_bulk", { row_ids: rowIds });
        const _payload = (res && res.data) || res || {};
        if (res && _payload.ok !== false) {
          showToast({
            type: "success",
            text: `${n} film${n > 1 ? "s" : ""} marqué${n > 1 ? "s" : ""} pour suppression.`,
          });
          _state.selected.clear();
          _fetchLibrary();
        } else {
          showToast({ type: "error", text: _payload.message || _payload.error || "Erreur marquage." });
        }
      } catch (err) {
        showToast({ type: "error", text: String(err && err.message ? err.message : err) });
      } finally {
        if (typeof releaseBulkLock === "function") releaseBulkLock();
      }
    },
    onCancel: () => {
      if (typeof releaseBulkLock === "function") releaseBulkLock();
    },
  });
}

/* --- Smart playlists data layer (sprint orphelins #350) --- */

/** Construit l'objet filtres a partir de l'etat courant pour persister une playlist. */
function _currentFiltersForPlaylist() {
  const f = {};
  if (_state.tierFilter && _state.tierFilter !== "all") {
    f.tier_v2 = [_state.tierFilter];
  }
  const chips = Array.from(_state.activeChips || []);
  if (chips.length > 0) {
    f.chips = chips;
  }
  if (_state.search) {
    f.search = _state.search;
  }
  // On embarque aussi les options "Avance" si elles ont ete touchees, pour
  // garantir une restitution fidele a l'application.
  if (_state.advancedActive && _state.advanced) {
    f.advanced = { ..._state.advanced };
  }
  return f;
}

/** Applique les filtres d'une playlist (presets ou custom). */
function _applyPlaylist(playlistId) {
  const list = Array.isArray(_state.playlists) ? _state.playlists : [];
  const p = list.find((pl) => String(pl.id) === String(playlistId));
  if (!p || !p.filters || typeof p.filters !== "object") return;
  const filters = p.filters;
  // tier_v2 : on prend le premier tier (UI mono-tier).
  if (Array.isArray(filters.tier_v2) && filters.tier_v2.length > 0) {
    _state.tierFilter = String(filters.tier_v2[0] || "all");
    try { localStorage.setItem(LS_TIER, _state.tierFilter); } catch (_e) { /* noop */ }
  } else {
    _state.tierFilter = "all";
  }
  // warnings / chips -> activeChips
  _state.activeChips.clear();
  if (Array.isArray(filters.warnings)) {
    filters.warnings.forEach((_w) => {
      // Fix audit 2026-05-24 : mapping `dnr_partial` -> `recently_modified`
      // etait faux semantiquement (dnr_partial = warning DNR partiel, sans
      // rapport avec une modif recente). Aucun mapping exact n'existe a ce
      // jour ; on ne fait plus rien tant qu'on n'a pas de correspondance sure.
    });
  }
  if (Array.isArray(filters.chips)) {
    filters.chips.forEach((k) => _state.activeChips.add(String(k)));
  }
  // search
  _state.search = String(filters.search || "");
  // year_min/max via advanced
  if (filters.advanced) {
    _state.advanced = { ...ADVANCED_DRAWER_DEFAULTS, ...filters.advanced };
    _state.advancedActive = true;
    try { localStorage.setItem(LS_ADV, JSON.stringify(_state.advanced)); } catch (_e) { /* noop */ }
  } else if (filters.year_min != null || filters.year_max != null) {
    _state.advanced = {
      ...ADVANCED_DRAWER_DEFAULTS,
      year_min: filters.year_min ?? ADVANCED_DRAWER_DEFAULTS.year_min,
      year_max: filters.year_max ?? ADVANCED_DRAWER_DEFAULTS.year_max,
    };
    _state.advancedActive = true;
  }
  showToast({ type: "success", text: `Playlist appliquée : ${p.name}` });
  _fetchLibrary();
}

/** Prompt pour le nom + save_smart_playlist(name, filters). */
function _promptSavePlaylist() {
  const filters = _currentFiltersForPlaylist();
  const filtersSummary = (() => {
    const parts = [];
    if (filters.tier_v2) parts.push(`Tier ${filters.tier_v2.join("/")}`);
    if (filters.chips) parts.push(`${filters.chips.length} chip${filters.chips.length > 1 ? "s" : ""}`);
    if (filters.search) parts.push(`recherche "${filters.search}"`);
    if (filters.advanced) parts.push(`filtres avancés`);
    return parts.length ? parts.join(" · ") : "aucun filtre actif";
  })();
  showModal({
    title: "Enregistrer la playlist",
    body: `
      <p>Filtres capturés : <em>${escapeHtml(filtersSummary)}</em></p>
      <label class="bibliotheque-playlist-form-field">
        <span>Nom de la playlist</span>
        <input type="text"
               class="v5-input"
               data-bibliotheque-playlist-name
               maxlength="80"
               placeholder="Ex : Films 2020+ à re-encoder">
      </label>
    `,
    actions: [
      { label: "Annuler", cls: "", onClick: () => {} },
      {
        label: "Enregistrer",
        cls: "btn-primary",
        onClick: () => {
          const inp = document.querySelector("[data-bibliotheque-playlist-name]");
          const name = inp && inp.value ? String(inp.value).trim() : "";
          if (!name) {
            showToast({ type: "warn", text: "Le nom est requis." });
            return;
          }
          try { closeModal(); } catch (_e) { /* noop */ }
          void _doSavePlaylist(name, filters);
        },
      },
    ],
  });
}

async function _doSavePlaylist(name, filters) {
  try {
    const res = await apiPost("library/save_smart_playlist", { name, filters });
    if (res && res.ok !== false) {
      showToast({ type: "success", text: `Playlist "${name}" enregistrée.` });
      await _fetchPlaylists();
      _render();
    } else {
      showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur enregistrement." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
  }
}

function _confirmDeletePlaylist(playlistId) {
  const list = Array.isArray(_state.playlists) ? _state.playlists : [];
  const p = list.find((pl) => String(pl.id) === String(playlistId));
  if (!p) return;
  // Confirmation simple via showModal (suppression unitaire, pas bulk > 50).
  showModal({
    title: "Supprimer la playlist ?",
    body: `<p>La playlist <strong>${escapeHtml(p.name || "Sans nom")}</strong> sera supprimée. Cette action est définitive.</p>`,
    actions: [
      { label: "Annuler", cls: "", onClick: () => {} },
      {
        label: "Supprimer",
        cls: "btn-danger",
        onClick: () => {
          try { closeModal(); } catch (_e) { /* noop */ }
          void _doDeletePlaylist(playlistId);
        },
      },
    ],
  });
}

async function _doDeletePlaylist(playlistId) {
  try {
    const res = await apiPost("library/delete_smart_playlist", { playlist_id: playlistId });
    if (res && res.ok !== false) {
      showToast({ type: "success", text: "Playlist supprimée." });
      await _fetchPlaylists();
      _render();
    } else {
      showToast({ type: "error", text: (res && (res.message || res.error)) || "Erreur suppression." });
    }
  } catch (err) {
    showToast({ type: "error", text: String(err && err.message ? err.message : err) });
  }
}

async function _fetchPlaylists() {
  try {
    const res = await apiPost("library/get_smart_playlists", {});
    if (res && res.ok !== false) {
      _state.playlists = Array.isArray(res.playlists) ? res.playlists : [];
      _state.playlistsLoaded = true;
    } else {
      _state.playlists = [];
      _state.playlistsLoaded = true;
    }
  } catch (err) {
    // Silencieux : la zone playlists tolere l'erreur, on log juste.
    console.warn("[bibliotheque] get_smart_playlists ko :", err && err.message ? err.message : err);
    _state.playlists = [];
    _state.playlistsLoaded = true;
  }
}

/* --- Entrypoint --- */

export async function initBibliotheque(container) {
  if (!container) return;
  // Si un mount precedent n'a pas ete proprement unmount, on nettoie ici pour
  // garantir un controller frais et eviter les listeners stacks.
  if (_eventsController) {
    try { _eventsController.abort(); } catch (_e) { /* noop */ }
  }
  _eventsController = new AbortController();
  _eventsBound = false;

  _container = container;
  _state = _initState();
  _state.loading = true;
  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;
  void signal;
  // Issue #350 : fetch playlists en parallele du premier chargement library.
  // En cas d'echec on continue : la zone playlists est tolerante a l'absence.
  void _fetchPlaylists();
  await _fetchLibrary();
}

export function unmountBibliotheque() {
  if (_abortController) {
    try { _abortController.abort(); } catch (_e) { /* noop */ }
    _abortController = null;
  }
  // Audit C17 P0 #7 : abort des listeners DOM poses via signal (delegation
  // sur container, drag-select grid, etc.). Empeche les leak quand la vue
  // est demontee/remontee.
  if (_eventsController) {
    try { _eventsController.abort(); } catch (_e) { /* noop */ }
    _eventsController = null;
  }
  _eventsBound = false;
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
