"""Tests phase 4 doublons backend (spec docs/internal/design/refonte_2026_05_17/screens/01-doublons.md).

Couvre les 3 endpoints crees + l'enrichissement size_savings_total :
- check_duplicates : presence de size_savings_total dans la reponse.
- queue_perceptual_analyses + get_perceptual_job_status : queue + polling.
- mark_duplicate_winner : persistance DB + payload retour conforme.
- get_perceptual_compare_audio : mock ffmpeg + base64 retourne.
"""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import perceptual_support, run_flow_support
from cinesort.ui.api.cinesort_api import CineSortApi


def _write_settings(state_dir: Path, **fields: Any) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "settings.json").write_text(json.dumps(fields), encoding="utf-8")


# =============================================================================
# 1. mark_duplicate_winner : persistance DB
# =============================================================================


class MarkDuplicateWinnerDbTests(unittest.TestCase):
    """La decision est correctement persistee dans la table duplicate_decisions."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_dup_winner_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_table_duplicate_decisions_exists_after_init(self) -> None:
        """La migration 023 cree la table duplicate_decisions."""
        with self.store._managed_conn() as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='duplicate_decisions'"
            )
            self.assertIsNotNone(cur.fetchone())

    def test_upsert_persists_winner_and_losers(self) -> None:
        result = self.store.apply.upsert_duplicate_decision(
            run_id="run1",
            group_key="fast_furious_4|2009",
            winner_row_id="rowA",
            loser_row_ids=["rowB", "rowC"],
        )
        self.assertEqual(result["winner_row_id"], "rowA")
        self.assertEqual(result["loser_row_ids"], ["rowB", "rowC"])

        read = self.store.apply.get_duplicate_decision(
            run_id="run1", group_key="fast_furious_4|2009"
        )
        assert read is not None
        self.assertEqual(read["winner_row_id"], "rowA")
        self.assertEqual(set(read["loser_row_ids"]), {"rowB", "rowC"})

    def test_upsert_overrides_previous_decision(self) -> None:
        """Conflict sur (run_id, group_key) -> update plutot que doublon."""
        self.store.apply.upsert_duplicate_decision(
            run_id="run1",
            group_key="g1",
            winner_row_id="rowA",
            loser_row_ids=["rowB"],
        )
        self.store.apply.upsert_duplicate_decision(
            run_id="run1",
            group_key="g1",
            winner_row_id="rowB",  # change d'avis
            loser_row_ids=["rowA"],
        )
        read = self.store.apply.get_duplicate_decision(run_id="run1", group_key="g1")
        assert read is not None
        self.assertEqual(read["winner_row_id"], "rowB")
        self.assertEqual(read["loser_row_ids"], ["rowA"])

    def test_list_returns_all_decisions_for_run(self) -> None:
        self.store.apply.upsert_duplicate_decision(
            run_id="run1", group_key="g1", winner_row_id="a", loser_row_ids=["b"]
        )
        self.store.apply.upsert_duplicate_decision(
            run_id="run1", group_key="g2", winner_row_id="c", loser_row_ids=["d"]
        )
        self.store.apply.upsert_duplicate_decision(
            run_id="run2", group_key="g3", winner_row_id="e", loser_row_ids=["f"]
        )
        rows = self.store.apply.list_duplicate_decisions(run_id="run1")
        self.assertEqual(len(rows), 2)
        keys = {r["group_key"] for r in rows}
        self.assertEqual(keys, {"g1", "g2"})

    def test_get_returns_none_for_unknown_decision(self) -> None:
        self.assertIsNone(
            self.store.apply.get_duplicate_decision(run_id="ghost", group_key="x")
        )


class MarkDuplicateWinnerEndpointTests(unittest.TestCase):
    """L'endpoint run_flow_support.mark_duplicate_winner valide les inputs et persiste."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_dup_endpoint_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()

        # Mock minimal API : _find_run_row renvoie (run_row, store).
        self.api = mock.MagicMock()
        self.api._find_run_row.return_value = ({"run_id": "run1"}, self.store)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_run_id_returns_validation_error(self) -> None:
        r = run_flow_support.mark_duplicate_winner(self.api, "", "g1", "rowA")
        self.assertFalse(r["ok"])

    def test_empty_group_key_returns_validation_error(self) -> None:
        r = run_flow_support.mark_duplicate_winner(self.api, "run1", "", "rowA")
        self.assertFalse(r["ok"])

    def test_empty_winner_returns_validation_error(self) -> None:
        r = run_flow_support.mark_duplicate_winner(self.api, "run1", "g1", "")
        self.assertFalse(r["ok"])

    def test_unknown_run_returns_resource_error(self) -> None:
        self.api._find_run_row.return_value = None
        r = run_flow_support.mark_duplicate_winner(self.api, "ghost", "g1", "rowA")
        self.assertFalse(r["ok"])

    def test_persists_winner_and_returns_payload(self) -> None:
        # check_duplicates est mock pour eviter de charger un plan complet.
        with mock.patch.object(
            run_flow_support,
            "check_duplicates",
            return_value={
                "ok": True,
                "groups": [
                    {
                        "group_key": "g1",
                        "rows": [{"row_id": "rowA"}, {"row_id": "rowB"}, {"row_id": "rowC"}],
                    }
                ],
            },
        ):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "g1", "rowA")

        self.assertTrue(r["ok"], msg=str(r))
        self.assertEqual(r["group_key"], "g1")
        self.assertEqual(r["winner_row_id"], "rowA")
        self.assertEqual(set(r["losers"]), {"rowB", "rowC"})

        # Persistance verifiee directement en DB.
        read = self.store.apply.get_duplicate_decision(run_id="run1", group_key="g1")
        assert read is not None
        self.assertEqual(read["winner_row_id"], "rowA")
        self.assertEqual(set(read["loser_row_ids"]), {"rowB", "rowC"})


