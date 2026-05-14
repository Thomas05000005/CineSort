/* views/library.js — Bibliotheque de films du dashboard distant */

import { $, escapeHtml, safeUrl } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { tableHtml, attachSort } from "../components/table.js";
import { badgeHtml, scoreBadgeHtml, tierPill } from "../components/badge.js";
import { showModal } from "../components/modal.js";
import { fmtDate as _fmtTs } from "../core/format.js";
import { skeletonViewHtml, skeletonLinesHtml } from "../components/skeleton.js";
import { scrapingStatusHtml } from "../components/scraping-status.js";
import { renderScoreV2Container, bindScoreV2Events } from "../components/score-v2.js";
import { glossaryTooltip } from "../components/glossary-tooltip.js";
import { virtualizeTbody, destroyVirtualization } from "../components/virtual-table.js";

/* V5-01 : seuil au-dela duquel on active le windowing.
 * En dessous, fallback transparent vers tbody.innerHTML simple (zero overhead). */
const _VIRT_THRESHOLD = 500;
/* Handle de virtualisation actif (pour cleanup au filtre/refresh). */
let _virtHandle = null;

/* --- Etat local -------------------------------------------- */

let _allRows = [];
let _filteredRows = [];
let _filters = { search: "", tiers: new Set(), confidence: new Set() };
let _debounceTimer = null;
let _viewMode = (() => {
  try { return localStorage.getItem("cinesort.library.viewMode") || "table"; }
  catch { return "table"; }
})();
let _posterCache = new Map();
let _posterFetchPromise = null;
/* G7 : bulk ops */
let _selectedIds = new Set();

/* --- Colonnes de la table ---------------------------------- */

function _rowIdOf(row) {
  return String(row.row_id || row.id || row.proposed_title || "");
}

const _COLUMNS = [
  { key: "_sel", label: "", sortable: false, render: (_v, row) => {
    const rid = _rowIdOf(row);
    const checked = _selectedIds.has(rid) ? "checked" : "";
    return `<input type="checkbox" class="lib-sel" data-row-id="${window.escapeHtml ? window.escapeHtml(rid) : rid}" ${checked} onclick="event.stopPropagation()" />`;
  }},
  { key: "proposed_title", label: "Titre", sortable: true },
  { key: "proposed_year", label: "Annee", sortable: true },
  { key: "resolution", label: "Resolution", sortable: true },
  { key: "score", label: "Score", sortable: true, render: (v) => v != null ? `${Math.round(v)}` : "—" },
  { key: "tier", label: "Tier", sortable: true, render: (v) => tierPill(v, { compact: true }) },
  { key: "scrape_status", label: "Scraping", sortable: false, render: (_v, row) => scrapingStatusHtml(row, window.__dashSettings || {}) },
  { key: "confidence_label", label: "Confiance", sortable: true, render: (v) => badgeHtml("confidence", v) },
  { key: "source", label: "Source", sortable: true },
  { key: "warning_flags", label: "Alertes", render: (v) => {
    if (!v) return "";
    const flags = Array.isArray(v) ? v : String(v).split(",").map((s) => s.trim()).filter(Boolean);
    return flags.length ? `<span class="badge badge-warning">${flags.length}</span>` : "";
  }},
];

/* --- Chargement -------------------------------------------- */

async function _load() {
  const container = $("libraryContent");
  if (!container) return;

  // V5-01 : cleanup virtualisation precedente (changement de run, refresh, etc.)
  if (_virtHandle && typeof _virtHandle.destroy === "function") {
    try { _virtHandle.destroy(); } catch { /* noop */ }
    _virtHandle = null;
  }

  // V2-D (a11y) : annonce "chargement en cours" aux lecteurs d'ecran.
  container.setAttribute("aria-busy", "true");
  container.innerHTML = skeletonViewHtml();

  try {
    const res = await apiPost("get_dashboard", { run_id: "latest" });
    const d = res.data || {};

    if (!d.ok && !d.rows) {
      container.innerHTML = '<div class="card"><p class="text-muted">Aucun run disponible.</p></div>';
      return;
    }

    _allRows = _normalizeRows(d.rows || []);
    _filters = { search: "", tiers: new Set(), confidence: new Set() };
    _filteredRows = [..._allRows];

    _renderFull(container);
  } catch (err) {
    container.innerHTML = `<p class="status-msg error">Erreur : ${escapeHtml(String(err))}</p>`;
  } finally {
    // V2-D (a11y) : retombe a "false" meme en cas d'erreur.
    container.setAttribute("aria-busy", "false");
  }
}

/* --- Normaliser les rows ----------------------------------- */

function _normalizeRows(rows) {
  return rows.map((r) => ({
    ...r,
    proposed_title: r.proposed_title || r.title || "",
    proposed_year: r.proposed_year || r.year || 0,
    resolution: r.resolution || r.probe_quality || "",
    score: r.score ?? r.quality_score ?? null,
    tier: _tierFromScore(r.score ?? r.quality_score),
    confidence_label: _confidenceLabel(r.confidence),
    source: r.source || "",
    warning_flags: r.warning_flags || r.warnings || "",
  }));
}

function _tierFromScore(score) {
  if (score == null) return "";
  const s = Number(score);
  if (s >= 85) return "premium";
  if (s >= 68) return "bon";
  if (s >= 54) return "moyen";
  return "mauvais";
}

function _confidenceLabel(conf) {
  const c = Number(conf) || 0;
  if (c >= 80) return "high";
  if (c >= 60) return "med";
  return "low";
}

/* --- Rendu complet ----------------------------------------- */

function _renderFull(container) {
  let html = "";

  // Barre de recherche + filtres + toggle vue
  html += '<div class="library-toolbar">';
  html += '<input id="librarySearch" type="text" class="input search-input" placeholder="Rechercher un titre...">';
  html += '<div class="filter-group" id="libraryFilters">';
  html += _filterBtnsHtml(
    "tier",
    ["platinum", "gold", "silver", "bronze", "reject"],
    ["Platinum", "Gold", "Silver", "Bronze", "Reject"],
  );
  html += "</div>";
  html += `<div class="view-mode-toggle" role="radiogroup" aria-label="Mode d'affichage">
    <button type="button" class="btn btn--compact${_viewMode === "table" ? " is-active" : ""}" data-view-mode="table" role="radio" aria-checked="${_viewMode === "table"}">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
      Table
    </button>
    <button type="button" class="btn btn--compact${_viewMode === "grid" ? " is-active" : ""}" data-view-mode="grid" role="radio" aria-checked="${_viewMode === "grid"}">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
      Mosa&iuml;que
    </button>
  </div>`;
  html += "</div>";

  // Distribution tiers (bar chart SVG)
  html += '<div id="libraryChart" class="mt-4"></div>';

  // Vue dynamique (table ou mosaique)
  html += '<div id="libraryTable" class="mt-4"></div>';

  container.innerHTML = html;

  _renderChart();
  _renderView();
  _hookSearch();
  _hookFilterBtns();
  _hookViewToggle();
  _hookBulkSelection();
  _renderBulkBar();
}

