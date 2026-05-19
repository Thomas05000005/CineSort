/* views/traitement.js — Phase 3.3 (spec 08-traitement.md) — Workflow 5 étapes.
 *
 * Squelette : breadcrumb 5 étapes + navigation libre + placeholder pour le
 * contenu de chaque étape. Le workflow détaillé (scan, vérification, validation,
 * doublons, apply) réutilise la logique de l'ancienne vue Bibliothèque pour
 * cette PR initiale. Le portage complet est reporté à des PRs ultérieures.
 *
 * Spec §1 breadcrumb : Analyse → Vérification → Validation → Doublons → Apply
 * + Navigation libre entre étapes passées (clic = re-affiche le statut).
 *
 * Route cible : /traitement (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { navigateTo } from "../core/router.js";

const STEPS = [
  { id: "analyse", label: "Analyse", desc: "Scan des dossiers racines" },
  { id: "verification", label: "Vérification", desc: "Cas à vérifier (priorités)" },
  { id: "validation", label: "Validation", desc: "Approuver / rejeter les films" },
  { id: "doublons", label: "Doublons", desc: "Choisir le winner pour chaque groupe" },
  { id: "apply", label: "Apply", desc: "Renommer / déplacer sur disque" },
];

let _currentStep = "analyse";

function _readStep() {
  // Lis l'étape depuis le hash fragment : /traitement#step-validation
  const hash = window.location.hash || "";
  const m = hash.match(/#step-([a-z]+)/);
  if (m && STEPS.some((s) => s.id === m[1])) return m[1];
  return "analyse";
}

function _writeStep(stepId) {
  if (window.location.hash.includes(`#step-${stepId}`)) return;
  window.location.hash = `#/traitement#step-${stepId}`;
}

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

function _renderStepPanel(stepId) {
  const step = STEPS.find((s) => s.id === stepId) || STEPS[0];
  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">${escapeHtml(step.label)}</h2>
      <p class="traitement-panel-desc">${escapeHtml(step.desc)}</p>
      <div class="traitement-panel-body">
        <p class="traitement-placeholder">
          Cette étape du workflow Traitement réutilise temporairement la vue
          Bibliothèque legacy. Pour exécuter cette étape, ouvre
          <a href="#/library#step-${escapeHtml(stepId)}" class="link-primary">la vue Bibliothèque legacy → ${escapeHtml(step.label)}</a>.
        </p>
        <p class="traitement-placeholder">
          L'implémentation native du workflow 5 étapes (spec 08) — drawer scan
          options, table dense vérification, validation rapide, doublons inline,
          apply avec confirmation et countdown 3s — sera portée dans les PRs
          suivantes (~7 j d'effort spec).
        </p>
      </div>
    </section>
  `;
}

function _renderTraitement() {
  return `
    <section class="traitement-view">
      <header class="traitement-header">
        <h1 class="traitement-title">Traitement</h1>
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

function _onHashChange() {
  // Au cas où la nav externe change le hash.
  const next = _readStep();
  if (next !== _currentStep) {
    _currentStep = next;
    const container = document.querySelector(".traitement-view");
    if (container && container.parentElement) _rerender(container.parentElement);
  }
}

export function initTraitement(container) {
  if (!container) return;
  _currentStep = _readStep();
  container.innerHTML = _renderTraitement();
  _bindEvents(container);
  window.addEventListener("hashchange", _onHashChange);
}

export function unmountTraitement() {
  window.removeEventListener("hashchange", _onHashChange);
  _currentStep = "analyse";
  // Navigue vers /traitement plus tard.
  void navigateTo;
}
