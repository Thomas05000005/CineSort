/* views/review.js — Review triage distant (approuver/rejeter depuis le navigateur) */

import { $, escapeHtml } from "../core/dom.js";
import { apiGet, apiPost } from "../core/api.js";
import { tableHtml } from "../components/table.js";
import { badgeHtml } from "../components/badge.js";
import { showModal, closeModal } from "../components/modal.js";
import { fmtBytes as _fmtSize, formatDateTime } from "../core/format.js";
import { skeletonLinesHtml } from "../components/skeleton.js";
import { glossaryTooltip } from "../components/glossary-tooltip.js";
import { getNavSignal, isAbortError } from "../core/nav-abort.js";

/* --- Etat local -------------------------------------------- */

let _runId = null;
let _rows = [];
/** Map<string, "approved"|"rejected"|null> */
let _decisions = new Map();
let _autoThreshold = 85;

/* --- Draft auto (V2-03) ------------------------------------ */
/* Persiste les decisions in-memory dans localStorage pour survivre crash/refresh.
 * Cle : val_draft_<run_id>. TTL 30j. Nettoye apres save_validation reussi. */
const VAL_DRAFT_KEY_PREFIX = "val_draft_";
const VAL_DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000;

/* V2-C R4-MEM-5 : la purge globale des drafts expires (TTL 30j) est dans
 * core/drafts-cleanup.js (re-exportee ici pour compat retro). Appelee une
 * fois au boot du dashboard, scanne toutes les cles val_draft_* et supprime
 * celles dont le timestamp depasse VAL_DRAFT_TTL_MS. */
export { cleanupExpiredDrafts } from "../core/drafts-cleanup.js";

let _draftSaveTimer = null;

function _scheduleDraftSave() {
  if (_draftSaveTimer) clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(_saveDraft, 500);
}

function _decisionsToObject() {
  const out = {};
  for (const [id, dec] of _decisions.entries()) {
    if (dec === "approved" || dec === "rejected") out[id] = dec;
  }
  return out;
}

function _saveDraft() {
  if (!_runId) return;
  try {
    const payload = {
      ts: Date.now(),
      runId: _runId,
      decisions: _decisionsToObject(),
    };
    localStorage.setItem(VAL_DRAFT_KEY_PREFIX + _runId, JSON.stringify(payload));
  } catch (e) {
    console.warn("[review] draft save failed", e);
  }
}

function _checkAndOfferRestore() {
  if (!_runId) return;
  let raw;
  try {
    raw = localStorage.getItem(VAL_DRAFT_KEY_PREFIX + _runId);
  } catch (e) { return; }
  if (!raw) return;
  let draft;
  try {
    draft = JSON.parse(raw);
  } catch (e) { _clearDraft(); return; }
  if (!draft || !draft.decisions || typeof draft.decisions !== "object") return;

  const age = Date.now() - (draft.ts || 0);
  if (age > VAL_DRAFT_TTL_MS) {
    _clearDraft();
    return;
  }

  // Si toutes les decisions du draft sont identiques a l'etat courant, inutile de proposer.
  let differs = false;
  for (const [id, val] of Object.entries(draft.decisions)) {
    if ((_decisions.get(id) || null) !== val) { differs = true; break; }
  }
  if (!differs) return;

  _showRestoreBanner(draft);
}

function _showRestoreBanner(draft) {
  if (document.getElementById("valDraftBanner")) return;
  // V6-04 : datetime locale-aware via core/format.js (formatDateTime).
  const date = formatDateTime(draft.ts);
  const count = Object.keys(draft.decisions || {}).length;
  const html = `<div class="alert alert--info" id="valDraftBanner" role="status" style="display:flex;gap:.6em;align-items:center;flex-wrap:wrap;margin-bottom:1em">
    <span>Decisions non sauvegardees du <strong>${escapeHtml(date)}</strong> (${count} films).</span>
    <button class="btn btn--compact" id="valDraftRestore">Restaurer</button>
    <button class="btn btn--compact" id="valDraftDiscard">Ignorer</button>
  </div>`;
  const root = $("reviewContent");
  if (!root) return;
  root.insertAdjacentHTML("afterbegin", html);
  document.getElementById("valDraftRestore")?.addEventListener("click", () => _restoreDraft(draft));
  document.getElementById("valDraftDiscard")?.addEventListener("click", () => _discardDraft());
}

function _restoreDraft(draft) {
  if (draft && draft.decisions && typeof draft.decisions === "object") {
    for (const [id, val] of Object.entries(draft.decisions)) {
      if (val === "approved" || val === "rejected") _decisions.set(id, val);
    }
  }
  document.getElementById("valDraftBanner")?.remove();
  _renderTable();
  _updateCounters();
}

function _discardDraft() {
  _clearDraft();
  document.getElementById("valDraftBanner")?.remove();
}

function _clearDraft() {
  if (!_runId) return;
  try {
    localStorage.removeItem(VAL_DRAFT_KEY_PREFIX + _runId);
  } catch (e) { /* ignore */ }
}

/* --- SVG icones inline ------------------------------------- */

const _IC_CHECK = '<svg viewBox="0 0 24 24" width="16" height="16"><polyline points="20 6 9 17 4 12"/></svg>';
const _IC_X = '<svg viewBox="0 0 24 24" width="16" height="16"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

/* --- Colonnes de la table ---------------------------------- */

