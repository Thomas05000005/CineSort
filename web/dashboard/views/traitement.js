/* views/traitement.js — Phase 5 (spec 08-traitement.md, refonte complete).
 *
 * Workflow Traitement natif : header run actif + breadcrumb 5 etapes +
 * etapes Analyse/Verification/Validation/Doublons/Apply portees nativement
 * (sans renvoi vers la vue Bibliotheque legacy).
 *
 * Spec §1 breadcrumb : Analyse → Verification → Validation → Doublons → Apply
 *
 * Endpoints consommes :
 *   - get_dashboard          : KPIs, run_id, runs_history (started_ts)
 *   - run/get_status         : statut, progress (idx/total), eta_s, logs
 *   - run/start_plan         : demarre un nouveau scan
 *   - run/cancel_run         : annule un run en cours
 *   - run/pause_run          : (optionnel, fallback si endpoint absent)
 *   - run/resume_run         : (optionnel, fallback si endpoint absent)
 *   - run/save_for_later     : (optionnel, fallback si endpoint absent)
 *   - check_duplicates       : groupes de doublons + comparison
 *   - save_validation        : persiste les decisions de validation
 *   - apply                  : execute apply (dry-run ou reel)
 *   - get_plan               : recharge plan.jsonl
 *
 * Route : /traitement (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost, fetchConfidenceThresholds, getConfidenceThresholdsSync } from "../core/api.js";
import { navigateTo } from "../core/router.js";
import { dangerConfirmModal, showModal, closeModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";
import { formatRelative, formatDuration } from "../core/format.js";
import { initDoublons, unmountDoublons } from "./doublons.js";
// Fix audit 2026-05-24 : import renderFilmDetail pour brancher les actions
// "rename" (Vérification) et "inspect" (Validation) qui étaient inertes.
import { renderFilmDetail } from "../components/film-detail.js";

const STEPS = [
  { id: "analyse", label: "Analyse", desc: "Scan des dossiers racines" },
  { id: "verification", label: "Vérification", desc: "Cas à vérifier (priorités)" },
  { id: "validation", label: "Validation", desc: "Approuver / rejeter les films" },
  { id: "doublons", label: "Doublons", desc: "Choisir le winner pour chaque groupe" },
  { id: "apply", label: "Apply", desc: "Renommer / déplacer sur disque" },
];

const STATUS_COLORS = {
  RUNNING: { cls: "is-running", icon: "●", label: "En cours" },
  PENDING: { cls: "is-running", icon: "●", label: "En attente" },
  PAUSED: { cls: "is-paused", icon: "⏸", label: "En pause" },
  SAVED: { cls: "is-paused", icon: "💾", label: "Sauvegardé" },
  AWAITING_VALIDATION: { cls: "is-paused", icon: "⏳", label: "En attente de validation" },
  DONE: { cls: "is-done", icon: "✓", label: "Terminé" },
  CANCELLED: { cls: "is-error", icon: "✗", label: "Annulé" },
  FAILED: { cls: "is-error", icon: "✗", label: "Erreur" },
  ERROR: { cls: "is-error", icon: "✗", label: "Erreur" },
};

const POLL_INTERVAL_RUNNING = 5000; // 5s pendant RUNNING (header)
const POLL_INTERVAL_ANALYSE = 2000; // 2s pendant scan en cours (etape 1)
// Fix APPLY-2 (2026-05-30) : polling rapide pendant apply en cours (etape 5).
const POLL_INTERVAL_APPLY = 1500;
const UNDO_COUNTDOWN_INTERVAL_MS = 60_000; // Spec 08 §3.5 : refresh carte undo / 60s

let _currentStep = "analyse";
let _runInfo = null;
let _runStatus = null; // { status, idx, total, eta_s, speed, logs }
let _loading = false;
let _targetRunId = null; // Phase 5 spec §2 : fragment #run-XXX = run cible à afficher.
let _pollTimer = null;
let _undoCountdownTimer = null; // Spec 08 §3.5 : refresh carte annulation post-apply.
let _logsState = { items: [], nextIndex: 0 };
let _scanOptions = {
  perceptual: true,
  subtitles: true,
  omdb: false,
  nfo: false,
  parallelism: 4,
};
let _activeContainer = null;
let _doublonsMounted = false;
// Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : flag d'idempotence du binding.
// Avant : _bindEvents() rattachait addEventListener() à chaque _renderInPlace()
// (polling 2-5s + chaque action UI) -> N listeners accumulés sur les MÊMES
// boutons (Pause, Cancel, Apply…) -> 1 clic = N appels API -> doubles annulations,
// doubles toasts, race conditions sur les state setters. Avec event delegation
// (un seul listener sur _container qui dispatch via event.target.closest),
// _renderInPlace() peut innerHTML= toute la vue sans risque : le listener vit
// sur le container parent, pas sur les enfants recrées.
let _eventsBound = false;
let _verifFilter = "all";
let _validationPlan = null; // { rows: [...] }
// Fix VAL-3 (2026-05-30) : state module-level pour filtre / tri / expanded rows
// de l'etape Validation. Reset au unmount pour eviter de garder un etat surprenant
// si l'utilisateur revient plus tard sur l'etape Validation.
let _validationFilter = "all"; // all | high | mid | low | none
let _validationSort = { key: "confidence", dir: "desc" };
let _validationExpanded = new Set();
// Fix APPLY-2 (2026-05-30) : intervalle polling pendant l'apply (idem scan)
// et state apply pour les progressions live.
let _applyStatus = null;
let _applyOptions = { dry_run: true, export_csv: false, sync_jellyfin: false, quarantine: false };
// Fix audit 2026-05-24 : AbortController scope module pour annuler tous les
// apiPost en vol au unmount (navigation, fermeture vue). Sans ça les fetch
// continuent et appellent _renderInPlace/_loadXxx après remise à null du
// container -> NPE silencieux dans la console + fuite mémoire.
let _abortController = null;

function _signal() {
  return _abortController ? _abortController.signal : undefined;
}

/* --- Step nav helpers --- */

