"""Tests Phase 4 backend : 4 endpoints "Aide" (spec 12-aide.md).

Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md section 4.

Endpoints couverts :
    - runtime/get_diagnostic
    - runtime/get_recent_logs(limit=100)
    - runtime/get_doc(file)
    - runtime/search_docs(query)

Couverture securite :
    - Path traversal sur get_doc (`..`, `/`, `\\`, doc_id inconnu)
    - Cap de get_recent_logs a 1000 lignes max
    - Aucun acces a un fichier hors du dossier docs/
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.ui.api import runtime_support
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.docs_whitelist import DOCS_WHITELIST, get_doc_path, list_doc_ids
from cinesort.ui.api.facades import RuntimeFacade


# ---------------------------------------------------------------------------
# RuntimeFacade : exposition + delegation
# ---------------------------------------------------------------------------


class RuntimeFacadeExposureTests(unittest.TestCase):
    """La facade runtime est exposee comme attribut de CineSortApi."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_runtime_facade_exposed(self) -> None:
        self.assertIsInstance(self.api.runtime, RuntimeFacade)

    def test_runtime_facade_delegates(self) -> None:
        """La facade delegue bien vers les methodes _impl du CineSortApi."""
        with patch.object(self.api, "_get_diagnostic_impl", return_value={"ok": True}) as mock:
            self.api.runtime.get_diagnostic()
            mock.assert_called_once_with()

        with patch.object(self.api, "_get_recent_logs_impl", return_value={"ok": True}) as mock:
            self.api.runtime.get_recent_logs(42)
            mock.assert_called_once_with(42)

        with patch.object(self.api, "_get_doc_impl", return_value={"ok": True}) as mock:
            self.api.runtime.get_doc("user-guide")
            mock.assert_called_once_with("user-guide")

        with patch.object(self.api, "_search_docs_impl", return_value={"ok": True}) as mock:
            self.api.runtime.search_docs("hello")
            mock.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# get_diagnostic
# ---------------------------------------------------------------------------


