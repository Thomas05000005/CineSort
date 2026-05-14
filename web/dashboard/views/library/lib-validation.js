/* lib-validation.js — Section 3 : Validation (table complète, filtres, presets, inspecteur) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiGet, apiPost } from "../../core/api.js";
import { tableHtml, attachSort } from "../../components/table.js";
import { badgeHtml } from "../../components/badge.js";
import { showModal } from "../../components/modal.js";
import { refreshVerification } from "./lib-verification.js";
import { getNavSignal, isAbortError } from "../../core/nav-abort.js";

let _state = null;
let _allRows = [];
let _filteredRows = [];
let _searchTimer = null;
let _filters = { search: "", confidence: "", source: "", preset: "" };

/* --- Colonnes de la table (9 colonnes) ------------------------ */

const _COLUMNS = [
  { key: "_approve", label: "✓/✗", sortable: false, render: (_, row) => _approveCell(row) },
  { key: "confidence", label: "Confiance", sortable: true, render: (v) => badgeHtml("confidence", _confLabel(v)) },
  { key: "kind", label: "Type", sortable: true, render: (v) => v === "tv_episode" ? '<span class="badge badge-saga">Série</span>' : "Film" },
  { key: "folder", label: "Dossier", sortable: false, render: (v) => `<span class="text-muted" title="${escapeHtml(v || "")}">${escapeHtml(_short(v, 30))}</span>` },
  { key: "video_name", label: "Vidéo", sortable: false, render: (v, row) => `<span class="text-muted" title="${escapeHtml(v || row.video_filename || "")}">${escapeHtml(_short(v || row.video_filename || "", 25))}</span>` },
  { key: "proposed_title", label: "Titre", sortable: true, render: (v, row) => _titleCell(v, row) },
  { key: "proposed_year", label: "Année", sortable: true, render: (v, row) => `<input type="number" class="input input--xs" value="${Number(v) || ""}" data-year-rid="${row.row_id || ""}" style="width:70px">` },
  { key: "proposed_source", label: "Source", sortable: true, render: (v) => `<span class="badge">${escapeHtml(v || "?")}</span>` },
  { key: "score", label: "Score", sortable: true, render: (v) => v ? String(Math.round(Number(v))) : "—" },
];

/* --- Point d'entree ------------------------------------------- */

export function initValidation(libState) {
  _state = libState;
  const el = $("libValidationContent");
  if (!el) return;
  _loadRows(el);
}

/* --- Chargement des rows -------------------------------------- */

async function _loadRows(el) {
  if (!_state.runId) {
    el.innerHTML = '<p class="text-muted">Aucun run disponible.</p>';
    return;
  }
  el.innerHTML = '<p class="text-muted">Chargement...</p>';

  try {
    // Audit ID-ROB-002 : Promise.allSettled pour qu'un echec sur load_validation
    // (ex: fichier de validation corrompu) n'empeche pas d'afficher le plan.
    // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur switche route.
    const navSig = getNavSignal();
    const labels = ["get_plan", "load_validation"];
    const results = await Promise.allSettled([
      apiPost("run/get_plan", { run_id: _state.runId }, { signal: navSig }),
      apiPost("load_validation", { run_id: _state.runId }, { signal: navSig }),
    ]);
    const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
    const [planRes, valRes] = results.map(_val);
    const failed = labels.filter((_, i) => results[i].status !== "fulfilled" && !isAbortError(results[i].reason));
    if (failed.length > 0) console.warn("[lib-validation] endpoints en echec:", failed);

    _allRows = Array.isArray(planRes?.data?.rows) ? planRes.data.rows : [];
    _state.rows = _allRows;

    // Restaurer les decisions existantes
    _state.decisions = new Map();
    const saved = valRes?.data?.decisions || valRes?.data || {};
    if (typeof saved === "object" && !Array.isArray(saved)) {
      for (const [id, d] of Object.entries(saved)) {
        if (d && typeof d === "object") {
          if (d.ok === true) _state.decisions.set(id, "approved");
          else if (d.ok === false) _state.decisions.set(id, "rejected");
        }
      }
    }

    // Rafraichir la section Verification
    refreshVerification(_allRows);

    // Rendu complet
    _renderFull(el);
  } catch (err) {
    el.innerHTML = `<p class="status-msg error">Erreur : ${escapeHtml(String(err))}</p>`;
  }
}