function _readStep() {
  const hash = window.location.hash || "";
  const m = hash.match(/#step-([a-z]+)/);
  if (m && STEPS.some((s) => s.id === m[1])) return m[1];
  return "analyse";
}

/** Phase 5 (spec 05 §2 "Reprendre la validation") : extrait le run_id si
 *  fragment "/traitement#run-XXXX" présent. Stocké dans _targetRunId pour
 *  forcer le focus sur ce run au lieu du dernier en date.
 */
function _readTargetRunId() {
  const hash = window.location.hash || "";
  const m = hash.match(/#run-([^#&?\s]+)/);
  if (m) {
    try { return decodeURIComponent(m[1]); }
    catch (_e) { return m[1]; }
  }
  return null;
}

function _writeStep(stepId) {
  if (window.location.hash.includes(`#step-${stepId}`)) return;
  window.location.hash = `#/traitement#step-${stepId}`;
}

/* --- Data fetchers --- */

async function _loadRunInfo() {
  _loading = true;
  try {
    // Phase 5 : si fragment #run-XXX présent, charge ce run précis.
    const targetId = _targetRunId;
    // Fix audit 2026-05-24 : avant `run_id_or` (n'existe pas dans la facade)
    // -> get_dashboard renvoyait 400 -> _runInfo restait null -> polling
    // get_status jamais armé -> barre de progress + logs scan invisibles
    // dans l'UI alors que le scan tourne en backend.
    const params = targetId ? { run_id: targetId } : { run_id: "latest" };
    const res = await apiPost("run/get_dashboard", params, { signal: _signal() });
    if (!res || res.data?.ok === false) {
      _runInfo = null;
      return;
    }
    const data = res.data || res;
    // Fix audit 2026-05-24 : si le run actif change (nouveau scan lancé,
    // navigation #run-XXX), les logs accumulés du run précédent restaient
    // dans _logsState et étaient injectés en haut du log live du nouveau run
    // -> confusion utilisateur + nextIndex pointait dans la timeline du run
    // précédent -> get_status renvoyait des logs déjà vus (ou rien).
    if (data.run_id && _runInfo && _runInfo.runId && data.run_id !== _runInfo.runId) {
      _logsState = { items: [], nextIndex: 0 };
    }
    const k = data.kpis || {};
    const history = Array.isArray(data.runs_history) ? data.runs_history : [];
    const current = history.find((r) => r.run_id === data.run_id) || history[0] || {};
    const pendingUndoRaw = data.pending_undo && typeof data.pending_undo === "object" ? data.pending_undo : null;
    _runInfo = {
      runId: data.run_id,
      total: Number(k.total_movies || k.total_rows || 0),
      validated: Number(k.validated_count || k.approved_count || 0),
      rejected: Number(k.rejected_count || 0),
      conflicts: Number(k.conflicts_count || 0),
      duplicatesGroups: Number(k.duplicates_groups || 0),
      applied: Number(k.applied_rows || current.applied_rows || 0),
      reviewQueue: Number(k.review_queue_count || 0),
      score: Number(k.score_avg || 0),
      startedTs: Number(current.started_ts || 0),
      endedTs: Number(current.ended_ts || 0),
      duration: Number(current.duration_s || 0),
      errorsCount: Number(current.errors_count || 0),
      // Spec 08 §3.5 : carte annulation post-apply (24h).
      pendingUndo: pendingUndoRaw
        ? {
            batchId: String(pendingUndoRaw.batch_id || ""),
            applyTs: Number(pendingUndoRaw.apply_ts || 0),
            deadlineTs: Number(pendingUndoRaw.deadline_ts || 0),
            reversibleCount: Number(pendingUndoRaw.reversible_count || 0),
            expired: Boolean(pendingUndoRaw.expired),
          }
        : null,
    };
  } catch (_err) {
    _runInfo = null;
  }
  _loading = false;
}

async function _loadRunStatus() {
  if (!_runInfo || !_runInfo.runId) return;
  try {
    const res = await apiPost("run/get_status", {
      run_id: _runInfo.runId,
      last_log_index: _logsState.nextIndex || 0,
    }, { signal: _signal() });
    const data = res?.data || res;
    if (!data || data.ok === false) {
      _runStatus = null;
      return;
    }
    _runStatus = {
      status: String(data.status || "UNKNOWN"),
      running: Boolean(data.running),
      done: Boolean(data.done),
      idx: Number(data.idx || 0),
      total: Number(data.total || 0),
      eta_s: Number(data.eta_s || 0),
      speed: Number(data.speed || 0),
      current: String(data.current || ""),
      error: data.error || null,
      cancelRequested: Boolean(data.cancel_requested),
    };
    // Fix APPLY-2 (2026-05-30) : capter le sous-objet apply pour le rendu
    // de la barre de progression de l'etape 5. Backward-compat : si le backend
    // ne renvoie pas encore data.apply, on garde _applyStatus tel quel (peut
    // etre seede par _handleApplyNow en local).
    if (data.apply) {
      _applyStatus = {
        running: Boolean(data.apply.running),
        done: Boolean(data.apply.done),
        idx: Number(data.apply.idx || 0),
        total: Number(data.apply.total || 0),
        current: String(data.apply.current || ""),
        phase: String(data.apply.phase || ""),
        eta_s: Number(data.apply.eta_s || 0),
        speed: Number(data.apply.speed || 0),
        dryRun: Boolean(data.apply.dry_run),
      };
    } else if (!_applyStatus?.running) {
      _applyStatus = null;
    }
    const newLogs = Array.isArray(data.logs) ? data.logs : [];
    if (newLogs.length) {
      _logsState.items = (_logsState.items || []).concat(newLogs).slice(-30);
    }
    _logsState.nextIndex = Number(data.next_log_index || _logsState.nextIndex);
  } catch (_err) {
    /* on garde l'ancien _runStatus */
  }
}

/* --- Polling lifecycle --- */

function _stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

function _startPolling() {
  _stopPolling();
  // Fix APPLY-2 (2026-05-30) : polling rapide pendant un apply en cours sur
  // l'etape 5, pour que la barre de progression et le fichier en cours
  // refletent la realite serveur sans attendre 5s.
  let interval = POLL_INTERVAL_RUNNING;
  if (_currentStep === "analyse") {
    interval = POLL_INTERVAL_ANALYSE;
  } else if (_currentStep === "apply" && _applyStatus?.running) {
    interval = POLL_INTERVAL_APPLY;
  }
  _pollTimer = setInterval(async () => {
    // Fix audit 2026-05-24 : avant on poll-ait infiniment meme apres run done
    // -> 1 call/2-5s a vie tant que vue montee. Arret propre quand run termine.
    // Un refresh manuel ou un nouveau scan re-arme via _startPolling().
    // Fix APPLY-2 (2026-05-30) : ne PAS stopper le polling tant qu'un apply
    // est en cours, meme si le scan top-level est done.
    if (_runStatus && _runStatus.done && (!_applyStatus || _applyStatus.done || !_applyStatus.running)) {
      _stopPolling();
      // Fix audit 2026-05-24 (v1.5.2) : auto-transition Analyse -> Verification
      // quand le scan vient de se terminer. Avant : utilisateur restait sur
      // l'ecran Analyse avec uniquement le bouton "Lancer scan", aucun CTA
      // pour passer a l'etape suivante -> impasse UX. Le workflow est lineaire
      // et deterministe, pas de raison de rester sur Analyse quand done. Le
      // breadcrumb permet de revenir d'un clic au besoin.
      if (_currentStep === "analyse") {
        _currentStep = "verification";
        _writeStep("verification");
        // Fix audit 2026-05-26 (v1.5.6) Vague L (step-1) :
        // _renderInPlace seul affichait la Verification avec _validationPlan vide
        // (ou stale d'un run precedent). On charge le plan AVANT le render final
        // pour eviter l'ecran "0 films a verifier" trompeur juste apres la fin
        // de scan. _loadPlan est idempotent et s'auto-protege si runId absent.
        await _loadPlan();
      }
      _renderInPlace(); // render final manquant (avant return)
      return;
    }
    await _loadRunStatus();
    await _loadRunInfo();
    _renderInPlace();
  }, interval);
}

/* --- Header run actif (spec §2) --- */

function _shortRunId(rid) {
  if (!rid) return "—";
  // Format usuel : 20260517_15123abc-xxxx
  return String(rid).slice(0, 16);
}

function _renderHeaderRun() {
  if (!_runInfo || !_runInfo.runId) {
    return `
      <header class="traitement-header-run traitement-header-run--empty">
        <p class="traitement-header-empty">Aucun run actif détecté.</p>
        <div class="traitement-header-actions">
          <a href="#/processing" class="v5-btn v5-btn--primary">▶ Lancer un scan</a>
        </div>
      </header>
    `;
  }

  const status = _runStatus?.status || "UNKNOWN";
  const meta = STATUS_COLORS[status] || { cls: "is-unknown", icon: "?", label: status };
  const isRunning = status === "RUNNING" || status === "PENDING";
  const isPaused = status === "PAUSED" || status === "SAVED";
  const idx = _runStatus?.idx || 0;
  const total = _runStatus?.total || _runInfo.total || 0;
  const etaSeconds = _runStatus?.eta_s || 0;
  // ETA derive : si pas d'eta_s, calcule depuis progress + elapsed
  let etaLabel = "—";
  if (etaSeconds > 0) {
    etaLabel = `${formatDuration(etaSeconds)} restant`;
  } else if (isRunning && idx > 0 && total > 0 && _runInfo.startedTs > 0) {
    const elapsed = Date.now() / 1000 - _runInfo.startedTs;
    const estTotal = (elapsed / idx) * total;
    const remaining = Math.max(0, Math.round(estTotal - elapsed));
    etaLabel = remaining > 0 ? `${formatDuration(remaining)} restant` : "—";
  }

  const startedLabel = _runInfo.startedTs > 0
    ? `Démarré ${formatRelative(_runInfo.startedTs)}`
    : "";

  return `
    <header class="traitement-header-run ${escapeHtml(meta.cls)}">
      <div class="traitement-header-run-top">
        <div class="traitement-header-run-id">
          <button type="button" class="traitement-runchip" data-traitement-copy-runid title="Copier le run ID">
            run ${escapeHtml(_shortRunId(_runInfo.runId))}…
          </button>
        </div>
        <div class="traitement-run-status ${escapeHtml(meta.cls)}">
          <span class="traitement-run-status-dot" aria-hidden="true">${escapeHtml(meta.icon)}</span>
          <span class="traitement-run-status-label">${escapeHtml(meta.label)}</span>
        </div>
        <div class="traitement-run-meta">
          <span>${escapeHtml(String(total))} films</span>
          ${startedLabel ? `<span>·</span><span>${escapeHtml(startedLabel)}</span>` : ""}
          ${etaLabel !== "—" ? `<span>·</span><span class="traitement-run-eta">${escapeHtml(etaLabel)}</span>` : ""}
        </div>
      </div>
      <div class="traitement-header-actions">
        ${isRunning ? `<button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="pause">⏸ Pause</button>` : ""}
        ${isPaused ? `<button type="button" class="v5-btn v5-btn--primary" data-traitement-action="resume">▶ Reprendre</button>` : ""}
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="save" title="Sauvegarde le run en cours pour le reprendre plus tard depuis l Historique">💾 Sauvegarder</button><!-- Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-04 : tooltip explicite, distingue "Sauvegarder le run" (header) de "Sauver les decisions" (validation). -->
        <button type="button" class="v5-btn v5-btn--danger" data-traitement-action="cancel">⏹ Annuler</button>
      </div>
    </header>
  `;
}

/* --- Breadcrumb --- */

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
    case "validation": {
      // Fix VAL-1 (2026-05-30) : fallback defensif si le backend ne renvoie
      // pas encore validated_count / rejected_count dans kpis (compat ascendante
      // pendant rollout du patch backend dashboard_support.py).
      const validated = Number(_runInfo.validated ?? 0);
      const rejected = Number(_runInfo.rejected ?? 0);
      const total = Number(_runInfo.total ?? 0);
      return `
        <div class="traitement-stats">
          ${_renderStat("Validés", validated)}
          ${_renderStat("Rejetés", rejected)}
          ${_renderStat("En attente", Math.max(0, total - validated - rejected))}
        </div>
      `;
    }
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

/* --- Etape 1 : Analyse (spec §3.1) --- */

function _renderAnalyseStep() {
  const isRunning = _runStatus?.running;
  const idx = _runStatus?.idx || 0;
  const total = _runStatus?.total || _runInfo?.total || 0;
  const progressPct = total > 0 ? Math.round((idx * 100) / total) : 0;
  const logs = _logsState.items || [];

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 1 — Analyse</h2>
      <p class="traitement-panel-desc">Scan filesystem (probe ffprobe + MediaInfo)</p>
      ${_renderStepStats("analyse")}

      <details class="traitement-scan-drawer" ${isRunning ? "" : "open"}>
        <summary>Options de scan</summary>
        <div class="traitement-scan-options">
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="perceptual" ${_scanOptions.perceptual ? "checked" : ""}>
            Analyse perceptuelle (LPIPS V2)
          </label>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="subtitles" ${_scanOptions.subtitles ? "checked" : ""}>
            Détection sous-titres manquants (FR/EN)
          </label>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="omdb" ${_scanOptions.omdb ? "checked" : ""}>
            OMDb cross-check (rating + IMDb id)
          </label>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="nfo" ${_scanOptions.nfo ? "checked" : ""}>
            Vérification cohérence NFO/Kodi
          </label>
          <label class="traitement-scan-slider-row">
            Parallélisme : <strong data-scan-parallelism-label>${_scanOptions.parallelism}</strong>
            <input type="range" min="1" max="8" value="${_scanOptions.parallelism}" data-scan-opt="parallelism" class="traitement-scan-slider">
          </label>
        </div>
      </details>

      ${isRunning ? `
        <div class="traitement-scan-progress" role="status" aria-live="polite">
          <div class="traitement-scan-progress-bar">
            <div class="traitement-scan-progress-fill" style="--progress: ${progressPct / 100}"></div>
          </div>
          <div class="traitement-scan-progress-meta">
            <span>${escapeHtml(String(idx))}/${escapeHtml(String(total))} films</span>
            <span>${progressPct}%</span>
            ${_runStatus?.eta_s ? `<span>~${escapeHtml(formatDuration(_runStatus.eta_s))} restant</span>` : ""}
          </div>
        </div>
        <div class="traitement-scan-current">
          ${_runStatus?.current ? `Fichier en cours : <code>${escapeHtml(_runStatus.current)}</code>` : ""}
        </div>
      ` : ""}

      <div class="traitement-actions">
        ${!isRunning ? `<button type="button" class="v5-btn v5-btn--primary" data-traitement-action="start-scan">▶ Lancer le scan</button>` : ""}
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="view-logs">📋 Voir log complet</button>
      </div>

      ${logs.length > 0 ? `
        <div class="traitement-scan-live-log" aria-label="Journal live">
          <div class="traitement-scan-live-log-title">Journal live (10 dernières lignes)</div>
          <pre class="traitement-scan-live-log-pre">${escapeHtml(logs.slice(-10).map((l) => typeof l === "string" ? l : JSON.stringify(l)).join("\n"))}</pre>
        </div>
      ` : ""}
    </section>
  `;
}

/* --- Etape 2 : Verification (spec §3.2) --- */

function _renderVerificationStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  const flagged = rows.filter((r) => {
    const flags = String(r.warning_flags || "").split(",").filter(Boolean);
    return flags.length > 0;
  });
  const filtered = flagged.filter((r) => {
    if (_verifFilter === "all") return true;
    const flags = String(r.warning_flags || "");
    if (_verifFilter === "subs") return flags.includes("subtitle");
    if (_verifFilter === "dups") return flags.includes("duplicate");
    if (_verifFilter === "nfo") return flags.includes("nfo");
    return true;
  });

  // Fix VAL-2 (2026-05-30) : suppression du slice(0,50) qui tronquait
  // silencieusement la liste. Si > 500 lignes, un info banner est affiche
  // pour suggerer l'usage des filtres de confiance.
  const tableRows = filtered.map((r) => {
    const flags = String(r.warning_flags || "").split(",").filter(Boolean);
    return `
      <tr data-row-id="${escapeHtml(r.row_id || "")}">
        <td class="traitement-verif-title">${escapeHtml(r.proposed_title || "—")}</td>
        <td class="traitement-verif-year">${escapeHtml(String(r.proposed_year || ""))}</td>
        <td class="traitement-verif-alerts">
          ${flags.slice(0, 3).map((f) => `<span class="traitement-verif-alert">${escapeHtml(f)}</span>`).join(" ")}
          ${flags.length > 3 ? `<span class="traitement-verif-alert-more">+${flags.length - 3}</span>` : ""}
        </td>
        <td class="traitement-verif-confidence">${escapeHtml(String(r.confidence || 0))}</td>
        <td class="traitement-verif-actions">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-traitement-verif-action="rescan" data-row-id="${escapeHtml(r.row_id || "")}">↻ Re-scanner</button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-traitement-verif-action="rename" data-row-id="${escapeHtml(r.row_id || "")}">✎ Renommer</button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-traitement-verif-action="ignore" data-row-id="${escapeHtml(r.row_id || "")}">Ignorer</button>
        </td>
      </tr>
    `;
  }).join("");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 2 — Vérification</h2>
      <p class="traitement-panel-desc">Films problématiques à examiner avant validation</p>
      ${_renderStepStats("verification")}

      <div class="traitement-verif-filters" role="tablist" aria-label="Filtres vérification">
        <button type="button" class="traitement-verif-filter ${_verifFilter === "all" ? "is-active" : ""}" data-traitement-verif-filter="all">Tous problèmes (${flagged.length})</button>
        <button type="button" class="traitement-verif-filter ${_verifFilter === "subs" ? "is-active" : ""}" data-traitement-verif-filter="subs">Subs FR manquants</button>
        <button type="button" class="traitement-verif-filter ${_verifFilter === "dups" ? "is-active" : ""}" data-traitement-verif-filter="dups">Doublons cross-root</button>
        <button type="button" class="traitement-verif-filter ${_verifFilter === "nfo" ? "is-active" : ""}" data-traitement-verif-filter="nfo">NFO incohérent</button>
      </div>

      ${flagged.length === 0 ? `
        <p class="traitement-placeholder">✅ Tous les fichiers passent les contrôles. Continuez vers Validation.</p>
      ` : `
        <table class="traitement-verif-table" role="grid">
          <thead>
            <tr>
              <th>Titre</th>
              <th>Année</th>
              <th>Alertes</th>
              <th>Confiance</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
        ${filtered.length > 500 ? `
          <p class="traitement-verif-info v5u-text-muted v5u-text-center">
            Affichage de ${filtered.length} films. Utilisez les filtres ci-dessus pour reduire la liste si besoin.
          </p>
        ` : ""}
      `}

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="go-validation">→ Continuer vers Validation</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="reload-plan">↻ Re-vérifier</button>
      </div>
    </section>
  `;
}

/* --- Etape 3 : Validation (spec §3.3) --- */

// Fix VAL-3 (2026-05-30) : helpers de tri et bucketization.
// VN-C.1 (batch 2) : seuils 85/60 -> getConfidenceThresholdsSync()
// (source unique : cinesort/domain/confidence_thresholds.py).
function _confidenceBucket(conf) {
  const c = Number(conf || 0);
  const t = getConfidenceThresholdsSync();
  if (c >= t.high) return "high";
  if (c >= t.medium) return "mid";
  if (c > 0) return "low";
  return "none";
}

function _sortValidationRows(rows, sort) {
  const dirMult = sort.dir === "asc" ? 1 : -1;
  const key = sort.key;
  const copy = rows.slice();
  copy.sort((a, b) => {
    let va;
    let vb;
    if (key === "titre" || key === "proposed_title") {
      va = String(a.proposed_title || "").toLocaleLowerCase();
      vb = String(b.proposed_title || "").toLocaleLowerCase();
      return va.localeCompare(vb) * dirMult;
    }
    if (key === "annee" || key === "proposed_year") {
      va = Number(a.proposed_year) || 0;
      vb = Number(b.proposed_year) || 0;
    } else if (key === "score") {
      va = Number(a.score) || 0;
      vb = Number(b.score) || 0;
    } else {
      // confidence (defaut)
      va = Number(a.confidence) || 0;
      vb = Number(b.confidence) || 0;
    }
    if (va < vb) return -1 * dirMult;
    if (va > vb) return 1 * dirMult;
    return 0;
  });
  return copy;
}

// Fix VAL-3 : snapshot des etats DOM (checkbox + year input) avant un re-render
// declenche par un filtre / tri / expand pour eviter de perdre les modifications
// manuelles de l'utilisateur (regression UX-03 documentee dans _handleBulkApprove).
// Reinjecte directement dans _validationPlan.rows[].decision/proposed_year pour
// que le prochain render reflete les choix actifs.
function _persistValidationDomState() {
  if (!_activeContainer || !_validationPlan || !Array.isArray(_validationPlan.rows)) return;
  const byId = new Map();
  _validationPlan.rows.forEach((r) => byId.set(String(r.row_id || ""), r));
  _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
    const row = byId.get(String(cb.dataset.rowId || ""));
    if (!row) return;
    row.decision = cb.checked ? "OK" : "REJECT";
  });
  _activeContainer.querySelectorAll(".traitement-validation-year-input").forEach((inp) => {
    const row = byId.get(String(inp.dataset.rowId || ""));
    if (!row) return;
    const y = Number(inp.value) || null;
    if (y !== null) row.proposed_year = y;
  });
}

