"""H5 — la duree MESUREE par le probe fait autorite sur la duree DECLAREE par le NFO.

Scenario central : le NFO annonce 95 min (un autre cut), mais le fichier reel
ET TMDb valent 142 min.

- AVANT le fix : phase 6.1 in-line pose un `runtime_mismatch_likely_wrong_film`
  (delta 95 vs 142 = 47 >= 30) et la phase 6.1.b probe SKIPPE la row (nfo_runtime
  present) -> le flag bloquant reste. En parallele, `_resolve_file_runtime_min`
  privilegie le NFO -> le filtre HARD raisonne sur une duree declaree fausse.
- APRES le fix : `_resolve_file_runtime_min` lit le cache probe d'abord, et
  `cross_check_rows_with_probe` reconcilie le flag (le retire) quand le fichier
  reel colle a TMDb.

Contrainte produit : la duree ne sert qu'au SCORING/MATCHING (choix candidat,
flags), jamais au nom du fichier video (seeding torrent). Ces tests ne touchent
qu'a de la confidence / des warning_flags.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

from cinesort.app.runtime_probe_check import cross_check_rows_with_probe
from cinesort.domain.runtime_matching import WARN_RUNTIME_MISMATCH

# ---------------------------------------------------------------------------
# Finding 1 : _resolve_file_runtime_min lit le cache probe AVANT le NFO
# ---------------------------------------------------------------------------


class _FakeNfo:
    def __init__(self, runtime: Optional[int]) -> None:
        self.runtime = runtime


class _FakeProbeStore:
    """Store minimal exposant get_probe_cache (comme SQLiteStore)."""

    def __init__(self, duration_s: Optional[float]) -> None:
        self._duration_s = duration_s
        self.calls: List[str] = []

    def get_probe_cache(self, media_path: str) -> Optional[dict]:
        self.calls.append(media_path)
        if self._duration_s is None:
            return None
        return {"normalized": {"duration_s": self._duration_s}}


class ResolveFileRuntimeMinProbeFirstTests(unittest.TestCase):
    def setUp(self) -> None:
        from cinesort.app.plan_support import _resolve_file_runtime_min

        self.resolve = _resolve_file_runtime_min
        self.tmp_dir = tempfile.mkdtemp(prefix="h5_resolve_")
        self.video = Path(self.tmp_dir) / "Movie.mkv"
        self.video.write_bytes(b"\x00" * 1024)

    def test_probe_cache_wins_over_nfo(self) -> None:
        # NFO declare 95 min (autre cut), probe a MESURE 142 min sur le fichier reel.
        nfo = _FakeNfo(runtime=95)
        store = _FakeProbeStore(duration_s=142 * 60)

        result = self.resolve(nfo, Path(self.tmp_dir), self.video, store=store, settings={})

        # AVANT le fix : retournait 95.0 (NFO d'abord). APRES : 142.0 (probe mesure).
        # La source remontee doit etre "measured" (autorite du probe).
        self.assertEqual(result, (142.0, "measured"))
        self.assertEqual(len(store.calls), 1)

    def test_falls_back_to_nfo_when_probe_cache_miss(self) -> None:
        # Pas de cache probe -> repli sur la duree declaree du NFO, source "declared".
        nfo = _FakeNfo(runtime=95)
        store = _FakeProbeStore(duration_s=None)

        result = self.resolve(nfo, Path(self.tmp_dir), self.video, store=store, settings={})
        self.assertEqual(result, (95.0, "declared"))

    def test_no_store_uses_nfo(self) -> None:
        # Cas scan-time reel (store non fourni) : comportement inchange = NFO declare.
        nfo = _FakeNfo(runtime=95)
        result = self.resolve(nfo, Path(self.tmp_dir), self.video)
        self.assertEqual(result, (95.0, "declared"))

    def test_no_data_returns_none(self) -> None:
        store = _FakeProbeStore(duration_s=None)
        result = self.resolve(None, Path(self.tmp_dir), self.video, store=store)
        self.assertEqual(result, (None, None))


# ---------------------------------------------------------------------------
# Finding 2 : cross_check_rows_with_probe reconcilie le faux runtime_mismatch
# ---------------------------------------------------------------------------


@dataclass
class _FakeCandidate:
    title: str
    year: Optional[int]
    tmdb_id: Optional[int]


@dataclass
class _FakeRow:
    proposed_title: str
    proposed_year: int
    confidence: int
    folder: str
    video: str
    candidates: List[_FakeCandidate] = field(default_factory=list)
    nfo_runtime: Optional[int] = None
    edition: Optional[str] = None
    warning_flags: List[str] = field(default_factory=list)
    confidence_label: str = ""


class ProbeReconcilesNfoMismatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="h5_probe_")
        self.video_path = Path(self.tmp_dir) / "Movie.mkv"
        self.video_path.write_bytes(b"\x00" * 1024)
        self.mock_store = MagicMock()
        self.mock_tmdb = MagicMock()
        self.settings = {"probe_backend": "auto"}

    def _make_row(self, **overrides: Any) -> _FakeRow:
        defaults = {
            "proposed_title": "Movie",
            "proposed_year": 2000,
            "confidence": 70,
            "folder": self.tmp_dir,
            "video": "Movie.mkv",
            "candidates": [_FakeCandidate("Movie", 2000, 27205)],
            "nfo_runtime": None,
            "edition": None,
            "warning_flags": [],
            "confidence_label": "med",
        }
        defaults.update(overrides)
        return _FakeRow(**defaults)

    @patch("cinesort.infra.probe.ProbeService")
    def test_false_mismatch_is_reconciled(self, MockProbe: MagicMock) -> None:
        # NFO = 95 (autre cut) -> phase 6.1 avait pose le flag et -25 (70 -> 45).
        # Fichier reel MESURE = 142 = TMDb -> faux positif a reconcilier.
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 142 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 142

        row = self._make_row(
            confidence=45,
            nfo_runtime=95,
            warning_flags=[WARN_RUNTIME_MISMATCH],
        )
        n = cross_check_rows_with_probe([row], self.mock_store, self.settings, self.mock_tmdb)

        # AVANT le fix : row skippee (nfo_runtime present) -> n=0, flag reste, confidence 45.
        self.assertEqual(n, 1)
        self.assertNotIn(WARN_RUNTIME_MISMATCH, row.warning_flags)
        # -25 annule (+25) puis +20 match parfait : 45 + 25 + 20 = 90.
        self.assertEqual(row.confidence, 90)

    @patch("cinesort.infra.probe.ProbeService")
    def test_reconcile_recomputes_confidence_label(self, MockProbe: MagicMock) -> None:
        # Defaut 2 : la reconciliation restaure row.confidence (45 -> 90) mais AVANT
        # le fix laissait confidence_label="low" -> badge "low" faux + review count gonfle.
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 142 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 142

        row = self._make_row(
            confidence=45,
            confidence_label="low",  # pose par phase 6.1 sur la foi du faux mismatch
            nfo_runtime=95,
            warning_flags=[WARN_RUNTIME_MISMATCH],
        )
        cross_check_rows_with_probe([row], self.mock_store, self.settings, self.mock_tmdb)

        # Confidence remonte a 90 -> le label doit devenir "high", pas rester "low".
        self.assertEqual(row.confidence, 90)
        self.assertEqual(row.confidence_label, "high")

    @patch("cinesort.infra.probe.ProbeService")
    def test_nfo_row_without_flag_still_skipped(self, MockProbe: MagicMock) -> None:
        # NFO correct (pas de flag) -> pas de reconciliation, pas de double bonus.
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 142 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 142

        row = self._make_row(confidence=90, nfo_runtime=142, warning_flags=[])
        n = cross_check_rows_with_probe([row], self.mock_store, self.settings, self.mock_tmdb)

        self.assertEqual(n, 0)
        MockProbe.return_value.probe_file.assert_not_called()
        self.assertEqual(row.confidence, 90)  # pas de +20 en double

    @patch("cinesort.infra.probe.ProbeService")
    def test_probe_confirms_real_mismatch_keeps_flag(self, MockProbe: MagicMock) -> None:
        # NFO = 95 ET fichier reel MESURE = 95 (TMDb 142) -> vrai mismatch : on garde le flag.
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 95 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 142

        row = self._make_row(
            confidence=45,
            nfo_runtime=95,
            warning_flags=[WARN_RUNTIME_MISMATCH],
        )
        cross_check_rows_with_probe([row], self.mock_store, self.settings, self.mock_tmdb)

        self.assertIn(WARN_RUNTIME_MISMATCH, row.warning_flags)
        self.assertEqual(row.confidence, 45)  # pas de double penalite

    @patch("cinesort.infra.probe.ProbeService")
    def test_reconcile_does_not_touch_video_name(self, MockProbe: MagicMock) -> None:
        # Contrainte produit : le fix ne renomme jamais le fichier video.
        instance = MockProbe.return_value
        instance.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": 142 * 60},
        }
        self.mock_tmdb.get_movie_runtime.return_value = 142

        row = self._make_row(
            confidence=45,
            nfo_runtime=95,
            warning_flags=[WARN_RUNTIME_MISMATCH],
        )
        before = row.video
        cross_check_rows_with_probe([row], self.mock_store, self.settings, self.mock_tmdb)
        self.assertEqual(row.video, before)


# ---------------------------------------------------------------------------
# Defaut 1 : une duree DECLAREE (NFO) ne doit JAMAIS provoquer d'exclusion dure
# ---------------------------------------------------------------------------


class DeclaredRuntimeNeverHardExcludesTests(unittest.TestCase):
    """La politique pure evaluate_runtime_hard_filter distingue mesure vs declare."""

    def test_declared_runtime_keeps_candidate_with_warning(self) -> None:
        from cinesort.domain.runtime_hard_filter import (
            WARN_RUNTIME_HARD_KEPT_DECLARED,
            evaluate_runtime_hard_filter,
        )

        # NFO declare 95 min ; TMDb 142 min ; delta 47 > seuil 30 ; pas d'edition.
        # Source DECLAREE -> conserve + warning (le probe reconciliera).
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=95.0,
            candidate_runtime_min=142,
            edition_label=None,
            threshold_min=30,
            runtime_measured=False,
        )
        self.assertFalse(excluded)
        self.assertEqual(warn, WARN_RUNTIME_HARD_KEPT_DECLARED)

    def test_measured_runtime_still_excludes(self) -> None:
        from cinesort.domain.runtime_hard_filter import evaluate_runtime_hard_filter

        # Meme delta mais source MESUREE (probe) -> la mesure fait autorite -> EXCLU.
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=95.0,
            candidate_runtime_min=142,
            edition_label=None,
            threshold_min=30,
            runtime_measured=True,
        )
        self.assertTrue(excluded)
        self.assertIsNone(warn)

    def test_measured_is_the_default(self) -> None:
        # Retro-compat : sans runtime_measured, comportement historique = mesure.
        from cinesort.domain.runtime_hard_filter import evaluate_runtime_hard_filter

        excluded, _warn = evaluate_runtime_hard_filter(
            file_runtime_min=95.0,
            candidate_runtime_min=142,
            edition_label=None,
            threshold_min=30,
        )
        self.assertTrue(excluded)


class ApplyDeclaredSourceKeepsCandidateTests(unittest.TestCase):
    """Integration _apply_runtime_hard_filter_to_tmdb_cands avec runtime_source."""

    def setUp(self) -> None:
        from cinesort.app.plan_support import _apply_runtime_hard_filter_to_tmdb_cands

        self.apply = _apply_runtime_hard_filter_to_tmdb_cands
        self.logs: List[tuple] = []

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _tmdb(self, runtime: int) -> MagicMock:
        client = MagicMock()
        client.get_movie_runtime = MagicMock(return_value=runtime)
        return client

    def test_declared_source_keeps_candidate(self) -> None:
        from cinesort.domain.runtime_hard_filter import WARN_RUNTIME_HARD_KEPT_DECLARED

        cand = _FakeCandidate("Movie Extended", 2000, tmdb_id=27205)
        cand.note = ""
        cand.title = "Movie Extended"
        kept, excluded_any = self.apply(
            [cand],
            file_runtime_min=95.0,  # NFO declare
            detected_edition=None,
            tmdb=self._tmdb(142),
            settings={"runtime_hard_filter_enabled": True, "runtime_hard_threshold_min": 30},
            log=self._log,
            runtime_source="declared",
        )
        # AVANT le fix : le candidat 142 min etait EXCLU sur une duree declaree fausse.
        # APRES : conserve + warning, le probe tranchera plus tard.
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)
        self.assertIn(WARN_RUNTIME_HARD_KEPT_DECLARED, kept[0].note)

    def test_measured_source_still_excludes(self) -> None:
        cand = _FakeCandidate("Movie", 2000, tmdb_id=27205)
        cand.note = ""
        cand.title = "Movie"
        kept, excluded_any = self.apply(
            [cand],
            file_runtime_min=95.0,  # duree MESUREE par le probe
            detected_edition=None,
            tmdb=self._tmdb(142),
            settings={"runtime_hard_filter_enabled": True, "runtime_hard_threshold_min": 30},
            log=self._log,
            runtime_source="measured",
        )
        self.assertEqual(kept, [])
        self.assertTrue(excluded_any)


if __name__ == "__main__":
    unittest.main()
