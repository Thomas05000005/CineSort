/* views/processing.js — v7.6.0 Vague 5 + V5bis-04 port ES module
 *
 * Vue Traitement : fusion F1 scan -> review -> apply en 3 steps continus.
 *
 * Stepper horizontal en haut (3 segments cliquables avec indicateurs d'etat).
 * Chaque step rend un contenu minimaliste + CTAs vers les actions reelles.
 * Les features avancees (bulk actions complexes, undo v5, presets batch) restent
 * accessibles via les vues legacy validation / execution (routes alternatives).
 *
 * V5bis-04 : port IIFE -> ES module + migration des 11 sites pywebview natif
 * vers apiPost (REST + fallback pywebview via _v5_helpers).
 *
 * Features V5A preservees :
 *   - V5 workflow F1 (3 steps continus scan/review/apply)
 *   - V2-03 Draft auto localStorage (debounce 500ms + restore banner)
 *   - V3-06 Drawer mobile inspecteur (< 768px)
 *   - V2-07 EmptyState (donnees indisponibles + aucun film)
 *   - V2-08 Skeleton states pendant chargement
 *   - V2-04 Promise.allSettled pour les pre-requis du scan
 *
 * API publique :
 *   import { initProcessing, goToStep } from "./processing.js";
 *   initProcessing(container, opts?)  // opts.step = "scan" | "review" | "apply"
 */
import { apiPost, escapeHtml } from "./_v5_helpers.js";
import { buildEmptyState, bindEmptyStateCta } from "../dashboard/components/empty-state.js";

const STEPS = [
  { id: "scan", num: 1, label: "Scan", sub: "Explorer les dossiers" },
  { id: "review", num: 2, label: "Review", sub: "Valider les décisions" },
  { id: "apply", num: 3, label: "Apply", sub: "Appliquer les changements" },
];

const _state = {
  containerRef: null,
  activeStep: "scan",
  currentRunId: null,
  status: null,
  pollTimer: null,
  decisions: {},
  rowCounts: { approved: 0, rejected: 0, pending: 0 },
};

function _esc(s) {
  return escapeHtml(String(s ?? ""));
}

function _svg(path, size) {
  const s = size || 14;
  return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

const ICON_CHECK = '<polyline points="20 6 9 17 4 12"/>';
const ICON_PLAY = '<polygon points="5 3 19 12 5 21 5 3"/>';
const ICON_STOP = '<rect x="6" y="6" width="12" height="12"/>';
const ICON_CHECK_CIRCLE = '<polyline points="9 12 11 14 15 10"/><circle cx="12" cy="12" r="10"/>';

/* ===========================================================
 * V2-03 — Draft auto validation (localStorage debounce 500ms + restore)
 * ===========================================================
 * Persiste les decisions in-memory dans localStorage pour survivre
 * a un crash ou un refresh. Cle : cinesort.processing.draft.<run_id>.
 * TTL 30 jours. Nettoye apres save_validation reussi cote serveur.
 */
const DRAFT_KEY_PREFIX = "cinesort.processing.draft.";
const DRAFT_TTL_MS = 30 * 24 * 3600 * 1000; // 30 jours
let _draftSaveTimer = null;

function _draftKey(runId) {
  return DRAFT_KEY_PREFIX + String(runId || "");
}

function _scheduleDraftSave(runId, decisions) {
  if (!runId) return;
  if (_draftSaveTimer) clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(() => {
    try {
      const payload = { ts: Date.now(), runId: String(runId), decisions: decisions || {} };
      localStorage.setItem(_draftKey(runId), JSON.stringify(payload));
    } catch (e) {
      /* quota depasse : silencieux */
    }
  }, 500);
}

function _loadDraft(runId) {
  if (!runId) return null;
  try {
    const raw = localStorage.getItem(_draftKey(runId));
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== "object") return null;
    if (Date.now() - (data.ts || 0) > DRAFT_TTL_MS) {
      localStorage.removeItem(_draftKey(runId));
      return null;
    }
    return data.decisions && typeof data.decisions === "object" ? data.decisions : null;
  } catch (e) {
    return null;
  }
}