function _renderValidationStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  const pending = rows.filter((r) => !r.decision || r.decision === "PENDING");
  const sureCount = pending.filter((r) => Number(r.confidence || 0) >= 90).length;

  // Fix VAL-3 : compteurs par bucket de confiance sur l'ensemble pending.
  const buckets = { high: 0, mid: 0, low: 0, none: 0 };
  pending.forEach((r) => { buckets[_confidenceBucket(r.confidence)] += 1; });

  // Application du filtre puis du tri (VAL-3).
  let filtered = pending;
  if (_validationFilter !== "all") {
    filtered = pending.filter((r) => _confidenceBucket(r.confidence) === _validationFilter);
  }
  filtered = _sortValidationRows(filtered, _validationSort);

  // Fix VAL-2 (2026-05-30) : suppression du slice(0,100). On rend toutes les
  // lignes filtrees/triees ; un info banner s'affiche au-dela de 500.
  const sortKey = _validationSort.key;
  const sortDir = _validationSort.dir;
  const ariaSort = (col) => (sortKey === col ? (sortDir === "asc" ? "ascending" : "descending") : "none");
  const sortIndicator = (col) => {
    if (sortKey !== col) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  };

  // VN-C.1 (batch 2) : seuils unifies — 85/60 deviennent t.high / t.medium.
  const _thr = getConfidenceThresholdsSync();
  const tableRows = filtered.map((r) => {
    const conf = Number(r.confidence || 0);
    const confLabel = conf >= _thr.high ? "Haute" : (conf >= _thr.medium ? "Moyenne" : "Basse");
    const confCls = conf >= _thr.high ? "is-high" : (conf >= _thr.medium ? "is-mid" : "is-low");
    const rowId = String(r.row_id || "");
    const isExpanded = _validationExpanded.has(rowId);
    let defaultChecked;
    if (r.decision === "OK" || r.decision === "APPROVED") defaultChecked = true;
    else if (r.decision === "REJECT" || r.decision === "REJECTED") defaultChecked = false;
    else defaultChecked = conf >= _thr.high;

    const flags = String(r.warning_flags || "").split(",").filter(Boolean);
    const candidates = Array.isArray(r.candidates) ? r.candidates.slice(0, 3) : [];

    const baseRow = `
      <tr data-row-id="${escapeHtml(rowId)}">
        <td class="traitement-validation-check">
          <input type="checkbox" data-traitement-validation-check data-row-id="${escapeHtml(rowId)}" ${defaultChecked ? "checked" : ""}>
        </td>
        <td class="traitement-validation-confidence ${confCls}">${escapeHtml(confLabel)} (${conf})</td>
        <td class="traitement-validation-title">${escapeHtml(r.proposed_title || "—")}</td>
        <td class="traitement-validation-year">
          <input type="number" min="1900" max="2099" value="${escapeHtml(String(r.proposed_year || ""))}" class="traitement-validation-year-input" data-row-id="${escapeHtml(rowId)}">
        </td>
        <td class="traitement-validation-score">${escapeHtml(String(r.score ?? "—"))}</td>
        <td class="traitement-validation-source">${escapeHtml(String(r.proposed_source || "—"))}</td>
        <td class="traitement-validation-actions">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
                  data-traitement-validation-action="toggle-reasons"
                  data-row-id="${escapeHtml(rowId)}"
                  aria-expanded="${isExpanded ? "true" : "false"}"
                  title="${isExpanded ? "Replier les details" : "Afficher les details"}">
            ${isExpanded ? "▾" : "▸"}
          </button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-traitement-validation-action="inspect" data-row-id="${escapeHtml(rowId)}" title="Voir le detail">👁</button>
        </td>
      </tr>
    `;

    if (!isExpanded) return baseRow;

    const flagsHtml = flags.length
      ? `<div class="traitement-validation-reasons-flags">${flags.map((f) => `<span class="traitement-verif-alert">${escapeHtml(f)}</span>`).join(" ")}</div>`
      : "";
    const yearReason = r.detected_year_reason
      ? `<div><strong>Annee detectee :</strong> ${escapeHtml(String(r.detected_year_reason))}</div>`
      : "";
    const notes = r.notes
      ? `<div><strong>Notes :</strong> ${escapeHtml(String(r.notes))}</div>`
      : "";
    const candidatesHtml = candidates.length
      ? `<div class="traitement-validation-reasons-candidates">
           <strong>Candidats (top ${candidates.length}) :</strong>
           <ul>
             ${candidates.map((c) => `<li>[${escapeHtml(String(c.source || "?"))}] ${escapeHtml(String(c.title || "—"))} (${escapeHtml(String(c.year || "—"))}) — score=${escapeHtml(String(c.score ?? "—"))}${c.note ? ` — ${escapeHtml(String(c.note))}` : ""}</li>`).join("")}
           </ul>
         </div>`
      : "";

    return `${baseRow}
      <tr class="traitement-validation-row-expand">
        <td colspan="7">
          <div class="traitement-validation-reasons">
            ${flagsHtml}
            ${yearReason}
            ${notes}
            ${candidatesHtml}
            ${!flagsHtml && !yearReason && !notes && !candidatesHtml ? '<p class="v5u-text-muted">Aucun detail supplementaire.</p>' : ""}
          </div>
        </td>
      </tr>
    `;
  }).join("");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 3 — Validation</h2>
      <p class="traitement-panel-desc">Approuver / rejeter les propositions de classification</p>
      ${_renderStepStats("validation")}

      <div class="traitement-validation-filters" role="tablist" aria-label="Filtres confiance validation">
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "all" ? "is-active" : ""}" data-traitement-validation-filter="all" aria-selected="${_validationFilter === "all" ? "true" : "false"}">Tous (${pending.length})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "high" ? "is-active" : ""}" data-traitement-validation-filter="high" aria-selected="${_validationFilter === "high" ? "true" : "false"}">Haute (${buckets.high})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "mid" ? "is-active" : ""}" data-traitement-validation-filter="mid" aria-selected="${_validationFilter === "mid" ? "true" : "false"}">Moyenne (${buckets.mid})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "low" ? "is-active" : ""}" data-traitement-validation-filter="low" aria-selected="${_validationFilter === "low" ? "true" : "false"}">Basse (${buckets.low})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "none" ? "is-active" : ""}" data-traitement-validation-filter="none" aria-selected="${_validationFilter === "none" ? "true" : "false"}">Sans confiance (${buckets.none})</button>
      </div>

      <div class="traitement-validation-bulk">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="bulk-approve-sure">
          ✓ Tout approuver les sûrs (${sureCount})
        </button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="preset-no-alert">
          Approuver sans alerte
        </button>
        <!-- Fix audit 2026-05-24 : bouton "Rejeter tier Reject" supprimé.
             L'action n'était branchée que sur un showToast "non disponible"
             (cf _bindEvents preset-reject-reject) -> UI mensongère qui
             cassait la confiance utilisateur. À ré-ajouter quand bulk reject
             via run/save_validation sera spécifié. -->
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="preset-platinum-gold">
          Approuver Platinum + Gold
        </button>
      </div>

      ${pending.length === 0 ? `
        <p class="traitement-placeholder">✅ Toutes les décisions sont prises. Continuez vers Doublons.</p>
      ` : `
        <table class="traitement-validation-table" role="grid">
          <thead>
            <tr>
              <th>✓</th>
              <th class="is-sort ${sortKey === "confidence" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="confidence"
                  aria-sort="${ariaSort("confidence")}"
                  role="columnheader"
                  tabindex="0">Confiance${sortIndicator("confidence")}</th>
              <th class="is-sort ${sortKey === "titre" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="titre"
                  aria-sort="${ariaSort("titre")}"
                  role="columnheader"
                  tabindex="0">Titre${sortIndicator("titre")}</th>
              <th class="is-sort ${sortKey === "annee" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="annee"
                  aria-sort="${ariaSort("annee")}"
                  role="columnheader"
                  tabindex="0">Année${sortIndicator("annee")}</th>
              <th class="is-sort ${sortKey === "score" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="score"
                  aria-sort="${ariaSort("score")}"
                  role="columnheader"
                  tabindex="0">Score${sortIndicator("score")}</th>
              <th>Source</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
        ${filtered.length > 500 ? `
          <p class="traitement-validation-info v5u-text-muted v5u-text-center">
            Affichage de ${filtered.length} films. Utilisez les presets "Approuver les surs" ou les filtres de confiance pour traiter par lots.
          </p>
        ` : ""}
      `}

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="save-validation">💾 Sauver les décisions</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="go-doublons">→ Passer aux Doublons</button>
      </div>
    </section>
  `;
}

/* --- Etape 4 : Doublons (spec §3.4, inline) --- */

function _renderDoublonsStep() {
  return `
    <section class="traitement-panel traitement-panel--doublons" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 4 — Doublons</h2>
      <p class="traitement-panel-desc">Choisir le winner pour chaque groupe de doublons</p>
      <div id="traitement-doublons-mount" class="traitement-doublons-mount"></div>
      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="go-apply">→ Passer à l'application</button>
      </div>
    </section>
  `;
}

/* --- Spec 08 §3.5 : Carte "Annulation possible" post-apply --- */

function _formatUndoRemaining(remainingSeconds) {
  // Forme courte FR : "23h 12min", "45min", "30s". Pas de zero-pad pour rester court.
  const r = Math.max(0, Math.floor(Number(remainingSeconds) || 0));
  if (r <= 0) return "0s";
  const h = Math.floor(r / 3600);
  const m = Math.floor((r % 3600) / 60);
  const s = r % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}min`;
  if (m > 0) return `${m}min ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
}

function _renderUndoCard() {
  const undo = _runInfo?.pendingUndo;
  if (!undo || !undo.applyTs) return "";

  const now = Date.now() / 1000;
  const remaining = Math.max(0, Math.floor(undo.deadlineTs - now));
  const expired = undo.expired || remaining <= 0;
  const appliedAt = undo.applyTs > 0
    ? `Apply réalisé ${formatRelative(undo.applyTs)}`
    : "Apply récent";

  if (expired) {
    return `
      <aside class="traitement-undo-card traitement-undo-card--expired" data-traitement-undo-card>
        <header class="traitement-undo-card-head">
          <strong>Annulation post-apply</strong>
          <span class="traitement-undo-card-badge traitement-undo-card-badge--expired">Délai dépassé</span>
        </header>
        <p class="traitement-undo-card-body">
          Délai d'annulation dépassé (24h). ${escapeHtml(appliedAt)}.
        </p>
        <div class="traitement-undo-card-actions">
          <button type="button" class="v5-btn v5-btn--ghost" disabled title="Délai 24h dépassé">
            Prévisualiser annulation
          </button>
        </div>
      </aside>
    `;
  }

  return `
    <aside class="traitement-undo-card" data-traitement-undo-card>
      <header class="traitement-undo-card-head">
        <strong>Annulation possible</strong>
        <span class="traitement-undo-card-badge">
          ${escapeHtml(_formatUndoRemaining(remaining))} restant
        </span>
      </header>
      <p class="traitement-undo-card-body">
        ${escapeHtml(String(undo.reversibleCount))} opération${undo.reversibleCount > 1 ? "s" : ""} réversible${undo.reversibleCount > 1 ? "s" : ""}.
        ${escapeHtml(appliedAt)}. Tu peux encore restaurer l'état d'avant l'apply.
      </p>
      <div class="traitement-undo-card-actions">
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="undo-preview">
          Prévisualiser annulation
        </button>
      </div>
    </aside>
  `;
}

function _updateUndoCountdownLabels() {
  if (!_activeContainer) return;
  const undo = _runInfo?.pendingUndo;
  if (!undo || !undo.applyTs) return;
  const card = _activeContainer.querySelector("[data-traitement-undo-card]");
  if (!card) return;
  const now = Date.now() / 1000;
  const remaining = Math.max(0, Math.floor(undo.deadlineTs - now));
  if (remaining <= 0 && !card.classList.contains("traitement-undo-card--expired")) {
    // Bascule passive sur "Délai dépassé" : on re-rend tout l'étape Apply.
    _renderInPlace();
    return;
  }
  const badge = card.querySelector(".traitement-undo-card-badge");
  if (badge && !badge.classList.contains("traitement-undo-card-badge--expired")) {
    badge.textContent = `${_formatUndoRemaining(remaining)} restant`;
  }
}

// Fix audit 2026-05-25 (v1.5.3) Vague G Fix 1 : idempotence du countdown undo.
// Sans le _stopUndoCountdown() initial, un appel répété à _startUndoCountdown()
// (ex. remount, hashchange brutal, re-binding) lancerait un 2eme setInterval
// alors que le 1er continue de tourner -> double tick -> badge "X restant" se
// rafraichit 2 fois par cycle + leak. Le guard ci-dessous clear l'ancien
// timer avant d'en créer un nouveau. Le cleanup au unmount est déjà couvert
// dans unmountTraitement() ligne ~1510 via _stopUndoCountdown().
function _startUndoCountdown() {
  _stopUndoCountdown();
  _undoCountdownTimer = setInterval(_updateUndoCountdownLabels, UNDO_COUNTDOWN_INTERVAL_MS);
}

function _stopUndoCountdown() {
  if (_undoCountdownTimer) {
    clearInterval(_undoCountdownTimer);
    _undoCountdownTimer = null;
  }
}

function _renderUndoPreviewModalBody(preview) {
  const counts = preview?.counts || {};
  const reversible = Number(counts.reversible || 0);
  const irreversible = Number(counts.irreversible || 0);
  const conflicts = Number(counts.conflicts_predicted || 0);
  const samples = Array.isArray(preview?.samples) ? preview.samples : [];

  const summary = `
    <div class="traitement-undo-modal-summary">
      <ul>
        <li><strong>${escapeHtml(String(reversible))}</strong> opération${reversible > 1 ? "s" : ""} réversible${reversible > 1 ? "s" : ""}</li>
        <li><strong>${escapeHtml(String(irreversible))}</strong> non réversible${irreversible > 1 ? "s" : ""}</li>
        <li><strong>${escapeHtml(String(conflicts))}</strong> conflit${conflicts > 1 ? "s" : ""} prévu${conflicts > 1 ? "s" : ""}</li>
      </ul>
    </div>
  `;

  if (!samples.length) {
    return `${summary}<p class="traitement-undo-modal-empty">Aucun fichier réversible à afficher.</p>`;
  }

  const rows = samples.map((s) => `
    <li class="traitement-undo-modal-row">
      <code class="traitement-undo-modal-before">${escapeHtml(String(s.current_path || ""))}</code>
      <span class="traitement-undo-modal-arrow">↩</span>
      <code class="traitement-undo-modal-after">${escapeHtml(String(s.restore_path || ""))}</code>
    </li>
  `).join("");

  return `
    ${summary}
    <p class="traitement-undo-modal-note">Aperçu (${samples.length} première${samples.length > 1 ? "s" : ""} opération${samples.length > 1 ? "s" : ""}) :</p>
    <ul class="traitement-undo-modal-list">${rows}</ul>
  `;
}

async function _onUndoPreview() {
  if (!_runInfo?.runId) return;
  if (!_runInfo?.pendingUndo) return;
  try {
    const res = await apiPost("run/undo_last_apply_preview", { run_id: _runInfo.runId }, { signal: _signal() });
    const data = res?.data || res;
    if (!data || data.ok === false) {
      showToast({ type: "error", text: "Impossible de préparer l'annulation." });
      return;
    }
    if (!data.can_undo) {
      showToast({ type: "info", text: data.message || "Aucune opération réversible." });
      return;
    }
    // Fix audit 2026-05-24 (v1.5.2) : si le backend signale `expired`, on
    // retire l'action "Exécuter annulation" du modal — le call serait refuse
    // avec un 410 Gone. La preview reste consultable pour info.
    const expired = Boolean(data.expired);
    const actions = expired
      ? [
          { label: "Fermer", cls: "v5-btn v5-btn--ghost", onClick: () => {} },
        ]
      : [
          { label: "Fermer", cls: "v5-btn v5-btn--ghost", onClick: () => {} },
          {
            label: "Exécuter annulation",
            cls: "v5-btn v5-btn--danger",
            onClick: () => _onUndoExecute(),
          },
        ];
    showModal({
      title: expired
        ? "Prévisualisation de l'annulation (délai 24h dépassé)"
        : "Prévisualisation de l'annulation",
      body: _renderUndoPreviewModalBody(data),
      actions,
    });
  } catch {
    showToast({ type: "error", text: "Erreur lors de la prévisualisation." });
  }
}

function _onUndoExecute() {
  if (!_runInfo?.runId) return;
  const undo = _runInfo?.pendingUndo;
  if (!undo) return;

  // Spec 08 §3.5 : confirmation supplementaire + countdown 3s (memo
  // utilisateur "actions dangereuses CineSort").
  closeModal();
  dangerConfirmModal({
    title: "Confirmer l'annulation du dernier apply ?",
    items: [
      `${undo.reversibleCount} opération${undo.reversibleCount > 1 ? "s" : ""} sera${undo.reversibleCount > 1 ? "ont" : ""} annulée${undo.reversibleCount > 1 ? "s" : ""}`,
      `Batch ID : ${undo.batchId || "—"}`,
    ],
    consequence:
      "Les fichiers seront restaurés à leur emplacement et nom d'origine. Cette opération elle-même n'est PAS réversible automatiquement.",
    confirmLabel: "↩ Exécuter l'annulation",
    cancelLabel: "Annuler",
    countdownSeconds: 3,
    onConfirm: async () => {
      try {
        const res = await apiPost("run/undo_last_apply", { run_id: _runInfo.runId, dry_run: false }, { signal: _signal() });
        const data = res?.data || res;
        if (!data || data.ok === false) {
          // Fix audit 2026-05-24 (v1.5.2) : message dedie quand le backend
          // refuse pour delai 24h depasse (cas race ou client a un cache
          // d'`expired=false` perime). On rafraichit aussi le dashboard pour
          // synchroniser la carte.
          const msg = data?.message || data?.error || "Échec de l'annulation.";
          showToast({ type: "error", text: msg });
          await _loadRunInfo();
          _renderInPlace();
          return;
        }
        showToast({ type: "success", text: "Annulation appliquée. Restauration effectuée.", duration: 6000 });
        await _loadRunInfo();
        _renderInPlace();
      } catch {
        showToast({ type: "error", text: "Erreur lors de l'annulation." });
      }
    },
  });
}

/* --- Etape 5 : Apply (spec §3.5) --- */

// Fix audit 2026-05-25 (v1.5.3) Vague F : formattage explicite des entries
// preview apply. apply_core.py ne renomme JAMAIS les fichiers video : il
// renomme uniquement le dossier parent. Affichage src->dst brut suggerait
// a tort un renommage du fichier.
function _formatPreviewEntry(entry) {
  const action = String(entry?.action_summary || "");
  const folderOld = escapeHtml(String(entry?.folder_old_name || ""));
  const folderNew = escapeHtml(String(entry?.folder_new_name || ""));
  const videoName = escapeHtml(String(entry?.video_filename || ""));
  if (action === "folder_rename") {
    return `<div class="apply-preview-entry">
      <span>Dossier renomme :</span>
      <code>${folderOld}</code> -> <code>${folderNew}</code>
      <div class="apply-preview-note">Fichier conserve : <code>${videoName}</code></div>
    </div>`;
  }
  if (action === "video_move" || action === "folder_rename_and_video_move") {
    return `<div class="apply-preview-entry">
      <span>Video deplacee :</span>
      <code>${folderOld}/${videoName}</code> -> <code>${folderNew}/${videoName}</code>
      <div class="apply-preview-note">Nom du fichier conserve.</div>
    </div>`;
  }
  if (action === "video_rename_tv") {
    return `<div class="apply-preview-entry">
      <span>Episode TV renomme :</span>
      <code>${folderOld}/${videoName}</code> -> <code>${folderNew}/${escapeHtml(String(entry?.dst_filename || ""))}</code>
    </div>`;
  }
  // Retro-compat : si l'entry n'a pas d'action_summary (ex. row simple),
  // on affiche le titre/annee comme fallback prudent en signalant que le
  // fichier video conserve son nom.
  const src = escapeHtml(String(entry?.src_path || entry?.video || ""));
  const dst = escapeHtml(String(entry?.dst_path || ""));
  if (src && dst) {
    return `<div class="apply-preview-entry">
      <code>${src}</code> -> <code>${dst}</code>
    </div>`;
  }
  return `<div class="apply-preview-entry">${src || dst || "&mdash;"}</div>`;
}

function _renderApplyStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  // VN-C.1 (batch 2) : seuil "auto-approve" = CONF_HIGH (85) via thresholds unifies.
  const _autoThr = getConfidenceThresholdsSync().high;
  const approved = rows.filter((r) => r.decision === "ok" || r.decision === "approved" || Number(r.confidence || 0) >= _autoThr);
  const renames = approved.length;
  const moves = (_runInfo?.duplicatesGroups || 0) * 2;
  const deletions = 0; // placeholder pour reject deletions

  // Fix audit 2026-05-25 (v1.5.3) Vague F : afficher dossier_avant -> dossier_apres
  // et indiquer explicitement que le nom du fichier video est conserve par
  // apply_core (contrainte projet : "JAMAIS modifier le titre des films").
  const preview = approved.slice(0, 3).map((r) => {
    const videoName = String(r.video || "");
    const folderOld = String(r.folder || r.path || "");
    const proposedTitle = String(r.proposed_title || "");
    const proposedYear = String(r.proposed_year || "");
    const folderNew = proposedTitle ? `${proposedTitle}${proposedYear ? " (" + proposedYear + ")" : ""}` : folderOld;
    return `
    <li>
      <div class="apply-preview-entry">
        <span>Dossier renomme :</span>
        <code class="traitement-apply-before">${escapeHtml(folderOld)}</code>
        <span class="traitement-apply-arrow">-></span>
        <code class="traitement-apply-after">${escapeHtml(folderNew)}</code>
        ${videoName ? `<div class="apply-preview-note">Fichier conserve : <code>${escapeHtml(videoName)}</code></div>` : ""}
      </div>
    </li>
  `;
  }).join("");

  // Fix APPLY-2 (2026-05-30) : barre de progression live pendant un apply
  // en cours. Reutilise les classes CSS .traitement-scan-progress-* deja
  // stylees pour l'etape Analyse.
  const applyIdx = Number(_applyStatus?.idx || 0);
  const applyTotal = Number(_applyStatus?.total || 0);
  const applyPct = applyTotal > 0 ? Math.round((applyIdx * 100) / applyTotal) : 0;
  const applyEta = Number(_applyStatus?.eta_s || 0);
  const applyDryRun = Boolean(_applyStatus?.dryRun);
  const applyCurrent = String(_applyStatus?.current || "");
  const applyPhase = String(_applyStatus?.phase || "");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 5 — Application</h2>
      <p class="traitement-panel-desc">Renommage et déplacement sur disque</p>
      ${_renderStepStats("apply")}

      ${_applyStatus?.running ? `
        <div class="traitement-apply-progress traitement-scan-progress" role="status" aria-live="polite">
          <div class="traitement-scan-progress-bar">
            <div class="traitement-scan-progress-fill" style="--progress: ${applyPct / 100}"></div>
          </div>
          <div class="traitement-scan-progress-meta">
            <span>${escapeHtml(String(applyIdx))}/${escapeHtml(String(applyTotal))} ${applyDryRun ? "simules" : "appliques"}</span>
            <span>${applyPct}%</span>
            ${applyEta > 0 ? `<span>~${escapeHtml(formatDuration(applyEta))} restant</span>` : ""}
          </div>
          ${applyCurrent ? `<div class="traitement-scan-current">${applyDryRun ? "Simulation" : "Traitement"} : <code>${escapeHtml(applyCurrent)}</code></div>` : ""}
          ${applyPhase ? `<div class="traitement-apply-phase v5u-text-muted">Phase : ${escapeHtml(applyPhase)}</div>` : ""}
        </div>
      ` : ""}

      <div class="traitement-apply-summary">
        <h3>Résumé des opérations</h3>
        <ul>
          <li><strong>${escapeHtml(String(renames))}</strong> renommage${renames > 1 ? "s" : ""}</li>
          <li><strong>${escapeHtml(String(moves))}</strong> déplacement${moves > 1 ? "s" : ""}</li>
          <li><strong>${escapeHtml(String(deletions))}</strong> suppression${deletions > 1 ? "s" : ""}</li>
        </ul>
      </div>

      ${preview ? `
        <div class="traitement-apply-preview">
          <h4>Aperçu (3 premiers exemples)</h4>
          <ul class="traitement-apply-preview-list">${preview}</ul>
        </div>
      ` : ""}

      <div class="traitement-apply-options">
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="dry_run" ${_applyOptions.dry_run ? "checked" : ""}>
          Mode dry-run (recommandé pour le premier passage)
        </label>
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="export_csv" ${_applyOptions.export_csv ? "checked" : ""}>
          Exporter le rapport en CSV
        </label>
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="sync_jellyfin" ${_applyOptions.sync_jellyfin ? "checked" : ""}>
          Synchroniser Jellyfin après apply
        </label>
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="quarantine" ${_applyOptions.quarantine ? "checked" : ""}>
          Quarantaine des non-approuvés
        </label>
      </div>

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="apply-now">
          ${_applyOptions.dry_run ? "▶ Lancer le dry-run" : "✅ Appliquer maintenant"}
        </button>
      </div>

      ${_renderUndoCard()}
    </section>
  `;
}