/* --- Bulk ops (G7) ---------------------------------------- */

function _renderBulkBar() {
  let bar = document.getElementById("libBulkBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "libBulkBar";
    bar.className = "lib-bulk-bar";
    bar.innerHTML = `
      <span class="lib-bulk-bar__count" id="libBulkCount"></span>
      <button type="button" class="btn btn--compact" data-bulk="reanalyze">Re-analyser qualite</button>
      <button type="button" class="btn btn--compact" data-bulk="export-csv">Exporter CSV</button>
      <button type="button" class="btn btn--compact" data-bulk="clear">Tout deselectionner</button>`;
    document.body.appendChild(bar);
    bar.addEventListener("click", _onBulkAction);
  }
  const count = _selectedIds.size;
  bar.classList.toggle("is-visible", count > 0);
  const c = document.getElementById("libBulkCount");
  if (c) c.textContent = `${count} film${count > 1 ? "s" : ""} selectionne${count > 1 ? "s" : ""}`;
}

async function _onBulkAction(e) {
  const btn = e.target.closest("[data-bulk]");
  if (!btn) return;
  const action = btn.dataset.bulk;
  const ids = Array.from(_selectedIds);

  if (action === "clear") {
    _selectedIds.clear();
    _renderView();
    _renderBulkBar();
    return;
  }
  if (action === "reanalyze") {
    try {
      await apiPost("analyze_quality_batch", { run_id: "latest", row_ids: ids, options: { reuse_existing: false } });
      if (window.toast) window.toast({ type: "success", text: `Re-analyse lancee pour ${ids.length} film(s).` });
    } catch (err) {
      if (window.toast) window.toast({ type: "error", text: "Re-analyse impossible." });
    }
    return;
  }
  if (action === "export-csv") {
    /* Simple export CSV client-side depuis _filteredRows */
    const selected = _allRows.filter((r) => _selectedIds.has(_rowIdOf(r)));
    if (selected.length === 0) return;
    const header = ["row_id", "title", "year", "score", "tier", "resolution"];
    const lines = [header.join(",")];
    for (const r of selected) {
      const row = [r.row_id, `"${(r.proposed_title || "").replace(/"/g, '""')}"`, r.proposed_year, r.score ?? "", r.tier || "", r.resolution || ""];
      lines.push(row.join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cinesort_selection_${Date.now()}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    if (window.toast) window.toast({ type: "success", text: `Export CSV : ${selected.length} lignes.` });
  }
}

function _hookBulkSelection() {
  const container = document.getElementById("libraryTable");
  if (!container) return;
  container.addEventListener("change", (e) => {
    const ck = e.target.closest(".lib-sel");
    if (!ck) return;
    const rid = ck.dataset.rowId;
    if (!rid) return;
    if (ck.checked) _selectedIds.add(rid);
    else _selectedIds.delete(rid);
    _renderBulkBar();
  });
}

function _renderView() {
  if (_viewMode === "grid") _renderMosaic();
  else _renderTable();
}

/* --- Mosaïque posters (F1) -------------------------------- */

async function _renderMosaic() {
  const el = $("libraryTable");
  if (!el) return;

  if (_filteredRows.length === 0) {
    el.innerHTML = '<p class="text-muted" style="text-align:center;padding:32px">Aucun film.</p>';
    return;
  }

  /* Precharge posters (batch) */
  await _prefetchPosters(_filteredRows);

  let html = '<div class="film-grid">';
  for (let i = 0; i < _filteredRows.length; i++) {
    const row = _filteredRows[i];
    const posterUrl = _posterForRow(row);
    const title = escapeHtml(row.proposed_title || "Sans titre");
    const year = row.proposed_year ? ` (${row.proposed_year})` : "";
    const tier = row.tier || "";
    // Cf issue #67 : valider scheme + escape posterUrl avant injection dans src=""
    const safePoster = posterUrl ? safeUrl(posterUrl) : "";
    const posterHtml = safePoster
      ? `<img class="film-tile__poster" src="${safePoster}" alt="Affiche ${title}" loading="lazy" />`
      : `<div class="film-tile__poster film-tile__poster--empty" aria-hidden="true"><svg viewBox="0 0 24 24" width="42" height="42" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg></div>`;
    const tierBadge = tier ? `<span class="film-tile__tier">${tierPill(tier, { compact: true })}</span>` : "";
    html += `<button class="film-tile" data-row-idx="${i}" type="button" aria-label="Voir ${title}${year}">
      ${posterHtml}
      ${tierBadge}
      <div class="film-tile__label">
        <div class="film-tile__title">${title}</div>
        <div class="film-tile__year">${escapeHtml(year.trim())}</div>
      </div>
    </button>`;
  }
  html += "</div>";
  el.innerHTML = html;

  /* Click -> detail modal */
  el.querySelectorAll(".film-tile").forEach((tile) => {
    tile.addEventListener("click", () => {
      const idx = Number(tile.dataset.rowIdx);
      if (!Number.isNaN(idx)) _showDetail(_filteredRows[idx]);
    });
  });
}

function _posterForRow(row) {
  const tmdbId = row.tmdb_id || (row.candidates && row.candidates[0] && row.candidates[0].tmdb_id);
  if (!tmdbId) return null;
  return _posterCache.get(Number(tmdbId)) || null;
}

async function _prefetchPosters(rows) {
  const ids = rows
    .map((r) => r.tmdb_id || (r.candidates && r.candidates[0] && r.candidates[0].tmdb_id))
    .map((v) => Number(v))
    .filter((v) => v > 0 && !_posterCache.has(v));
  if (ids.length === 0) return;
  if (_posterFetchPromise) return _posterFetchPromise;
  _posterFetchPromise = (async () => {
    try {
      const res = await apiPost("get_tmdb_posters", { tmdb_ids: ids, size: "w342" });
      const posters = res && res.data && res.data.posters ? res.data.posters : {};
      for (const [id, url] of Object.entries(posters)) {
        _posterCache.set(Number(id), url);
      }
    } catch (e) { console.warn("[mosaic] poster batch failed", e); }
    finally { _posterFetchPromise = null; }
  })();
  return _posterFetchPromise;
}

function _hookViewToggle() {
  const buttons = document.querySelectorAll("[data-view-mode]");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.viewMode;
      if (mode === _viewMode) return;
      _viewMode = mode;
      try { localStorage.setItem("cinesort.library.viewMode", mode); } catch { /* ignore */ }
      buttons.forEach((b) => {
        const active = b.dataset.viewMode === mode;
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-checked", active ? "true" : "false");
      });
      _renderView();
    });
  });
}

