"""#762 — `disambiguate_by_context` boostait des candidats hors du groupe ambigu.

`detect_title_ambiguity` ne compte comme ambigus que les candidats de source
`tmdb` / `nfo_tmdb` / `nfo_imdb`. `disambiguate_by_context` appliquait pourtant
le boost contextuel a TOUT candidat au titre normalise egal, sans regarder la
source.

Pourquoi c'est un defaut et pas un simple ecart cosmetique : le signal « annee
exacte » (+0.10, le deuxieme plus fort) compare `context["name_year"]` a
l'annee du candidat. Pour un candidat de source `name` / `name_tag`, ces deux
valeurs sont extraites du MEME nom de fichier — le candidat se confirmait donc
lui-meme et empochait quasi systematiquement le boost maximal d'annee, dans un
arbitrage cense departager des identites TMDb entre elles.

Le correctif ne durcit aucune heuristique : il retire un boost, il n'en ajoute
aucun, et il fait partager le meme predicat de source aux deux moities pour
qu'elles ne puissent plus deriver.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional

from cinesort.domain.title_ambiguity import detect_title_ambiguity, disambiguate_by_context


@dataclass(frozen=True)
class _FakeCandidate:
    """Mini-candidate — mimique l'API de core.Candidate (cf. test_title_ambiguity)."""

    title: str
    year: Optional[int]
    source: str
    score: float
    tmdb_id: Optional[int] = None
    runtime_min: Optional[int] = None
    note: str = ""


# Sources reellement emises par le scan (core.build_candidates_from_* et
# plan_support_dedup) : 3 identites provider, 5 derivees du nom/NFO brut.
_PROVIDER_SOURCES = ("tmdb", "nfo_tmdb", "nfo_imdb")
_NON_PROVIDER_SOURCES = ("name", "nfo", "name_tag", "name_tmdb", "name_imdb")


def _ambiguous_tmdb_pair():
    return [
        _FakeCandidate(title="Dune", year=1984, source="tmdb", score=0.70, tmdb_id=841),
        _FakeCandidate(title="Dune", year=2021, source="tmdb", score=0.90, tmdb_id=438631),
    ]


class BoostScopeMatchesDetectionScopeTests(unittest.TestCase):
    def test_name_candidate_sharing_the_ambiguous_title_keeps_its_score(self) -> None:
        outsider = _FakeCandidate(title="Dune", year=1984, source="name", score=0.72)
        cands = [*_ambiguous_tmdb_pair(), outsider]

        out, ambiguous, key = disambiguate_by_context(cands, {"name_year": 1984})

        self.assertTrue(ambiguous)
        self.assertEqual(key, "dune")
        got = next(c for c in out if c.source == "name")
        self.assertAlmostEqual(got.score, 0.72, places=4, msg="le candidat 'name' ne doit pas etre booste")
        self.assertNotIn("disambig", got.note)

    def test_provider_members_are_still_arbitrated(self) -> None:
        """Non-regression : le coeur de la fonction reste intact."""
        out, _ambiguous, _key = disambiguate_by_context(_ambiguous_tmdb_pair(), {"name_year": 1984})
        c1984 = next(c for c in out if c.year == 1984)
        c2021 = next(c for c in out if c.year == 2021)
        self.assertAlmostEqual(c1984.score, 0.80, places=4)
        self.assertAlmostEqual(c2021.score, 0.90, places=4)
        self.assertIn("annee exacte", c1984.note)

    # tmdb_id dedie a la sonde : la paire ambigue porte 841 / 438631, donc
    # selectionner par `tmdb_id == _PROBE_ID` ne peut pas attraper un autre
    # candidat (piege : selectionner « celui dont le score a change » revient a
    # supposer la reponse).
    _PROBE_ID = 999

    def _probe_score(self, source: str) -> float:
        probe = _FakeCandidate(title="Dune", year=1984, source=source, score=0.50, tmdb_id=self._PROBE_ID)
        out, _ambiguous, _key = disambiguate_by_context(
            [*_ambiguous_tmdb_pair(), probe],
            {"name_year": 1984, "nfo_tmdb_id": self._PROBE_ID},
        )
        return next(c for c in out if c.tmdb_id == self._PROBE_ID).score

    def test_every_non_provider_source_is_left_untouched(self) -> None:
        for source in _NON_PROVIDER_SOURCES:
            with self.subTest(source=source):
                # Deux signaux contextuels seraient applicables (annee exacte
                # +0.10, nfo_tmdb_id exact +0.15) : aucun ne doit s'appliquer.
                self.assertAlmostEqual(self._probe_score(source), 0.50, places=4)

    def test_every_provider_source_is_boosted(self) -> None:
        for source in _PROVIDER_SOURCES:
            with self.subTest(source=source):
                self.assertAlmostEqual(self._probe_score(source), 0.75, places=4)

    def test_detection_and_boost_share_the_same_source_predicate(self) -> None:
        """Verrou de coherence : une source compte pour la detection SI ET
        SEULEMENT SI elle est eligible au boost. C'est cette equivalence qui
        avait derive."""
        for source in (*_PROVIDER_SOURCES, *_NON_PROVIDER_SOURCES):
            with self.subTest(source=source):
                counted_by_detection, _key = detect_title_ambiguity(
                    [
                        _FakeCandidate(title="Dune", year=1984, source=source, score=0.5, tmdb_id=841),
                        _FakeCandidate(title="Dune", year=2021, source=source, score=0.5, tmdb_id=438631),
                    ]
                )
                eligible_for_boost = self._probe_score(source) != 0.50
                self.assertEqual(
                    counted_by_detection,
                    eligible_for_boost,
                    f"perimetre desaccorde pour source={source!r}",
                )


if __name__ == "__main__":
    unittest.main()