/* --- Step panel routing --- */

function _renderStepPanel(stepId) {
  if (_loading) {
    // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 3 : loading visible avec skeleton.
    // Avant : "Chargement de l'état du run…" sur une ligne -> écran quasi-vide
    // pendant 3-5s -> utilisateur confus (vue cassée ? backend lent ?). Pattern
    // emprunté à doublons.js:393 qui combine header + skeletons + détail attente.
    return `
      <section class="traitement-panel">
        <div class="traitement-loading-header">⏳ Chargement de l'état du run…</div>
        ${[1, 2, 3].map(() => `<div class="v5-skeleton" style="height:48px;margin:8px 0;"></div>`).join("")}
      </section>
    `;
  }
  if (!_runInfo) {
    const step = STEPS.find((s) => s.id === stepId) || STEPS[0];
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
  switch (stepId) {
    case "analyse": return _renderAnalyseStep();
    case "verification": return _renderVerificationStep();
    case "validation": return _renderValidationStep();
    case "doublons": return _renderDoublonsStep();
    case "apply": return _renderApplyStep();
    default: return _renderAnalyseStep();
  }
}

/* --- Main render --- */

function _renderTraitement() {
  // Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 4) : si aucun run actif, on
  // masque le breadcrumb pour eviter l'incoherence visuelle "etape 3 Validation
  // en violet active" + message "Aucun run actif detecte" simultanes
  // (capture 11 du rapport audit). Le breadcrumb reapparait des qu'un run est
  // detecte via _loadRunInfo(). Note : on garde le step panel qui affiche un
  // CTA "Lancer un scan" — l'utilisateur sait quoi faire ensuite.
  const showBreadcrumb = Boolean(_runInfo && _runInfo.runId);
  return `
    <section class="traitement-view">
      <header class="traitement-header">
        <div class="traitement-header-row">
          <h1 class="traitement-title">Traitement</h1>
        </div>
        <p class="traitement-subtitle">Workflow d'un scan : analyse → validation → apply</p>
      </header>
      ${_renderHeaderRun()}
      ${showBreadcrumb ? _renderBreadcrumb(_currentStep) : ""}
      ${_renderStepPanel(_currentStep)}
    </section>
  `;
}

function _renderInPlace() {
  if (!_activeContainer) return;
  _activeContainer.innerHTML = _renderTraitement();
  _bindEvents(_activeContainer);
  // Si on est sur l'etape doublons, monte la vue Doublons dans son container
  if (_currentStep === "doublons") {
    const mount = _activeContainer.querySelector("#traitement-doublons-mount");
    // Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 1) : avant on ne re-montait
    // Doublons QUE si !_doublonsMounted. Mais _renderInPlace() est appele par
    // le polling toutes les 5s (POLL_INTERVAL_RUNNING) -> ecrase mount.innerHTML
    // -> Doublons reste mount=true mais le DOM est vide -> zone blanche entre
    // titre et bouton "Passer a l'application" (capture 8 du rapport audit).
    // Solution : detecter mount vide (re-mount necessaire) OU !_doublonsMounted
    // (1er passage). Le re-mount est idempotent (initDoublons reset son _state
    // et _filmCache, puis relance _loadGroups). Pas de double fetch en pratique
    // car le polling 5s laisse le temps au fetch precedent de finir.
    if (mount && (!_doublonsMounted || mount.children.length === 0)) {
      _doublonsMounted = true;
      initDoublons(mount);
    }
  } else if (_doublonsMounted) {
    unmountDoublons();
    _doublonsMounted = false;
  }
}

/* --- Actions (header + steps) --- */

async function _handleHeaderAction(action) {
  if (!_runInfo?.runId) return;
  const runId = _runInfo.runId;

  if (action === "pause") {
    try {
      const res = await apiPost("run/pause_run", { run_id: runId }, { signal: _signal() });
      if (res?.data?.ok) {
        showToast({ type: "info", text: "Run mis en pause." });
        await _loadRunStatus();
        _renderInPlace();
      } else {
        showToast({ type: "warn", text: "Endpoint pause indisponible (PR backend en attente)." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors de la pause." });
    }
  } else if (action === "resume") {
    try {
      const res = await apiPost("run/resume_run", { run_id: runId }, { signal: _signal() });
      if (res?.data?.ok) {
        showToast({ type: "success", text: "Run repris." });
        await _loadRunStatus();
        _renderInPlace();
      } else {
        showToast({ type: "warn", text: "Endpoint resume indisponible (PR backend en attente)." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors de la reprise." });
    }
  } else if (action === "save") {
    try {
      const res = await apiPost("run/save_for_later", { run_id: runId }, { signal: _signal() });
      if (res?.data?.ok) {
        showToast({ type: "success", text: "Run sauvegardé. Retrouvez-le dans l'Historique." });
      } else {
        showToast({ type: "warn", text: "Endpoint save_for_later indisponible (PR backend en attente)." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors de la sauvegarde." });
    }
  } else if (action === "cancel") {
    dangerConfirmModal({
      title: "Annuler le run en cours ?",
      items: [`Run ${_shortRunId(runId)}`, `${_runInfo.total} films · ${_runInfo.validated} validés`],
      consequence: "Les décisions validées seront perdues. Aucune modification sur disque (le run n'a pas été appliqué). Run marqué CANCELLED dans l'Historique.",
      confirmLabel: "Annuler le run",
      cancelLabel: "Garder le run",
      countdownSeconds: 3,
      onConfirm: async () => {
        try {
          const res = await apiPost("run/cancel_run", { run_id: runId }, { signal: _signal() });
          if (res?.data?.ok) {
            showToast({ type: "success", text: "Run annulé." });
            await _loadRunInfo();
            await _loadRunStatus();
            _renderInPlace();
          } else {
            showToast({ type: "error", text: "Échec de l'annulation." });
          }
        } catch {
          showToast({ type: "error", text: "Erreur lors de l'annulation." });
        }
      },
    });
  }
}

async function _handleScanStart() {
  try {
    const settings = {
      perceptual: _scanOptions.perceptual,
      subtitles: _scanOptions.subtitles,
      omdb: _scanOptions.omdb,
      nfo: _scanOptions.nfo,
      parallelism: _scanOptions.parallelism,
    };
    const res = await apiPost("run/start_plan", { settings }, { signal: _signal() });
    if (res?.data?.ok) {
      showToast({ type: "success", text: "Scan démarré." });
      await _loadRunInfo();
      await _loadRunStatus();
      _startPolling();
      _renderInPlace();
    } else {
      showToast({ type: "error", text: "Impossible de démarrer le scan." });
    }
  } catch {
    showToast({ type: "error", text: "Erreur lors du démarrage." });
  }
}

async function _loadPlan() {
  if (!_runInfo?.runId) return;
  try {
    const res = await apiPost("run/get_plan", { run_id: _runInfo.runId }, { signal: _signal() });
    const data = res?.data || res;
    if (data?.ok !== false) {
      _validationPlan = { rows: Array.isArray(data.rows) ? data.rows : (Array.isArray(data) ? data : []) };
    }
  } catch {
    _validationPlan = { rows: [] };
  }
}

function _buildDecisions() {
  if (!_activeContainer) return {};
  const decisions = {};
  _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
    const rowId = cb.dataset.rowId;
    if (!rowId) return;
    const yearInput = _activeContainer.querySelector(`.traitement-validation-year-input[data-row-id="${rowId}"]`);
    decisions[rowId] = {
      ok: cb.checked,
      year: yearInput ? Number(yearInput.value) || null : null,
    };
  });
  return decisions;
}

async function _handleBulkApprove(filter) {
  if (!_validationPlan?.rows) return;
  if (!_runInfo?.runId) return;
  let approvedCount = 0;
  const rows = _validationPlan.rows;
  const targetIds = new Set();
  rows.forEach((r) => {
    const conf = Number(r.confidence || 0);
    const flags = String(r.warning_flags || "");
    let match = false;
    // VN-C.1 (batch 2) : "sure" reste a 90 (seuil bulk-approve specifique,
    // plus strict que CONF_HIGH=85). C'est un parametre UI distinct
    // des seuils high/med/low semantiques.
    if (filter === "sure") match = conf >= 90;
    else if (filter === "no-alert") match = !flags;
    else if (filter === "platinum-gold") match = ["Platinum", "Gold"].includes(String(r.tier || ""));
    if (match) {
      targetIds.add(r.row_id);
      approvedCount += 1;
    }
  });

  // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-03 : snapshot des
  // checkboxes AVANT modification (et non du champ `decision` cote serveur qui
  // n'a pas encore ete persiste a ce stade). Sans ca, l'undo restaurait des
  // "PENDING" cote DOM alors que l'utilisateur avait deja coche manuellement.
  const checkboxSnapshot = new Map();
  _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
    checkboxSnapshot.set(cb.dataset.rowId, cb.checked);
  });

  // Mise a jour locale + UI
  _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
    if (targetIds.has(cb.dataset.rowId)) cb.checked = true;
  });

  // Fix VAL-1 (2026-05-30) : persister les decisions cote serveur via
  // run/save_validation AVANT d'afficher le toast success. Sans ca, les KPI
  // cards (Valides / Rejetes / En attente) restaient figes a 0 puisque le
  // backend ne savait rien des approbations en masse. En cas d'echec API on
  // rollback le DOM via le snapshot et on n'affiche pas le toast success.
  const decisions = _buildDecisions();
  let saveOk = false;
  try {
    const res = await apiPost(
      "run/save_validation",
      { run_id: _runInfo.runId, decisions },
      { signal: _signal() },
    );
    saveOk = res?.data?.ok !== false;
  } catch (_err) {
    saveOk = false;
  }

  if (!saveOk) {
    // Rollback DOM : on remet les checkboxes telles qu'avant le bulk approve.
    _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
      const prev = checkboxSnapshot.get(cb.dataset.rowId);
      if (prev !== undefined) cb.checked = prev;
    });
    showToast({
      type: "error",
      text: "Echec de la sauvegarde des decisions. Aucun changement applique.",
      duration: 8000,
    });
    return;
  }

  // Recharge les KPIs frais (validated_count / rejected_count) puis re-render.
  await _loadRunInfo();
  _renderInPlace();

  // Fix TOAST-1 (2026-05-30) : remplacement de persistent: true par
  // duration: 10000. Le bouton Annuler reste cliquable 10s (UX standard,
  // cf Gmail Undo Send 5-30s) et le toast disparait tout seul ensuite.
  // Evite l'accumulation de toasts indemontables si l'utilisateur clique
  // plusieurs fois "Approuver les surs" (10+ toasts persistants signales).
  showToast({
    type: "success",
    text: `${approvedCount} films approuves.`,
    duration: 10000,
    action: {
      label: "Annuler",
      onClick: async () => {
        if (!_activeContainer) return;
        // Restaurer les checkboxes au snapshot original.
        _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
          const prev = checkboxSnapshot.get(cb.dataset.rowId);
          if (prev !== undefined) cb.checked = prev;
        });
        // Re-persister les decisions originales pour que les KPI reflechissent
        // l'etat avant le bulk approve.
        if (!_runInfo?.runId) return;
        const originalDecisions = _buildDecisions();
        try {
          await apiPost(
            "run/save_validation",
            { run_id: _runInfo.runId, decisions: originalDecisions },
            { signal: _signal() },
          );
          await _loadRunInfo();
          _renderInPlace();
          showToast({ type: "info", text: "Approbation en masse annulee." });
        } catch (_err) {
          showToast({
            type: "error",
            text: "Annulation echouee : impossible de restaurer les decisions.",
            duration: 8000,
          });
        }
      },
    },
  });
}