/* --- Bar chart SVG distribution tiers ---------------------- */

function _renderChart() {
  const el = $("libraryChart");
  if (!el) return;

  // U1 audit : 5 tiers modernes + retro-compat sur les valeurs legacy
  const counts = { platinum: 0, gold: 0, silver: 0, bronze: 0, reject: 0 };
  const _tierAlias = { premium: "platinum", bon: "gold", moyen: "silver", faible: "bronze", mauvais: "reject" };
  for (const r of _allRows) {
    const key = _tierAlias[r.tier] || r.tier;
    if (key && counts[key] !== undefined) counts[key]++;
  }
  const total = _allRows.length || 1;
  const colors = {
    platinum: "var(--success)",
    gold: "var(--accent)",
    silver: "var(--info)",
    bronze: "var(--warning)",
    reject: "var(--danger)",
  };
  const labels = { platinum: "Platinum", gold: "Gold", silver: "Silver", bronze: "Bronze", reject: "Reject" };

  let svg = '<svg class="tier-chart" viewBox="0 0 400 100" xmlns="http://www.w3.org/2000/svg">';
  let y = 5;
  for (const tier of ["premium", "bon", "moyen", "mauvais"]) {
    const pct = Math.round((counts[tier] / total) * 100);
    const w = Math.max(2, (counts[tier] / total) * 300);
    svg += `<text x="0" y="${y + 12}" fill="var(--text-secondary)" font-size="11">${labels[tier]}</text>`;
    svg += `<rect x="80" y="${y}" width="${w}" height="16" rx="3" fill="${colors[tier]}" opacity="0.8"/>`;
    svg += `<text x="${82 + w}" y="${y + 12}" fill="var(--text-secondary)" font-size="10">${counts[tier]} (${pct}%)</text>`;
    y += 24;
  }
  svg += "</svg>";
  el.innerHTML = svg;
}

/* --- Table ------------------------------------------------- */

/* V5-01 : rendu d'une ligne extrait pour le pattern windowing. */
function _renderLibraryRowHtml(row, i) {
  let html = `<tr data-row-idx="${i}" class="tr-clickable">`;
  for (const col of _COLUMNS) {
    const raw = row[col.key];
    const cell = col.render ? col.render(raw, row) : escapeHtml(String(raw ?? ""));
    html += `<td>${cell}</td>`;
  }
  html += "</tr>";
  return html;
}

function _renderTable() {
  const el = $("libraryTable");
  if (!el) return;

  // V5-01 : cleanup virtualisation precedente avant re-render.
  if (_virtHandle && typeof _virtHandle.destroy === "function") {
    try { _virtHandle.destroy(); } catch { /* noop */ }
    _virtHandle = null;
  }

  // V5-01 : on instrumente le boot pour mesurer le gain en presence de tres
  // grosses bibliotheques. console.time/timeEnd ignore en prod si pas devtools.
  const tStart = (typeof performance !== "undefined" && performance.now) ? performance.now() : 0;

  // 1) On rend toujours la coquille de la table (header + tbody vide) via
  // tableHtml — ainsi attachSort + le tri client continuent de fonctionner.
  el.innerHTML = tableHtml({
    columns: _COLUMNS,
    rows: [],
    id: "libTable",
    emptyText: "Aucun film.",
    clickable: true,
  });

  const table = el.querySelector("#libTable");
  const tbody = table ? table.querySelector("tbody") : null;

  if (!tbody) {
    // Fallback safe : retombe sur le rendu original si la structure differe.
    el.innerHTML = tableHtml({
      columns: _COLUMNS,
      rows: _filteredRows,
      id: "libTable",
      emptyText: "Aucun film.",
      clickable: true,
    });
  } else if (_filteredRows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${_COLUMNS.length}" class="text-muted" style="text-align:center">Aucun film.</td></tr>`;
  } else {
    // 2) Virtualisation transparente. Si rows <= _VIRT_THRESHOLD, le helper
    // retombe sur tbody.innerHTML simple (comportement identique a avant).
    _virtHandle = virtualizeTbody(tbody, _filteredRows, _renderLibraryRowHtml, {
      threshold: _VIRT_THRESHOLD,
      colspan: _COLUMNS.length,
    });
  }

  attachSort("libTable", _filteredRows, () => _renderTable());

  // Clic sur ligne → modale detail. Event delegation sur tbody pour couvrir
  // les rows render dynamiquement par le windowing au scroll.
  if (tbody && !tbody._libClickBound) {
    tbody.addEventListener("click", (e) => {
      const tr = e.target.closest(".tr-clickable");
      if (!tr) return;
      // Ignore les clics sur les checkboxes bulk (gere par _hookBulkSelection).
      if (e.target.closest(".lib-sel")) return;
      const idx = parseInt(tr.dataset.rowIdx, 10);
      const row = _filteredRows[idx];
      if (row) _showDetail(row);
    });
    tbody._libClickBound = true;
  }

  if (tStart && typeof console !== "undefined" && _filteredRows.length > _VIRT_THRESHOLD) {
    const dt = ((typeof performance !== "undefined" && performance.now) ? performance.now() : 0) - tStart;
    try { console.debug(`[library] _renderTable ${_filteredRows.length} rows in ${dt.toFixed(1)}ms (virtualized=${!!(_virtHandle && _virtHandle.isVirtualized)})`); } catch { /* noop */ }
  }
}

/* --- Recherche --------------------------------------------- */

function _hookSearch() {
  const input = $("librarySearch");
  if (!input) return;
  input.addEventListener("input", () => {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => {
      _filters.search = input.value.trim().toLowerCase();
      _applyFilters();
    }, 300);
  });
}