# =============================================================================
# 2. check_duplicates : size_savings_total
# =============================================================================


class CheckDuplicatesSizeSavingsTests(unittest.TestCase):
    """Le payload de check_duplicates expose size_savings_total agrege."""

    def test_compute_size_savings_total_sums_groups(self) -> None:
        data: Dict[str, Any] = {
            "groups": [
                {"comparison": {"size_savings": 1_000_000_000}},
                {"comparison": {"size_savings": 2_500_000_000}},
                {"comparison": {"size_savings": 0}},
            ]
        }
        total = run_flow_support._compute_size_savings_total(data)
        self.assertEqual(total, 3_500_000_000)

    def test_compute_size_savings_total_tolerates_missing_comparison(self) -> None:
        data = {
            "groups": [
                {"comparison": {"size_savings": 500}},
                {},  # groupe sans comparison (probes indisponibles)
                {"comparison": {}},  # comparison sans size_savings
                {"comparison": {"size_savings": "abc"}},  # valeur invalide -> ignoree
            ]
        }
        self.assertEqual(run_flow_support._compute_size_savings_total(data), 500)

    def test_compute_size_savings_total_empty(self) -> None:
        self.assertEqual(run_flow_support._compute_size_savings_total({"groups": []}), 0)
        self.assertEqual(run_flow_support._compute_size_savings_total({}), 0)

    def test_check_duplicates_response_includes_size_savings_total(self) -> None:
        """Integration : check_duplicates renvoie bien size_savings_total dans le dict."""
        api = mock.MagicMock()
        api._find_run_row.return_value = ({"run_id": "run1"}, mock.MagicMock())

        # rs (RuntimeRun snapshot) avec rows et done=True pour passer la garde.
        rs = mock.MagicMock()
        rs.done = True
        rs.rows = [mock.MagicMock()]
        rs.cfg = mock.MagicMock()
        rs.store = mock.MagicMock()
        api._get_run.return_value = rs

        api._normalize_decisions_for_rows.return_value = {}

        with mock.patch.object(
            run_flow_support,
            "_find_dups",
            return_value={
                "groups": [
                    {"comparison": {"size_savings": 12_345}},
                    {"comparison": {"size_savings": 67_890}},
                ]
            },
        ):
            with mock.patch.object(
                run_flow_support, "_enrich_groups_with_quality_comparison"
            ):
                r = run_flow_support.check_duplicates(api, "run1", {})

        self.assertTrue(r["ok"], msg=str(r))
        self.assertIn("size_savings_total", r)
        self.assertEqual(r["size_savings_total"], 80_235)


# =============================================================================
# 3. queue_perceptual_analyses : JobRunner queue + polling
# =============================================================================


