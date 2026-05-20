"""Tests Phase 6 (Spec 07 Fix 100%) — Export multi-format CSV / JSON / NDJSON.

Couvre les deux moities du fix Spec 07.4.4 :

Backend (cinesort/ui/api/library_actions_support.py) :
  - export_films supporte format="ndjson" (en plus de csv et json) et produit
    un fichier .ndjson conforme : 1 ligne JSON par film, terminee par \n.
  - format inconnu reste rejete (xml, html, etc).

Frontend (web/dashboard/views/bibliotheque.js) :
  - _bulkExport ouvre un selecteur de format AVANT l'appel API (3 options
    csv / json / ndjson) au lieu de passer "csv" hardcode.
  - showModal est importe depuis components/modal.js (pour le selecteur).
  - apiPost("library/export_films", { row_ids, format }) recoit bien le format
    selectionne par l'utilisateur, pas un literal "csv".
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_phase4_bibliotheque_endpoints import _make_mock_api_with_rows

_ROOT = Path(__file__).resolve().parents[1]
_BIBLIOTHEQUE_JS = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_FACADE_PY = _ROOT / "cinesort" / "ui" / "api" / "facades" / "library_facade.py"


# ---------------------------------------------------------------------------
# 1. Backend : export NDJSON
# ---------------------------------------------------------------------------


class ExportNdjsonBackendTests(unittest.TestCase):
    """Spec 07.4.4 : export_films accepte fmt="ndjson"."""

    def _patch_default_state_dir(self, tmp_path: Path):
        return patch(
            "cinesort.ui.api.library_actions_support.state.default_state_dir",
            return_value=tmp_path,
        )

    def test_export_ndjson_returns_ok(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    ["f1", "f2", "f3"],
                    fmt="ndjson",
                    run_id="r1",
                )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["format"], "ndjson")
        self.assertEqual(res["count"], 3)
        self.assertIn("file_path", res)
        self.assertTrue(res["file_path"].endswith(".ndjson"))

    def test_export_ndjson_writes_one_json_per_line(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    ["f1", "f2"],
                    fmt="ndjson",
                    run_id="r1",
                )
            file_path = Path(res["file_path"])
            self.assertTrue(file_path.exists())
            lines = file_path.read_text(encoding="utf-8").splitlines()
        # Pas d'enveloppe : 1 ligne = 1 film, donc autant de lignes que films.
        self.assertEqual(len(lines), 2)
        # Chaque ligne doit etre du JSON valide et representer un dict film
        for line in lines:
            parsed = json.loads(line)
            self.assertIsInstance(parsed, dict)
            self.assertIn("title", parsed)
            self.assertIn("row_id", parsed)
            self.assertIn("tier", parsed)

    def test_export_ndjson_no_top_level_wrapper(self) -> None:
        """Contrairement au JSON qui contient {run_id, films:[...]}, le NDJSON
        ne doit PAS avoir d'enveloppe globale : sinon ce n'est plus du NDJSON."""
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    ["f1"],
                    fmt="ndjson",
                    run_id="r1",
                )
            content = Path(res["file_path"]).read_text(encoding="utf-8")
        # Pas de "films":[ ni "run_id":" au debut.
        self.assertFalse(content.startswith('{"run_id"'))
        self.assertNotIn('"films":', content)

    def test_export_invalid_format_still_rejected(self) -> None:
        """Garde-fou : on accepte csv/json/ndjson mais rien d'autre."""
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    ["f1"],
                    fmt="parquet",
                    run_id="r1",
                )
        self.assertFalse(res["ok"])

    def test_facade_docstring_mentions_ndjson(self) -> None:
        """Le docstring du facade.export_films doit mentionner les 3 formats."""
        text = _FACADE_PY.read_text(encoding="utf-8")
        self.assertIn("NDJSON", text)


# ---------------------------------------------------------------------------
# 2. Frontend : bibliotheque.js ouvre un selecteur de format
# ---------------------------------------------------------------------------


class BibliothequeJsExportPickerTests(unittest.TestCase):
    """Le bouton Exporter ne doit plus hardcoder format:"csv"."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_showmodal_imported(self) -> None:
        """showModal du composant modal.js est utilise pour le selecteur."""
        self.assertIn("showModal", self.js)
        # Import explicite
        self.assertRegex(
            self.js,
            r"import\s*\{[^}]*showModal[^}]*\}\s*from\s*[\"']\.\./components/modal\.js[\"']",
        )

    def test_three_format_options_declared(self) -> None:
        """Les 3 formats CSV / JSON / NDJSON sont presents dans le picker."""
        # Le tableau d'options doit contenir les 3 valeurs.
        self.assertIn('value: "csv"', self.js)
        self.assertIn('value: "json"', self.js)
        self.assertIn('value: "ndjson"', self.js)

    def test_no_more_hardcoded_csv_in_export_call(self) -> None:
        """Le pattern format: "csv" ne doit plus apparaitre dans l'appel d'API
        export_films (pour eviter une regression du fix)."""
        bad = 'apiPost("library/export_films", { row_ids: rowIds, format: "csv" })'
        self.assertNotIn(bad, self.js)

    def test_export_picker_helper_present(self) -> None:
        """Une fonction dediee (_openExportFormatPicker ou _doExport) ouvre
        la modal et passe le format dynamique au backend."""
        self.assertIn("_openExportFormatPicker", self.js)
        # L'appel API utilise une variable, pas un literal "csv".
        self.assertRegex(
            self.js,
            r'apiPost\(\s*"library/export_films"\s*,\s*\{[^}]*format\s*:\s*fmt',
        )

    def test_bulk_export_no_longer_calls_api_directly(self) -> None:
        """_bulkExport doit deleguer au picker, pas appeler apiPost directement."""
        import re

        m = re.search(
            r"async\s+function\s+_bulkExport\s*\([^)]*\)\s*\{(.+?)\n\}\n",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "fonction _bulkExport introuvable")
        body = m.group(1)
        self.assertNotIn("apiPost", body)
        self.assertIn("_openExportFormatPicker", body)


if __name__ == "__main__":
    unittest.main()
