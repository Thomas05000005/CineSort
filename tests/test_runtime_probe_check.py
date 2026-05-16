"""Tests Phase 6.1.b — probe runtime cross-check post-plan."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

from cinesort.app.runtime_probe_check import (
    _get_chosen_tmdb_id,
    cross_check_rows_with_probe,
)


@dataclass
class _FakeCandidate:
    title: str
    year: Optional[int]
    tmdb_id: Optional[int]


@dataclass
class _FakeRow:
    """Stub PlanRow pour tests (champs accédés par cross_check_rows_with_probe)."""

    proposed_title: str
    proposed_year: int
    confidence: int
    folder: str
    video: str
    candidates: List[_FakeCandidate] = field(default_factory=list)
    nfo_runtime: Optional[int] = None
    edition: Optional[str] = None
    warning_flags: List[str] = field(default_factory=list)


class GetChosenTmdbIdTests(unittest.TestCase):
    def test_exact_match_title_year(self):
        row = _FakeRow(
            "Inception",
            2010,
            75,
            "",
            "",
            candidates=[
                _FakeCandidate("Other", 2010, 999),
                _FakeCandidate("Inception", 2010, 27205),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 27205)

    def test_fallback_to_first_with_tmdb_id(self):
        # Pas de match exact mais candidate avec tmdb_id existe
        row = _FakeRow(
            "Inception (Director's Cut)",
            2010,
            75,
            "",
            "",
            candidates=[
                _FakeCandidate("Inception", 2010, 27205),
            ],
        )
        # Pas de match exact mais fallback prend le 1er avec tmdb_id
        self.assertEqual(_get_chosen_tmdb_id(row), 27205)

    def test_no_candidates(self):
        row = _FakeRow("X", 2020, 75, "", "", candidates=[])
        self.assertIsNone(_get_chosen_tmdb_id(row))

    def test_candidate_without_tmdb(self):
        row = _FakeRow(
            "X",
            2020,
            75,
            "",
            "",
            candidates=[_FakeCandidate("X", 2020, None)],
        )
        self.assertIsNone(_get_chosen_tmdb_id(row))


class CrossCheckRowsWithProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="probe_test_")
        # Cree un fichier video factice
        self.video_path = Path(self.tmp_dir) / "Inception.mkv"
        self.video_path.write_bytes(b"\x00" * 1024)

        self.mock_store = MagicMock()
        self.mock_tmdb = MagicMock()
        self.settings = {"probe_backend": "auto"}

    def _make_row(self, **overrides) -> _FakeRow:
        defaults = {
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "confidence": 70,
            "folder": self.tmp_dir,
            "video": "Inception.mkv",
            "candidates": [_FakeCandidate("Inception", 2010, 27205)],
            "nfo_runtime": None,
            "edition": None,
            "warning_flags": [],
        }
        defaults.update(overrides)
        return _FakeRow(**defaults)

    @patch("cinesort.infra.probe.ProbeService")
    def test_full_match_adds_bonus_20(self, MockProbe):
        # ProbeService retourne duration_s = 8880 (148 min) = match parfait avec TMDb 148
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 148 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 148

        rows = [self._make_row(confidence=70)]
        n = cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(n, 1)
        self.assertEqual(rows[0].confidence, 90)  # 70 + 20

    @patch("cinesort.infra.probe.ProbeService")
    def test_mismatch_adds_penalty_and_warning(self, MockProbe):
        # Film 90 min, TMDb dit 140 min → mismatch
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 90 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 140

        rows = [self._make_row(confidence=70)]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(rows[0].confidence, 45)  # 70 - 25
        self.assertIn("runtime_mismatch_likely_wrong_film", rows[0].warning_flags)

    @patch("cinesort.infra.probe.ProbeService")
    def test_skip_if_nfo_runtime_present(self, MockProbe):
        # Phase 6.1 in-line a deja traite cette row via nfo_runtime
        rows = [self._make_row(confidence=70, nfo_runtime=148)]
        n = cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(n, 0)  # skip
        # ProbeService instancie mais probe_file pas appele
        MockProbe.return_value.probe_file.assert_not_called()

    @patch("cinesort.infra.probe.ProbeService")
    def test_skip_if_already_very_confident(self, MockProbe):
        rows = [self._make_row(confidence=98)]
        n = cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(n, 0)

    @patch("cinesort.infra.probe.ProbeService")
    def test_no_tmdb_id_skipped(self, MockProbe):
        # Aucun candidate avec tmdb_id
        rows = [self._make_row(candidates=[_FakeCandidate("X", 2010, None)])]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.mock_tmdb.get_movie_runtime.assert_not_called()

    @patch("cinesort.infra.probe.ProbeService")
    def test_no_video_file_skipped(self, MockProbe):
        rows = [self._make_row(video="nonexistent.mkv")]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.mock_tmdb.get_movie_runtime.assert_not_called()

    @patch("cinesort.infra.probe.ProbeService")
    def test_tmdb_runtime_none_skipped(self, MockProbe):
        self.mock_tmdb.get_movie_runtime.return_value = None
        rows = [self._make_row()]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        MockProbe.return_value.probe_file.assert_not_called()

    @patch("cinesort.infra.probe.ProbeService")
    def test_probe_returns_no_duration_no_change(self, MockProbe):
        instance = MockProbe.return_value
        instance.probe_file.return_value = {"ok": True, "normalized": {"duration_s": 0}}
        self.mock_tmdb.get_movie_runtime.return_value = 148
        rows = [self._make_row(confidence=70)]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(rows[0].confidence, 70)  # unchanged

    @patch("cinesort.infra.probe.ProbeService")
    def test_probe_failure_no_change(self, MockProbe):
        instance = MockProbe.return_value
        instance.probe_file.side_effect = OSError("probe failed")
        self.mock_tmdb.get_movie_runtime.return_value = 148
        rows = [self._make_row(confidence=70)]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(rows[0].confidence, 70)  # unchanged

    @patch("cinesort.infra.probe.ProbeService")
    def test_should_cancel_stops_early(self, MockProbe):
        instance = MockProbe.return_value
        instance.probe_file.return_value = {"ok": True, "normalized": {"duration_s": 148 * 60}}
        self.mock_tmdb.get_movie_runtime.return_value = 148

        # Cree 2 fichiers videos
        v2 = Path(self.tmp_dir) / "Other.mkv"
        v2.write_bytes(b"\x00" * 1024)
        rows = [
            self._make_row(confidence=70),
            self._make_row(confidence=70, video="Other.mkv"),
        ]
        call_count = [0]

        def cancel_after_one():
            call_count[0] += 1
            return call_count[0] > 1

        cross_check_rows_with_probe(
            rows, self.mock_store, self.settings, self.mock_tmdb, should_cancel=cancel_after_one
        )
        # 1er traite, 2eme skip
        self.assertEqual(rows[0].confidence, 90)
        self.assertEqual(rows[1].confidence, 70)

    @patch("cinesort.infra.probe.ProbeService")
    def test_edition_aware_tolerance(self, MockProbe):
        # Extended Edition + delta 12 min → +10 (vs +0 sans edition)
        instance = MockProbe.return_value
        instance.probe_file.return_value = {"ok": True, "normalized": {"duration_s": 160 * 60}}
        self.mock_tmdb.get_movie_runtime.return_value = 148

        rows = [self._make_row(confidence=70, edition="Extended Edition")]
        cross_check_rows_with_probe(rows, self.mock_store, self.settings, self.mock_tmdb)
        # Sans edition : delta 12 = zone grise, +0
        # Avec edition : delta 12 < 15 tolerance → +10
        self.assertEqual(rows[0].confidence, 80)

    def test_empty_rows_returns_zero(self):
        n = cross_check_rows_with_probe([], self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(n, 0)

    def test_no_store_returns_zero(self):
        rows = [self._make_row()]
        n = cross_check_rows_with_probe(rows, None, self.settings, self.mock_tmdb)
        self.assertEqual(n, 0)

    def test_no_tmdb_returns_zero(self):
        rows = [self._make_row()]
        n = cross_check_rows_with_probe(rows, self.mock_store, self.settings, None)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
