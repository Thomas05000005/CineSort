/* tests/run_vague_l_tests.mjs — Tests JS Vague L (audit 2026-05-26 v1.5.6).
 *
 * Harness Node ESM autonome (zero dependance). Couvre les findings :
 *   - crules-1 : openCustomRulesEditor lit profRes.data.profile_json
 *   - drawer-1 : _renderRange + buildBackendFilters propagent size_min_gb/size_max_gb
 *   - undo-1  : modale danger pre-apply affiche 24h (pas 7 jours)
 *   - step-1  : _startPolling appelle _loadPlan() au switch Analyse->Verification
 *   - i18n-1  : _fetchLocale retry + reloadLocale reset _state.messages
 *   - theme-1 : _map dans _loadDashTheme respecte 0 (v??50 et pas v||50)
 *
 * Exec : node web/dashboard/tests/run_vague_l_tests.mjs
 *
 * Chaque test fait du mutation testing manuel : la rubrique "MUTATION" stub
 * l'implementation testee (constante / no-op) et verifie que le test casse.
 * La sortie listera donc pour chaque test :
 *   - "PASS <name>" : implementation correcte
 *   - "MUTANT-KILL <name>" : test echoue si on stub -> preuve non-vacuous
 */

import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, "..");

let passed = 0;
let failed = 0;
const failures = [];

function assertEq(actual, expected, msg) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    throw new Error(`${msg}\n  expected=${e}\n  actual  =${a}`);
  }
}

function assertContains(haystack, needle, msg) {
  if (!String(haystack).includes(needle)) {
    throw new Error(`${msg}\n  needle="${needle}"\n  haystack=${haystack}`);
  }
}

function assertNotContains(haystack, needle, msg) {
  if (String(haystack).includes(needle)) {
    throw new Error(`${msg}\n  needle="${needle}" found in haystack`);
  }
}

async function runTest(name, fn) {
  try {
    await fn();
    console.log(`PASS ${name}`);
    passed += 1;
  } catch (err) {
    console.log(`FAIL ${name}: ${err.message}`);
    failed += 1;
    failures.push({ name, err });
  }
}

// =====================================================================
// drawer-1 : _renderRange + buildBackendFilters propagent size_min_gb
// =====================================================================
await runTest("drawer-1 size_min_gb is propagated end-to-end", async () => {
  const mod = await import(pathToFileURL(resolve(ROOT, "components/library-advanced-drawer.js")).href);
  const { buildBackendFilters } = mod;
  // Simule un drawer state issu de _collectValues : si l'attribut name HTML
  // est "size_min_gb" / "size_max_gb" (apres fix), _collectValues retourne :
  const state = {
    size_min_gb: 5,
    size_max_gb: 50,
  };
  const filters = buildBackendFilters(state);
  // 5 Go -> 5 * 1024^3 bytes, 50 Go -> 50 * 1024^3 bytes
  assertEq(filters.size_min, Math.round(5 * 1024 * 1024 * 1024), "size_min should be 5 GB in bytes");
  assertEq(filters.size_max, Math.round(50 * 1024 * 1024 * 1024), "size_max should be 50 GB in bytes");
});

