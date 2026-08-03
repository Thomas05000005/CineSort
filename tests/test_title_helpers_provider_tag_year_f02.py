"""F02 — les chiffres d'un tag provider ne doivent jamais devenir une annee.

Deux volets solidaires dans cinesort/domain/title_helpers.py :
  (1) YEAR_RE borne par des lookarounds sur CHIFFRES -> "tt1950186" ne livre
      plus 1950, "19995" ne livre plus 1999 ;
  (2) infer_name_year strippe les tags providers en entree -> un id provider
      de 4 chiffres exactement ({tmdb-2019}) est neutralise lui aussi.
Chaque volet a son test dedie : aucun des deux ne couvre le cas de l'autre.
"""

from __future__ import annotations

import unittest

from cinesort.domain.core import build_candidates_from_name
from cinesort.domain.title_helpers import extract_all_years, extract_year, infer_name_year


class ProviderTagYearTests(unittest.TestCase):
    def test_imdb_tag_digits_not_taken_as_year(self):
        self.assertIsNone(infer_name_year("Ford v Ferrari [imdbid-tt1950186]", "Ford v Ferrari.mkv")[0])

    def test_tmdb_tag_digits_not_taken_as_year(self):
        self.assertIsNone(infer_name_year("Avatar {tmdb-19995}", "Avatar.mkv")[0])

    def test_real_year_wins_over_tag_digits(self):
        # Aggravant du finding : "Extended" declenche la regle remaster min(),
        # qui elisait la VRAIE annee (2019) au profit du faux 1950 du tag.
        self.assertEqual(
            infer_name_year("Ford v Ferrari [imdbid-tt1950186]", "Ford.v.Ferrari.2019.Extended.mkv")[0],
            2019,
        )

    def test_no_name_candidate_with_fake_year(self):
        folder, video = "Ford v Ferrari [imdbid-tt1950186]", "Ford v Ferrari.mkv"
        year = infer_name_year(folder, video)[0]
        cands = build_candidates_from_name(folder, video, preferred_year=year)
        self.assertNotIn(1950, [c.year for c in cands])

    # --- couverture volet par volet -------------------------------------

    def test_volet1_year_re_ignores_digit_neighbours(self):
        """Seul le bornage de YEAR_RE couvre un tag NON reconnu par le stripper."""
        self.assertEqual(extract_all_years("tt1950186"), [])
        self.assertIsNone(extract_year("19995"))
        self.assertIsNone(infer_name_year("Ford v Ferrari [id-1950186]", "Ford v Ferrari.mkv")[0])

    def test_volet2_strip_tags_covers_four_digit_id(self):
        """Seul le strip des tags couvre un id provider long de 4 chiffres."""
        self.assertIsNone(infer_name_year("Avatar {tmdb-2019}", "Avatar.mkv")[0])


class ProviderTagYearNonRegressionTests(unittest.TestCase):
    """Doit rester VERT des deux cotes de la mutation."""

    def test_parenthesized_year_still_detected(self):
        self.assertEqual(infer_name_year("Inception (2010)", "Inception.2010.1080p.mkv")[0], 2010)

    def test_year_title_film_still_detected(self):
        self.assertEqual(infer_name_year("Blade Runner 2049", "Blade.Runner.2049.2017.mkv")[0], 2017)

    def test_extract_year_last_wins(self):
        self.assertEqual(extract_year("Wonder Woman 1984 2020"), 2020)

    def test_year_glued_to_title_still_detected(self):
        """Garde anti-`\\b` : "Avatar2009" doit garder son annee."""
        self.assertEqual(infer_name_year("Avatar2009", "Avatar2009.mkv")[0], 2009)


if __name__ == "__main__":
    unittest.main()
