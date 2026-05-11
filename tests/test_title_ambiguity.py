"""P2.2 : tests pour title_ambiguity.

Couvre : normalisation titres, détection ambiguïté, désambiguïsation par
contexte (année, NFO tmdb_id, runtime).
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional

from cinesort.domain.title_ambiguity import (
    detect_title_ambiguity,
    disambiguate_by_context,
    normalize_title_for_ambiguity,
)


@dataclass(frozen=True)
class _FakeCandidate:
    """Mini-candidate pour tests — mimique l'API de core.Candidate."""

    title: str
    year: Optional[int]
    source: str
    score: float
    tmdb_id: Optional[int] = None
    runtime_min: Optional[int] = None
    note: str = ""


class NormalizeTitleTests(unittest.TestCase):
    def test_lowercase_and_strip_accents(self):
        self.assertEqual(normalize_title_for_ambiguity("L'Été"), "ete")

    def test_strips_punctuation(self):
        self.assertEqual(normalize_title_for_ambiguity("Dune: Part One!"), "dune part one")

    def test_removes_leading_articles(self):
        self.assertEqual(normalize_title_for_ambiguity("The Thing"), "thing")
        self.assertEqual(normalize_title_for_ambiguity("Le Petit Prince"), "petit prince")
        self.assertEqual(normalize_title_for_ambiguity("Les Misérables"), "miserables")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_title_for_ambiguity("Hello   world"), "hello world")

    def test_empty_input_returns_empty(self):
        self.assertEqual(normalize_title_for_ambiguity(""), "")
        self.assertEqual(normalize_title_for_ambiguity(None), "")  # type: ignore

    def test_same_title_different_punctuation_same_norm(self):
        a = normalize_title_for_ambiguity("Avatar: The Way of Water")
        b = normalize_title_for_ambiguity("Avatar - The Way of Water")
        self.assertEqual(a, b)


class DetectTitleAmbiguityTests(unittest.TestCase):
    def test_two_tmdb_same_title_detected(self):
        cands = [
            _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.7, tmdb_id=841),
            _FakeCandidate(title="Dune", year=2021, source="tmdb", score=0.9, tmdb_id=438631),
        ]
        ambig, key = detect_title_ambiguity(cands)
        self.assertTrue(ambig)
        self.assertEqual(key, "dune")

    def test_no_ambiguity_when_single_tmdb(self):
        cands = [_FakeCandidate(title="Inception", year=2010, source="tmdb", score=0.95, tmdb_id=27205)]
        ambig, key = detect_title_ambiguity(cands)
        self.assertFalse(ambig)
        self.assertIsNone(key)

    def test_name_candidate_ignored_for_ambiguity(self):
        # Le candidat "name" ne doit pas contribuer à la détection d'ambiguïté.
        cands = [
            _FakeCandidate(title="Dune", year=2021, source="name", score=0.6),
            _FakeCandidate(title="Dune", year=2021, source="tmdb", score=0.9, tmdb_id=438631),
        ]
        ambig, _ = detect_title_ambiguity(cands)
        self.assertFalse(ambig)

    def test_different_titles_not_ambiguous(self):
        cands = [
            _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.7, tmdb_id=841),
            _FakeCandidate(title="Inception", year=2010, source="tmdb", score=0.95, tmdb_id=27205),
        ]
        ambig, _ = detect_title_ambiguity(cands)
        self.assertFalse(ambig)

    def test_nfo_tmdb_counts_toward_ambiguity(self):
        # nfo_tmdb candidate est un candidat TMDb valide (via NFO tmdbid)
        cands = [
            _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.7, tmdb_id=841),
            _FakeCandidate(title="Dune", year=2021, source="nfo_tmdb", score=0.93, tmdb_id=438631),
        ]
        ambig, _ = detect_title_ambiguity(cands)
        self.assertTrue(ambig)


