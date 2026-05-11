/* global pywebview */

const state = {
  view: "settings",
  settings: null,
  runId: null,
  runDir: null,
  rowsRunId: null,
  runDirsById: new Map(),
  lastRunId: null,
  selectedRunId: null,
  selectedRowId: null,
  selectedTitle: "",
  selectedYear: 0,
  selectedFolder: "",
  advancedMode: false,
  selectedRunForModal: null,
  logIndex: 0,
  polling: null,
  pollInFlight: false,
  applyInFlight: false,
  undoInFlight: false,
  undoPreview: null,
  cleanupResidualPreview: null,
  cleanupResidualLastResult: null,
  qualityBatchInFlight: false,
  validationPreset: "none",
  nextStepInFlight: false,
  rows: [],
  rowsById: new Map(),
  duplicates: null,
  qualityHubPanel: "overview",
  nextStepView: "plan",
  decisions: {}, // rowId -> {ok,title,year,edited}
  candidatesForRow: null,
  qualityProfile: null,
  qualityPresets: [],
  qualityByRow: new Map(),
  probeToolsStatus: null,
  probeToolsInFlight: false,
  dashboard: null,
  runsHistory: [],
  modalRows: [],
  activeModalId: null,
  modalReturnFocusEl: null,
  theme: "dark",
  tmdbLastTestOk: null,
};
const LS_LAST_RUN_ID = "cinesort.lastRunId";
const LS_SELECTED_RUN_ID = "cinesort.selectedRunId";
const LS_SELECTED_ROW_ID = "cinesort.selectedRowId";
const LS_SELECTED_TITLE = "cinesort.selectedTitle";
const LS_SELECTED_YEAR = "cinesort.selectedYear";
const LS_SELECTED_FOLDER = "cinesort.selectedFolder";
const LS_ADVANCED_MODE = "cinesort.advancedMode";

function restoreContextFromStorage(){
  state.lastRunId = getStoredText(LS_LAST_RUN_ID) || null;
  state.selectedRunId = getStoredText(LS_SELECTED_RUN_ID) || null;
  state.selectedRowId = null;
  state.selectedTitle = "";
  state.selectedYear = 0;
  state.selectedFolder = "";
  const adv = getStoredText(LS_ADVANCED_MODE).toLowerCase();
  state.advancedMode = adv === "1" || adv === "true" || adv === "yes";
}

function persistContextToStorage(){
  setStoredText(LS_LAST_RUN_ID, state.lastRunId || "");
  setStoredText(LS_SELECTED_RUN_ID, state.selectedRunId || "");
  setStoredText(LS_SELECTED_ROW_ID, state.selectedRowId || "");
  setStoredText(LS_SELECTED_TITLE, state.selectedTitle || "");
  setStoredText(LS_SELECTED_YEAR, state.selectedYear || 0);
  setStoredText(LS_SELECTED_FOLDER, state.selectedFolder || "");
  setStoredText(LS_ADVANCED_MODE, state.advancedMode ? "1" : "0");
}

function currentContextRunId(){
  return String(state.runId || state.selectedRunId || state.lastRunId || "");
}

function currentContextRowId(){
  return String(state.selectedRowId || "");
}

function currentContextRunLabel(){
  const rid = currentContextRunId();
  return rid || "Dernier run";
}

function currentContextFilmLabel(){
  const title = String(state.selectedTitle || "").trim();
  const year = Number(state.selectedYear || 0);
  if(title && year > 0) return `${title} (${year})`;
  if(title) return title;
  return "Aucun film sélectionné.";
}

function applyAdvancedVisibility(){
  qsa(".advancedOnly").forEach((el) => {
    el.classList.toggle("hidden", !state.advancedMode);
  });
  const ck = $("ckAdvancedMode");
  if(ck) ck.checked = !!state.advancedMode;
}

function syncContextToInputs(){
  if($("qTestRunId")) $("qTestRunId").value = String(currentContextRunId() || "");
  if($("qTestRowId")) $("qTestRowId").value = String(currentContextRowId() || "");
  if($("dashRunId") && state.advancedMode){
    $("dashRunId").value = String(currentContextRunId() || "");
  }
}

function resetFilmDetailPanels(){
  state.candidatesForRow = null;
  const candHeader = $("candHeader");
  if(candHeader) candHeader.textContent = "—";
  const candList = $("candList");
  if(candList) candList.innerHTML = "";
  const qualityOut = $("qualityTestOut");
  if(qualityOut) qualityOut.textContent = "—";
  if(state.activeModalId === "modalCandidates"){
    closeModal("modalCandidates");
  }
}

function resetRunDetailPanels(){
  resetFilmDetailPanels();
  const qualityBatchOut = $("qualityBatchOut");
  if(qualityBatchOut) qualityBatchOut.textContent = "—";
  const applyResult = $("applyResult");
  if(applyResult) applyResult.textContent = "—";
  const undoResult = $("undoResult");
  if(undoResult) undoResult.textContent = "—";
}

function syncSelectedFilmContextForLoadedRows(){
  const selectedRowId = String(state.selectedRowId || "").trim();
  const rowsRunId = String(state.rowsRunId || "").trim();
  const selectedRunId = String(state.selectedRunId || "").trim();
  if(!selectedRowId || !rowsRunId){
    updateSelectedRowVisual();
    return false;
  }
  if(selectedRunId && selectedRunId !== rowsRunId){
    clearSelectedFilmContext();
    resetFilmDetailPanels();
    persistContextToStorage();
    updateSelectedRowVisual();
    return false;
  }
  const row = findRowById(selectedRowId);
  if(!row){
    clearSelectedFilmContext();
    resetFilmDetailPanels();
    persistContextToStorage();
    updateSelectedRowVisual();
    return false;
  }
  const nextTitle = String(row.proposed_title || row.title || "").trim();
  const nextYear = parseInt(row.proposed_year || row.year || 0, 10) || 0;
  const nextFolder = String(row.folder || row.path || "").trim();
  const changed = state.selectedTitle !== nextTitle
    || Number(state.selectedYear || 0) !== nextYear
    || String(state.selectedFolder || "") !== nextFolder
    || selectedRunId !== rowsRunId;
  state.selectedRunId = rowsRunId || null;
  state.selectedTitle = nextTitle;
  state.selectedYear = nextYear;
  state.selectedFolder = nextFolder;
  if(changed){
    persistContextToStorage();
  }
  updateSelectedRowVisual();
  return true;
}

function updateContextBar(){
  syncSelectedFilmContextForLoadedRows();
  const runLabel = currentContextRunLabel();
  const runEl = $("ctxRunText");
  if(runEl) runEl.textContent = runLabel;

  const filmEl = $("ctxFilmText");
  if(filmEl) filmEl.textContent = currentContextFilmLabel();

  const rowEl = $("ctxRowIdText");
  if(rowEl) rowEl.textContent = currentContextRowId() || "—";
  const hint = $("ctxRunHint");
  if(hint) hint.textContent = "Le run actif sert aux actions Qualité. Le Dashboard consulte un run sans changer le workflow.";

  syncContextToInputs();
  setUndoControlsState();
}

function setAdvancedMode(enabled){
  state.advancedMode = !!enabled;
  applyAdvancedVisibility();
  persistContextToStorage();
  updateContextBar();
}

function rememberRunDir(runId, runDir){
  const rid = String(runId || "").trim();
  const dir = String(runDir || "").trim();
  if(!rid || !dir){
    return;
  }
  state.runDirsById.set(rid, dir);
}

function rememberRunDirsFromHistory(runs){
  const list = Array.isArray(runs) ? runs : [];
  for(const row of list){
    if(!row || typeof row !== "object"){
      continue;
    }
    rememberRunDir(row.run_id, row.run_dir);
  }
}

function clearSelectedFilmContext(){
  state.selectedRowId = null;
  state.selectedTitle = "";
  state.selectedYear = 0;
  state.selectedFolder = "";
}

function resetRunScopedState(){
  setRows([], null);
  state.decisions = {};
  state.duplicates = null;
  state.qualityByRow = new Map();
  state.cleanupResidualPreview = null;
  state.cleanupResidualLastResult = null;
  clearSelectedFilmContext();
  resetRunDetailPanels();
  renderDuplicatesView({ total_groups: 0, checked_rows: 0, groups: [] });
  renderApplyCleanupDiagnostic();
}

function clearRunCachesForStateDirChange(){
  state.dashboard = null;
  state.runsHistory = [];
  state.runDirsById = new Map();
  state.runId = null;
  state.runDir = null;
  state.lastRunId = null;
  state.selectedRunId = null;
  state.selectedRunForModal = null;
  state.modalRows = [];
  resetRunScopedState();
  persistContextToStorage();
  updateContextBar();
  setPill("pillRun", "Run: —");
  if($("dashRunId")) $("dashRunId").value = "";
  if(state.activeModalId === "modalRunSelector"){
    closeModal("modalRunSelector");
  }
  clearDashboardView();
}

function setLastRunContext(runId, runDir){
  const rid = String(runId || "").trim();
  if(!rid) return;
  const currentRunId = String(state.runId || "").trim();
  const workflowChanged = !!currentRunId && currentRunId !== rid;
  state.lastRunId = rid;
  state.selectedRunId = rid;
  if(runDir){
    rememberRunDir(rid, runDir);
    state.runDir = String(runDir);
  } else if(workflowChanged){
    state.runDir = state.runDirsById.get(rid) || null;
  }
  if(workflowChanged){
    resetRunScopedState();
  }
  if(state.runId !== rid){
    state.runId = rid;
  }
  persistContextToStorage();
  updateContextBar();
  setPill("pillRun", "Run: " + rid);
}

function setSelectedFilmContext(row, runId){
  if(!row) return;
  state.selectedRunId = String(runId || state.runId || state.lastRunId || "").trim() || null;
  state.selectedRowId = String(row.row_id || "").trim() || null;
  state.selectedTitle = String(row.proposed_title || row.title || "").trim();
  state.selectedYear = parseInt(row.proposed_year || row.year || 0, 10) || 0;
  state.selectedFolder = String(row.folder || row.path || "").trim();
  persistContextToStorage();
  updateContextBar();
}

function setRows(rows, runId = null){
  state.rows = Array.isArray(rows) ? rows : [];
  state.rowsRunId = String(runId || "").trim() || null;
  state.rowsById = new Map();
  for(const row of state.rows){
    const rid = String(row?.row_id || "");
    if(rid){
      state.rowsById.set(rid, row);
    }
  }
  syncSelectedFilmContextForLoadedRows();
}

function findRowById(rowId){
  const rid = String(rowId || "").trim();
  if(!rid) return null;
  return state.rowsById.get(rid) || null;
}

function updateSelectedRowVisual(){
  const selected = String(state.selectedRowId || "");
  document.querySelectorAll("#planTbody tr[data-row-id]").forEach((tr) => {
    const isSelected = String(tr.dataset.rowId || "") === selected;
    tr.classList.toggle("selectedRow", isSelected);
  });
}

function setSelectedFilmById(rowId, runId){
  const row = findRowById(rowId);
  if(!row) return;
  setSelectedFilmContext(row, runId || state.runId);
}

function resolveRunDirFor(runId){
  const rid = String(runId || "").trim();
  if(!rid) return "";
  const known = String(state.runDirsById.get(rid) || "").trim();
  if(known){
    return known;
  }
  if(state.runId && state.runDir && state.runId === rid){
    return String(state.runDir);
  }
  return "";
}

function setHeadline(view){
  const map = {
    settings: ["Paramètres", "Configure la source et l'état local (logs + cache)."],
    quality: ["Qualité", "Hub qualité: actions batch, filtres, outils probe et profil scoring."],
    dashboard: ["Dashboard", "Vue premium de la qualité de la bibliothèque (dernier run)."],
    plan: ["Analyse", "Scanne la bibliothèque, prépare le plan et les signaux de relecture."],
    validate: ["Validation", "Valide les lignes sûres et isole les cas à relire."],
    duplicates: ["Doublons", "Vérifie les conflits de destination avant d'appliquer."],
    apply: ["Application", "Applique les lignes validées (mode test recommandé en premier)."],
    logs: ["Journaux", "Historique détaillé du run en cours."],
  };
  const [h, s] = map[view] || ["CineSort", ""];
  $("headline").textContent = h;
  $("subline").textContent = s;
}

function viewLabelFr(view){
  const labels = {
    settings: "Paramètres",
    plan: "Analyse",
    quality: "Qualité",
    validate: "Validation",
    duplicates: "Doublons",
    apply: "Application",
    logs: "Journaux",
    dashboard: "Dashboard",
  };
  return labels[String(view || "")] || "étape suivante";
}