function _clearDraft(runId) {
  if (!runId) return;
  try {
    localStorage.removeItem(_draftKey(runId));
  } catch (e) {
    /* ignore */
  }
}

function _checkAndOfferRestore(runId, currentDecisions) {
  const draft = _loadDraft(runId);
  if (!draft) return;
  let differs = false;
  const cur = currentDecisions || {};
  const keys = new Set([...Object.keys(draft), ...Object.keys(cur)]);
  for (const k of keys) {
    const a = draft[k] && draft[k].decision;
    const b = cur[k] && cur[k].decision;
    if ((a || null) !== (b || null)) {
      differs = true;
      break;
    }
  }
  if (!differs) return;
  _showRestoreBanner(runId, draft);
}

function _showRestoreBanner(runId, draft) {
  if (document.getElementById("v5DraftRestoreBanner")) return;
  const count = Object.keys(draft || {}).length;
  const banner = document.createElement("div");
  banner.id = "v5DraftRestoreBanner";
  banner.className = "v5-alert v5-alert--info v5-draft-restore-banner";
  banner.setAttribute("role", "status");
  banner.style.cssText = "display:flex;gap:.6em;align-items:center;flex-wrap:wrap;padding:.6em 1em;margin:0 0 1em 0;border-left:3px solid var(--accent,#3b82f6);background:var(--surface-2,#1a1f2e);";
  banner.innerHTML = `
    <span>Brouillon non sauvegarde trouve pour ce run (${count} decision${count > 1 ? "s" : ""}).</span>
    <button type="button" class="v5-btn v5-btn--sm" id="v5BtnRestoreDraft">Restaurer</button>
    <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" id="v5BtnDiscardDraft">Ignorer</button>
  `;
  const host = _state.containerRef || document.body;
  host.insertBefore(banner, host.firstChild);

  document.getElementById("v5BtnRestoreDraft")?.addEventListener("click", () => {
    _applyDraftDecisions(draft);
    banner.remove();
  });
  document.getElementById("v5BtnDiscardDraft")?.addEventListener("click", () => {
    _clearDraft(runId);
    banner.remove();
  });
}

function _applyDraftDecisions(draft) {
  if (!draft || typeof draft !== "object") return;
  for (const [rowId, value] of Object.entries(draft)) {
    const dec = value && value.decision;
    if (dec === "approve" || dec === "reject") {
      _state.decisions[rowId] = { decision: dec };
    }
  }
  _renderActiveStep();
}

/* ===========================================================
 * V3-06 — Drawer mobile inspector (< 768px)
 * ===========================================================
 * Sur les ecrans etroits, l'inspecteur film s'affiche dans un drawer
 * slide-in plutot qu'un panel a cote du tableau (qui n'a pas la place).
 * En desktop (>= 768px), l'utilisateur a deja la table en pleine vue
 * donc le drawer est skip.
 */

function _isMobileViewport() {
  return !window.matchMedia("(min-width: 768px)").matches;
}

function _renderInspectorMobileDrawer() {
  if (document.getElementById("v5ProcessingInspectorDrawer")) return;
  const overlay = document.createElement("div");
  overlay.id = "v5ProcessingInspectorOverlay";
  overlay.className = "v5-drawer-overlay";
  overlay.hidden = true;
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:80";

  const drawer = document.createElement("aside");
  drawer.id = "v5ProcessingInspectorDrawer";
  drawer.className = "v5-drawer v5-drawer--right v5-processing-inspector-drawer";
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  drawer.setAttribute("aria-hidden", "true");
  drawer.style.cssText = "position:fixed;top:0;right:0;height:100vh;width:min(420px,90vw);background:var(--surface-1,#0f141d);border-left:1px solid var(--border-1,#222);transform:translateX(100%);transition:transform 220ms ease;z-index:90;display:flex;flex-direction:column;";
  drawer.innerHTML = `
    <div class="v5-drawer-header" style="display:flex;align-items:center;justify-content:space-between;padding:1em;border-bottom:1px solid var(--border-1,#222)">
      <h3 style="margin:0;font-size:1rem">Inspecteur film</h3>
      <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost" id="v5BtnCloseInspector" aria-label="Fermer">&times;</button>
    </div>
    <div class="v5-drawer-body" id="v5InspectorBody" style="flex:1;overflow:auto;padding:1em"></div>
  `;
  document.body.appendChild(overlay);
  document.body.appendChild(drawer);

  document.getElementById("v5BtnCloseInspector")?.addEventListener("click", _closeInspectorDrawer);
  overlay.addEventListener("click", _closeInspectorDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") _closeInspectorDrawer();
  });
}

