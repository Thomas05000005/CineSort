/* views/traitement.js — Phase 3.3 (spec 08-traitement.md).
 *
 * Workflow Traitement avec breadcrumb 5 etapes + compteurs reels par etape
 * issus du run actif. Le workflow detaille (drawer scan options, validation
 * rapide, doublons inline, apply confirmation) reste delegue temporairement
 * a la vue Bibliotheque legacy en attendant le portage complet.
 *
 * Spec §1 breadcrumb : Analyse → Verification → Validation → Doublons → Apply
 *
 * Route : /traitement (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { navigateTo } from "../core/router.js";

const STEPS = [
  { id: "analyse", label: "Analyse", desc: "Scan des dossiers racines" },
  { id: "verification", label: "Vérification", desc: "Cas à vérifier (priorités)" },
  { id: "validation", label: "Validation", desc: "Approuver / rejeter les films" },
  { id: "doublons", label: "Doublons", desc: "Choisir le winner pour chaque groupe" },
  { id: "apply", label: "Apply", desc: "Renommer / déplacer sur disque" },
];

let _currentStep = "analyse";
let _runInfo = null; // { runId, total, validated, rejected, conflicts, duplicatesGroups, applied }
let _loading = false;

function _readStep() {
  const hash = window.location.hash || "";
  const m = hash.match(/#step-([a-z]+)/);
  if (m && STEPS.some((s) => s.id === m[1])) return m[1];
  return "analyse";
}

function _writeStep(stepId) {
  if (window.location.hash.includes(`#step-${stepId}`)) return;
  window.location.hash = `#/traitement#step-${stepId}`;
}

/* --- Data --- */

async function _loadRunInfo() {
  _loading = true;
  try {
    const res = await apiPost("get_dashboard", { run_id_or: "latest" });
    if (!res || res.ok === false) {
      _runInfo = null;
      return;
    }
    const data = res.data || res;
    const k = data.kpis || {};
    _runInfo = {
      runId: data.run_id,
      total: Number(k.total_rows || 0),
      validated: Number(k.validated_count || k.approved_count || 0),
      rejected: Number(k.rejected_count || 0),
      conflicts: Number(k.conflicts_count || 0),
      duplicatesGroups: Number(k.duplicates_groups || 0),
      applied: Number(k.applied_rows || 0),
      reviewQueue: Number(k.review_queue_count || 0),
      score: Number(k.score_avg || 0),
    };
  } catch (_err) {
    _runInfo = null;
  }
  _loading = false;
}

/* --- Render --- */

function _renderBreadcrumb(currentStep) {
  const items = STEPS.map((s, i) => {
    const isCurrent = s.id === currentStep;
    const currentIndex = STEPS.findIndex((x) => x.id === currentStep);
    const isPast = i < currentIndex;
    const cls = isCurrent ? "is-current" : (isPast ? "is-past" : "is-future");
    return `
      <button type="button" class="traitement-step ${cls}"
              data-traitement-step="${escapeHtml(s.id)}"
              aria-current="${isCurrent ? "step" : "false"}"
              ${isPast || isCurrent ? "" : "disabled"}>
        <span class="traitement-step-num">${i + 1}</span>
        <span class="traitement-step-content">
          <span class="traitement-step-label">${escapeHtml(s.label)}</span>
          <span class="traitement-step-desc">${escapeHtml(s.desc)}</span>
        </span>
      </button>
      ${i < STEPS.length - 1 ? '<span class="traitement-step-sep" aria-hidden="true">→</span>' : ""}
    `;
  }).join("");
  return `
    <nav class="traitement-breadcrumb" role="navigation" aria-label="Étapes du workflow Traitement">
      ${items}
    </nav>
  `;
}

function _renderStat(label, value, suffix) {
  return `
    <div class="traitement-stat">
      <div class="traitement-stat-value">${escapeHtml(String(value))}${suffix ? ` <span class="traitement-stat-suffix">${escapeHtml(suffix)}</span>` : ""}</div>
      <div class="traitement-stat-label">${escapeHtml(label)}</div>
    </div>
  `;
}

