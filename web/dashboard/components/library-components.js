/* dashboard/components/library-components.js — v7.6.0 Vague 3 (ES module)
 * Parite desktop. Memes API, memes classes CSS.
 */

import { escapeHtml } from "../core/dom.js";

function _svg(pathContent, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
}

export const FILTER_DIMENSIONS = {
  tier_v2: {
    label: "Tier V2",
    options: [
      { value: "platinum", label: "Platinum" },
      { value: "gold",     label: "Gold" },
      { value: "silver",   label: "Silver" },
      { value: "bronze",   label: "Bronze" },
      { value: "reject",   label: "Reject" },
      { value: "unknown",  label: "Non classe" },
    ],
  },
  codec: {
    label: "Codec video",
    options: [
      { value: "hevc", label: "HEVC" }, { value: "h264", label: "H.264" },
      { value: "av1", label: "AV1" }, { value: "vp9", label: "VP9" },
      { value: "mpeg2", label: "MPEG-2" }, { value: "vc1", label: "VC-1" },
      { value: "xvid", label: "XviD" },
    ],
  },
  resolution: {
    label: "Resolution",
    options: [
      { value: "4k", label: "4K / UHD" }, { value: "1080p", label: "1080p" },
      { value: "720p", label: "720p" }, { value: "sd", label: "SD" },
    ],
  },
  hdr: {
    label: "HDR",
    options: [
      { value: "sdr", label: "SDR" }, { value: "hdr10", label: "HDR10" },
      { value: "hdr10_plus", label: "HDR10+" }, { value: "dv", label: "Dolby Vision" },
      { value: "dv_p5", label: "DV Profile 5" },
    ],
  },
  warnings: {
    label: "Warnings",
    options: [
      { value: "dv_profile_5", label: "DV Profile 5" },
      { value: "hdr_metadata_missing", label: "HDR metadata incomplete" },
      { value: "runtime_mismatch", label: "Runtime mismatch" },
      { value: "short_file", label: "Fichier court" },
      { value: "low_confidence", label: "Confidence faible" },
      { value: "category_imbalance", label: "Desequilibre V/A" },
      { value: "fake_lossless", label: "Faux lossless" },
      { value: "dnr_partial", label: "DNR partiel" },
      { value: "fake_4k_confirmed", label: "Faux 4K" },
    ],
  },
  grain_era_v2: {
    label: "Ere grain",
    options: [
      { value: "uhd_native_dolby_vision", label: "UHD Dolby Vision" },
      { value: "blu_ray_digital", label: "Blu-ray digital" },
      { value: "digital_transition", label: "Digital transition" },
      { value: "modern_film", label: "Modern film" },
      { value: "early_color", label: "Early color" },
      { value: "35mm_golden", label: "35mm golden" },
      { value: "16mm_era", label: "16mm era" },
    ],
  },
  grain_nature: {
    label: "Nature grain",
    options: [
      { value: "film_grain", label: "Film grain authentique" },
      { value: "encode_noise", label: "Bruit encode" },
      { value: "post_added", label: "Post added" },
      { value: "ambiguous", label: "Ambigu" },
    ],
  },
};

const _WARN_SHORT = {
  dv_profile_5: "DV5", hdr_metadata_missing: "HDR?", runtime_mismatch: "Runtime",
  short_file: "Court", low_confidence: "Confidence", category_imbalance: "V/A delta",
  fake_lossless: "Faux LL", dnr_partial: "DNR", fake_4k_confirmed: "Faux 4K",
};

function _readFilters(root) {
  const out = {};
  root.querySelectorAll(".v5-filter-chip.is-active").forEach((c) => {
    const k = c.dataset.filterKey, v = c.dataset.filterValue;
    if (!k) return;
    if (!out[k]) out[k] = [];
    out[k].push(v);
  });
  root.querySelectorAll("input[data-filter-key]").forEach((inp) => {
    const k = inp.dataset.filterKey, v = inp.value.trim();
    if (v) out[k] = (k.startsWith("year_") || k.startsWith("duration_")) ? Number(v) : v;
  });
  return out;
}

