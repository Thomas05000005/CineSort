/* views/logs.js — Journaux (logs live + historique runs + exports) */

import { $, escapeHtml } from "../core/dom.js";
import { apiGet, apiPost } from "../core/api.js";
import { startPolling, stopPolling } from "../core/state.js";
import { tableHtml, attachSort } from "../components/table.js";
import { badgeHtml } from "../components/badge.js";
import { fmtDate as _fmtDate, fmtDuration as _fmtDuration } from "../core/format.js";
import { skeletonLinesHtml } from "../components/skeleton.js";
import { getNavSignal, isAbortError } from "../core/nav-abort.js";
import { t } from "../core/i18n.js";

/* --- Etat local ----------------------------------------------- */

let _runId = null;
let _lastLogIndex = 0;
let _runs = [];
let _selectedRunId = null;
let _mode = "live"; // "live" ou "history"

/* --- Colonnes table runs -------------------------------------- */

function _runColumns() {
  return [
    { key: "started_at", label: t("legacy.logs.col_date"), sortable: true, render: v => _fmtDate(v) },
    { key: "run_id", label: t("legacy.logs.col_run_id"), sortable: true, render: v => `<span class="text-mono">${escapeHtml(String(v || "").slice(0, 18))}</span>` },
    { key: "total_rows", label: t("legacy.logs.col_movies"), sortable: true },
    { key: "avg_score", label: t("legacy.logs.col_score"), sortable: true, render: v => v ? `${Math.round(Number(v))}` : "—" },
    { key: "status", label: t("legacy.logs.col_status"), sortable: true, render: v => badgeHtml("status", v || "analysis") },
    { key: "duration_s", label: t("legacy.logs.col_duration"), sortable: true, render: v => _fmtDuration(v) },
  ];
}

/* --- Point d'entree ------------------------------------------- */

export function initLogs() {
  _runId = null;
  _lastLogIndex = 0;
  _selectedRunId = null;
  _load();
}

/* --- Chargement ----------------------------------------------- */

async function _load() {
  const container = $("logsContent");
  if (!container) return;
  container.innerHTML = skeletonLinesHtml(6);

  // Detecter run actif + charger historique en parallele.
  // Audit ID-ROB-002 : Promise.allSettled pour qu'un endpoint en echec
  // ne casse pas tout l'affichage logs (live et historique sont independants).
  // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur navigate ailleurs.
  const navSig = getNavSignal();
  const labels = ["/api/health", "run/get_global_stats"];
  const results = await Promise.allSettled([
    apiGet("/api/health"),
    apiPost("run/get_global_stats", { limit_runs: 50 }, { signal: navSig }),
  ]);
  const _val = (r) => (r && r.status === "fulfilled" && r.value ? r.value.data || {} : {});
  const [healthData, statsData] = results.map(_val);
  const failed = labels.filter((_, i) => results[i].status !== "fulfilled" && !isAbortError(results[i].reason));
  if (failed.length > 0) console.warn("[logs] endpoints en echec:", failed);

  _runId = healthData.active_run_id || null;
  _runs = statsData.runs_summary || [];
  if (!_selectedRunId && _runs.length > 0) _selectedRunId = _runs[0].run_id;

  _render(container);
}

/* --- Rendu principal ------------------------------------------ */

function _render(container) {
  let html = "";

  // Toggle live / historique
  html += `<div class="flex gap-2 mb-4">
    <button class="btn btn--compact${_mode === "live" ? " active" : ""}" id="logModeLive">${escapeHtml(t("legacy.logs.mode_live"))}</button>
    <button class="btn btn--compact${_mode === "history" ? " active" : ""}" id="logModeHistory">${escapeHtml(t("legacy.logs.mode_history"))}</button>
  </div>`;

  if (_mode === "live") {
    html += _renderLiveSection();
  } else {
    html += _renderHistorySection();
  }

  container.innerHTML = html;
  _hookEvents(container);

  // Demarrer le polling si run actif et mode live
  if (_mode === "live" && _runId) {
    _lastLogIndex = 0;
    startPolling("logs-live", _pollLogs, 2000);
  }
}

