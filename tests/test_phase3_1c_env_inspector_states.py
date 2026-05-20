"""Tests Phase 3.1-C : Accueil — Environment bar + Inspecteur droit + États dynamiques.

Etend les tests Phase 3.1-A et 3.1-B. Couvre la section 1 + l'inspecteur droit
+ l'etat "scan en cours" selon spec 05-accueil.md.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class EnvironmentBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_render_environment_bar_function(self) -> None:
        # Phase 5 : la signature accepte un 3eme parametre optionnel pingResults
        # pour le statut hors-ligne. On verifie au moins les 2 premiers.
        self.assertIn("function _renderEnvironmentBar(roots, settings", self.js)

    def test_integrations_list_complete(self) -> None:
        # Spec : 5 integrations - TMDb, Jellyfin, Plex, Radarr, OMDb.
        for key in ("tmdb", "jellyfin", "plex", "radarr", "omdb"):
            self.assertIn(f'key: "{key}"', self.js, f"integration {key} manquante")

    def test_roots_truncated_to_2(self) -> None:
        # Spec §2.1 : tronque si > 2 roots, affiche "+N" pour le surplus.
        self.assertIn("rootsList.slice(0, 2)", self.js)
        self.assertIn("accueil-env-more", self.js)

    def test_empty_roots_message(self) -> None:
        self.assertIn("Aucun root configuré", self.js)

    def test_pill_states_ok_and_off(self) -> None:
        self.assertIn("is-ok", self.js)
        self.assertIn("is-off", self.js)

    def test_pills_clickable_to_settings_integrations(self) -> None:
        # Spec §2.1 : clic pastille -> Paramètres > Intégrations > section concernée.
        self.assertIn('data-integration="', self.js)
        self.assertIn("/parametres#integrations-", self.js)

    def test_bar_displayed_at_top(self) -> None:
        # Doit apparaitre dans _renderAccueil AVANT le hero. On cherche les
        # APPELS dans le HTML template (chaque appel est prefixe par ${).
        # Phase 5 : l'appel inclut maintenant un 3eme argument (pingSnapshot).
        import re

        rendered = self.js
        env_pos = -1
        for m in re.finditer(r"\$\{_renderEnvironmentBar\(roots, settings[^}]*\)\}", rendered):
            env_pos = m.start()
            break
        hero_pos = rendered.find("${_renderHero(heroState)}")
        self.assertNotEqual(env_pos, -1, "Environment bar non rendue dans le template _renderAccueil")
        self.assertNotEqual(hero_pos, -1, "Hero non rendu dans le template _renderAccueil")
        self.assertLess(env_pos, hero_pos, "Environment bar doit etre AVANT le Hero dans le template")


class ScanInProgressStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_extract_scan_progress_function(self) -> None:
        self.assertIn("function _extractScanProgress(payload)", self.js)

    def test_render_scan_in_progress_function(self) -> None:
        self.assertIn("function _renderScanInProgress(progress)", self.js)

    def test_progress_bar_with_aria(self) -> None:
        self.assertIn('class="accueil-cta-scan-bar"', self.js)
        self.assertIn('role="progressbar"', self.js)

    def test_cta_branches_on_scan_active(self) -> None:
        # _renderCtaScan retourne _renderScanInProgress si scanProgress.active.
        self.assertIn("if (scanProgress && scanProgress.active)", self.js)

    def test_view_traitement_action_present(self) -> None:
        self.assertIn("open-traitement", self.js)
        self.assertIn("Voir le détail", self.js)


class InspectorContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_import_right_panel(self) -> None:
        self.assertIn('from "../components/right-panel.js"', self.js)
        self.assertIn("import * as rightPanel", self.js)

    def test_build_inspector_sections_function(self) -> None:
        self.assertIn("function _buildInspectorSections(payload, stats, settings)", self.js)

    def test_inspector_has_3_sections(self) -> None:
        # Spec §3 : Contexte / Rappels opérateur / Raccourcis.
        self.assertIn('title: "Contexte"', self.js)
        self.assertIn('title: "Rappels opérateur"', self.js)
        self.assertIn('title: "Raccourcis"', self.js)

    def test_context_section_shows_library_count(self) -> None:
        self.assertIn("Bibliothèque", self.js)
        self.assertIn("Run actif", self.js)
        self.assertIn("Dernier scan", self.js)

    def test_shortcuts_section_lists_keys(self) -> None:
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>S</kbd>", self.js)
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>K</kbd>", self.js)
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>,</kbd>", self.js)
        self.assertIn("<kbd>?</kbd>", self.js)

    def test_reminders_logic_for_omdb_not_configured(self) -> None:
        # Spec §3 : alerte "OMDb non configuré".
        self.assertIn("OMDb non configuré", self.js)

    def test_reminders_for_awaiting_validation(self) -> None:
        self.assertIn("AWAITING_VALIDATION", self.js)
        self.assertIn("valider la run", self.js)

    def test_init_calls_right_panel_set_sections(self) -> None:
        self.assertIn("rightPanel.setSections(_buildInspectorSections(", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_env_bar_height_32(self) -> None:
        self.assertIn(".accueil-env-bar", self.css)
        self.assertIn("height: 32px", self.css)

    def test_env_pill_classes(self) -> None:
        self.assertIn(".accueil-env-pill", self.css)
        self.assertIn(".accueil-env-pill.is-ok", self.css)
        self.assertIn(".accueil-env-pill.is-off", self.css)

    def test_scan_progress_classes(self) -> None:
        self.assertIn(".accueil-cta-scan--running", self.css)
        self.assertIn(".accueil-cta-scan-bar", self.css)
        self.assertIn(".accueil-cta-scan-fill", self.css)

    def test_inspector_classes(self) -> None:
        self.assertIn(".accueil-inspector-dl", self.css)
        self.assertIn(".accueil-inspector-shortcuts", self.css)
        self.assertIn(".accueil-inspector-list", self.css)


if __name__ == "__main__":
    unittest.main()
