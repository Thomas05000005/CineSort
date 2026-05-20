"""Tests Phase 3.1-A : nouvelle vue Accueil (spec 05-accueil.md).

Couvre la PR initiale (Hero + Card Dernier run + Activite recente) :
- Existence du fichier web/dashboard/views/accueil.js
- API ESM exportee (initAccueil, computeHeroSummary, formatRelativeTime)
- Helpers de format (relatif: Aujourd'hui/Hier/etc)
- Resume dynamique du Hero selon l'etat
- Cablage de la route /accueil vers initAccueil dans app.js
- CSS classes .accueil-* presentes dans web/shared/components.css

Les sections 1 (Environment bar), 3 (CTA Scan), 4 (Suggestions), 5 (Sante
biblio) et l'inspecteur droit sont couverts par les tests des PRs 3.1-B et 3.1-C.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_accueil_view_exists(self) -> None:
        self.assertTrue(_ACCUEIL_JS.is_file(), f"manquant : {_ACCUEIL_JS}")


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_exports_init_accueil(self) -> None:
        self.assertIn("export async function initAccueil(", self.js)

    def test_exports_compute_hero_summary(self) -> None:
        self.assertIn("export function computeHeroSummary(", self.js)

    def test_exports_format_relative_time(self) -> None:
        self.assertIn("export function formatRelativeTime(", self.js)


class HeroSummaryLogicTests(unittest.TestCase):
    """Spec 05 §2 Hero : 6 phrases selon l'etat agrege."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_error_critical_summary_present(self) -> None:
        self.assertIn("Problème : la base de données n'est pas accessible.", self.js)

    def test_no_run_welcome_summary(self) -> None:
        self.assertIn("Bienvenue. Lance ton premier scan pour commencer.", self.js)

    def test_zero_alert_positive_summary(self) -> None:
        self.assertIn("Ta bibliothèque va bien.", self.js)

    def test_few_alerts_neutral_summary(self) -> None:
        self.assertIn("Ta bibliothèque va bien, quelques points à voir.", self.js)

    def test_many_alerts_warning_summary(self) -> None:
        self.assertIn("Ta bibliothèque demande ton attention.", self.js)

    def test_active_run_summary_template(self) -> None:
        # Phrase dynamique : "Scan en cours sur N films. ~M min restant."
        self.assertIn("Scan en cours sur", self.js)


class RelativeTimeFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_aujourdhui_label(self) -> None:
        self.assertIn("Aujourd'hui", self.js)

    def test_hier_label(self) -> None:
        self.assertIn("Hier", self.js)

    def test_il_y_a_n_jours_template(self) -> None:
        self.assertIn("Il y a", self.js)
        self.assertIn("jours", self.js)


class LastRunCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_section_title_dernier_run(self) -> None:
        self.assertIn("Dernier run", self.js)

    def test_renders_film_count_score_confidence(self) -> None:
        self.assertIn("Films", self.js)
        self.assertIn("Score moyen", self.js)
        self.assertIn("Confiance moyenne", self.js)

    def test_resume_validation_button_conditional(self) -> None:
        # Spec §2 : bouton "Reprendre la validation" visible si AWAITING_VALIDATION.
        self.assertIn("AWAITING_VALIDATION", self.js)
        self.assertIn("Reprendre la validation", self.js)

    def test_view_detail_action_present(self) -> None:
        self.assertIn("view-run-detail", self.js)

    def test_empty_state_placeholder(self) -> None:
        self.assertIn("Aucun run encore", self.js)


class RecentActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_section_title_activite_recente(self) -> None:
        self.assertIn("Activité récente", self.js)

    def test_limit_to_3_runs(self) -> None:
        # Spec §6 : 3 derniers runs max via slice. Phase 5 : la liste tabulaire
        # a ete remplacee par la timeline 7j (qui affiche tous les runs sur 7j).
        # On verifie qu'au moins la limite de 3 est utilisee (suggestions).
        self.assertIn("slice(0, 3)", self.js)

    def test_status_classes_for_severity(self) -> None:
        # Phase 5 : la liste tabulaire a ete remplacee par une timeline visuelle.
        # Les classes de statut sont maintenant sur les bullets de la timeline :
        # accueil-timeline-bullet--applied / --partial / --error / --done.
        for cls in (
            "accueil-timeline-bullet--applied",
            "accueil-timeline-bullet--partial",
            "accueil-timeline-bullet--error",
            "accueil-timeline-bullet--done",
        ):
            self.assertIn(cls, self.js)

    def test_view_history_button_present(self) -> None:
        self.assertIn("view-history", self.js)


class NavigationActionsTests(unittest.TestCase):
    """Les boutons d'action doivent naviguer vers les routes FR canoniques."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_start_scan_navigates_to_traitement(self) -> None:
        self.assertIn('navigateTo("/traitement")', self.js)

    def test_view_history_navigates_to_historique(self) -> None:
        self.assertIn('navigateTo("/historique")', self.js)


class XssEscapingTests(unittest.TestCase):
    """Garde XSS : escapeHtml doit etre utilise sur les champs utilisateur."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_escapes_run_id(self) -> None:
        self.assertIn("escapeHtml(latestRun.run_id)", self.js)

    def test_escapes_relative_date(self) -> None:
        self.assertIn("escapeHtml(date)", self.js)

    def test_escapes_summary_text(self) -> None:
        self.assertIn("escapeHtml(summary)", self.js)

    def test_imports_escape_html(self) -> None:
        self.assertIn("escapeHtml", self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports_init_accueil(self) -> None:
        self.assertIn('from "./views/accueil.js"', self.js)
        self.assertIn("initAccueil", self.js)

    def test_route_accueil_uses_init_accueil(self) -> None:
        # La route /accueil doit cabler initAccueil (et pas l'ancienne initStatus).
        # On extrait la ligne de la registration de /accueil et on verifie le init.
        line_start = self.js.find('registerRoute("/accueil"')
        self.assertNotEqual(line_start, -1, "route /accueil manquante")
        line_end = self.js.find("\n", line_start)
        snippet = self.js[line_start:line_end]
        self.assertIn("init: initAccueil", snippet)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_accueil_view_root_class(self) -> None:
        self.assertIn(".accueil-view {", self.css)

    def test_accueil_hero_classes(self) -> None:
        self.assertIn(".accueil-hero {", self.css)
        self.assertIn(".accueil-hero-greeting", self.css)
        self.assertIn(".accueil-hero-summary", self.css)

    def test_accueil_section_class(self) -> None:
        self.assertIn(".accueil-section {", self.css)
        self.assertIn(".accueil-section-title", self.css)

    def test_accueil_last_run_classes(self) -> None:
        self.assertIn(".accueil-last-run", self.css)
        self.assertIn(".accueil-last-run-stats", self.css)

    def test_accueil_activity_classes(self) -> None:
        self.assertIn(".accueil-activity", self.css)
        self.assertIn(".accueil-activity-row", self.css)
        self.assertIn(".accueil-activity-status", self.css)

    def test_status_color_classes(self) -> None:
        # 3 etats de severite : done / partial / error.
        for cls in ("is-done", "is-partial", "is-error"):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
