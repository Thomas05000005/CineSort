"""Revue adversaire de la PR #855 — /accueil et /historique doivent dire le
MEME mot sur le MEME run.

La premiere version de la PR ne corrigeait la derivation de statut que dans
`views/historique.js`. Mesure faite en executant les DEUX vraies fonctions sur
le MEME payload :

    run                      | /accueil               | /historique
    -------------------------|------------------------|---------------------
    FAILED, errors_count 0   | DONE  (pastille grise) | ERROR
    RUNNING                  | DONE                   | RUNNING
    CANCELLED                | DONE                   | CANCELLED
    AWAITING_VALIDATION      | DONE                   | AWAITING_VALIDATION
    DONE, applied 10/10      | DONE                   | APPLIED

Avant la PR les deux ecrans mentaient de la meme facon ; apres, ils se
CONTREDISAIENT. Et `accueil.js` portait exactement le defaut que la PR corrigeait
ailleurs : sa liste blanche `APPLIED/DONE/PARTIAL/ERROR` ne contenait ni FAILED
ni CANCELLED ni aucun statut transitoire, donc un run plante sans ligne d'erreur
— ou encore en cours — s'affichait en pastille grise « saine » avec une
infobulle « ... — DONE », sur l'ecran d'atterrissage.

La regle vit desormais dans `core/run-status.js`, importee par les deux vues.
Ces tests l'exigent au RUNTIME et de bout en bout : cote accueil on lit le HTML
reellement produit par `_renderRecentActivity` (pas la fonction de derivation),
donc remettre une derivation locale dans accueil.js les fait rougir.

Note anti-faux-vert : `core/run-status.js` n'est jamais stubbe. `inline_module`
injecte sa VRAIE source dans les deux harnais (cf. tests/_jsexec.py) ; un stub
maison aurait teste la copie du testeur au lieu du code livre.
"""

from __future__ import annotations

import re
import unittest

from tests._jsexec import ROOT, esm_syntax_error, require_node, run_module_test
from tests.test_revue_20260803_historique_statuts import EXTRA as HIST_EXTRA
from tests.test_revue_20260803_historique_statuts import STUBS as HIST_STUBS
from tests.test_revue_20260803_modales_et_payloads import ACCUEIL_STUBS

ACCUEIL_JS = ROOT / "web" / "dashboard" / "views" / "accueil.js"
HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"
RUN_STATUS_JS = ROOT / "web" / "dashboard" / "core" / "run-status.js"

ACCUEIL_EXTRA_TIMELINE = r"""
export const __t = {
  renderRecentActivity: _renderRecentActivity,
  bulletClass: _statusBulletClass,
};
"""

# Les cas couvrent les 8 valeurs de RunStatus (cinesort/domain/run_models.py)
# plus les combinaisons de compteurs qui doivent affiner un terminal neutre.
CASES = r"""
const __TS = Math.floor(Date.now() / 1000) - 3600;   // aujourd'hui, dans la fenetre 7j
const CASES = [
  ["done_plein",   { status: "DONE",   applied_rows: 10, total_rows: 10 }],
  ["done_partiel", { status: "DONE",   applied_rows: 4,  total_rows: 10 }],
  ["done_scan",    { status: "DONE",   applied_rows: 0,  total_rows: 10 }],
  ["done_erreurs", { status: "DONE",   applied_rows: 0,  total_rows: 10, errors_count: 3 }],
  ["failed_muet",  { status: "FAILED", applied_rows: 0,  total_rows: 10 }],
  ["failed_bruyant", { status: "FAILED", applied_rows: 0, total_rows: 10, errors_count: 7 }],
  ["cancelled",    { status: "CANCELLED", applied_rows: 2, total_rows: 10 }],
  ["pending",      { status: "PENDING" }],
  ["running",      { status: "RUNNING" }],
  ["paused",       { status: "PAUSED" }],
  ["saved_plein",  { status: "SAVED",  applied_rows: 10, total_rows: 10 }],
  ["awaiting",     { status: "AWAITING_VALIDATION", applied_rows: 0, total_rows: 10 }],
];
function __mk(id, over) {
  return Object.assign({
    run_id: id, run_dir: "C:/state/runs/" + id, status: "DONE",
    started_ts: __TS, ended_ts: __TS + 60, duration_s: 60,
    total_rows: 0, applied_rows: 0, errors_count: 0, anomalies_count: 0,
  }, over);
}
"""

_TITLE_RE = re.compile(r'data-run-id="([^"]+)"\s+title="([^"]*)"')


def _accueil_statuses() -> dict[str, str]:
    """Statut lu dans le HTML REELLEMENT produit par la timeline d'accueil."""
    res = run_module_test(
        ACCUEIL_JS,
        stubs=ACCUEIL_STUBS,
        extra=ACCUEIL_EXTRA_TIMELINE,
        driver=CASES
        + r"""
const runs = CASES.map(([id, over]) => __mk(id, over));
__emit({ html: M.__t.renderRecentActivity(runs) });
""",
    )
    out = {}
    for run_id, title in _TITLE_RE.findall(res["html"]):
        # infobulle : "HH:MM — Run <id> — N films — <STATUT>"
        out[run_id] = title.rsplit("— ", 1)[-1].strip()
    return out


