/* lib-validation.js — Section 3 : Validation (table complète, filtres, presets, inspecteur) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiGet, apiPost, fetchConfidenceThresholds, getConfidenceThresholdsSync } from "../../core/api.js";
import { tableHtml, attachSort } from "../../components/table.js";
import { badgeHtml } from "../../components/badge.js";
import { showModal, dangerConfirmModal } from "../../components/modal.js";
import { refreshVerification } from "./lib-verification.js";
import { markValidationSaved } from "./lib-apply.js";
import { getNavSignal, isAbortError } from "../../core/nav-abort.js";
// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplacer alert() natifs
// par showToast pour notifications informatives/erreur (read-only history & report).
import { showToast } from "../../components/toast.js";

let _state = null;
let _allRows = [];
let _filteredRows = [];
let _searchTimer = null;
let _filters = { search: "", confidence: "", source: "", preset: "" };
// VO-C-FRONTEND-LIB-VAL : cache module-level du mapping rule_id -> {name, action}
// pour render le waterfall custom_formats sans refetch a chaque ouverture de
// l'inspecteur. Hydrate au 1er showInspector (paresseux). Map<string, {name,
// action}>.
let _profileRulesById = null;
let _profileRulesPromise = null;

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
  // VN-C.1 (batch 2) : prefetch des seuils confidence (cache module-level
  // dans core/api.js). Lance en // — fallback sync sur DEFAULTS si pas
  // encore arrive au premier render.
  fetchConfidenceThresholds().catch(() => { /* fallback DEFAULTS */ });
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
    const labels = ["run/get_plan", "run/load_validation"];
    const results = await Promise.allSettled([
      apiPost("run/get_plan", { run_id: _state.runId }, { signal: navSig }),
      apiPost("run/load_validation", { run_id: _state.runId }, { signal: navSig }),
    ]);
    const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
    const [planRes, valRes] = results.map(_val);
    const failed = labels.filter((_, i) => results[i].status !== "fulfilled" && !isAbortError(results[i].reason));
    if (failed.length > 0) console.warn("[lib-validation] endpoints en echec:", failed);

    _allRows = Array.isArray(planRes?.data?.rows) ? planRes.data.rows : [];
    _state.rows = _allRows;

    // Restaurer les decisions existantes.
    // Vague P / VP-D : tri-etat accepted/rejected/deferred. La cle SQL
    // canonique est `decision` ; on conserve le legacy `ok: bool` pour
    // les payloads pre-VP-D (backward compat ABSOLUE).
    _state.decisions = new Map();
    const saved = valRes?.data?.decisions || valRes?.data || {};
    if (typeof saved === "object" && !Array.isArray(saved)) {
      for (const [id, d] of Object.entries(saved)) {
        if (d && typeof d === "object") {
          const decision = String(d.decision || "").toLowerCase();
          if (decision === "accepted") _state.decisions.set(id, "approved");
          else if (decision === "rejected") _state.decisions.set(id, "rejected");
          else if (decision === "deferred") _state.decisions.set(id, "deferred");
          else if (d.ok === true) _state.decisions.set(id, "approved");
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
  // VN-C.1 (batch 2) : libelles dynamiques bases sur les seuils unifies.
  const _tFlt = getConfidenceThresholdsSync();
  html += `<select class="input" id="libValFilterConf" data-testid="lib-valid-filter-conf" style="max-width:140px">
    <option value="">Confiance : Toutes</option><option value="high">Haute (&ge;${_tFlt.high})</option><option value="med">Moyenne (${_tFlt.medium}-${_tFlt.high - 1})</option><option value="low">Basse (&lt;${_tFlt.medium})</option></select>`;
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

  // Colorier les lignes (VP-D : tri-etat -> 3 classes).
  const tbody = el.querySelector("tbody");
  if (tbody) {
    const trs = tbody.querySelectorAll("tr");
    trs.forEach((tr, i) => {
      const row = _filteredRows[i];
      if (!row) return;
      const dec = _state.decisions.get(String(row.row_id));
      tr.classList.remove("row-approved", "row-rejected", "row-deferred");
      if (dec === "approved") tr.classList.add("row-approved");
      else if (dec === "rejected") tr.classList.add("row-rejected");
      else if (dec === "deferred") tr.classList.add("row-deferred");
    });
  }

  // Clic sur ligne → modale inspecteur
  // mega-hotfix frontend_ui_polish (#1) : handlers nommes pour stack traces lisibles
  // (avant : lambda anonyme "(e) =>" sans nom de fonction dans la stack).
  el.querySelectorAll("tr[data-row-idx]").forEach(tr => {
    tr.addEventListener("click", function onValidationRowClick(e) {
      if (e.target.closest("button") || e.target.closest("input")) return;
      const idx = Number(tr.dataset.rowIdx);
      const row = _filteredRows[idx];
      if (row) _showInspector(row);
    });
  });

  // Boutons approve/reject par ligne
  el.querySelectorAll(".btn-review").forEach(btn => {
    btn.addEventListener("click", function onReviewButtonClick(e) {
      e.stopPropagation();
      const rid = btn.dataset.rid;
      const action = btn.dataset.action;
      _toggleDecision(rid, action);
    });
  });

  // Edition inline annee
  el.querySelectorAll("[data-year-rid]").forEach(input => {
    input.addEventListener("change", function onYearInputChange() {
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
    // Confiance — VN-C.1 (batch 2) : seuils 85/60 -> getConfidenceThresholdsSync().
    if (_filters.confidence) {
      const c = Number(row.confidence || 0);
      const t = getConfidenceThresholdsSync();
      if (_filters.confidence === "high" && c < t.high) return false;
      if (_filters.confidence === "med" && (c < t.medium || c >= t.high)) return false;
      if (_filters.confidence === "low" && c >= t.medium) return false;
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
  // Vague P / VP-D : action 'defer' = etat 'deferred'.
  let target;
  if (action === "approve") target = "approved";
  else if (action === "defer") target = "deferred";
  else target = "rejected";
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
  // Vague P / VP-D : 3 compteurs (accepted/rejected/deferred).
  let approved = 0, rejected = 0, deferred = 0;
  for (const row of _allRows) {
    const dec = _state.decisions.get(String(row.row_id));
    if (dec === "approved") approved++;
    else if (dec === "rejected") rejected++;
    else if (dec === "deferred") deferred++;
  }
  el.innerHTML = `
    <span>${_filteredRows.length} / ${_allRows.length} visibles</span>
    <span class="badge badge-success">${approved} accepté(s)</span>
    <span class="badge badge-warning">${deferred} reporté(s)</span>
    <span class="badge badge-danger">${rejected} rejeté(s)</span>`;
}

/* --- Payload decisions ---------------------------------------- */

export function buildDecisionsPayload() {
  const out = {};
  for (const row of _allRows) {
    const id = String(row.row_id || "");
    const dec = _state.decisions.get(id) || null;
    // Vague P / VP-D : emet `decision` (tri-etat) ET `ok` (legacy) pour
    // backward compat ABSOLUE. Le backend lit `decision` en priorite (si
    // present) et retombe sur `ok` sinon (helper `to_legacy_ok_bool`).
    let decision;
    if (dec === "approved") decision = "accepted";
    else if (dec === "deferred") decision = "deferred";
    else decision = "rejected";
    out[id] = {
      ok: dec === "approved",
      decision: decision,
      title: String(row.proposed_title || "").trim(),
      year: parseInt(row.proposed_year || 0, 10) || 0,
      edited: false,
    };
    // Echo film_id si dispo (cle stable VP-C/VP-D).
    if (row.tmdb_id) out[id].tmdb_id = row.tmdb_id;
  }
  return out;
}

/* --- Cellules custom ------------------------------------------ */

function _approveCell(row) {
  const rid = String(row.row_id || "");
  const dec = _state.decisions.get(rid) || null;
  const aCls = dec === "approved" ? " active" : "";
  const rCls = dec === "rejected" ? " active" : "";
  // Vague P / VP-D : 3eme bouton "Reporter" (deferred).
  const dCls = dec === "deferred" ? " active" : "";
  return `<div class="review-actions-cell">
    <button class="btn-review btn-approve${aCls}" data-action="approve" data-rid="${escapeHtml(rid)}" title="Accepter">✓</button>
    <button class="btn-review btn-defer${dCls}" data-action="defer" data-rid="${escapeHtml(rid)}" title="Reporter (decider plus tard)">⏸</button>
    <button class="btn-review btn-reject${rCls}" data-action="reject" data-rid="${escapeHtml(rid)}" title="Rejeter">✗</button>
  </div>`;
}

function _titleCell(v, row) {
  let html = escapeHtml(v || "");
  const flags = _parseFlags(row.warning_flags);
  if (flags.includes("not_a_movie")) html += ' <span class="badge badge-not-a-movie">Non-film</span>';
  if (flags.includes("integrity_header_invalid")) html += ' <span class="badge badge-integrity">Corrompu</span>';
  // VN-A.1 : badge probe_quality (FAILED/PARTIAL) explicite. Lit row.probe_quality
  // si fourni par le backend (quality_report_support), sinon retombe sur
  // warning_flags=integrity_probe_failed. data-probe-quality permet aux tests
  // e2e/Playwright de cibler l'etat sans deviner le label.
  const pq = String(row.probe_quality || "").toUpperCase();
  const pqFlag = flags.includes("integrity_probe_failed");
  if (pq === "FAILED" || (pqFlag && pq !== "FULL" && pq !== "PARTIAL")) {
    html += ` <span class="badge badge-probe-failed" data-probe-quality="FAILED" title="Analyse technique échouée">Probe KO</span>`;
  } else if (pq === "PARTIAL") {
    html += ` <span class="badge badge-probe-partial" data-probe-quality="PARTIAL" title="Analyse technique partielle">Probe partielle</span>`;
  }
  if (row.tmdb_collection_name) html += ` <span class="badge badge-saga" title="${escapeHtml(row.tmdb_collection_name)}">Saga</span>`;
  if (row.edition) html += ` <span class="badge badge-edition">${escapeHtml(row.edition)}</span>`;
  const aa = row.audio_analysis || {};
  if (aa.badge_label) html += ` <span class="badge badge-audio-${aa.badge_tier || "bronze"}">${escapeHtml(aa.badge_label)}</span>`;
  return html;
}

function _confLabel(c) {
  // VN-C.1 (batch 2) : seuils 85/60 -> getConfidenceThresholdsSync()
  // (source unique : cinesort/domain/confidence_thresholds.py).
  const v = Number(c) || 0;
  const t = getConfidenceThresholdsSync();
  return v >= t.high ? "high" : v >= t.medium ? "med" : "low";
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

  // VO-C-FRONTEND-LIB-VAL : Breakdown du score waterfall (categories +
  // baseline + applied_rule_ids + suggestions). Affiche uniquement si le
  // backend a fourni row.score_explanation_full (VO-C-BACKEND).
  body += _renderScoreWaterfall(row);

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

  // Hydrate paresseuse du mapping rule_id -> name. Si la modale contient
  // au moins un applied_rule_id non resolu, on lance le fetch profile et on
  // re-render uniquement la sous-section custom_formats (sans re-ouvrir la
  // modale).
  const full = row.score_explanation_full;
  if (full && Array.isArray(full.applied_rule_ids) && full.applied_rule_ids.length > 0) {
    _hydrateProfileRulesAsync().then(() => {
      _refreshWaterfallCustomFormats(full.applied_rule_ids);
    }).catch(() => { /* network refused : labels restent en rule_id brut */ });
  }
}

/** Render waterfall additif type Radarr. Retourne "" si pas de donnees. */
function _renderScoreWaterfall(row) {
  const full = row && row.score_explanation_full;
  if (!full || typeof full !== "object") return "";

  const categories = Array.isArray(full.categories) ? full.categories : [];
  const baseline = (full.baseline && typeof full.baseline === "object") ? full.baseline : {};
  const applied = Array.isArray(full.applied_rule_ids) ? full.applied_rule_ids : [];
  const suggestions = Array.isArray(full.suggestions) ? full.suggestions : [];
  const narrative = String(full.narrative || "");

  // Score total + tier final (vient du row, source unique).
  const totalScore = (row.score === null || row.score === undefined || row.score === "")
    ? null
    : Math.round(Number(row.score) || 0);
  const finalTier = String(row.quality_tier || "").trim();

  // Baseline = score "de depart" du profil. build_rich_explanation ne fournit
  // pas explicitement ce nombre : on affiche une ligne baseline neutre avec
  // les seuils du profil (Platinum/Gold/Silver/Bronze) en label, et la
  // distance au prochain tier si calculee.
  const thresholds = (baseline.tier_thresholds && typeof baseline.tier_thresholds === "object")
    ? baseline.tier_thresholds : {};
  const nextTier = baseline.next_tier ? String(baseline.next_tier) : "";
  const distance = (typeof baseline.distance_to_next_tier === "number")
    ? baseline.distance_to_next_tier : null;

  let html = `<h4 class="mt-4" data-testid="score-waterfall-title">Breakdown du score</h4>`;
  html += `<div class="score-waterfall" data-testid="score-waterfall">`;

  // Ligne baseline : seuils du profil (texte informatif).
  const thresholdsTxt = ["Platinum", "Gold", "Silver", "Bronze"]
    .map(t => (thresholds[t] != null ? `${t} ≥ ${thresholds[t]}` : null))
    .filter(Boolean)
    .join(" · ");
  if (thresholdsTxt) {
    html += `<div class="score-waterfall-row score-waterfall-row--baseline">`;
    html += `<span class="score-waterfall-label">Seuils du profil</span>`;
    html += `<span class="score-waterfall-detail">${escapeHtml(thresholdsTxt)}</span>`;
    html += `</div>`;
  }

  // Lignes categories (video / audio / extras / custom_rules).
  if (categories.length === 0) {
    html += `<div class="score-waterfall-row score-waterfall-row--empty">`;
    html += `<span class="score-waterfall-label">Pas de breakdown disponible</span>`;
    html += `</div>`;
  }
  for (const cat of categories) {
    if (!cat || typeof cat !== "object") continue;
    const name = String(cat.name || "");
    const label = String(cat.label || name || "?");

    // Categorie synthetique custom_rules : pas de contribution chiffree
    // (deja agregee dans video par compute_quality_score). On affiche les
    // badges des regles via _renderCustomFormatsImpact (placeholder ici,
    // hydratation paresseuse).
    if (name === "custom_rules") {
      const ruleIds = Array.isArray(cat.rule_ids) ? cat.rule_ids : applied;
      html += `<div class="score-waterfall-row score-waterfall-row--custom" data-waterfall-custom-formats>`;
      html += `<span class="score-waterfall-label">${escapeHtml(label)}</span>`;
      html += `<span class="score-waterfall-detail">${_renderCustomFormatsImpact(ruleIds, _profileRulesById)}</span>`;
      html += `</div>`;
      continue;
    }

    // Categories standards : contribution ponderee + subscore + counts.
    const contribution = (cat.contribution === null || cat.contribution === undefined)
      ? null : Number(cat.contribution);
    const subscore = (cat.subscore === null || cat.subscore === undefined)
      ? null : Number(cat.subscore);
    const weightPct = (cat.weight_pct === null || cat.weight_pct === undefined)
      ? null : Number(cat.weight_pct);
    const pos = Number(cat.positive_count || 0);
    const neg = Number(cat.negative_count || 0);

    let contribClass = "score-waterfall-contribution-neutral";
    let contribTxt = "—";
    if (contribution !== null && !Number.isNaN(contribution)) {
      if (contribution > 0) {
        contribClass = "score-waterfall-contribution-positive";
        contribTxt = `+${_round1(contribution)}`;
      } else if (contribution < 0) {
        contribClass = "score-waterfall-contribution-negative";
        contribTxt = `${_round1(contribution)}`;
      } else {
        contribTxt = "0";
      }
    }

    const details = [];
    if (subscore !== null && !Number.isNaN(subscore)) details.push(`subscore ${Math.round(subscore)}`);
    if (weightPct !== null && !Number.isNaN(weightPct)) details.push(`poids ${Math.round(weightPct)}%`);
    if (pos > 0) details.push(`${pos} bonus`);
    if (neg > 0) details.push(`${neg} pénalité${neg > 1 ? "s" : ""}`);

    html += `<div class="score-waterfall-row" data-cat="${escapeHtml(name)}">`;
    html += `<span class="score-waterfall-label">${escapeHtml(label)}</span>`;
    html += `<span class="score-waterfall-contribution ${contribClass}">${escapeHtml(contribTxt)}</span>`;
    if (details.length) {
      html += `<span class="score-waterfall-detail">${escapeHtml(details.join(" · "))}</span>`;
    }
    html += `</div>`;
  }

  // Ligne total : score final + tier.
  html += `<div class="score-waterfall-row score-waterfall-row--total">`;
  html += `<span class="score-waterfall-label">Total</span>`;
  if (totalScore !== null) {
    html += `<span class="score-waterfall-contribution score-waterfall-contribution-total">= ${escapeHtml(String(totalScore))}</span>`;
  } else {
    html += `<span class="score-waterfall-contribution score-waterfall-contribution-total">—</span>`;
  }
  if (finalTier) {
    html += `<span class="score-waterfall-detail">→ ${escapeHtml(finalTier)}</span>`;
  }
  html += `</div>`;

  // Distance au prochain tier (info actionable).
  if (nextTier && distance !== null) {
    html += `<div class="score-waterfall-row score-waterfall-row--next">`;
    html += `<span class="score-waterfall-label">Prochain tier</span>`;
    html += `<span class="score-waterfall-detail">${escapeHtml(nextTier)} à ${escapeHtml(String(distance))} pt(s)</span>`;
    html += `</div>`;
  }

  html += `</div>`; // .score-waterfall

  // Narrative (1-3 phrases FR generees par build_rich_explanation).
  if (narrative) {
    html += `<p class="score-waterfall-narrative" data-testid="score-waterfall-narrative">${escapeHtml(narrative)}</p>`;
  }

  // Suggestions actionables.
  if (suggestions.length > 0) {
    html += `<ul class="score-waterfall-suggestions" data-testid="score-waterfall-suggestions">`;
    for (const s of suggestions) {
      html += `<li>${escapeHtml(String(s))}</li>`;
    }
    html += `</ul>`;
  }

  return html;
}

/** Render badges "Rule: NomLisible" pour chaque applied_rule_id. */
function _renderCustomFormatsImpact(appliedRuleIds, profileRulesById) {
  const ids = Array.isArray(appliedRuleIds) ? appliedRuleIds : [];
  if (ids.length === 0) return `<span class="text-muted">—</span>`;

  let html = "";
  for (const rawId of ids) {
    const id = String(rawId || "").trim();
    if (!id) continue;
    const rule = profileRulesById ? profileRulesById.get(id) : null;
    const name = (rule && rule.name) ? String(rule.name) : id;
    const action = rule && rule.action;
    const actionTxt = action && (action.value !== null && action.value !== undefined && action.value !== "")
      ? ` (${Number(action.value) >= 0 ? "+" : ""}${action.value})`
      : "";
    html += `<span class="badge badge-custom-rule" title="${escapeHtml(id)}">Rule: ${escapeHtml(name)}${escapeHtml(actionTxt)}</span> `;
  }
  return html || `<span class="text-muted">—</span>`;
}

/** Charge le profil qualite (1x par session) pour resoudre rule_id -> name. */
async function _hydrateProfileRulesAsync() {
  if (_profileRulesById) return _profileRulesById;
  if (_profileRulesPromise) return _profileRulesPromise;
  _profileRulesPromise = (async () => {
    try {
      const res = await apiPost("quality/get_quality_profile", {});
      const payload = (res && res.data) || res || {};
      const profile = payload.profile_json || {};
      const rules = Array.isArray(profile.custom_rules) ? profile.custom_rules : [];
      const map = new Map();
      for (const r of rules) {
        const id = String((r && r.id) || "").trim();
        if (!id) continue;
        map.set(id, {
          name: String((r && r.name) || id),
          action: (r && r.action) || null,
        });
      }
      _profileRulesById = map;
      return map;
    } catch {
      _profileRulesById = new Map();
      return _profileRulesById;
    } finally {
      _profileRulesPromise = null;
    }
  })();
  return _profileRulesPromise;
}

/** Re-render uniquement la sous-section custom_formats apres hydratation. */
function _refreshWaterfallCustomFormats(appliedRuleIds) {
  const overlay = document.querySelector(".modal-overlay");
  if (!overlay) return;
  const cell = overlay.querySelector("[data-waterfall-custom-formats] .score-waterfall-detail");
  if (!cell) return;
  cell.innerHTML = _renderCustomFormatsImpact(appliedRuleIds, _profileRulesById);
}

/** Arrondi a 1 decimale, en supprimant le ".0" trailing. */
function _round1(v) {
  const n = Math.round(Number(v) * 10) / 10;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
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
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
      if (!events.length) { showToast({ type: "info", text: "Aucun historique." }); return; }
      let h = '<div class="timeline-container">';
      for (const ev of events) { h += `<div class="timeline-event"><strong>${escapeHtml(ev.type)}</strong> — ${escapeHtml(ev.date || "")}<br>${escapeHtml(ev.detail || "")}</div>`; }
      h += "</div>";
      const { showModal: showM } = await import("../../components/modal.js");
      showM({ title: "Historique", body: h });
    } else if (action === "perceptual-report") {
      // Cf #32 : 2-step fetch.
      // 1) D'abord get_perceptual_details (read-only) — retourne tout, y
      //    compris audio_fingerprint, ssim_self_ref, upscale_verdict.
      // 2) Si rien en BDD (missing), on tombe sur get_perceptual_report qui
      //    declenche l'analyse puis on rappelle details pour les 3 champs
      //    orphelins.
      const { apiPost } = await import("../../core/api.js");
      const runId = btn.dataset.runId || "";
      const rowId = btn.dataset.rowId || "";
      let details = null;
      const r1 = await apiPost("quality/get_perceptual_details", { run_id: runId, row_id: rowId });
      const d1 = r1.data || {};
      if (d1.ok && d1.details) {
        details = d1.details;
      } else if (d1.missing) {
        // Pas encore analyse : declenche l'analyse puis refetch details.
        const r2 = await apiPost("quality/get_perceptual_report", { run_id: runId, row_id: rowId });
        const d2 = r2.data || {};
        if (!d2.ok && d2.ok !== undefined) {
          // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
          showToast({ type: "error", text: d2.message || "Analyse perceptuelle echouee." });
          return;
        }
        const r3 = await apiPost("quality/get_perceptual_details", { run_id: runId, row_id: rowId });
        details = r3?.data?.details || null;
        // Fallback : si meme apres analyse on n'a pas de details, on affiche
        // au moins le payload immediat de get_perceptual_report.
        if (!details) details = d2;
      } else if (d1.message) {
        // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
        showToast({ type: "error", text: d1.message });
        return;
      }
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
      if (!details) { showToast({ type: "info", text: "Pas de rapport perceptuel disponible." }); return; }
      // Helpers d'affichage
      const _fmt = (v, missing = "—") => (v === null || v === undefined || v === "") ? missing : v;
      const _shortFp = (fp) => { const s = String(fp || ""); return s.length > 16 ? s.slice(0, 8) + "…" + s.slice(-6) : s; };
      const _ssimLabel = (v) => {
        if (v === null || v === undefined) return "non calcule";
        const n = Number(v);
        if (n >= 0.95) return `${n.toFixed(3)} (Excellent)`;
        if (n >= 0.85) return `${n.toFixed(3)} (Bon)`;
        if (n >= 0.70) return `${n.toFixed(3)} (Moyen)`;
        return `${n.toFixed(3)} (Faible — upscale suspect)`;
      };
      const _verdictLabel = (v) => {
        if (!v) return "non calcule";
        const s = String(v);
        const labels = {
          native_4k: "Natif 4K",
          native: "Natif (resolution authentique)",
          upscaled_1080p: "Upscale depuis 1080p (faux 4K)",
          upscaled: "Upscale suspect",
          disabled: "Detection desactivee",
        };
        return labels[s] || s;
      };
      // Header : scores globaux
      let h = `<p>Score global : <strong>${_fmt(details.global_score)}</strong>`;
      if (details.global_tier) h += ` (${_fmt(details.global_tier)})`;
      h += `</p>`;
      h += `<p>Vidéo : ${_fmt(details.visual_score)} | Audio : ${_fmt(details.audio_score)}</p>`;
      // Cf #32 : section "Empreintes et verdicts" pour les donnees orphelines.
      h += `<hr><h4 style="margin-top:1em">Empreintes &amp; verdicts</h4>`;
      h += `<table class="tbl detail-table">`;
      h += `<tr><th style="text-align:left">Empreinte audio (Chromaprint)</th><td><code title="${_fmt(details.audio_fingerprint, "")}">${details.audio_fingerprint ? _shortFp(details.audio_fingerprint) : "non calculee"}</code>`;
      if (details.audio_fingerprint) {
        h += ` <button class="btn btn--xs" data-fp-copy="${details.audio_fingerprint}" title="Copier l'empreinte complete">Copier</button>`;
      }
      h += `</td></tr>`;
      h += `<tr><th style="text-align:left">SSIM self-ref</th><td>${_ssimLabel(details.ssim_self_ref)}</td></tr>`;
      h += `<tr><th style="text-align:left">Verdict resolution (faux 4K)</th><td>${_verdictLabel(details.upscale_verdict)}</td></tr>`;
      if (details.lossy_verdict) {
        h += `<tr><th style="text-align:left">Verdict audio</th><td>${_fmt(details.lossy_verdict)}</td></tr>`;
      }
      h += `</table>`;
      const { showModal: showM } = await import("../../components/modal.js");
      showM({ title: "Analyse perceptuelle", body: h });
      // Bind du bouton copy de l'empreinte (apres mount de la modale).
      setTimeout(() => {
        const overlay = document.querySelector(".modal-overlay");
        const copyBtn = overlay?.querySelector("[data-fp-copy]");
        if (copyBtn) {
          copyBtn.addEventListener("click", async () => {
            try {
              await navigator.clipboard.writeText(copyBtn.dataset.fpCopy);
              copyBtn.textContent = "Copié";
              setTimeout(() => { copyBtn.textContent = "Copier"; }, 1500);
            } catch { /* clipboard refused : noop */ }
          });
        }
      }, 0);
    }
  });
}

function _dline(label, value) {
  return `<div class="detail-row"><span class="detail-label">${escapeHtml(label)}</span><span>${escapeHtml(String(value))}</span></div>`;
}

/* --- Evenements ----------------------------------------------- */

function _hookValidationEvents() {
  // mega-hotfix frontend_ui_polish (#1) : handlers nommes pour faciliter le debug
  // (stack traces lisibles : "at onLibValSearchInput" plutot que "anonymous").
  // Recherche
  const search = $("libValSearch");
  if (search) {
    search.addEventListener("input", function onLibValSearchInput() {
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(function applyLibValSearchDebounced() {
        _filters.search = search.value; _applyFilters();
      }, 300);
    });
  }

  // Filtres dropdowns
  const confF = $("libValFilterConf");
  if (confF) confF.addEventListener("change", function onLibValConfFilterChange() { _filters.confidence = confF.value; _applyFilters(); });
  const srcF = $("libValFilterSource");
  if (srcF) srcF.addEventListener("change", function onLibValSourceFilterChange() { _filters.source = srcF.value; _applyFilters(); });

  // Presets
  const presets = $("libValPresets");
  if (presets) {
    presets.addEventListener("click", function onLibValPresetClick(e) {
      const btn = e.target.closest("[data-preset]");
      if (!btn) return;
      _filters.preset = _filters.preset === btn.dataset.preset ? "" : btn.dataset.preset;
      presets.querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.preset === _filters.preset));
      _applyFilters();
    });
  }

  // Bulk actions
  $("libBtnApproveAll")?.addEventListener("click", function onLibValApproveAll() {
    _allRows.forEach(r => _state.decisions.set(String(r.row_id), "approved"));
    _renderTable(); _updateCounters();
  });
  $("libBtnApproveSure")?.addEventListener("click", function onLibValApproveSure() {
    _allRows.forEach(r => { if (Number(r.confidence || 0) >= _state.autoThreshold) _state.decisions.set(String(r.row_id), "approved"); });
    _renderTable(); _updateCounters();
  });
  // Vague P / VP-D AC-4 : "Rejeter Tout" -> dangerConfirmModal avec
  // countdown 3s SI > 50 items (memo feedback_cinesort_actions_dangereuses).
  $("libBtnRejectAll")?.addEventListener("click", function onLibValRejectAll() {
    confirmBulkReject(_allRows, function onConfirmedBulkReject() {
      _allRows.forEach(r => _state.decisions.set(String(r.row_id), "rejected"));
      _renderTable();
      _updateCounters();
    });
  });
  // Vague P / VP-G AC-5 : "Reinitialiser" efface TOUTES les decisions
  // accepted/rejected/deferred -> action destructive, dangerConfirmModal
  // OBLIGATOIRE (memo feedback_cinesort_actions_dangereuses). Countdown 3s
  // si plus de 50 decisions posees. Si aucune decision posee : no-op silencieux.
  $("libBtnResetDec")?.addEventListener("click", function onLibValResetDecisions() {
    confirmResetDecisions(_state.decisions, function onConfirmedResetDecisions() {
      _state.decisions = new Map();
      _renderTable();
      _updateCounters();
    });
  });

  // Sauvegarder
  $("libBtnSaveVal")?.addEventListener("click", async function onLibValSave() {
    const btn = $("libBtnSaveVal");
    if (btn) btn.disabled = true;
    try {
      const res = await apiPost("run/save_validation", { run_id: _state.runId, decisions: buildDecisionsPayload() });
      const ok = res.data?.ok !== false;
      _showMsg(ok ? "Décisions sauvegardées." : (res.data?.message || "Échec."), !ok);
      // Fix audit 2026-05-24 (v1.5.2) : checklist Apply etait cosmetique. On
      // flagge l'etat "saved" pour debloquer le bouton Appliquer (combine avec
      // dupsChecked via markDuplicatesChecked). Voir lib-apply.js.
      if (ok) {
        try { markValidationSaved(); } catch (_e) { /* lib-apply pas monte */ }
      }
    } catch { _showMsg("Erreur réseau.", true); }
    finally { if (btn) btn.disabled = false; }
  });

  // Quick review
  const ckQR = $("ckQuickReview");
  if (ckQR) ckQR.addEventListener("change", function onLibValQuickReviewToggle() { _state.quickReview = ckQR.checked; });

  // Seuil auto-approve (mode avance)
  const slider = $("libValThreshold");
  const lbl = $("libValThresholdLbl");
  if (slider) {
    slider.addEventListener("input", function onLibValThresholdChange() {
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

/* =============================================================
 * Vague P / VP-C : Field locks Jellyfin-style — UI
 * =============================================================
 * Cadenas par champ + 2 modes UI :
 *   - "Completer les manques uniquement" (defaut, sans confirmation)
 *   - "Tout reconstruire" : dangerConfirmModal OBLIGATOIRE avec liste
 *     des champs verrouilles + countdown 3s si plus de 50 items
 *     (memo feedback_cinesort_actions_dangereuses).
 *
 * `dangerConfirmModal` est la seule modale autorisee pour les actions
 * destructives (jamais window.confirm/alert/prompt).
 */

const _DEFAULT_LOCKABLE_FIELDS = [
  "title",
  "proposed_title",
  "year",
  "proposed_year",
  "tmdb_id",
  "imdb_id",
  "overview",
  "genres",
];

/**
 * mega-hotfix frontend_ui_polish (#5) : countdown gradue lineaire pour
 * dangerConfirmModal. Avant : cliff effect a 50/51 (0s a 50 elements, 3s
 * direct a 51 elements -> sensation de "punition" arbitraire).
 * Maintenant : transition lineaire entre 30 et 50 elements (0s -> 3s),
 * puis 3s ferme au-dela.
 *   - <= 30 elements : 0s (action rapide, pas de friction)
 *   - 30 < n <= 50   : interpolation lineaire arrondie a la seconde
 *   - > 50           : 3s STRICT (memo feedback_cinesort_actions_dangereuses,
 *     regle absolue "countdown 3s si > 50")
 * La gradation 0->1->2->3 sur la plage 30..50 lisse le cliff sous le seuil
 * tout en respectant la regle absolue au-dela de 50.
 *
 * @param {number} count - nombre d'elements impactes
 * @returns {number} countdown en secondes (entier 0-3)
 */
function _gradedCountdownSeconds(count) {
  const n = Number(count) || 0;
  if (n <= 30) return 0;
  // Regle absolue (memo feedback_cinesort_actions_dangereuses) : countdown
  // 3s des que > 50 elements. Doit etre verifie AVANT l'interpolation pour
  // ne jamais sous-dimensionner le countdown d'une action destructive.
  if (n > 50) return 3;
  // Interpolation lineaire entre 30 et 50 vers [0, 3].
  const linear = ((n - 30) / (50 - 30)) * 3;
  return Math.max(0, Math.min(3, Math.round(linear)));
}

/**
 * Lance un rebuild complet d'un champ (ou de plusieurs films) avec
 * confirmation dangereuse OBLIGATOIRE.
 *
 * @param {object} opts
 * @param {string[]} opts.rowIds - films impactes par le rebuild
 * @param {string[]} [opts.lockedFields] - champs actuellement verrouilles
 * @param {Function} opts.onConfirm - callback async appele a la confirmation
 */
export function confirmRebuildAll({ rowIds = [], lockedFields = [], onConfirm } = {}) {
  const count = Array.isArray(rowIds) ? rowIds.length : 0;
  const fields = Array.isArray(lockedFields) && lockedFields.length > 0
    ? lockedFields
    : _DEFAULT_LOCKABLE_FIELDS;

  // mega-hotfix frontend_ui_polish (#5) : countdown gradue (0-3s entre 30 et 100
  // elements) au lieu du cliff effect a 50/51. Memo
  // feedback_cinesort_actions_dangereuses reste respecte : > 50 elements
  // produit ~1.5-3s selon l'interpolation, jamais 0s.
  const countdownSeconds = _gradedCountdownSeconds(count);

  const titleSuffix = count > 1 ? `${count} films` : "ce film";
  const items = fields.map((f) => `Champ : ${f}`);
  const consequence = count > 50
    ? `Les champs verrouilles de ${count} films seront ecrases si vous les deverrouilez d'abord. Action non-reversible automatiquement.`
    : `Les champs verrouilles seront preserves. Les autres champs seront reconstruits depuis TMDb/OMDb.`;

  return dangerConfirmModal({
    title: `Tout reconstruire (${titleSuffix}) ?`,
    items,
    consequence,
    countdownSeconds,
    confirmLabel: "Reconstruire",
    cancelLabel: "Annuler",
    onConfirm: async () => {
      if (typeof onConfirm === "function") {
        await onConfirm();
      }
    },
  });
}

/**
 * Pose ou retire un verrou sur un champ pour un film.
 *
 * @param {string} filmId - cle stable (tmdb:<id> ou path:<sha1>)
 * @param {string} fieldName
 * @param {*} value - valeur a verrouiller (ignoree si unlock)
 * @param {boolean} [locked=true] - true=lock, false=unlock
 */
export async function setFieldLock(filmId, fieldName, value, locked = true) {
  if (!filmId || !fieldName) return { ok: false, reason: "filmId et fieldName requis" };
  const endpoint = locked ? "library/set_field_lock" : "library/clear_field_lock";
  try {
    const res = await apiPost(endpoint, {
      film_id: String(filmId),
      field_name: String(fieldName),
      locked_value: locked ? value : undefined,
      source: "ui_lock",
    });
    return res?.data || { ok: true };
  } catch (err) {
    return { ok: false, reason: String(err) };
  }
}

/**
 * Recupere les locks d'un film (pour render les cadenas).
 *
 * @param {string} filmId
 * @returns {Promise<{locked_fields: string[]}>}
 */
export async function loadFieldLocks(filmId) {
  if (!filmId) return { locked_fields: [] };
  try {
    const res = await apiPost("library/list_field_locks", { film_id: String(filmId) });
    const list = res?.data?.locks || [];
    return {
      locked_fields: list.map((lk) => String(lk.field_name || "")).filter(Boolean),
    };
  } catch {
    return { locked_fields: [] };
  }
}

/**
 * Render un cadenas inline pour un champ (utilise par lib-inspector).
 * Renvoie le HTML d'un bouton toggle (lock/unlock).
 *
 * @param {string} fieldName
 * @param {boolean} isLocked
 * @returns {string} HTML
 */
export function fieldLockToggleHtml(fieldName, isLocked) {
  const icon = isLocked ? "[verrouille]" : "[deverrouille]";
  const cls = isLocked ? "field-lock-toggle field-lock-toggle--locked" : "field-lock-toggle";
  const label = isLocked ? "Deverrouiller le champ" : "Verrouiller le champ";
  return `<button type="button" class="${cls}" data-field-lock="${escapeHtml(fieldName)}" title="${escapeHtml(label)}">${icon}</button>`;
}

/* =============================================================
 * Vague P / VP-D : Decisions tri-etat & dangerConfirmModal Rejeter
 * =============================================================
 * AC-4 ROADMAP_VAGUE_P : "Rejeter Tout" doit declencher
 * `dangerConfirmModal` avec countdown 3s SI plus de 50 items.
 * Memo `feedback_cinesort_actions_dangereuses` : toute action UI
 * destructive demande une modale dediee (jamais window.confirm).
 */

/**
 * Confirme un rejet en masse via `dangerConfirmModal`. Si la liste
 * contient plus de 50 elements, un countdown de 3s est applique sur
 * le bouton "Rejeter" (memo actions dangereuses).
 *
 * @param {Array<object>} rows - rows visees par le rejet
 * @param {Function} onConfirm - callback applique apres confirmation
 */
export function confirmBulkReject(rows, onConfirm) {
  const count = Array.isArray(rows) ? rows.length : 0;
  // mega-hotfix frontend_ui_polish (#5) : countdown gradue (0-3s entre 30 et 100
  // elements). Conserve AC-4 ("countdown si > 50") : la valeur graduee est
  // ~1.5-3s dans cette plage, jamais 0s, donc la regle reste respectee.
  const countdownSeconds = _gradedCountdownSeconds(count);

  // Items list : on prend les 5 premiers titres (la modale gere "+ N autres").
  const items = (rows || []).slice(0, 50).map((r) => {
    const t = String((r && (r.proposed_title || r.original_title || r.folder)) || "?");
    const y = r && (r.proposed_year || r.year);
    return y ? `${t} (${y})` : t;
  });

  const consequence = count > 50
    ? `Vous etes sur le point de rejeter ${count} films d'un seul coup. Cette action peut etre annulee mais demande un re-traitement complet.`
    : `Les ${count} films listes seront marques comme rejetes (non appliques au prochain Apply).`;

  return dangerConfirmModal({
    title: `Rejeter ${count} film${count > 1 ? "s" : ""} ?`,
    items,
    consequence,
    countdownSeconds,
    confirmLabel: "Rejeter",
    cancelLabel: "Annuler",
    onConfirm: async () => {
      if (typeof onConfirm === "function") {
        await onConfirm();
      }
    },
  });
}

/**
 * Vague P / VP-G AC-5 : confirme la reinitialisation TOTALE des decisions
 * (efface accepted+rejected+deferred). Action destructive -> `dangerConfirmModal`
 * OBLIGATOIRE avec countdown 3s si plus de 50 decisions posees (memo
 * feedback_cinesort_actions_dangereuses).
 *
 * Si zero decision posee : no-op silencieux (pas de modal inutile).
 *
 * @param {Map<string,string>} decisionsMap - Map row_id -> 'approved'/'rejected'/'deferred'
 * @param {Function} onConfirm - callback applique apres confirmation
 */
export function confirmResetDecisions(decisionsMap, onConfirm) {
  const decisions = decisionsMap instanceof Map ? decisionsMap : new Map();
  const count = decisions.size;
  if (count === 0) {
    // Rien a effacer -> on n'affiche pas de modal (UX silencieuse).
    if (typeof onConfirm === "function") onConfirm();
    return Promise.resolve();
  }

  // Comptage par etat pour la modale.
  let approved = 0;
  let rejected = 0;
  let deferred = 0;
  for (const dec of decisions.values()) {
    if (dec === "approved") approved++;
    else if (dec === "rejected") rejected++;
    else if (dec === "deferred") deferred++;
  }

  // mega-hotfix frontend_ui_polish (#5) : countdown gradue (0-3s entre 30 et 100
  // elements). Conserve AC-5 ("countdown si > 50") : la valeur graduee est
  // ~1.5-3s dans cette plage, jamais 0s, donc la regle reste respectee.
  const countdownSeconds = _gradedCountdownSeconds(count);

  const items = [];
  if (approved > 0) items.push(`${approved} decision(s) "accepte(es)"`);
  if (deferred > 0) items.push(`${deferred} decision(s) "reporte(es)"`);
  if (rejected > 0) items.push(`${rejected} decision(s) "rejete(es)"`);

  const consequence = count > 50
    ? `Vous etes sur le point d'effacer ${count} decisions de validation. Cette action n'est pas reversible : il faudra refaire la revue.`
    : `Toutes les decisions accepted/rejected/deferred seront effacees. Le brouillon de validation revient a vide.`;

  return dangerConfirmModal({
    title: `Reinitialiser ${count} decision${count > 1 ? "s" : ""} ?`,
    items,
    consequence,
    countdownSeconds,
    confirmLabel: "Reinitialiser",
    cancelLabel: "Annuler",
    onConfirm: async () => {
      if (typeof onConfirm === "function") {
        await onConfirm();
      }
    },
  });
}

/**
 * Filtre les rows par etat de decision tri-etat (VP-D).
 *
 * @param {string} state - 'accepted' | 'rejected' | 'deferred' | 'pending'
 * @returns {Array<object>} rows correspondants
 */
export function filterByDecisionState(state) {
  if (!_state || !Array.isArray(_allRows)) return [];
  const want = String(state || "").toLowerCase();
  return _allRows.filter((row) => {
    const dec = _state.decisions.get(String(row.row_id)) || null;
    if (want === "accepted") return dec === "approved";
    if (want === "rejected") return dec === "rejected";
    if (want === "deferred") return dec === "deferred";
    if (want === "pending") return dec === null;
    return false;
  });
}