/* --- Section Logs en direct ----------------------------------- */

function _renderLiveSection() {
  let html = "";
  if (_runId) {
    html += `<div class="flex justify-between items-center mb-4">
      <h3>${escapeHtml(t("legacy.logs.current_run_label"))} <span class="text-accent">${escapeHtml(_runId)}</span></h3>
      <button id="btnLogsCancel" class="btn btn-danger btn--compact">${escapeHtml(t("legacy.logs.btn_cancel"))}</button>
    </div>`;
    html += '<div id="logsProgressBar" class="progress-bar"><div class="progress-fill" style="--progress:0"></div></div>';
    html += '<p id="logsProgressText" class="text-muted mt-2"></p>';
  } else {
    html += `<div class="card"><p class="text-muted">${escapeHtml(t("legacy.logs.no_active_run"))}</p></div>`;
  }
  html += '<div id="logsBox" class="logs-box mt-4" style="max-height:400px;overflow-y:auto"></div>';
  return html;
}

/* --- Section Historique runs ---------------------------------- */

function _renderHistorySection() {
  let html = "";

  // Export pour le run selectionne
  html += `<div class="card mb-4">
    <div class="flex gap-2 items-center flex-wrap">
      <span>${escapeHtml(t("legacy.logs.selected_run_label"))} <strong id="logSelectedLabel">${_selectedRunId ? escapeHtml(String(_selectedRunId).slice(0, 20)) : escapeHtml(t("legacy.logs.none"))}</strong></span>
      <button class="btn btn--compact" data-export="json">JSON</button>
      <button class="btn btn--compact" data-export="csv">CSV</button>
      <button class="btn btn--compact" data-export="html">HTML</button>
      <button class="btn btn--compact" id="btnLogExportNfo">${escapeHtml(t("legacy.logs.btn_export_nfo"))}</button>
      <span id="logExportMsg" class="status-msg"></span>
    </div>
  </div>`;

  // Table runs
  html += `<div id="logRunsTable" class="mb-4"></div>`;

  return html;
}

/* --- Evenements ----------------------------------------------- */

function _hookEvents(container) {
  // Toggle mode
  $("logModeLive")?.addEventListener("click", () => { _mode = "live"; stopPolling("logs-live"); _render(container); });
  $("logModeHistory")?.addEventListener("click", () => { _mode = "history"; stopPolling("logs-live"); _render(container); });

  // Annuler run
  $("btnLogsCancel")?.addEventListener("click", async () => {
    const btn = $("btnLogsCancel");
    if (btn) btn.disabled = true;
    try { await apiPost("run/cancel_run", { run_id: _runId }); } catch {}
    finally { if (btn) btn.disabled = false; }
  });

  // Table runs (mode historique)
  if (_mode === "history") {
    const tableEl = $("logRunsTable");
    if (tableEl && _runs.length > 0) {
      const cols = _runColumns();
      tableEl.innerHTML = tableHtml({ columns: cols, rows: _runs, id: "logsRunsTbl", clickable: true, emptyText: t("legacy.logs.no_runs") });
      attachSort("logsRunsTbl", _runs, () => { tableEl.innerHTML = tableHtml({ columns: cols, rows: _runs, id: "logsRunsTbl", clickable: true }); });

      // Clic sur un run → selectionner
      tableEl.querySelectorAll("tr[data-row-idx]").forEach(tr => {
        tr.addEventListener("click", () => {
          const idx = Number(tr.dataset.rowIdx);
          const run = _runs[idx];
          if (run) {
            _selectedRunId = run.run_id;
            const label = $("logSelectedLabel");
            if (label) label.textContent = String(run.run_id).slice(0, 20);
          }
        });
      });
    }

    // Export buttons
    container.querySelectorAll("[data-export]").forEach(btn => {
      btn.addEventListener("click", () => _exportRun(btn.dataset.export));
    });
    $("btnLogExportNfo")?.addEventListener("click", _exportNfo);
  }
}