class QueuePerceptualAnalysesTests(unittest.TestCase):
    """La queue accepte des paires, retourne un job_id, expose le statut via polling."""

    def setUp(self) -> None:
        # Nettoyage du registry global entre tests (singleton process-wide).
        with perceptual_support._PERCEPTUAL_JOBS_LOCK:
            perceptual_support._PERCEPTUAL_JOBS.clear()
        self.api = mock.MagicMock()

    def test_empty_pairs_returns_validation_error(self) -> None:
        r = perceptual_support.queue_perceptual_analyses(self.api, [])
        self.assertFalse(r["ok"])

    def test_pairs_missing_fields_are_filtered_out(self) -> None:
        r = perceptual_support.queue_perceptual_analyses(
            self.api,
            [{"run_id": "r1", "row_a": "a"}],  # row_b manquant
        )
        self.assertFalse(r["ok"])

    def test_queue_returns_job_id_and_total(self) -> None:
        """Queue OK : job_id retourne + total = N paires."""
        # On stubs compare_perceptual pour retourner OK instantanement.
        with mock.patch.object(
            perceptual_support,
            "compare_perceptual",
            return_value={"ok": True, "comparison": {}},
        ):
            r = perceptual_support.queue_perceptual_analyses(
                self.api,
                [
                    {"run_id": "r1", "row_a": "a", "row_b": "b"},
                    {"run_id": "r1", "row_a": "c", "row_b": "d"},
                ],
            )
        self.assertTrue(r["ok"], msg=str(r))
        self.assertEqual(r["total"], 2)
        self.assertTrue(r["job_id"].startswith("perceptual_batch_"))

    def test_polling_eventually_marks_job_done(self) -> None:
        """Apres execution complete, le status passe a 'done' + results renseignes."""
        with mock.patch.object(
            perceptual_support,
            "compare_perceptual",
            return_value={"ok": True, "comparison": {}},
        ):
            r = perceptual_support.queue_perceptual_analyses(
                self.api,
                [{"run_id": "r1", "row_a": "a", "row_b": "b"}],
            )
        job_id = r["job_id"]

        # Polling avec un timeout court (le worker est immediat car compare est mocke).
        deadline = time.time() + 5.0
        status = None
        while time.time() < deadline:
            status = perceptual_support.get_perceptual_job_status(self.api, job_id)
            if status.get("status") == "done":
                break
            time.sleep(0.05)

        assert status is not None
        self.assertEqual(status.get("status"), "done")
        self.assertEqual(status.get("total"), 1)
        self.assertEqual(status.get("done"), 1)

    def test_unknown_job_id_returns_error(self) -> None:
        r = perceptual_support.get_perceptual_job_status(self.api, "ghost")
        self.assertFalse(r["ok"])

    def test_facade_exposes_queue_and_status(self) -> None:
        """La facade quality expose bien les nouvelles methodes."""
        api = CineSortApi()
        self.assertTrue(hasattr(api.quality, "queue_perceptual_analyses"))
        self.assertTrue(hasattr(api.quality, "get_perceptual_job_status"))


# =============================================================================
# 4. get_perceptual_compare_audio : mock ffmpeg
# =============================================================================