const _COLUMNS = [
  { key: "proposed_title", label: "Titre", sortable: false, render: (v, row) => {
    const saga = String(row.tmdb_collection_name || "").trim();
    const aa = row.audio_analysis || {};
    const audioB = aa.badge_label ? ` <span class="badge badge-audio-${aa.badge_tier || "basique"}" title="${escapeHtml(aa.badge_label)}">${escapeHtml(aa.badge_label)}</span>` : "";
    const ed = String(row.edition || "").trim();
    const edB = ed ? ` <span class="badge badge-edition" title="${escapeHtml(ed)}">${escapeHtml(ed)}</span>` : "";
    return escapeHtml(v || "") + (saga ? ` <span class="badge badge-saga" title="${escapeHtml(saga)}">Saga</span>` : "") + edB + audioB;
  }},
  { key: "proposed_year", label: "Annee", sortable: false },
  { key: "folder", label: "Ancien chemin", sortable: false, render: (v) => `<span class="text-muted" title="${escapeHtml(v || "")}">${escapeHtml(_shortPath(v))}</span>` },
  { key: "proposed_path", label: "Nouveau chemin", sortable: false, render: (v) => `<span title="${escapeHtml(v || "")}">${escapeHtml(_shortPath(v))}</span>` },
  { key: "confidence", label: "Confiance", sortable: false, render: (v) => badgeHtml("confidence", _confLabel(v)) },
  { key: "warning_flags", label: "Alertes", sortable: false, render: (v, row) => {
    const flags = _parseFlags(v);
    const notMovie = flags.includes("not_a_movie") ? ' <span class="badge badge-not-a-movie" title="Contenu suspect">Non-film</span>' : "";
    const integrity = flags.includes("integrity_header_invalid") ? ' <span class="badge badge-integrity" title="Header invalide">Corrompu</span>' : "";
    const encWarn = Array.isArray(row.encode_warnings) ? row.encode_warnings : [];
    const upscale = encWarn.includes("upscale_suspect") ? ' <span class="badge badge-danger" title="Probable upscale">Upscale</span>' : "";
    const light4k = encWarn.includes("4k_light") ? ' <span class="badge badge-warning" title="4K compresse">4K light</span>' : "";
    const reencode = encWarn.includes("reencode_degraded") ? ' <span class="badge badge-danger" title="Re-encode destructif">Re-encode</span>' : "";
    const audioLang = (flags.includes("audio_language_missing") || flags.includes("audio_language_incomplete")) ? ' <span class="badge badge-audio-lang" title="Piste(s) audio sans tag langue">Langue ?</span>' : "";
    const mkvTitle = encWarn.includes("mkv_title_mismatch") ? ' <span class="badge badge-mkv-title" title="Titre conteneur MKV incoherent">MKV titre</span>' : "";
    const rootLevel = flags.includes("root_level_source") ? ' <span class="badge badge-root-level" title="Film pose directement a la racine — sera range dans un sous-dossier">Depuis la racine</span>' : "";
    // P1.1 : NFO cross-validation
    const nfoFile = flags.includes("nfo_file_mismatch") ? ' <span class="badge badge-nfo-mismatch" title="NFO matche dossier XOR fichier — vidéo possiblement remplacée">NFO partiel</span>' : "";
    const nfoRuntime = encWarn.includes("nfo_runtime_mismatch") ? ' <span class="badge badge-nfo-mismatch" title="Durée vidéo ne correspond pas au NFO">Durée NFO ?</span>' : "";
    // P2.2 : deux films même titre (remake/reboot)
    const titleAmbig = flags.includes("title_ambiguity_detected") ? ' <span class="badge badge-title-ambig" title="Plusieurs films TMDb partagent ce titre — vérifier l\'année">Titre ambigu</span>' : "";
    return (flags.length ? `<span class="badge badge-warning">${flags.length}</span>` : "") + notMovie + integrity + upscale + light4k + reencode + audioLang + mkvTitle + rootLevel + nfoFile + nfoRuntime + titleAmbig;
  }},
  { key: "_actions", label: "Actions", sortable: false, render: (_, row) => _actionCellHtml(row) },
];

/* --- Helpers ----------------------------------------------- */

function _shortPath(p) {
  const s = String(p || "");
  if (s.length <= 50) return s;
  return s.slice(0, 22) + "..." + s.slice(-22);
}

function _confLabel(c) {
  const v = Number(c) || 0;
  if (v >= 80) return "high";
  if (v >= 60) return "med";
  return "low";
}

function _parseFlags(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  return String(v).split(",").map((s) => s.trim()).filter(Boolean);
}

function _rowId(row) {
  return String(row.row_id || "").trim();
}

function _actionCellHtml(row) {
  const id = _rowId(row);
  const dec = _decisions.get(id) || null;
  const approvedCls = dec === "approved" ? " active" : "";
  const rejectedCls = dec === "rejected" ? " active" : "";
  return `<div class="review-actions-cell">
    <button class="btn-review btn-approve${approvedCls}" data-action="approve" data-rid="${escapeHtml(id)}" title="Approuver">${_IC_CHECK}</button>
    <button class="btn-review btn-reject${rejectedCls}" data-action="reject" data-rid="${escapeHtml(id)}" title="Rejeter">${_IC_X}</button>
    <button class="btn btn--small btn-inspect-mobile" data-row-id="${escapeHtml(id)}" aria-label="Inspecter ce film">Inspecter</button>
  </div>`;
}

/* --- Chargement initial ------------------------------------ */