/* --- Filtres toggle tier ----------------------------------- */

function _filterBtnsHtml(group, keys, labels) {
  return keys.map((k, i) =>
    `<button class="btn btn-filter" data-filter-group="${group}" data-filter-key="${k}">${escapeHtml(labels[i])}</button>`
  ).join("");
}

function _hookFilterBtns() {
  const container = $("libraryFilters");
  if (!container) return;
  container.querySelectorAll(".btn-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      const group = btn.dataset.filterGroup;
      const key = btn.dataset.filterKey;
      const set = group === "tier" ? _filters.tiers : _filters.confidence;
      if (set.has(key)) { set.delete(key); btn.classList.remove("active"); }
      else { set.add(key); btn.classList.add("active"); }
      _applyFilters();
    });
  });
}

function _applyFilters() {
  _filteredRows = _allRows.filter((r) => {
    if (_filters.search && !(r.proposed_title || "").toLowerCase().includes(_filters.search)) return false;
    if (_filters.tiers.size > 0 && !_filters.tiers.has(r.tier)) return false;
    if (_filters.confidence.size > 0 && !_filters.confidence.has(r.confidence_label)) return false;
    return true;
  });
  _renderTable();
}

/* --- Modale detail film ------------------------------------ */

function _showDetail(row) {
  const title = escapeHtml(row.proposed_title || "Film");
  let body = '<div class="detail-grid">';
  body += _detailLine("Titre", row.proposed_title);
  body += _detailLine("Annee", row.proposed_year);
  body += _detailLine("Dossier", row.folder || row.path);
  body += _detailLine("Source", row.source);
  body += _detailLine("Confiance", row.confidence);
  body += _detailLine("Resolution", row.resolution);
  body += _detailLine("Codec video", row.video_codec);
  body += _detailLine("Codec audio", row.audio_codec);
  body += _detailLine("Canaux", row.channels);
  if (row.hdr) {
    const hdrTerm = String(row.hdr).includes("HDR10+") ? "HDR10+" : (String(row.hdr).includes("Dolby") ? "Dolby Vision" : null);
    const hdrLabel = hdrTerm ? glossaryTooltip(hdrTerm, "HDR") : escapeHtml("HDR");
    body += `<div class="detail-row"><span class="detail-label">${hdrLabel}</span><span>${escapeHtml(String(row.hdr))}</span></div>`;
  }
  if (row.bitrate != null && row.bitrate !== "") {
    body += `<div class="detail-row"><span class="detail-label">${glossaryTooltip("Bitrate")}</span><span>${escapeHtml(String(row.bitrate))}</span></div>`;
  }

  if (row.score != null) {
    body += `<div class="detail-row"><span class="detail-label">Score</span><span>${Math.round(row.score)} ${scoreBadgeHtml(row.score)}</span></div>`;
  }

  // Sous-titres
  if (row.subtitle_count != null) {
    body += _detailLine("Sous-titres", `${row.subtitle_count} (${row.subtitle_languages || "—"})`);
  }

  // Warnings
  const flags = Array.isArray(row.warning_flags) ? row.warning_flags : String(row.warning_flags || "").split(",").filter(Boolean);
  if (flags.length) {
    body += `<div class="detail-row"><span class="detail-label">Alertes</span><span>${flags.map((f) => `<span class="badge badge-warning">${escapeHtml(f.trim())}</span>`).join(" ")}</span></div>`;
  }

  // Sous-titres detailles
  if (row.subtitle_count > 0 || row.subtitle_missing_langs || row.subtitle_orphans) {
    body += `<div class="detail-row"><span class="detail-label">Langues ST</span><span>${escapeHtml(row.subtitle_languages || "—")}</span></div>`;
    body += `<div class="detail-row"><span class="detail-label">Formats ST</span><span>${escapeHtml(row.subtitle_formats || "—")}</span></div>`;
    if (row.subtitle_missing_langs) body += `<div class="detail-row"><span class="detail-label">ST manquants</span><span class="badge badge-warning">${escapeHtml(row.subtitle_missing_langs)}</span></div>`;
    if (row.subtitle_orphans) body += `<div class="detail-row"><span class="detail-label">ST orphelins</span><span class="badge badge-danger">${row.subtitle_orphans}</span></div>`;
  }

  // Edition / Collection
  if (row.edition) body += _detailLine("Edition", row.edition);
  if (row.tmdb_collection_name) body += _detailLine("Saga", row.tmdb_collection_name);

  body += "</div>";

  // Candidats TMDb
  const cands = Array.isArray(row.candidates) ? row.candidates : [];
  if (cands.length > 0) {
    body += `<details style="margin-top:12px"><summary style="cursor:pointer;font-weight:600;font-size:var(--fs-sm)">Candidats TMDb (${cands.length})</summary>`;
    body += '<div style="margin-top:4px">';
    for (const c of cands) {
      const selected = c.tmdb_id && row.chosen_tmdb_id && String(c.tmdb_id) === String(row.chosen_tmdb_id);
      body += `<div style="padding:4px 0;border-bottom:1px solid var(--border);${selected ? 'color:var(--accent);font-weight:600' : ''}">`;
      body += `${escapeHtml(c.title || "?")} (${c.year || "?"}) `;
      body += `<span class="text-muted">score=${(c.score * 100).toFixed(0)}% src=${escapeHtml(c.source || "?")}</span>`;
      if (c.tmdb_id) body += ` <span class="text-muted">tmdb:${c.tmdb_id}</span>`;
      body += `</div>`;
    }
    body += '</div></details>';
  }

  body += `<div style="margin-top:12px"><button class="btn btn--compact" id="btnFilmHistory">Historique</button> <button class="btn btn--compact" id="btnDashPerceptual">Analyse perceptuelle</button> <button class="btn btn--compact" id="btnDashExplainScore">Détail du score</button></div>`;
  body += `<div id="filmTimelineContainer"></div>`;
  body += `<div id="dashPerceptualContainer"></div>`;
  body += `<div id="dashExplainScoreContainer"></div>`;

  showModal({ title: `${title} (${row.proposed_year || "?"})`, body });

  const btnHist = document.getElementById("btnFilmHistory");
  if (btnHist) btnHist.addEventListener("click", () => _loadFilmHistory(row));
  const btnPerc = document.getElementById("btnDashPerceptual");
  if (btnPerc) btnPerc.addEventListener("click", () => _loadDashPerceptual(row));
  const btnExpl = document.getElementById("btnDashExplainScore");
  if (btnExpl) btnExpl.addEventListener("click", () => _loadDashExplainScore(row));
}

