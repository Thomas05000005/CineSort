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
import { apiPost } from "../core/api.js";
import { navigateTo } from "../core/router.js";
import { dangerConfirmModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";
import { formatRelative, formatDuration } from "../core/format.js";
import { initDoublons, unmountDoublons } from "./doublons.js";

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

let _currentStep = "analyse";
let _runInfo = null;
let _runStatus = null; // { status, idx, total, eta_s, speed, logs }
let _loading = false;
let _targetRunId = null; // Phase 5 spec §2 : fragment #run-XXX = run cible à afficher.
let _pollTimer = null;
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
let _verifFilter = "all";
let _validationPlan = null; // { rows: [...] }
let _applyOptions = { dry_run: true, export_csv: false, sync_jellyfin: false, quarantine: false };

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
    const params = targetId ? { run_id: targetId } : { run_id_or: "latest" };
    const res = await apiPost("get_dashboard", params);
    if (!res || res.ok === false) {
    const res = await apiPost("get_dashboard", { run_id_or: "latest" });
    if (!res || res.data?.ok === false) {
      _runInfo = null;
      return;
    }
    const data = res.data || res;
    const k = data.kpis || {};
    const history = Array.isArray(data.runs_history) ? data.runs_history : [];
    const current = history.find((r) => r.run_id === data.run_id) || history[0] || {};
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
    });
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
  const interval = _currentStep === "analyse" ? POLL_INTERVAL_ANALYSE : POLL_INTERVAL_RUNNING;
  _pollTimer = setInterval(async () => {
    if (!_runStatus || !_runStatus.running) {
      // Plus rien a poll si le run est termine, on continue tout de meme
      // pour rafraichir get_dashboard (utile apres apply)
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
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="save">💾 Sauvegarder</button>
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
            <div class="traitement-scan-progress-fill" style="width: ${progressPct}%"></div>
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

  const tableRows = filtered.slice(0, 50).map((r) => {
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
      `}

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="go-validation">→ Continuer vers Validation</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="reload-plan">↻ Re-vérifier</button>
      </div>
    </section>
  `;
}

/* --- Etape 3 : Validation (spec §3.3) --- */

function _renderValidationStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  const pending = rows.filter((r) => !r.decision || r.decision === "PENDING");
  const sureCount = pending.filter((r) => Number(r.confidence || 0) >= 90).length;

  const tableRows = pending.slice(0, 100).map((r) => {
    const conf = Number(r.confidence || 0);
    const confLabel = conf >= 85 ? "Haute" : (conf >= 60 ? "Moyenne" : "Basse");
    const confCls = conf >= 85 ? "is-high" : (conf >= 60 ? "is-mid" : "is-low");
    return `
      <tr data-row-id="${escapeHtml(r.row_id || "")}">
        <td class="traitement-validation-check">
          <input type="checkbox" data-traitement-validation-check data-row-id="${escapeHtml(r.row_id || "")}" ${conf >= 85 ? "checked" : ""}>
        </td>
        <td class="traitement-validation-confidence ${confCls}">${escapeHtml(confLabel)}</td>
        <td class="traitement-validation-title">${escapeHtml(r.proposed_title || "—")}</td>
        <td class="traitement-validation-year">
          <input type="number" min="1900" max="2099" value="${escapeHtml(String(r.proposed_year || ""))}" class="traitement-validation-year-input" data-row-id="${escapeHtml(r.row_id || "")}">
        </td>
        <td class="traitement-validation-score">${escapeHtml(String(r.score ?? "—"))}</td>
        <td class="traitement-validation-actions">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-traitement-validation-action="inspect" data-row-id="${escapeHtml(r.row_id || "")}">👁</button>
        </td>
      </tr>
    `;
  }).join("");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 3 — Validation</h2>
      <p class="traitement-panel-desc">Approuver / rejeter les propositions de classification</p>
      ${_renderStepStats("validation")}

      <div class="traitement-validation-bulk">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="bulk-approve-sure">
          ✓ Tout approuver les sûrs (${sureCount})
        </button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="preset-no-alert">
          Approuver sans alerte
        </button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="preset-reject-reject">
          Rejeter tier Reject
        </button>
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
              <th>Confiance</th>
              <th>Titre</th>
              <th>Année</th>
              <th>Score</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
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

/* --- Etape 5 : Apply (spec §3.5) --- */

function _renderApplyStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  const approved = rows.filter((r) => r.decision === "ok" || r.decision === "approved" || Number(r.confidence || 0) >= 85);
  const renames = approved.length;
  const moves = (_runInfo?.duplicatesGroups || 0) * 2;
  const deletions = 0; // placeholder pour reject deletions

  const preview = approved.slice(0, 3).map((r) => `
    <li>
      <code class="traitement-apply-before">${escapeHtml(r.video || r.path || r.proposed_title || "—")}</code>
      <span class="traitement-apply-arrow">→</span>
      <code class="traitement-apply-after">${escapeHtml(r.proposed_title || "—")} (${escapeHtml(String(r.proposed_year || ""))})</code>
    </li>
  `).join("");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 5 — Application</h2>
      <p class="traitement-panel-desc">Renommage et déplacement sur disque</p>
      ${_renderStepStats("apply")}

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
    </section>
  `;
}

/* --- Step panel routing --- */

function _renderStepPanel(stepId) {
  if (_loading) {
    return `
      <section class="traitement-panel">
        <p class="traitement-placeholder">Chargement de l'état du run…</p>
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
  return `
    <section class="traitement-view">
      <header class="traitement-header">
        <div class="traitement-header-row">
          <h1 class="traitement-title">Traitement</h1>
        </div>
        <p class="traitement-subtitle">Workflow d'un scan : analyse → validation → apply</p>
      </header>
      ${_renderHeaderRun()}
      ${_renderBreadcrumb(_currentStep)}
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
    if (mount && !_doublonsMounted) {
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
      const res = await apiPost("run/pause_run", { run_id: runId });
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
      const res = await apiPost("run/resume_run", { run_id: runId });
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
      const res = await apiPost("run/save_for_later", { run_id: runId });
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
          const res = await apiPost("run/cancel_run", { run_id: runId });
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
    const res = await apiPost("run/start_plan", { settings });
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
    const res = await apiPost("run/get_plan", { run_id: _runInfo.runId });
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
  let approvedCount = 0;
  const rows = _validationPlan.rows;
  const targetIds = new Set();
  rows.forEach((r) => {
    const conf = Number(r.confidence || 0);
    const flags = String(r.warning_flags || "");
    let match = false;
    if (filter === "sure") match = conf >= 90;
    else if (filter === "no-alert") match = !flags;
    else if (filter === "platinum-gold") match = ["Platinum", "Gold"].includes(String(r.tier || ""));
    if (match) {
      targetIds.add(r.row_id);
      approvedCount += 1;
    }
  });

  // Mise a jour locale + UI
  _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
    if (targetIds.has(cb.dataset.rowId)) cb.checked = true;
  });

  // Snapshot pour Undo
  const snapshot = {};
  rows.forEach((r) => { snapshot[r.row_id] = r.decision; });

  showToast({
    type: "success",
    text: `${approvedCount} films approuvés.`,
    duration: 5000,
  });

  // L'undo via toast est un placeholder : on l'expose comme bouton dans le toast,
  // mais le composant showToast actuel n'a pas d'API onAction. On utilise une
  // sauvegarde du snapshot accessible 5s via fenetre globale.
  window._traitementLastBulkSnapshot = snapshot;
  setTimeout(() => { delete window._traitementLastBulkSnapshot; }, 5000);
}

async function _handleApplyNow() {
  if (!_runInfo?.runId) return;
  const decisions = _buildDecisions();
  const opCount = Object.values(decisions).filter((d) => d.ok).length;

  if (_applyOptions.dry_run) {
    // Dry-run direct sans confirmation
    try {
      const res = await apiPost("apply", {
        run_id: _runInfo.runId,
        decisions,
        dry_run: true,
        quarantine_unapproved: _applyOptions.quarantine,
      });
      if (res?.data?.ok !== false) {
        showToast({ type: "success", text: "Dry-run terminé. Aucun fichier modifié.", duration: 5000 });
        await _loadRunInfo();
        _renderInPlace();
      } else {
        showToast({ type: "error", text: "Échec du dry-run." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors du dry-run." });
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
    consequence: "Les fichiers sur disque seront effectivement modifiés. Réversible via Undo pendant 7 jours après apply.",
    confirmLabel: "✗ Appliquer pour de vrai",
    cancelLabel: "Annuler",
    countdownSeconds: 3,
    onConfirm: async () => {
      try {
        const res = await apiPost("apply", {
          run_id: _runInfo.runId,
          decisions,
          dry_run: false,
          quarantine_unapproved: _applyOptions.quarantine,
        });
        if (res?.data?.ok !== false) {
          showToast({ type: "success", text: "Apply terminé · Undo possible 24h", duration: 7000 });
          await _loadRunInfo();
          _renderInPlace();
        } else {
          showToast({ type: "error", text: "Échec de l'apply." });
        }
      } catch {
        showToast({ type: "error", text: "Erreur lors de l'apply." });
      }
    },
  });
}

/* --- Event binding --- */

function _bindEvents(container) {
  // Breadcrumb
  container.querySelectorAll("[data-traitement-step]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const stepId = btn.dataset.traitementStep;
      _currentStep = stepId;
      _writeStep(stepId);
      _renderInPlace();
    });
  });

  // Copy run ID
  const copyBtn = container.querySelector("[data-traitement-copy-runid]");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      if (!_runInfo?.runId) return;
      try {
        await navigator.clipboard.writeText(_runInfo.runId);
        showToast({ type: "info", text: "Run ID copié dans le presse-papier." });
      } catch {
        /* ignore */
      }
    });
  }

  // Header actions
  container.querySelectorAll("[data-traitement-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.traitementAction;
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
        _currentStep = "doublons";
        _writeStep("doublons");
        _renderInPlace();
      } else if (action === "go-apply") {
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
      } else if (action === "preset-reject-reject") {
        showToast({ type: "info", text: "Rejet tier Reject - non disponible (preset)." });
      } else if (action === "apply-now") {
        _handleApplyNow();
      }
    });
  });

  // Scan options
  container.querySelectorAll("[data-scan-opt]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.scanOpt;
      if (input.type === "checkbox") _scanOptions[key] = input.checked;
      else if (input.type === "range") {
        _scanOptions[key] = Number(input.value);
        const lbl = container.querySelector("[data-scan-parallelism-label]");
        if (lbl) lbl.textContent = String(_scanOptions[key]);
      }
    });
  });

  // Verification filters
  container.querySelectorAll("[data-traitement-verif-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _verifFilter = btn.dataset.traitementVerifFilter;
      _renderInPlace();
    });
  });

  // Apply options
  container.querySelectorAll("[data-apply-opt]").forEach((input) => {
    input.addEventListener("change", () => {
      _applyOptions[input.dataset.applyOpt] = input.checked;
      _renderInPlace();
    });
  });
}

async function _handleSaveValidation() {
  if (!_runInfo?.runId) return;
  const decisions = _buildDecisions();
  try {
    const res = await apiPost("save_validation", {
      run_id: _runInfo.runId,
      decisions,
    });
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
      _loadRunInfo().then(() => {
        if (_activeContainer) _rerender(_activeContainer);
      });
      return;
    }
  }
  if (changed && _activeContainer) {
    _rerender(_activeContainer);
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
  container.innerHTML = _renderTraitement();
  window.addEventListener("hashchange", _onHashChange);
  await _loadRunInfo();
  await _loadRunStatus();
  await _loadPlan();
  _renderInPlace();
  // Demarre le polling si on a un run actif
  if (_runInfo?.runId) {
    _startPolling();
  }
}

export function unmountTraitement() {
  _stopPolling();
  if (_doublonsMounted) {
    unmountDoublons();
    _doublonsMounted = false;
  }
  window.removeEventListener("hashchange", _onHashChange);
  _currentStep = "analyse";
  _runInfo = null;
  _targetRunId = null;
  _runStatus = null;
  _activeContainer = null;
  _validationPlan = null;
  _logsState = { items: [], nextIndex: 0 };
  void navigateTo;
}