async function _handleApplyNow() {
  if (!_runInfo?.runId) return;
  const decisions = _buildDecisions();
  const opCount = Object.values(decisions).filter((d) => d.ok).length;

  if (_applyOptions.dry_run) {
    // Dry-run direct sans confirmation
    // Fix APPLY-2 (2026-05-30) : seed l'etat optimiste pour la barre de
    // progression + relance le polling avec interval rapide (1.5s).
    _applyStatus = {
      running: true,
      done: false,
      idx: 0,
      total: opCount,
      current: "Demarrage...",
      phase: "starting",
      eta_s: 0,
      speed: 0,
      dryRun: true,
    };
    _renderInPlace();
    _startPolling();
    try {
      const res = await apiPost("run/apply", {
        run_id: _runInfo.runId,
        decisions,
        dry_run: true,
        quarantine_unapproved: _applyOptions.quarantine,
      }, { signal: _signal() });
      if (res?.data?.ok !== false) {
        if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
        showToast({ type: "success", text: "Dry-run terminé. Aucun fichier modifié.", duration: 5000 });
        await _loadRunInfo();
        _renderInPlace();
      } else {
        if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
        // Fix audit 2026-05-25 (v1.5.5) Vague J : remonter le vrai message
        // backend (user_message Vague G / message _err_response) au lieu
        // d'un toast generique qui masque le diag. (res.data || res) car
        // certains endpoints renvoient le payload a plat, d'autres sous .data.
        const data = res?.data || res || {};
        const backendMsg = data.user_message || data.message || data.error;
        showToast({
          type: "error",
          text: backendMsg ? `Echec du dry-run : ${backendMsg}` : "Echec du dry-run.",
          duration: 8000,
        });
      }
    } catch (err) {
      // Fix audit 2026-05-25 (v1.5.5) Vague J : meme exception, on tente de
      // remonter le message si l'erreur porte un payload (apiPost levee).
      const exMsg = err?.data?.user_message || err?.data?.message || err?.message;
      showToast({
        type: "error",
        text: exMsg ? `Erreur lors du dry-run : ${exMsg}` : "Erreur lors du dry-run.",
        duration: 8000,
      });
    }
    return;
  }

  // Apply reel : modale danger avec countdown 3s
  dangerConfirmModal({
    title: "Confirmer l'application sur le filesystem ?",
    items: [
      `${opCount} fichiers renommés/déplacés`,
      `Quarantaine : ${_applyOptions.quarantine ? "activée" : "désactivée"}`,
      `CSV : ${_applyOptions.export_csv ? "exporté" : "non exporté"}`,
    ],
    // Fix audit 2026-05-26 (v1.5.6) Vague L (undo-1) :
    // Le backend enforce un delai d'undo de 24h (cf cinesort/ui/api/apply_support.py:52,
    // _UNDO_DEADLINE_SECONDS = 24 * 3600). La modale danger pre-apply affichait
    // erronement "7 jours" (heritage du doc 08-traitement.md), ce qui creait une
    // attente utilisateur incoherente avec la realite serveur. On aligne sur 24h
    // pour matcher le toast post-apply (ligne ~1317) et la carte annulation expiree.
    consequence: "Les fichiers sur disque seront effectivement modifiés. Réversible via Undo pendant 24h après apply.",
    confirmLabel: "✗ Appliquer pour de vrai",
    cancelLabel: "Annuler",
    countdownSeconds: 3,
    onConfirm: async () => {
      // Fix APPLY-2 (2026-05-30) : seed apply progress optimiste + polling
      // rapide pour refleter en direct l'avancement cote backend.
      _applyStatus = {
        running: true,
        done: false,
        idx: 0,
        total: opCount,
        current: "Demarrage...",
        phase: "starting",
        eta_s: 0,
        speed: 0,
        dryRun: false,
      };
      _renderInPlace();
      _startPolling();
      try {
        const res = await apiPost("run/apply", {
          run_id: _runInfo.runId,
          decisions,
          dry_run: false,
          quarantine_unapproved: _applyOptions.quarantine,
        }, { signal: _signal() });
        if (res?.data?.ok !== false) {
          if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
          showToast({ type: "success", text: "Apply terminé · Undo possible 24h", duration: 7000 });
          await _loadRunInfo();
          _renderInPlace();
        } else {
          if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
          showToast({ type: "error", text: "Échec de l'apply." });
          _renderInPlace();
        }
      } catch {
        if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
        showToast({ type: "error", text: "Erreur lors de l'apply." });
        _renderInPlace();
      }
    },
  });
}