async function _loadDashPerceptual(row) {
  const container = document.getElementById("dashPerceptualContainer");
  if (!container) return;
  container.innerHTML = `<p class="text-muted">Analyse en cours...</p>`;
  try {
    const r = await apiPost("get_perceptual_report", { run_id: row.run_id || "", row_id: row.row_id || "" });
    if (!r?.data?.ok) { container.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(r?.data?.message || "echec")}</p>`; return; }
    const p = r.data.perceptual || {};
    const cv = p.cross_verdicts || [];
    let html = `<div style="margin-top:8px">`;
    html += `<span class="badge badge-perceptual-${p.global_tier || "degrade"}">${p.global_score ?? "?"}/100 ${p.global_tier || ""}</span>`;
    html += ` <span class="text-muted">Video ${p.visual_score ?? "?"} | Audio ${p.audio_score ?? "?"}</span>`;
    if (cv.length) { cv.forEach(v => { html += `<div class="cross-verdict cross-verdict--${escapeHtml(v.severity || "info")}" style="margin-top:4px">${escapeHtml(v.label || "")}</div>`; }); }
    html += `</div>`;

    // §16b v7.5.0 — Score composite V2 (cercle + jauges + accordeon + warnings)
    const gsv2 = p.global_score_v2;
    if (gsv2) {
      html += `<div style="margin-top:10px"><div class="text-muted font-sm" style="margin-bottom:4px">Score CineSort V2</div>`;
      html += renderScoreV2Container(gsv2);
      html += `</div>`;
    }

    container.innerHTML = html;
    if (gsv2) bindScoreV2Events(container);
  } catch (e) { container.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(e.message)}</p>`; }
}

function _detailLine(label, value) {
  if (value == null || value === "") return "";
  return `<div class="detail-row"><span class="detail-label">${escapeHtml(label)}</span><span>${escapeHtml(String(value))}</span></div>`;
}

/* --- P2.1 : Détail du score ------------------------------- */

function _explainTierColor(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "platinum") return "#A78BFA";
  if (t === "gold") return "#FBBF24";
  if (t === "silver") return "#9CA3AF";
  if (t === "bronze") return "#FB923C";
  return "#EF4444";
}

function _explainDeltaColor(weighted) {
  const v = Number(weighted || 0);
  if (v > 0.5) return "#34D399";
  if (v > 0) return "#A7F3D0";
  if (v < -0.5) return "#EF4444";
  if (v < 0) return "#FCA5A5";
  return "var(--text-muted)";
}

function _explainFmtDelta(w) {
  const v = Number(w || 0);
  if (v === 0) return "0";
  return (v > 0 ? "+" : "") + v.toFixed(1);
}

function _explainCatLabel(cat) {
  return { video: "Vidéo", audio: "Audio", extras: "Extras", custom: "Règle", probe: "Sonde", perceptual: "Perceptuel" }[cat] || cat;
}

function _buildDashExplainHtml(data) {
  const score = Number(data.score || 0);
  const tier = String(data.tier || "?");
  const expl = data.explanation || data.metrics?.score_explanation || {};
  const narrative = expl.narrative || "—";
  const categories = expl.categories || {};
  const factors = expl.factors || [];
  const suggestions = expl.suggestions || [];
  const baseline = expl.baseline || {};
  const tierColor = _explainTierColor(tier);

  // Header
  let html = `<div style="margin-top:12px; padding:8px; border-left:4px solid ${tierColor}; background:var(--bg-raised); border-radius:4px">
    <div style="display:flex; gap:12px; align-items:center">
      <div style="font-size:1.8em; font-weight:700; color:${tierColor}">${score}</div>
      <div>
        <div><strong>${escapeHtml(tier)}</strong> <span class="text-muted" style="font-size:var(--fs-xs)">/100</span></div>
        ${baseline.next_tier && baseline.distance_to_next_tier != null ? `<div class="text-muted" style="font-size:var(--fs-xs)">À ${baseline.distance_to_next_tier} pt(s) du tier ${escapeHtml(baseline.next_tier)}</div>` : ""}
      </div>
    </div>
    <p style="font-style:italic; font-size:var(--fs-sm); color:var(--text-muted); margin:6px 0 0">${escapeHtml(narrative)}</p>
  </div>`;

  // Categories bars
  html += '<div style="margin-top:10px"><div class="text-muted" style="font-size:var(--fs-xs); font-weight:600; margin-bottom:4px">Contribution par catégorie</div>';
  for (const cat of ["video", "audio", "extras"]) {
    const c = categories[cat] || {};
    const sub = c.subscore || 0;
    const weight = c.weight_pct || 0;
    const contrib = c.contribution || 0;
    const posC = c.positive_count || 0;
    const negC = c.negative_count || 0;
    const pct = Math.max(0, Math.min(100, sub));
    const fill = sub >= 85 ? "#A78BFA" : sub >= 68 ? "#FBBF24" : sub >= 54 ? "#9CA3AF" : sub >= 30 ? "#FB923C" : "#EF4444";
    html += `<div style="margin-bottom:6px">
      <div style="display:flex; justify-content:space-between; font-size:var(--fs-sm)">
        <strong>${escapeHtml(c.label || cat)}</strong>
        <span class="text-muted" style="font-size:var(--fs-xs)">${weight}% · contrib. ${contrib.toFixed(1)}/100</span>
      </div>
      <div style="height:8px; background:var(--bg-raised); border-radius:4px; overflow:hidden; margin:3px 0"><div style="width:${pct}%; height:100%; background:${fill}"></div></div>
      <div class="text-muted" style="font-size:var(--fs-xs)">${sub}/100 · ${posC} atout(s), ${negC} pénalité(s)</div>
    </div>`;
  }
  html += '</div>';

  // Factors table
  const sorted = [...factors].sort((a, b) => Math.abs(Number(b.weighted_delta || 0)) - Math.abs(Number(a.weighted_delta || 0)));
  if (sorted.length) {
    html += '<div style="margin-top:10px"><div class="text-muted" style="font-size:var(--fs-xs); font-weight:600; margin-bottom:4px">Règles appliquées (par impact)</div>';
    html += '<table style="width:100%; border-collapse:collapse"><thead><tr style="font-size:var(--fs-xs); color:var(--text-muted)"><th style="text-align:left; padding:2px 4px">Catégorie</th><th style="text-align:left; padding:2px 4px">Règle</th><th style="text-align:right; padding:2px 4px">Impact</th></tr></thead><tbody>';
    for (const f of sorted.slice(0, 20)) {
      const wd = Number(f.weighted_delta || 0);
      html += `<tr style="font-size:var(--fs-xs)"><td style="padding:1px 4px; color:var(--text-muted)">${escapeHtml(_explainCatLabel(f.category))}</td><td style="padding:1px 4px">${escapeHtml(f.label || "")}</td><td style="padding:1px 4px; text-align:right; color:${_explainDeltaColor(wd)}; font-weight:600">${_explainFmtDelta(wd)}</td></tr>`;
    }
    if (sorted.length > 20) html += `<tr><td colspan="3" style="text-align:center; font-size:var(--fs-xs); color:var(--text-muted); padding:3px">... ${sorted.length - 20} autre(s) facteur(s)</td></tr>`;
    html += '</tbody></table></div>';
  }

  // Suggestions
  if (Array.isArray(suggestions) && suggestions.length) {
    html += '<div style="margin-top:10px; padding:8px; background:rgba(245,158,11,.1); border-left:3px solid #F59E0B; border-radius:4px">';
    html += '<div style="color:#F59E0B; font-weight:600; font-size:var(--fs-sm); margin-bottom:3px">Pour améliorer :</div>';
    html += '<ul style="margin:0; padding-left:18px; font-size:var(--fs-sm)">';
    for (const s of suggestions) html += `<li>${escapeHtml(s)}</li>`;
    html += '</ul></div>';
  }

  return html;
}

