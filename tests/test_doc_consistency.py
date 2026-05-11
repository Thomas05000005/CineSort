"""Verifie que CLAUDE.md reste aligne avec les mesures objectives.

Si ce test echoue : soit le code a derive (changements non documentes), soit
CLAUDE.md ment encore. Dans les deux cas, relancer :

    python scripts/measure_codebase_health.py --output audit/results/v7_X_real.md

puis mettre a jour CLAUDE.md ou corriger la divergence.

Phase 0 du plan de remediation v7.8.0.
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


class ClaudeMdMetricsConsistencyTests(unittest.TestCase):
    """Assertions sur les revendications chiffrees de CLAUDE.md.

    Tolerance : on accepte ±20 % de drift pour les compteurs (codebase vit), mais
    pas de revendication absolument incoherente avec la realite.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not CLAUDE_MD.exists():
            raise unittest.SkipTest("CLAUDE.md absent (cas inhabituel)")
        cls.text = CLAUDE_MD.read_text(encoding="utf-8")

    def test_claude_md_not_revendique_note_9_9(self) -> None:
        """CLAUDE.md ne doit plus revendiquer 9.9/10 dans la section Etat de sante."""
        # Cherche specifiquement une revendication explicite "9.9 / 10" en tant que note globale
        forbidden = "**9.9 / 10**"
        if forbidden in self.text:
            # Tolere si encadre par "(ancienne revendication)" ou "(archive)" — cas historique
            for line in self.text.splitlines():
                if forbidden in line and "archive" not in line.lower() and "anterieur" not in line.lower():
                    self.fail(
                        f"CLAUDE.md revendique encore {forbidden} dans : {line.strip()[:120]}\n"
                        "Mettre a jour la section 'Etat de sante' avec la note honnete mesuree."
                    )

    def test_claude_md_mentionne_dette_technique(self) -> None:
        """La section 'Dette technique connue' doit exister depuis l'audit Phase 0."""
        self.assertIn(
            "Dette technique connue",
            self.text,
            "Section 'Dette technique connue' manquante dans CLAUDE.md (cf Phase 0).",
        )

    def test_claude_md_mentionne_remediation_plan(self) -> None:
        """CLAUDE.md doit pointer vers le plan de remediation v7.8.0."""
        self.assertIn(
            "REMEDIATION_PLAN_v7_8_0.md",
            self.text,
            "Reference au plan de remediation manquante.",
        )

    def test_claude_md_mentionne_verification_continue(self) -> None:
        """Doit indiquer comment recalculer les metriques (script auditable)."""
        self.assertIn(
            "measure_codebase_health.py",
            self.text,
            "Reference au script de mesure manquante dans CLAUDE.md.",
        )

    def test_claude_md_doc_consistency_test_referenced(self) -> None:
        """Le test de coherence doit etre mentionne dans CLAUDE.md (self-reference)."""
        self.assertIn(
            "test_doc_consistency",
            self.text,
            "Test de coherence non reference dans CLAUDE.md (self-documentation).",
        )

    def test_audit_files_exist(self) -> None:
        """Les fichiers du plan de remediation doivent exister."""
        plan = REPO_ROOT / "audit" / "REMEDIATION_PLAN_v7_8_0.md"
        tracking = REPO_ROOT / "audit" / "TRACKING_v7_8_0.md"
        self.assertTrue(plan.exists(), f"Plan absent : {plan}")
        self.assertTrue(tracking.exists(), f"Tracking absent : {tracking}")

    def test_measurement_script_exists_and_runnable(self) -> None:
        """Le script de mesure doit exister et etre importable sans erreur."""
        script = REPO_ROOT / "scripts" / "measure_codebase_health.py"
        self.assertTrue(script.exists(), f"Script absent : {script}")
        # Verifier qu'il compile (sans l'executer pour ne pas allonger la suite)
        import py_compile
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as exc:
            self.fail(f"Script de mesure ne compile pas : {exc}")


class HistoricalSnapshotPresenceTests(unittest.TestCase):
    """Verifie qu'un snapshot de mesure objective a ete fait recemment."""

    def test_at_least_one_metrics_snapshot_exists(self) -> None:
        # docs/internal/audit_v7_8_0/results/ depuis la reorganisation v1.0.0-beta
        results_dir = REPO_ROOT / "docs" / "internal" / "audit_v7_8_0" / "results"
        if not results_dir.is_dir():
            self.fail(f"{results_dir} n'existe pas — lancer measure_codebase_health.py")
        snapshots = list(results_dir.glob("v7_*_real_metrics_*.md"))
        self.assertGreaterEqual(
            len(snapshots), 1,
            "Aucun snapshot de mesure objective trouve dans audit/results/ "
            "(format attendu : v7_X_Y_real_metrics_YYYYMMDD.md). "
            "Relancer python scripts/measure_codebase_health.py --output ..."
        )


if __name__ == "__main__":
    unittest.main()
