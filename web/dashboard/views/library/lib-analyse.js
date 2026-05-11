/* lib-analyse.js — Section 1 : Analyse (scan, progress, journal) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiGet, apiPost } from "../../core/api.js";
import { startPolling, stopPolling } from "../../core/state.js";

let _state = null;
let _activeRunId = null;
let _lastLogIndex = 0;
let _maxLogLines = 50;
// BUG 4 : tracker le total precedent pour distinguer decouverte vs analyse
let _scanLastTotal = 0;

/* --- Point d'entree ------------------------------------------- */

export function initAnalyse(libState) {
  _state = libState;
  const el = $("libAnalyseContent");
  if (!el) return;
  _render(el);
}

export function destroyAnalyse() {
  stopPolling("lib-scan");
}

/* --- Rendu ---------------------------------------------------- */

function _render(el) {
  const hasRun = !!_state.runId;
  el.innerHTML = `
    <div class="card">
      <div class="flex gap-2 items-center">
        <button id="libBtnStartScan" class="btn btn-primary" data-testid="lib-analyse-btn-scan">Lancer l'analyse</button>
        <button id="libBtnCancelScan" class="btn" style="display:none" data-testid="lib-analyse-btn-cancel">Annuler</button>
        <span id="libScanMsg" class="status-msg" data-testid="lib-analyse-msg"></span>
      </div>
      <div id="libScanProgress" class="mt-4" style="display:none" data-testid="lib-analyse-progress">
        <div class="progress-bar" id="libProgressBar"><div class="progress-fill"></div></div>
        <div class="flex justify-between mt-2 font-sm text-secondary">
          <span id="libProgText">0/0</span>
          <span id="libProgSpeed">—</span>
          <span>ETA <span id="libProgEta">—</span></span>
        </div>
        <div class="font-xs text-muted mt-1 truncate" id="libProgCurrent">—</div>
      </div>
      <div id="libScanLogs" class="mt-4" style="display:none">
        <div class="logs-box" id="libLogsBox" style="max-height:200px;overflow-y:auto"></div>
      </div>
      <div id="libScanDone" class="mt-4" style="display:none">
        <button id="libBtnLoadResults" class="btn btn-primary" data-testid="lib-analyse-btn-load">Charger les résultats</button>
      </div>
    </div>
    ${!_state.settings.ffprobe_path && !_state.settings.mediainfo_path ? `
    <div class="card card--banner mt-4" id="libProbeInstallBanner">
      <span class="text-warning" id="libProbeInstallMsg">Outils d'analyse vidéo manquants.</span>
      <button id="libBtnAutoInstall" class="btn btn-primary btn--compact">Installer automatiquement</button>
    </div>` : ""}
  `;
  _hookEvents();

  // Si un run est actif, demarrer le polling
  if (_state.runId) {
    _checkActiveRun();
  }
}

/* --- Evenements ----------------------------------------------- */