/* V4.1 : formulaire de feedback de calibration (P4.1) */
function _buildDashFeedbackForm(row) {
  const tierOpts = ["Platinum", "Gold", "Silver", "Bronze", "Reject"]
    .map(t => `<option value="${t}">${t}</option>`).join("");
  const catOpts = `
    <option value="">Aucune</option>
    <option value="video">Vidéo</option>
    <option value="audio">Audio</option>
    <option value="extras">Extras</option>`;
  return `<div style="margin-top:10px; padding:8px; border:1px solid var(--border); border-radius:4px; background:var(--bg-raised)">
    <div style="color:var(--text-muted); font-size:var(--fs-xs); font-weight:600; text-transform:uppercase; letter-spacing:.05em; margin-bottom:4px">Ce score vous semble-t-il juste ?</div>
    <div style="font-size:var(--fs-xs); color:var(--text-muted); margin-bottom:6px">Votre feedback contribue à calibrer le scoring (P4.1). Stocké localement.</div>
    <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:6px; align-items:center">
      <label style="font-size:var(--fs-sm)">Tier attendu :</label>
      <select id="dashFbTier" class="input" style="height:28px; font-size:var(--fs-sm)">${tierOpts}</select>
      <label style="font-size:var(--fs-sm)">Catégorie :</label>
      <select id="dashFbCategory" class="input" style="height:28px; font-size:var(--fs-sm)">${catOpts}</select>
    </div>
    <input id="dashFbComment" class="input" placeholder="Commentaire (optionnel)" style="width:100%; font-size:var(--fs-sm); margin-bottom:6px" />
    <button class="btn btn--compact" id="dashFbSubmit" data-run-id="${escapeHtml(row.run_id || "")}" data-row-id="${escapeHtml(row.row_id || "")}">Enregistrer</button>
    <span id="dashFbResult" style="font-size:var(--fs-sm); margin-left:8px" aria-live="polite"></span>
  </div>`;
}

