"""Revue post-merge 2026-08-03 — views/historique.js : filtres inertes,
statut FAILED invisible, banniere de retention mensongere.

Trois defauts, tous prouves ici en EXECUTANT la vraie source sous Node avec le
payload EXACT du backend (`_runs_history_payload`, dashboard_support.py) :

1. `_deriveStatus` commencait par `if (run.status) return ...`. Or le backend
   emet TOUJOURS un `status` non vide (`str(run_row.get("status") or "PENDING")`)
   : toutes les lignes suivantes etaient mortes. Consequences : un run FAILED
   tombait dans le `default` de `_statusClass` (gris, comme un run sain) et le
   filtre « Error » ne le trouvait pas ; « Applied » et « Partiel » ne
   matchaient jamais rien.

2. `AWAITING_VALIDATION` mappait vers `is-pending`, classe declaree dans AUCUN
   CSS du depot -> statut affiche sans couleur.

3. Options mortes par construction : `run.undone` / `run.is_undo` / `run.type`
   n'existent dans aucun payload (un undo n'insere pas de ligne dans `runs`).
   Les filtres « Undone » / « Undo » et le compteur « N undo » du resume etaient
   inertes ; ils ont ete retires plutot que laisses.

4. `history_retention_days` etait lu dans le payload de `run/get_dashboard`, qui
   ne l'emet nulle part : la banniere affichait « retention 90 jours » en dur
   pendant que le cron purgeait a J-<reglage>.

Note faux-vert : les tests historiques de la zone (test_phase3_4_historique,
test_phase5_historique_complete) faisaient des `assertIn(...)` sur le TEXTE
SOURCE du JS. Ils restaient verts alors que les options etaient mortes.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, inline_module, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "historique.js"

# Les 8 valeurs de RunStatus (cinesort/domain/run_models.py) telles qu'ecrites
# par cinesort/infra/db/repositories/run.py.
RUN_STATUSES = (
    "PENDING",
    "RUNNING",
    "DONE",
    "FAILED",
    "CANCELLED",
    "PAUSED",
    "SAVED",
    "AWAITING_VALIDATION",
)

# Classes reellement declarees pour .historique-run-status dans
# web/shared/components.css (L6417-6421 + L6441).
CSS_STATUS_CLASSES = {"is-error", "is-applied", "is-partial", "is-done", "is-cancelled", "is-undone"}

# `deriveRunStatus` n'est PAS stubbe : on injecte la vraie source partagee
# (core/run-status.js), sinon le test verifierait une copie ecrite par le testeur.
STUBS = (
    inline_module("core/run-status.js")
    + r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

globalThis.__calls = [];
globalThis.__dashboard = { ok: true, runs_history: [] };
globalThis.__settings = {};
const apiPost = async (endpoint, body) => {
  globalThis.__calls.push({ endpoint, body: body || {} });
  if (endpoint === "run/get_dashboard") return { status: 200, data: globalThis.__dashboard };
  return { status: 200, data: { ok: true } };
};
// FORME REELLE du payload, verifiee le 2026-08-03 sur le vrai
// CineSortApi().settings.get_settings() : un dict PLAT de reglages, SANS cle
// `ok` et SANS enveloppe `data` (c'est ainsi que app.js le lit deja :
// `res.data.theme`, `res.data.jellyfin_enabled`). `history_retention_days` est
// meme ABSENTE tant que l'utilisateur n'a rien regle.
// `__settingsEnvelope` permet de rejouer une enveloppe {ok,data} pour verifier
// la tolerance du lecteur, mais le cas NOMINAL teste ici est le cas plat.
const cachedGetSettings = async () => {
  globalThis.__calls.push({ endpoint: "settings/get_settings", body: {} });
  if (globalThis.__breakSettings) throw new Error("401 token refuse");
  const payload = globalThis.__settingsEnvelope
    ? { ok: true, data: globalThis.__settings }
    : globalThis.__settings;
  return { status: 200, data: payload };
};
const getNavSignal = () => undefined;
const navigateTo = () => {};
const rightPanel = { setSections() {}, clear() {} };
const dangerConfirmModal = () => {};
const showModal = () => {};
const closeModal = () => {};
const showToast = () => {};
const buildEmptyState = (o) => `<div class="empty">${(o && o.title) || ""}</div>`;

function __el(name) {
  const el = {
    _name: name, _html: "", isConnected: true,
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {}, style: { setProperty() {} },
    querySelector: () => null, querySelectorAll: () => [],
    focus() {}, click() {}, closest: () => null,
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  return el;
}
globalThis.__el = __el;
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "#/historique" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => __el("created"), addEventListener() {}, removeEventListener() {},
  body: Object.assign(__el("body"), { appendChild() {} }),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""
)

EXTRA = r"""
export const __h = {
  deriveStatus: _deriveStatus,
  statusClass: _statusClass,
  runType: _runType,
  filterRuns: _filterRuns,
  computeStats: _computeHistoriqueStats,
  renderHeader: _renderHeader,
  fetchRetentionDays: _fetchRetentionDays,
  setRuns: (r) => { _runs = r; },
  setFilters: (o) => {
    if (o.status !== undefined) _filterStatus = o.status;
    if (o.type !== undefined) _filterType = o.type;
    if (o.period !== undefined) _filterPeriod = o.period;
  },
  setRetention: (d) => { _retentionDays = d; },
  getRetention: () => _retentionDays,
};
"""

# Payload EXACT emis par _runs_history_payload (dashboard_support.py:93-116) :
# run_id, run_dir, status, started_ts, ended_ts, duration_s, total_rows,
# applied_rows, errors_count, anomalies_count — et RIEN d'autre.
BUILD_RUNS = r"""
const __TS = Math.floor(Date.now() / 1000) - 3600;
function __run(status, over) {
  return Object.assign({
    run_id: `run_${status}`,
    run_dir: `C:/state/runs/${status}`,
    status,
    started_ts: __TS,
    ended_ts: __TS + 60,
    duration_s: 60,
    total_rows: 10,
    applied_rows: 0,
    errors_count: 0,
    anomalies_count: 0,
  }, over || {});
}
"""


class DerivationDesStatutsTests(unittest.TestCase):
    """Le statut derive doit refleter l'etat REEL du run."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=BUILD_RUNS + driver)

    # ---------------------------------------------------------------- ROUGE
    def test_run_failed_est_signale_en_rouge(self):
        """ROUGE avant fix : FAILED sortait tel quel de _deriveStatus, tombait
        dans le `default` de _statusClass et s'affichait en GRIS (is-done),
        exactement comme un run sain."""
        res = self._run(r"""
const st = M.__h.deriveStatus(__run("FAILED", { errors_count: 7 }));
__emit({ status: st, cls: M.__h.statusClass(st) });
""")
        self.assertEqual(res["status"], "ERROR", "FAILED (DB) doit devenir ERROR (vocabulaire UI)")
        self.assertEqual(
            res["cls"],
            "is-error",
            "un run plante doit porter la classe rouge, pas le gris neutre des runs sains",
        )

    def test_filtre_error_retrouve_le_run_plante(self):
        """Scenario du finding : une nuit de scans dont un a plante ; Statut =
        Error renvoyait « Aucun run ne correspond aux filtres »."""
        res = self._run(r"""
M.__h.setRuns([__run("DONE"), __run("FAILED", { errors_count: 7 }), __run("DONE")]);
M.__h.setFilters({ status: "error", type: "all", period: "all" });
__emit({ ids: M.__h.filterRuns([__run("DONE"), __run("FAILED", { errors_count: 7 })]).map(r => r.run_id) });
""")
        self.assertEqual(res["ids"], ["run_FAILED"])

    def test_filtres_applied_et_partiel_matchent_enfin(self):
        """ROUGE avant fix : les deux filtres renvoyaient toujours 0 run."""
        res = self._run(r"""
const runs = [
  __run("DONE", { run_id: "plein",  applied_rows: 10, total_rows: 10 }),
  __run("DONE", { run_id: "moitie", applied_rows: 4,  total_rows: 10 }),
  __run("DONE", { run_id: "scan",   applied_rows: 0,  total_rows: 10 }),
];
const out = {};
for (const f of ["applied", "partial", "done"]) {
  M.__h.setFilters({ status: f, type: "all", period: "all" });
  out[f] = M.__h.filterRuns(runs).map(r => r.run_id);
}
__emit(out);
""")
        self.assertEqual(res["applied"], ["plein"])
        self.assertEqual(res["partial"], ["moitie"])
        self.assertEqual(res["done"], ["scan"], "un scan sans apply reste un run 'done'")

    def test_aucune_classe_css_inexistante(self):
        """ROUGE avant fix : AWAITING_VALIDATION -> `is-pending`, absente de tout
        le CSS du depot -> statut affiche sans couleur."""
        res = self._run(
            r"""
const out = {};
for (const s of %s) out[s] = M.__h.statusClass(M.__h.deriveStatus(__run(s)));
__emit(out);
"""
            % list(RUN_STATUSES).__repr__().replace("'", '"')
        )
        for status, cls in res.items():
            self.assertIn(
                cls,
                CSS_STATUS_CLASSES,
                f"{status} -> classe {cls!r} qui n'existe dans aucun CSS "
                f"(.historique-run-status.* declare : {sorted(CSS_STATUS_CLASSES)})",
            )

    def test_resume_ne_promet_plus_un_compteur_dundo(self):
        """ROUGE avant fix : le bandeau affichait invariablement « 0 undo »,
        fige par construction (aucun run d'undo n'existe en base)."""
        res = self._run(r"""
M.__h.setFilters({ status: "all", type: "all", period: "all" });
const runs = [
  __run("DONE",   { applied_rows: 10 }),
  __run("FAILED", { errors_count: 3 }),
  __run("DONE"),
];
__emit({ summary: M.__h.computeStats(runs).summary });
""")
        self.assertNotIn("undo", res["summary"], f"resume = {res['summary']!r}")
        self.assertIn("1 en erreur", res["summary"], f"resume = {res['summary']!r}")

    def test_options_de_filtre_mortes_retirees(self):
        """Les <option> Undone / Undo ne doivent plus etre proposees : elles ne
        peuvent matcher aucun run."""
        res = self._run(r"""
M.__h.setRetention(90);
__emit({ html: M.__h.renderHeader({ summary: "x" }) });
""")
        html = res["html"]
        self.assertNotIn('value="undone"', html)
        self.assertNotIn('value="undo"', html)
        # Les options qui matchent reellement restent proposees.
        for opt in ('value="error"', 'value="applied"', 'value="partial"', 'value="awaiting_validation"'):
            self.assertIn(opt, html, f"option utile {opt} disparue")

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_statuts_transitoires_conserves(self):
        res = self._run(r"""
const out = {};
for (const s of ["PENDING", "RUNNING", "PAUSED", "CANCELLED", "AWAITING_VALIDATION"]) {
  out[s] = M.__h.deriveStatus(__run(s));
}
__emit(out);
""")
        self.assertEqual(res["PENDING"], "PENDING")
        self.assertEqual(res["RUNNING"], "RUNNING")
        self.assertEqual(res["PAUSED"], "PAUSED")
        self.assertEqual(res["CANCELLED"], "CANCELLED")
        self.assertEqual(res["AWAITING_VALIDATION"], "AWAITING_VALIDATION")

    def test_nonreg_type_plan_vs_apply(self):
        res = self._run(r"""
__emit({
  scan: M.__h.runType(__run("DONE", { applied_rows: 0 })),
  apply: M.__h.runType(__run("DONE", { applied_rows: 3 })),
});
""")
        self.assertEqual(res["scan"], "plan")
        self.assertEqual(res["apply"], "apply")

    def test_nonreg_syntaxe(self):
        node_check(self, JS)