function _buildInspectorContent(rowId) {
  const decision = _state.decisions[rowId];
  const label = decision?.decision === "approve" ? "Approuve"
    : decision?.decision === "reject" ? "Rejete" : "En attente";
  return `
    <div class="v5-inspector-content">
      <p class="v5u-text-muted" style="margin-top:0">Film <code>${_esc(rowId)}</code></p>
      <p>Decision actuelle : <strong>${_esc(label)}</strong></p>
      <div style="display:flex;gap:.5em;flex-wrap:wrap">
        <button type="button" class="v5-btn v5-btn--sm v5-btn--primary" data-inspector-action="approve" data-row-id="${_esc(rowId)}">Approuver</button>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--danger" data-inspector-action="reject" data-row-id="${_esc(rowId)}">Rejeter</button>
      </div>
    </div>
  `;
}

function _openInspectorDrawer(rowId) {
  if (!_isMobileViewport()) {
    // Desktop : pas de drawer, l'utilisateur a deja la table en pleine vue
    return;
  }
  _renderInspectorMobileDrawer();
  const drawer = document.getElementById("v5ProcessingInspectorDrawer");
  const overlay = document.getElementById("v5ProcessingInspectorOverlay");
  const body = document.getElementById("v5InspectorBody");
  if (!drawer || !body) return;
  body.innerHTML = _buildInspectorContent(rowId);
  drawer.style.transform = "translateX(0)";
  drawer.setAttribute("aria-hidden", "false");
  if (overlay) overlay.hidden = false;
  document.getElementById("v5BtnCloseInspector")?.focus();

  body.querySelectorAll("[data-inspector-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rid = btn.dataset.rowId;
      const action = btn.dataset.inspectorAction;
      if (!rid || !action) return;
      _state.decisions[rid] = { decision: action };
      _scheduleDraftSave(_state.currentRunId, _state.decisions);
      await _saveDecisions();
      _closeInspectorDrawer();
      _renderActiveStep();
    });
  });
}

function _closeInspectorDrawer() {
  const drawer = document.getElementById("v5ProcessingInspectorDrawer");
  const overlay = document.getElementById("v5ProcessingInspectorOverlay");
  if (!drawer) return;
  drawer.style.transform = "translateX(100%)";
  drawer.setAttribute("aria-hidden", "true");
  if (overlay) overlay.hidden = true;
}

/* ===========================================================
 * V2-08 — Skeleton states pour chaque step
 * =========================================================== */

function _renderSkeletonForStep(stepEl, stepId) {
  if (!stepEl) return;
  if (stepId === "scan") {
    stepEl.innerHTML = `
      <div class="v5-processing-step-content">
        <div class="v5-skeleton v5-skeleton--scan" style="height:24px;width:40%;margin-bottom:1em"></div>
        <div class="v5-skeleton" style="height:14px;width:70%;margin-bottom:.6em"></div>
        <div class="v5-skeleton" style="height:14px;width:55%;margin-bottom:1.2em"></div>
        <div class="v5-skeleton" style="height:40px;width:160px"></div>
      </div>`;
  } else if (stepId === "review") {
    const rows = "<div class='v5-skeleton v5-skeleton-row' style='height:32px;margin-bottom:.4em'></div>".repeat(10);
    stepEl.innerHTML = `
      <div class="v5-processing-step-content">
        <div class="v5-skeleton" style="height:24px;width:35%;margin-bottom:1em"></div>
        <div class="v5-skeleton-table">${rows}</div>
      </div>`;
  } else if (stepId === "apply") {
    stepEl.innerHTML = `
      <div class="v5-processing-step-content">
        <div class="v5-skeleton v5-skeleton--apply" style="height:24px;width:40%;margin-bottom:1em"></div>
        <div class="v5-skeleton" style="height:80px;margin-bottom:.8em"></div>
        <div class="v5-skeleton" style="height:48px;width:30%"></div>
      </div>`;
  }
}