async function _loadDashExplainScore(row) {
  const container = document.getElementById("dashExplainScoreContainer");
  if (!container) return;
  container.innerHTML = `<p class="text-muted">Chargement du score...</p>`;
  try {
    const r = await apiPost("get_quality_report", { run_id: row.run_id || "", row_id: row.row_id || "" });
    const data = r?.data || {};
    if (!data.ok) {
      container.innerHTML = `<p class="text-muted">${escapeHtml(data.message || "Erreur")}</p>`;
      return;
    }
    container.innerHTML = _buildDashExplainHtml(data) + _buildDashFeedbackForm(row);
    _hookDashFeedbackForm();
  } catch (e) {
    container.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(e.message)}</p>`;
  }
}

function _hookDashFeedbackForm() {
  const btn = document.getElementById("dashFbSubmit");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const runId = btn.dataset.runId || "";
    const rowId = btn.dataset.rowId || "";
    const userTier = document.getElementById("dashFbTier")?.value || "";
    const categoryFocus = document.getElementById("dashFbCategory")?.value || null;
    const comment = document.getElementById("dashFbComment")?.value || null;
    const result = document.getElementById("dashFbResult");
    if (!runId || !rowId || !userTier) return;
    btn.disabled = true;
    if (result) result.textContent = "Enregistrement...";
    try {
      const r = await apiPost("submit_score_feedback", {
        run_id: runId, row_id: rowId, user_tier: userTier,
        category_focus: categoryFocus, comment
      });
      const data = r?.data || {};
      if (data.ok) {
        const delta = Number(data.tier_delta || 0);
        const label = delta === 0 ? "Accord" : (delta > 0 ? `Sous-évalué (+${delta})` : `Sur-évalué (${delta})`);
        if (result) result.innerHTML = `<span style="color:#34D399">✓ Enregistré</span> <span class="text-muted">(${escapeHtml(label)})</span>`;
      } else {
        if (result) result.innerHTML = `<span style="color:#EF4444">${escapeHtml(data.message || "Erreur")}</span>`;
        btn.disabled = false;
      }
    } catch (e) {
      if (result) result.textContent = "Erreur : " + String(e.message || e);
      btn.disabled = false;
    }
  });
}

/* --- Film history timeline ---------------------------------- */

function _filmId(row) {
  const ed = String(row.edition || "").trim().toLowerCase();
  const edSuffix = ed ? "|" + ed : "";
  const cands = Array.isArray(row.candidates) ? row.candidates : [];
  for (const c of cands) {
    if (c.tmdb_id && Number(c.tmdb_id) > 0) return "tmdb:" + c.tmdb_id + edSuffix;
  }
  const title = String(row.proposed_title || "").trim().toLowerCase();
  const year = Number(row.proposed_year || 0);
  return "title:" + title + "|" + year + edSuffix;
}

async function _loadFilmHistory(row) {
  const container = document.getElementById("filmTimelineContainer");
  if (!container) return;
  container.innerHTML = skeletonLinesHtml(4);
  try {
    const r = await apiPost("get_film_history", { film_id: _filmId(row) });
    if (!r?.data?.ok || !(r.data.events || []).length) {
      container.innerHTML = `<p class="text-muted">Aucun historique disponible.</p>`;
      return;
    }
    container.innerHTML = _buildDashHistoryFull(r.data);
  } catch {
    container.innerHTML = `<p class="text-muted">Erreur de chargement.</p>`;
  }
}

/* V4.2 : rendu enrichi historique film dashboard (parite desktop P3.3) */

function _shortenDashPath(p, max = 45) {
  const s = String(p || "");
  if (s.length <= max) return s;
  return s.slice(0, Math.floor(max * 0.4)) + " … " + s.slice(-Math.floor(max * 0.5));
}

function _dashTierColor(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "platinum") return "#A78BFA";
  if (t === "gold") return "#FBBF24";
  if (t === "silver") return "#9CA3AF";
  if (t === "bronze") return "#FB923C";
  return "#EF4444";
}

function _buildDashHistoryHeader(data) {
  const currentScore = data.current_score;
  const events = data.events || [];
  const scoreEvents = events.filter(e => e.type === "score");
  const firstScore = scoreEvents.length > 0 ? Number(scoreEvents[0].score) : null;
  const lastTier = scoreEvents.length > 0 ? String(scoreEvents[scoreEvents.length - 1].tier || "") : "";
  const lastEvent = events[events.length - 1];
  const daysSinceLast = lastEvent ? Math.floor((Date.now() / 1000 - Number(lastEvent.ts || 0)) / 86400) : null;
  const trendDelta = (firstScore != null && currentScore != null) ? (currentScore - firstScore) : 0;
  const tierPillHtml = (currentScore != null && lastTier && typeof tierPill === "function") ? tierPill(lastTier, { compact: false }) : "";
  const trendHtml = trendDelta !== 0
    ? `<span style="font-size:var(--fs-xs); color:${trendDelta > 0 ? "#34D399" : "#EF4444"}; font-weight:600">${trendDelta > 0 ? "↑ +" : "↓ "}${trendDelta}</span>`
    : '<span style="font-size:var(--fs-xs); color:var(--text-muted)">→ stable</span>';

  return `<div style="padding:10px; border:1px solid var(--border); border-radius:4px; background:var(--bg-raised); margin-bottom:10px">
    <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap">
      <div>
        <div style="font-size:var(--fs-xs); color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em">Film</div>
        <div style="font-weight:700">${escapeHtml(data.title || "?")}${data.year ? ` <span class="text-muted">(${data.year})</span>` : ""}</div>
      </div>
      ${currentScore != null ? `
      <div>
        <div style="font-size:var(--fs-xs); color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em">Score</div>
        <div style="display:flex; align-items:center; gap:6px">
          <span style="font-size:1.3em; font-weight:700">${currentScore}</span>
          ${tierPillHtml}
          ${trendHtml}
        </div>
      </div>` : ""}
      <div>
        <div style="font-size:var(--fs-xs); color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em">Activite</div>
        <div style="font-size:var(--fs-sm)"><strong>${data.scan_count || 0}</strong> scan · <strong>${data.apply_count || 0}</strong> apply</div>
        ${daysSinceLast != null ? `<div style="font-size:var(--fs-xs); color:var(--text-muted)">Dernier : il y a ${daysSinceLast}j</div>` : ""}
      </div>
    </div>
  </div>`;
}

function _buildDashSparkline(events) {
  const scorePoints = events.filter(e => e.type === "score" && Number.isFinite(Number(e.score)));
  if (scorePoints.length < 2) return "";
  const w = 640, h = 96, padL = 26, padR = 8, padT = 10, padB = 20;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const scores = scorePoints.map(p => Number(p.score));
  const minS = Math.max(0, Math.min(...scores) - 5);
  const maxS = Math.min(100, Math.max(...scores) + 5);
  const rangeS = Math.max(1, maxS - minS);
  const ts = scorePoints.map(p => Number(p.ts || 0));
  const minT = Math.min(...ts), maxT = Math.max(...ts);
  const rangeT = Math.max(1, maxT - minT);
  const coords = scorePoints.map((p, i) => {
    const x = padL + (innerW * (Number(p.ts || 0) - minT) / rangeT);
    const y = padT + innerH - (innerH * (Number(p.score) - minS) / rangeS);
    return { x, y, p };
  });
  const polyPath = "M " + coords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" L ");
  const areaPath = polyPath + ` L ${coords[coords.length - 1].x},${padT + innerH} L ${coords[0].x},${padT + innerH} Z`;
  const thresholdLines = [
    { y: padT + innerH - (innerH * (85 - minS) / rangeS), color: "#A78BFA", label: "Pt" },
    { y: padT + innerH - (innerH * (68 - minS) / rangeS), color: "#FBBF24", label: "Go" },
    { y: padT + innerH - (innerH * (54 - minS) / rangeS), color: "#9CA3AF", label: "Si" },
  ].filter(l => l.y >= padT && l.y <= padT + innerH);
  const thresholdsHtml = thresholdLines.map(l =>
    `<line x1="${padL}" y1="${l.y}" x2="${padL + innerW}" y2="${l.y}" stroke="${l.color}" stroke-dasharray="2,3" stroke-width="0.5" opacity="0.4"/><text x="${padL - 4}" y="${l.y + 3}" text-anchor="end" font-size="8" fill="${l.color}" opacity="0.7">${l.label}</text>`
  ).join("");
  const pointsHtml = coords.map(c => {
    const color = _dashTierColor(c.p.tier);
    return `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="3" fill="${color}" stroke="var(--bg-raised)" stroke-width="1.5"><title>Score ${c.p.score} (${c.p.tier || "?"})</title></circle>`;
  }).join("");
  const firstScore = scorePoints[0].score;
  const lastScore = scorePoints[scorePoints.length - 1].score;
  const totalDelta = lastScore - firstScore;
  const deltaLabel = totalDelta > 0 ? `+${totalDelta}` : String(totalDelta);
  const deltaColor = totalDelta > 0 ? "#34D399" : totalDelta < 0 ? "#EF4444" : "var(--text-muted)";
  return `<div style="padding:8px; border:1px solid var(--border); border-radius:4px; background:var(--bg-raised); margin-bottom:10px">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px">
      <div style="font-size:var(--fs-xs); color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em">Evolution (${scorePoints.length} mesures)</div>
      <div style="font-size:var(--fs-sm); color:${deltaColor}; font-weight:600">Total ${deltaLabel}</div>
    </div>
    <svg viewBox="0 0 ${w} ${h}" style="width:100%; height:auto; display:block" preserveAspectRatio="xMidYMid meet">
      ${thresholdsHtml}
      <path d="${areaPath}" fill="url(#dashScoreGrad)" opacity="0.2"/>
      <path d="${polyPath}" fill="none" stroke="#60A5FA" stroke-width="2"/>
      ${pointsHtml}
      <defs><linearGradient id="dashScoreGrad" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#60A5FA" stop-opacity="0.6"/><stop offset="100%" stop-color="#60A5FA" stop-opacity="0"/></linearGradient></defs>
    </svg>
  </div>`;
}