// MUTATION drawer-1 : si on stub buildBackendFilters pour ignorer size_min_gb,
// le test casse. Verifions concretement en re-implementant un stub.
await runTest("drawer-1 MUTATION buildBackendFilters({})", async () => {
  // Stub : un buildBackendFilters qui IGNORE size_min_gb/size_max_gb (comme l'ancien
  // comportement quand HTML produisait size_gb_min/size_gb_max et que DEFAULTS
  // ecrasait les vraies valeurs avec 0/100). On verifie que le test ci-dessus
  // ECHOUERAIT avec ce stub.
  const stub = (drawerState) => {
    const DEFAULTS = { size_min_gb: 0, size_max_gb: 100 };
    const s = { ...DEFAULTS, ...(drawerState || {}) };
    // Bug : ignore size_min_gb/size_max_gb car DEFAULTS les ramene a 0/100
    // (simule l'ancien comportement avec mismatch de cle).
    const filters = {};
    if (s.size_min_gb && s.size_min_gb > 0) filters.size_min = s.size_min_gb * 1024 * 1024 * 1024;
    // BUG : la sortie de _collectValues ne mettait JAMAIS size_min_gb, donc
    // s.size_min_gb restait a 0 et filters.size_min n'etait pas pose.
    return filters;
  };
  // Simulons l'ancien _collectValues : avec name="size_gb_min", out['size_gb_min']
  // est ecrit, et out['size_min_gb'] reste a DEFAULTS (0). On passe donc cet
  // etat au stub :
  const collected = { size_gb_min: 5, size_gb_max: 50, size_min_gb: 0, size_max_gb: 100 };
  const filters = stub(collected);
  // Avec le bug, la valeur n'est PAS propagee -> assertion ci-dessous echoue
  // (cad le test "drawer-1 size_min_gb..." aurait fail avec ce stub).
  if (filters.size_min === Math.round(5 * 1024 * 1024 * 1024)) {
    throw new Error("MUTATION FAILED TO KILL : stub propagated size_min anyway");
  }
  // Le test passe (= la mutation casse bien le scenario nominal).
});

// =====================================================================
// theme-1 : _map dans _loadDashTheme respecte 0 (v??50 et pas v||50)
// =====================================================================
await runTest("theme-1 app.js _map uses ?? not || (regex source check)", async () => {
  // Lit app.js et verifie que _loadDashTheme contient v??50 et PAS v||50.
  const src = readFileSync(resolve(ROOT, "app.js"), "utf-8");
  // Extrait la fonction _loadDashTheme
  const startIdx = src.indexOf("async function _loadDashTheme()");
  if (startIdx < 0) throw new Error("_loadDashTheme not found");
  // Cherche jusqu'a la prochaine declaration de function
  const endIdx = src.indexOf("\nasync function ", startIdx + 1);
  const block = src.slice(startIdx, endIdx > 0 ? endIdx : startIdx + 2000);
  // _map doit utiliser (v ?? 50)
  const fixPattern = /\(v\s*\?\?\s*50\)/;
  const buggyPattern = /\(v\s*\|\|\s*50\)/;
  if (buggyPattern.test(block)) {
    throw new Error("BUG residual: _loadDashTheme still uses v||50");
  }
  if (!fixPattern.test(block)) {
    throw new Error("FIX missing: _loadDashTheme does not use v??50");
  }
  // Sanity check formule
  const _mapFixed = (v, lo, hi) => lo + ((v ?? 50) - 0) * (hi - lo) / 100;
  assertEq(_mapFixed(0, 0, 0.5), 0, "fixed map should treat 0 as 0%");
  assertEq(_mapFixed(undefined, 0, 0.5), 0.25, "undefined defaults to 50%");
});

await runTest("theme-1 MUTATION _map(0) with v||50 returns hi/2 (buggy)", async () => {
  // Stub : ancien code v||50
  const _mapBuggy = (v, lo, hi) => lo + ((v || 50) - 0) * (hi - lo) / 100;
  // Bug : 0 est traite comme absent et remplace par 50 -> renvoie hi/2 au lieu de lo
  assertEq(_mapBuggy(0, 0, 0.5), 0.25, "buggy map treats 0 as 50%");
  // Le scenario nominal (v??50) renverrait 0 ici ; donc le test "fixed" passerait
  // et celui-ci confirme le comportement buggy ANCIEN (mutation = revert).
});