class CompareAudioTests(unittest.TestCase):
    """L'extraction audio+waveform repose sur ffmpeg : on mock subprocess.run."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_compare_audio_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_requires_run_id_and_row_ids(self) -> None:
        r = self.api.quality.get_perceptual_compare_audio("", "a", "b")
        self.assertFalse(r["ok"])

    def test_perceptual_disabled_returns_error(self) -> None:
        _write_settings(self._tmp, perceptual_enabled=False)
        r = self.api.quality.get_perceptual_compare_audio("run1", "a", "b")
        self.assertFalse(r["ok"])

    def test_no_ffmpeg_returns_missing_tool(self) -> None:
        _write_settings(self._tmp, perceptual_enabled=True, ffprobe_path="")
        with mock.patch(
            "cinesort.ui.api.perceptual_support.resolve_ffmpeg_path",
            return_value="",
        ):
            r = self.api.quality.get_perceptual_compare_audio("run1", "a", "b")
        self.assertFalse(r["ok"])
        self.assertEqual(r.get("missing_tool"), "ffmpeg")

    def test_returns_base64_when_ffmpeg_succeeds(self) -> None:
        """Mock complet ffmpeg : retourne PNG + MP3 base64 valides."""
        _write_settings(self._tmp, perceptual_enabled=True, ffprobe_path="/fake/ffprobe")

        row_a = mock.MagicMock(row_id="a")
        row_b = mock.MagicMock(row_id="b")
        run_row = {"state_dir": str(self._tmp)}
        store = mock.MagicMock()
        cfg = mock.MagicMock()
        rs = mock.MagicMock(rows=[row_a, row_b], cfg=cfg)

        # Faux bytes pour PNG + MP3.
        fake_png = b"\x89PNG\r\n\x1a\nfake_png_payload"
        fake_mp3 = b"\xff\xfb\x90\x00fake_mp3_payload"

        fake_proc_png = mock.MagicMock(returncode=0, stdout=fake_png, stderr=b"")
        fake_proc_mp3 = mock.MagicMock(returncode=0, stdout=fake_mp3, stderr=b"")

        # subprocess.run est appele 4 fois : 2 waveforms puis 2 clips MP3.
        # On retourne alternativement PNG / MP3 selon l'ordre d'appel (waveform_a,
        # waveform_b, audio_a, audio_b dans cet ordre).
        run_side_effects: List[Any] = [
            fake_proc_png,
            fake_proc_png,
            fake_proc_mp3,
            fake_proc_mp3,
        ]

        patches = [
            mock.patch.object(self.api, "_find_run_row", return_value=(run_row, store)),
            mock.patch.object(self.api, "_get_run", return_value=rs),
            mock.patch.object(self.api, "_run_paths_for", return_value=mock.MagicMock()),
            mock.patch.object(
                self.api, "_load_rows_from_plan_jsonl", return_value=[row_a, row_b]
            ),
            mock.patch.object(
                self.api,
                "_resolve_media_path_for_row",
                side_effect=[Path("/m/a.mkv"), Path("/m/b.mkv")],
            ),
            mock.patch(
                "cinesort.ui.api.perceptual_support.resolve_ffmpeg_path",
                return_value="/fake/ffmpeg",
            ),
            mock.patch(
                "cinesort.ui.api.perceptual_support._load_probe",
                return_value={"normalized": {"duration_s": 100.0}},
            ),
            mock.patch("subprocess.run", side_effect=run_side_effects),
        ]
        for p in patches:
            p.start()
        for p in patches:
            self.addCleanup(p.stop)

        r = self.api.quality.get_perceptual_compare_audio("run1", "a", "b")
        self.assertTrue(r["ok"], msg=str(r))
        self.assertEqual(r["audio_mime"], "audio/mpeg")

        # Verifie que le decode base64 redonne bien les bytes attendus.
        self.assertEqual(base64.b64decode(r["waveform_a_b64"]), fake_png)
        self.assertEqual(base64.b64decode(r["waveform_b_b64"]), fake_png)
        self.assertEqual(base64.b64decode(r["audio_a_b64"]), fake_mp3)
        self.assertEqual(base64.b64decode(r["audio_b_b64"]), fake_mp3)

        self.assertGreaterEqual(r["duration_s"], 5)
        self.assertLessEqual(r["duration_s"], 30)

    def test_ffmpeg_failure_returns_empty_string_not_crash(self) -> None:
        """Si ffmpeg echoue, on retourne base64 vide plutot que crasher."""
        # Helper de bas niveau pris directement.
        out = perceptual_support._extract_audio_waveform_b64(
            "ffmpeg_does_not_exist_xyz", "/no/file.mkv", 0.0, 10, 400, 80
        )
        self.assertEqual(out, "")


class FacadeWiringTests(unittest.TestCase):
    """Sanity check : les 3 endpoints sont accessibles via les facades."""

    def test_facade_quality_has_compare_audio(self) -> None:
        api = CineSortApi()
        self.assertTrue(hasattr(api.quality, "get_perceptual_compare_audio"))

    def test_facade_quality_has_queue_perceptual_analyses(self) -> None:
        api = CineSortApi()
        self.assertTrue(hasattr(api.quality, "queue_perceptual_analyses"))

    def test_facade_run_has_mark_duplicate_winner(self) -> None:
        api = CineSortApi()
        self.assertTrue(hasattr(api.run, "mark_duplicate_winner"))


if __name__ == "__main__":
    unittest.main()