/* ===========================================================
 * Stepper header
 * =========================================================== */

function _stepStatus(stepId) {
  /* Renvoie "done" | "current" | "pending" | "blocked" */
  const active = _state.activeStep;
  if (stepId === active) return "current";

  if (stepId === "scan") {
    return _state.currentRunId ? "done" : "pending";
  }
  if (stepId === "review") {
    if (!_state.currentRunId) return "blocked";
    const pending = _state.rowCounts.pending || 0;
    const total = pending + (_state.rowCounts.approved || 0) + (_state.rowCounts.rejected || 0);
    if (total > 0 && pending === 0) return "done";
    return "pending";
  }
  if (stepId === "apply") {
    if (!_state.currentRunId) return "blocked";
    return "pending";
  }
  return "pending";
}

function _buildStepper() {
  const activeIdx = STEPS.findIndex((s) => s.id === _state.activeStep);
  return `
    <nav class="v5-processing-stepper" role="tablist" aria-label="Etapes de traitement">
      ${STEPS.map((step, i) => {
        const status = _stepStatus(step.id);
        const connector = i < STEPS.length - 1
          ? `<div class="v5-stepper-connector v5-stepper-connector--${_esc(i < activeIdx ? "done" : "pending")}"></div>`
          : "";
        const iconHtml = status === "done" ? _svg(ICON_CHECK, 14) : String(step.num);
        const disabled = status === "blocked" ? "disabled" : "";
        return `
          <button type="button"
                  class="v5-stepper-step is-${_esc(status)}"
                  data-step-id="${_esc(step.id)}"
                  role="tab" aria-selected="${status === "current" ? "true" : "false"}"
                  ${disabled}>
            <span class="v5-stepper-circle">${iconHtml}</span>
            <span class="v5-stepper-content">
              <span class="v5-stepper-label">${_esc(step.label)}</span>
              <span class="v5-stepper-sub v5u-text-muted">${_esc(step.sub)}</span>
            </span>
          </button>
          ${connector}
        `;
      }).join("")}
    </nav>
  `;
}

/* ===========================================================
 * STEP 1 : SCAN
 * =========================================================== */

function _initScanStep(panel) {
  const isRunning = _state.status && _state.status.status === "running";
  const progress = _state.status?.progress || 0;
  const logsCount = _state.status?.logs?.length || 0;

  panel.innerHTML = `
    <div class="v5-processing-step-content">
      <header class="v5-processing-step-header">
        <h2 class="v5-processing-step-title">Lancer un scan</h2>
        <p class="v5-processing-step-desc v5u-text-muted">
          Analyse les dossiers racines configures et produit un plan de renommage.
        </p>
      </header>

      ${isRunning ? `
        <div class="v5-processing-running">
          <div class="v5-processing-progress">
            <div class="v5-processing-progress-bar" style="width: ${progress}%"></div>
          </div>
          <div class="v5-processing-progress-label">
            <span>Analyse en cours : ${Math.round(progress)}%</span>
            <span class="v5u-text-muted">${logsCount} entrees de log</span>
          </div>
          <button type="button" class="v5-btn v5-btn--danger v5-btn--sm" data-action="cancel-run">
            ${_svg(ICON_STOP, 12)} Annuler
          </button>
        </div>
      ` : `
        <div class="v5-processing-card">
          <div class="v5-processing-actions">
            <button type="button" class="v5-btn v5-btn--primary" data-action="start-scan">
              ${_svg(ICON_PLAY, 14)} Lancer le scan
            </button>
            ${_state.currentRunId
              ? `<button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-action="goto-review">
                   Continuer vers Review
                 </button>`
              : ""}
          </div>
          ${_state.currentRunId
            ? `<div class="v5-processing-run-info v5u-text-muted">
                 Dernier run : <code>${_esc(_state.currentRunId)}</code>
               </div>`
            : `<div class="v5u-text-muted">Aucun run en cours. Assurez-vous d'avoir configuré vos dossiers dans les Paramètres.</div>`
          }
        </div>
      `}
    </div>
  `;

  _bindStepActions(panel);
}