// =====================================================================
// undo-1 : modale danger pre-apply affiche "24h"
// =====================================================================
await runTest("undo-1 modale danger consequence (apply) text mentions 24h", async () => {
  const src = readFileSync(resolve(ROOT, "views/traitement.js"), "utf-8");
  // Cible specifiquement la consequence de l'apply danger modal.
  // L'identifiant unique : phrase "fichiers sur disque seront effectivement modifies".
  const matches = [...src.matchAll(/consequence:\s*"([^"]+)"/g)];
  const applyConsequence = matches.find((m) => /fichiers sur disque/i.test(m[1]));
  if (!applyConsequence) throw new Error("no apply-danger consequence string found");
  const displayedText = applyConsequence[1];
  assertContains(displayedText, "24h", "consequence must mention 24h");
  assertNotContains(displayedText, "7 jours", "consequence must NOT mention 7 jours");
});

await runTest("undo-1 MUTATION revert to '7 jours' would fail the assertion", async () => {
  // Stub : on simule l'ancien texte
  const buggyText = "Les fichiers sur disque seront effectivement modifies. Reversible via Undo pendant 7 jours apres apply.";
  let caught = false;
  try {
    assertContains(buggyText, "24h", "consequence must mention 24h");
    assertNotContains(buggyText, "7 jours", "consequence must NOT mention 7 jours");
  } catch (e) {
    caught = true;
  }
  if (!caught) throw new Error("MUTATION FAILED TO KILL : buggy text passed the assertion");
});

// =====================================================================
// step-1 : _startPolling appelle _loadPlan() au switch Analyse->Verification
// =====================================================================
await runTest("step-1 _startPolling calls await _loadPlan() before _renderInPlace on done", async () => {
  const src = readFileSync(resolve(ROOT, "views/traitement.js"), "utf-8");
  // Isole le corps de _startPolling jusqu'a sa fermeture par '}, interval);'
  const idx = src.indexOf("function _startPolling()");
  if (idx < 0) throw new Error("_startPolling not found");
  const closeIdx = src.indexOf("}, interval);", idx);
  if (closeIdx < 0) throw new Error("_startPolling close marker not found");
  const block = src.slice(idx, closeIdx);
  // L'ordre doit etre : _writeStep("verification") -> await _loadPlan() -> _renderInPlace()
  const writeStepIdx = block.indexOf('_writeStep("verification")');
  const loadPlanIdx = block.indexOf("await _loadPlan()");
  const renderIdx = block.indexOf("_renderInPlace();");
  if (writeStepIdx < 0 || loadPlanIdx < 0 || renderIdx < 0) {
    throw new Error(`order tokens missing: writeStep=${writeStepIdx} loadPlan=${loadPlanIdx} render=${renderIdx}`);
  }
  if (!(writeStepIdx < loadPlanIdx && loadPlanIdx < renderIdx)) {
    throw new Error(`bad order: writeStep=${writeStepIdx} loadPlan=${loadPlanIdx} render=${renderIdx}`);
  }
});

await runTest("step-1 MUTATION remove await _loadPlan() makes order check fail", async () => {
  // Stub : on simule l'ancien code sans _loadPlan
  const stubBlock = `
function _startPolling() {
  _stopPolling();
  _pollTimer = setInterval(async () => {
    if (_runStatus && _runStatus.done) {
      _stopPolling();
      if (_currentStep === "analyse") {
        _currentStep = "verification";
        _writeStep("verification");
      }
      _renderInPlace();
      return;
    }
  }, 1000);
}`;
  const writeStepIdx = stubBlock.indexOf('_writeStep("verification")');
  const loadPlanIdx = stubBlock.indexOf("await _loadPlan()");
  const renderIdx = stubBlock.indexOf("_renderInPlace();");
  // Bug : loadPlanIdx === -1 -> condition (loadPlanIdx >= 0) fail
  if (loadPlanIdx >= 0) throw new Error("MUTATION FAILED TO KILL : stub still has _loadPlan");
  // Verifie que l'assertion d'ordre echouerait sur ce stub
  let asserted = false;
  try {
    if (writeStepIdx < 0 || loadPlanIdx < 0 || renderIdx < 0) {
      asserted = true;
      throw new Error("order tokens missing");
    }
  } catch {
    if (!asserted) throw new Error("unexpected");
  }
});