/* --- Rendu complet -------------------------------------------- */

function _renderFull(el) {
  let html = "";

  // Compteurs
  html += `<div class="flex gap-4 items-center mb-4" id="libValCounters"></div>`;

  // Filtres
  html += `<div class="flex gap-2 items-center mb-4 flex-wrap">`;
  html += `<input type="text" class="input" placeholder="Rechercher..." id="libValSearch" data-testid="lib-valid-search" style="max-width:200px">`;
  html += `<select class="input" id="libValFilterConf" data-testid="lib-valid-filter-conf" style="max-width:140px">
    <option value="">Confiance : Toutes</option><option value="high">Haute (≥85)</option><option value="med">Moyenne (60-84)</option><option value="low">Basse (&lt;60)</option></select>`;
  html += `<select class="input" id="libValFilterSource" data-testid="lib-valid-filter-source" style="max-width:140px">
    <option value="">Source : Toutes</option><option value="nfo">NFO</option><option value="tmdb">TMDb</option><option value="name">Nom</option></select>`;
  html += `</div>`;

  // Presets
  html += `<div class="flex gap-2 mb-4 flex-wrap" id="libValPresets" data-testid="lib-valid-presets">`;
  for (const [val, label] of [["", "Tous"], ["review", "À revoir"], ["year", "Ajout année"], ["sensitive", "Sensibles"], ["collections", "Collections"], ["low_quality", "Qualité faible"]]) {
    const active = _filters.preset === val ? " active" : "";
    html += `<button class="btn btn--compact${active}" data-preset="${val}">${escapeHtml(label)}</button>`;
  }
  html += `</div>`;

  // Actions bulk
  html += `<div class="flex gap-2 mb-4">`;
  html += `<button id="libBtnApproveAll" class="btn btn--compact" data-testid="lib-valid-btn-check-all">Tout approuver</button>`;
  html += `<button id="libBtnApproveSure" class="btn btn--compact" data-testid="lib-valid-btn-approve-sure">Approuver les sûrs</button>`;
  html += `<button id="libBtnRejectAll" class="btn btn--compact btn-danger" data-testid="lib-valid-btn-uncheck-all">Tout rejeter</button>`;
  html += `<button id="libBtnResetDec" class="btn btn--compact" data-testid="lib-valid-btn-reset">Réinitialiser</button>`;
  html += `<button id="libBtnSaveVal" class="btn btn-primary btn--compact" data-testid="lib-valid-btn-save" style="margin-left:auto">Sauvegarder</button>`;
  html += `<label class="checkbox-row"><input type="checkbox" id="ckQuickReview"> Revue rapide</label>`;
  html += `</div>`;

  // Table
  html += `<div id="libValTable" class="mt-2" data-testid="lib-valid-table"></div>`;

  // Message
  html += `<div id="libValMsg" class="status-msg mt-2"></div>`;

  // Settings inline (mode avance)
  html += `<div class="lib-advanced hidden mt-4 card">`;
  html += `<h4>Paramètres validation</h4>`;
  html += `<div class="flex gap-4 items-center mt-2">`;
  html += `<label>Seuil auto-approve : <input type="range" min="70" max="100" value="${_state.autoThreshold}" id="libValThreshold"> <span id="libValThresholdLbl">${_state.autoThreshold}%</span></label>`;
  html += `</div></div>`;

  el.innerHTML = html;
  _applyFilters();
  _updateCounters();
  _hookValidationEvents();
}

/* --- Table ---------------------------------------------------- */

function _renderTable() {
  const el = $("libValTable");
  if (!el) return;

  el.innerHTML = tableHtml({
    columns: _COLUMNS,
    rows: _filteredRows,
    id: "libValidationTbl",
    emptyText: "Aucun film à afficher.",
    clickable: true,
  });

  // Colorier les lignes
  const tbody = el.querySelector("tbody");
  if (tbody) {
    const trs = tbody.querySelectorAll("tr");
    trs.forEach((tr, i) => {
      const row = _filteredRows[i];
      if (!row) return;
      const dec = _state.decisions.get(String(row.row_id));
      tr.classList.remove("row-approved", "row-rejected");
      if (dec === "approved") tr.classList.add("row-approved");
      else if (dec === "rejected") tr.classList.add("row-rejected");
    });
  }

  // Clic sur ligne → modale inspecteur
  el.querySelectorAll("tr[data-row-idx]").forEach(tr => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("button") || e.target.closest("input")) return;
      const idx = Number(tr.dataset.rowIdx);
      const row = _filteredRows[idx];
      if (row) _showInspector(row);
    });
  });

  // Boutons approve/reject par ligne
  el.querySelectorAll(".btn-review").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const rid = btn.dataset.rid;
      const action = btn.dataset.action;
      _toggleDecision(rid, action);
    });
  });

  // Edition inline annee
  el.querySelectorAll("[data-year-rid]").forEach(input => {
    input.addEventListener("change", () => {
      const rid = input.dataset.yearRid;
      const row = _allRows.find(r => String(r.row_id) === rid);
      if (row) row.proposed_year = input.value;
    });
  });

  attachSort("libValidationTbl", _filteredRows, _renderTable);
}