function _renderStepStats(stepId) {
  if (!_runInfo) return "";
  switch (stepId) {
    case "analyse":
      return `
        <div class="traitement-stats">
          ${_renderStat("Films scannés", _runInfo.total)}
          ${_renderStat("Score moyen", _runInfo.score ? _runInfo.score.toFixed(0) : "—", "/100")}
        </div>
      `;
    case "verification":
      return `
        <div class="traitement-stats">
          ${_renderStat("Cas à vérifier", _runInfo.reviewQueue)}
          ${_renderStat("Conflits", _runInfo.conflicts)}
        </div>
      `;
    case "validation":
      return `
        <div class="traitement-stats">
          ${_renderStat("Validés", _runInfo.validated)}
          ${_renderStat("Rejetés", _runInfo.rejected)}
          ${_renderStat("En attente", Math.max(0, _runInfo.total - _runInfo.validated - _runInfo.rejected))}
        </div>
      `;
    case "doublons":
      return `
        <div class="traitement-stats">
          ${_renderStat("Groupes de doublons", _runInfo.duplicatesGroups)}
        </div>
      `;
    case "apply":
      return `
        <div class="traitement-stats">
          ${_renderStat("Appliqués", _runInfo.applied)}
          ${_renderStat("Restant", Math.max(0, _runInfo.total - _runInfo.applied))}
        </div>
      `;
    default:
      return "";
  }
}

function _renderStepActions(stepId) {
  const links = [];
  if (stepId === "doublons") {
    links.push(`<a href="#/doublons" class="v5-btn v5-btn--primary">→ Ouvrir la vue Doublons (refondue)</a>`);
  }
  links.push(`<a href="#/library#step-${escapeHtml(stepId)}" class="v5-btn v5-btn--secondary">→ Ouvrir workflow legacy (étape ${escapeHtml(stepId)})</a>`);
  if (stepId === "analyse") {
    links.push(`<a href="#/processing" class="v5-btn v5-btn--secondary">→ Lancer un nouveau scan</a>`);
  }
  return `<div class="traitement-actions">${links.join("")}</div>`;
}

function _renderStepPanel(stepId) {
  const step = STEPS.find((s) => s.id === stepId) || STEPS[0];
  if (_loading) {
    return `
      <section class="traitement-panel">
        <p class="traitement-placeholder">Chargement de l'état du run…</p>
      </section>
    `;
  }
  if (!_runInfo) {
    return `
      <section class="traitement-panel" aria-labelledby="traitement-panel-title">
        <h2 id="traitement-panel-title" class="traitement-panel-title">${escapeHtml(step.label)}</h2>
        <p class="traitement-placeholder">
          Aucun run actif détecté. Lance un scan depuis la vue Processing pour démarrer le workflow.
        </p>
        <div class="traitement-actions">
          <a href="#/processing" class="v5-btn v5-btn--primary">▶ Lancer un scan</a>
        </div>
      </section>
    `;
  }
  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">${escapeHtml(step.label)}</h2>
      <p class="traitement-panel-desc">${escapeHtml(step.desc)}</p>
      ${_renderStepStats(stepId)}
      ${_renderStepActions(stepId)}
      <p class="traitement-placeholder">
        L'implémentation native du workflow 5 étapes (spec 08) — drawer scan options,
        table dense vérification, validation rapide, apply avec countdown 3s — sera
        portée dans des PRs ultérieures (~7 j d'effort spec). En attendant, utilisez
        les liens ci-dessus.
      </p>
    </section>
  `;
}

function _renderTraitement() {
  const runChip = _runInfo && _runInfo.runId
    ? `<span class="traitement-runchip" title="Run ID">run ${escapeHtml(_runInfo.runId.slice(0, 16))}…</span>`
    : "";
  return `
    <section class="traitement-view">
      <header class="traitement-header">
        <div class="traitement-header-row">
          <h1 class="traitement-title">Traitement</h1>
          ${runChip}
        </div>
        <p class="traitement-subtitle">Workflow d'un scan : analyse → validation → apply</p>
      </header>
      ${_renderBreadcrumb(_currentStep)}
      ${_renderStepPanel(_currentStep)}
    </section>
  `;
}

function _bindEvents(container) {
  container.querySelectorAll("[data-traitement-step]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const stepId = btn.dataset.traitementStep;
      _currentStep = stepId;
      _writeStep(stepId);
      _rerender(container);
    });
  });
}

function _rerender(container) {
  container.innerHTML = _renderTraitement();
  _bindEvents(container);
}

let _activeContainer = null;
function _onHashChange() {
  const next = _readStep();
  if (next !== _currentStep && _activeContainer) {
    _currentStep = next;
    _rerender(_activeContainer);
  }
}

export async function initTraitement(container) {
  if (!container) return;
  _activeContainer = container;
  _currentStep = _readStep();
  container.innerHTML = _renderTraitement();
  window.addEventListener("hashchange", _onHashChange);
  await _loadRunInfo();
  _rerender(container);
}

export function unmountTraitement() {
  window.removeEventListener("hashchange", _onHashChange);
  _currentStep = "analyse";
  _runInfo = null;
  _activeContainer = null;
  void navigateTo;
}