async function _startScan() {
  // V2-04 : on parallelise les pre-requis (settings + status courant) avec
  // Promise.allSettled pour resilience — un endpoint en echec ne bloque
  // pas le scan si on peut s'en passer (settings est obligatoire, status optionnel).
  const results = await Promise.allSettled([
    apiPost("settings/get_settings", {}),
    apiPost("run/get_status", { run_id: _state.currentRunId || "", last_log_index: 0 }),
  ]);
  const settingsRes = results[0];
  if (settingsRes.status !== "fulfilled" || !settingsRes.value?.ok) {
    console.error("[processing] start_scan: get_settings failed", settingsRes.reason || settingsRes.value?.error);
    return;
  }
  try {
    const res = await apiPost("run/start_plan", { settings: settingsRes.value.data });
    if (res.ok && res.data?.run_id) {
      _state.currentRunId = res.data.run_id;
      _pollStatus();
    }
  } catch (e) {
    console.error("[processing] start_scan:", e);
  }
}

async function _cancelRun() {
  if (!_state.currentRunId) return;
  try {
    await apiPost("run/cancel_run", { run_id: _state.currentRunId });
  } catch (e) {
    console.error("[processing] cancel:", e);
  }
}

function _pollStatus() {
  if (_state.pollTimer) clearTimeout(_state.pollTimer);
  if (!_state.currentRunId) return;

  const tick = async () => {
    try {
      const res = await apiPost("run/get_status", { run_id: _state.currentRunId, last_log_index: 0 });
      _state.status = res.data;
      if (_state.activeStep === "scan") _renderActiveStep();
      if (_state.status && _state.status.status !== "running") {
        _state.pollTimer = null;
        return;
      }
    } catch (e) {
      console.error("[processing] poll:", e);
    }
    _state.pollTimer = setTimeout(tick, 2000);
  };
  tick();
}

/* ===========================================================
 * STEP 2 : REVIEW
 * =========================================================== */

async function _initReviewStep(panel) {
  if (!_state.currentRunId) {
    panel.innerHTML = _blockedMessage("Lancez d'abord un scan (Step 1).");
    _bindStepActions(panel);
    return;
  }

  // V2-08 : skeleton pendant le chargement de la validation.
  _renderSkeletonForStep(panel, "review");

  panel.innerHTML = `
    <div class="v5-processing-step-content">
      <header class="v5-processing-step-header">
        <h2 class="v5-processing-step-title">Valider les decisions</h2>
        <p class="v5-processing-step-desc v5u-text-muted">
          Inspectez les films detectes et approuvez ou rejetez chacun. Les decisions seront persistees.
        </p>
      </header>
      <div id="processing-review-body" class="v5-processing-review">
        <div class="v5-library-loading">Chargement des films...</div>
      </div>
      <footer class="v5-processing-step-footer">
        <button type="button" class="v5-btn v5-btn--ghost" data-action="goto-scan">&larr; Retour au scan</button>
        <div class="v5-processing-counters" data-v5-review-counters>—</div>
        <button type="button" class="v5-btn v5-btn--primary" data-action="goto-apply">Aller a Apply &rarr;</button>
      </footer>
    </div>
  `;
  _bindStepActions(panel);

  // Charger validation
  try {
    const res = await apiPost("load_validation", { run_id: _state.currentRunId });
    const body = panel.querySelector("#processing-review-body");
    if (!res.ok) {
      const msg = res.data?.message || res.error || "Aucune donnée de review.";
      if (body) {
        // V2-07 : EmptyState pour les erreurs / donnees manquantes.
        body.innerHTML = buildEmptyState({
          icon: "alert",
          title: "Donnees indisponibles",
          message: _esc(msg),
        });
      }
      return;
    }
    const payload = res.data || {};
    _state.decisions = payload.decisions || {};
    const rows = payload.rows || [];
    _renderReviewTable(body, rows);
    _updateReviewCounters(panel, rows);
    // V2-03 : si un draft localStorage existe et differe de l'etat serveur,
    // proposer la restauration via une banniere.
    _checkAndOfferRestore(_state.currentRunId, _state.decisions);
  } catch (e) {
    console.error("[processing] review:", e);
  }
}