/* --- Event binding --- */

// Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : event delegation centralisée.
// Avant : 7 boucles forEach(addEventListener) à chaque _renderInPlace() ->
// listeners empilés sur les boutons recréés (innerHTML replace ne nettoie pas
// les anciens handlers de leurs ancêtres si on rattache à chaque tour).
// Maintenant : 2 listeners (click + change) attachés UNE seule fois au container
// parent. Le dispatch utilise event.target.closest() qui survit aux re-renders
// puisque le container lui-même n'est jamais détruit avant unmount.
function _onContainerClick(event) {
  const container = _activeContainer;
  if (!container) return;

  // Breadcrumb (étapes du workflow)
  const stepBtn = event.target.closest("[data-traitement-step]");
  if (stepBtn && container.contains(stepBtn)) {
    if (stepBtn.disabled) return;
    const stepId = stepBtn.dataset.traitementStep;
    _currentStep = stepId;
    _writeStep(stepId);
    _renderInPlace();
    return;
  }

  // Copy run ID
  const copyBtn = event.target.closest("[data-traitement-copy-runid]");
  if (copyBtn && container.contains(copyBtn)) {
    if (!_runInfo?.runId) return;
    navigator.clipboard.writeText(_runInfo.runId).then(
      () => showToast({ type: "info", text: "Run ID copié dans le presse-papier." }),
      () => { /* ignore */ },
    );
    return;
  }

  // Header + step generic actions (data-traitement-action)
  const actionBtn = event.target.closest("[data-traitement-action]");
  if (actionBtn && container.contains(actionBtn)) {
    const action = actionBtn.dataset.traitementAction;
    if (["pause", "resume", "save", "cancel"].includes(action)) {
      _handleHeaderAction(action);
    } else if (action === "start-scan") {
      _handleScanStart();
    } else if (action === "view-logs") {
      showToast({ type: "info", text: "Ouverture du journal complet…" });
      window.location.hash = "#/logs";
    } else if (action === "go-validation") {
      _currentStep = "validation";
      _writeStep("validation");
      _renderInPlace();
    } else if (action === "go-doublons") {
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-02 : avant la
      // transition Validation -> Doublons, detecter si l'utilisateur a modifie
      // des decisions (checkboxes / annees) sans cliquer "Sauver les decisions".
      // Avant : la transition etait silencieuse -> au retour sur Validation,
      // les decisions etaient perdues car save_validation n'avait jamais ete
      // appele. Maintenant : modal explicite "Sauvegarder avant de continuer ?"
      // avec 3 choix (Sauver puis continuer / Continuer sans sauver / Annuler).
      if (_hasUnsavedValidationDecisions()) {
        showModal({
          title: "Decisions non sauvegardees",
          body: `<p>Vous avez modifie des decisions de validation sans cliquer sur <strong>"Sauver les decisions"</strong>.</p>
                 <p>Si vous passez aux Doublons maintenant, vos modifications seront perdues au prochain rechargement.</p>
                 <p><strong>Sauvegarder avant de continuer ?</strong></p>`,
          actions: [
            { label: "Annuler", cls: "", onClick: () => {} },
            { label: "Continuer sans sauver", cls: "v5-btn--secondary", onClick: () => {
              _currentStep = "doublons";
              _writeStep("doublons");
              _renderInPlace();
            } },
            { label: "Sauver puis continuer", cls: "btn-primary v5-btn--primary", onClick: async () => {
              await _handleSaveValidation();
              _currentStep = "doublons";
              _writeStep("doublons");
              _renderInPlace();
            } },
          ],
        });
        return;
      }
      _currentStep = "doublons";
      _writeStep("doublons");
      _renderInPlace();
    } else if (action === "go-apply") {
      // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 4 : confirmation si doublons
      // non décidés. Avant : transition Doublons->Apply silencieuse -> appliquait
      // les "défauts" (le 1er fichier de chaque groupe gagne par convention) sans
      // que l'utilisateur en soit informé -> suppressions non voulues sur des
      // groupes qu'il n'avait pas encore arbitrés.
      // L'état pendingCount est local au module doublons.js (non exporté), on
      // lit donc le DOM du mount : le badge ".doublons-decided-count" affiche
      // "X décidés / Y" => on calcule pending depuis le DOM si présent.
      const pendingDups = _readDoublonsPendingFromDom();
      if (pendingDups > 0) {
        // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace window.confirm()
        // natif par dangerConfirmModal (application defauts = potentiellement destructif sur
        // les groupes non arbitres). Memoire utilisateur exige countdown 3s si > 50 elements.
        dangerConfirmModal({
          title: `Passer à Apply avec ${pendingDups} doublon${pendingDups > 1 ? "s" : ""} non décidé${pendingDups > 1 ? "s" : ""} ?`,
          consequence: "Les choix par défaut (premier fichier de chaque groupe) seront appliqués. Les autres fichiers de doublons peuvent être supprimés/déplacés selon votre profil.",
          countdownSeconds: pendingDups > 50 ? 3 : 0,
          confirmLabel: "Continuer vers Apply",
          cancelLabel: "Retourner aux Doublons",
          onConfirm: () => {
            _currentStep = "apply";
            _writeStep("apply");
            _renderInPlace();
          },
        });
        return;
      }
      _currentStep = "apply";
      _writeStep("apply");
      _renderInPlace();
    } else if (action === "reload-plan") {
      _loadPlan().then(() => _renderInPlace());
    } else if (action === "save-validation") {
      _handleSaveValidation();
    } else if (action === "bulk-approve-sure") {
      _handleBulkApprove("sure");
    } else if (action === "preset-no-alert") {
      _handleBulkApprove("no-alert");
    } else if (action === "preset-platinum-gold") {
      _handleBulkApprove("platinum-gold");
    } else if (action === "apply-now") {
      _handleApplyNow();
    } else if (action === "undo-preview") {
      _onUndoPreview();
    }
    return;
  }

  // Verification filters
  const verifFilterBtn = event.target.closest("[data-traitement-verif-filter]");
  if (verifFilterBtn && container.contains(verifFilterBtn)) {
    _verifFilter = verifFilterBtn.dataset.traitementVerifFilter;
    _renderInPlace();
    return;
  }

  // Fix VAL-3 (2026-05-30) : filtre confiance validation (chips).
  const validationFilterBtn = event.target.closest("[data-traitement-validation-filter]");
  if (validationFilterBtn && container.contains(validationFilterBtn)) {
    // Persister l'etat DOM (checkboxes/years modifies a la main) avant re-render
    // pour ne pas perdre les changements utilisateur (regression UX-03).
    _persistValidationDomState();
    _validationFilter = validationFilterBtn.dataset.traitementValidationFilter || "all";
    _renderInPlace();
    return;
  }

  // Fix VAL-3 (2026-05-30) : tri colonne validation.
  const validationSortBtn = event.target.closest("[data-traitement-validation-sort]");
  if (validationSortBtn && container.contains(validationSortBtn)) {
    _persistValidationDomState();
    const newKey = validationSortBtn.dataset.traitementValidationSort;
    if (_validationSort.key === newKey) {
      _validationSort = { key: newKey, dir: _validationSort.dir === "asc" ? "desc" : "asc" };
    } else {
      _validationSort = { key: newKey, dir: "asc" };
    }
    _renderInPlace();
    return;
  }

  // Verification actions (rescan / rename / ignore)
  const verifActionBtn = event.target.closest("[data-traitement-verif-action]");
  if (verifActionBtn && container.contains(verifActionBtn)) {
    const action = verifActionBtn.dataset.traitementVerifAction;
    const rowId = verifActionBtn.dataset.rowId;
    const runId = _runInfo?.runId;
    if (!runId || !rowId) return;
    if (action === "rescan") {
      apiPost("run/rescan_row", { run_id: runId, row_id: rowId }, { signal: _signal() })
        .then((res) => {
          if (res?.data?.ok !== false) {
            showToast({ type: "success", text: "Ligne re-scannée." });
            return _loadPlan().then(() => _renderInPlace());
          }
          showToast({ type: "error", text: "Échec du re-scan." });
        })
        .catch(() => showToast({ type: "error", text: "Erreur lors du re-scan." }));
    } else if (action === "rename") {
      renderFilmDetail({ mode: "C", rowId, runId });
    } else if (action === "ignore") {
      apiPost("run/mark_alert_ignored", { run_id: runId, row_id: rowId }, { signal: _signal() })
        .then((res) => {
          if (res?.data?.ok !== false) {
            showToast({ type: "info", text: "Alerte ignorée." });
            return _loadPlan().then(() => _renderInPlace());
          }
          showToast({ type: "error", text: "Échec de l'ignorance." });
        })
        .catch(() => showToast({ type: "error", text: "Erreur lors de l'ignorance." }));
    }
    return;
  }

  // Validation inspect (œil) + toggle-reasons (VAL-3)
  const validationActionBtn = event.target.closest("[data-traitement-validation-action]");
  if (validationActionBtn && container.contains(validationActionBtn)) {
    const action = validationActionBtn.dataset.traitementValidationAction;
    const rowId = validationActionBtn.dataset.rowId;
    const runId = _runInfo?.runId;
    if (action === "inspect" && runId && rowId) {
      renderFilmDetail({ mode: "C", rowId, runId });
    } else if (action === "toggle-reasons" && rowId) {
      // Fix VAL-3 (2026-05-30) : ouvrir/fermer la ligne de details.
      _persistValidationDomState();
      if (_validationExpanded.has(rowId)) {
        _validationExpanded.delete(rowId);
      } else {
        _validationExpanded.add(rowId);
      }
      _renderInPlace();
    }
    return;
  }
}