async function _load() {
  const container = $("reviewContent");
  if (!container) return;

  // V2-08 : skeleton uniquement au 1er load (ne flashe pas sur re-render apres apply)
  if (!container.innerHTML.trim()) {
    container.innerHTML = `<div aria-busy="true" aria-label="Chargement de la review">
      ${skeletonLinesHtml(2)}
      <div class="skeleton skeleton--block" style="height:240px;margin-top:var(--sp-3)"></div>
    </div>`;
  }

  try {
    // Detecter le run courant via health
    const healthRes = await apiGet("/api/health");
    _runId = healthRes.data?.active_run_id || null;

    // Si pas de run actif, chercher le dernier via get_global_stats
    if (!_runId) {
      const statsRes = await apiPost("get_global_stats", { limit_runs: 1 });
      const runs = statsRes.data?.runs_summary || [];
      if (runs.length > 0) _runId = runs[0].run_id;
    }

    if (!_runId) {
      container.innerHTML = '<div class="card"><p class="text-muted">Aucun run disponible pour review.</p></div>';
      return;
    }

    // Charger le plan + decisions existantes en parallele.
    // Audit ID-ROB-002 : Promise.allSettled pour qu'un echec sur load_validation
    // ou get_settings ne cache pas le plan (et inversement).
    // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur navigate ailleurs.
    const navSig = getNavSignal();
    const labels = ["get_plan", "load_validation", "get_settings"];
    const results = await Promise.allSettled([
      apiPost("run/get_plan", { run_id: _runId }, { signal: navSig }),
      apiPost("load_validation", { run_id: _runId }, { signal: navSig }),
      apiPost("settings/get_settings", {}, { signal: navSig }),
    ]);
    const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
    const [planRes, valRes, settingsRes] = results.map(_val);
    const failed = labels.filter((_, i) => results[i].status !== "fulfilled");
    if (failed.length > 0) console.warn("[review] endpoints en echec:", failed);

    const planData = planRes?.data || {};
    _rows = Array.isArray(planData.rows) ? planData.rows : [];
    _autoThreshold = Number(settingsRes?.data?.auto_approve_threshold) || 85;

    // Restaurer les decisions existantes
    _decisions = new Map();
    const savedDec = valRes?.data?.decisions || valRes?.data || {};
    if (typeof savedDec === "object" && !Array.isArray(savedDec)) {
      for (const [id, d] of Object.entries(savedDec)) {
        if (d && typeof d === "object") {
          if (d.ok === true) _decisions.set(id, "approved");
          else if (d.ok === false && (d.edited || d.title)) _decisions.set(id, "rejected");
        }
      }
    }

    _renderFull(container);

    // V2-03 : proposer restauration si un draft non sauvegarde existe pour ce run.
    _checkAndOfferRestore();
  } catch (err) {
    // V2-C R4-MEM-6 : si le fetch a ete abort par le router (navigate), ne pas
    // afficher d'erreur — la vue est deja remplacee.
    if (isAbortError(err)) return;
    container.innerHTML = `<p class="status-msg error">Erreur : ${escapeHtml(String(err))}</p>`;
    console.error("[review]", err);
  }
}

/* --- Rendu complet ----------------------------------------- */

function _renderFull(container) {
  let html = "";

  // En-tete avec run_id et compteurs
  html += `<div class="flex justify-between items-center mb-4">`;
  html += `<p>${glossaryTooltip("Run")} : <span class="text-accent">${escapeHtml(_runId || "")}</span> — ${_rows.length} films</p>`;
  html += `<div id="reviewCounters" class="review-counters"></div>`;
  html += `</div>`;

  // Barre d'actions bulk
  html += '<div class="review-bulk-bar">';
  html += '<button id="btnBulkApprove" class="btn btn-approve-bulk">Approuver les surs</button>';
  html += '<button id="btnBulkReject" class="btn btn-danger">Tout rejeter</button>';
  html += '<button id="btnBulkReset" class="btn">Reinitialiser</button>';
  html += '<button id="btnDashUndo" class="btn" style="margin-left:auto">Annuler dernier apply</button>';
  html += "</div>";

  // Table
  html += '<div id="reviewTable" class="mt-4"></div>';

  // Section doublons detectes
  html += '<div id="reviewDuplicatesSection" class="mt-4"></div>';

  // Barre d'actions en bas (save + preview + dry-run + apply)
  html += '<div class="review-action-bar mt-4">';
  html += '<button id="btnReviewSave" class="btn">Sauvegarder</button>';
  html += '<button id="btnReviewPreview" class="btn">Doublons / Conflits</button>';
  html += '<button id="btnDashPreviewApply" class="btn" title="V4.3 : apercu detaille avant + vs apres par film">Apercu detaille</button>';
  html += `<button id="btnReviewDryRun" class="btn">Dry-run (test)</button>${glossaryTooltip("Dry-run", "")}`;
  html += `<button id="btnReviewApply" class="btn btn-primary">Appliquer</button>${glossaryTooltip("Apply", "")}`;
  html += "</div>";
  // V4.6 : boutons d'export du journal d'audit
  html += '<div class="review-action-bar mt-2" style="flex-wrap:wrap">';
  html += '<button id="btnDashAuditJsonl" class="btn" style="font-size:var(--fs-sm)" title="Journal d\'audit JSONL (apres apply reel)">Journal audit (.jsonl)</button>';
  html += '<button id="btnDashAuditCsv" class="btn" style="font-size:var(--fs-sm)" title="Journal d\'audit au format CSV">Journal (.csv)</button>';
  html += "</div>";
  html += '<div id="reviewMsg" class="status-msg mt-4"></div>';

  // V3-06 : drawer mobile inspector (cache par defaut, visible <768px sur clic)
  html += `
    <aside class="inspector-drawer" id="inspectorDrawer" aria-hidden="true" role="dialog" aria-label="Inspecteur film">
      <div class="inspector-drawer__header">
        <h3>Inspecteur</h3>
        <button class="btn btn--icon" id="btnCloseDrawer" aria-label="Fermer">×</button>
      </div>
      <div class="inspector-drawer__body" id="inspectorDrawerBody"></div>
    </aside>
    <div class="inspector-drawer__overlay" id="inspectorDrawerOverlay" hidden></div>
  `;

  container.innerHTML = html;

  _renderTable();
  _updateCounters();
  _hookBulkActions();
  _hookBottomActions();
  _hookInspectorDrawer();
}

/* --- Table ------------------------------------------------- */

function _renderTable() {
  const el = $("reviewTable");
  if (!el) return;

  el.innerHTML = tableHtml({
    columns: _COLUMNS,
    rows: _rows,
    id: "revTable",
    emptyText: "Aucun film a revoir.",
  });

  // Colorier les lignes selon la decision
  const tbody = el.querySelector("tbody");
  if (tbody) {
    const trs = tbody.querySelectorAll("tr");
    trs.forEach((tr, i) => {
      const row = _rows[i];
      if (!row) return;
      const dec = _decisions.get(_rowId(row));
      tr.classList.remove("row-approved", "row-rejected");
      if (dec === "approved") tr.classList.add("row-approved");
      else if (dec === "rejected") tr.classList.add("row-rejected");
    });
  }

  // Hook boutons approve/reject dans les cellules
  el.querySelectorAll(".btn-review").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const rid = btn.dataset.rid;
      const action = btn.dataset.action;
      _toggleDecision(rid, action);
    });
  });
}

