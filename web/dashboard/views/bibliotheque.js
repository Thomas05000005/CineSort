/* views/bibliotheque.js — Phase 3.2 grille complete (spec 07-bibliotheque.md).
 *
 * Grille de posters TMDb + chips de filtres tier + recherche + tri + pagination
 * + selection multi + toolbar contextuelle + click -> /film/:id (spec 06 mode C).
 *
 * Hors scope de cette PR (itererations futures) :
 *   - scroll infini reel (on a une pagination prev/next simple a la place)
 *   - drag-select rectangulaire
 *   - drawer "Avance" (annee/duree/codec/source sliders)
 *   - 4 endpoints bulk (mark_for_deletion_bulk/rescan_rows_bulk/export_films/queue_perceptual_analyses)
 *     -> les boutons existent mais affichent une modale "feature a venir"
 *
 * Route cible : /bibliotheque (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { dangerConfirmModal } from "../components/modal.js";
import { renderFilmDetail } from "../components/film-detail.js";

const PAGE_SIZE = 60;
const LS_VIEW = "cinesort.bibliotheque.view";
const LS_TIER = "cinesort.bibliotheque.tier";
const LS_SORT = "cinesort.bibliotheque.sort";

const TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
  unknown: "Non identifié",
};

const TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject", "unknown"];

const SORT_OPTIONS = [
  { value: "title", label: "Titre A→Z" },
  { value: "title_desc", label: "Titre Z→A" },
  { value: "year_desc", label: "Année (récent)" },
  { value: "year_asc", label: "Année (ancien)" },
  { value: "score_desc", label: "Score (meilleur)" },
  { value: "score_asc", label: "Score (pire)" },
  { value: "duration_desc", label: "Durée (long)" },
  { value: "duration_asc", label: "Durée (court)" },
];

/* --- State --- */

let _state = null;
let _searchDebounce = null;
let _container = null;
let _abortController = null;

