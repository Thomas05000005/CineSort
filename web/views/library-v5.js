/* views/library-v5.js — v7.6.0 Vague 3 (V5bis-02 ES module port)
 *
 * Vue Bibliotheque v5 portee en ES module + REST apiPost.
 *
 * Composition : FilterSidebar + SmartPlaylists (gauche) | LibraryTable/PosterGrid (droite)
 * avec toggle Table/Grid + sort + pagination + persistance etat localStorage.
 *
 * API publique :
 *   import { initLibrary } from "./library-v5.js"
 *   await initLibrary(container, opts)
 *
 * Features V5A preservees :
 *   - V2-04 : Promise.allSettled (playlists + library en parallele)
 *   - V2-08 : skeleton state pendant le fetch initial
 */

import {
  apiPost,
  escapeHtml,
  renderSkeleton,
  renderError,
} from "./_v5_helpers.js";

const STORAGE_KEY_VIEW_MODE = "cinesort.library.viewMode";
const STORAGE_KEY_FILTERS = "cinesort.library.filters";
const STORAGE_KEY_SORT = "cinesort.library.sort";

const _state = {
  filters: {},
  sort: "title",
  page: 1,
  pageSize: 50,
  viewMode: "table",  // "table" | "grid"
  playlists: [],
  activePlaylistId: null,
  lastResult: null,
  containerRef: null,
};

function _loadPersistedState() {
  try {
    _state.viewMode = localStorage.getItem(STORAGE_KEY_VIEW_MODE) || "table";
    const f = localStorage.getItem(STORAGE_KEY_FILTERS);
    if (f) _state.filters = JSON.parse(f) || {};
    const s = localStorage.getItem(STORAGE_KEY_SORT);
    if (s) _state.sort = s;
  } catch (e) { /* noop */ }
}

function _persistState() {
  try {
    localStorage.setItem(STORAGE_KEY_VIEW_MODE, _state.viewMode);
    localStorage.setItem(STORAGE_KEY_FILTERS, JSON.stringify(_state.filters));
    localStorage.setItem(STORAGE_KEY_SORT, _state.sort);
  } catch (e) { /* noop */ }
}

async function _fetchLibrary() {
  const r = await apiPost("get_library_filtered", {
    run_id: null,
    filters: _state.filters,
    sort: _state.sort,
    page: _state.page,
    page_size: _state.pageSize,
  });
  if (!r.ok) {
    return { ok: false, message: r.error || "Bibliotheque indisponible" };
  }
  return r.data || { ok: false };
}

async function _fetchPlaylists() {
  const r = await apiPost("get_smart_playlists");
  if (r.ok && r.data && Array.isArray(r.data.playlists)) {
    return r.data.playlists;
  }
  return [];
}

function _buildShell(container) {
  container.innerHTML = `
    <div class="v5-library-shell">
      <aside class="v5-library-side" data-v5-library-side>
        <div data-v5-library-playlists></div>
        <div data-v5-library-filters></div>
      </aside>
      <section class="v5-library-main">
        <header class="v5-library-header">
          <div class="v5-library-header-info">
            <span class="v5-library-count" data-v5-library-count>—</span>
            <span class="v5-library-run" data-v5-library-run></span>
          </div>
          <div class="v5-library-header-actions">
            <div class="v5-library-view-toggle" role="tablist" aria-label="Mode d'affichage">
              <button type="button" class="v5-library-view-btn ${_state.viewMode === 'table' ? 'is-active' : ''}"
                      data-view-mode="table" role="tab" aria-selected="${_state.viewMode === 'table'}">
                Table
              </button>
              <button type="button" class="v5-library-view-btn ${_state.viewMode === 'grid' ? 'is-active' : ''}"
                      data-view-mode="grid" role="tab" aria-selected="${_state.viewMode === 'grid'}">
                Grille
              </button>
            </div>
          </div>
        </header>
        <div class="v5-library-body" data-v5-library-body>
          <div class="v5-library-loading">Chargement...</div>
        </div>
        <footer class="v5-library-footer" data-v5-library-footer></footer>
      </section>
    </div>
  `;

  // Bind view mode toggle
  container.querySelectorAll("[data-view-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.viewMode = btn.dataset.viewMode;
      _persistState();
      container.querySelectorAll("[data-view-mode]").forEach((b) => {
        const active = b.dataset.viewMode === _state.viewMode;
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-selected", active ? "true" : "false");
      });
      _renderBody();
    });
  });
}

function _renderBody() {
  const root = _state.containerRef;
  if (!root) return;
  const body = root.querySelector("[data-v5-library-body]");
  if (!body) return;
  const result = _state.lastResult;
  if (!result || !result.ok) {
    // V2-07 : empty state actionnable (CTA "Lancer un scan" → vue Accueil).
    const message = result?.message || "Lancez un scan pour analyser votre bibliotheque puis explorez vos films ici.";
    if (typeof window.buildEmptyState === "function") {
      body.innerHTML = window.buildEmptyState({
        icon: "library",
        title: "Aucun run disponible",
        message,
        ctaLabel: "Lancer un scan",
        testId: "library-empty-cta",
      });
      if (typeof window.bindEmptyStateCta === "function") {
        window.bindEmptyStateCta(body, () => {
          if (typeof window.navigateTo === "function") window.navigateTo("home");
        });
      }
    } else {
      body.innerHTML = `<div class="v5-library-empty">${escapeHtml(message)}</div>`;
    }
    return;
  }
  const rows = result.rows || [];
  const comps = window.LibraryComponents;
  if (!comps) {
    body.innerHTML = `<div class="v5-library-empty">Composants non charges.</div>`;
    return;
  }
  if (_state.viewMode === "grid") {
    comps.renderPosterGrid(body, rows, {
      onRowClick: (rid) => window.navigateTo && window.navigateTo("film/" + rid),
    });
  } else {
    comps.renderLibraryTable(body, rows, {
      sort: _state.sort,
      onRowClick: (rid) => window.navigateTo && window.navigateTo("film/" + rid),
      onSortChange: (newSort) => {
        _state.sort = newSort;
        _state.page = 1;
        _persistState();
        refresh();
      },
    });
  }
}