/* --- Decisions --------------------------------------------- */

function _toggleDecision(rowId, action) {
  console.log("[review] %s row=%s", action, rowId);
  const current = _decisions.get(rowId) || null;
  const target = action === "approve" ? "approved" : "rejected";
  // Toggle : meme action → annuler, action differente → changer
  _decisions.set(rowId, current === target ? null : target);
  _renderTable();
  _updateCounters();
  _scheduleDraftSave();
}

function _updateCounters() {
  const el = $("reviewCounters");
  if (!el) return;
  let approved = 0, rejected = 0, pending = 0;
  for (const row of _rows) {
    const dec = _decisions.get(_rowId(row)) || null;
    if (dec === "approved") approved++;
    else if (dec === "rejected") rejected++;
    else pending++;
  }
  el.innerHTML =
    `<span class="badge badge-success">${approved} approuvé(s)</span> ` +
    `<span class="badge badge-danger">${rejected} rejeté(s)</span> ` +
    `<span class="badge">${pending} en attente</span>`;
}

/* --- Construire le payload decisions pour l'API ------------ */

function _buildDecisionsPayload() {
  const out = {};
  for (const row of _rows) {
    const id = _rowId(row);
    const dec = _decisions.get(id) || null;
    out[id] = {
      ok: dec === "approved",
      title: String(row.proposed_title || "").trim(),
      year: parseInt(row.proposed_year || 0, 10) || 0,
      edited: false,
    };
  }
  return out;
}

/* --- Actions bulk ------------------------------------------ */

function _hookBulkActions() {
  const btnApprove = $("btnBulkApprove");
  const btnReject = $("btnBulkReject");
  const btnReset = $("btnBulkReset");

  if (btnApprove) {
    btnApprove.addEventListener("click", () => {
      for (const row of _rows) {
        const conf = Number(row.confidence) || 0;
        if (conf >= _autoThreshold) _decisions.set(_rowId(row), "approved");
      }
      _renderTable();
      _updateCounters();
      _scheduleDraftSave();
    });
  }

  if (btnReject) {
    btnReject.addEventListener("click", () => {
      for (const row of _rows) _decisions.set(_rowId(row), "rejected");
      _renderTable();
      _updateCounters();
      _scheduleDraftSave();
    });
  }

  if (btnReset) {
    btnReset.addEventListener("click", () => {
      _decisions = new Map();
      _renderTable();
      _updateCounters();
      _scheduleDraftSave();
    });
  }

  // Undo dernier apply (V4.4 : gestion atomic + ABORTED_HASH_MISMATCH)
  const btnUndo = $("btnDashUndo");
  if (btnUndo) {
    btnUndo.addEventListener("click", async () => {
      if (!_runId) return;
      btnUndo.disabled = true;
      console.log("[review] undo preview run=%s", _runId);
      try {
        // Preview d'abord
        const preview = await apiPost("undo_last_apply", { run_id: _runId, dry_run: true });
        if (!preview.data?.ok) {
          alert(preview.data?.message || "Aucun apply a annuler.");
          btnUndo.disabled = false;
          return;
        }
        const count = preview.data?.count || preview.data?.operations_count || 0;
        if (!confirm(`Annuler le dernier apply ? ${count} operation(s) seront restaurees.`)) {
          btnUndo.disabled = false;
          return;
        }
        // Execution reelle (atomic=True par defaut = safety P1.2)
        const result = await apiPost("undo_last_apply", { run_id: _runId, dry_run: false, atomic: true });
        const data = result.data || {};
        if (data.status === "ABORTED_HASH_MISMATCH") {
          // P1.2 : refus atomique — fichiers modifies depuis apply
          const details = (data.preverify?.mismatch_details || []).slice(0, 5);
          const lines = details.map(d => `• ${d.dst_path}\n  (${d.reason})`).join("\n");
          const more = data.preverify?.hash_mismatch_count > details.length ? `\n...et ${data.preverify.hash_mismatch_count - details.length} autre(s).` : "";
          const msg = `Annulation refusée : ${data.preverify?.hash_mismatch_count} fichier(s) ont été modifiés depuis l'apply.\n\n${lines}${more}\n\nAucun fichier n'a été déplacé.\n\nForcer l'annulation (les fichiers modifiés seront ignorés) ?`;
          if (confirm(msg)) {
            const forced = await apiPost("undo_last_apply", { run_id: _runId, dry_run: false, atomic: false });
            if (forced.data?.ok) {
              alert("Annulation forcee terminee.");
              await _load();
            } else {
              alert(forced.data?.message || "Erreur lors de l'annulation forcee.");
            }
          }
        } else if (data.ok) {
          alert("Annulation reussie !");
          await _load();
        } else {
          alert(data.message || "Erreur lors de l'annulation.");
        }
      } catch (err) {
        console.error("[review] undo error", err);
        alert("Erreur : " + err);
      }
      btnUndo.disabled = false;
    });
  }

  // V4.3 : Preview apply detaillee (cote-a-cote avec verdicts)
  const btnPreviewApply = $("btnDashPreviewApply");
  if (btnPreviewApply) {
    btnPreviewApply.addEventListener("click", async () => {
      if (!_runId) return;
      btnPreviewApply.disabled = true;
      try {
        const decisions = _buildDecisionsPayload();
        const r = await apiPost("run/build_apply_preview", { run_id: _runId, decisions });
        const data = r.data || {};
        if (!data.ok) {
          alert(data.message || "Apercu impossible.");
          return;
        }
        _showPreviewModal(data);
      } catch (err) {
        console.error("[review] preview error", err);
        alert("Erreur : " + err);
      } finally {
        btnPreviewApply.disabled = false;
      }
    });
  }

  // V4.6 : Export audit apply
  const btnExportAuditJsonl = $("btnDashAuditJsonl");
  const btnExportAuditCsv = $("btnDashAuditCsv");
  if (btnExportAuditJsonl) btnExportAuditJsonl.addEventListener("click", () => _downloadDashAudit("jsonl"));
  if (btnExportAuditCsv) btnExportAuditCsv.addEventListener("click", () => _downloadDashAudit("csv"));
}