class BanniereRetentionTests(unittest.TestCase):
    """La banniere doit afficher la duree REELLEMENT appliquee par le cron."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_banniere_suit_le_reglage_utilisateur(self):
        """ROUGE avant fix : `run/get_dashboard` n'emet PAS
        `history_retention_days` -> `Number(undefined || 90)` = 90 en dur. Un
        utilisateur regle sur 30 lisait « retention 90 jours » alors que ses
        runs de J-40 etaient deja purges."""
        res = self._run(r"""
globalThis.__settings = { history_retention_days: 30 };
globalThis.__dashboard = { ok: true, runs_history: [] };   // sans history_retention_days
const container = globalThis.__el("container");
await M.initHistorique(container);
__emit({
  retention: M.__h.getRetention(),
  html: container.innerHTML,
  dashboardHadKey: Object.prototype.hasOwnProperty.call(globalThis.__dashboard, "history_retention_days"),
});
""")
        self.assertFalse(res["dashboardHadKey"], "le payload dashboard ne porte pas la cle (fait d'ancrage)")
        self.assertEqual(res["retention"], 30)
        self.assertIn("rétention 30 jours", res["html"])
        self.assertNotIn("rétention 90 jours", res["html"])

    def test_reglage_absent_retombe_sur_90(self):
        """Cas reel : `history_retention_days` est ABSENTE du payload tant que
        l'utilisateur ne l'a jamais reglee (verifie sur le vrai get_settings)."""
        res = self._run(r"""