class GetDiagnosticTests(unittest.TestCase):
    """Spec 12-aide.md : diagnostic complet pour le bouton "Copier diagnostic"."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_returns_ok_true(self) -> None:
        result = self.api.runtime.get_diagnostic()
        self.assertTrue(result.get("ok"))
        self.assertIn("diagnostic", result)

    def test_required_fields_present(self) -> None:
        """Tous les champs listes dans la spec sont presents."""
        diag = self.api.runtime.get_diagnostic()["diagnostic"]
        required = {
            "version",
            "build_date",
            "python_version",
            "platform",
            "db_schema_version",
            "ffprobe_version",
            "mediainfo_version",
            "integrations",
            "roots",
            "lib_total",
            "lib_scored",
            "log_path",
            "settings_path",
            "last_run_id",
            "last_run_status",
            "timestamp",
        }
        missing = required - set(diag.keys())
        self.assertFalse(missing, f"Champs manquants: {missing}")

    def test_integrations_has_all_keys(self) -> None:
        """Les 5 integrations TMDB/Jellyfin/Plex/Radarr/OMDb sont listees."""
        diag = self.api.runtime.get_diagnostic()["diagnostic"]
        integrations = diag["integrations"]
        for key in ("tmdb", "jellyfin", "plex", "radarr", "omdb"):
            self.assertIn(key, integrations)
            self.assertIn("configured", integrations[key])
            self.assertIsInstance(integrations[key]["configured"], bool)

    def test_python_version_format(self) -> None:
        """Le python_version est au format X.Y.Z."""
        diag = self.api.runtime.get_diagnostic()["diagnostic"]
        pv = diag["python_version"]
        parts = pv.split(".")
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(parts[0].isdigit())

    def test_timestamp_iso(self) -> None:
        """timestamp est au format ISO 8601 UTC."""
        diag = self.api.runtime.get_diagnostic()["diagnostic"]
        ts = diag["timestamp"]
        # Verifie que c'est parseable (mecanisme minimal).
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_roots_is_list(self) -> None:
        diag = self.api.runtime.get_diagnostic()["diagnostic"]
        self.assertIsInstance(diag["roots"], list)

    def test_lib_counts_are_ints(self) -> None:
        diag = self.api.runtime.get_diagnostic()["diagnostic"]
        self.assertIsInstance(diag["lib_total"], int)
        self.assertIsInstance(diag["lib_scored"], int)
        self.assertGreaterEqual(diag["lib_total"], 0)
        self.assertGreaterEqual(diag["lib_scored"], 0)


# ---------------------------------------------------------------------------
# get_recent_logs
# ---------------------------------------------------------------------------


class GetRecentLogsTests(unittest.TestCase):
    """Spec 12-aide.md : N dernieres lignes du log courant."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def _write_fake_log(self, lines: list[str], tmpdir: Path) -> Path:
        log_dir = tmpdir / "CineSort" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "cinesort.log"
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log_file

    def test_missing_log_returns_empty(self) -> None:
        """Si le fichier log n'existe pas, on retourne lines=[] sans erreur."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                result = self.api.runtime.get_recent_logs(50)
                self.assertTrue(result["ok"])
                self.assertEqual(result["lines"], [])

    def test_limit_max_50(self) -> None:
        """get_recent_logs(50) retourne au maximum 50 lignes."""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            lines = [f"line {i}" for i in range(200)]
            self._write_fake_log(lines, tmpdir)
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                result = self.api.runtime.get_recent_logs(50)
                self.assertTrue(result["ok"])
                self.assertLessEqual(len(result["lines"]), 50)
                # Les lignes retournees sont les dernieres.
                self.assertEqual(result["lines"][-1], "line 199")

    def test_limit_capped_at_1000(self) -> None:
        """Limit > 1000 est cap a 1000 (defense en profondeur)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            lines = [f"l{i}" for i in range(5000)]
            self._write_fake_log(lines, tmpdir)
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                result = self.api.runtime.get_recent_logs(99999)
                self.assertTrue(result["ok"])
                self.assertLessEqual(len(result["lines"]), 1000)

    def test_strips_ansi_codes(self) -> None:
        """Les sequences ANSI sont strippees."""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            # "\x1b[31mROUGE\x1b[0m message"
            self._write_fake_log(["\x1b[31mROUGE\x1b[0m message"], tmpdir)
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                result = self.api.runtime.get_recent_logs(10)
                self.assertTrue(result["ok"])
                self.assertEqual(result["lines"][0], "ROUGE message")

    def test_invalid_limit_falls_back(self) -> None:
        """limit non-int retombe sur defaut (100)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_fake_log(["a"], tmpdir)
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                result = self.api.runtime.get_recent_logs("not-a-number")  # type: ignore[arg-type]
                self.assertTrue(result["ok"])


# ---------------------------------------------------------------------------
# get_doc
# ---------------------------------------------------------------------------


class GetDocTests(unittest.TestCase):
    """Spec 12-aide.md : lecture markdown whiteliste, refus path traversal."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_user_guide_returns_content(self) -> None:
        """get_doc("user-guide") retourne content non vide."""
        result = self.api.runtime.get_doc("user-guide")
        self.assertTrue(result["ok"])
        self.assertIn("content", result)
        self.assertGreater(len(result["content"]), 0)
        self.assertEqual(result["doc_id"], "user-guide")

    def test_case_insensitive_doc_id(self) -> None:
        """Le doc_id est case-insensitive."""
        result = self.api.runtime.get_doc("User-Guide")
        self.assertTrue(result["ok"])

    def test_path_traversal_dotdot_rejected(self) -> None:
        """get_doc("../../etc/passwd") est rejete avec category=validation."""
        result = self.api.runtime.get_doc("../../etc/passwd")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_path_traversal_slash_rejected(self) -> None:
        result = self.api.runtime.get_doc("docs/USER_GUIDE_v2.md")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_path_traversal_backslash_rejected(self) -> None:
        result = self.api.runtime.get_doc("..\\..\\etc\\passwd")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_unknown_doc_id_rejected(self) -> None:
        result = self.api.runtime.get_doc("unknown-doc-id")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_empty_doc_id_rejected(self) -> None:
        result = self.api.runtime.get_doc("")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_null_byte_rejected(self) -> None:
        """Caractere null byte rejete (anti smuggling)."""
        result = self.api.runtime.get_doc("user-guide\x00.md")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_tilde_rejected(self) -> None:
        """Tilde rejete (eviter expansion de home)."""
        result = self.api.runtime.get_doc("~user-guide")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("category"), "validation")

    def test_available_list_returned_on_error(self) -> None:
        """En cas d'erreur, la liste des doc_id disponibles est fournie."""
        result = self.api.runtime.get_doc("unknown")
        self.assertIn("available", result)
        self.assertIsInstance(result["available"], list)
        self.assertIn("user-guide", result["available"])

    def test_all_whitelisted_docs_readable(self) -> None:
        """Tous les doc_id de la whitelist sont accessibles (si fichier present)."""
        for doc_id in list_doc_ids():
            with self.subTest(doc_id=doc_id):
                # Verifie d'abord que le fichier existe dans le repo
                rel = get_doc_path(doc_id)
                assert rel is not None
                repo = Path(__file__).resolve().parents[1]
                if not (repo / rel).is_file():
                    continue
                result = self.api.runtime.get_doc(doc_id)
                self.assertTrue(result["ok"], f"Echec pour doc_id={doc_id}")


