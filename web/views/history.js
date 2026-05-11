/* views/history.js — Historique + exports */

function renderHistoryTable(runs) {
  renderGenericTable("historyTbody", {
    rows: Array.isArray(runs) ? runs : [],
    columns: [
      { render: (r) => escapeHtml(r.run_id || "—") },
      { render: (r) => fmtDateTime(r.start_ts) },
      { render: (r) => fmtDurationSec(r.duration_s) },
      { render: (r) => String(r.total_rows || 0) },
      { render: (r) => r.applied ? '<span class="badge badge--ok">Oui</span>' : '<span class="badge badge--neutral">Non</span>' },
      { render: (r) => String(r.anomalies_count || 0) },
      { render: (r) => `<button class="btn btn--compact btn--ghost" data-open-run="${escapeHtml(r.run_id)}">Ouvrir</button>` },
    ],
    emptyTitle: "Aucun run enregistré.",
    emptyHint: "Lancez un scan depuis l'Accueil pour démarrer votre premier run.",
    /* V2-07 : CTA "Lancer un scan" via composant EmptyState. */
    emptyCta: {
      label: "Lancer un scan",
      icon: "history",
      testId: "history-empty-cta",
      onClick: () => {
        if (typeof navigateTo === "function") navigateTo("home");
      },
    },
    onRowClick: (row) => {
      state.logsSelectedRunId = row.run_id;
      setLastRunContext(row.run_id, row.run_dir);
      updateHistoryExportLabel();
    },
  });
}

function updateHistoryExportLabel() {
  const rid = currentContextRunId();
  if ($("historyRunLabel")) {
    $("historyRunLabel").textContent = rid ? `Run : ${rid}` : "Aucun run selectionne";
  }
}

async function refreshHistoryView(opts = {}) {
  const r = await apiCall("get_dashboard(history)", () => window.pywebview.api.get_dashboard("latest"), {
    statusId: "exportMsg",
    fallbackMessage: "Impossible de charger l'historique.",
  });
  if (r && r.ok !== false) {
    state.dashboard = r;
    if (r.run_id && r.run_dir) {
      setLastRunContext(r.run_id, r.run_dir);
    }
  }

  /* Load runs history */
  const runs = r?.runs_history || r?.runs || [];
  state.runsHistory = Array.isArray(runs) ? runs : [];
  rememberRunDirsFromHistory(state.runsHistory);
  renderHistoryTable(state.runsHistory);
  updateHistoryExportLabel();

  /* Journal */
  const log = r?.journal || "";
  if ($("logboxAll")) {
    $("logboxAll").textContent = log || "Aucun journal disponible.";
  }
}

async function exportCurrentRunReport(fmt) {
  const runId = currentContextRunId();
  if (!runId) {
    setStatusMessage("exportMsg", "Aucun run actif.", { error: true, clearMs: 2000 });
    return;
  }
  setStatusMessage("exportMsg", `Export ${fmt} en cours...`, { loading: true });
  const r = await apiCall("export_run_report", () => window.pywebview.api.export_run_report(runId, fmt), {
    statusId: "exportMsg",
    fallbackMessage: `Erreur d'export ${fmt}.`,
  });
  if (r?.ok) {
    setStatusMessage("exportMsg", `Export ${fmt} termine : ${r.path || "OK"}`, { success: true, clearMs: 3000 });
  }
}

async function exportRunNfo() {
  const runId = currentContextRunId();
  if (!runId) {
    setStatusMessage("exportMsg", "Aucun run actif.", { error: true, clearMs: 2000 });
    return;
  }
  /* Preview first */
  setStatusMessage("exportMsg", "Preview .nfo...", { loading: true });
  const preview = await apiCall("export_run_nfo(preview)", () => window.pywebview.api.export_run_nfo(runId, false, true), {
    statusId: "exportMsg",
  });
  if (!preview?.ok) return;

  const count = Number(preview.total || preview.count || 0);
  const proceed = await uiConfirm({
    title: "Generer les fichiers .nfo",
    message: `${count} fichier(s) .nfo seront generes. Continuer ?`,
    confirmLabel: "Generer",
  });
  if (!proceed) {
    setStatusMessage("exportMsg", "Generation annulee.", { clearMs: 2000 });
    return;
  }

  setStatusMessage("exportMsg", "Generation .nfo...", { loading: true });
  const r = await apiCall("export_run_nfo", () => window.pywebview.api.export_run_nfo(runId, false, false), {
    statusId: "exportMsg",
  });
  if (r?.ok) {
    setStatusMessage("exportMsg", `${r.created || 0} .nfo genere(s).`, { success: true, clearMs: 3000 });
  }
}

function hookHistoryEvents() {
  $("btnExportJson")?.addEventListener("click", () => exportCurrentRunReport("json"));
  $("btnExportCsv")?.addEventListener("click", () => exportCurrentRunReport("csv"));
  $("btnExportHtml")?.addEventListener("click", () => exportCurrentRunReport("html"));
  $("btnExportNfo")?.addEventListener("click", exportRunNfo);

  /* Delegate open-run buttons in table */
  $("historyTbody")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-open-run]");
    if (btn) {
      const rid = btn.dataset.openRun;
      state.logsSelectedRunId = rid;
      setLastRunContext(rid, resolveRunDirFor(rid));
      updateHistoryExportLabel();
    }
  });
}