export function renderFilterSidebar(container, opts = {}) {
  if (!container) return;
  const active = opts.activeFilters || {};
  const tierCounts = opts.tierCounts || {};

  let html = `<div class="v5-filter-sidebar" data-v5-filter-sidebar>`;
  html += `
    <div class="v5-filter-section">
      <label class="v5-filter-section-title">Recherche</label>
      <input type="text" class="v5-input" data-filter-key="search"
             placeholder="Titre du film..." value="${escapeHtml(active.search || "")}">
    </div>
  `;

  Object.entries(FILTER_DIMENSIONS).forEach(([key, dim]) => {
    const activeList = Array.isArray(active[key]) ? active[key] : [];
    const chips = dim.options.map((opt) => {
      const isActive = activeList.includes(opt.value);
      const count = (key === "tier_v2" && tierCounts[opt.value] !== undefined)
        ? ` <span class="v5-filter-chip-count">${tierCounts[opt.value]}</span>` : "";
      return `
        <button type="button" class="v5-filter-chip ${isActive ? "is-active" : ""}"
                data-filter-key="${escapeHtml(key)}"
                data-filter-value="${escapeHtml(opt.value)}"
                aria-pressed="${isActive ? "true" : "false"}">
          ${escapeHtml(opt.label)}${count}
        </button>`;
    }).join("");
    html += `
      <div class="v5-filter-section">
        <label class="v5-filter-section-title">${escapeHtml(dim.label)}</label>
        <div class="v5-filter-chips">${chips}</div>
      </div>`;
  });

  html += `
    <div class="v5-filter-section">
      <label class="v5-filter-section-title">Annee</label>
      <div class="v5-filter-range">
        <input type="number" class="v5-input v5-input--sm" data-filter-key="year_min"
               placeholder="Min" min="1900" max="2030" value="${escapeHtml(active.year_min || "")}">
        <span class="v5u-text-muted">-</span>
        <input type="number" class="v5-input v5-input--sm" data-filter-key="year_max"
               placeholder="Max" min="1900" max="2030" value="${escapeHtml(active.year_max || "")}">
      </div>
    </div>
    <div class="v5-filter-section">
      <label class="v5-filter-section-title">Duree (min)</label>
      <div class="v5-filter-range">
        <input type="number" class="v5-input v5-input--sm" data-filter-key="duration_min"
               placeholder="Min" min="0" value="${escapeHtml(active.duration_min || "")}">
        <span class="v5u-text-muted">-</span>
        <input type="number" class="v5-input v5-input--sm" data-filter-key="duration_max"
               placeholder="Max" min="0" value="${escapeHtml(active.duration_max || "")}">
      </div>
    </div>
    <div class="v5-filter-footer">
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-v5-filter-reset>Reinitialiser</button>
    </div>
  </div>`;

  container.innerHTML = html;

  let debounceTimer = null;
  const _emit = () => {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const f = _readFilters(container);
      if (typeof opts.onChange === "function") opts.onChange(f);
    }, 150);
  };
  container.querySelectorAll(".v5-filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("is-active");
      btn.setAttribute("aria-pressed", btn.classList.contains("is-active") ? "true" : "false");
      _emit();
    });
  });
  container.querySelectorAll("input[data-filter-key]").forEach((inp) => {
    inp.addEventListener("input", _emit);
  });
  const resetBtn = container.querySelector("[data-v5-filter-reset]");
  if (resetBtn) resetBtn.addEventListener("click", () => {
    container.querySelectorAll(".v5-filter-chip").forEach((c) => {
      c.classList.remove("is-active");
      c.setAttribute("aria-pressed", "false");
    });
    container.querySelectorAll("input[data-filter-key]").forEach((inp) => { inp.value = ""; });
    _emit();
  });
}

function _sortIndicator(currentSort, colKey) {
  if (currentSort === colKey || currentSort === colKey + "_asc") return '<span class="v5-sort-ind">↑</span>';
  if (currentSort === colKey + "_desc") return '<span class="v5-sort-ind">↓</span>';
  return "";
}

