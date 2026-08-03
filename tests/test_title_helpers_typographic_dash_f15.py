"""F15 - _expand_tmdb_queries doit splitter sur les tirets typographiques.

Les 2e/3e separateurs du tuple etaient un mojibake (" ? " ASCII 0x3F) de
l'en-dash U+2013 et de l'em-dash U+2014 : du code mort qui privait
"Mission Impossible <en-dash> Fallout" de sa query de repli avant tiret.

Ce fichier est volontairement en ASCII PUR (chr(0x2013) et pas un litteral) :
c'est une perte d'encodage qui a produit le bug d'origine, un test ecrit en
litteraux typographiques pourrait subir exactement le meme accident et
deviendrait alors vert pour de mauvaises raisons.
"""

from __future__ import annotations

import unittest

from cinesort.domain.title_helpers import _expand_tmdb_queries

EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)


class ExpandTmdbQueriesDashTests(unittest.TestCase):
    def test_en_dash_generates_prefix_query(self):
        self.assertIn(
            "Mission Impossible",
            _expand_tmdb_queries(["Mission Impossible " + EN_DASH + " Fallout"]),
        )

    def test_em_dash_generates_prefix_query(self):
        self.assertIn(
            "Mission Impossible",
            _expand_tmdb_queries(["Mission Impossible " + EM_DASH + " Fallout"]),
        )

    def test_point_interrogation_ne_sert_plus_de_separateur(self):
        """Garde anti-reapparition du mojibake, mesuree sur le COMPORTEMENT.

        L'ancienne version de ce test lisait `inspect.getsource(...)` et
        comparait des chaines de code source. Trois defauts, releves en revue
        adversaire : il n'exercait aucun chemin de production ; son `isascii()`
        contraignait jusqu'aux COMMENTAIRES de la fonction ; et il restait vert
        avec un tuple casse comme (" - ", "en-dash", "em-dash") sans espaces
        autour, qui splitterait a l'interieur des mots.

        On mesure donc ce qui compte : le mojibake ' ? ' ne doit pas etre un
        separateur, et les vrais tirets typographiques doivent en etre.
        """
        # Un titre contenant " ? " ne doit PAS produire de query tronquee.
        self.assertEqual(
            _expand_tmdb_queries(["Qui suis-je ? Le retour"]),
            ["Qui suis-je ? Le retour"],
            "' ? ' n'est pas un separateur de titre : aucune query de repli ne doit en sortir",
        )
        # Les tirets typographiques, eux, en sont bien.
        for tiret in (EN_DASH, EM_DASH):
            self.assertIn(
                "Mission Impossible",
                _expand_tmdb_queries(["Mission Impossible " + tiret + " Fallout"]),
                f"le tiret U+{ord(tiret):04X} doit produire la query de repli",
            )

    def test_separateurs_exigent_des_espaces_autour(self):
        """Un tiret typographique COLLE ne doit pas couper a l'interieur d'un mot.

        C'est le trou que l'ancien test de source laissait passer : un tuple
        sans espaces autour des tirets serait resté vert.
        """
        colle = "Spider" + EN_DASH + "Man"
        self.assertEqual(
            _expand_tmdb_queries([colle]),
            [colle],
            "un tiret colle fait partie du mot : il ne doit produire aucune query de repli",
        )


class ExpandTmdbQueriesNonRegressionTests(unittest.TestCase):
    """Doit rester VERT des deux cotes de la mutation."""

    def test_ascii_dash_unchanged(self):
        self.assertEqual(
            _expand_tmdb_queries(["Mission Impossible - Fallout"]),
            ["Mission Impossible - Fallout", "Mission Impossible"],
        )

    def test_colon_split_unchanged(self):
        self.assertIn("Blade Runner", _expand_tmdb_queries(["Blade Runner: 2049"]))

    def test_plain_title_not_split(self):
        self.assertEqual(_expand_tmdb_queries(["Inception"]), ["Inception"])


if __name__ == "__main__":
    unittest.main()
