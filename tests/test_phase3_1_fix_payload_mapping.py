"""Tests fix Phase 3.1 : alignement du mapping payload backend -> Accueil.

Bugs identifies au test live sur EXE (2026-05-19) :
1. Hero affichait "Bienvenue. Lance ton premier scan" alors qu'il y avait
   des runs (mauvais mapping latestRun via payload.run_info inexistant).
2. Carte "Dernier run" affichait "Aucun run encore" pour la meme raison.
3. Sante biblio (853 films classes) -> tous tiers a 0/0%. tier_distribution
   utilise des keys potentiellement Capitalisees (Bronze/Gold/...) mais le
   composant lisait en lowercase. v2_tier_distribution.counts est plus fiable.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._jsexec import require_node, run_module_test
from tests.test_revue_20260803_modales_et_payloads import ACCUEIL_STUBS

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"


class ResolveLatestRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_resolve_latest_run_function_present(self) -> None:
        # get_dashboard ne fournit pas run_info. Cette fonction cherche dans
        # runs_history[] via payload.run_id, fallback sur runs_history[0].
        self.assertIn("function _resolveLatestRun(payload)", self.js)

    def test_finds_run_by_id(self) -> None:
        self.assertIn("runs.find((r) => r && r.run_id === payload.run_id)", self.js)

    def test_fallback_to_first_history_entry(self) -> None:
        # Si le run actuel n'est pas dans l'historique, on prend le premier.
        self.assertIn("runs.length > 0 ? runs[0] : null", self.js)


class TierDistributionNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_normalize_function_present(self) -> None:
        self.assertIn("function _normalizeTierDist(rawDist)", self.js)

    def test_lowercases_keys(self) -> None:
        # Le backend legacy retourne "Bronze"/"Gold"/etc Capitalisees.
        # On lowercase pour pouvoir lire dist[t] avec t in _TIER_ORDER.
        self.assertIn("String(k).toLowerCase()", self.js)

    def test_prefers_v2_tier_distribution(self) -> None:
        # v2_tier_distribution.counts est la version moderne (keys lowercase
        # garantis + structure stable). Doit etre prioritaire sur tier_distribution.
        self.assertIn("stats.v2_tier_distribution.counts", self.js)

    def test_total_uses_sum_of_5_tiers(self) -> None:
        # Le total affiche "(N films classes)" doit etre la somme des 5 tiers,
        # PAS stats.total_scored qui peut inclure des films sans tier ou
        # etre desynchronise.
        self.assertIn("const sumTiers = _TIER_ORDER.reduce", self.js)


class StatusDerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_derives_status_from_errors_and_applied(self) -> None:
        """ERROR si errors_count > 0, PARTIAL si applied < total, DONE sinon.

        Revue adversaire PR #855 : ce test cherchait le NOM `_deriveRunStatus`
        dans la source. Il est tombe quand la derivation a demenage dans
        `core/run-status.js` (source unique partagee avec /historique), alors
        que le comportement teste, lui, ne changeait pas. On execute desormais
        le vrai rendu : le nom du helper n'a plus d'importance, son resultat si.
        """
        require_node(self)
        res = run_module_test(
            _ACCUEIL_JS,
            stubs=ACCUEIL_STUBS,
            extra="export const __t = { render: _renderRecentActivity };\n",
            driver=r"""
const ts = Math.floor(Date.now() / 1000) - 3600;
const mk = (o) => Object.assign({ run_id: "r", status: "DONE", started_ts: ts,
  total_rows: 10, applied_rows: 0, errors_count: 0 }, o);
__emit({
  erreurs: M.__t.render([mk({ errors_count: 3 })]),
  partiel: M.__t.render([mk({ applied_rows: 4 })]),
  termine: M.__t.render([mk({})]),
});
""",
        )
        self.assertIn("— ERROR", res["erreurs"])
        self.assertIn("— PARTIAL", res["partiel"])
        self.assertIn("— DONE", res["termine"])


class TimestampHandlingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_handles_started_ts_epoch_float(self) -> None:
        # Le backend retourne started_ts en epoch float (secondes). On convertit
        # en Date JS via new Date(Number(ts) * 1000).
        self.assertIn("new Date(Number(", self.js)
        self.assertIn("* 1000", self.js)

    def test_score_avg_from_kpis(self) -> None:
        # runs_history[i].avg_score_v2 n'existe pas; on lit payload.kpis.score_avg
        # pour le run actif.
        self.assertIn("kpis.score_avg", self.js)


if __name__ == "__main__":
    unittest.main()