/* V4.3 : rendu modale preview apply */
function _showPreviewModal(data) {
  const films = data.films || [];
  const t = data.totals || {};
  let html = `<div style="padding:10px; border:1px solid var(--border); border-radius:4px; background:var(--bg-raised); margin-bottom:10px">
    <div style="display:flex; gap:16px; font-size:var(--fs-sm); flex-wrap:wrap">
      <div><strong>${t.films || 0}</strong> film(s)</div>
      <div><strong>${t.changes_count || 0}</strong> changement(s)</div>
      ${t.noop_count ? `<div><strong>${t.noop_count}</strong> deja conforme(s)</div>` : ""}
      ${t.quarantined ? `<div style="color:#F59E0B"><strong>${t.quarantined}</strong> quarantaine</div>` : ""}
      ${t.errors ? `<div style="color:#EF4444"><strong>${t.errors}</strong> erreur(s)</div>` : ""}
    </div>
    <div style="font-size:var(--fs-xs); color:var(--text-muted); margin-top:4px">Total ${t.total_ops || 0} operations. Aucun fichier n'a ete touche.</div>
  </div>`;
  if (!films.length) {
    html += '<p class="text-muted">Aucun film avec changement dans ce plan.</p>';
  } else {
    for (const film of films) {
      const warns = (film.warnings || []).filter(w => w && !String(w).startsWith("subtitle_missing_"));
      const warnTag = warns.length ? ` <span style="font-size:var(--fs-xs); padding:1px 6px; border-radius:8px; background:rgba(251,191,36,.15); color:#FBBF24; margin-left:4px">${warns.length} alerte${warns.length > 1 ? "s" : ""}</span>` : "";
      const tierHtml = typeof tierPill === "function" ? tierPill(film.confidence_label || "", { compact: true }) : escapeHtml(String(film.confidence_label || ""));
      const ctMap = { rename_folder: "Renommage dossier", move_files: "Deplacement fichiers", move_mixed: "Renommage + deplacement", noop: "Aucun changement" };
      const ctLabel = ctMap[film.change_type] || film.change_type || "Changement";
      const opsHtml = (film.ops || []).map(op => `<div style="font-family:monospace; font-size:var(--fs-xs); color:var(--text-muted); padding:2px 0">
        <span style="color:var(--text-muted)">${escapeHtml(op.op_type)}</span>
        <div style="margin-left:6px">${escapeHtml(_shortenDashPreviewPath(op.src_path))}<br><span style="color:#60A5FA">→</span> ${escapeHtml(_shortenDashPreviewPath(op.dst_path))}</div>
      </div>`).join("");
      html += `<div style="padding:10px; border:1px solid var(--border); border-radius:4px; background:var(--bg-raised); margin-bottom:8px">
        <div style="display:flex; justify-content:space-between; align-items:center">
          <div>
            <strong>${escapeHtml(film.title || "?")}</strong>${film.year ? ` <span class="text-muted">(${escapeHtml(String(film.year))})</span>` : ""}
            <div style="font-size:var(--fs-xs); color:var(--text-muted)">${escapeHtml(ctLabel)}</div>
          </div>
          <div>${tierHtml}${warnTag}</div>
        </div>
        <div style="margin-top:6px">${opsHtml}</div>
      </div>`;
    }
  }
  showModal({ title: "Apercu detaille avant application", body: html });
}

function _shortenDashPreviewPath(p, max = 65) {
  const s = String(p || "");
  if (s.length <= max) return s;
  return s.slice(0, Math.floor(max * 0.4)) + " … " + s.slice(-Math.floor(max * 0.5));
}

