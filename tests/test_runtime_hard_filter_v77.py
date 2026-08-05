"""Tests VN-D.3 — runtime HARD filter pour TMDb candidates.

Couvre :
- evaluate_runtime_hard_filter : politique pure (excluded vs kept-via-edition)
- _apply_runtime_hard_filter_to_tmdb_cands : integration avec TmdbClient mock
- Cas Dune 1984 vs Dune 2021 (faux match historique L05/L01)
- Edge cases : probe FAILED (file_runtime None), threshold custom, enabled=False,
  candidat sans tmdb_id, runtime TMDb None, edition flag detecte.
"""

from __future__ import annotations

import unittest
from typing import List, Optional
from unittest.mock import MagicMock

from cinesort.domain.runtime_hard_filter import (
    DEFAULT_RUNTIME_HARD_THRESHOLD_MIN,
    WARN_RUNTIME_HARD_EXCLUDED,
    WARN_RUNTIME_HARD_KEPT_VIA_EDITION,
    evaluate_runtime_hard_filter,
)


class FakeCandidate:
    """Minimal stand-in pour cinesort.domain.core.Candidate (evite l'import lourd)."""

    def __init__(
        self,
        title: str,
        year: Optional[int],
        tmdb_id: Optional[int],
        note: str = "",
    ) -> None:
        self.title = title
        self.year = year
        self.source = "tmdb"
        self.tmdb_id = tmdb_id
        self.poster_url = None
        self.score = 0.5
        self.note = note


# ---------------------------------------------------------------------------
# evaluate_runtime_hard_filter : politique pure
# ---------------------------------------------------------------------------