function _buildDashTimelineEvents(events) {
  const items = events.map((e, idx) => {
    const date = _fmtTs(e.ts);
    const isLast = idx === events.length - 1;
    const connector = isLast ? "" : '<div style="position:absolute; left:14px; top:24px; bottom:-12px; width:2px; background:var(--border)"></div>';
    let iconColor = "var(--text-muted)"; let icon = "•"; let bodyHtml = "";
    if (e.type === "scan") {
      iconColor = "#60A5FA"; icon = "\u{1F50D}";
      bodyHtml = `<div><strong>Scan</strong> — confiance <strong>${e.confidence}</strong>, source ${escapeHtml(e.source || "?")}</div>`;
    } else if (e.type === "score") {
      iconColor = "#FBBF24"; icon = "⭐";
      const deltaText = e.delta === 0 ? "" : (e.delta > 0 ? ` <span style="color:#34D399">+${e.delta}</span>` : ` <span style="color:#EF4444">${e.delta}</span>`);
      const tierHtml = typeof tierPill === "function" ? tierPill(e.tier || "", { compact: true }) : escapeHtml(String(e.tier || ""));
      bodyHtml = `<div><strong>Score ${e.score}</strong>${deltaText} &nbsp; ${tierHtml}</div>`;
    } else if (e.type === "apply") {
      iconColor = "#34D399"; icon = "\u{1F4C1}";
      const ops = (e.operations || []).map(op => `<div style="font-family:monospace; font-size:var(--fs-xs); color:var(--text-muted)" title="${escapeHtml(op.from || "")} → ${escapeHtml(op.to || "")}">${escapeHtml(_shortenDashPath(op.from || ""))}<br>&nbsp;→ ${escapeHtml(_shortenDashPath(op.to || ""))}</div>`).join("");
      bodyHtml = `<div><strong>Apply</strong> (${(e.operations || []).length} op)</div><div style="margin-top:4px">${ops}</div>`;
    } else {
      bodyHtml = `<div>${escapeHtml(e.type || "?")}</div>`;
    }
    return `<div style="position:relative; padding-left:32px; padding-bottom:14px; min-height:28px">
      <div style="position:absolute; left:4px; top:2px; width:18px; height:18px; border-radius:50%; background:var(--bg-raised); border:2px solid ${iconColor}; display:flex; align-items:center; justify-content:center; font-size:.65em; z-index:2">${icon}</div>
      ${connector}
      <div style="font-size:var(--fs-xs); color:var(--text-muted); margin-bottom:2px">${escapeHtml(date)}</div>
      <div style="font-size:var(--fs-sm)">${bodyHtml}</div>
    </div>`;
  }).join("");
  return `<div style="padding:10px; border:1px solid var(--border); border-radius:4px; background:var(--bg-raised)">
    <div style="font-size:var(--fs-xs); color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em; margin-bottom:6px">Chronologie detaillee</div>
    ${items}
  </div>`;
}

function _buildDashHistoryFull(data) {
  return _buildDashHistoryHeader(data) + _buildDashSparkline(data.events || []) + _buildDashTimelineEvents(data.events || []);
}

/* --- Watchlist import --------------------------------------- */

function _hookWatchlistDash() {
  const container = document.getElementById("libraryWatchlistResults");
  function _importDash(source, file) {
    if (!file || !container) return;
    const reader = new FileReader();
    reader.onload = async () => {
      container.innerHTML = "<p>Analyse...</p>";
      try {
        const r = await apiPost("import_watchlist", { csv_content: reader.result, source });
        if (!r?.data?.ok) { container.innerHTML = `<p class="text-muted">${escapeHtml(r?.data?.message || "Erreur")}</p>`; return; }
        const d = r.data;
        let html = `<div class="sync-summary ${d.missing_count === 0 ? "sync-ok" : "sync-warn"}"><strong>${d.owned_count}</strong> possede(s) — <strong>${d.missing_count}</strong> manquant(s) — <strong>${d.coverage_pct}%</strong></div>`;
        if ((d.missing || []).length) {
          html += '<table class="table"><thead><tr><th>Titre</th><th>Annee</th></tr></thead><tbody>';
          for (const m of (d.missing || []).slice(0, 50)) html += `<tr><td>${escapeHtml(m.title || "")}</td><td>${m.year || ""}</td></tr>`;
          html += "</tbody></table>";
        }
        container.innerHTML = html;
      } catch { container.innerHTML = '<p class="text-muted">Erreur</p>'; }
    };
    reader.readAsText(file, "utf-8");
  }
  const btnLB = document.getElementById("dashFileLetterboxd");
  const btnIMDb = document.getElementById("dashFileImdb");
  if (btnLB) btnLB.addEventListener("change", e => _importDash("letterboxd", e.target.files[0]));
  if (btnIMDb) btnIMDb.addEventListener("change", e => _importDash("imdb", e.target.files[0]));
}

/* --- Point d'entree ---------------------------------------- */

export function initLibrary() {
  _allRows = [];
  _filteredRows = [];
  _load().then(() => _hookWatchlistDash());
}

/* V5-01 : unmount public pour le router (reset virtualisation propre). */
export function unmountLibrary() {
  if (_virtHandle && typeof _virtHandle.destroy === "function") {
    try { _virtHandle.destroy(); } catch { /* noop */ }
    _virtHandle = null;
  }
  // Cleanup explicite du tbody si encore monte (defense en profondeur).
  const table = document.getElementById("libTable");
  if (table) {
    const tbody = table.querySelector("tbody");
    if (tbody) destroyVirtualization(tbody);
  }
}