function _nextSort(currentSort, colKey) {
  if (currentSort === colKey || currentSort === colKey + "_asc") return colKey + "_desc";
  return colKey + "_asc";
}

function _shortWarn(w) { return _WARN_SHORT[w] || w.substr(0, 8); }

export function renderLibraryTable(container, rows, opts = {}) {
  if (!container) return;
  if (!Array.isArray(rows) || rows.length === 0) {
    container.innerHTML = `<div class="v5-library-empty">Aucun film ne correspond aux filtres.</div>`;
    return;
  }
  const currentSort = opts.sort || "title";

  let html = `
    <div class="v5-library-table-wrap v5-scroll">
      <table class="v5-table v5-library-table">
        <thead><tr>
          <th class="sortable" data-sort-key="title">Titre ${_sortIndicator(currentSort, "title")}</th>
          <th class="sortable" data-sort-key="score">Score ${_sortIndicator(currentSort, "score")}</th>
          <th>Tier</th><th>Resolution</th><th>Codec</th><th>HDR</th>
          <th class="sortable" data-sort-key="year">Annee ${_sortIndicator(currentSort, "year")}</th>
          <th class="sortable" data-sort-key="duration">Duree ${_sortIndicator(currentSort, "duration")}</th>
          <th>Warnings</th>
        </tr></thead><tbody>
  `;
  rows.forEach((r) => {
    const tier = String(r.tier_v2 || "unknown").toLowerCase();
    const scoreVal = r.score_v2 != null ? Math.round(Number(r.score_v2)) : null;
    const scoreHtml = scoreVal != null
      ? `<span class="v5-library-score-mini v5-library-score-mini--${escapeHtml(tier)}">${scoreVal}</span>`
      : `<span class="v5u-text-muted">—</span>`;
    const dur = r.duration_min ? `${r.duration_min} min` : "—";
    const warnings = (r.warnings || []).slice(0, 3).map((w) =>
      `<span class="v5-badge v5-badge--severity-warning v5-library-warn" title="${escapeHtml(w)}">${escapeHtml(_shortWarn(w))}</span>`
    ).join("");
    const moreWarns = (r.warnings || []).length > 3
      ? ` <span class="v5u-text-muted">+${(r.warnings || []).length - 3}</span>` : "";
    html += `
      <tr class="row-tier-${escapeHtml(tier)}" data-row-id="${escapeHtml(r.row_id)}" tabindex="0">
        <td class="v5-library-title">${escapeHtml(r.title || "—")}</td>
        <td class="v5u-tabular-nums">${scoreHtml}</td>
        <td><span class="v5-badge v5-badge--tier-${escapeHtml(tier)}">${escapeHtml(tier)}</span></td>
        <td>${escapeHtml(r.resolution || "—")}</td>
        <td>${escapeHtml(String(r.codec || "—").toUpperCase())}</td>
        <td>${escapeHtml(String(r.hdr || "—").toUpperCase())}</td>
        <td class="v5u-tabular-nums">${escapeHtml(r.year || "—")}</td>
        <td class="v5u-tabular-nums">${escapeHtml(dur)}</td>
        <td class="v5-library-warns">${warnings}${moreWarns}</td>
      </tr>`;
  });
  html += `</tbody></table></div>`;
  container.innerHTML = html;

  container.querySelectorAll("tr[data-row-id]").forEach((tr) => {
    const activate = () => {
      const rowId = tr.dataset.rowId;
      if (typeof opts.onRowClick === "function") opts.onRowClick(rowId);
    };
    tr.addEventListener("click", activate);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); activate(); }
    });
  });
  container.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sortKey;
      if (!key || typeof opts.onSortChange !== "function") return;
      opts.onSortChange(_nextSort(currentSort, key));
    });
  });
}