/* V4.6 : telechargement journal d'audit */
async function _downloadDashAudit(format) {
  if (!_runId) { alert("Aucun run selectionne."); return; }
  try {
    const r = await apiPost("export_apply_audit", { run_id: _runId, batch_id: null, as_format: format });
    const data = r.data || {};
    if (!data.ok) { alert(data.message || "Export impossible."); return; }
    if (!data.count || !data.content) { alert("Aucune entree d'audit disponible (apply reel requis)."); return; }
    const mime = format === "csv" ? "text/csv" : "application/x-ndjson";
    const blob = new Blob([data.content], { type: mime + ";charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.download = `apply_audit_${_runId}_${ts}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("[review] audit error", err);
    alert("Erreur : " + err);
  }
}

/* --- Actions bas (save, preview, apply) -------------------- */

function _hookBottomActions() {
  const btnSave = $("btnReviewSave");
  const btnPreview = $("btnReviewPreview");
  const btnDryRun = $("btnReviewDryRun");
  const btnApply = $("btnReviewApply");

  if (btnSave) btnSave.addEventListener("click", _onSave);
  if (btnPreview) btnPreview.addEventListener("click", _onPreview);
  if (btnDryRun) btnDryRun.addEventListener("click", _onDryRunAlone);
  if (btnApply) btnApply.addEventListener("click", _onApply);

  // Charger les doublons au chargement
  _loadDuplicatesSection();
}

async function _onSave() {
  const btn = $("btnReviewSave");
  if (btn) btn.disabled = true;
  _showMsg("Sauvegarde...");
  try {
    const res = await apiPost("save_validation", {
      run_id: _runId,
      decisions: _buildDecisionsPayload(),
    });
    const ok = res.data?.ok !== false;
    if (ok) _clearDraft();  // V2-03 : draft localStorage plus necessaire apres confirmation serveur.
    _showMsg(ok ? "Décisions sauvegardées." : escapeHtml(res.data?.message || "Echec."), !ok);
  } catch { _showMsg("Erreur reseau.", true); }
  finally { if (btn) btn.disabled = false; }
}

async function _onPreview() {
  const btn = $("btnReviewPreview");
  if (btn) btn.disabled = true;
  _showMsg("Verification des doublons...");
  try {
    const res = await apiPost("check_duplicates", {
      run_id: _runId,
      decisions: _buildDecisionsPayload(),
    });
    const d = res.data || {};
    const groups = d.groups || [];
    let body;
    if (groups.length > 0) {
      body = `<p>${groups.length} conflit(s) détecté(s) :</p>`;
      for (const g of groups) {
        body += `<div class="card mt-4"><h4>${escapeHtml(g.title || "?")} ${g.year ? `(${g.year})` : ""}</h4>`;
        if (g.comparison) {
          body += _buildDashComparisonHtml(g.comparison);
        } else {
          body += `<p class="text-muted">${escapeHtml(g.plan_conflict ? "Conflit de plan (meme destination)" : "Doublon detecte")}</p>`;
        }
        body += "</div>";
      }
    } else {
      body = '<p class="status-msg success">Aucun conflit détecté. L\'application est sure.</p>';
    }
    showModal({ title: "Impact de l'application", body });
  } catch { _showMsg("Erreur reseau.", true); }
  finally { if (btn) btn.disabled = false; }
}

function _compareTierColorDash(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "platinum") return "#A78BFA";
  if (t === "gold") return "#FBBF24";
  if (t === "silver") return "#9CA3AF";
  if (t === "bronze") return "#FB923C";
  return "#EF4444";
}

function _dashCompareCard(side, cmp) {
  const isA = side === "a";
  const name = isA ? (cmp.file_a_name || "Fichier A") : (cmp.file_b_name || "Fichier B");
  const size = isA ? cmp.file_a_size : cmp.file_b_size;
  const quality = isA ? (cmp.quality_a || {}) : (cmp.quality_b || {});
  const verdict = isA ? cmp.verdict_a : cmp.verdict_b;
  const isWinner = cmp.winner === side;
  const isTie = cmp.winner === "tie";
  const tierColor = _compareTierColorDash(quality.tier);
  const verdictColor = isWinner ? "#34D399" : (isTie ? "#9CA3AF" : "#FB923C");
  const verdictIcon = isWinner ? "✓" : (isTie ? "≡" : "⚠");
  const borderColor = isWinner ? "#34D399" : (isTie ? "var(--border)" : "rgba(251,146,60,.4)");

  const byName = {};
  for (const c of (cmp.criteria || [])) byName[c.name] = isA ? c.value_a : c.value_b;
  const resolution = byName.resolution || "?";
  const codec = byName.video_codec || byName.codec || "?";
  const bitrate = byName.bitrate || "?";
  const audio = byName.audio_codec || byName.audio || "?";
  const channels = byName.audio_channels || byName.channels || "";
  const hdr = byName.hdr;

  return `<div class="compare-card" style="flex:1; min-width:0; padding:10px; border:2px solid ${borderColor}; border-radius:8px; background:var(--bg-raised)">
    <div style="font-size:var(--fs-xs); color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em; margin-bottom:3px">Version ${side.toUpperCase()}</div>
    <div style="font-family:monospace; font-size:var(--fs-sm); font-weight:600; word-break:break-all; margin-bottom:8px" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
    <div style="font-size:var(--fs-sm); line-height:1.6; color:var(--text-muted)">
      <div><strong style="color:var(--text-primary)">${escapeHtml(String(resolution))}</strong> · ${escapeHtml(String(codec).toUpperCase())} · ${escapeHtml(String(bitrate))}</div>
      <div>${escapeHtml(String(audio).toUpperCase())}${channels && channels !== "?" ? " " + escapeHtml(String(channels)) : ""}</div>
      ${hdr && hdr !== "-" && hdr !== "?" ? `<div>${escapeHtml(String(hdr))}</div>` : ""}
      <div style="margin-top:4px"><strong style="color:var(--text-primary)">${_fmtSize(size || 0)}</strong></div>
    </div>
    <hr style="border:0; border-top:1px solid var(--border); margin:8px 0">
    <div style="display:flex; justify-content:space-between; align-items:center">
      <div><div style="font-size:var(--fs-xs); color:var(--text-muted)">Score</div><div style="font-size:1.3em; font-weight:700; color:${tierColor}">${quality.score || "?"}</div></div>
      <div style="text-align:right"><div style="font-size:var(--fs-xs); color:var(--text-muted)">Tier</div><div style="font-weight:600; color:${tierColor}">${escapeHtml(quality.tier || "?")}</div></div>
    </div>
    <div style="margin-top:8px; padding:5px 8px; border-radius:4px; background:${verdictColor}22; color:${verdictColor}; font-weight:600; font-size:var(--fs-sm); text-align:center">${verdictIcon} ${escapeHtml(verdict || "")}</div>
  </div>`;
}

function _buildDashComparisonHtml(cmp) {
  let html = `<div style="display:flex; gap:10px; margin-top:8px; align-items:stretch; flex-wrap:wrap">
    ${_dashCompareCard("a", cmp)}
    ${_dashCompareCard("b", cmp)}
  </div>`;

  if (cmp.recommendation) {
    const savings = Number(cmp.size_savings) || 0;
    html += `<div style="margin-top:10px; padding:8px; background:rgba(96,165,250,.1); border-left:3px solid #60A5FA; border-radius:4px">
      <div style="font-weight:600; color:#60A5FA; font-size:var(--fs-sm); margin-bottom:3px">Recommandation</div>
      <div style="font-size:var(--fs-sm)">${escapeHtml(cmp.recommendation)}${savings > 0 ? " — économie potentielle " + _fmtSize(savings) : ""}</div>
    </div>`;
  }

  // Détail critères en details
  html += '<details style="margin-top:10px"><summary style="cursor:pointer; font-weight:600; font-size:var(--fs-sm)">Voir le détail critère par critère</summary>';
  html += '<div class="table-wrap" style="margin-top:6px"><table class="compare-table"><thead><tr><th>Critère</th><th>Version A</th><th>Version B</th><th>Points</th></tr></thead><tbody>';
  for (const c of (cmp.criteria || [])) {
    const pts = Number(c.points_delta || 0);
    const ptsStr = pts === 0 ? "=" : (pts > 0 ? `A+${pts}` : `B+${-pts}`);
    const ptsColor = pts === 0 ? "var(--text-muted)" : (pts > 0 ? "#34D399" : "#F59E0B");
    const aStyle = c.winner === "a" ? 'style="color:#34D399; font-weight:600"' : "";
    const bStyle = c.winner === "b" ? 'style="color:#34D399; font-weight:600"' : "";
    html += `<tr><td>${escapeHtml(c.label)}</td><td ${aStyle}>${escapeHtml(c.value_a || "?")}</td><td ${bStyle}>${escapeHtml(c.value_b || "?")}</td><td style="text-align:right; font-family:monospace; font-size:var(--fs-xs); color:${ptsColor}">${ptsStr}</td></tr>`;
  }
  html += '</tbody></table></div></details>';
  return html;
}

/* _fmtSize est un alias de fmtBytes (core/format.js). */

async function _loadDuplicatesSection() {
  const section = $("reviewDuplicatesSection");
  if (!section || !_runId) return;
  try {
    const res = await apiPost("check_duplicates", { run_id: _runId, decisions: _buildDecisionsPayload() });
    const groups = res.data?.groups || [];
    if (groups.length === 0) {
      section.innerHTML = "";
      return;
    }
    let html = `<div class="card"><h3>Doublons detectes (${groups.length})</h3>`;
    for (const g of groups) {
      html += `<div class="card mt-2" style="padding:var(--sp-3)"><h4>${escapeHtml(g.title || "?")} ${g.year ? `(${g.year})` : ""}</h4>`;
      if (g.comparison) {
        html += _buildDashComparisonHtml(g.comparison);
      } else {
        html += `<p class="text-muted">${escapeHtml(g.plan_conflict ? "Conflit de plan" : "Doublon")}</p>`;
      }
      html += "</div>";
    }
    html += "</div>";
    section.innerHTML = html;
  } catch { /* ignore */ }
}

async function _onDryRunAlone() {
  const btn = $("btnReviewDryRun");
  if (btn) btn.disabled = true;
  _showMsg("Dry-run en cours...");
  try {
    const decisions = _buildDecisionsPayload();
    const approvedCount = Object.values(decisions).filter((d) => d.ok).length;
    if (approvedCount === 0) { _showMsg("Aucun film approuve.", true); return; }

    const dryRes = await apiPost("apply", { run_id: _runId, decisions, dry_run: true, quarantine_unapproved: false });
    const d = dryRes.data || {};
    const applied = d.applied ?? 0;
    const skipped = d.skipped ?? 0;
    const failed = d.failed ?? 0;

    let body = `<p><strong>${applied}</strong> film(s) seraient renommé(s)/deplace(s).</p>`;
    if (skipped) body += `<p>${skipped} ignore(s).</p>`;
    if (failed) body += `<p class="status-msg error">${failed} en erreur.</p>`;
    body += `<p class="mt-4 text-muted">Aucune modification effectuée (mode test).</p>`;
    showModal({ title: "Résultat du dry-run", body });
    _showMsg(`Dry-run : ${applied} film(s) seraient déplacés.`);
  } catch { _showMsg("Erreur reseau.", true); }
  finally { if (btn) btn.disabled = false; }
}

async function _onApply() {
  const decisions = _buildDecisionsPayload();
  const approvedCount = Object.values(decisions).filter((d) => d.ok).length;

  if (approvedCount === 0) {
    _showMsg("Aucun film approuve a appliquer.", true);
    return;
  }

  // Etape 1 : dry-run obligatoire
  _showMsg("Dry-run en cours...");
  const btnApply = $("btnReviewApply");
  if (btnApply) btnApply.disabled = true;

  try {
    const dryRes = await apiPost("apply", {
      run_id: _runId,
      decisions,
      dry_run: true,
      quarantine_unapproved: false,
    });
    const dryData = dryRes.data || {};

    if (!dryData.ok && dryData.ok !== undefined) {
      _showMsg(escapeHtml(dryData.message || "Dry-run echoue."), true);
      return;
    }

    // Afficher le resultat du dry-run et proposer de confirmer
    const applied = dryData.applied ?? 0;
    const skipped = dryData.skipped ?? 0;
    const failed = dryData.failed ?? 0;

    let body = `<p><strong>${applied}</strong> film(s) seront renomme(s)/deplace(s).</p>`;
    if (skipped) body += `<p>${skipped} ignore(s).</p>`;
    if (failed) body += `<p class="status-msg error">${failed} en erreur.</p>`;
    body += `<p class="mt-4">Confirmer l'application réelle ?</p>`;

    showModal({
      title: `Appliquer ${applied} film(s)`,
      body,
      actions: [
        { label: "Annuler", cls: "", onClick: () => {} },
        { label: "Confirmer l'application", cls: "btn-primary", onClick: () => _executeApply(decisions) },
      ],
    });
  } catch {
    _showMsg("Erreur reseau pendant le dry-run.", true);
  } finally {
    if (btnApply) btnApply.disabled = false;
  }
}

async function _executeApply(decisions) {
  _showMsg("Application en cours...");
  const btnApply = $("btnReviewApply");
  if (btnApply) btnApply.disabled = true;

  try {
    const res = await apiPost("apply", {
      run_id: _runId,
      decisions,
      dry_run: false,
      quarantine_unapproved: false,
    });
    const d = res.data || {};

    if (d.ok !== false) {
      const applied = d.applied ?? 0;
      _showMsg(`Application terminée : ${applied} film(s) traite(s).`);
      // Recharger la vue apres apply
      setTimeout(() => _load(), 1500);
    } else {
      _showMsg(escapeHtml(d.message || "Echec de l'application."), true);
    }
  } catch {
    _showMsg("Erreur reseau.", true);
  } finally {
    if (btnApply) btnApply.disabled = false;
  }
}

function _showMsg(text, isError = false) {
  const el = $("reviewMsg");
  if (!el) return;
  el.textContent = text;
  el.className = "status-msg" + (isError ? " error" : " success");
}

/* --- V3-06 : Drawer mobile inspector ----------------------- */

/* Rend le contenu detail d'une ligne (titre, chemins, alertes, audio).
 * Reutilisable comme corps du drawer mobile. */
function _renderInspectorContent(rowId) {
  const row = _rows.find((r) => _rowId(r) === String(rowId));
  if (!row) return '<p class="text-muted">Ligne introuvable.</p>';

  const title = String(row.proposed_title || "").trim() || "?";
  const year = row.proposed_year || "";
  const folder = String(row.folder || "").trim();
  const proposedPath = String(row.proposed_path || "").trim();
  const conf = Number(row.confidence) || 0;
  const flags = _parseFlags(row.warning_flags);
  const encWarn = Array.isArray(row.encode_warnings) ? row.encode_warnings : [];
  const aa = row.audio_analysis || {};
  const saga = String(row.tmdb_collection_name || "").trim();
  const edition = String(row.edition || "").trim();

  let html = `<div class="inspector-section">
    <h4 class="inspector-section__title">${escapeHtml(title)}${year ? ` <span class="text-muted">(${escapeHtml(String(year))})</span>` : ""}</h4>`;
  if (saga) html += `<p><span class="badge badge-saga">Saga</span> ${escapeHtml(saga)}</p>`;
  if (edition) html += `<p><span class="badge badge-edition">${escapeHtml(edition)}</span></p>`;
  html += `<p><strong>Confiance :</strong> ${badgeHtml("confidence", _confLabel(conf))} <span class="text-muted">(${conf})</span></p>`;
  html += "</div>";

  html += `<div class="inspector-section">
    <h5 class="inspector-section__title">Chemins</h5>
    <p><strong>Ancien :</strong><br><span class="text-muted" style="word-break:break-all">${escapeHtml(folder || "—")}</span></p>
    <p><strong>Nouveau :</strong><br><span style="word-break:break-all">${escapeHtml(proposedPath || "—")}</span></p>
  </div>`;

  if (flags.length || encWarn.length) {
    html += `<div class="inspector-section"><h5 class="inspector-section__title">Alertes</h5><ul class="inspector-flags">`;
    for (const f of flags) html += `<li>${escapeHtml(f)}</li>`;
    for (const w of encWarn) html += `<li>${escapeHtml(w)}</li>`;
    html += "</ul></div>";
  }

  if (aa.badge_label) {
    html += `<div class="inspector-section">
      <h5 class="inspector-section__title">Audio</h5>
      <p><span class="badge badge-audio-${escapeHtml(aa.badge_tier || "basique")}">${escapeHtml(aa.badge_label)}</span></p>
    </div>`;
  }

  // Boutons decision rapide depuis le drawer
  const dec = _decisions.get(String(rowId)) || null;
  const aActive = dec === "approved" ? " active" : "";
  const rActive = dec === "rejected" ? " active" : "";
  html += `<div class="inspector-section inspector-section--actions">
    <button class="btn-review btn-approve${aActive}" data-action="approve" data-rid="${escapeHtml(String(rowId))}" data-drawer="1" title="Approuver">${_IC_CHECK} Approuver</button>
    <button class="btn-review btn-reject${rActive}" data-action="reject" data-rid="${escapeHtml(String(rowId))}" data-drawer="1" title="Rejeter">${_IC_X} Rejeter</button>
  </div>`;

  return html;
}

function _openInspectorDrawer(rowId) {
  const drawer = document.getElementById("inspectorDrawer");
  const overlay = document.getElementById("inspectorDrawerOverlay");
  const body = document.getElementById("inspectorDrawerBody");
  if (!drawer || !overlay || !body) return;
  body.innerHTML = _renderInspectorContent(rowId);
  drawer.classList.add("inspector-drawer--open");
  drawer.setAttribute("aria-hidden", "false");
  overlay.hidden = false;
  // Focus trap simple : focus sur le bouton fermer
  const btnClose = document.getElementById("btnCloseDrawer");
  if (btnClose) btnClose.focus();
}

function _closeInspectorDrawer() {
  const drawer = document.getElementById("inspectorDrawer");
  const overlay = document.getElementById("inspectorDrawerOverlay");
  if (!drawer || !overlay) return;
  drawer.classList.remove("inspector-drawer--open");
  drawer.setAttribute("aria-hidden", "true");
  overlay.hidden = true;
}

let _drawerListenersAttached = false;
function _hookInspectorDrawer() {
  if (_drawerListenersAttached) return;
  _drawerListenersAttached = true;

  document.addEventListener("click", (ev) => {
    const inspectBtn = ev.target.closest(".btn-inspect-mobile");
    if (inspectBtn) {
      ev.preventDefault();
      _openInspectorDrawer(inspectBtn.dataset.rowId);
      return;
    }
    const target = ev.target;
    if (target && (target.id === "btnCloseDrawer" || target.id === "inspectorDrawerOverlay")) {
      _closeInspectorDrawer();
      return;
    }
    // Decision via drawer : delegue a _toggleDecision puis ferme
    const decBtn = ev.target.closest('.btn-review[data-drawer="1"]');
    if (decBtn) {
      ev.stopPropagation();
      _toggleDecision(decBtn.dataset.rid, decBtn.dataset.action);
      _closeInspectorDrawer();
    }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      const drawer = document.getElementById("inspectorDrawer");
      if (drawer && drawer.classList.contains("inspector-drawer--open")) {
        _closeInspectorDrawer();
      }
    }
  });
}

/* --- Point d'entree ---------------------------------------- */

export function initReview() {
  _runId = null;
  _rows = [];
  _decisions = new Map();
  _load();
}