globalThis.__settings = { theme: "luxe", jellyfin_enabled: false };
const container = globalThis.__el("container");
await M.initHistorique(container);
__emit({ retention: M.__h.getRetention(), html: container.innerHTML });
""")
        self.assertEqual(res["retention"], 90)
        self.assertIn("rétention 90 jours", res["html"])

    def test_zero_signifie_le_defaut_comme_cote_backend(self):
        """Le cron fait `int(settings.get("history_retention_days") or 90)` :
        0 y vaut 90. La banniere doit dire la meme chose que le cron."""
        res = self._run(r"""
globalThis.__settings = { history_retention_days: 0 };
const container = globalThis.__el("container");
await M.initHistorique(container);
__emit({ retention: M.__h.getRetention() });
""")
        self.assertEqual(res["retention"], 90)

    def test_tolere_une_enveloppe_ok_data(self):
        """Filet : si la reponse etait un jour enveloppee {ok, data}, la lecture
        ne doit pas silencieusement retomber sur 90."""
        res = self._run(r"""
globalThis.__settingsEnvelope = true;
globalThis.__settings = { history_retention_days: 45 };
const container = globalThis.__el("container");
await M.initHistorique(container);
__emit({ retention: M.__h.getRetention() });
""")
        self.assertEqual(res["retention"], 45)

    def test_echec_de_lecture_des_reglages_ne_casse_pas_la_vue(self):
        """La lecture des reglages ne doit jamais faire basculer l'ecran en
        etat d'erreur : elle retombe sur le defaut."""
        res = self._run(r"""
globalThis.__breakSettings = true;          // get_settings repond 401
const container = globalThis.__el("container");
await M.initHistorique(container);
__emit({ retention: M.__h.getRetention(), html: container.innerHTML });
""")
        self.assertEqual(res["retention"], 90)
        self.assertNotIn("n'a pas pu se charger", res["html"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_runs_toujours_charges_depuis_get_dashboard(self):
        res = self._run(r"""
globalThis.__settings = { history_retention_days: 15 };
globalThis.__dashboard = {
  ok: true,
  runs_history: [{
    run_id: "run_A", run_dir: "d", status: "DONE",
    started_ts: Math.floor(Date.now() / 1000) - 120, ended_ts: null, duration_s: 1,
    total_rows: 2, applied_rows: 2, errors_count: 0, anomalies_count: 0,
  }],
};
const container = globalThis.__el("container");
await M.initHistorique(container);
__emit({
  endpoints: globalThis.__calls.map(c => c.endpoint),
  html: container.innerHTML,
  retention: M.__h.getRetention(),
});
""")
        self.assertIn("run/get_dashboard", res["endpoints"])
        self.assertIn("settings/get_settings", res["endpoints"])
        self.assertIn("run_A", res["html"])
        self.assertEqual(res["retention"], 15)


if __name__ == "__main__":
    unittest.main()