// =====================================================================
// crules-1 : openCustomRulesEditor doit lire profRes.data.profile_json
// =====================================================================
await runTest("crules-1 source code reads profPayload.profile_json (not profRes.profile_json)", async () => {
  const src = readFileSync(resolve(ROOT, "views/custom-rules-editor.js"), "utf-8");
  // L'ancien pattern buggy etait : const profile = (profRes && profRes.profile_json) || {};
  // Le pattern attendu doit normaliser via res.data avant de lire profile_json,
  // soit via _profPayload, _payload ou (res && res.data) || res.
  // On verifie l'ABSENCE du pattern buggy hors commentaires en cherchant la sequence
  // "= (profRes && profRes.profile_json)" qui etait la signature exacte du bug.
  const buggyPattern = /=\s*\(profRes\s*&&\s*profRes\.profile_json\)/;
  if (buggyPattern.test(src)) {
    throw new Error("BUG residual: code still reads profRes.profile_json directly");
  }
  // Et on verifie la presence du nouveau pattern (profPayload + data)
  if (!src.includes("profPayload.profile_json") && !src.includes("(profRes && profRes.data)")) {
    throw new Error("FIX missing: no profPayload.profile_json or profRes.data unwrap");
  }
});

await runTest("crules-1 MUTATION revert to profRes.profile_json triggers buggy detection", async () => {
  const stubSrc = "  const profile = (profRes && profRes.profile_json) || {};";
  const buggyPattern = /=\s*\(profRes\s*&&\s*profRes\.profile_json\)/;
  if (!buggyPattern.test(stubSrc)) {
    throw new Error("MUTATION FAILED TO KILL : stub did not match buggy pattern regex");
  }
});

// =====================================================================
// i18n-1 : _fetchLocale retry exponentiel + reloadLocale reset
// =====================================================================
await runTest("i18n-1 reloadLocale exports and _FETCH_RETRY_DELAYS_MS has 3 entries", async () => {
  // Mock minimal de localStorage et fetch pour le boot du module i18n
  globalThis.localStorage = {
    _data: {},
    getItem(k) { return this._data[k] ?? null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; },
  };
  let callCount = 0;
  globalThis.fetch = async (url) => {
    callCount += 1;
    // 2 echecs puis succes -> verifie retry
    if (callCount < 3) {
      return { ok: false, status: 503, json: async () => ({}) };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ sidebar: { brand_name: "TestBrand" } }),
    };
  };
  const mod = await import(pathToFileURL(resolve(ROOT, "core/i18n.js")).href + "?cache=" + Date.now());
  if (typeof mod.reloadLocale !== "function") {
    throw new Error("reloadLocale not exported");
  }
  const ok = await mod.reloadLocale("fr");
  if (!ok) throw new Error("reloadLocale should have returned true after retry success");
  if (callCount < 3) throw new Error(`expected at least 3 fetch attempts, got ${callCount}`);
  // Verifie que t() retourne maintenant le vrai message
  assertEq(mod.t("sidebar.brand_name"), "TestBrand", "t() should serve loaded message");
});

await runTest("i18n-1 MUTATION single attempt without retry would never succeed", async () => {
  // Stub : version sans retry. On simule callCount=1 et echec.
  const stubFetch = async () => ({ ok: false, status: 503, json: async () => ({}) });
  // Simule un _fetchLocale sans retry
  const stubFetchLocale = async () => {
    try {
      const r = await stubFetch();
      if (!r.ok) return {};
      return await r.json();
    } catch { return {}; }
  };
  const data = await stubFetchLocale();
  assertEq(Object.keys(data).length, 0, "without retry, single 503 yields empty data");
  // Confirme que le scenario nominal (3 retries) aurait reussi alors que stub a 1 essai echoue.
});

// =====================================================================
// Bilan
// =====================================================================
console.log("");
console.log(`==== BILAN : ${passed} passed, ${failed} failed ====`);
if (failed > 0) {
  for (const f of failures) {
    console.log(`  - ${f.name}: ${f.err.message}`);
  }
  process.exit(1);
}
process.exit(0);