function _updateReviewCounters(panel, rows) {
  const counter = panel.querySelector("[data-v5-review-counters]");
  if (!counter) return;
  let approved = 0, rejected = 0;
  const total = rows.length;
  for (const r of rows) {
    const d = _state.decisions[r.row_id];
    if (d?.decision === "approve") approved += 1;
    else if (d?.decision === "reject") rejected += 1;
  }
  const pending = total - approved - rejected;
  _state.rowCounts = { approved, rejected, pending };
  counter.innerHTML = `
    <span><strong class="v5u-tabular-nums">${approved}</strong> approuves</span>
    <span class="v5u-text-muted">·</span>
    <span><strong class="v5u-tabular-nums">${rejected}</strong> rejetes</span>
    <span class="v5u-text-muted">·</span>
    <span><strong class="v5u-tabular-nums">${pending}</strong> en attente</span>
  `;
}

function _renderReviewTable(body, rows) {
  if (!body) return;
  if (!rows || rows.length === 0) {
    // V2-07 : EmptyState avec CTA pour relancer un scan.
    body.innerHTML = buildEmptyState({
      icon: "search",
      title: "Aucun film a valider",
      message: "Lance un scan pour commencer.",
      ctaLabel: "Lancer un scan",
      ctaRoute: "processing?step=scan",
    });
    bindEmptyStateCta(body, () => goToStep("scan"));
    return;
  }
  body.innerHTML = `
    <div class="v5-processing-bulk-bar">
      <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-bulk="approve-all">Approuver tous</button>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-bulk="reject-all">Rejeter tous</button>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-bulk="clear">Reinitialiser</button>
      <span class="v5u-text-muted" style="margin-left:auto">${rows.length} film${rows.length > 1 ? "s" : ""}</span>
    </div>
    <div class="v5-processing-table-wrap v5-scroll">
      <table class="v5-table v5-processing-table">
        <thead><tr>
          <th>Titre</th><th>Annee</th><th>Confiance</th><th style="width:140px">Decision</th>
        </tr></thead>
        <tbody>
          ${rows.slice(0, 200).map((r) => _renderReviewRow(r)).join("")}
        </tbody>
      </table>
      ${rows.length > 200 ? `<div class="v5u-text-muted v5u-p-3 v5u-text-center">Affichage 200 premieres lignes sur ${rows.length}. Utilisez la vue Validation classique pour le reste.</div>` : ""}
    </div>
  `;

  // Bulk
  body.querySelectorAll("[data-bulk]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.bulk;
      rows.forEach((r) => {
        if (action === "approve-all") _state.decisions[r.row_id] = { decision: "approve" };
        else if (action === "reject-all") _state.decisions[r.row_id] = { decision: "reject" };
        else if (action === "clear") delete _state.decisions[r.row_id];
      });
      _renderReviewTable(body, rows);
      _updateReviewCounters(_state.containerRef, rows);
      // V2-03 : draft save debounce avant l'appel reseau
      _scheduleDraftSave(_state.currentRunId, _state.decisions);
      await _saveDecisions();
    });
  });

  // Row decisions
  body.querySelectorAll("[data-row-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rowId = btn.dataset.rowId;
      const decision = btn.dataset.rowAction;
      _state.decisions[rowId] = { decision };
      _renderReviewTable(body, rows);
      _updateReviewCounters(_state.containerRef, rows);
      // V2-03 : draft save debounce
      _scheduleDraftSave(_state.currentRunId, _state.decisions);
      await _saveDecisions();
    });
  });

  // V3-06 : bouton "Inspecter" — ouvre le drawer mobile (skip si desktop)
  body.querySelectorAll("[data-row-inspect]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rowId = btn.dataset.rowId;
      if (rowId) _openInspectorDrawer(rowId);
    });
  });
}