function _onContainerChange(event) {
  const container = _activeContainer;
  if (!container) return;

  // Scan options (checkbox + range)
  const scanInput = event.target.closest("[data-scan-opt]");
  if (scanInput && container.contains(scanInput)) {
    const key = scanInput.dataset.scanOpt;
    if (scanInput.type === "checkbox") {
      _scanOptions[key] = scanInput.checked;
    } else if (scanInput.type === "range") {
      _scanOptions[key] = Number(scanInput.value);
      const lbl = container.querySelector("[data-scan-parallelism-label]");
      if (lbl) lbl.textContent = String(_scanOptions[key]);
    }
    return;
  }

  // Apply options
  const applyInput = event.target.closest("[data-apply-opt]");
  if (applyInput && container.contains(applyInput)) {
    _applyOptions[applyInput.dataset.applyOpt] = applyInput.checked;
    _renderInPlace();
    return;
  }
}

// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-02 : detecte si l'etat
// des checkboxes / annees diverge du `decision` cote serveur (_validationPlan).
// - checkbox cochee = decision OK (approuve), non cochee = REJECT.
// - year input value differente du proposed_year initial = modifie.
// Renvoie true si AU MOINS une ligne diverge -> proposer la sauvegarde.
function _hasUnsavedValidationDecisions() {
  if (!_activeContainer) return false;
  const rows = (_validationPlan && _validationPlan.rows) || [];
  if (rows.length === 0) return false;
  const rowsById = new Map(rows.map((r) => [String(r.row_id || ""), r]));
  const checks = _activeContainer.querySelectorAll("[data-traitement-validation-check]");
  // Si la vue Validation n'a jamais ete montee (aucune checkbox), pas de
  // divergence possible : on retourne false (laisse passer la transition).
  if (checks.length === 0) return false;
  for (const cb of checks) {
    const rowId = String(cb.dataset.rowId || "");
    const row = rowsById.get(rowId);
    if (!row) continue;
    // _renderValidationStep coche par defaut si confidence >= CONF_HIGH.
    // VN-C.1 (batch 2) : seuil 85 -> getConfidenceThresholdsSync().high.
    let defaultChecked;
    if (row.decision === "OK" || row.decision === "APPROVED") defaultChecked = true;
    else if (row.decision === "REJECT" || row.decision === "REJECTED") defaultChecked = false;
    else defaultChecked = Number(row.confidence || 0) >= getConfidenceThresholdsSync().high;
    if (cb.checked !== defaultChecked) return true;
    // Annee : compare l'input avec proposed_year.
    const yearInput = _activeContainer.querySelector(`.traitement-validation-year-input[data-row-id="${rowId}"]`);
    if (yearInput) {
      const currentYear = Number(yearInput.value) || null;
      const originalYear = Number(row.proposed_year) || null;
      if (currentYear !== originalYear) return true;
    }
  }
  return false;
}