/* --- Export ---------------------------------------------------- */

async function _exportRun(fmt) {
  if (!_selectedRunId) return;
  const msg = $("logExportMsg");
  if (msg) { msg.textContent = t("legacy.logs.export_running"); msg.className = "status-msg"; }
  try {
    const res = await apiPost("run/export_run_report", { run_id: _selectedRunId, fmt });
    if (res.data?.content) {
      const blob = new Blob([typeof res.data.content === "string" ? res.data.content : JSON.stringify(res.data.content, null, 2)],
        { type: fmt === "json" ? "application/json" : fmt === "csv" ? "text/csv" : "text/html" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${_selectedRunId}.${fmt}`; a.click();
      URL.revokeObjectURL(url);
      if (msg) { msg.textContent = t("legacy.logs.export_ok"); msg.className = "status-msg success"; }
    } else {
      if (msg) { msg.textContent = res.data?.message || t("legacy.logs.export_no_data"); msg.className = "status-msg error"; }
    }
  } catch { if (msg) { msg.textContent = t("legacy.logs.network_error"); msg.className = "status-msg error"; } }
}

async function _exportNfo() {
  if (!_selectedRunId) return;
  const msg = $("logExportMsg");
  try {
    const res = await apiPost("run/export_run_nfo", { run_id: _selectedRunId, overwrite: false, dry_run: false });
    if (msg) msg.textContent = res.data?.message || t("legacy.logs.nfo_created", { count: res.data?.created || 0 });
  } catch { if (msg) { msg.textContent = t("legacy.logs.generic_error"); msg.className = "status-msg error"; } }
}

/* --- Polling logs live ---------------------------------------- */

async function _pollLogs() {
  if (!_runId) return;
  try {
    const res = await apiPost("run/get_status", { run_id: _runId, last_log_index: _lastLogIndex });
    const d = res.data || {};

    const progressText = $("logsProgressText");
    const progressFill = document.querySelector("#logsProgressBar .progress-fill");
    const total = d.total || 0, idx = d.idx || 0;
    if (progressText) {
      if (total > 0) {
        const pct = Math.round((idx / total) * 100);
        progressText.textContent = `${idx}/${total} (${pct}%)${d.eta_s > 0 ? ` — ETA ${_fmtDuration(d.eta_s)}` : ""}`;
        // B8 (fin sprint 4) : --progress (0..1) -> scaleX (compositor only, no reflow).
        if (progressFill) { progressFill.style.setProperty("--progress", String(pct / 100)); progressFill.classList.remove("progress-fill--shimmer"); }
      } else {
        progressText.textContent = t("legacy.logs.scanning", { count: idx });
        if (progressFill) progressFill.classList.add("progress-fill--shimmer");
      }
    }

    const logsBox = $("logsBox");
    if (logsBox && Array.isArray(d.logs) && d.logs.length > 0) {
      for (const entry of d.logs) {
        const line = document.createElement("div");
        line.className = "log-line";
        const level = String(entry.level || "INFO").toUpperCase();
        if (level === "ERROR") line.classList.add("log-error");
        else if (level === "WARN" || level === "WARNING") line.classList.add("log-warn");
        line.textContent = `[${entry.ts || ""}] ${level}: ${entry.msg || ""}`;
        logsBox.appendChild(line);
      }
      logsBox.scrollTop = logsBox.scrollHeight;
    }
    if (d.next_log_index) _lastLogIndex = d.next_log_index;

    if (d.done || (!d.running && !d.error)) {
      _runId = null;
      stopPolling("logs-live");
      if (logsBox) {
        const end = document.createElement("div");
        end.className = "log-line log-end";
        end.textContent = t("legacy.logs.run_finished");
        logsBox.appendChild(end);
        logsBox.scrollTop = logsBox.scrollHeight;
      }
    }
  } catch { /* polling silencieux */ }
}

/* _fmtDuration / _fmtDate importes depuis core/format.js (voir en-tete du fichier). */