function _renderReviewRow(r) {
  const d = _state.decisions[r.row_id];
  const decisionLabel = d?.decision || "pending";
  const rowClass = decisionLabel === "approve" ? "row-approved"
    : decisionLabel === "reject" ? "row-rejected" : "";
  const conf = Number(r.confidence || 0);
  const confClass = conf >= 80 ? "tier-gold" : conf >= 60 ? "tier-silver" : "tier-bronze";

  return `
    <tr class="${rowClass}" data-row-id="${_esc(r.row_id)}">
      <td class="v5u-truncate" style="max-width:400px">${_esc(r.proposed_title || "—")}</td>
      <td class="v5u-tabular-nums">${_esc(r.proposed_year || "—")}</td>
      <td><span class="v5u-tabular-nums ${confClass}">${conf.toFixed(0)}%</span></td>
      <td>
        <div class="v5-processing-decision-btns">
          <button type="button" class="v5-btn v5-btn--sm ${decisionLabel === "approve" ? "v5-btn--primary" : "v5-btn--ghost"}"
                  data-row-action="approve" data-row-id="${_esc(r.row_id)}" aria-label="Approuver">
            ${_svg(ICON_CHECK, 12)}
          </button>
          <button type="button" class="v5-btn v5-btn--sm ${decisionLabel === "reject" ? "v5-btn--danger" : "v5-btn--ghost"}"
                  data-row-action="reject" data-row-id="${_esc(r.row_id)}" aria-label="Rejeter">
            &times;
          </button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost v5-btn-inspect-mobile"
                  data-row-inspect="1" data-row-id="${_esc(r.row_id)}"
                  aria-label="Inspecter (mobile)" title="Inspecter">
            i
          </button>
        </div>
      </td>
    </tr>
  `;
}

async function _saveDecisions() {
  try {
    const res = await apiPost("save_validation", { run_id: _state.currentRunId, decisions: _state.decisions });
    // V2-03 : si save serveur OK, le draft local est obsolete -> on le supprime.
    if (res.ok) _clearDraft(_state.currentRunId);
  } catch (e) {
    console.error("[processing] save_validation:", e);
  }
}

/* ===========================================================
 * STEP 3 : APPLY
 * =========================================================== */

async function _initApplyStep(panel) {
  if (!_state.currentRunId) {
    panel.innerHTML = _blockedMessage("Lancez d'abord un scan (Step 1).");
    _bindStepActions(panel);
    return;
  }

  const c = _state.rowCounts;
  panel.innerHTML = `
    <div class="v5-processing-step-content">
      <header class="v5-processing-step-header">
        <h2 class="v5-processing-step-title">Appliquer les changements</h2>
        <p class="v5-processing-step-desc v5u-text-muted">
          Apply execute les renommages et deplacements. Un dry-run est toujours effectue en premier pour preview.
        </p>
      </header>

      <div class="v5-processing-apply-summary">
        <div class="v5-processing-apply-card">
          <div class="v5-processing-apply-label">Films approuves</div>
          <div class="v5-processing-apply-value v5u-tabular-nums">${c.approved}</div>
        </div>
        <div class="v5-processing-apply-card">
          <div class="v5-processing-apply-label">Films rejetes</div>
          <div class="v5-processing-apply-value v5u-tabular-nums">${c.rejected}</div>
        </div>
        <div class="v5-processing-apply-card v5-processing-apply-card--warn">
          <div class="v5-processing-apply-label">En attente</div>
          <div class="v5-processing-apply-value v5u-tabular-nums">${c.pending}</div>
        </div>
      </div>

      <div class="v5-processing-card">
        <label class="v5-processing-option">
          <input type="checkbox" class="v5-checkbox" checked data-v5-dry-run>
          <span>Dry-run (simulation, aucune modification filesystem)</span>
        </label>
        <label class="v5-processing-option">
          <input type="checkbox" class="v5-checkbox" data-v5-quarantine>
          <span>Envoyer les rejetes dans _review/quarantine</span>
        </label>
      </div>

      <div class="v5-processing-apply-actions">
        <button type="button" class="v5-btn v5-btn--ghost" data-action="goto-review">&larr; Retour Review</button>
        <button type="button" class="v5-btn v5-btn--primary" data-action="run-apply">
          ${_svg(ICON_CHECK_CIRCLE, 14)} Lancer Apply
        </button>
      </div>

      <div class="v5-processing-apply-result" data-v5-apply-result></div>
    </div>
  `;
  _bindStepActions(panel);
}