function _initState() {
  return {
    rows: [],
    total: 0,
    page: 1,
    pages: 1,
    byTier: {},
    tierFilter: localStorage.getItem(LS_TIER) || "all",
    search: "",
    sort: localStorage.getItem(LS_SORT) || "title",
    viewMode: localStorage.getItem(LS_VIEW) || "grid",
    selected: new Set(),
    loading: false,
    error: null,
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

/* --- Rendering --- */

function _renderSkeleton() {
  return `
    <section class="bibliotheque-view bibliotheque-view--loading" aria-busy="true">
      <div class="bibliotheque-header"><div class="v5-skeleton bibliotheque-title-skel"></div></div>
      <div class="bibliotheque-section v5-skeleton bibliotheque-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="bibliotheque-view bibliotheque-view--error" role="alert">
      <h2>La Bibliothèque n'a pas pu se charger.</h2>
      <p>${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-bibliotheque-retry>Réessayer</button>
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
          ${visible} affiché${visible > 1 ? "s" : ""}
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
        <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-action="filters">▾ Filtres avancés</button>
      </div>
    </header>
  `;
}

function _renderTierChips() {
  const counts = _state.byTier || {};
  const allCount = Object.values(counts).reduce((a, b) => a + (Number(b) || 0), 0);
  const chips = [
    `<button type="button" class="bibliotheque-chip${_state.tierFilter === "all" ? " is-active" : ""}" data-bibliotheque-tier="all">
       Tous <span class="bibliotheque-chip-count">${allCount}</span>
     </button>`,
  ];
  for (const t of TIER_ORDER) {
    const n = Number(counts[t] || 0);
    chips.push(`<button type="button"
                        class="bibliotheque-chip bibliotheque-chip--tier-${t}${_state.tierFilter === t ? " is-active" : ""}"
                        data-bibliotheque-tier="${t}">
                  ${escapeHtml(TIER_LABELS[t] || t)} <span class="bibliotheque-chip-count">${n}</span>
                </button>`);
  }
  return `
    <div class="bibliotheque-chips" role="group" aria-label="Filtres tier">
      ${chips.join("")}
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
      <td>${_formatScore(row.score_v2)}</td>
      <td>${escapeHtml(row.resolution || "—")}</td>
      <td>${row.duration_min ? `${row.duration_min} min` : "—"}</td>
    </tr>
  `;
}

function _renderGrid() {
  if (_state.rows.length === 0) {
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
        <table class="bibliotheque-table">
          <thead>
            <tr>
              <th aria-label="Sélection"></th>
              <th>Titre</th>
              <th>Année</th>
              <th>Tier</th>
              <th>Score</th>
              <th>Résolution</th>
              <th>Durée</th>
            </tr>
          </thead>
          <tbody>${_state.rows.map(_renderTableRow).join("")}</tbody>
        </table>
      </div>
    `;
  }
  return `<div class="bibliotheque-grid">${_state.rows.map(_renderFilmCard).join("")}</div>`;
}

function _renderPagination() {
  if (_state.pages <= 1) return "";
  const p = _state.page;
  const last = _state.pages;
  return `
    <nav class="bibliotheque-pagination" aria-label="Pagination Bibliothèque">
      <button type="button" class="v5-btn v5-btn--ghost" data-bibliotheque-page="prev"${p <= 1 ? " disabled" : ""}>← Précédent</button>
      <span class="bibliotheque-pagination-info">Page <strong>${p}</strong> sur ${last}</span>
      <button type="button" class="v5-btn v5-btn--ghost" data-bibliotheque-page="next"${p >= last ? " disabled" : ""}>Suivant →</button>
    </nav>
  `;
}

function _renderBody() {
  if (_state.loading) {
    return `<div class="bibliotheque-section bibliotheque-loading">Chargement…</div>`;
  }
  if (_state.error) {
    return `<div class="bibliotheque-section bibliotheque-error">${escapeHtml(_state.error)}</div>`;
  }
  return `
    ${_renderGrid()}
    ${_renderPagination()}
  `;
}

function _render() {
  if (!_container) return;
  _container.innerHTML = `
    <section class="bibliotheque-view">
      ${_renderHeader()}
      ${_renderTierChips()}
      ${_renderBulkToolbar()}
      <section class="bibliotheque-section">${_renderBody()}</section>
    </section>
  `;
  _bindEvents(_container);
}

/* --- Data --- */

async function _fetchLibrary() {
  if (_abortController) _abortController.abort();
  _abortController = new AbortController();
  const signal = _abortController.signal;
  _state.loading = true;
  _state.error = null;
  _render();

  const filters = {};
  if (_state.tierFilter && _state.tierFilter !== "all") {
    filters.tier_v2 = [_state.tierFilter];
  }
  if (_state.search) {
    filters.search = _state.search;
  }

  try {
    const res = await apiPost(
      "library/get_library_filtered",
      {
        filters,
        sort: _state.sort,
        page: _state.page,
        page_size: PAGE_SIZE,
      },
      { signal },
    );
    if (!res || res.ok === false) {
      _state.error = (res && (res.message || res.error)) || "Erreur de chargement.";
      _state.loading = false;
      _render();
      return;
    }
    const data = res.data || res;
    _state.rows = data.rows || [];
    _state.total = data.total || 0;
    _state.page = data.page || 1;
    _state.pages = data.pages || 1;
    // Si on filtre par tier, on garde le compteur global (charge initiale).
    // by_tier est present aussi en filtré, mais on veut le total pour les chips.
    if (data.stats && data.stats.by_tier && _state.tierFilter === "all" && !_state.search) {
      _state.byTier = data.stats.by_tier;
    } else if (_state.byTier && Object.keys(_state.byTier).length === 0 && data.stats && data.stats.by_tier) {
      _state.byTier = data.stats.by_tier;
    }
    _state.loading = false;
    _render();
  } catch (err) {
    if (err && err.name === "AbortError") return;
    _state.error = err ? String(err.message || err) : "Erreur réseau";
    _state.loading = false;
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
      _state.page = 1;
      localStorage.setItem(LS_TIER, "all");
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
        _state.page = 1;
        _fetchLibrary();
      }, 250);
    });
  }

  const sort = container.querySelector("[data-bibliotheque-sort]");
  if (sort) {
    sort.addEventListener("change", (ev) => {
      _state.sort = ev.target.value || "title";
      _state.page = 1;
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
      _state.page = 1;
      localStorage.setItem(LS_TIER, _state.tierFilter);
      _fetchLibrary();
    });
  });

  container.querySelectorAll("[data-bibliotheque-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = btn.dataset.bibliothequePage;
      if (dir === "prev" && _state.page > 1) _state.page -= 1;
      else if (dir === "next" && _state.page < _state.pages) _state.page += 1;
      else return;
      _fetchLibrary();
    });
  });

  container.querySelectorAll("[data-bibliotheque-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const action = btn.dataset.bibliothequeAction;
      if (action === "filters") {
        alert("Drawer Filtres avancés (année / durée / codec / source / etc.) à implémenter ultérieurement.");
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
    });
    card.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        const rowId = card.dataset.rowId;
        if (rowId) renderFilmDetail({ mode: "A", rowId });
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
}

function _handleBulkAction(action) {
  const n = _state.selected.size;
  if (n === 0) return;
  if (action === "delete") {
    _confirmBulkDelete(n);
    return;
  }
  // Autres actions : feature à venir (endpoints backend manquants).
  alert(`Action "${action}" sur ${n} film(s) — endpoint backend à brancher en itération ultérieure.`);
}

function _confirmBulkDelete(n) {
  // P0 #233 : dangerConfirmModal (au lieu de window.confirm legacy + alert > 50).
  // La modale gere elle-meme : items 5 max visibles + "et N autres", countdown
  // anti-clic-reflexe 3s si bulk > 50.
  const selectedIds = Array.from(_state.selected);
  const items = selectedIds.map((id) => {
    const r = _state.rows.find((row) => String(row.row_id) === String(id));
    return r ? `${r.title}${r.year ? ` (${r.year})` : ""}` : String(id);
  });
  dangerConfirmModal({
    title: `Confirmer la suppression de ${n} film${n > 1 ? "s" : ""} ?`,
    items,
    consequence:
      `Ils seront déplacés vers _user_marked_for_deletion/ au prochain apply (réversible via Undo). ` +
      `[Endpoint mark_for_deletion_bulk à brancher en itération ultérieure.]`,
    countdownSeconds: n > 50 ? 3 : 0,
    confirmLabel: "✗ Confirmer la suppression",
    onConfirm: () => {
      alert(`Marquage de ${n} films à brancher quand library/mark_for_deletion_bulk sera dispo.`);
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
  _container = null;
  _state = null;
}