/* --- Filtres -------------------------------------------------- */

function _applyFilters() {
  _filteredRows = _allRows.filter(row => {
    // Recherche textuelle
    if (_filters.search) {
      const q = _filters.search.toLowerCase();
      const text = `${row.proposed_title || ""} ${row.folder || ""} ${row.video_filename || ""}`.toLowerCase();
      if (!text.includes(q)) return false;
    }
    // Confiance
    if (_filters.confidence) {
      const c = Number(row.confidence || 0);
      if (_filters.confidence === "high" && c < 85) return false;
      if (_filters.confidence === "med" && (c < 60 || c >= 85)) return false;
      if (_filters.confidence === "low" && c >= 60) return false;
    }
    // Source
    if (_filters.source) {
      const s = String(row.proposed_source || row.source || "").toLowerCase();
      if (!s.includes(_filters.source)) return false;
    }
    // Preset
    if (_filters.preset) {
      if (!_matchesPreset(row, _filters.preset)) return false;
    }
    return true;
  });
  _renderTable();
  _updateCounters();
}

function _matchesPreset(row, preset) {
  const conf = Number(row.confidence || 0);
  const flags = _parseFlags(row.warning_flags);
  switch (preset) {
    case "review": return conf < 70 || flags.some(f => ["not_a_movie", "integrity_header_invalid", "nfo_title_mismatch"].includes(f));
    case "year": return String(row.proposed_title || "") === String(row.original_title || row.folder || "");
    case "sensitive": return flags.length > 0;
    case "collections": return !!row.tmdb_collection_name;
    case "low_quality": return Number(row.score || 100) < 54;
    default: return true;
  }
}

function _parseFlags(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  return String(v).split(",").map(s => s.trim()).filter(Boolean);
}

/* --- Decisions ------------------------------------------------ */