# ---------------------------------------------------------------------------
# search_docs
# ---------------------------------------------------------------------------


class SearchDocsTests(unittest.TestCase):
    """Spec 12-aide.md : recherche full-text grep avec contexte +/- 2 lignes."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_empty_query_returns_empty(self) -> None:
        result = self.api.runtime.search_docs("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"], [])

    def test_score_search_returns_hits(self) -> None:
        """search_docs("score") retourne des resultats."""
        result = self.api.runtime.search_docs("score")
        self.assertTrue(result["ok"])
        self.assertGreater(len(result["results"]), 0, "Aucun hit pour 'score' dans la doc")
        first = result["results"][0]
        self.assertIn("doc_id", first)
        self.assertIn("title", first)
        self.assertIn("snippet", first)
        self.assertIn("line_number", first)

    def test_results_have_line_number(self) -> None:
        """Chaque resultat fournit un line_number >= 1."""
        result = self.api.runtime.search_docs("CineSort")
        self.assertTrue(result["ok"])
        for hit in result["results"]:
            self.assertGreaterEqual(hit["line_number"], 1)

    def test_case_insensitive(self) -> None:
        """La recherche est case-insensitive."""
        low = self.api.runtime.search_docs("cinesort")
        up = self.api.runtime.search_docs("CINESORT")
        # Devraient retourner le meme nombre de hits (au minimum).
        self.assertEqual(len(low["results"]), len(up["results"]))

    def test_results_capped(self) -> None:
        """Le nombre de resultats est cap a 50."""
        result = self.api.runtime.search_docs("e")  # tres frequent
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["results"]), 50)

    def test_no_match_returns_empty(self) -> None:
        result = self.api.runtime.search_docs("xyzabcdefghijk-needle-not-in-docs-1234")
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"], [])


# ---------------------------------------------------------------------------
# Docs whitelist : invariants
# ---------------------------------------------------------------------------


class DocsWhitelistInvariantsTests(unittest.TestCase):
    """La whitelist ne doit contenir aucun chemin dangereux."""

    def test_no_dotdot_in_paths(self) -> None:
        for doc_id, rel in DOCS_WHITELIST.items():
            with self.subTest(doc_id=doc_id):
                self.assertNotIn("..", rel)
                self.assertFalse(rel.startswith("/"))
                self.assertFalse(rel.startswith("\\"))

    def test_all_paths_under_docs(self) -> None:
        """Tous les chemins sont sous `docs/`."""
        for doc_id, rel in DOCS_WHITELIST.items():
            with self.subTest(doc_id=doc_id):
                self.assertTrue(rel.startswith("docs/"), f"{doc_id}: {rel}")

    def test_user_guide_present(self) -> None:
        """user-guide pointe vers docs/USER_GUIDE_v2.md (cf spec section 2)."""
        self.assertEqual(DOCS_WHITELIST.get("user-guide"), "docs/USER_GUIDE_v2.md")


# ---------------------------------------------------------------------------
# Module runtime_support : helpers internes
# ---------------------------------------------------------------------------


class HelperInternalsTests(unittest.TestCase):
    """Tests cibles sur les helpers internes pour augmenter la couverture."""

    def test_strip_ansi_no_op(self) -> None:
        self.assertEqual(runtime_support._strip_ansi("hello world"), "hello world")

    def test_strip_ansi_removes_color(self) -> None:
        self.assertEqual(runtime_support._strip_ansi("\x1b[1;31mhi\x1b[0m"), "hi")


if __name__ == "__main__":
    unittest.main()