function _renderFooter() {
  const root = _state.containerRef;
  if (!root) return;
  const footer = root.querySelector("[data-v5-library-footer]");
  if (!footer) return;
  const r = _state.lastResult;
  if (!r || !r.ok || !r.total) { footer.innerHTML = ""; return; }

  const { total, page, pages } = r;
  footer.innerHTML = `
    <div class="v5-library-pagination">
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
              data-page-action="prev" ${page <= 1 ? "disabled" : ""}>Precedent</button>
      <span class="v5-library-pagination-info">
        Page <strong class="v5u-tabular-nums">${page}</strong> / <span class="v5u-tabular-nums">${pages}</span>
        · <span class="v5u-tabular-nums">${total}</span> film${total > 1 ? "s" : ""}
      </span>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
              data-page-action="next" ${page >= pages ? "disabled" : ""}>Suivant</button>
    </div>
  `;
  footer.querySelectorAll("[data-page-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const act = btn.dataset.pageAction;
      if (act === "prev" && _state.page > 1) _state.page -= 1;
      if (act === "next" && _state.page < pages) _state.page += 1;
      refresh();
    });
  });
}

function _renderSidebar() {
  const root = _state.containerRef;
  if (!root) return;
  const filtersSlot = root.querySelector("[data-v5-library-filters]");
  const playlistsSlot = root.querySelector("[data-v5-library-playlists]");
  const comps = window.LibraryComponents;
  if (!comps) return;

  if (filtersSlot) {
    const tierCounts = _state.lastResult?.stats?.by_tier || {};
    comps.renderFilterSidebar(filtersSlot, {
      activeFilters: _state.filters,
      tierCounts,
      onChange: (newFilters) => {
        _state.filters = newFilters;
        _state.activePlaylistId = null;
        _state.page = 1;
        _persistState();
        refresh();
      },
    });
  }

  if (playlistsSlot) {
    comps.renderSmartPlaylists(playlistsSlot, _state.playlists, {
      activeId: _state.activePlaylistId,
      onSelect: (pl) => {
        _state.filters = pl.filters || {};
        _state.activePlaylistId = pl.id;
        _state.page = 1;
        _persistState();
        _renderSidebar();  /* refresh chips */
        refresh();
      },
      onSaveCurrent: async () => {
        const name = window.prompt("Nom de la playlist :");
        if (!name) return;
        const r = await apiPost("save_smart_playlist", {
          name,
          filters: _state.filters,
        });
        if (r.ok && r.data) {
          _state.playlists = await _fetchPlaylists();
          _state.activePlaylistId = r.data.playlist_id || null;
          _renderSidebar();
        }
      },
      onDelete: async (id) => {
        if (!window.confirm("Supprimer cette playlist ?")) return;
        const r = await apiPost("delete_smart_playlist", { playlist_id: id });
        if (r.ok) {
          _state.playlists = await _fetchPlaylists();
          if (_state.activePlaylistId === id) _state.activePlaylistId = null;
          _renderSidebar();
        }
      },
    });
  }
}

function _renderCount() {
  const root = _state.containerRef;
  if (!root) return;
  const count = root.querySelector("[data-v5-library-count]");
  const runEl = root.querySelector("[data-v5-library-run]");
  if (count) {
    const total = _state.lastResult?.total ?? 0;
    count.textContent = `${total} film${total > 1 ? "s" : ""}`;
  }
  if (runEl) {
    const rid = _state.lastResult?.run_id || "—";
    runEl.textContent = `Run : ${rid}`;
  }
}

export async function refresh() {
  const result = await _fetchLibrary();
  _state.lastResult = result;
  _renderCount();
  _renderBody();
  _renderFooter();
  _renderSidebar();  /* update tier counts */
}

async function _loadLibraryData() {
  // V2-04 : Promise.allSettled — playlists et library en parallele.
  // Si l'un des endpoints plante, l'autre continue de fonctionner.
  const results = await Promise.allSettled([
    _fetchPlaylists(),
    _fetchLibrary(),
  ]);
  return {
    playlists: results[0].status === "fulfilled" ? results[0].value : [],
    library: results[1].status === "fulfilled"
      ? results[1].value
      : { ok: false, message: "Bibliotheque indisponible" },
  };
}

function _renderLibrary(container, data) {
  _state.playlists = data.playlists;
  _state.lastResult = data.library;
  _buildShell(container);
  _renderCount();
  _renderBody();
  _renderFooter();
  _renderSidebar();
}

/**
 * Initialise la vue Bibliotheque v5 (port V5bis-02).
 * Pattern : skeleton -> Promise.allSettled(playlists, library) -> render | error.
 *
 * @param {HTMLElement} container - conteneur DOM
 * @param {object} [opts] - options (reserve pour usage futur)
 */
export async function initLibrary(container, opts) {
  if (!container) return;
  void opts;
  _state.containerRef = container;
  _loadPersistedState();

  // V2-08 : skeleton avant le fetch (type "grid" pour l'aspect cartes/grille).
  renderSkeleton(container, "grid");

  try {
    const data = await _loadLibraryData();
    _renderLibrary(container, data);
  } catch (e) {
    renderError(container, e, () => initLibrary(container, opts));
  }
}