function _toggleDecision(rowId, action) {
  const current = _state.decisions.get(rowId) || null;
  const target = action === "approve" ? "approved" : "rejected";
  _state.decisions.set(rowId, current === target ? null : target);
  _renderTable();
  _updateCounters();

  // Mode revue rapide : avancer au film suivant
  if (_state.quickReview && current !== target) {
    // Trouver l'index courant et scroller au suivant
    const idx = _filteredRows.findIndex(r => String(r.row_id) === rowId);
    if (idx >= 0 && idx < _filteredRows.length - 1) {
      const nextRow = document.querySelector(`#libValTable tr[data-row-idx="${idx + 1}"]`);
      if (nextRow) nextRow.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
}

function _updateCounters() {
  const el = $("libValCounters");
  if (!el) return;
  let approved = 0, rejected = 0;
  for (const row of _allRows) {
    const dec = _state.decisions.get(String(row.row_id));
    if (dec === "approved") approved++;
    else if (dec === "rejected") rejected++;
  }
  el.innerHTML = `
    <span>${_filteredRows.length} / ${_allRows.length} visibles</span>
    <span class="badge badge-success">${approved} approuvé(s)</span>
    <span class="badge badge-danger">${rejected} rejeté(s)</span>`;
}

/* --- Payload decisions ---------------------------------------- */

export function buildDecisionsPayload() {
  const out = {};
  for (const row of _allRows) {
    const id = String(row.row_id || "");
    const dec = _state.decisions.get(id) || null;
    out[id] = {
      ok: dec === "approved",
      title: String(row.proposed_title || "").trim(),
      year: parseInt(row.proposed_year || 0, 10) || 0,
      edited: false,
    };
  }
  return out;
}

/* --- Cellules custom ------------------------------------------ */

function _approveCell(row) {
  const rid = String(row.row_id || "");
  const dec = _state.decisions.get(rid) || null;
  const aCls = dec === "approved" ? " active" : "";
  const rCls = dec === "rejected" ? " active" : "";
  return `<div class="review-actions-cell">
    <button class="btn-review btn-approve${aCls}" data-action="approve" data-rid="${escapeHtml(rid)}" title="Approuver">✓</button>
    <button class="btn-review btn-reject${rCls}" data-action="reject" data-rid="${escapeHtml(rid)}" title="Rejeter">✗</button>
  </div>`;
}

function _titleCell(v, row) {
  let html = escapeHtml(v || "");
  const flags = _parseFlags(row.warning_flags);
  if (flags.includes("not_a_movie")) html += ' <span class="badge badge-not-a-movie">Non-film</span>';
  if (flags.includes("integrity_header_invalid")) html += ' <span class="badge badge-integrity">Corrompu</span>';
  if (row.tmdb_collection_name) html += ` <span class="badge badge-saga" title="${escapeHtml(row.tmdb_collection_name)}">Saga</span>`;
  if (row.edition) html += ` <span class="badge badge-edition">${escapeHtml(row.edition)}</span>`;
  const aa = row.audio_analysis || {};
  if (aa.badge_label) html += ` <span class="badge badge-audio-${aa.badge_tier || "basique"}">${escapeHtml(aa.badge_label)}</span>`;
  return html;
}

function _confLabel(c) {
  const v = Number(c) || 0;
  return v >= 85 ? "high" : v >= 60 ? "med" : "low";
}

function _short(p, max = 30) {
  const s = String(p || "");
  if (s.length <= max) return s;
  const h = Math.floor((max - 3) / 2);
  return s.slice(0, h) + "..." + s.slice(-h);
}

/* --- Inspecteur film (modale) --------------------------------- */

function _showInspector(row) {
  let body = `<div class="detail-grid">`;
  body += _dline("Source", row.proposed_source || row.source || "?");
  body += _dline("Confiance", `${Number(row.confidence || 0)}%`);
  body += _dline("Dossier", row.folder || "—");
  body += _dline("Fichier vidéo", row.video_filename || "—");

  // Sous-titres
  if (row.subtitle_count > 0) {
    body += _dline("Sous-titres", `${row.subtitle_count} (${row.subtitle_languages || "?"})`);
    if (row.subtitle_missing_langs) body += _dline("Langues manquantes", row.subtitle_missing_langs);
  }

  // Warnings
  const flags = _parseFlags(row.warning_flags);
  if (flags.length) body += _dline("Alertes", flags.join(", "));

  body += `</div>`;

  // Candidats TMDb
  const candidates = row.candidates || [];
  if (candidates.length > 1) {
    body += `<h4 class="mt-4">Candidats TMDb</h4><ul>`;
    for (const c of candidates.slice(0, 5)) {
      body += `<li>${escapeHtml(c.title || "")} (${c.year || "?"}) — ${Math.round((c.score || 0) * 100)}%</li>`;
    }
    body += `</ul>`;
  }

  // Boutons actions (event delegation via _hookDetailModalActions)
  const filmId = escapeHtml(row.tmdb_id ? "tmdb:" + row.tmdb_id : (row.proposed_title || "") + "|" + (row.proposed_year || ""));
  body += `<div class="flex gap-2 mt-4">`;
  body += `<button class="btn btn--compact" data-action="film-history" data-film-id="${filmId}">Historique</button>`;
  body += `<button class="btn btn--compact" data-action="perceptual-report" data-run-id="${escapeHtml(_state.runId || "")}" data-row-id="${escapeHtml(String(row.row_id || ""))}">Perceptuel</button>`;
  body += `</div>`;

  showModal({ title: `${escapeHtml(row.proposed_title || "")} (${row.proposed_year || "?"})`, body });

  // Event delegation pour les boutons d'action dans la modale detail
  _hookDetailModalActions();
}

/** Event delegation sur les boutons data-action dans la modale ouverte. */
async function _hookDetailModalActions() {
  const overlay = document.querySelector(".modal-overlay");
  if (!overlay) return;
  overlay.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === "film-history") {
      const { apiPost } = await import("../../core/api.js");
      const r = await apiPost("library/get_film_history", { film_id: btn.dataset.filmId || "" });
      const events = r.data?.events || [];
      if (!events.length) { alert("Aucun historique."); return; }
      let h = '<div class="timeline-container">';
      for (const ev of events) { h += `<div class="timeline-event"><strong>${escapeHtml(ev.type)}</strong> — ${escapeHtml(ev.date || "")}<br>${escapeHtml(ev.detail || "")}</div>`; }
      h += "</div>";
      const { showModal: showM } = await import("../../components/modal.js");
      showM({ title: "Historique", body: h });
    } else if (action === "perceptual-report") {
      const { apiPost } = await import("../../core/api.js");
      const r = await apiPost("quality/get_perceptual_report", { run_id: btn.dataset.runId || "", row_id: btn.dataset.rowId || "" });
      const d = r.data || {};
      if (!d.ok && d.ok !== undefined) { alert(d.message || "Pas de rapport."); return; }
      let h = `<p>Score global : <strong>${d.global_score || "—"}</strong></p>`;
      h += `<p>Vidéo : ${d.visual_score || "—"} | Audio : ${d.audio_score || "—"}</p>`;
      const { showModal: showM } = await import("../../components/modal.js");
      showM({ title: "Analyse perceptuelle", body: h });
    }
  });
}

