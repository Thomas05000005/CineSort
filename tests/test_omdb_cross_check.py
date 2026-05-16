"""Tests Phase 6.2 OMDb cross-check post-plan."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock

from cinesort.app.omdb_cross_check import (
    WARN_OMDB_DISAGREE,
    _compute_adjustment,
    _normalize_title_for_compare,
    cross_check_rows_with_omdb,
)
from cinesort.infra.omdb_client import OmdbResult


@dataclass
class _FakeRow:
    """Stub PlanRow pour les tests (juste les champs accédés par cross_check)."""

    proposed_title: str
    proposed_year: int
    confidence: int
    warning_flags: List[str] = field(default_factory=list)


def _make_omdb_result(title: str, year: Optional[int]) -> OmdbResult:
    return OmdbResult(
        imdb_id="tt0000000",
        title=title,
        year=year,
        runtime_min=120,
        genre="",
        imdb_rating=None,
        imdb_votes=None,
        awards="",
        plot="",
    )


class NormalizeTitleTests(unittest.TestCase):
    def test_lowercase_strip_punct(self):
        self.assertEqual(_normalize_title_for_compare("Le Capitaine: Fracasse!"), "lecapitainefracasse")

    def test_accents_stripped(self):
        self.assertEqual(_normalize_title_for_compare("Amélie"), "amelie")

    def test_empty(self):
        self.assertEqual(_normalize_title_for_compare(""), "")

    def test_special_chars(self):
        self.assertEqual(_normalize_title_for_compare("Spider-Man 2"), "spiderman2")


class ComputeAdjustmentTests(unittest.TestCase):
    def test_full_convergence(self):
        omdb = _make_omdb_result("Inception", 2010)
        bonus, warn = _compute_adjustment("Inception", 2010, omdb)
        self.assertEqual(bonus, 20)
        self.assertIsNone(warn)

    def test_full_convergence_with_punct_diff(self):
        # "Spider-Man 2" vs "Spider-Man 2:" → normalises identiques → +20
        omdb = _make_omdb_result("Spider-Man 2:", 2004)
        bonus, warn = _compute_adjustment("Spider-Man 2", 2004, omdb)
        self.assertEqual(bonus, 20)

    def test_partial_year_match_title_diff(self):
        # OMDb a le titre original, TMDb a le titre traduit
        omdb = _make_omdb_result("The Holy Mountain", 1973)
        bonus, warn = _compute_adjustment("La Montagne sacree", 1973, omdb)
        self.assertEqual(bonus, 5)
        self.assertIsNone(warn)

    def test_partial_title_match_year_diff_1(self):
        # Meme titre, delta annee ±1 (remaster ou release date difference)
        omdb = _make_omdb_result("Inception", 2011)
        bonus, warn = _compute_adjustment("Inception", 2010, omdb)
        self.assertEqual(bonus, 5)
        self.assertIsNone(warn)

    def test_divergence_franc(self):
        # Le Ruffian (1982, 90min) vs OMDb "Magnificent Ruffians" (1979, 140min)
        omdb = _make_omdb_result("The Magnificent Ruffians", 1979)
        bonus, warn = _compute_adjustment("Le Ruffian", 1982, omdb)
        self.assertEqual(bonus, -25)
        self.assertEqual(warn, WARN_OMDB_DISAGREE)

    def test_no_omdb_year_is_noop(self):
        omdb = _make_omdb_result("Inception", None)
        bonus, warn = _compute_adjustment("Inception", 2010, omdb)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_no_chosen_year_is_noop(self):
        omdb = _make_omdb_result("Inception", 2010)
        bonus, warn = _compute_adjustment("Inception", None, omdb)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)


class CrossCheckRowsTests(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()

    def test_skip_high_confidence_rows(self):
        rows = [
            _FakeRow("Inception", 2010, 95),  # >= seuil 90 → skip
            _FakeRow("Inception", 2010, 75),  # < seuil → call OMDb
        ]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Inception", 2010)
        n = cross_check_rows_with_omdb(rows, self.mock_client, min_confidence_for_call=90)
        self.assertEqual(n, 1)
        # Premier row inchange
        self.assertEqual(rows[0].confidence, 95)
        # Deuxieme row boosted +20
        self.assertEqual(rows[1].confidence, 95)

    def test_convergence_adds_bonus(self):
        rows = [_FakeRow("Inception", 2010, 70)]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Inception", 2010)
        cross_check_rows_with_omdb(rows, self.mock_client)
        self.assertEqual(rows[0].confidence, 90)  # 70 + 20

    def test_divergence_adds_warning_and_penalty(self):
        rows = [_FakeRow("Le Ruffian", 1982, 75)]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Magnificent Ruffians", 1979)
        cross_check_rows_with_omdb(rows, self.mock_client)
        self.assertEqual(rows[0].confidence, 50)  # 75 - 25
        self.assertIn(WARN_OMDB_DISAGREE, rows[0].warning_flags)

    def test_no_omdb_response_is_noop(self):
        rows = [_FakeRow("Unknown Film", 2020, 70)]
        self.mock_client.search_by_title.return_value = None
        cross_check_rows_with_omdb(rows, self.mock_client)
        self.assertEqual(rows[0].confidence, 70)  # inchange
        self.assertEqual(rows[0].warning_flags, [])

    def test_confidence_clamped_to_100(self):
        rows = [_FakeRow("Inception", 2010, 85)]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Inception", 2010)
        cross_check_rows_with_omdb(rows, self.mock_client)
        # 85 + 20 = 105 -> clamp 100
        self.assertEqual(rows[0].confidence, 100)

    def test_confidence_clamped_to_0(self):
        rows = [_FakeRow("X", 2020, 10)]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Y", 1990)
        cross_check_rows_with_omdb(rows, self.mock_client)
        # 10 - 25 = -15 -> clamp 0
        self.assertEqual(rows[0].confidence, 0)

    def test_no_title_or_year_skipped(self):
        rows = [
            _FakeRow("", 2010, 50),  # no title
            _FakeRow("X", 0, 50),  # no year
        ]
        n = cross_check_rows_with_omdb(rows, self.mock_client)
        self.assertEqual(n, 0)
        self.mock_client.search_by_title.assert_not_called()

    def test_should_cancel_stops_early(self):
        rows = [
            _FakeRow("Inception", 2010, 70),
            _FakeRow("Other", 2015, 70),
        ]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Inception", 2010)
        call_count = [0]

        def cancel_after_one():
            call_count[0] += 1
            return call_count[0] > 1

        cross_check_rows_with_omdb(rows, self.mock_client, should_cancel=cancel_after_one)
        # Seul le 1er row a ete traite
        self.assertEqual(rows[0].confidence, 90)
        self.assertEqual(rows[1].confidence, 70)  # inchange

    def test_omdb_exception_is_swallowed(self):
        rows = [_FakeRow("Inception", 2010, 70)]
        self.mock_client.search_by_title.side_effect = ValueError("network error")
        cross_check_rows_with_omdb(rows, self.mock_client)
        # Row inchange, pas de crash
        self.assertEqual(rows[0].confidence, 70)

    def test_warning_not_duplicated(self):
        rows = [_FakeRow("X", 2020, 50, warning_flags=[WARN_OMDB_DISAGREE])]
        self.mock_client.search_by_title.return_value = _make_omdb_result("Y", 1990)
        cross_check_rows_with_omdb(rows, self.mock_client)
        # Le warning n'est pas ajoute en double
        self.assertEqual(rows[0].warning_flags.count(WARN_OMDB_DISAGREE), 1)

    def test_empty_rows_returns_zero(self):
        n = cross_check_rows_with_omdb([], self.mock_client)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