function _hookEvents() {
  const btnStart = $("libBtnStartScan");
  const btnCancel = $("libBtnCancelScan");
  const btnLoad = $("libBtnLoadResults");
  const btnInstall = $("libBtnAutoInstall");

  if (btnStart) {
    btnStart.addEventListener("click", async () => {
      btnStart.disabled = true;
      _showMsg("Démarrage de l'analyse...");
      try {
        const res = await apiPost("start_plan", { settings: _state.settings });
        if (res.data?.ok) {
          _activeRunId = res.data.run_id || null;
          _state.runId = _activeRunId;
          if ($("libRunLabel")) $("libRunLabel").textContent = _activeRunId || "—";
          _showMsg(`Analyse démarrée : ${escapeHtml(_activeRunId || "")}`);
          _startScanUI();
          _startPolling();
        } else {
          _showMsg(res.data?.message || "Échec du démarrage.", true);
          btnStart.disabled = false;
        }
      } catch { _showMsg("Erreur réseau.", true); btnStart.disabled = false; }
    });
  }

  if (btnCancel) {
    btnCancel.addEventListener("click", async () => {
      btnCancel.disabled = true;
      try { await apiPost("cancel_run", { run_id: _activeRunId }); _showMsg("Annulation demandée."); }
      catch { /* ignore */ }
      finally { btnCancel.disabled = false; }
    });
  }

  if (btnLoad) {
    btnLoad.addEventListener("click", () => {
      // Scroller vers la section Validation
      const target = document.querySelector('[data-lib-section="validation"]');
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  if (btnInstall) {
    btnInstall.addEventListener("click", async () => {
      btnInstall.disabled = true;
      const msg = $("libProbeInstallMsg");
      if (msg) msg.textContent = "Installation en cours...";
      try {
        const res = await apiPost("auto_install_probe_tools", {});
        if (res.data?.ok) {
          if (msg) { msg.textContent = "Outils installés !"; msg.className = "text-success"; }
          const banner = $("libProbeInstallBanner");
          if (banner) setTimeout(() => banner.remove(), 2000);
        } else {
          if (msg) { msg.textContent = "Échec : " + (res.data?.message || "Erreur"); msg.className = "text-danger"; }
          btnInstall.disabled = false;
        }
      } catch {
        if (msg) { msg.textContent = "Erreur réseau."; msg.className = "text-danger"; }
        btnInstall.disabled = false;
      }
    });
  }
}

/* --- Scan UI et polling --------------------------------------- */

async function _checkActiveRun() {
  try {
    const health = await apiGet("/api/health");
    if (health.data?.active_run_id) {
      _activeRunId = health.data.active_run_id;
      _startScanUI();
      _startPolling();
    }
  } catch { /* ignore */ }
}

function _startScanUI() {
  const progress = $("libScanProgress");
  const logs = $("libScanLogs");
  const cancel = $("libBtnCancelScan");
  const start = $("libBtnStartScan");
  if (progress) progress.style.display = "";
  if (logs) logs.style.display = "";
  if (cancel) cancel.style.display = "";
  if (start) start.disabled = true;
}

function _startPolling() {
  _lastLogIndex = 0;
  _scanLastTotal = 0;  // BUG 4 : reset pour le nouveau scan
  startPolling("lib-scan", () => _pollRunStatus(), 2000);
}

async function _pollRunStatus() {
  if (!_activeRunId) return;
  try {
    const res = await apiPost("get_status", { run_id: _activeRunId, last_log_index: _lastLogIndex });
    const d = res.data || {};

    // Barre de progression
    const progressFill = document.querySelector("#libProgressBar .progress-fill");
    const progText = $("libProgText");
    const total = d.total || 0;
    const idx = d.idx || 0;

    // BUG 4 : distinguer decouverte (total qui monte) vs analyse (total stable)
    const totalGrew = total > _scanLastTotal;
    _scanLastTotal = total;
    const inDiscovery = totalGrew || (total > 0 && idx === 0);

    if (inDiscovery || total === 0) {
      if (progText) progText.textContent = total > 0
        ? `Découverte en cours... ${total} dossiers trouvés`
        : `${idx} films trouvés...`;
      if (progressFill) progressFill.classList.add("progress-fill--shimmer");
    } else {
      const pct = Math.round((idx / total) * 100);
      if (progText) progText.textContent = `Analyse : ${idx}/${total} (${pct}%)`;
      if (progressFill) { progressFill.style.width = `${pct}%`; progressFill.classList.remove("progress-fill--shimmer"); }
    }

    if ($("libProgSpeed")) $("libProgSpeed").textContent = d.speed ? `${Number(d.speed).toFixed(1)} doss./s` : "—";
    if ($("libProgEta")) $("libProgEta").textContent = (!inDiscovery && d.eta_s > 0) ? _fmtDuration(d.eta_s) : "—";
    if ($("libProgCurrent")) { const c = $("libProgCurrent"); c.textContent = "📂 " + (d.current || "—"); c.title = d.current || ""; }

    // Logs
    if (Array.isArray(d.logs) && d.logs.length > 0) {
      const box = $("libLogsBox");
      if (box) {
        for (const entry of d.logs) {
          const line = document.createElement("div");
          line.className = "log-line";
          const level = String(entry.level || "INFO").toUpperCase();
          if (level === "ERROR") line.classList.add("log-error");
          else if (level === "WARN" || level === "WARNING") line.classList.add("log-warn");
          line.textContent = `[${entry.ts || ""}] ${level}: ${entry.msg || ""}`;
          box.appendChild(line);
          // Limiter a _maxLogLines
          while (box.children.length > _maxLogLines) box.removeChild(box.firstChild);
        }
        box.scrollTop = box.scrollHeight;
      }
    }
    if (d.next_log_index) _lastLogIndex = d.next_log_index;

    // Run termine
    if (d.done || d.error || (!d.running && !d.error)) {
      stopPolling("lib-scan");
      const finishedRunId = _activeRunId;
      _activeRunId = null;
      const done = $("libScanDone");
      const cancel = $("libBtnCancelScan");
      const start = $("libBtnStartScan");
      if (done) done.style.display = "";
      if (cancel) cancel.style.display = "none";
      if (start) start.disabled = false;
      if (d.error) _showMsg(`Erreur : ${d.error}`, true);
      else _showMsg(`Analyse terminée. ${total || idx} films traités.`);
      // C2 : rafraichir le state library avec le nouveau runId + les stats globales
      // pour que les sections Verification / Validation / Apply voient le nouveau run.
      try {
        if (_state && finishedRunId) {
          _state.runId = finishedRunId;
        }
        const statsRes = await apiPost("get_global_stats", { limit_runs: 1 });
        if (statsRes?.data?.recent_runs?.[0]?.run_id && _state) {
          _state.runId = statsRes.data.recent_runs[0].run_id;
        }
      } catch { /* refresh non bloquant */ }
    }
  } catch { /* polling silencieux */ }
}

/* --- Helpers -------------------------------------------------- */

function _showMsg(text, isError = false) {
  const el = $("libScanMsg");
  if (!el) return;
  el.textContent = text;
  el.className = "status-msg" + (isError ? " error" : " success");
}

function _fmtDuration(s) {
  if (!s || s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}