function _dline(label, value) {
  return `<div class="detail-row"><span class="detail-label">${escapeHtml(label)}</span><span>${escapeHtml(String(value))}</span></div>`;
}

/* --- Evenements ----------------------------------------------- */

function _hookValidationEvents() {
  // Recherche
  const search = $("libValSearch");
  if (search) {
    search.addEventListener("input", () => {
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => { _filters.search = search.value; _applyFilters(); }, 300);
    });
  }

  // Filtres dropdowns
  const confF = $("libValFilterConf");
  if (confF) confF.addEventListener("change", () => { _filters.confidence = confF.value; _applyFilters(); });
  const srcF = $("libValFilterSource");
  if (srcF) srcF.addEventListener("change", () => { _filters.source = srcF.value; _applyFilters(); });

  // Presets
  const presets = $("libValPresets");
  if (presets) {
    presets.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-preset]");
      if (!btn) return;
      _filters.preset = _filters.preset === btn.dataset.preset ? "" : btn.dataset.preset;
      presets.querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.preset === _filters.preset));
      _applyFilters();
    });
  }

  // Bulk actions
  $("libBtnApproveAll")?.addEventListener("click", () => { _allRows.forEach(r => _state.decisions.set(String(r.row_id), "approved")); _renderTable(); _updateCounters(); });
  $("libBtnApproveSure")?.addEventListener("click", () => { _allRows.forEach(r => { if (Number(r.confidence || 0) >= _state.autoThreshold) _state.decisions.set(String(r.row_id), "approved"); }); _renderTable(); _updateCounters(); });
  $("libBtnRejectAll")?.addEventListener("click", () => { _allRows.forEach(r => _state.decisions.set(String(r.row_id), "rejected")); _renderTable(); _updateCounters(); });
  $("libBtnResetDec")?.addEventListener("click", () => { _state.decisions = new Map(); _renderTable(); _updateCounters(); });

  // Sauvegarder
  $("libBtnSaveVal")?.addEventListener("click", async () => {
    const btn = $("libBtnSaveVal");
    if (btn) btn.disabled = true;
    try {
      const res = await apiPost("save_validation", { run_id: _state.runId, decisions: buildDecisionsPayload() });
      _showMsg(res.data?.ok !== false ? "Décisions sauvegardées." : (res.data?.message || "Échec."), res.data?.ok === false);
    } catch { _showMsg("Erreur réseau.", true); }
    finally { if (btn) btn.disabled = false; }
  });

  // Quick review
  const ckQR = $("ckQuickReview");
  if (ckQR) ckQR.addEventListener("change", () => { _state.quickReview = ckQR.checked; });

  // Seuil auto-approve (mode avance)
  const slider = $("libValThreshold");
  const lbl = $("libValThresholdLbl");
  if (slider) {
    slider.addEventListener("input", () => {
      _state.autoThreshold = Number(slider.value);
      if (lbl) lbl.textContent = slider.value + "%";
    });
  }
}

function _showMsg(text, isError = false) {
  const el = $("libValMsg");
  if (!el) return;
  el.textContent = text;
  el.className = "status-msg" + (isError ? " error" : " success");
}
