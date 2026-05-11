/* core/state.js — Application state + localStorage persistence */

/* eslint-disable no-unused-vars */

const LS_LAST_RUN_ID     = "cinesort.lastRunId";
const LS_SELECTED_RUN_ID = "cinesort.selectedRunId";
const LS_SELECTED_ROW_ID = "cinesort.selectedRowId";
const LS_SELECTED_TITLE  = "cinesort.selectedTitle";
const LS_SELECTED_YEAR   = "cinesort.selectedYear";
const LS_SELECTED_FOLDER = "cinesort.selectedFolder";
const LS_ADVANCED_MODE   = "cinesort.advancedMode";

const state = {
  view: "home",
  settings: null,
  theme: "dark",

  /* Run context */
  runId: null,
  runDir: null,
  lastRunId: null,
  selectedRunId: null,
  rowsRunId: null,
  runDirsById: new Map(),

  /* Film selection */
  selectedRowId: null,
  selectedTitle: "",
  selectedYear: 0,
  selectedFolder: "",

  /* Plan / scan */
  logIndex: 0,
  polling: null,
  pollInFlight: false,

  /* Rows & decisions */
  rows: [],
  rowsById: new Map(),
  decisions: {},
  validationPreset: "none",
  validationShortcutsHooked: false,
  candidatesForRow: null,

  /* Duplicates */
  duplicates: null,
  selectedDuplicateKey: null,

  /* Apply / undo */
  applyInFlight: false,
  undoInFlight: false,
  undoPreview: null,
  undoV5BatchId: null,
  cleanupResidualPreview: null,
  cleanupResidualLastResult: null,

  /* Quality */
  qualityHubPanel: "overview",
  qualityProfile: null,
  qualityPresets: [],
  qualityByRow: new Map(),
  qualityRunOverview: null,
  qualityBatchInFlight: false,
  globalStats: null,

  /* Probe */
  probeToolsStatus: null,
  probeToolsInFlight: false,

  /* Dashboard / history */
  dashboard: null,
  runsHistory: [],
  logsSelectedRunId: null,
  homeOverview: null,

  /* UI */
  advancedMode: false,
  nextStepView: "validation",
  nextStepInFlight: false,
  tmdbLastTestOk: null,

  /* Modals */
  activeModalId: null,
  modalReturnFocusEl: null,
  modalRows: [],
  selectedRunForModal: null,

  /* Event-driven polling (parite dashboard) */
  lastEventTs: 0,
  lastSettingsTs: 0,
};

/* --- Event-driven change detection (parite dashboard) ------- */

/**
 * Verifie si le timestamp serveur a change depuis la derniere verification.
 * Retourne true uniquement si un changement est detecte (premiere initialisation = false).
 */
function checkEventChanged(serverTs) {
  const ts = Number(serverTs) || 0;
  if (!ts) return false;
  if (!state.lastEventTs) { state.lastEventTs = ts; return false; }
  if (ts > state.lastEventTs) { state.lastEventTs = ts; return true; }
  return false;
}

function checkSettingsEventChanged(serverTs) {
  const ts = Number(serverTs) || 0;
  if (!ts) return false;
  if (!state.lastSettingsTs) { state.lastSettingsTs = ts; return false; }
  if (ts > state.lastSettingsTs) { state.lastSettingsTs = ts; return true; }
  return false;
}

/* --- Persistence ------------------------------------------- */

function restoreContextFromStorage() {
  state.lastRunId     = getStoredText(LS_LAST_RUN_ID) || null;
  state.selectedRunId = getStoredText(LS_SELECTED_RUN_ID) || null;
  state.selectedRowId = null;
  state.selectedTitle = "";
  state.selectedYear  = 0;
  state.selectedFolder = "";
  const adv = getStoredText(LS_ADVANCED_MODE).toLowerCase();
  state.advancedMode = adv === "1" || adv === "true";
}