async function _runApply() {
  const root = _state.containerRef;
  if (!root) return;
  const dry = !!root.querySelector("[data-v5-dry-run]")?.checked;
  const quarantine = !!root.querySelector("[data-v5-quarantine]")?.checked;
  const resultBox = root.querySelector("[data-v5-apply-result]");
  if (resultBox) resultBox.innerHTML = `<div class="v5u-text-muted">Apply en cours...</div>`;
  try {
    const res = await apiPost("apply", { run_id: _state.currentRunId, dry_run: dry, quarantine });
    if (res.ok) {
      const msg = dry ? "Dry-run termine." : "Apply termine.";
      const done = res.data?.done || 0;
      if (resultBox) resultBox.innerHTML = `
        <div class="v5-processing-apply-success">
          <strong>${_esc(msg)}</strong>
          <span class="v5u-text-muted">${done} operation${done > 1 ? "s" : ""}.</span>
        </div>
      `;
    } else {
      if (resultBox) resultBox.innerHTML = `<div class="v5-processing-apply-error">${_esc(res.data?.message || res.error || "Erreur")}</div>`;
    }
  } catch (e) {
    if (resultBox) resultBox.innerHTML = `<div class="v5-processing-apply-error">${_esc(String(e))}</div>`;
  }
}

/* ===========================================================
 * Helpers
 * =========================================================== */

function _blockedMessage(msg) {
  return `
    <div class="v5-processing-step-content">
      <div class="v5-processing-blocked">
        <p>${_esc(msg)}</p>
        <button type="button" class="v5-btn v5-btn--primary v5-btn--sm" data-action="goto-scan">Revenir au Scan</button>
      </div>
    </div>
  `;
}

function _bindStepActions(panel) {
  panel.querySelectorAll("[data-action]").forEach((btn) => {
    const action = btn.dataset.action;
    btn.addEventListener("click", async () => {
      switch (action) {
        case "start-scan": await _startScan(); break;
        case "cancel-run": await _cancelRun(); break;
        case "goto-scan": goToStep("scan"); break;
        case "goto-review": goToStep("review"); break;
        case "goto-apply": goToStep("apply"); break;
        case "run-apply": await _runApply(); break;
      }
    });
  });
}

function _renderActiveStep() {
  const root = _state.containerRef;
  if (!root) return;
  const stepperHost = root.querySelector(".v5-processing-stepper-wrap");
  const panelHost = root.querySelector("[data-v5-processing-panel]");
  if (stepperHost) stepperHost.innerHTML = _buildStepper();
  // Bind stepper clicks
  root.querySelectorAll("[data-step-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      goToStep(btn.dataset.stepId);
    });
  });

  if (!panelHost) return;
  switch (_state.activeStep) {
    case "scan": _initScanStep(panelHost); break;
    case "review": _initReviewStep(panelHost); break;
    case "apply": _initApplyStep(panelHost); break;
  }
}

export function goToStep(stepId) {
  if (!STEPS.find((s) => s.id === stepId)) return;
  _state.activeStep = stepId;
  _renderActiveStep();
}

async function _fetchLastRunId() {
  try {
    const res = await apiPost("get_dashboard", { run_id: "latest" });
    if (res.ok && res.data?.run_id) _state.currentRunId = res.data.run_id;
  } catch (e) {
    /* no run yet */
  }
}

export async function initProcessing(container, opts) {
  if (!container) return;
  const o = opts || {};
  _state.containerRef = container;
  _state.activeStep = STEPS.find((s) => s.id === o.step) ? o.step : "scan";

  // V2-08 : skeleton initial pendant la resolution du run id.
  container.innerHTML = `
    <div class="v5-processing-shell">
      <div class="v5-processing-stepper-wrap"></div>
      <div class="v5-processing-panel" data-v5-processing-panel></div>
    </div>
  `;
  const initialPanel = container.querySelector("[data-v5-processing-panel]");
  _renderSkeletonForStep(initialPanel, _state.activeStep);

  await _fetchLastRunId();
  _renderActiveStep();
}

export function unmountProcessing() {
  if (_state.pollTimer) clearTimeout(_state.pollTimer);
  _state.pollTimer = null;
  if (_state.containerRef) _state.containerRef.innerHTML = "";
  _state.containerRef = null;
}

export { STEPS };
