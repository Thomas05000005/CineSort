"""GATE AUDIT 2026-06-13 (R5-J) — la vue Doublons montre les groupes meme sans
validation prealable.

Bug constate (capture app reelle) : la vue Doublons affiche "0 groupe / Aucun
doublon detecte" alors que le badge/chip annoncent 65 doublons. Cause :
check_duplicates -> find_duplicate_targets ne groupe QUE les films APPROUVES
(dec.ok), or la vue appelle avec decisions={} hors workflow apply -> rien
approuve -> 0 groupe. Ce n'est PAS une confusion de racines.

Fix : quand aucun film n'est approuve, check_duplicates traite tous les films
comme candidats (navigateur de doublons). La securite pre-apply
(apply_support -> find_duplicate_targets direct avec vraies decisions) est
inchangee.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import run_flow_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done


class _Row:
    def __init__(self, row_id, title, year):
        self.row_id = row_id
        self.proposed_title = title
        self.proposed_year = year


class BrowseAllHelperTests(unittest.TestCase):
    """Unit du helper _browse_all_if_none_approved."""

    def test_marks_all_ok_when_none_approved(self) -> None:
        rows = [_Row("a", "Inception", 2010), _Row("b", "Inception", 2010)]
        safe = {"a": {"ok": False}, "b": {"ok": False}}
        out = run_flow_support._browse_all_if_none_approved(rows, safe)
        self.assertTrue(out["a"]["ok"])
        self.assertTrue(out["b"]["ok"])
        self.assertEqual(out["a"]["title"], "Inception")
        self.assertEqual(out["a"]["year"], 2010)

    def test_respects_decisions_when_some_approved(self) -> None:
        rows = [_Row("a", "Inception", 2010), _Row("b", "Inception", 2010)]
        safe = {"a": {"ok": True}, "b": {"ok": False}}
        out = run_flow_support._browse_all_if_none_approved(rows, safe)
        # Au moins un approuve -> on NE touche pas (workflow apply en cours).
        self.assertIs(out, safe)
        self.assertFalse(out["b"]["ok"])


class CheckDuplicatesBrowserTests(unittest.TestCase):
    """Integration : check_duplicates({}) montre les groupes."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_dupbrowse_")
        self.root = Path(self._tmp) / "root"
        self.sd = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.sd.mkdir(parents=True, exist_ok=True)
        # 2 versions du MEME film (meme titre+annee), 2 sous-dossiers distincts.
        (self.root / "Inception 1080p" / "Inception 2010.mkv").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "Inception 1080p" / "Inception 2010.mkv").write_bytes(b"x" * 4096)
        (self.root / "Inception 4k" / "Inception 2010.mkv").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "Inception 4k" / "Inception 2010.mkv").write_bytes(b"y" * 8192)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_check_duplicates_empty_decisions_finds_group(self) -> None:
        api = CineSortApi()
        st = api.run.start_plan({"root": str(self.root), "state_dir": str(self.sd), "tmdb_enabled": False})
        self.assertTrue(st.get("ok"), st)
        run_id = str(st["run_id"])
        _wait_done(api, run_id)

        # decisions={} comme la vue Doublons reelle.
        res = api.run.check_duplicates(run_id, {})
        self.assertTrue(res.get("ok"), res)
        groups = res.get("groups") or []
        self.assertGreaterEqual(
            len(groups),
            1,
            f"check_duplicates({{}}) doit montrer le groupe de doublons (vue navigateur). groups={groups}",
        )


if __name__ == "__main__":
    unittest.main()