function persistContextToStorage() {
  setStoredText(LS_LAST_RUN_ID, state.lastRunId || "");
  setStoredText(LS_SELECTED_RUN_ID, state.selectedRunId || "");
  setStoredText(LS_SELECTED_ROW_ID, state.selectedRowId || "");
  setStoredText(LS_SELECTED_TITLE, state.selectedTitle || "");
  setStoredText(LS_SELECTED_YEAR, state.selectedYear || 0);
  setStoredText(LS_SELECTED_FOLDER, state.selectedFolder || "");
  setStoredText(LS_ADVANCED_MODE, state.advancedMode ? "1" : "0");
}

/* --- Context helpers --------------------------------------- */

function currentContextRunId() {
  return String(state.runId || state.selectedRunId || state.lastRunId || "");
}

function currentContextRowId() {
  return String(state.selectedRowId || "");
}

function currentContextRunLabel() {
  return currentContextRunId() || "Aucun run";
}

function currentContextFilmLabel() {
  const title = String(state.selectedTitle || "").trim();
  const year = Number(state.selectedYear || 0);
  if (title && year > 0) return `${title} (${year})`;
  if (title) return title;
  return "Aucun film";
}

/* --- Row management ---------------------------------------- */

function setRows(rows, runId) {
  state.rows = Array.isArray(rows) ? rows : [];
  state.rowsRunId = runId || null;
  state.rowsById = new Map();
  for (const r of state.rows) {
    const id = String(r.row_id || "").trim();
    if (id) state.rowsById.set(id, r);
  }
}

function findRowById(rowId) {
  const id = String(rowId || "").trim();
  return state.rowsById.get(id) || null;
}

function currentDecision(row) {
  if (!row) return { ok: false, title: "", year: 0, edited: false };
  const id = String(row.row_id || "").trim();
  if (!state.decisions[id]) {
    state.decisions[id] = {
      ok: !!row.auto_approved,
      title: String(row.proposed_title || "").trim(),
      year: parseInt(row.proposed_year || 0, 10) || 0,
      edited: false,
    };
  }
  return state.decisions[id];
}

function gatherDecisions() {
  const out = {};
  for (const [id, d] of Object.entries(state.decisions)) {
    out[id] = { ok: !!d.ok, title: d.title || "", year: d.year || 0, edited: !!d.edited };
  }
  return out;
}

/* --- Run dir cache ----------------------------------------- */

function rememberRunDir(runId, runDir) {
  const rid = String(runId || "").trim();
  const dir = String(runDir || "").trim();
  if (rid && dir) state.runDirsById.set(rid, dir);
}

function rememberRunDirsFromHistory(runs) {
  for (const row of (Array.isArray(runs) ? runs : [])) {
    if (row && typeof row === "object") rememberRunDir(row.run_id, row.run_dir);
  }
}

function resolveRunDirFor(runId) {
  return state.runDirsById.get(String(runId || "").trim()) || "";
}

function setLastRunContext(runId, runDir) {
  state.lastRunId = runId || null;
  state.selectedRunId = runId || null;
  rememberRunDir(runId, runDir);
  persistContextToStorage();
}

function setSelectedFilmContext(row, runId) {
  if (!row) return;
  state.selectedRowId = String(row.row_id || "").trim() || null;
  state.selectedTitle = String(row.proposed_title || row.title || "").trim();
  state.selectedYear = parseInt(row.proposed_year || row.year || 0, 10) || 0;
  state.selectedFolder = String(row.folder || row.path || "").trim();
  if (runId) state.selectedRunId = runId;
  persistContextToStorage();
}

function clearSelectedFilmContext() {
  state.selectedRowId = null;
  state.selectedTitle = "";
  state.selectedYear = 0;
  state.selectedFolder = "";
}

function resetRunScopedState() {
  setRows([], null);
  state.decisions = {};
  state.duplicates = null;
  state.qualityByRow = new Map();
  state.cleanupResidualPreview = null;
  state.cleanupResidualLastResult = null;
  clearSelectedFilmContext();
}

function clearRunCachesForStateDirChange() {
  resetRunScopedState();
  state.dashboard = null;
  state.runsHistory = [];
  state.homeOverview = null;
  state.qualityRunOverview = null;
  state.logsSelectedRunId = null;
}