// Fix Vague G Fix 4 helper : lit le nombre de doublons en attente depuis le DOM
// du mount doublons (état interne du module non exporté). Fallback à 0 si la
// vue Doublons n'a jamais été montée ou si le selector n'est pas trouvé.
function _readDoublonsPendingFromDom() {
  if (!_activeContainer) return 0;
  const mount = _activeContainer.querySelector("#traitement-doublons-mount");
  if (!mount) return 0;
  // doublons.js rend "<strong>${pendingCount}</strong> en attente" dans le header.
  const candidates = mount.querySelectorAll("strong");
  for (const el of candidates) {
    const next = (el.nextSibling && el.nextSibling.textContent) || "";
    if (next.includes("en attente")) {
      const n = Number((el.textContent || "0").replace(/[^\d]/g, ""));
      if (Number.isFinite(n)) return n;
    }
  }
  return 0;
}

function _bindEvents(container) {
  // Idempotent : un seul jeu de listeners par mount, attachés au container parent.
  // _renderInPlace() peut réécrire innerHTML sans recréer les listeners car ils
  // vivent sur le container, pas sur les boutons enfants.
  if (_eventsBound) return;
  if (!container) return;
  container.addEventListener("click", _onContainerClick);
  container.addEventListener("change", _onContainerChange);
  _eventsBound = true;
}

async function _handleSaveValidation() {
  if (!_runInfo?.runId) return;
  const decisions = _buildDecisions();
  try {
    const res = await apiPost("run/save_validation", {
      run_id: _runInfo.runId,
      decisions,
    }, { signal: _signal() });
    if (res?.data?.ok !== false) {
      showToast({ type: "success", text: "Décisions sauvegardées." });
      await _loadRunInfo();
      _renderInPlace();
    } else {
      showToast({ type: "error", text: "Échec de la sauvegarde." });
    }
  } catch {
    showToast({ type: "error", text: "Erreur lors de la sauvegarde." });
  }
}

/* --- Hash change handling --- */

function _onHashChange() {
  const next = _readStep();
  const nextRun = _readTargetRunId();
  let changed = false;
  if (next !== _currentStep) {
    _currentStep = next;
    changed = true;
  }
  if (nextRun !== _targetRunId) {
    _targetRunId = nextRun;
    changed = true;
    // Recharge les données du nouveau run cible.
    if (_activeContainer) {
      // Fix audit 2026-05-24 : _rerender n'existe pas (ReferenceError silencieux
      // a chaque hashchange -> back/forward navigateur cassé). Utiliser
      // _renderInPlace() qui re-rend a partir du container actif.
      _loadRunInfo().then(() => {
        if (_activeContainer) _renderInPlace();
      });
      return;
    }
  }
  if (changed && _activeContainer) {
    _renderInPlace();
  }
}

/* --- Lifecycle --- */

export async function initTraitement(container) {
  if (!container) return;
  _activeContainer = container;
  _currentStep = _readStep();
  _targetRunId = _readTargetRunId();
  // Phase 5 : si fragment #run-XXX présent sans step, aller direct à "validation".
  if (_targetRunId && _currentStep === "analyse") {
    _currentStep = "validation";
  }
  _logsState = { items: [], nextIndex: 0 };
  // Fix audit 2026-05-24 : nouveau AbortController par mount, abort au
  // unmount pour interrompre tous les apiPost en vol (cf _signal()).
  _abortController = new AbortController();
  // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : reset flag binding au mount
  // pour qu'un re-mount (navigation back/forward) attache à nouveau les
  // listeners sur le nouveau container.
  _eventsBound = false;
  // VN-C.1 (batch 2) : prefetch des seuils confidence (cache module-level
  // dans core/api.js). Lance en // — pas critique de l'attendre, le
  // fallback sync renvoie les DEFAULTS si pas encore arrive.
  fetchConfidenceThresholds().catch(() => { /* fallback DEFAULTS */ });
  container.innerHTML = _renderTraitement();
  window.addEventListener("hashchange", _onHashChange);
  await _loadRunInfo();
  await _loadRunStatus();
  await _loadPlan();
  _renderInPlace();
  // Demarre le polling si on a un run actif
  if (_runInfo?.runId) {
    _startPolling();
    _startUndoCountdown();
  }
}

export function unmountTraitement() {
  _stopPolling();
  _stopUndoCountdown();
  // Fix audit 2026-05-24 : abort tous les apiPost en vol avant remise à null
  // du container (sinon le .then() qui suit appelle _renderInPlace sur un
  // _activeContainer null -> NPE silencieux + state set sur ancien run).
  if (_abortController) {
    try { _abortController.abort(); } catch { /* noop */ }
    _abortController = null;
  }
  if (_doublonsMounted) {
    unmountDoublons();
    _doublonsMounted = false;
  }
  // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : retirer les listeners délégués
  // du container avant de le détacher. removeEventListener avec la même référence
  // de fonction module-level fonctionne car les handlers sont stables.
  if (_activeContainer && _eventsBound) {
    _activeContainer.removeEventListener("click", _onContainerClick);
    _activeContainer.removeEventListener("change", _onContainerChange);
  }
  _eventsBound = false;
  window.removeEventListener("hashchange", _onHashChange);
  _currentStep = "analyse";
  _runInfo = null;
  _targetRunId = null;
  _runStatus = null;
  _activeContainer = null;
  _validationPlan = null;
  // Fix VAL-3 (2026-05-30) : reset filtre/tri/expand au unmount pour eviter
  // qu'un etat "filtre=high" persiste si l'utilisateur revient plus tard.
  _validationFilter = "all";
  _validationSort = { key: "confidence", dir: "desc" };
  _validationExpanded = new Set();
  // Fix APPLY-2 (2026-05-30) : reset etat apply.
  _applyStatus = null;
  _logsState = { items: [], nextIndex: 0 };
  void navigateTo;
}
