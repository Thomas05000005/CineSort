/* library/library.js — Orchestrateur de la page Bibliothèque (5 sections workflow) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiGet, apiPost } from "../../core/api.js";
import { startPolling, stopPolling, stopAllPolling } from "../../core/state.js";
import { initAnalyse, destroyAnalyse } from "./lib-analyse.js";
import { initVerification } from "./lib-verification.js";
import { initValidation } from "./lib-validation.js";
import { initDuplicates } from "./lib-duplicates.js";
import { initApply } from "./lib-apply.js";
import { getNavSignal, isAbortError } from "../../core/nav-abort.js";

/* V2-C R4-MEM-4 : tracker observers et fetch en cours pour cleanup au unmount. */
let _libIntersectionObserver = null;
let _libFetchAbortController = null;
import { skeletonLinesHtml } from "../../components/skeleton.js";
import { glossaryTooltip } from "../../components/glossary-tooltip.js";

/* --- Etat partage entre les sous-modules ---------------------- */
export let libState = {
  runId: null,
  rows: [],
  decisions: new Map(),
  autoThreshold: 85,
  settings: {},
  activeSection: "analyse",
  advancedMode: false,
  quickReview: false,
};

/* --- Point d'entree ------------------------------------------- */

export async function initLibraryWorkflow() {
  const container = $("libraryContent");
  if (!container) return;

  // Construire le squelette HTML
  container.innerHTML = _buildSkeleton();

  // Charger les donnees initiales
  await _loadRunContext();

  // Initialiser les 5 sections
  initAnalyse(libState);
  initVerification(libState);
  initValidation(libState);
  initDuplicates(libState);
  initApply(libState);

  // Navigation workflow
  _hookStepNav();
  _setupIntersectionObserver();
  _hookAdvancedToggle();
}

/* --- Squelette HTML ------------------------------------------- */

function _buildSkeleton() {
  // V2-08 : skeletons remplaces par les init* sous-modules une fois _loadRunContext resolu.
  const sk = `<div aria-busy="true">${skeletonLinesHtml(3)}</div>`;
  return `
    <div class="workflow-header" id="libWorkflowHeader">
      <span>${glossaryTooltip("Run")} : <strong id="libRunLabel" data-testid="lib-run-label">—</strong></span>
      <label class="checkbox-row"><input type="checkbox" id="ckLibAdvanced" data-testid="lib-advanced-toggle"> Mode avancé</label>
    </div>
    <div class="workflow-steps" id="libWorkflowSteps">
      <button class="step active" data-section="analyse" data-testid="lib-step-analyse">1. Analyse</button>
      <button class="step" data-section="verification" data-testid="lib-step-verification">2. Vérification</button>
      <button class="step" data-section="validation" data-testid="lib-step-validation">3. Validation</button>
      <button class="step" data-section="doublons" data-testid="lib-step-doublons">4. Doublons</button>
      <button class="step" data-section="application" data-testid="lib-step-application">5. Application</button>
    </div>
    <section class="lib-section" id="step-analyse" data-lib-section="analyse">
      <h3>1. Analyse</h3>
      <div id="libAnalyseContent">${sk}</div>
    </section>
    <section class="lib-section" id="step-verification" data-lib-section="verification">
      <h3>2. Vérification</h3>
      <div id="libVerificationContent">${sk}</div>
    </section>
    <section class="lib-section" id="step-validation" data-lib-section="validation">
      <h3>3. Validation</h3>
      <div id="libValidationContent">${sk}</div>
    </section>
    <section class="lib-section" id="step-doublons" data-lib-section="doublons">
      <h3>4. Doublons</h3>
      <div id="libDuplicatesContent">${sk}</div>
    </section>
    <section class="lib-section" id="step-application" data-lib-section="application">
      <h3>5. Application</h3>
      <div id="libApplyContent">${sk}</div>
    </section>
  `;
}

/* --- Chargement du contexte run ------------------------------- */

async function _loadRunContext() {
  try {
    // Audit ID-ROB-002 : Promise.allSettled pour qu'un echec health
    // ne masque pas les settings (et inversement).
    // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur switche route.
    const navSig = getNavSignal();
    const labels = ["/api/health", "get_settings"];
    const results = await Promise.allSettled([
      apiGet("/api/health"),
      apiPost("settings/get_settings", {}, { signal: navSig }),
    ]);
    const _val = (r) => (r && r.status === "fulfilled" && r.value ? r.value.data || {} : {});
    const [healthData, settingsData] = results.map(_val);
    const failed = labels.filter((_, i) => results[i].status !== "fulfilled");
    if (failed.length > 0) console.warn("[library] endpoints en echec:", failed);

    libState.settings = settingsData;
    libState.autoThreshold = Number(libState.settings.auto_approve_threshold) || 85;

    // Detecter le run courant
    libState.runId = healthData.active_run_id || null;
    if (!libState.runId) {
      const statsRes = await apiPost("get_global_stats", { limit_runs: 1 }, { signal: navSig });
      const runs = statsRes.data?.runs_summary || [];
      if (runs.length > 0) libState.runId = runs[0].run_id;
    }

    const label = $("libRunLabel");
    if (label) label.textContent = libState.runId || "Aucun run";
  } catch (err) {
    if (isAbortError(err)) return;
    console.error("[library] erreur chargement contexte", err);
  }
}

/* --- Navigation workflow -------------------------------------- */

function _hookStepNav() {
  const steps = $("libWorkflowSteps");
  if (!steps) return;
  steps.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-section]");
    if (!btn) return;
    const section = btn.dataset.section;
    const target = document.querySelector(`[data-lib-section="${section}"]`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      _setActiveStep(section);
    }
  });
}

function _setActiveStep(name) {
  libState.activeSection = name;
  document.querySelectorAll("#libWorkflowSteps .step").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.section === name);
  });
}

function _setupIntersectionObserver() {
  const sections = document.querySelectorAll(".lib-section[data-lib-section]");
  if (!sections.length) return;
  // V2-C R4-MEM-4 : disconnect le precedent (cas re-init sans navigate full)
  if (_libIntersectionObserver) {
    try { _libIntersectionObserver.disconnect(); } catch { /* noop */ }
    _libIntersectionObserver = null;
  }
  _libIntersectionObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        _setActiveStep(entry.target.dataset.libSection);
      }
    }
  }, { threshold: 0.3 });
  sections.forEach(s => _libIntersectionObserver.observe(s));
}

/* V2-C R4-MEM-4 : cleanup public exporte pour le router.
 * Stoppe tous les pollings (analyse), disconnect l'observer, abort les fetchs
 * en cours. Pas de container.innerHTML="" ici car le router toggle la
 * visibilite via .active (cf router.js resolve()). */
export function unmountLibrary() {
  try { destroyAnalyse(); } catch { /* noop */ }
  if (_libIntersectionObserver) {
    try { _libIntersectionObserver.disconnect(); } catch { /* noop */ }
    _libIntersectionObserver = null;
  }
  if (_libFetchAbortController) {
    try { _libFetchAbortController.abort(); } catch { /* noop */ }
    _libFetchAbortController = null;
  }
  // stopAllPolling() est deja appele par le router lui-meme.
}

function _hookAdvancedToggle() {
  const ck = $("ckLibAdvanced");
  if (!ck) return;
  ck.addEventListener("change", () => {
    libState.advancedMode = ck.checked;
    document.querySelectorAll(".lib-advanced").forEach(el => {
      el.classList.toggle("hidden", !ck.checked);
    });
  });
}