class DisambiguateByContextTests(unittest.TestCase):
    def _dune_pair(self):
        return [
            _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.70, tmdb_id=841, note=""),
            _FakeCandidate(title="Dune", year=2021, source="tmdb", score=0.90, tmdb_id=438631, note=""),
        ]

    def test_name_year_promotes_matching_candidate(self):
        cands = self._dune_pair()
        ctx = {"name_year": 1984}
        out, ambig, key = disambiguate_by_context(cands, ctx)
        self.assertTrue(ambig)
        self.assertEqual(key, "dune")
        # Le candidat 1984 doit avoir son score boosté de 0.10
        c1984 = next(c for c in out if c.year == 1984)
        c2021 = next(c for c in out if c.year == 2021)
        self.assertAlmostEqual(c1984.score, 0.80, places=2)
        self.assertAlmostEqual(c2021.score, 0.90, places=2)  # inchangé
        self.assertIn("annee exacte", c1984.note)

    def test_name_year_pm1_gives_smaller_boost(self):
        cands = self._dune_pair()
        ctx = {"name_year": 1985}  # ±1 du 1984
        out, _, _ = disambiguate_by_context(cands, ctx)
        c1984 = next(c for c in out if c.year == 1984)
        self.assertAlmostEqual(c1984.score, 0.75, places=2)  # +0.05

    def test_nfo_tmdb_id_strong_boost(self):
        cands = self._dune_pair()
        ctx = {"nfo_tmdb_id": 841}  # pointe le 1984
        out, _, _ = disambiguate_by_context(cands, ctx)
        c1984 = next(c for c in out if c.year == 1984)
        self.assertAlmostEqual(c1984.score, 0.85, places=2)  # +0.15

    def test_combined_signals_stack(self):
        cands = self._dune_pair()
        ctx = {"name_year": 1984, "nfo_tmdb_id": 841}
        out, _, _ = disambiguate_by_context(cands, ctx)
        c1984 = next(c for c in out if c.year == 1984)
        # 0.70 + 0.10 (année exacte) + 0.15 (nfo_tmdb_id) = 0.95
        self.assertAlmostEqual(c1984.score, 0.95, places=2)

    def test_no_ambiguity_no_modification(self):
        cands = [_FakeCandidate(title="Inception", year=2010, source="tmdb", score=0.95, tmdb_id=27205)]
        ctx = {"name_year": 2010}
        out, ambig, _ = disambiguate_by_context(cands, ctx)
        self.assertFalse(ambig)
        # Score inchangé car pas d'ambiguïté
        self.assertEqual(out[0].score, 0.95)

    def test_context_empty_no_boost(self):
        cands = self._dune_pair()
        out, ambig, _ = disambiguate_by_context(cands, {})
        self.assertTrue(ambig)  # Ambiguïté toujours détectée
        # Aucun boost car pas de signal contextuel
        for orig, new in zip(cands, out):
            self.assertEqual(orig.score, new.score)

    def test_runtime_match_gives_small_boost(self):
        cands = [
            _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.70, tmdb_id=841, runtime_min=137),
            _FakeCandidate(title="Dune", year=2021, source="tmdb", score=0.90, tmdb_id=438631, runtime_min=155),
        ]
        ctx = {"nfo_runtime": 140}  # proche du 1984 (137)
        out, _, _ = disambiguate_by_context(cands, ctx)
        c1984 = next(c for c in out if c.year == 1984)
        self.assertAlmostEqual(c1984.score, 0.73, places=2)  # +0.03

    def test_note_augmented_with_disambig_reason(self):
        cands = self._dune_pair()
        ctx = {"name_year": 1984}
        out, _, _ = disambiguate_by_context(cands, ctx)
        c1984 = next(c for c in out if c.year == 1984)
        self.assertIn("disambig:", c1984.note)

    def test_non_ambiguous_group_not_boosted_by_context(self):
        # 2 candidats ambigus + 1 non ambigu → seul le groupe ambigu est modifié
        cands = [
            _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.70, tmdb_id=841),
            _FakeCandidate(title="Dune", year=2021, source="tmdb", score=0.90, tmdb_id=438631),
            _FakeCandidate(title="Avatar", year=1984, source="tmdb", score=0.60, tmdb_id=999),
        ]
        ctx = {"name_year": 1984}
        out, _, _ = disambiguate_by_context(cands, ctx)
        # Dune 1984 boosté
        c_dune = next(c for c in out if c.title == "Dune" and c.year == 1984)
        self.assertGreater(c_dune.score, 0.70)
        # Avatar (pas dans le groupe ambigu "dune") non modifié
        c_avatar = next(c for c in out if c.title == "Avatar")
        self.assertEqual(c_avatar.score, 0.60)


if __name__ == "__main__":
    unittest.main()