function setQualityHubPanel(panel){
  const p = String(panel || "overview");
  const allowed = new Set(["overview", "filters", "tools", "profile"]);
  state.qualityHubPanel = allowed.has(p) ? p : "overview";

  qsa(".qualityHubTab").forEach((btn) => {
    const active = String(btn.dataset.qualityPanel || "") === state.qualityHubPanel;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  qsa(".qualityPanel").forEach((panelEl) => {
    const id = String(panelEl.id || "");
    const panelKey = id.replace("quality-panel-", "");
    const active = panelKey === state.qualityHubPanel;
    panelEl.classList.toggle("hidden", !active);
    panelEl.setAttribute("aria-hidden", active ? "false" : "true");
  });
}

function updateGuidedAction(view){
  const plan = {
    settings: {
      title: "Configure les paramètres de base",
      text: "Renseigne ROOT, STATE_DIR et teste TMDb avant de lancer l'analyse.",
      nextView: "plan",
      details: ["Vérifie ROOT + STATE_DIR.", "Teste la clé TMDb.", "Passe ensuite à Analyse."],
    },
    plan: {
      title: "Lance l'analyse de la bibliothèque",
      text: "Démarre le scan puis charge la table de validation.",
      nextView: "quality",
      details: ["Surveille progression et ETA.", "Charge la table dès PLAN READY.", "Puis ouvre Qualité pour un tri rapide."],
    },
    quality: {
      title: "Priorise les cas qualité avant validation finale",
      text: "Exécute batch qualité, filtre les cas faibles, puis reviens à Validation.",
      nextView: "validate",
      details: ["Vue & batch pour scorer.", "Filtres qualité pour isoler les cas à relire.", "Outils probe et profil avancé si nécessaire."],
    },
    validate: {
      title: "Valide les lignes sûres",
      text: "Utilise presets et filtres avancés, puis vérifie les doublons.",
      nextView: "duplicates",
      details: ["Coche surtout les cas à haute confiance.", "Traite MED/LOW par priorité.", "Sauvegarde la validation avant l'application."],
    },
    duplicates: {
      title: "Contrôle les conflits de destination",
      text: "Actualise la vue doublons, corrige si besoin, puis applique.",
      nextView: "apply",
      details: ["Conflits plan vs cible existante.", "Les cas fusionnables restent séparés.", "Passe à Application en mode test d'abord."],
    },
    apply: {
      title: "Applique en sécurité",
      text: "Lance d'abord un mode test, puis l'application réelle après vérification.",
      nextView: "logs",
      details: ["Surveille le résumé final.", "Ouvre _review en cas de conflits.", "Consulte Journaux si nécessaire."],
    },
    logs: {
      title: "Contrôle les journaux du run",
      text: "Vérifie les messages finaux et anomalies avant de clôturer.",
      nextView: "dashboard",
      details: ["Logs plan + apply.", "Pistes de correction immédiates.", "Dashboard pour vue globale."],
    },
    dashboard: {
      title: "Lis la santé globale de la bibliothèque",
      text: "Utilise KPI/outliers pour préparer le prochain run.",
      nextView: "settings",
      details: ["Score moyen + premium.", "Anomalies top et historique runs.", "Ajuste ensuite paramètres/qualité."],
    },
  };
  const cfg = plan[String(view || "")] || plan.settings;
  state.nextStepView = cfg.nextView;

  const title = $("nextActionTitle");
  const text = $("nextActionText");
  if(title) title.textContent = cfg.title;
  if(text) text.textContent = cfg.text;

  const d1 = $("nextActionDetail1");
  const d2 = $("nextActionDetail2");
  const d3 = $("nextActionDetail3");
  if(d1) d1.textContent = cfg.details[0] || "";
  if(d2) d2.textContent = cfg.details[1] || "";
  if(d3) d3.textContent = cfg.details[2] || "";

  const details = $("nextActionDetails");
  const btn = $("btnToggleGuideDetails");
  if(details && btn){
    const open = !details.classList.contains("hidden");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  const nextBtn = $("btnNextStep");
  if(nextBtn){
    const nextLabel = viewLabelFr(cfg.nextView);
    nextBtn.textContent = `Aller à ${nextLabel}`;
    nextBtn.title = `Ouvrir ${nextLabel}`;
    nextBtn.setAttribute("aria-label", `Aller à ${nextLabel}`);
    nextBtn.dataset.nextView = String(cfg.nextView || "");
  }
}

function syncActiveRunForWorkflow(){
  const rid = String(state.runId || state.selectedRunId || state.lastRunId || "").trim();
  if(!rid){
    return "";
  }
  if(String(state.runId || "").trim() !== rid){
    setLastRunContext(rid, null);
  } else {
    setPill("pillRun", "Run: " + rid);
  }
  return rid;
}

async function ensureValidationReadyForWorkflow(){
  const rid = syncActiveRunForWorkflow();
  if(!rid){
    return false;
  }
  if(Array.isArray(state.rows) && state.rows.length > 0){
    return true;
  }
  return !!(await loadTable());
}

async function goToNextStep(){
  const btn = $("btnNextStep");
  const next = String(state.nextStepView || "").trim();
  if(!btn || !next){
    return;
  }
  if(state.nextStepInFlight){
    setStatusMessage("planMsg", "Navigation déjà en cours...", { error: true });
    flashActionButton(btn, "error");
    return;
  }

  state.nextStepInFlight = true;
  btn.disabled = true;
  try {
    if(next === "validate"){
      const ok = await ensureValidationReadyForWorkflow();
      if(!ok){
        setStatusMessage("validationMsg", "Impossible d'ouvrir Validation : aucun run exploitable.", { error: true });
        flashActionButton(btn, "error");
        return;
      }
      showView("validate");
      renderTable();
      flashActionButton(btn, "ok");
      return;
    }

    if(next === "duplicates"){
      const ok = await ensureValidationReadyForWorkflow();
      if(!ok){
        setStatusMessage("dupMsg", "Impossible d'ouvrir Doublons : chargez d'abord un run.", { error: true });
        flashActionButton(btn, "error");
        return;
      }
      showView("duplicates");
      await refreshDuplicatesView();
      flashActionButton(btn, "ok");
      return;
    }

    if(next === "apply"){
      const rid = syncActiveRunForWorkflow();
      if(!rid){
        setStatusMessage("applyMsg", "Impossible d'ouvrir Application : lancez d'abord une analyse.", { error: true });
        flashActionButton(btn, "error");
        return;
      }
      showView("apply");
      await refreshUndoPreview(null, { silent: true });
      flashActionButton(btn, "ok");
      return;
    }

    showView(next);
    if(next === "quality"){
      await loadQualityProfile();
      await loadProbeToolsStatus(false);
    } else if(next === "dashboard"){
      await loadDashboard("latest");
    }
    flashActionButton(btn, "ok");
  } catch(err){
    setStatusMessage("planMsg", `Navigation impossible : ${String(err || "erreur inconnue")}`, { error: true });
    flashActionButton(btn, "error");
  } finally {
    state.nextStepInFlight = false;
    btn.disabled = false;
  }
}

function showView(view){
  state.view = view;
  document.body.dataset.view = String(view || "");
  qsa(".step").forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
    b.setAttribute("tabindex", active ? "0" : "-1");
  });
  qsa(".view").forEach((v) => {
    v.classList.add("hidden");
    v.setAttribute("aria-hidden", "true");
  });
  const target = $("view-" + view);
  if(target){
    target.classList.remove("hidden");
    target.setAttribute("aria-hidden", "false");
  }
  if(view === "quality"){
    setQualityHubPanel(state.qualityHubPanel || "overview");
  }
  setHeadline(view);
  updateGuidedAction(view);
  updateContextBar();
  if(typeof syncNextApplyViewState === "function"){
    syncNextApplyViewState();
  }
}

function fmtEta(s){
  if(!s || s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if(h > 0) return `${h}h ${m}m`;
  if(m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

function fmtSpeed(v){
  const n = Number(v || 0);
  return n.toFixed(2).replace(".", ",");
}

function fmtDateTime(ts){
  const n = Number(ts || 0);
  if(!n) return "—";
  const d = new Date(n * 1000);
  if(Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("fr-FR");
}

function fmtDurationSec(s){
  const n = Number(s || 0);
  if(!Number.isFinite(n) || n <= 0) return "—";
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const r = Math.floor(n % 60);
  if(h > 0) return `${h}h ${m}m`;
  if(m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

function formatMovieLabel(item){
  const title = String(item?.title || "").trim();
  const year = Number(item?.year || 0);
  if(title && year > 0) return `${title} (${year})`;
  if(title) return title;
  return "—";
}

function severityBadge(severity){
  const s = String(severity || "INFO").toUpperCase();
  if(s === "ERROR") return '<span class="badge low">ERROR</span>';
  if(s === "WARN") return '<span class="badge med">WARN</span>';
  return '<span class="badge high">INFO</span>';
}

function formatApplyResult(result, dryRun){
  if(!result || typeof result !== "object"){
    return "Résultat non disponible.";
  }
  const mode = dryRun ? "Mode test" : "Application réelle";
  const skipReasons = (result.skip_reasons && typeof result.skip_reasons === "object")
    ? result.skip_reasons
    : null;
  const skipReasonLabels = [
    ["skip_non_valide", "non validés"],
    ["skip_validation_absente", "validation absente"],
    ["skip_noop_deja_conforme", "déjà conformes"],
    ["skip_option_desactivee", "option désactivée"],
    ["skip_merged", "fusionnés"],
    ["skip_conflit_quarantaine", "conflits"],
    ["skip_erreur_precedente", "erreurs précédentes"],
    ["skip_autre", "autres"],
  ];
  const skipDetails = [];
  const keyFallback = {
    skip_non_valide: "non_valide",
    skip_validation_absente: "validation_absente",
    skip_noop_deja_conforme: "deja_conforme",
    skip_option_desactivee: "option_desactivee",
    skip_merged: "fusionne",
    skip_conflit_quarantaine: "conflit_quarantaine",
    skip_erreur_precedente: "erreur_precedente",
    skip_autre: "autre",
  };
  if(skipReasons){
    skipReasonLabels.forEach(([key, label]) => {
      const fallbackKey = keyFallback[key];
      const n = Number(skipReasons[key] || skipReasons[fallbackKey] || 0);
      if(n > 0){
        skipDetails.push(`${label}: ${n}`);
      }
    });
  }
  const lines = [
    `${mode}`,
    "",
    `- Renommages de dossiers : ${result.renames ?? 0}`,
    `- Déplacements de fichiers : ${result.moves ?? 0}`,
    `- Dossiers créés (Collection, _review, sous-dossiers) : ${result.mkdirs ?? 0}`,
    `- Dossiers de collection déplacés dans le dossier collections : ${result.collection_moves ?? 0}`,
    `- Éléments placés en _review : ${result.quarantined ?? 0}`,
    `- Éléments non appliqués : ${result.skipped ?? 0}`,
    `- Erreurs : ${result.errors ?? 0}`,
  ];
  if(skipDetails.length > 0){
    lines.push(`  Détail : ${skipDetails.join(", ")}`);
  }
  const cleanupDiag = (result.cleanup_residual_diagnostic && typeof result.cleanup_residual_diagnostic === "object")
    ? result.cleanup_residual_diagnostic
    : null;
  if(cleanupDiag){
    const families = Array.isArray(cleanupDiag.families) && cleanupDiag.families.length > 0
      ? cleanupDiag.families.join(", ")
      : "Aucune";
    const statusLabel = cleanupResidualStatusDescriptor(null, { diagnostic: cleanupDiag, dry_run: !!dryRun }, { enabled: !!cleanupDiag.enabled }).label.toLowerCase();
    const moved = Number(cleanupDiag.moved_count || 0);
    const probable = Number(cleanupDiag.probable_eligible_count || 0);
    const left = Number(cleanupDiag.left_in_place_count || 0);
    lines.push(
      "",
      "Nettoyage résiduel",
      `- Activé : ${cleanupDiag.enabled ? "oui" : "non"}`,
      `- Dossier cible : ${cleanupDiag.target_folder_name || "_Dossier Nettoyage"}`,
      `- Scope : ${cleanupResidualScopeDescriptor(cleanupDiag.scope || "touched_only").label}`,
      `- Familles actives : ${families}`,
      `- Statut : ${statusLabel}`,
      `- Probablement éligibles avant l'application : ${probable}`,
      `- Dossiers déplacés : ${moved}`,
      `- Dossiers laissés en place : ${left}`,
    );
    const cleanupMsg = String(cleanupDiag.message_post || cleanupDiag.message || "").trim();
    if(cleanupMsg){
      lines.push(`- Diagnostic : ${cleanupMsg}`);
    }
  }
  return lines.join("\n");
}

function cleanupResidualFamiliesFromInputs(){
  const families = [];
  if($("ckResidualIncludeNfo")?.checked) families.push("NFO/XML");
  if($("ckResidualIncludeImages")?.checked) families.push("Images");
  if($("ckResidualIncludeSubtitles")?.checked) families.push("Sous-titres");
  if($("ckResidualIncludeTexts")?.checked) families.push("Textes");
  return families;
}

function cleanupResidualConfiguredState(){
  return {
    enabled: !!$("ckResidualCleanupEnabled")?.checked,
    target_folder_name: String($("inResidualCleanupFolderName")?.value || "_Dossier Nettoyage").trim() || "_Dossier Nettoyage",
    scope: String($("selResidualCleanupScope")?.value || "touched_only").trim() || "touched_only",
    families: cleanupResidualFamiliesFromInputs(),
  };
}

function cleanupResidualActivePreview(){
  const rid = String(currentContextRunId() || state.runId || "").trim();
  if(!rid || !state.cleanupResidualPreview || typeof state.cleanupResidualPreview !== "object"){
    return null;
  }
  return String(state.cleanupResidualPreview.run_id || "").trim() === rid ? state.cleanupResidualPreview : null;
}

function cleanupResidualActiveResult(){
  const rid = String(currentContextRunId() || state.runId || "").trim();
  if(!rid || !state.cleanupResidualLastResult || typeof state.cleanupResidualLastResult !== "object"){
    return null;
  }
  return String(state.cleanupResidualLastResult.run_id || "").trim() === rid ? state.cleanupResidualLastResult : null;
}

function cleanupResidualScopeDescriptor(scope){
  if(String(scope || "").trim() === "root_all"){
    return {
      label: "Toute la racine ROOT",
      hint: "Inspecte tous les dossiers top-level du ROOT.",
    };
  }
  return {
    label: "Dossiers touchés par ce run",
    hint: "Inspecte seulement les dossiers top-level touchés par ce run.",
  };
}

function cleanupResidualReasonLabel(code){
  return {
    disabled: "Fonction désactivée.",
    eligible: "Des dossiers semblent éligibles.",
    scope_touched_only_none: "Aucun dossier touché ne correspond au scope actuel.",
    videos_present: "Les dossiers inspectés contiennent encore une vraie vidéo.",
    ambiguous_extensions: "Des extensions ambiguës bloquent le nettoyage.",
    empty_only: "Seuls des dossiers vides relèvent de _Vide.",
    none_eligible: "Aucun dossier sidecar-only éligible trouvé.",
    no_families_enabled: "Aucune famille résiduelle n'est activée.",
  }[String(code || "").trim()] || "Diagnostic indisponible.";
}

function cleanupResidualFamiliesLabel(families){
  return Array.isArray(families) && families.length > 0 ? families.join(" • ") : "Aucune";
}

function cleanupResidualBlockedHint(diag){
  if(!diag || typeof diag !== "object"){
    return "";
  }
  const parts = [];
  const videos = Number(diag.has_video_count || 0);
  const ambiguous = Number(diag.ambiguous_count || 0);
  const empty = Number(diag.empty_dir_count || 0);
  const symlink = Number(diag.symlink_count || 0);
  if(videos > 0) parts.push(`${videos} avec vidéo`);
  if(ambiguous > 0) parts.push(`${ambiguous} ambigu${ambiguous > 1 ? "s" : ""}`);
  if(empty > 0) parts.push(`${empty} relevant de _Vide`);
  if(symlink > 0) parts.push(`${symlink} symlink${symlink > 1 ? "s" : ""}`);
  return parts.join(" • ");
}

function cleanupResidualStatusDescriptor(previewWrap, resultWrap, configured){
  if(resultWrap?.diagnostic){
    const diag = resultWrap.diagnostic;
    const post = String(diag.status_post || "").trim();
    if(post === "executed"){
      return {
        tone: "ok",
        label: "Exécuté",
        hint: String(diag.message_post || "Nettoyage résiduel exécuté.").trim(),
      };
    }
    if(post === "executed_no_move"){
      return {
        tone: "warn",
        label: "Exécuté sans déplacement",
        hint: String(diag.message_post || diag.message || "Nettoyage exécuté sans déplacement.").trim(),
      };
    }
    if(post === "not_executed"){
      return {
        tone: "warn",
        label: resultWrap.dry_run ? "Simulation" : "Non exécuté",
        hint: String(diag.message_post || "Dry-run: aucun déplacement réel.").trim(),
      };
    }
    return {
      tone: "bad",
      label: "Désactivé",
      hint: String(diag.message_post || diag.message || "Nettoyage résiduel désactivé.").trim(),
    };
  }

  if(previewWrap?.error){
    return {
      tone: "warn",
      label: "Non exécuté",
      hint: String(previewWrap.message || "Prévision indisponible pour ce run.").trim(),
    };
  }

  if(previewWrap?.preview){
    const preview = previewWrap.preview;
    if(!preview.enabled){
      return {
        tone: "bad",
        label: "Désactivé",
        hint: String(preview.message || "Nettoyage résiduel désactivé.").trim(),
      };
    }
    if(String(preview.status || "").trim() === "ready"){
      return {
        tone: "ok",
        label: "Prêt",
        hint: String(preview.message || "Des dossiers semblent éligibles.").trim(),
      };
    }
    return {
      tone: "warn",
      label: "Aucune action probable",
      hint: String(preview.message || "Aucun dossier éligible trouvé pour ce run.").trim(),
    };
  }

  if(!configured.enabled){
    return {
      tone: "bad",
      label: "Désactivé",
      hint: "Option désactivée dans les paramètres.",
    };
  }

  return {
    tone: "warn",
    label: "Non exécuté",
    hint: "Lancez ou rechargez un run pour obtenir une prévision fiable.",
  };
}

function formatCleanupResidualDetail(previewWrap, resultWrap){
  const parts = [];
  const preview = previewWrap?.preview;
  const result = resultWrap?.diagnostic;
  if(preview){
    parts.push(`Inspectés : ${Number(preview.candidates_considered || 0)}`);
    parts.push(`Probablement éligibles : ${Number(preview.probable_eligible_count || 0)}`);
    parts.push(`Bloqués car vidéo : ${Number(preview.has_video_count || 0)}`);
    parts.push(`Bloqués car ambiguïté : ${Number(preview.ambiguous_count || 0)}`);
    parts.push(`Ignorés car symlink : ${Number(preview.symlink_count || 0)}`);
    parts.push(`Dossiers relevant de _Vide : ${Number(preview.empty_dir_count || 0)}`);
    const sampleEligible = Array.isArray(preview.sample_eligible_dirs) ? preview.sample_eligible_dirs : [];
    const sampleVideo = Array.isArray(preview.sample_video_blocked_dirs) ? preview.sample_video_blocked_dirs : [];
    const sampleAmbiguous = Array.isArray(preview.sample_ambiguous_dirs) ? preview.sample_ambiguous_dirs : [];
    if(sampleEligible.length > 0){
      parts.push(`Exemples éligibles : ${sampleEligible.join(" | ")}`);
    }
    if(sampleVideo.length > 0){
      parts.push(`Exemples bloqués par vidéo : ${sampleVideo.join(" | ")}`);
    }
    if(sampleAmbiguous.length > 0){
      parts.push(`Exemples ambigus : ${sampleAmbiguous.join(" | ")}`);
    }
  }
  if(result){
    parts.push(`Déplacés : ${Number(result.moved_count || 0)}`);
    parts.push(`Laissés en place : ${Number(result.left_in_place_count || 0)}`);
    const msg = String(result.message_post || result.message || "").trim();
    if(msg){
      parts.push(`Résumé : ${msg}`);
    }
  } else if(previewWrap?.error){
    parts.push(`Prévision indisponible : ${String(previewWrap.message || "").trim() || "run non prêt"}`);
  }
  return parts.length > 0 ? parts.join("\n") : "Aucun diagnostic disponible pour ce run.";
}

function renderApplyCleanupDiagnostic(){
  if(!$("applyCleanupDiagPanel")) return;

  const configured = cleanupResidualConfiguredState();
  const previewWrap = cleanupResidualActivePreview();
  const resultWrap = cleanupResidualActiveResult();
  const active = resultWrap?.diagnostic || previewWrap?.preview || configured;
  const families = cleanupResidualFamiliesLabel(active.families);
  const scope = cleanupResidualScopeDescriptor(active.scope || "touched_only");

  setOnboardingBadge("applyCleanupEnabledBadge", active.enabled ? "ok" : "bad", active.enabled ? "Activé" : "Désactivé");
  if($("applyCleanupEnabledHint")){
    $("applyCleanupEnabledHint").textContent = active.enabled
      ? (previewWrap?.preview ? "Le nettoyage résiduel est bien porté par ce run." : "Le réglage est actif et sera pris en compte au prochain run.")
      : "Option désactivée dans les paramètres.";
  }

  if($("applyCleanupScopeValue")) $("applyCleanupScopeValue").textContent = scope.label;
  if($("applyCleanupScopeHint")) $("applyCleanupScopeHint").textContent = scope.hint;

  if($("applyCleanupTargetValue")) $("applyCleanupTargetValue").textContent = String(active.target_folder_name || "_Dossier Nettoyage");
  if($("applyCleanupTargetHint")) $("applyCleanupTargetHint").textContent = "Déplacement uniquement, jamais de suppression.";

  if($("applyCleanupFamiliesValue")) $("applyCleanupFamiliesValue").textContent = families;
  if($("applyCleanupFamiliesHint")) $("applyCleanupFamiliesHint").textContent = active.enabled
    ? "Si une vidéo, une ISO ou une extension inconnue est présente, le dossier reste en place."
    : "Familles inactives tant que le nettoyage résiduel est désactivé.";

  const status = cleanupResidualStatusDescriptor(previewWrap, resultWrap, configured);
  setOnboardingBadge("applyCleanupStatusBadge", status.tone, status.label);
  if($("applyCleanupStatusHint")) $("applyCleanupStatusHint").textContent = status.hint;

  let previewValue = "Nettoyage résiduel désactivé";
  let previewHint = "Aucune estimation pour ce run.";
  if(resultWrap?.diagnostic){
    const diag = resultWrap.diagnostic;
    const probable = Number(diag.probable_eligible_count || 0);
    const moved = Number(diag.moved_count || 0);
    if(resultWrap.dry_run){
      previewValue = probable > 0
        ? `Dry-run : ${probable} dossier(s) seraient déplacé(s)`
        : "Dry-run : aucun dossier ne serait déplacé";
    } else {
      previewValue = moved > 0
        ? `${moved} dossier(s) déplacé(s) vers ${String(diag.target_folder_name || "_Dossier Nettoyage")}`
        : "Aucun dossier déplacé";
    }
    previewHint = cleanupResidualBlockedHint(diag) || cleanupResidualReasonLabel(diag.reason_code);
  } else if(previewWrap?.preview){
    const preview = previewWrap.preview;
    const probable = Number(preview.probable_eligible_count || 0);
    previewValue = probable > 0
      ? `${probable} dossier(s) probablement éligible(s)`
      : "Aucun dossier probablement éligible";
    previewHint = cleanupResidualBlockedHint(preview) || cleanupResidualReasonLabel(preview.reason_code);
  } else if(previewWrap?.error){
    previewValue = "Prévision indisponible pour ce run";
    previewHint = String(previewWrap.message || "Le run n'est pas prêt ou introuvable.").trim();
  } else if(configured.enabled){
    previewValue = "Prévision indisponible tant qu'aucun run chargé n'est disponible";
    previewHint = "Lancez ou rechargez un run pour obtenir une estimation prudente.";
  }
  if($("applyCleanupPreviewValue")) $("applyCleanupPreviewValue").textContent = previewValue;
  if($("applyCleanupPreviewHint")) $("applyCleanupPreviewHint").textContent = previewHint;

  const detailText = formatCleanupResidualDetail(previewWrap, resultWrap);
  if($("applyCleanupDetailText")) $("applyCleanupDetailText").textContent = detailText;
}

async function refreshCleanupResidualPreview(triggerEl = null, opts = {}){
  const rid = syncActiveRunForWorkflow() || String(currentContextRunId() || "").trim();
  if(!rid){
    state.cleanupResidualPreview = null;
    renderApplyCleanupDiagnostic();
    return { ok: false, message: "Run manquant." };
  }

  const out = await apiCall("get_cleanup_residual_preview", () => window.pywebview.api.get_cleanup_residual_preview(rid), {
    statusId: opts.silent ? undefined : "applyMsg",
    fallbackMessage: "Impossible de prévisualiser le nettoyage résiduel.",
  });
  if(!out?.ok){
    state.cleanupResidualPreview = {
      run_id: rid,
      error: true,
      message: String(out?.message || "Prévision indisponible."),
    };
    renderApplyCleanupDiagnostic();
    if(triggerEl) flashActionButton(triggerEl, "error");
    return out;
  }

  state.cleanupResidualPreview = {
    run_id: rid,
    preview: out.preview && typeof out.preview === "object" ? out.preview : {},
  };
  renderApplyCleanupDiagnostic();
  if(triggerEl) flashActionButton(triggerEl, "ok");
  return out;
}

function formatUndoPreview(preview){
  if(!preview || typeof preview !== "object"){
    return "Prévisualisation Undo indisponible.";
  }
  const counts = (preview.counts && typeof preview.counts === "object") ? preview.counts : {};
  const categories = (preview.categories && typeof preview.categories === "object") ? preview.categories : {};
  const lines = [
    `Run: ${preview.run_id || state.runId || "—"}`,
    `Batch cible: ${preview.batch_id || "—"}`,
    `Undo possible: ${preview.can_undo ? "oui" : "non"}`,
    "",
    `- Opérations journalisées: ${Number(counts.total || 0)}`,
    `- Opérations réversibles: ${Number(counts.reversible || 0)}`,
    `- Opérations irréversibles: ${Number(counts.irreversible || 0)}`,
    `- Conflits prévus: ${Number(counts.conflicts_predicted || 0)}`,
  ];
  if(Number(categories.empty_folder_dirs || 0) > 0 || Number(categories.cleanup_residual_dirs || 0) > 0){
    lines.push("", "Dossiers inclus dans l'Undo :");
    if(Number(categories.empty_folder_dirs || 0) > 0){
      lines.push(`- Dossiers vides (_Vide): ${Number(categories.empty_folder_dirs || 0)}`);
    }
    if(Number(categories.cleanup_residual_dirs || 0) > 0){
      lines.push(`- Dossiers résiduels (_Dossier Nettoyage): ${Number(categories.cleanup_residual_dirs || 0)}`);
    }
  }
  if(preview.message){
    lines.push("", `Message: ${String(preview.message)}`);
  }
  return lines.join("\n");
}

function formatUndoExecution(result, dryRun){
  if(!result || typeof result !== "object"){
    return "Résultat Undo indisponible.";
  }
  const counts = (result.counts && typeof result.counts === "object") ? result.counts : {};
  const categories = (result.categories && typeof result.categories === "object") ? result.categories : {};
  const lines = [
    dryRun ? "Annulation en mode test" : "Annulation réelle",
    `Run: ${result.run_id || state.runId || "—"}`,
    `Batch: ${result.batch_id || "—"}`,
    `Statut: ${result.status || "—"}`,
    "",
    `- Restaurées: ${Number(counts.done || 0)}`,
    `- Skipées: ${Number(counts.skipped || 0)}`,
    `- Échecs: ${Number(counts.failed || 0)}`,
    `- Irréversibles: ${Number(counts.irreversible || 0)}`,
  ];
  if(Number(categories.empty_folder_dirs || 0) > 0 || Number(categories.cleanup_residual_dirs || 0) > 0){
    lines.push("", dryRun ? "Dossiers concernés :" : "Dossiers restaurés :");
    if(Number(categories.empty_folder_dirs || 0) > 0){
      const n = dryRun ? Number(categories.empty_folder_dirs || 0) : Number(categories.empty_folder_dirs_reversed || 0);
      lines.push(`- Dossiers vides (_Vide): ${n}`);
    }
    if(Number(categories.cleanup_residual_dirs || 0) > 0){
      const n = dryRun ? Number(categories.cleanup_residual_dirs || 0) : Number(categories.cleanup_residual_dirs_reversed || 0);
      lines.push(`- Dossiers résiduels (_Dossier Nettoyage): ${n}`);
    }
  }
  if(result.message){
    lines.push("", `Message: ${String(result.message)}`);
  }
  return lines.join("\n");
}

function updateUndoRunButton(){
  const btn = $("btnUndoRun");
  if(!btn) return;
  const dry = !!$("ckUndoDryRun")?.checked;
  if(dry){
    btn.classList.add("primary");
    btn.classList.remove("danger");
    btn.textContent = "Tester l'annulation";
  } else {
    btn.classList.remove("primary");
    btn.classList.add("danger");
    btn.textContent = "Lancer l'annulation réelle";
  }
}

function setUndoControlsState(){
  const rid = String(currentContextRunId() || state.runId || "").trim();
  const hasRun = !!rid;
  const busy = !!(state.undoInFlight || state.applyInFlight);
  const dry = !!$("ckUndoDryRun")?.checked;
  const canUndoReal = !!(state.undoPreview && state.undoPreview.can_undo);

  const btnPreview = $("btnUndoPreview");
  const btnRun = $("btnUndoRun");
  const ck = $("ckUndoDryRun");
  if(btnPreview) btnPreview.disabled = busy || !hasRun;
  if(ck) ck.disabled = busy || !hasRun;
  if(btnRun){
    btnRun.disabled = busy || !hasRun || (!dry && !canUndoReal);
  }
}

async function refreshUndoPreview(triggerEl = null, opts = {}){
  const rid = syncActiveRunForWorkflow() || String(currentContextRunId() || "").trim();
  if(!rid){
    state.undoPreview = null;
    setStatusMessage("undoMsg", "Sélectionnez d'abord un run.", { error: true });
    $("undoResult").textContent = "Aucun run actif.";
    setUndoControlsState();
    if(triggerEl) flashActionButton(triggerEl, "error");
    return { ok: false, message: "Run manquant." };
  }

  state.undoInFlight = true;
  setUndoControlsState();
  try {
    if(!opts.silent){
      setStatusMessage("undoMsg", "Prévisualisation Undo en cours...", { loading: true });
    }
    const preview = await apiCall("undo_last_apply_preview", () => window.pywebview.api.undo_last_apply_preview(rid), {
      statusId: "undoMsg",
      fallbackMessage: "Impossible de charger la prévisualisation Undo.",
    });
    if(!preview?.ok){
      state.undoPreview = null;
      setStatusMessage("undoMsg", `Erreur : ${preview?.message || "prévisualisation impossible"}`, { error: true });
      $("undoResult").textContent = preview?.message || "Prévisualisation Undo impossible.";
      if(triggerEl) flashActionButton(triggerEl, "error");
      return preview;
    }

    state.undoPreview = preview;
    $("undoResult").textContent = formatUndoPreview(preview);
    if(!opts.silent){
      if(preview.can_undo){
        setStatusMessage("undoMsg", "Prévisualisation prête.", { success: true });
      } else {
        setStatusMessage("undoMsg", String(preview.message || "Aucun Undo disponible."), { error: true });
      }
    }
    if(triggerEl) flashActionButton(triggerEl, preview.can_undo ? "ok" : "error");
    return preview;
  } finally {
    state.undoInFlight = false;
    setUndoControlsState();
  }
}

async function runUndoFromUI(){
  if(state.undoInFlight){
    setStatusMessage("undoMsg", "Undo déjà en cours...", { loading: true });
    flashActionButton("btnUndoRun", "error");
    return;
  }
  if(state.applyInFlight){
    setStatusMessage("undoMsg", "Attendez la fin de l'application en cours.", { error: true });
    flashActionButton("btnUndoRun", "error");
    return;
  }

  const rid = syncActiveRunForWorkflow() || String(currentContextRunId() || "").trim();
  if(!rid){
    setStatusMessage("undoMsg", "Sélectionnez d'abord un run.", { error: true });
    flashActionButton("btnUndoRun", "error");
    return;
  }

  const dry = !!$("ckUndoDryRun")?.checked;
  if(!dry){
    const latestPreview = state.undoPreview && state.undoPreview.run_id === rid
      ? state.undoPreview
      : await refreshUndoPreview(null, { silent: true });
    if(!latestPreview?.ok || !latestPreview?.can_undo){
      setStatusMessage("undoMsg", String(latestPreview?.message || "Aucune annulation réelle possible."), { error: true });
      flashActionButton("btnUndoRun", "error");
      return;
    }

    const proceed = await uiConfirm({
      title: "Confirmer l'annulation réelle",
      message: "Cette action va tenter de restaurer le dernier apply réel. Les conflits seront isolés dans _review/_undo_conflicts.",
      confirmLabel: "Lancer l'annulation réelle",
      cancelLabel: "Annuler",
      danger: true,
      statusId: "undoMsg",
    });
    if(!proceed){
      setStatusMessage("undoMsg", "Undo annulé.", { clearMs: 1800 });
      return;
    }
  }

  state.undoInFlight = true;
  setUndoControlsState();
  const btnRun = $("btnUndoRun");
  try {
    setStatusMessage("undoMsg", dry ? "Annulation en mode test..." : "Annulation réelle en cours...", { loading: true });
    const out = await apiCall("undo_last_apply", () => window.pywebview.api.undo_last_apply(rid, dry), {
      statusId: "undoMsg",
      fallbackMessage: "Impossible d'exécuter l'Undo.",
    });
    if(!out?.ok){
      setStatusMessage("undoMsg", `Erreur : ${out?.message || "undo impossible"}`, { error: true });
      $("undoResult").textContent = formatUndoExecution(out, dry);
      flashActionButton(btnRun, "error");
      return;
    }

    const partial = String(out.status || "") === "UNDONE_PARTIAL";
    setStatusMessage("undoMsg", String(out.message || "Undo terminé."), {
      success: !partial,
      error: partial,
    });
    $("undoResult").textContent = formatUndoExecution(out, dry);
    flashActionButton(btnRun, "ok");
    await refreshUndoPreview(null, { silent: true });
  } finally {
    state.undoInFlight = false;
    setUndoControlsState();
  }
}

function appendLogs(targetId, logs){
  const box = $(targetId);
  if(!box || !logs || !logs.length) return;
  const lines = logs.map(l => `[${l.ts}] ${l.level}: ${l.msg}`).join("\n");
  box.textContent = (box.textContent ? box.textContent + "\n" : "") + lines;
  box.scrollTop = box.scrollHeight;

  const all = $("logboxAll");
  if(all){
    all.textContent = (all.textContent ? all.textContent + "\n" : "") + lines;
    all.scrollTop = all.scrollHeight;
  }
}

function badgeForConfidence(label){
  const cls = label === "high" ? "high" : label === "med" ? "med" : "low";
  const text = label === "high" ? "Haute" : label === "med" ? "Moyenne" : "Faible";
  return `<span class="badge ${cls}">${text}</span>`;
}

function sourceLabel(source){
  if(source === "nfo") return "NFO";
  if(source === "tmdb") return "TMDb";
  if(source === "name") return "Nom";
  if(source === "unknown") return "Inconnu";
  return source || "Inconnu";
}

function parseYearDelta(note){
  const m = /dY=(\d+)/.exec(String(note || ""));
  if(!m) return null;
  const n = parseInt(m[1], 10);
  return Number.isFinite(n) ? n : null;
}

function escapeHtml(s){
  return (s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function shortPath(path, maxLen = 94){
  const s = String(path || "");
  if(!s) return "—";
  if(s.length <= maxLen) return s;
  return "…" + s.slice(-(maxLen - 1));
}

function assistProfileLabel(v){
  if(v === "prudent") return "prudent";
  if(v === "agressif") return "agressif";
  return "equilibre";
}

function currentDecision(row){
  if(!row || !row.row_id){
    return { ok: false, title: "", year: 0, edited: false };
  }
  const d = state.decisions[row.row_id];
  if(d) return d;
  const ok = (row.confidence_label === "high") && row.proposed_year && row.proposed_title;
  state.decisions[row.row_id] = { ok, title: row.proposed_title, year: row.proposed_year, edited: false };
  return state.decisions[row.row_id];
}

function gatherDecisions(){
  const out = {};
  for(const [rowId, d] of Object.entries(state.decisions)){
    out[rowId] = { ok: !!d.ok, title: (d.title || "").trim(), year: parseInt(d.year || 0, 10) || 0 };
  }
  return out;
}

function renderRunSelectorRuns(runs){
  const tbody = $("selectorRunsTbody");
  if(!tbody) return;
  const list = Array.isArray(runs) ? runs : [];
  tbody.innerHTML = "";
  if(!list.length){
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="3" class="muted">Aucun run récent.</td>';
    tbody.appendChild(tr);
    return;
  }
  for(const run of list){
    const rid = String(run?.run_id || "");
    const selected = rid && rid === String(state.selectedRunForModal || "") ? "selectedRow" : "";
    const tr = document.createElement("tr");
    tr.className = selected;
    tr.innerHTML = [
      `<td><button class="btn smallBtn" data-select-run="${escapeHtml(rid)}">${escapeHtml(rid)}</button></td>`,
      `<td>${escapeHtml(fmtDateTime(run?.started_ts))}</td>`,
      `<td class="num">${Number(run?.total_rows || 0)}</td>`,
    ].join("");
    tbody.appendChild(tr);
  }
}

function renderRunSelectorRows(rows){
  const tbody = $("selectorRowsTbody");
  if(!tbody) return;
  const list = Array.isArray(rows) ? rows : [];
  tbody.innerHTML = "";
  if(!list.length){
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="3" class="muted">Sélectionnez un run pour afficher ses films.</td>';
    tbody.appendChild(tr);
    return;
  }
  for(const row of list){
    const title = String(row.proposed_title || "").trim() || "Film sans titre";
    const year = Number(row.proposed_year || 0);
    const label = year > 0 ? `${title} (${year})` : title;
    const tr = document.createElement("tr");
    tr.innerHTML = [
      `<td>${escapeHtml(label)}</td>`,
      `<td title="${escapeHtml(row.folder || "")}">${escapeHtml(shortPath(row.folder || ""))}</td>`,
      `<td><button class="btn smallBtn" data-select-row="${escapeHtml(String(row.row_id || ""))}">Choisir</button></td>`,
    ].join("");
    tbody.appendChild(tr);
  }
}

async function loadRunRowsForSelector(runId){
  const rid = String(runId || "").trim();
  const msg = $("selectorMsg");
  if(!rid){
    renderRunSelectorRows([]);
    if(msg) msg.textContent = "Sélectionnez un run.";
    return;
  }
  state.selectedRunForModal = rid;
  renderRunSelectorRuns(state.runsHistory || []);
  if(msg) msg.textContent = `Chargement des films du run ${rid}…`;
  const plan = await apiCall("get_plan(selector)", () => window.pywebview.api.get_plan(rid), {
    fallbackMessage: "Impossible de charger la liste des films pour ce run.",
  });
  if(!plan || !plan.ok){
    state.modalRows = [];
    renderRunSelectorRows([]);
    if(msg) msg.textContent = `Impossible de charger ce run: ${plan?.message || ""}`;
    return;
  }
  state.modalRows = Array.isArray(plan.rows) ? plan.rows : [];
  renderRunSelectorRows(state.modalRows);
  if(msg) msg.textContent = `${state.modalRows.length} film(s) disponibles dans ce run.`;
}

function applySelectedRowFromModal(rowId){
  const rid = String(state.selectedRunForModal || "").trim();
  const row = (state.modalRows || []).find((x) => String(x.row_id || "") === String(rowId || ""));
  if(!row){
    return;
  }
  if(rid){
    setLastRunContext(rid, null);
  }
  setSelectedFilmContext(row, rid);
  closeModal("modalRunSelector");
  if(rid){
    setPill("pillRun", "Run: " + rid);
  }
  if(state.runId && state.runId === rid){
    renderTable();
    if(String(state.rowsRunId || "").trim() !== rid || state.rows.length === 0){
      setStatusMessage("validationMsg", "Film sélectionné. Chargez la table pour ce run si vous voulez relire la validation.", { clearMs: 3200 });
    }
  }
}

async function openRunFilmSelector(preferredRunId){
  openModal("modalRunSelector");
  const msg = $("selectorMsg");
  if(msg) msg.textContent = "Chargement des runs récents…";
  state.modalRows = [];
  state.selectedRunForModal = null;
  renderRunSelectorRows([]);
  let runs = [];
  let loadFailed = false;
  try {
    const dash = await apiCall("get_dashboard(selector)", () => window.pywebview.api.get_dashboard("latest"), {
      fallbackMessage: "Impossible de charger les runs recents.",
    });
    if(dash?.ok){
      runs = Array.isArray(dash.runs_history) ? dash.runs_history : [];
      state.runsHistory = runs;
      rememberRunDirsFromHistory(runs);
      rememberRunDir(dash.run_id, dash.run_dir);
    } else {
      loadFailed = true;
      state.runsHistory = [];
      runs = [];
    }
  } catch(_e){
    loadFailed = true;
    state.runsHistory = [];
    runs = [];
  }
  renderRunSelectorRuns(runs);
  if(!runs.length){
    renderRunSelectorRows([]);
    if(msg) msg.textContent = loadFailed
      ? "Impossible de charger les runs récents. Réessayez."
      : "Aucun run disponible. Lancez une analyse.";
    return;
  }
  const wanted = String(preferredRunId || currentContextRunId() || runs[0]?.run_id || "").trim();
  await loadRunRowsForSelector(wanted);
}

async function openContextRunDir(){
  const btn = $("btnCtxOpenRun");
  const rid = currentContextRunId();
  if(!rid){
    flashActionButton(btn, "error");
    return;
  }
  const runPath = resolveRunDirFor(rid);
  if(!runPath){
    setStatusMessage("ctxRunHint", "Dossier du run indisponible pour ce contexte.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  await openPathWithFeedback(
    runPath,
    "ctxRunHint",
    "Impossible d'ouvrir le dossier du run.",
    {
      successMessage: "Dossier du run ouvert.",
      clearMs: 1800,
      triggerEl: btn,
    },
  );
}

function copyContextRun(){
  if(copyTextSafe(currentContextRunId())){
    const hint = $("ctxRunHint");
    if(hint) hint.textContent = "Run copié dans le presse-papiers.";
  }
}

function copyContextRow(){
  if(copyTextSafe(currentContextRowId())){
    const hint = $("ctxRunHint");
    if(hint) hint.textContent = "Identifiant film copié.";
  }
}

async function selectFilmFromContext(){
  await openRunFilmSelector(currentContextRunId() || state.lastRunId || "");
}

function setupContextBarEvents(){
  $("btnCtxSelectFilm")?.addEventListener("click", selectFilmFromContext);
  $("btnCtxOpenRun")?.addEventListener("click", openContextRunDir);
  $("btnCtxCopyRun")?.addEventListener("click", copyContextRun);
  $("btnCtxCopyRow")?.addEventListener("click", copyContextRow);
  $("btnIdsHelp")?.addEventListener("click", () => openModal("modalIdsHelp"));
  $("ckAdvancedMode")?.addEventListener("change", (e) => {
    setAdvancedMode(!!e.target?.checked);
  });
}

function setupRunSelectorEvents(){
  const modal = $("modalRunSelector");
  if(!modal) return;
  modal.addEventListener("click", async (e) => {
    const t = e.target;
    if(!t || !t.dataset) return;
    if(t.dataset.selectRun){
      await loadRunRowsForSelector(t.dataset.selectRun);
      return;
    }
    if(t.dataset.selectRow){
      applySelectedRowFromModal(t.dataset.selectRow);
    }
  });
}

function renderDashboardKeyValueList(targetId, obj, preferredOrder){
  const el = $(targetId);
  if(!el) return;
  const source = obj && typeof obj === "object" ? obj : {};
  const keysSet = new Set(Object.keys(source));
  const keys = [];
  for(const k of (preferredOrder || [])){
    if(keysSet.has(k)) keys.push(k);
  }
  for(const k of Object.keys(source)){
    if(!keys.includes(k)) keys.push(k);
  }
  if(!keys.length){
    el.textContent = "Aucune donnée.";
    return;
  }
  el.innerHTML = keys.map((k) => {
    const v = Number(source[k] || 0);
    return `<div class="kvLine"><span>${escapeHtml(k)}</span><b>${v}</b></div>`;
  }).join("");
}

function renderDashboardScoreBins(scoreBins){
  const host = $("dashScoreBins");
  if(!host) return;
  const bins = Array.isArray(scoreBins) ? scoreBins : [];
  if(!bins.length){
    host.innerHTML = '<div class="muted">Aucun score disponible.</div>';
    return;
  }
  const maxCount = Math.max(1, ...bins.map((b) => Number(b?.count || 0)));
  host.innerHTML = bins.map((b) => {
    const count = Number(b?.count || 0);
    const label = String(b?.label || "—");
    const pct = Math.max(2, Math.round((count * 100) / maxCount));
    return (
      `<div class="barRow">` +
        `<div class="barLabel">${escapeHtml(label)}</div>` +
        `<div class="barTrack"><div class="barFill" style="width:${pct}%"></div></div>` +
        `<div class="barCount">${count}</div>` +
      `</div>`
    );
  }).join("");
}

function renderDashboardAnomalies(anomalies){
  const tbody = $("dashAnomaliesTbody");
  if(!tbody) return;
  const rows = Array.isArray(anomalies) ? anomalies : [];
  tbody.innerHTML = "";
  if(!rows.length){
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="5" class="muted">Aucune anomalie.</td>';
    tbody.appendChild(tr);
    return;
  }
  for(const a of rows){
    const tr = document.createElement("tr");
    const path = String(a?.path || "");
    const action = String(a?.recommended_action || "");
    tr.innerHTML = [
      `<td>${severityBadge(a?.severity)}</td>`,
      `<td>${escapeHtml(String(a?.code || ""))}</td>`,
      `<td>${escapeHtml(String(a?.message || ""))}</td>`,
      `<td><button class="btn smallBtn pathBtn" data-open="${escapeHtml(path)}" title="${escapeHtml(path)}">${escapeHtml(shortPath(path))}</button></td>`,
      `<td>${escapeHtml(action || "—")}</td>`,
    ].join("");
    tbody.appendChild(tr);
  }
}

function renderDashboardOutlierRows(tbodyId, rows, opts){
  const tbody = $(tbodyId);
  if(!tbody) return;
  const list = Array.isArray(rows) ? rows : [];
  tbody.innerHTML = "";
  if(!list.length){
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="${opts?.withBitrate ? 3 : 2}" class="muted">Aucun cas.</td>`;
    tbody.appendChild(tr);
    return;
  }
  for(const x of list){
    const movie = formatMovieLabel(x);
    const path = String(x?.path || "");
    const tr = document.createElement("tr");
    if(opts?.withBitrate){
      tr.innerHTML = [
        `<td>${escapeHtml(movie)}</td>`,
        `<td class="num">${Number(x?.bitrate_kbps || 0)}</td>`,
        `<td><button class="btn smallBtn pathBtn" data-open="${escapeHtml(path)}" title="${escapeHtml(path)}">${escapeHtml(shortPath(path))}</button></td>`,
      ].join("");
    } else {
      tr.innerHTML = [
        `<td>${escapeHtml(movie)}</td>`,
        `<td><button class="btn smallBtn pathBtn" data-open="${escapeHtml(path)}" title="${escapeHtml(path)}">${escapeHtml(shortPath(path))}</button></td>`,
      ].join("");
    }
    tbody.appendChild(tr);
  }
}

function renderDashboardRunsHistory(runs){
  const tbody = $("dashRunsTbody");
  if(!tbody) return;
  const list = Array.isArray(runs) ? runs : [];
  tbody.innerHTML = "";
  if(!list.length){
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="7" class="muted">Aucun historique.</td>';
    tbody.appendChild(tr);
    return;
  }
  for(const r of list){
    const runId = String(r?.run_id || "");
    const tr = document.createElement("tr");
    tr.innerHTML = [
      `<td>${escapeHtml(runId || "—")}</td>`,
      `<td>${escapeHtml(fmtDateTime(r?.started_ts))}</td>`,
      `<td>${escapeHtml(fmtDurationSec(r?.duration_s))}</td>`,
      `<td class="num">${Number(r?.total_rows || 0)}</td>`,
      `<td class="num">${Number(r?.applied_rows || 0)}</td>`,
      `<td class="num">${Number(r?.errors_count || 0)}</td>`,
      `<td class="num">${Number(r?.anomalies_count || 0)}</td>`,
    ].join("");
    tbody.appendChild(tr);
  }
}

function clearDashboardView(){
  const simpleIds = [
    "dashRunDisplayed",
    "dashKpiScoreAvg",
    "dashKpiPremiumPct",
    "dashKpiScored",
    "dashKpiTotalMovies",
    "dashKpiProbePartial",
  ];
  simpleIds.forEach((id) => {
    const el = $(id);
    if(el) el.textContent = "—";
  });
  renderDashboardScoreBins([]);
  renderDashboardKeyValueList("dashResolutions", {}, []);
  renderDashboardKeyValueList("dashHdr", {}, []);
  renderDashboardKeyValueList("dashAudio", {}, []);
  renderDashboardAnomalies([]);
  renderDashboardOutlierRows("dashOutLowBitrate", [], { withBitrate: true });
  renderDashboardOutlierRows("dashOutSdr4k", [], { withBitrate: false });
  renderDashboardOutlierRows("dashOutVoMissing", [], { withBitrate: false });
  renderDashboardRunsHistory([]);
}

async function loadDashboard(forceRunId){
  const requestedInput = state.advancedMode ? String($("dashRunId")?.value || "").trim() : "";
  const requested = String(forceRunId || requestedInput || "latest").trim() || "latest";
  setStatusMessage("dashMsg", "Chargement du dashboard...", { loading: true });
  state.dashboard = null;
  state.runsHistory = [];
  clearDashboardView();
  try {
    const r = await apiCall("get_dashboard", () => window.pywebview.api.get_dashboard(requested), {
      statusId: "dashMsg",
      fallbackMessage: "Erreur lors du chargement du dashboard.",
    });
    if(!r || !r.ok){
      setStatusMessage("dashMsg", `Erreur dashboard : ${r?.message || "inconnue"}`, { error: true });
      return;
    }

    state.dashboard = r;
    rememberRunDir(r.run_id, r.run_dir);
    const kpis = r.kpis || {};
    const dist = r.distributions || {};
    const outliers = r.outliers || {};
    const runId = String(r.run_id || "");
    state.runsHistory = Array.isArray(r.runs_history) ? r.runs_history : [];
    rememberRunDirsFromHistory(state.runsHistory);

    $("dashRunDisplayed").textContent = runId || "Aucun";
    $("dashKpiScoreAvg").textContent = `${Number(kpis.score_avg || 0).toFixed(1)}/100`;
    $("dashKpiPremiumPct").textContent = `${Number(kpis.score_premium_pct || 0).toFixed(1)}%`;
    $("dashKpiScored").textContent = `${Number(kpis.scored_movies || 0)}`;
    $("dashKpiTotalMovies").textContent = `${Number(kpis.total_movies || 0)}`;
    $("dashKpiProbePartial").textContent = `${Number(kpis.probe_partial_count || 0)}`;

    if($("dashRunId") && state.advancedMode && (!$("dashRunId").value || requested === "latest")){
      $("dashRunId").value = runId || "latest";
    }

    renderDashboardScoreBins(dist.score_bins || []);
    renderDashboardKeyValueList("dashResolutions", dist.resolutions || {}, ["2160p", "1080p", "720p", "other"]);
    renderDashboardKeyValueList("dashHdr", dist.hdr || {}, ["DV", "HDR10+", "HDR10", "SDR", "Unknown"]);
    const audioObj = {};
    for(const a of (dist.audio_codecs || [])){
      audioObj[String(a?.label || "Autre")] = Number(a?.count || 0);
    }
    renderDashboardKeyValueList("dashAudio", audioObj, ["TrueHD/Atmos", "DTS-HD MA", "DTS", "AAC", "Autre"]);
    renderDashboardAnomalies(r.anomalies_top || []);
    renderDashboardOutlierRows("dashOutLowBitrate", outliers.low_bitrate || [], { withBitrate: true });
    renderDashboardOutlierRows("dashOutSdr4k", outliers.sdr_4k || [], { withBitrate: false });
    renderDashboardOutlierRows("dashOutVoMissing", outliers.vo_missing || [], { withBitrate: false });
    renderDashboardRunsHistory(r.runs_history || []);

    setStatusMessage("dashMsg", String(r.message || "Dashboard chargé."));
  } catch(err){
    setStatusMessage("dashMsg", `Erreur dashboard : ${String(err || "")}`, { error: true });
  }
}

function hookDashboardEvents(){
  const dashView = $("view-dashboard");
  if(!dashView) return;
  dashView.addEventListener("click", async (e) => {
    const t = e.target;
    if(!t || !t.dataset || !t.dataset.open) return;
    await openPathWithFeedback(t.dataset.open, "dashMsg", "Impossible d'ouvrir ce dossier.", {
      successMessage: "Chemin ouvert.",
      clearMs: 1800,
      triggerEl: t,
    });
  });
}

async function persistValidation(){
  if(!state.runId) return { ok: false, message: "Run non défini." };
  return await apiCall("save_validation", () => window.pywebview.api.save_validation(state.runId, gatherDecisions()), {
    fallbackMessage: "Erreur lors de la sauvegarde de la validation.",
  });
}

async function saveValidationFromUI(){
  const btn = $("btnSaveValidation");
  if(!state.runId){
    setStatusMessage("validationMsg", "Lancez d'abord une analyse.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  setStatusMessage("validationMsg", "Sauvegarde...", { loading: true });
  const r = await persistValidation();
  setStatusMessage("validationMsg", r.ok ? "Validation enregistrée." : `Erreur : ${r.message || ""}`, { error: !r.ok, success: !!r.ok });
  flashActionButton(btn, r?.ok ? "ok" : "error");
  clearStatusMessageLater("validationMsg", 2500);
}

function setOnboardingBadge(id, tone, text){
  const el = $(id);
  if(!el) return;
  const cls = tone === "ok" ? "ok" : tone === "warn" ? "med" : "bad";
  el.className = `badge ${cls}`;
  el.textContent = String(text || "—");
}

function renderOperatorDiagnostic(){
  if(!$("operatorDiagPanel")) return;

  const root = String($("inRoot")?.value || "").trim();
  const stateDir = String($("inState")?.value || "").trim();
  const tmdbEnabled = !!$("ckTmdbEnabled")?.checked;
  const tmdbKey = String($("inApiKey")?.value || "").trim();
  const rememberKey = !!$("ckRememberKey")?.checked;
  const probeBackend = String($("selProbeBackend")?.value || state.settings?.probe_backend || "auto").trim().toLowerCase();
  const dryRun = !!$("ckDryRun")?.checked;
  const quarantine = !!$("ckQuarantine")?.checked;
  const moveEmptyFolders = !!$("ckMoveEmptyFoldersEnabled")?.checked;
  const emptyScope = String($("selEmptyFoldersScope")?.value || "root_all").trim().toLowerCase();

  const probePayload = (state.probeToolsStatus && typeof state.probeToolsStatus === "object")
    ? state.probeToolsStatus
    : null;
  const tools = (probePayload && typeof probePayload.tools === "object") ? probePayload.tools : {};
  const ffOk = !!tools?.ffprobe?.available;
  const miOk = !!tools?.mediainfo?.available;
  const pathsReady = !!root && !!stateDir;

  let tmdbTone = "warn";
  let tmdbLabel = "Inactif";
  let tmdbHint = "TMDb desactive : analyse locale uniquement.";
  if(tmdbEnabled){
    if(!tmdbKey){
      tmdbTone = "bad";
      tmdbLabel = "A completer";
      tmdbHint = "TMDb active sans cle API.";
    } else if(state.tmdbLastTestOk === false){
      tmdbTone = "bad";
      tmdbLabel = "Test KO";
      tmdbHint = "La derniere verification TMDb a echoue.";
    } else if(state.tmdbLastTestOk === true){
      tmdbTone = "ok";
      tmdbLabel = "Actif";
      tmdbHint = "TMDb actif et cle testee.";
    } else {
      tmdbTone = "warn";
      tmdbLabel = "Actif";
      tmdbHint = "TMDb actif. Teste la cle pour valider la connexion.";
    }
  }
  setOnboardingBadge("operatorDiagTmdbBadge", tmdbTone, tmdbLabel);
  if($("operatorDiagTmdbHint")) $("operatorDiagTmdbHint").textContent = tmdbHint;

  let keyTone = "bad";
  let keyLabel = "Absente";
  let keyHint = "Aucune cle TMDb renseignee.";
  if(tmdbKey){
    keyTone = rememberKey ? "ok" : "warn";
    keyLabel = "Presente";
    keyHint = rememberKey
      ? "Cle disponible et memorisee dans settings.json."
      : "Cle disponible pour cette session, mais non memorisee.";
  } else if(!tmdbEnabled){
    keyTone = "warn";
    keyLabel = "Non utilisee";
    keyHint = "TMDb est desactive, la cle n'est pas necessaire.";
  }
  setOnboardingBadge("operatorDiagKeyBadge", keyTone, keyLabel);
  if($("operatorDiagKeyHint")) $("operatorDiagKeyHint").textContent = keyHint;

  let probeTone = "bad";
  let probeLabel = "À vérifier";
  let probeHint = "Lance la détection des outils d'analyse vidéo.";
  if(probeBackend === "none"){
    probeTone = "warn";
    probeLabel = "Desactive";
    probeHint = "Analyse vidéo désactivée : score qualité partiel.";
  } else if(probePayload){
    if(probeBackend === "auto"){
      if(ffOk && miOk){
        probeTone = "ok";
        probeLabel = "Hybride";
        probeHint = "ffprobe + MediaInfo detectes.";
      } else if(ffOk || miOk){
        probeTone = "warn";
        probeLabel = "Partiel";
        probeHint = ffOk ? "ffprobe detecte seul." : "MediaInfo detecte seul.";
      } else {
        probeTone = "bad";
        probeLabel = "Manquant";
        probeHint = "Aucun outil probe disponible.";
      }
    } else if(probeBackend === "ffprobe"){
      probeTone = ffOk ? "ok" : "bad";
      probeLabel = ffOk ? "ffprobe" : "Manquant";
      probeHint = ffOk ? "Backend ffprobe disponible." : "ffprobe requis pour ce mode.";
    } else {
      probeTone = miOk ? "ok" : "bad";
      probeLabel = miOk ? "MediaInfo" : "Manquant";
      probeHint = miOk ? "Backend MediaInfo disponible." : "MediaInfo requis pour ce mode.";
    }
  }
  setOnboardingBadge("operatorDiagProbeBadge", probeTone, probeLabel);
  if($("operatorDiagProbeHint")) $("operatorDiagProbeHint").textContent = probeHint;

  const dryTone = dryRun ? "ok" : "warn";
  const dryLabel = dryRun ? "Actif" : "Desactive";
  const dryHint = dryRun
    ? "Aucun mouvement réel pendant l'application."
    : "Application réelle autorisée si tu lances l'exécution.";
  setOnboardingBadge("operatorDiagDryRunBadge", dryTone, dryLabel);
  if($("operatorDiagDryRunHint")) $("operatorDiagDryRunHint").textContent = dryHint;

  let emptyTone = "warn";
  let emptyLabel = "Desactive";
  let emptyHint = "Les dossiers vides ne seront pas deplaces.";
  if(moveEmptyFolders){
    if(emptyScope === "touched_only"){
      emptyTone = "ok";
      emptyLabel = "Prudent";
      emptyHint = "Seuls les dossiers vides touches par ce run seront deplaces.";
    } else {
      emptyTone = "bad";
      emptyLabel = "Etendu";
      emptyHint = "Tous les dossiers vides sous ROOT peuvent etre deplaces.";
    }
  }
  setOnboardingBadge("operatorDiagEmptyBadge", emptyTone, emptyLabel);
  if($("operatorDiagEmptyHint")) $("operatorDiagEmptyHint").textContent = emptyHint;

  let safetyTone = "warn";
  let safetyLabel = "Standard";
  if(dryRun){
    safetyTone = "ok";
    safetyLabel = "Prudent";
  } else if(quarantine && (!moveEmptyFolders || emptyScope === "touched_only")){
    safetyTone = "ok";
    safetyLabel = "Prudent";
  } else if(!quarantine && moveEmptyFolders && emptyScope === "root_all"){
    safetyTone = "bad";
    safetyLabel = "Agressif";
  }
  const safetyHint = `Quarantaine ${quarantine ? "activee" : "desactivee"} • Dossiers vides ${moveEmptyFolders ? (emptyScope === "touched_only" ? "prudents" : "etendus") : "desactives"}`;
  setOnboardingBadge("operatorDiagSafetyBadge", safetyTone, safetyLabel);
  if($("operatorDiagSafetyHint")) $("operatorDiagSafetyHint").textContent = safetyHint;

  const ready = pathsReady && (!tmdbEnabled || !!tmdbKey) && (probeBackend === "none" || probeTone !== "bad");
  const hasWarn = tmdbTone === "warn" || keyTone === "warn" || probeTone === "warn" || dryTone === "warn" || safetyTone === "warn" || emptyTone === "warn";
  if(ready && !hasWarn){
    setOnboardingBadge("operatorDiagOverallBadge", "ok", "Pret");
  } else if(ready){
    setOnboardingBadge("operatorDiagOverallBadge", "warn", "Pret (surveille)");
  } else {
    setOnboardingBadge("operatorDiagOverallBadge", "bad", "À vérifier");
  }
}

function updateOnboardingStatus(){
  const root = String($("inRoot")?.value || "").trim();
  const stateDir = String($("inState")?.value || "").trim();
  const tmdbEnabled = !!$("ckTmdbEnabled")?.checked;
  const tmdbKey = String($("inApiKey")?.value || "").trim();
  const probeBackend = String($("selProbeBackend")?.value || state.settings?.probe_backend || "auto").trim().toLowerCase();

  const pathsDone = !!root && !!stateDir;
  const pathsHint = pathsDone
    ? `ROOT: ${shortPath(root, 56)} • STATE_DIR: ${shortPath(stateDir, 56)}`
    : "Renseigne ROOT et STATE_DIR.";
  setOnboardingBadge("onboardingPathsBadge", pathsDone ? "ok" : "bad", pathsDone ? "OK" : "À faire");
  if($("onboardingPathsHint")) $("onboardingPathsHint").textContent = pathsHint;

  let tmdbDone = true;
  let tmdbTone = "ok";
  let tmdbLabel = "OK";
  let tmdbHint = "TMDb désactivé: mode local uniquement.";
  if(tmdbEnabled){
    if(!tmdbKey){
      tmdbDone = false;
      tmdbTone = "bad";
      tmdbLabel = "Clé manquante";
      tmdbHint = "Ajoute une clé API TMDb ou désactive TMDb.";
    } else if(state.tmdbLastTestOk === false){
      tmdbDone = false;
      tmdbTone = "bad";
      tmdbLabel = "Test KO";
      tmdbHint = "La dernière vérification TMDb a échoué. Vérifie la clé.";
    } else if(state.tmdbLastTestOk === true){
      tmdbHint = "Clé API TMDb testée avec succès.";
    } else {
      tmdbTone = "warn";
      tmdbLabel = "À tester";
      tmdbHint = "Clé renseignée. Lance 'Tester TMDb' pour valider.";
    }
  }
  setOnboardingBadge("onboardingTmdbBadge", tmdbTone, tmdbLabel);
  if($("onboardingTmdbHint")) $("onboardingTmdbHint").textContent = tmdbHint;

  const probePayload = (state.probeToolsStatus && typeof state.probeToolsStatus === "object")
    ? state.probeToolsStatus
    : null;
  const tools = (probePayload && typeof probePayload.tools === "object") ? probePayload.tools : {};
  const ffOk = !!tools?.ffprobe?.available;
  const miOk = !!tools?.mediainfo?.available;

  let probeDone = false;
  let probeTone = "bad";
  let probeLabel = "À vérifier";
  let probeHint = "Lance la détection des outils d'analyse.";
  if(probeBackend === "none"){
    probeDone = true;
    probeTone = "warn";
    probeLabel = "Désactivé";
    probeHint = "Mode probe désactivé: score qualité basé sur infos partielles.";
  } else if(probePayload){
    if(probeBackend === "auto"){
      if(ffOk && miOk){
        probeDone = true;
        probeTone = "ok";
        probeLabel = "Hybride OK";
        probeHint = "ffprobe + MediaInfo détectés.";
      } else if(ffOk || miOk){
        probeDone = true;
        probeTone = "warn";
        probeLabel = "Partiel";
        probeHint = "Un seul outil détecté. Le mode dégradé reste utilisable.";
      } else {
        probeDone = false;
        probeTone = "bad";
        probeLabel = "Manquant";
        probeHint = "Aucun outil probe disponible.";
      }
    } else if(probeBackend === "ffprobe"){
      probeDone = ffOk;
      probeTone = ffOk ? "ok" : "bad";
      probeLabel = ffOk ? "OK" : "Manquant";
      probeHint = ffOk ? "ffprobe détecté." : "ffprobe requis pour ce mode.";
    } else {
      probeDone = miOk;
      probeTone = miOk ? "ok" : "bad";
      probeLabel = miOk ? "OK" : "Manquant";
      probeHint = miOk ? "MediaInfo détecté." : "MediaInfo requis pour ce mode.";
    }
  }
  setOnboardingBadge("onboardingProbeBadge", probeTone, probeLabel);
  if($("onboardingProbeHint")) $("onboardingProbeHint").textContent = probeHint;

  const ready = pathsDone && tmdbDone && probeDone;
  const hasWarn = tmdbTone === "warn" || probeTone === "warn";
  if(ready && hasWarn){
    setOnboardingBadge("onboardingOverallBadge", "warn", "Prêt (partiel)");
  } else if(ready){
    setOnboardingBadge("onboardingOverallBadge", "ok", "Prêt");
  } else {
    setOnboardingBadge("onboardingOverallBadge", "bad", "Incomplet");
  }
  renderOperatorDiagnostic();
  renderApplyCleanupDiagnostic();
}

async function loadSettings(){
  const s = await apiCall("get_settings", () => window.pywebview.api.get_settings(), {
    statusId: "saveMsg",
    fallbackMessage: "Impossible de charger les paramètres.",
  });
  if(!s || s.ok === false){
    return;
  }
  state.settings = s;

  $("inRoot").value = s.root || "";
  $("inState").value = s.state_dir || "";
  $("ckTmdbEnabled").checked = !!s.tmdb_enabled;
  $("inTimeout").value = s.tmdb_timeout_s || 10;
  $("ckCollectionMove").checked = !!s.collection_folder_enabled;
  $("inCollectionFolderName").value = s.collection_folder_name || "_Collection";
  $("inEmptyFoldersFolderName").value = s.empty_folders_folder_name || "_Vide";
  $("ckMoveEmptyFoldersEnabled").checked = !!s.move_empty_folders_enabled;
  $("inResidualCleanupFolderName").value = s.cleanup_residual_folders_folder_name || "_Dossier Nettoyage";
  $("ckResidualCleanupEnabled").checked = !!s.cleanup_residual_folders_enabled;
  $("selResidualCleanupScope").value = (s.cleanup_residual_folders_scope === "root_all") ? "root_all" : "touched_only";
  $("ckResidualIncludeNfo").checked = !!s.cleanup_residual_include_nfo;
  $("ckResidualIncludeImages").checked = !!s.cleanup_residual_include_images;
  $("ckResidualIncludeSubtitles").checked = !!s.cleanup_residual_include_subtitles;
  $("ckResidualIncludeTexts").checked = !!s.cleanup_residual_include_texts;
  $("ckIncrementalScanEnabled").checked = !!s.incremental_scan_enabled;
  $("selEmptyFoldersScope").value = (s.empty_folders_scope === "touched_only") ? "touched_only" : "root_all";

  $("ckDryRun").checked = !!s.dry_run_apply;
  $("ckQuarantine").checked = !!s.quarantine_unapproved;

  $("inApiKey").value = s.tmdb_api_key || "";
  $("ckRememberKey").checked = !!s.remember_key;
  state.tmdbLastTestOk = null;
  if($("inProbeFfprobePath")) $("inProbeFfprobePath").value = String(s.ffprobe_path || "");
  if($("inProbeMediainfoPath")) $("inProbeMediainfoPath").value = String(s.mediainfo_path || "");
  if($("selProbeBackend")) $("selProbeBackend").value = String(s.probe_backend || "auto");

  setStatusMessage("saveMsg", "");
  updateContextBar();
  updateOnboardingStatus();
}

function setTmdbBadge(ok, msg){
  state.tmdbLastTestOk = !!ok;
  const b = $("tmdbTestBadge");
  b.className = "badge " + (ok ? "ok" : "bad");
  b.textContent = ok ? "OK" : "KO";
  setStatusMessage("tmdbTestMsg", msg || "", { error: !ok, success: !!ok });
  updateOnboardingStatus();
}

async function testKey(){
  const btn = $("btnTestKey");
  setStatusMessage("tmdbTestMsg", "Test en cours...", { loading: true });
  $("tmdbTestBadge").className = "badge neutral";
  $("tmdbTestBadge").textContent = "...";

  const key = $("inApiKey").value;
  const sd = $("inState").value;
  const timeout = parseFloat($("inTimeout").value || "10");

  const r = await apiCall("test_tmdb_key", () => window.pywebview.api.test_tmdb_key(key, sd, timeout), {
    statusId: "tmdbTestMsg",
    fallbackMessage: "Impossible de tester la clé TMDb.",
  });
  setTmdbBadge(!!r.ok, r.message || "");
  flashActionButton(btn, r?.ok ? "ok" : "error");
}

async function saveSettings(opts = {}){
  const btn = $("btnSaveSettings");
  const previousStateDir = String(state.settings?.state_dir || "").trim();
  const settings = {
    root: $("inRoot").value,
    state_dir: $("inState").value,
    tmdb_enabled: $("ckTmdbEnabled").checked,
    tmdb_timeout_s: parseFloat($("inTimeout").value || "10"),
    tmdb_api_key: $("inApiKey").value,
    remember_key: $("ckRememberKey").checked,
    collection_folder_enabled: $("ckCollectionMove").checked,
    collection_folder_name: $("inCollectionFolderName").value,
    empty_folders_folder_name: $("inEmptyFoldersFolderName").value,
    move_empty_folders_enabled: $("ckMoveEmptyFoldersEnabled").checked,
    cleanup_residual_folders_folder_name: $("inResidualCleanupFolderName").value,
    cleanup_residual_folders_enabled: $("ckResidualCleanupEnabled").checked,
    cleanup_residual_folders_scope: $("selResidualCleanupScope").value,
    cleanup_residual_include_nfo: $("ckResidualIncludeNfo").checked,
    cleanup_residual_include_images: $("ckResidualIncludeImages").checked,
    cleanup_residual_include_subtitles: $("ckResidualIncludeSubtitles").checked,
    cleanup_residual_include_texts: $("ckResidualIncludeTexts").checked,
    incremental_scan_enabled: $("ckIncrementalScanEnabled").checked,
    empty_folders_scope: $("selEmptyFoldersScope").value,
    quarantine_unapproved: $("ckQuarantine").checked,
    dry_run_apply: $("ckDryRun").checked,
    probe_backend: $("selProbeBackend")?.value || "auto",
    ffprobe_path: $("inProbeFfprobePath")?.value || "",
    mediainfo_path: $("inProbeMediainfoPath")?.value || "",
  };

  const r = await apiCall("save_settings", () => window.pywebview.api.save_settings(settings), {
    statusId: "saveMsg",
    fallbackMessage: "Erreur d'enregistrement des paramètres.",
  });
  if(!opts.silent){
    const tmdbNotRemembered = !!(
      r?.ok &&
      settings.tmdb_enabled &&
      String(settings.tmdb_api_key || "").trim() &&
      !settings.remember_key
    );
    const msg = r.ok
      ? (tmdbNotRemembered
        ? "Paramètres enregistrés. La clé TMDb n'est pas mémorisée et devra être ressaisie après relance."
        : "Paramètres enregistrés.")
      : `Erreur : ${r.message || "enregistrement impossible."}`;
    setStatusMessage("saveMsg", msg, { error: !r.ok, success: !!r.ok });
    flashActionButton(btn, r?.ok ? "ok" : "error");
    clearStatusMessageLater("saveMsg", 2500);
  }
  if(r?.ok){
    const persistedTmdbKey = r.tmdb_key_persisted ? String(settings.tmdb_api_key || "").trim() : "";
    const nextStateDir = String(r.state_dir || settings.state_dir || "").trim();
    state.settings = {
      ...(state.settings || {}),
      ...settings,
      tmdb_api_key: persistedTmdbKey,
      remember_key: !!r.tmdb_key_persisted,
      state_dir: nextStateDir,
    };
    if(previousStateDir && nextStateDir && previousStateDir !== nextStateDir){
      clearRunCachesForStateDirChange();
    }
    updateOnboardingStatus();
  }
  return r;
}

async function startPlan(){
  const btnStart = $("btnStartPlan");
  const saved = await saveSettings({ silent: true });
  if(!saved || !saved.ok){
    setStatusMessage("planMsg", `Impossible de lancer l'analyse: ${saved?.message || "paramètres invalides."}`, { error: true });
    flashActionButton(btnStart, "error");
    return;
  }

  $("btnStartPlan").disabled = true;
  $("btnLoadTable").disabled = true;
  $("btnOpenRunDir").disabled = true;
  setStatusMessage("planMsg", "Analyse en cours... les informations se mettent à jour automatiquement.", { loading: true });
  $("logboxPlan").textContent = "";

  state.logIndex = 0;
  resetRunScopedState();
  updateContextBar();
  renderDuplicatesView({ total_groups: 0, checked_rows: 0, groups: [] });

  const settings = {
    root: $("inRoot").value,
    state_dir: $("inState").value,
    tmdb_enabled: $("ckTmdbEnabled").checked,
    tmdb_timeout_s: parseFloat($("inTimeout").value || "10"),
    tmdb_api_key: $("inApiKey").value,
    collection_folder_enabled: $("ckCollectionMove").checked,
    collection_folder_name: $("inCollectionFolderName").value,
    empty_folders_folder_name: $("inEmptyFoldersFolderName").value,
    move_empty_folders_enabled: $("ckMoveEmptyFoldersEnabled").checked,
    cleanup_residual_folders_folder_name: $("inResidualCleanupFolderName").value,
    cleanup_residual_folders_enabled: $("ckResidualCleanupEnabled").checked,
    cleanup_residual_folders_scope: $("selResidualCleanupScope").value,
    cleanup_residual_include_nfo: $("ckResidualIncludeNfo").checked,
    cleanup_residual_include_images: $("ckResidualIncludeImages").checked,
    cleanup_residual_include_subtitles: $("ckResidualIncludeSubtitles").checked,
    cleanup_residual_include_texts: $("ckResidualIncludeTexts").checked,
    incremental_scan_enabled: $("ckIncrementalScanEnabled").checked,
    empty_folders_scope: $("selEmptyFoldersScope").value,
    probe_backend: $("selProbeBackend")?.value || "auto",
    ffprobe_path: $("inProbeFfprobePath")?.value || "",
    mediainfo_path: $("inProbeMediainfoPath")?.value || "",
  };

  const r = await apiCall("start_plan", () => window.pywebview.api.start_plan(settings), {
    statusId: "planMsg",
    fallbackMessage: "Erreur de démarrage de l'analyse.",
  });
  if(!r.ok){
    setStatusMessage("planMsg", "Erreur : " + (r.message || ""), { error: true });
    $("btnStartPlan").disabled = false;
    $("btnLoadTable").disabled = true;
    flashActionButton(btnStart, "error");
    return;
  }

  state.runId = r.run_id;
  state.runDir = r.run_dir;
  setLastRunContext(state.runId, state.runDir);
  setPill("pillRun", "Run: " + state.runId);
  setPill("pillStatus", "En cours");

  $("btnOpenRunDir").disabled = false;
  flashActionButton(btnStart, "ok");
  showView("plan");

  if(state.polling) clearInterval(state.polling);
  state.pollInFlight = false;
  state.polling = setInterval(pollStatus, 650);
}

async function pollStatus(){
  if(!state.runId) return;
  if(state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    const r = await apiCall("get_status", () => window.pywebview.api.get_status(state.runId, state.logIndex), {
      fallbackMessage: "Impossible de récupérer l'état du run.",
    });
    if(!r.ok){
      setStatusMessage("planMsg", "Impossible de récupérer l'état du run. Réessayez dans quelques secondes.", { error: true });
      return;
    }

    const idx = r.idx || 0;
    const total = r.total || 0;
    const pct = (total > 0) ? Math.floor((idx / total) * 100) : 0;
    $("progressFill").style.width = pct + "%";
    $("progCount").textContent = `${idx}/${total}`;
    $("progSpeed").textContent = fmtSpeed(r.speed || 0);
    $("progEta").textContent = fmtEta(r.eta_s || 0);
    $("progCurrent").textContent = shortPath(r.current || "—", 150);
    $("progCurrent").title = String(r.current || "—");

    appendLogs("logboxPlan", r.logs);
    state.logIndex = r.next_log_index || state.logIndex;

    if(r.error){
      setPill("pillStatus", "Erreur");
      setStatusMessage("planMsg", "Erreur : " + r.error, { error: true });
      $("btnStartPlan").disabled = false;
      $("btnLoadTable").disabled = true;
      clearInterval(state.polling);
      state.polling = null;
      return;
    }

    if(r.done){
      setPill("pillStatus", "Termine");
      if((r.total || 0) <= 0){
        setStatusMessage("planMsg", "Analyse terminée : aucun dossier vidéo détecté.");
      } else {
        setStatusMessage("planMsg", "Plan prêt. Cliquez sur \"Charger la table de validation\".");
      }
      $("btnStartPlan").disabled = false;
      $("btnLoadTable").disabled = false;
      clearInterval(state.polling);
      state.polling = null;
    }
  } finally {
    state.pollInFlight = false;
  }
}

async function openRunDir(){
  const btn = $("btnOpenRunDir");
  if(state.runDir){
    await openPathWithFeedback(state.runDir, "planMsg", "Impossible d'ouvrir le dossier du run.", {
      successMessage: "Dossier du run ouvert.",
      clearMs: 1800,
      triggerEl: btn,
    });
    return;
  }
  await openContextRunDir();
}

async function exportCurrentRunReport(format, triggerEl){
  const runId = currentContextRunId();
  const fmt = String(format || "json").trim().toLowerCase();
  const btn = (typeof triggerEl === "string") ? $(triggerEl) : triggerEl;
  if(!runId){
    setStatusMessage("logsMsg", "Choisissez un run avant d'exporter un rapport.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  setStatusMessage("logsMsg", `Export ${fmt.toUpperCase()} en cours...`, { loading: true });
  const r = await apiCall("export_run_report", () => window.pywebview.api.export_run_report(runId, fmt), {
    statusId: "logsMsg",
    fallbackMessage: "Impossible d'exporter le rapport de run.",
  });
  if(!r?.ok){
    setStatusMessage("logsMsg", `Erreur export: ${r?.message || "inconnue"}`, { error: true });
    flashActionButton(btn, "error");
    return;
  }
  const rowsTotal = Number(r.rows_total || 0);
  const outPath = String(r.path || "");
  const msg = `Rapport ${fmt.toUpperCase()} exporté (${rowsTotal} lignes) : ${shortPath(outPath, 120)}`;
  setStatusMessage("logsMsg", msg, { success: true, clearMs: 4200 });
  flashActionButton(btn, "ok");
}

async function loadTable(){
  const targetRunId = String(state.runId || "").trim();
  if(!targetRunId) return false;
  const hadForeignSelection = !!state.selectedRunId && String(state.selectedRunId || "").trim() !== targetRunId;
  if(state.rowsRunId && String(state.rowsRunId || "").trim() !== targetRunId){
    resetRunScopedState();
  }
  const r = await apiCall("get_plan", () => window.pywebview.api.get_plan(state.runId), {
    statusId: "planMsg",
    fallbackMessage: "Impossible de charger la table de validation.",
  });
  if(!r.ok){
    setStatusMessage("planMsg", "Erreur : " + (r.message || ""), { error: true });
    return false;
  }
  setRows(r.rows || [], targetRunId);
  state.duplicates = null;
  state.decisions = {};
  state.selectedRunId = targetRunId;
  state.lastRunId = targetRunId;
  if(hadForeignSelection){
    clearSelectedFilmContext();
  }
  persistContextToStorage();
  updateContextBar();

  try {
    const v = await apiCall("load_validation", () => window.pywebview.api.load_validation(state.runId));
    if(v && v.ok && v.decisions){
      state.decisions = v.decisions;
    }
  } catch(_e) {
    // no-op
  }
  if(state.selectedRowId && !findRowById(state.selectedRowId)){
    clearSelectedFilmContext();
    persistContextToStorage();
    updateContextBar();
  }

  if(state.rows.length === 0){
    setStatusMessage("planMsg", "Plan chargé : aucune ligne à valider pour ce run.");
  } else {
    setStatusMessage("planMsg", `${state.rows.length} lignes chargées. Ouvrez l'onglet \"Validation\".`);
  }

  showView("validate");
  renderTable();
  return true;
}

function hookTableEvents(){
  $("planTbody").addEventListener("change", (e) => {
    const t = e.target;
    if(t && t.dataset && t.dataset.ok){
      const id = t.dataset.ok;
      const row = findRowById(id);
      const d = currentDecision(row);
      d.ok = t.checked;
    }
  });

  $("planTbody").addEventListener("input", (e) => {
    const t = e.target;
    if(t && t.dataset && t.dataset.title){
      const id = t.dataset.title;
      const row = findRowById(id);
      const d = currentDecision(row);
      d.title = t.value;
      d.edited = true;
      t.classList.add("edited");
    }
    if(t && t.dataset && t.dataset.year){
      const id = t.dataset.year;
      const row = findRowById(id);
      const d = currentDecision(row);
      d.year = parseInt(t.value || "0", 10) || 0;
      d.edited = true;
      t.classList.add("edited");
    }
  });

  $("planTbody").addEventListener("change", (e) => {
    const t = e.target;
    if(t && t.dataset && t.dataset.yearSelect){
      const id = t.dataset.yearSelect;
      const row = findRowById(id);
      const d = currentDecision(row);
      const y = parseInt(t.value || "0", 10) || 0;
      d.year = y;
      d.edited = true;

      const inp = document.querySelector(`input[data-year="${id}"]`);
      if(inp){
        inp.value = y;
        inp.classList.add("edited");
      }
    }
  });

  $("planTbody").addEventListener("click", async (e) => {
    const t = e.target;
    if(!t) return;
    const tr = t.closest("tr[data-row-id]");
    if(tr && tr.dataset.rowId){
      setSelectedFilmById(tr.dataset.rowId, state.runId);
      updateSelectedRowVisual();
    }
    if(!t.dataset) return;

    if(t.dataset.cand){
      await showCandidates(t.dataset.cand);
    }
    if(t.dataset.open){
      await openPathWithFeedback(t.dataset.open, "validationMsg", "Impossible d'ouvrir ce dossier.", {
        successMessage: "Dossier ouvert.",
        clearMs: 1600,
        triggerEl: t,
      });
    }
    if(t.dataset.pick){
      const id = t.dataset.pick;
      const title = t.dataset.ptitle || "";
      const year = parseInt(t.dataset.pyear || "0", 10) || 0;
      const row = findRowById(id);
      const d = currentDecision(row);
      d.title = title;
      d.year = year || d.year;
      d.ok = true;
      d.edited = true;

      const tit = document.querySelector(`input[data-title="${id}"]`);
      if(tit){ tit.value = title; tit.classList.add("edited"); }
      const yin = document.querySelector(`input[data-year="${id}"]`);
      if(yin && year){ yin.value = year; yin.classList.add("edited"); }
      const chk = document.querySelector(`input[data-ok="${id}"]`);
      if(chk){ chk.checked = true; }
      setSelectedFilmById(id, state.runId);
      renderTable();
      closeModal("modalCandidates");
    }
  });
}

function bestAssistantCandidate(row, profile){
  const mode = profile || "equilibre";
  const rules = {
    prudent: { nfoMin: 0.88, tmdbMin: 0.91, tmdbLoose: 0.96, tmdbDy: 1, tmdbDyLoose: 2, nameMin: 0.76 },
    equilibre: { nfoMin: 0.85, tmdbMin: 0.86, tmdbLoose: 0.95, tmdbDy: 1, tmdbDyLoose: 3, nameMin: 0.72 },
    agressif: { nfoMin: 0.82, tmdbMin: 0.82, tmdbLoose: 0.90, tmdbDy: 1, tmdbDyLoose: 2, nameMin: 0.66 },
  }[mode] || { nfoMin: 0.85, tmdbMin: 0.86, tmdbLoose: 0.95, tmdbDy: 1, tmdbDyLoose: 3, nameMin: 0.72 };

  const cands = (row.candidates || []).slice().sort((a, b) => (b.score || 0) - (a.score || 0));
  if(!cands.length) return null;
  const c = cands[0];
  const score = Number(c.score || 0);
  if(!c.year || !c.title) return null;

  if(c.source === "nfo" && score >= rules.nfoMin) return c;
  if(c.source === "tmdb" && score >= rules.tmdbMin){
    const dy = parseYearDelta(c.note);
    if(dy === null || dy <= rules.tmdbDy) return c;
    if(score >= rules.tmdbLoose && dy <= rules.tmdbDyLoose) return c;
  }
  if(c.source === "name" && score >= rules.nameMin) return c;
  return null;
}

function runValidationAssistant(){
  if(!state.rows.length){
    setStatusMessage("validationMsg", "Chargez d'abord la table de validation.", { error: true });
    clearStatusMessageLater("validationMsg", 2600);
    return;
  }

  let highChecked = 0;
  let medFixed = 0;
  let medPending = 0;
  const profile = ($("assistProfile")?.value || "equilibre");

  for(const row of state.rows){
    const d = currentDecision(row);
    if(row.confidence_label === "high"){
      if(!d.ok) d.ok = true;
      highChecked += 1;
      continue;
    }
    if(row.confidence_label !== "med"){
      continue;
    }

    const suggested = bestAssistantCandidate(row, profile);
    if(!suggested){
      medPending += 1;
      continue;
    }

    if(d.title !== suggested.title || Number(d.year || 0) !== Number(suggested.year || 0)){
      d.title = suggested.title;
      d.year = Number(suggested.year || 0);
      d.edited = true;
    }
    d.ok = true;
    medFixed += 1;
  }

  renderTable();
  setStatusMessage(
    "validationMsg",
    `Assistant (${assistProfileLabel(profile)}) : ${highChecked} lignes haute confiance cochées, ${medFixed} lignes moyennes corrigées automatiquement, ${medPending} lignes moyennes à revoir.`,
  );
  clearStatusMessageLater("validationMsg", 4600);
}

function formatDuplicateSummary(dup, limit = 8){
  if(!dup || !dup.total_groups){
    return "Aucun doublon potentiel détecté.";
  }
  const lines = [`Doublons potentiels: ${dup.total_groups} groupe(s).`];
  for(const g of (dup.groups || []).slice(0, limit)){
    const rowCount = (g.rows || []).length;
    const existing = (g.existing_paths || []).length;
    const flags = [];
    if(g.plan_conflict) flags.push("conflit dans la sélection");
    if(existing > 0) flags.push(`${existing} déjà présent(s)`);
    lines.push(`- ${g.title} (${g.year}): ${flags.join(", ")}${rowCount ? `, ${rowCount} ligne(s)` : ""}`);
  }
  if((dup.total_groups || 0) > limit){
    lines.push(`... +${dup.total_groups - limit} autre(s) groupe(s).`);
  }
  return lines.join("\n");
}

function renderDuplicatesView(data){
  const tbody = $("dupTbody");
  if(!tbody) return;
  const report = data || { total_groups: 0, checked_rows: 0, groups: [] };
  const groups = report.groups || [];

  $("dupCountPill").textContent = `${report.total_groups || 0} groupe(s)`;
  $("dupMsg").textContent = `Lignes validées analysées: ${report.checked_rows || 0}`;
  tbody.innerHTML = "";

  if(!groups.length){
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="4" class="muted">Aucun doublon potentiel détecté.</td>`;
    tbody.appendChild(tr);
    return;
  }

  for(const g of groups){
    const keyLabel = `${g.title} (${g.year})`;
    const rowsHtml = (g.rows || []).map((it) => `
      <div class="dupLine">
        <div class="dupMeta">row_id=${escapeHtml(it.row_id || "")} • ${escapeHtml(it.kind || "")}</div>
        <div class="row">
          <button class="btn smallBtn pathBtn" data-open="${escapeHtml(it.source_folder || "")}" title="${escapeHtml(it.source_folder || "")}">Source: ${escapeHtml(shortPath(it.source_folder || ""))}</button>
          <button class="btn smallBtn pathBtn" data-open="${escapeHtml(it.target || "")}" title="${escapeHtml(it.target || "")}">Cible: ${escapeHtml(shortPath(it.target || ""))}</button>
        </div>
      </div>
    `).join("");

    const existing = (g.existing_paths || []);
    const existingHtml = existing.length
      ? `<div class="dupStack">${existing.map((p) =>
          `<button class="btn smallBtn pathBtn" data-open="${escapeHtml(p)}" title="${escapeHtml(p)}">${escapeHtml(shortPath(p))}</button>`
        ).join("")}</div>`
      : `<span class="muted">Aucun dossier existant en conflit.</span>`;

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><b>${escapeHtml(keyLabel)}</b></td>
      <td>${g.plan_conflict ? '<span class="badge med">Oui</span>' : '<span class="badge high">Non</span>'}</td>
      <td><div class="dupStack">${rowsHtml}</div></td>
      <td>${existingHtml}</td>
    `;
    tbody.appendChild(tr);
  }
}

async function checkDuplicatesFromUI(showAlert, quiet = false){
  if(!state.runId){
    return { ok: false, message: "Lancez d'abord une analyse." };
  }
  const decisions = gatherDecisions();
  const r = await apiCall("check_duplicates", () => window.pywebview.api.check_duplicates(state.runId, decisions), {
    fallbackMessage: "Impossible de verifier les doublons.",
  });
  if(!r.ok){
    return r;
  }
  state.duplicates = r;
  if(!quiet){
    const msg = r.total_groups > 0
      ? `Doublons potentiels détectés: ${r.total_groups} groupe(s).`
      : "Aucun doublon potentiel détecté.";
    setStatusMessage("validationMsg", msg);
    clearStatusMessageLater("validationMsg", 3400);
  }
  if(showAlert){
    await uiInfo({
      title: "Résumé doublons",
      message: formatDuplicateSummary(r, 10),
      confirmLabel: "Fermer",
    });
  }
  return r;
}

async function refreshDuplicatesView(){
  const msg = $("dupMsg");
  if(!state.runId){
    msg.textContent = "Lancez d'abord une analyse.";
    renderDuplicatesView({ total_groups: 0, checked_rows: 0, groups: [] });
    return;
  }
  msg.textContent = "Analyse des conflits en cours...";
  const r = await checkDuplicatesFromUI(false, true);
  if(!r.ok){
    msg.textContent = `Erreur doublons : ${r.message || ""}`;
    return;
  }
  renderDuplicatesView(r);
}

function hookDuplicateEvents(){
  const dupTbody = $("dupTbody");
  if(!dupTbody) return;
  dupTbody.addEventListener("click", async (e) => {
    const t = e.target;
    if(!t || !t.dataset || !t.dataset.open) return;
    await openPathWithFeedback(t.dataset.open, "dupMsg", "Impossible d'ouvrir ce dossier.", {
      successMessage: "Dossier ouvert.",
      clearMs: 1600,
      triggerEl: t,
    });
  });
}

function hookFilters(){
  $("searchBox").addEventListener("input", renderTable);
  $("filterConf").addEventListener("change", renderTable);
  $("filterSource")?.addEventListener("change", renderTable);
  $("filterKind")?.addEventListener("change", renderTable);
  $("filterChangeType")?.addEventListener("change", renderTable);
  $("filterWarning")?.addEventListener("change", renderTable);
  $("qualityStateFilter")?.addEventListener("change", renderTable);
  $("qualityTierFilter")?.addEventListener("change", renderTable);
  $("qualityScoreFilter")?.addEventListener("change", renderTable);

  $("btnPresetReviewRisk")?.addEventListener("click", () => setValidationPreset("review_risk"));
  $("btnPresetAddYear")?.addEventListener("click", () => setValidationPreset("add_year"));
  $("btnPresetSensitive")?.addEventListener("click", () => setValidationPreset("sensitive"));
  $("btnPresetCollections")?.addEventListener("click", () => setValidationPreset("collections"));
  $("btnPresetQualityLow")?.addEventListener("click", () => setValidationPreset("quality_low"));
  $("btnPresetReset")?.addEventListener("click", () => {
    state.validationPreset = "none";
    if($("filterConf")) $("filterConf").value = "all";
    if($("filterSource")) $("filterSource").value = "all";
    if($("filterKind")) $("filterKind").value = "all";
    if($("filterChangeType")) $("filterChangeType").value = "all";
    if($("filterWarning")) $("filterWarning").value = "all";
    if($("qualityStateFilter")) $("qualityStateFilter").value = "all";
    if($("qualityTierFilter")) $("qualityTierFilter").value = "all";
    if($("qualityScoreFilter")) $("qualityScoreFilter").value = "all";
    renderTable();
  });

  $("btnCheckVisible").addEventListener("click", () => {
    document.querySelectorAll("#planTbody input[type=\"checkbox\"][data-ok]").forEach(ch => {
      ch.checked = true;
      const id = ch.dataset.ok;
      const row = findRowById(id);
      currentDecision(row).ok = true;
    });
  });

  $("btnUncheckVisible").addEventListener("click", () => {
    document.querySelectorAll("#planTbody input[type=\"checkbox\"][data-ok]").forEach(ch => {
      ch.checked = false;
      const id = ch.dataset.ok;
      const row = findRowById(id);
      currentDecision(row).ok = false;
    });
  });
}

async function applySelected(){
  if(state.applyInFlight){
    setStatusMessage("applyMsg", "Application déjà en cours...", { loading: true });
    flashActionButton("btnApply", "error");
    return;
  }
  if(!state.runId){
    setStatusMessage("applyMsg", "Lancez d'abord l'analyse.", { error: true });
    flashActionButton("btnApply", "error");
    return;
  }
  const dry = $("ckDryRun").checked;
  const quar = $("ckQuarantine").checked;

  state.applyInFlight = true;
  const btnApply = $("btnApply");
  if(btnApply) btnApply.disabled = true;
  setUndoControlsState();
  try {
    setStatusMessage("applyMsg", "Application en cours...", { loading: true });
    $("applyResult").textContent = "...";
    state.cleanupResidualLastResult = null;
    renderApplyCleanupDiagnostic();

    const decisions = gatherDecisions();
    const saveRes = await persistValidation();
    if(!saveRes.ok){
      setStatusMessage("applyMsg", `Application stoppée : validation non enregistrée (${saveRes.message || "erreur inconnue"}).`, { error: true });
      $("applyResult").textContent = saveRes.message || "La validation doit être enregistrée avant l'application.";
      flashActionButton(btnApply, "error");
      return;
    }

    const dup = await apiCall("check_duplicates(apply)", () => window.pywebview.api.check_duplicates(state.runId, decisions), {
      statusId: "applyMsg",
      fallbackMessage: "Impossible de vérifier les doublons.",
    });
    if(!dup || !dup.ok){
      setStatusMessage("applyMsg", `Application stoppée: vérification des doublons impossible (${dup?.message || "erreur inconnue"}).`, { error: true });
      flashActionButton(btnApply, "error");
      return;
    }
    if(dup && dup.ok && (dup.total_groups || 0) > 0){
      $("applyResult").textContent = formatDuplicateSummary(dup, 12);
      const proceed = await uiConfirm({
        title: "Doublons potentiels détectés",
        message: `Attention : ${dup.total_groups} doublon(s) potentiel(s) détecté(s). Continuer l'application ?`,
        confirmLabel: "Continuer l'application",
        cancelLabel: "Annuler",
        danger: true,
      });
      if(!proceed){
        setStatusMessage("applyMsg", "Application annulée (doublons à vérifier).");
        return;
      }
    }

    const r = await apiCall("apply", () => window.pywebview.api.apply(state.runId, decisions, dry, quar), {
      statusId: "applyMsg",
      fallbackMessage: "Erreur pendant l'application.",
    });
    if(!r.ok){
      setStatusMessage("applyMsg", "Erreur : " + (r.message || ""), { error: true });
      $("applyResult").textContent = r.message || "";
      flashActionButton(btnApply, "error");
      return;
    }

    setStatusMessage("applyMsg", "Application terminée.", { success: true });
    $("applyResult").textContent = formatApplyResult(r.result, dry);
    state.cleanupResidualLastResult = {
      run_id: String(state.runId || ""),
      dry_run: !!dry,
      diagnostic: (r.result && typeof r.result.cleanup_residual_diagnostic === "object")
        ? r.result.cleanup_residual_diagnostic
        : null,
    };
    renderApplyCleanupDiagnostic();
    flashActionButton(btnApply, "ok");
    if(!dry){
      await refreshUndoPreview(null, { silent: true });
    }
  } finally {
    state.applyInFlight = false;
    if(btnApply) btnApply.disabled = false;
    setUndoControlsState();
  }
}

function hookNav(){
  const tabs = qsa(".step");
  const openTab = async (btn) => {
    if(!btn || !btn.dataset?.view) return;
    showView(btn.dataset.view);
    if(btn.dataset.view === "validate") renderTable();
    if(btn.dataset.view === "duplicates") await refreshDuplicatesView();
    if(btn.dataset.view === "quality"){
      await loadQualityPresets();
      await loadQualityProfile();
      await loadProbeToolsStatus(false);
    }
    if(btn.dataset.view === "dashboard") await loadDashboard("latest");
    if(btn.dataset.view === "apply"){
      await refreshCleanupResidualPreview(null, { silent: true });
      await refreshUndoPreview(null, { silent: true });
    }
  };
  tabs.forEach((btn, index) => {
    btn.addEventListener("click", async () => {
      await openTab(btn);
    });
    btn.addEventListener("keydown", async (e) => {
      if(e.key === "ArrowRight" || e.key === "ArrowDown"){
        e.preventDefault();
        const next = tabs[(index + 1) % tabs.length];
        next?.focus();
        return;
      }
      if(e.key === "ArrowLeft" || e.key === "ArrowUp"){
        e.preventDefault();
        const prev = tabs[(index - 1 + tabs.length) % tabs.length];
        prev?.focus();
        return;
      }
      if(e.key === "Enter" || e.key === " "){
        e.preventDefault();
        await openTab(btn);
      }
    });
  });

  $("btnHelp").addEventListener("click", () => openModal("modalHelp"));
  qsa("[data-close]").forEach(b => {
    b.addEventListener("click", () => closeModal(b.dataset.close));
  });

  $("btnTheme").addEventListener("click", () => {
    if(document.body.classList.contains("light")){
      document.body.classList.remove("light");
      $("btnTheme").textContent = "Thème clair";
    } else {
      document.body.classList.add("light");
      $("btnTheme").textContent = "Thème sombre";
    }
  });

  const revealBtn = $("btnRevealKey");
  if(revealBtn){
    const refreshRevealButton = () => {
      const i = $("inApiKey");
      const visible = i && i.type === "text";
      revealBtn.textContent = visible ? "Masquer" : "Afficher";
      revealBtn.setAttribute("aria-pressed", visible ? "true" : "false");
    };
    refreshRevealButton();
    revealBtn.addEventListener("click", () => {
      const i = $("inApiKey");
      if(!i) return;
      i.type = (i.type === "password") ? "text" : "password";
      refreshRevealButton();
    });
  }
}

function hookButtons(){
  $("btnTestKey").addEventListener("click", testKey);
  $("btnSaveSettings").addEventListener("click", saveSettings);
  $("btnQualitySave").addEventListener("click", saveQualityProfileFromUI);
  $("btnQualityReset").addEventListener("click", resetQualityProfileFromUI);
  $("btnQualityExport").addEventListener("click", exportQualityProfileFromUI);
  $("btnQualityImport").addEventListener("click", importQualityProfileFromUI);
  qsa(".qualityPresetBtn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await applyQualityPresetFromUI(btn.dataset.qualityPreset || "", btn);
    });
  });
  $("btnQualityTestSelected").addEventListener("click", testQualityOnSelectedFilm);
  $("btnQualitySelectFilm").addEventListener("click", selectFilmFromContext);
  $("btnQualityTest").addEventListener("click", testQualityOnFilm);
  $("btnQualityBatchSelection").addEventListener("click", runQualityBatchOnSelection);
  $("btnQualityBatchFiltered").addEventListener("click", runQualityBatchOnFiltered);
  $("btnProbeInstall").addEventListener("click", async () => { await runProbeToolsAction("install"); });
  $("btnProbeUpdate").addEventListener("click", async () => { await runProbeToolsAction("update"); });
  $("btnProbeRecheck").addEventListener("click", async () => { await loadProbeToolsStatus(true, $("btnProbeRecheck")); });
  $("btnProbeSavePaths").addEventListener("click", saveProbeToolPathsFromUI);
  $("ckQualityForceReanalyze")?.addEventListener("change", syncQualityReuseControls);
  $("ckQualityReuseExisting")?.addEventListener("change", () => {
    if($("ckQualityForceReanalyze")?.checked){
      $("ckQualityReuseExisting").checked = false;
    }
  });
  $("btnStartPlan").addEventListener("click", startPlan);
  $("btnLoadTable").addEventListener("click", loadTable);
  $("btnOpenRunDir").addEventListener("click", openRunDir);
  $("btnAssistValidation").addEventListener("click", runValidationAssistant);
  $("btnCheckDuplicates").addEventListener("click", async () => {
    const r = await checkDuplicatesFromUI(true);
    if(!r.ok){
      setStatusMessage("validationMsg", `Erreur doublons : ${r.message || ""}`, { error: true });
      clearStatusMessageLater("validationMsg", 3000);
    }
  });
  $("btnOpenDuplicates").addEventListener("click", async () => {
    showView("duplicates");
    await refreshDuplicatesView();
  });
  $("btnDashboardRefresh").addEventListener("click", async () => {
    const runInput = state.advancedMode ? String($("dashRunId").value || "").trim() : "";
    await loadDashboard(runInput || "latest");
  });
  $("btnOnboardingFocusPaths")?.addEventListener("click", () => {
    showView("settings");
    $("inRoot")?.focus();
  });
  $("btnOnboardingTestTmdb")?.addEventListener("click", async () => {
    await testKey();
  });
  $("btnOnboardingProbeRecheck")?.addEventListener("click", async () => {
    await loadProbeToolsStatus(true, $("btnOnboardingProbeRecheck"));
  });
  $("inRoot")?.addEventListener("input", updateOnboardingStatus);
  $("inState")?.addEventListener("input", updateOnboardingStatus);
  $("ckTmdbEnabled")?.addEventListener("change", updateOnboardingStatus);
  $("selProbeBackend")?.addEventListener("change", updateOnboardingStatus);
  $("ckRememberKey")?.addEventListener("change", updateOnboardingStatus);
  $("ckDryRun")?.addEventListener("change", updateOnboardingStatus);
  $("ckQuarantine")?.addEventListener("change", updateOnboardingStatus);
  $("ckMoveEmptyFoldersEnabled")?.addEventListener("change", updateOnboardingStatus);
  $("selEmptyFoldersScope")?.addEventListener("change", updateOnboardingStatus);
  $("inResidualCleanupFolderName")?.addEventListener("input", updateOnboardingStatus);
  $("ckResidualCleanupEnabled")?.addEventListener("change", updateOnboardingStatus);
  $("selResidualCleanupScope")?.addEventListener("change", updateOnboardingStatus);
  $("ckResidualIncludeNfo")?.addEventListener("change", updateOnboardingStatus);
  $("ckResidualIncludeImages")?.addEventListener("change", updateOnboardingStatus);
  $("ckResidualIncludeSubtitles")?.addEventListener("change", updateOnboardingStatus);
  $("ckResidualIncludeTexts")?.addEventListener("change", updateOnboardingStatus);
  $("inApiKey")?.addEventListener("input", () => {
    state.tmdbLastTestOk = null;
    updateOnboardingStatus();
  });
  $("btnExportRunReportJson")?.addEventListener("click", async () => {
    await exportCurrentRunReport("json", "btnExportRunReportJson");
  });
  $("btnExportRunReportCsv")?.addEventListener("click", async () => {
    await exportCurrentRunReport("csv", "btnExportRunReportCsv");
  });
  $("btnRefreshDuplicates").addEventListener("click", refreshDuplicatesView);
  $("btnApply").addEventListener("click", applySelected);
  $("btnUndoPreview")?.addEventListener("click", async () => {
    await refreshUndoPreview($("btnUndoPreview"));
  });
  $("btnUndoRun")?.addEventListener("click", runUndoFromUI);
  $("ckUndoDryRun")?.addEventListener("change", () => {
    updateUndoRunButton();
    setUndoControlsState();
  });
  $("btnSaveValidation").addEventListener("click", saveValidationFromUI);

  qsa(".qualityHubTab").forEach((btn) => {
    btn.addEventListener("click", () => {
      setQualityHubPanel(btn.dataset.qualityPanel || "overview");
    });
  });

  $("btnNextStep")?.addEventListener("click", goToNextStep);

  $("btnToggleGuideDetails")?.addEventListener("click", () => {
    const details = $("nextActionDetails");
    const btn = $("btnToggleGuideDetails");
    if(!details || !btn){
      return;
    }
    const nowHidden = details.classList.toggle("hidden");
    btn.setAttribute("aria-expanded", nowHidden ? "false" : "true");
  });
}

let appBootstrapped = false;

function ready(){
  restoreContextFromStorage();
  if(typeof enhanceNextValidationLayout === "function"){
    enhanceNextValidationLayout();
  }
  if(typeof enhanceNextQualityLayout === "function"){
    enhanceNextQualityLayout();
  }
  if(typeof enhanceNextApplyLayout === "function"){
    enhanceNextApplyLayout();
  }
  hookNav();
  hookButtons();
  if(typeof bindNextApplyUi === "function"){
    bindNextApplyUi();
  }
  hookTableEvents();
  hookDashboardEvents();
  hookDuplicateEvents();
  setupContextBarEvents();
  setupRunSelectorEvents();
  hookFilters();
  initModalHandlers();
  setAdvancedMode(state.advancedMode);
  syncQualityReuseControls();
  updateUndoRunButton();
  setUndoControlsState();
  $("btnTheme").textContent = document.body.classList.contains("light") ? "Thème sombre" : "Thème clair";
  showView("settings");
  renderDuplicatesView({ total_groups: 0, checked_rows: 0, groups: [] });
  updateContextBar();
  updateOnboardingStatus();
}

window.addEventListener("pywebviewready", async () => {
  if(appBootstrapped){
    return;
  }
  appBootstrapped = true;
  ready();
  try {
    await loadSettings();
    await loadQualityPresets();
    await loadQualityProfile();
    await loadProbeToolsStatus(false);
    await loadDashboard("latest");
  } catch(err){
    const msg = "Initialisation incomplète. Vérifiez le backend puis relancez l'application.";
    setStatusMessage("saveMsg", msg, { error: true });
    setStatusMessage("planMsg", msg, { error: true });
    console.error("[startup] init error", err);
  }
});

