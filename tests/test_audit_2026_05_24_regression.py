"""Tests de regression - audit 2026-05-24 (v1.5.0).

Couvre les fixes du sprint d'audit qui ont reintroduit silencieusement des
endpoints et sections settings perdus, et corrige des appels API frontend
incoherents avec les facades Python.

Bugs couverts :
- `run_id_or` -> `run_id: "latest"` dans traitement.js / doublons.js
  (parametre `run_id_or` n'existe pas dans la facade run/get_dashboard).
- Sections settings absentes du dispatcher (`_save_section_omdb`,
  `_save_section_naming`, `_save_section_sources`, `_save_section_advanced`)
  qui causaient un drop silencieux de 16+ champs UI a chaque save.
- Endpoint `runtime/open_external_url` manquant cote facade alors qu'il
  etait appele depuis le frontend.
- `analyze_perceptual_single` n'existe pas backend : film-detail.js doit
  utiliser `quality/analyze_perceptual_batch` avec `row_ids: [rowId]`.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from cinesort.ui.api import settings_support
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.facades import runtime_facade


_ROOT = Path(__file__).resolve().parents[1]


class FrontendApiCallsTests(unittest.TestCase):
    """Verifie que le frontend utilise les bons noms de parametres."""

    def _strip_comments(self, src: str) -> str:
        """Retire commentaires // et /* */ pour eviter les faux positifs sur
        les mentions historiques (ex: `Fix audit ... avant run_id_or`).
        """
        import re

        # Bloc /* ... */ (non-greedy, multiline).
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        # Ligne // ... jusqu'au newline.
        src = re.sub(r"//[^\n]*", "", src)
        return src

    def test_run_id_param_in_traitement_js(self):
        path = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
        content = path.read_text(encoding="utf-8")
        code = self._strip_comments(content)
        self.assertNotIn(
            "run_id_or",
            code,
            "traitement.js ne doit plus utiliser `run_id_or` (parametre inexistant) "
            "hors commentaires.",
        )
        self.assertIn(
            'run_id: "latest"',
            content,
            "traitement.js doit utiliser `run_id: \"latest\"` pour run/get_dashboard.",
        )

    def test_run_id_param_in_doublons_js(self):
        path = _ROOT / "web" / "dashboard" / "views" / "doublons.js"
        content = path.read_text(encoding="utf-8")
        code = self._strip_comments(content)
        self.assertNotIn(
            "run_id_or",
            code,
            "doublons.js ne doit plus utiliser `run_id_or` (parametre inexistant) "
            "hors commentaires.",
        )
        self.assertIn(
            'run_id: "latest"',
            content,
            "doublons.js doit utiliser `run_id: \"latest\"` pour run/get_dashboard.",
        )

    def test_film_detail_uses_perceptual_batch(self):
        path = _ROOT / "web" / "dashboard" / "views" / "film-detail.js"
        content = path.read_text(encoding="utf-8")
        # Le mot "analyze_perceptual_single" peut apparaitre dans un commentaire
        # explicatif (fix audit), donc on cherche uniquement l'usage comme
        # endpoint : entre guillemets avec slash prefix typique apiPost.
        self.assertNotIn(
            '"quality/analyze_perceptual_single"',
            content,
            "film-detail.js ne doit plus appeler l'endpoint inexistant "
            "`quality/analyze_perceptual_single`.",
        )
        self.assertIn(
            "quality/analyze_perceptual_batch",
            content,
            "film-detail.js doit utiliser `quality/analyze_perceptual_batch`.",
        )


class SettingsDispatcherSectionsTests(unittest.TestCase):
    """Verifie que chaque section settings dispose d'un handler ET est appelee
    dans le dispatcher principal (`build_settings_payload`).
    """

    def _dispatcher_source(self) -> str:
        # Source du dispatcher central qui agrege toutes les sections.
        return inspect.getsource(settings_support.save_settings_payload)

    def test_save_section_omdb_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_omdb"),
            "`_save_section_omdb` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_omdb",
            self._dispatcher_source(),
            "`_save_section_omdb` doit etre appele dans save_settings_payload.",
        )

    def test_save_section_naming_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_naming"),
            "`_save_section_naming` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_naming",
            self._dispatcher_source(),
            "`_save_section_naming` doit etre appele dans save_settings_payload.",
        )

    def test_save_section_sources_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_sources"),
            "`_save_section_sources` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_sources",
            self._dispatcher_source(),
            "`_save_section_sources` doit etre appele dans save_settings_payload.",
        )

    def test_save_section_advanced_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_advanced"),
            "`_save_section_advanced` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_advanced",
            self._dispatcher_source(),
            "`_save_section_advanced` doit etre appele dans save_settings_payload.",
        )


class RuntimeOpenExternalUrlTests(unittest.TestCase):
    """Verifie que l'endpoint `runtime/open_external_url` existe cote API."""

    def test_open_external_url_endpoint_exists(self):
        # Cote CineSortApi : implementation interne `_open_external_url_impl`.
        self.assertTrue(
            hasattr(CineSortApi, "_open_external_url_impl"),
            "CineSortApi doit exposer `_open_external_url_impl`.",
        )
        # Cote facade : methode publique `open_external_url`.
        self.assertTrue(
            hasattr(runtime_facade.RuntimeFacade, "open_external_url"),
            "RuntimeFacade doit exposer `open_external_url`.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