def _historique_statuses() -> dict[str, str]:
    return run_module_test(
        HISTORIQUE_JS,
        stubs=HIST_STUBS,
        extra=HIST_EXTRA,
        driver=CASES
        + r"""
const out = {};
for (const [id, over] of CASES) out[id] = M.__h.deriveStatus(__mk(id, over));
__emit(out);
""",
    )


class DeuxEcransUnSeulMotTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    # ---------------------------------------------------------------- ROUGE
    def test_accueil_et_historique_ne_se_contredisent_jamais(self):
        """Le coeur de l'objection : le meme run, deux ecrans, un seul mot."""
        acc = _accueil_statuses()
        his = _historique_statuses()
        self.assertEqual(sorted(acc), sorted(his), "les deux vues n'ont pas traite les memes runs")
        divergences = {k: (acc[k], his[k]) for k in acc if acc[k] != his[k]}
        self.assertEqual(
            divergences,
            {},
            "meme run, deux verdicts (accueil, historique) : " + repr(divergences),
        )

    def test_run_plante_sans_ligne_derreur_visible_sur_laccueil(self):
        """ROUGE avant fix : FAILED + errors_count 0 -> « DONE », pastille grise
        sur la timeline de l'ecran le plus vu."""
        acc = _accueil_statuses()
        self.assertEqual(acc["failed_muet"], "ERROR")
        self.assertEqual(acc["failed_bruyant"], "ERROR")

    def test_run_en_cours_ne_se_declare_pas_termine(self):
        """ROUGE avant fix : PENDING / RUNNING / PAUSED retombaient tous sur
        « DONE » — un scan en cours s'annoncait fini."""
        acc = _accueil_statuses()
        self.assertEqual(acc["pending"], "PENDING")
        self.assertEqual(acc["running"], "RUNNING")
        self.assertEqual(acc["paused"], "PAUSED")
        self.assertEqual(acc["cancelled"], "CANCELLED")

    def test_pastille_daccueil_rouge_pour_un_run_plante(self):
        """Le mot ne suffit pas : la couleur doit suivre (l'infobulle demande un
        survol, la pastille se voit d'un coup d'oeil)."""
        res = run_module_test(
            ACCUEIL_JS,
            stubs=ACCUEIL_STUBS,
            extra=ACCUEIL_EXTRA_TIMELINE,
            driver=CASES
            + r"""
const runs = [__mk("failed_muet", { status: "FAILED" })];
const html = M.__t.renderRecentActivity(runs);
__emit({ html, error: html.includes("accueil-timeline-bullet--error") });
""",
        )
        self.assertTrue(res["error"], "un run FAILED doit porter la pastille rouge, pas le gris des runs sains")

    def test_en_validation_porte_la_meme_teinte_sur_les_deux_ecrans(self):
        """AWAITING_VALIDATION attend une action : teinte warning des deux cotes.

        /historique le mappe sur `.is-partial` (ambre). L'accueil le laissait
        tomber dans le gris « rien a faire ».
        """
        acc = run_module_test(
            ACCUEIL_JS,
            stubs=ACCUEIL_STUBS,
            extra=ACCUEIL_EXTRA_TIMELINE,
            driver=r"""__emit({ cls: M.__t.bulletClass("AWAITING_VALIDATION") });""",
        )
        his = run_module_test(
            HISTORIQUE_JS,
            stubs=HIST_STUBS,
            extra=HIST_EXTRA,
            driver=r"""__emit({ cls: M.__h.statusClass("AWAITING_VALIDATION") });""",
        )
        self.assertEqual(acc["cls"], "accueil-timeline-bullet--partial")
        self.assertEqual(his["cls"], "is-partial")

    def test_aucune_classe_de_pastille_inexistante(self):
        """Les 4 seules classes declarees dans components.css:4835-4838."""
        declared = {
            "accueil-timeline-bullet--applied",
            "accueil-timeline-bullet--done",
            "accueil-timeline-bullet--partial",
            "accueil-timeline-bullet--error",
        }
        css = (ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")
        for cls in declared:
            self.assertIn(f".{cls}", css, f"{cls} n'est plus declaree : le test d'ancrage est perime")
        res = run_module_test(
            ACCUEIL_JS,
            stubs=ACCUEIL_STUBS,
            extra=ACCUEIL_EXTRA_TIMELINE,
            driver=CASES
            + r"""
const out = {};
for (const [id, over] of CASES) {
  const html = M.__t.renderRecentActivity([__mk(id, over)]);
  const m = html.match(/class="accueil-timeline-bullet ([^"]+)"/);
  out[id] = m ? m[1] : null;
}
__emit(out);
""",
        )
        for run_id, cls in res.items():
            self.assertIn(cls, declared, f"{run_id} -> classe {cls!r} absente du CSS")

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_accueil_garde_ses_verdicts_justes(self):
        """Ce que l'accueil affichait DEJA correctement ne doit pas bouger."""
        acc = _accueil_statuses()
        self.assertEqual(acc["done_scan"], "DONE", "un scan sans apply reste un run termine")
        self.assertEqual(acc["done_erreurs"], "ERROR")
        self.assertEqual(acc["done_partiel"], "PARTIAL")

    def test_nonreg_la_source_partagee_est_bien_un_module_esm(self):
        self.assertEqual(esm_syntax_error(RUN_STATUS_JS), "")
        self.assertEqual(esm_syntax_error(ACCUEIL_JS), "")
        self.assertEqual(esm_syntax_error(HISTORIQUE_JS), "")


if __name__ == "__main__":
    unittest.main()