class EvaluateRuntimeHardFilterTests(unittest.TestCase):
    # --- Cas nominal : Dune 1984 vs file Dune 2021 (155 min) ---

    def test_dune_1984_137min_vs_file_dune_2021_155min_kept(self):
        # delta = 18 min < 60 -> conserve (pas de modification, scoring soft prendra le relais)
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=155.0,
            candidate_runtime_min=137,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    # --- Cas court metrage Dune 1984 vs file 90 min ---

    def test_dune_1984_137min_vs_file_90min_kept_warn_under_threshold(self):
        # delta = 47 min < 60 -> conserve (zone delta moyen, mais pas exclu par HARD)
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=90.0,
            candidate_runtime_min=137,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    # --- Cas franc mismatch sans edition ---

    def test_movie_120min_vs_file_180min_no_edition_excluded(self):
        # delta = 60 min, AU SEUIL exact -> conserve (politique "strict greater than")
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=180.0,
            candidate_runtime_min=120,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_movie_120min_vs_file_181min_no_edition_excluded(self):
        # delta = 61 min > 60 -> EXCLU
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=181.0,
            candidate_runtime_min=120,
            edition_label=None,
        )
        self.assertTrue(excluded)
        self.assertIsNone(warn)

    # --- Cas conserve grace a edition flag ---

    def test_movie_120min_vs_file_200min_extended_kept_with_warning(self):
        # delta = 80 min > 60 mais edition "Extended" detecte -> conserve + warning
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=200.0,
            candidate_runtime_min=120,
            edition_label="Extended",
        )
        self.assertFalse(excluded)
        self.assertEqual(warn, WARN_RUNTIME_HARD_KEPT_VIA_EDITION)

    def test_directors_cut_kept_with_warning(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=210.0,
            candidate_runtime_min=120,
            edition_label="Director's Cut",
        )
        self.assertFalse(excluded)
        self.assertEqual(warn, WARN_RUNTIME_HARD_KEPT_VIA_EDITION)

    def test_ultimate_cut_kept_with_warning(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=240.0,
            candidate_runtime_min=148,
            edition_label="Ultimate Cut",
        )
        self.assertFalse(excluded)
        self.assertEqual(warn, WARN_RUNTIME_HARD_KEPT_VIA_EDITION)

    def test_extended_edition_kept_with_warning(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=250.0,
            candidate_runtime_min=148,
            edition_label="Extended Edition",
        )
        self.assertFalse(excluded)
        self.assertEqual(warn, WARN_RUNTIME_HARD_KEPT_VIA_EDITION)

    # --- IMAX / Theatrical : pas dans la whitelist "edition longue" ---

    def test_imax_not_extended_excluded_at_high_delta(self):
        # IMAX n'est PAS dans _EXTENDED_EDITIONS -> traite comme pas d'edition
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=200.0,
            candidate_runtime_min=120,
            edition_label="IMAX",
        )
        self.assertTrue(excluded)
        self.assertIsNone(warn)

    def test_theatrical_not_extended_excluded_at_high_delta(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=200.0,
            candidate_runtime_min=120,
            edition_label="Theatrical Cut",
        )
        self.assertTrue(excluded)
        self.assertIsNone(warn)

    # --- Configuration : enabled / threshold ---

    def test_disabled_filter_never_excludes(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=300.0,
            candidate_runtime_min=120,
            edition_label=None,
            enabled=False,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_custom_threshold_strict_30min(self):
        # Threshold abaisse a 30 min -> delta 35 = EXCLU
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=120.0,
            candidate_runtime_min=85,
            edition_label=None,
            threshold_min=30,
        )
        self.assertTrue(excluded)
        self.assertIsNone(warn)

    def test_custom_threshold_loose_120min(self):
        # Threshold a 120 min -> delta 80 = conserve
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=200.0,
            candidate_runtime_min=120,
            edition_label=None,
            threshold_min=120,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_zero_threshold_disables_filter(self):
        # threshold <= 0 -> filtre off
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=300.0,
            candidate_runtime_min=120,
            edition_label=None,
            threshold_min=0,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    # --- Cas no-op : donnees manquantes ---

    def test_none_file_runtime_returns_kept_probe_failed(self):
        # Probe FAILED -> filtre desactive pour cette ligne (conserve)
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=None,
            candidate_runtime_min=120,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_none_candidate_runtime_returns_kept(self):
        # TMDb sans runtime -> conserve (on ne peut pas trancher)
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=180.0,
            candidate_runtime_min=None,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_zero_runtime_returns_kept(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=0.0,
            candidate_runtime_min=120,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min=180.0,
            candidate_runtime_min=0,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_invalid_runtime_types_return_kept(self):
        excluded, warn = evaluate_runtime_hard_filter(
            file_runtime_min="bad",  # type: ignore[arg-type]
            candidate_runtime_min=120,
            edition_label=None,
        )
        self.assertFalse(excluded)
        self.assertIsNone(warn)

    def test_default_threshold_is_60(self):
        self.assertEqual(DEFAULT_RUNTIME_HARD_THRESHOLD_MIN, 60)


# ---------------------------------------------------------------------------
# _apply_runtime_hard_filter_to_tmdb_cands : integration plan_support
# ---------------------------------------------------------------------------


class ApplyRuntimeHardFilterToTmdbCandsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Lazy import : evite de charger plan_support au module-load (DB sqlite,
        # tmdb client, etc.). Patternaligne sur tests/test_runtime_probe_check.py.
        from cinesort.app.plan_support import _apply_runtime_hard_filter_to_tmdb_cands

        self.apply = _apply_runtime_hard_filter_to_tmdb_cands
        self.logs: List[tuple] = []

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _make_tmdb(self, runtimes: dict) -> MagicMock:
        """Construit un mock TmdbClient avec un mapping tmdb_id -> runtime."""

        def _get_runtime(tmdb_id):
            return runtimes.get(int(tmdb_id))

        client = MagicMock()
        client.get_movie_runtime = MagicMock(side_effect=_get_runtime)
        return client

    # --- Cas L05/L01 : Dune 1984 vs file Dune 2021 (155 min) ---

    def test_dune_1984_kept_when_delta_under_60(self):
        # File = Dune 2021 (155 min). Candidat Dune 1984 (137 min) : delta 18 -> KEEP
        cands = [FakeCandidate("Dune", 1984, tmdb_id=841)]
        tmdb = self._make_tmdb({841: 137})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=155.0,
            detected_edition=None,
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": True},
            log=self._log,
            log_ctx="Dune (single)",
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)

    def test_dune_1984_kept_when_file_short_47min_delta(self):
        # File 90 min : delta 47 < 60 -> KEEP (warning soft hors HARD filter)
        cands = [FakeCandidate("Dune", 1984, tmdb_id=841)]
        tmdb = self._make_tmdb({841: 137})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=90.0,
            detected_edition=None,
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": True},
            log=self._log,
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)

    def test_movie_120min_excluded_when_file_180min_no_edition(self):
        # delta = 60 min : AU SEUIL exact -> conserve. delta 61 -> EXCLU
        cands = [FakeCandidate("ShortFilm", 1990, tmdb_id=42)]
        tmdb = self._make_tmdb({42: 120})

        # File 181 -> delta 61 > 60 -> EXCLU
        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=181.0,
            detected_edition=None,
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": True},
            log=self._log,
            log_ctx="ShortFilm",
        )
        self.assertEqual(kept, [])
        self.assertTrue(excluded_any)
        # Verify log mentions the exclusion
        info_logs = [m for lvl, m in self.logs if lvl == "INFO"]
        self.assertTrue(any("exclu" in m and "tmdb_id=42" in m for m in info_logs))

    def test_movie_120min_kept_with_extended_edition_when_file_200min(self):
        # delta = 80 min, edition "Extended" -> conserve + warning
        cands = [FakeCandidate("Avatar", 2009, tmdb_id=19995)]
        tmdb = self._make_tmdb({19995: 120})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=200.0,
            detected_edition="Extended",
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": True},
            log=self._log,
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)
        # warning ajoute dans note du candidat
        self.assertIn(WARN_RUNTIME_HARD_KEPT_VIA_EDITION, kept[0].note)
        # log WARN emis
        warn_logs = [m for lvl, m in self.logs if lvl == "WARN"]
        self.assertTrue(any("Extended" in m for m in warn_logs))

    # --- Mix : un candidat exclu, un autre conserve ---

    def test_mix_excludes_only_offenders(self):
        cands = [
            FakeCandidate("Dune", 1984, tmdb_id=841),
            FakeCandidate("Dune", 2021, tmdb_id=438631),
        ]
        # File 155 min (Dune 2021)
        tmdb = self._make_tmdb({841: 137, 438631: 155})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=155.0,
            detected_edition=None,
            tmdb=tmdb,
            settings=None,
            log=self._log,
        )
        # Les deux sont sous seuil -> tous conserves
        self.assertEqual(len(kept), 2)
        self.assertFalse(excluded_any)

    def test_mix_with_one_exclusion(self):
        # Faux match : "Dune" 1984 (137 min) face a un film de 250 min reels.
        # Et un vrai match "Dune" 2021 (155 min) -- non pertinent ici, mais test mixte.
        cands = [
            FakeCandidate("Dune", 1984, tmdb_id=841),
            FakeCandidate("Dune Long Edition", 2021, tmdb_id=99999),
        ]
        tmdb = self._make_tmdb({841: 137, 99999: 240})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=240.0,
            detected_edition=None,
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": True, "runtime_hard_threshold_min": 60},
            log=self._log,
        )
        # 841 (137 min) doit etre EXCLU vs file 240 (delta 103) ; 99999 (240) match parfait -> kept
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].tmdb_id, 99999)
        self.assertTrue(excluded_any)

    # --- Edge : probe FAILED ---

    def test_probe_failed_disables_filter(self):
        cands = [FakeCandidate("Anything", 2000, tmdb_id=1)]
        tmdb = self._make_tmdb({1: 90})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=None,  # probe FAILED
            detected_edition=None,
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": True},
            log=self._log,
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)
        # On ne doit pas avoir appele TMDb pour le runtime non plus
        tmdb.get_movie_runtime.assert_not_called()

    def test_tmdb_runtime_unknown_keeps_candidate(self):
        cands = [FakeCandidate("Mystery", 2000, tmdb_id=1)]
        tmdb = self._make_tmdb({})  # tous None

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=180.0,
            detected_edition=None,
            tmdb=tmdb,
            settings=None,
            log=self._log,
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)

    def test_candidate_without_tmdb_id_is_kept(self):
        cands = [FakeCandidate("Local NFO", 2000, tmdb_id=None)]
        tmdb = self._make_tmdb({})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=180.0,
            detected_edition=None,
            tmdb=tmdb,
            settings=None,
            log=self._log,
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)
        tmdb.get_movie_runtime.assert_not_called()

    # --- Rollback config ---

    def test_settings_disabled_returns_all_kept(self):
        cands = [FakeCandidate("ShortFilm", 1990, tmdb_id=42)]
        tmdb = self._make_tmdb({42: 90})

        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=300.0,  # delta 210, normalement EXCLU
            detected_edition=None,
            tmdb=tmdb,
            settings={"runtime_hard_filter_enabled": False},
            log=self._log,
        )
        self.assertEqual(len(kept), 1)
        self.assertFalse(excluded_any)
        # TMDb runtime ne doit meme pas etre interroge quand le filtre est off
        tmdb.get_movie_runtime.assert_not_called()

    def test_custom_threshold_via_settings(self):
        cands = [FakeCandidate("ShortFilm", 1990, tmdb_id=42)]
        tmdb = self._make_tmdb({42: 90})

        # Seuil 30 min, delta = 35 -> EXCLU
        kept, excluded_any = self.apply(
            cands,
            file_runtime_min=125.0,
            detected_edition=None,
            tmdb=tmdb,
            settings={
                "runtime_hard_filter_enabled": True,
                "runtime_hard_threshold_min": 30,
            },
            log=self._log,
        )
        self.assertEqual(kept, [])
        self.assertTrue(excluded_any)

    def test_warning_constant_value(self):
        # Sanity : la constante exportee correspond bien a la string attendue
        self.assertEqual(WARN_RUNTIME_HARD_EXCLUDED, "runtime_hard_filter_excluded_candidate")
        self.assertEqual(WARN_RUNTIME_HARD_KEPT_VIA_EDITION, "runtime_hard_kept_via_edition_flag")


if __name__ == "__main__":
    unittest.main()
