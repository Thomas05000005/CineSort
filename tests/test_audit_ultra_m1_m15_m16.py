"""AUDIT ULTRA 2026-07-13 vague 4 — M15 (export CSV) + M16 (cle doublon) + M1 (snapshot sante).

M15 : library_actions_support.export_films(fmt="csv") ecrivait un CSV en
      encoding="utf-8" (SANS BOM) + separateur "," par defaut, alors que l'autre
      export CSV du produit (dashboard_support.report_to_csv_text /
      write_run_report_file) suit la convention Excel-FR : BOM UTF-8 (`utf-8-sig`)
      + separateur ";". Les deux exports divergeaient. -> aligner l'export Biblio.

M16 : history_support duplicates_decided affichait la group_key BRUTE
      ("le seigneur des anneaux|2001") quand la cle n'etait pas au format
      "Titre (AAAA)". -> afficher le titre propre du row gagnant, parsing en repli.

M1  : run_flow_support figeait un snapshot sante (health_score,
      subtitle_coverage_pct) au scan AVANT que le probe n'ait produit les
      quality_reports (`generate_suggestions(rows, [], settings)` = liste VIDE)
      -> donnees sous-titres/codecs/resolution incompletes, jamais reconciliees.
      -> ne plus fabriquer ces metriques au scan (None, comme resolution_4k_pct).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_phase4_bibliotheque_endpoints import _make_mock_api_with_rows

_ROOT = Path(__file__).resolve().parents[1]
_RUN_FLOW_PY = _ROOT / "cinesort" / "ui" / "api" / "run_flow_support.py"


# ===========================================================================
# M15 : export CSV Biblio = BOM UTF-8 + separateur ";"
# ===========================================================================
class ExportCsvExcelFrConventionTests(unittest.TestCase):
    def _patch_default_state_dir(self, tmp_path: Path):
        return patch(
            "cinesort.ui.api.library_actions_support.state.default_state_dir",
            return_value=tmp_path,
        )

    def _export_csv(self, tmp: str) -> Path:
        from cinesort.ui.api import library_actions_support

        api = _make_mock_api_with_rows(Path(tmp))
        with self._patch_default_state_dir(Path(tmp)):
            res = library_actions_support.export_films(
                api, ["f1", "f2", "f3"], fmt="csv", run_id="r1"
            )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["format"], "csv")
        return Path(res["file_path"])

    def test_csv_starts_with_utf8_bom(self) -> None:
        """Convention Excel-FR : le fichier commence par le BOM UTF-8."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = self._export_csv(tmp).read_bytes()
        # AVANT le fix : encoding="utf-8" -> pas de BOM.
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM UTF-8 manquant en tete du CSV")

    def test_csv_uses_semicolon_delimiter(self) -> None:
        """Convention Excel-FR : separateur ";" (pas ",") comme dashboard_support."""
        with tempfile.TemporaryDirectory() as tmp:
            text = self._export_csv(tmp).read_text(encoding="utf-8-sig")
        header = text.splitlines()[0]
        # AVANT le fix : "row_id,title,year,..." (virgule).
        self.assertIn("row_id;title;year", header)
        self.assertNotIn("row_id,title,year", header)

    def test_csv_matches_dashboard_convention(self) -> None:
        """Meme couple (BOM + ";") que write_run_report_file (source unique de verite)."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = self._export_csv(tmp).read_bytes()
        text = raw.decode("utf-8-sig")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        # Une ligne de donnees doit contenir au moins un ";" (>=2 colonnes).
        self.assertIn(";", text.splitlines()[1] if len(text.splitlines()) > 1 else "")


# ===========================================================================
# M16 : titre lisible du groupe de doublons (pas la group_key brute)
# ===========================================================================
class _FakeQualityRepo:
    def list_quality_reports(self, *, run_id):
        return []


class _FakeApplyRepo:
    def __init__(self, decisions):
        self._decisions = decisions

    def get_last_reversible_apply_batch(self, run_id):
        return None

    def list_apply_operations(self, *, batch_id):
        return []

    def list_duplicate_decisions(self, *, run_id):
        return self._decisions


class _FakeRunRepo:
    def list_errors(self, run_id):
        return []


class _FakeStore:
    def __init__(self, decisions):
        self.run = _FakeRunRepo()
        self.quality = _FakeQualityRepo()
        self.apply = _FakeApplyRepo(decisions)


class _FakeRunFacade:
    def __init__(self, plan_rows):
        self._plan_rows = plan_rows

    def get_plan(self, run_id):
        return {"ok": True, "rows": self._plan_rows}

    def load_validation(self, run_id):
        return {"ok": True, "decisions": {}}


class _FakeApi:
    def __init__(self, row, store, plan_rows):
        self._row = row
        self._store = store
        self.run = _FakeRunFacade(plan_rows)
        self._state_dir = str(Path.cwd())

    def _is_valid_run_id(self, run_id):
        return bool(run_id)

    def _find_run_row(self, run_id):
        return (self._row, self._store)

    def _run_paths_for(self, _state_dir, _run_id, ensure_exists=False):
        from types import SimpleNamespace

        return SimpleNamespace(plan_jsonl=Path(self._state_dir) / "nope.jsonl")


class DuplicateReadableTitleTests(unittest.TestCase):
    def _decided(self, plan_rows, decisions):
        from cinesort.ui.api.history_support import get_history_stats

        rid = "20260101_100000_000"
        row = {
            "run_id": rid,
            "started_ts": 1000.0,
            "ended_ts": 1100.0,
            "status": "DONE",
            "state_dir": str(Path.cwd()),
            "total": len(plan_rows),
            "stats_json": json.dumps({"planned_rows": len(plan_rows)}),
        }
        api = _FakeApi(row, _FakeStore(decisions), plan_rows)
        out = get_history_stats(api, rid)
        self.assertTrue(out.get("ok"), out)
        return out["run"]["duplicates_decided"]

    def test_pipe_key_shows_winner_clean_title(self) -> None:
        """group_key "titre minuscule|annee" -> titre propre du gagnant, pas la cle."""
        plan_rows = [
            {"row_id": "w1", "proposed_title": "Le Seigneur des Anneaux", "proposed_year": 2001},
            {"row_id": "l1", "proposed_title": "Le Seigneur des Anneaux", "proposed_year": 2001},
        ]
        decisions = [
            {
                "group_key": "le seigneur des anneaux|2001",
                "winner_row_id": "w1",
                "loser_row_ids": ["l1"],
            }
        ]
        decided = self._decided(plan_rows, decisions)
        self.assertEqual(len(decided), 1)
        g = decided[0]
        # AVANT le fix : g["title"] == "le seigneur des anneaux|2001" (cle brute).
        self.assertEqual(g["title"], "Le Seigneur des Anneaux")
        self.assertEqual(g["year"], 2001)
        self.assertNotIn("|", g["title"])

    def test_parenthesized_key_still_parsed_when_winner_missing(self) -> None:
        """Non-regression : cle "Titre (AAAA)" + gagnant absent du plan -> parsing."""
        plan_rows: list = []  # winner introuvable
        decisions = [{"group_key": "Inception (2010)", "winner_row_id": "wX", "loser_row_ids": []}]
        decided = self._decided(plan_rows, decisions)
        self.assertEqual(decided[0]["title"], "Inception")
        self.assertEqual(decided[0]["year"], 2010)


class ReadableDuplicateGroupHelperTests(unittest.TestCase):
    """Unit test pur du helper de derivation titre/annee."""

    def test_winner_title_wins(self) -> None:
        from cinesort.ui.api.history_support import _readable_duplicate_group

        title, year = _readable_duplicate_group(
            "le seigneur des anneaux|2001",
            {"proposed_title": "Le Seigneur des Anneaux", "proposed_year": 2001},
        )
        self.assertEqual(title, "Le Seigneur des Anneaux")
        self.assertEqual(year, 2001)

    def test_pipe_fallback_strips_pipe(self) -> None:
        from cinesort.ui.api.history_support import _readable_duplicate_group

        # Gagnant absent -> parsing de la cle "titre|annee", jamais le "|" brut.
        title, year = _readable_duplicate_group("matrix reloaded|2003", {})
        self.assertNotIn("|", title)
        self.assertEqual(title, "matrix reloaded")
        self.assertEqual(year, 2003)

    def test_parenthesized_fallback(self) -> None:
        from cinesort.ui.api.history_support import _readable_duplicate_group

        title, year = _readable_duplicate_group("Dune (2021)", {})
        self.assertEqual(title, "Dune")
        self.assertEqual(year, 2021)


# ===========================================================================
# M1 : snapshot sante au scan ne fige aucune metrique dependante du probe
# ===========================================================================
class ScanHealthSnapshotTests(unittest.TestCase):
    def test_snapshot_metrics_all_none(self) -> None:
        """Au scan, aucune metrique du snapshot n'est fabriquee (probe absent)."""
        from cinesort.ui.api.run_flow_support import _build_scan_health_snapshot

        snap = _build_scan_health_snapshot()
        # AVANT le fix : health_score et subtitle_coverage_pct portaient des
        # valeurs calculees sur des donnees incompletes (quality_reports VIDE).
        self.assertIsNone(snap["health_score"])
        self.assertIsNone(snap["subtitle_coverage_pct"])
        self.assertIsNone(snap["resolution_4k_pct"])
        self.assertIsNone(snap["codec_modern_pct"])

    def test_no_empty_reports_health_call_in_source(self) -> None:
        """Regression : le scan ne doit plus appeler generate_suggestions avec [].

        Garde le call site : meme si quelqu'un re-inline une valeur, le pattern
        d'appel a liste de reports VIDE (cause racine de l'anti-pattern A) ne doit
        pas revenir.
        """
        src = _RUN_FLOW_PY.read_text(encoding="utf-8")
        self.assertNotIn("generate_suggestions(rows, [], settings)", src)
        self.assertIn("_build_scan_health_snapshot()", src)


if __name__ == "__main__":
    unittest.main()