export function renderPosterGrid(container, rows, opts = {}) {
  if (!container) return;
  if (!Array.isArray(rows) || rows.length === 0) {
    container.innerHTML = `<div class="v5-library-empty">Aucun film ne correspond aux filtres.</div>`;
    return;
  }
  const cards = rows.map((r, idx) => {
    const tier = String(r.tier_v2 || "unknown").toLowerCase();
    const score = r.score_v2 != null ? Math.round(Number(r.score_v2)) : "?";
    const posterStyle = r.poster_url ? `background-image: url('${escapeHtml(r.poster_url)}')` : "";
    return `
      <article class="v5-poster-card v5-poster-card--library stagger-item"
               role="listitem" style="--order: ${Math.min(idx, 20)}"
               data-row-id="${escapeHtml(r.row_id)}" tabindex="0"
               aria-label="${escapeHtml(r.title || "Film")}, score ${escapeHtml(score)}">
        <div class="v5-poster-image" style="${posterStyle}">
          ${!r.poster_url ? `<div class="v5-poster-placeholder">${_svg('<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>', 32)}</div>` : ""}
          <div class="v5-poster-score-overlay v5-poster-score-overlay--${escapeHtml(tier)}">${escapeHtml(score)}</div>
        </div>
        <div class="v5-poster-meta">
          <div class="v5-poster-title v5u-truncate">${escapeHtml(r.title || "?")}</div>
          <div class="v5-poster-sub v5u-text-muted">${escapeHtml(r.year || "")} · ${escapeHtml(String(r.resolution || "").toUpperCase())}</div>
        </div>
      </article>`;
  }).join("");
  container.innerHTML = `<div class="v5-poster-grid" role="list">${cards}</div>`;
  container.querySelectorAll("[data-row-id]").forEach((card) => {
    const activate = () => {
      if (typeof opts.onRowClick === "function") opts.onRowClick(card.dataset.rowId);
    };
    card.addEventListener("click", activate);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); activate(); }
    });
  });
}

export function renderSmartPlaylists(container, playlists, opts = {}) {
  if (!container) return;
  playlists = Array.isArray(playlists) ? playlists : [];

  const items = playlists.map((p) => {
    const isActive = p.id === opts.activeId;
    const isPreset = !!p.preset;
    const deleteBtn = !isPreset ? `<button type="button" class="v5-btn v5-btn--sm v5-btn--ghost v5-btn--icon"
             data-playlist-delete="${escapeHtml(p.id)}" aria-label="Supprimer">
         ${_svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>', 12)}
       </button>` : "";
    return `
      <div class="v5-playlist-item ${isActive ? "is-active" : ""} ${isPreset ? "is-preset" : ""}"
           data-playlist-id="${escapeHtml(p.id)}">
        <button type="button" class="v5-playlist-name" data-playlist-select="${escapeHtml(p.id)}">
          ${escapeHtml(p.name)}
          ${isPreset ? '<span class="v5-playlist-preset-badge">preset</span>' : ""}
        </button>
        ${deleteBtn}
      </div>`;
  }).join("");

  container.innerHTML = `
    <div class="v5-playlists-wrap">
      <div class="v5-playlists-header">
        <h3 class="v5-playlists-title">Smart Playlists</h3>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-playlist-save-current>
          ${_svg('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>', 14)}
          Sauvegarder filtres
        </button>
      </div>
      <div class="v5-playlists-list" role="list">
        ${items || `<div class="v5u-text-muted v5u-p-3">Aucune playlist.</div>`}
      </div>
    </div>`;

  container.querySelectorAll("[data-playlist-select]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.playlistSelect;
      const pl = playlists.find((p) => p.id === id);
      if (pl && typeof opts.onSelect === "function") opts.onSelect(pl);
    });
  });
  container.querySelectorAll("[data-playlist-delete]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (typeof opts.onDelete === "function") opts.onDelete(btn.dataset.playlistDelete);
    });
  });
  const saveBtn = container.querySelector("[data-playlist-save-current]");
  if (saveBtn && typeof opts.onSaveCurrent === "function") {
    saveBtn.addEventListener("click", () => opts.onSaveCurrent());
  }
}
