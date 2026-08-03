"""F14 - le tiret d'un template de nommage doit survivre quand les variables
sont pleines.

Le pattern de nettoyage `\\s+-\\s+(?=[\\[\\(])` s'appliquait APRES le retrait des
groupes vides : son lookahead ne voyait donc plus que des groupes PLEINS et il
supprimait le tiret voulu par l'utilisateur dans le cas nominal.
Les deux patterns de remplacement exigent le RESIDU d'espace laisse par une
variable videe, seul signal fiable distinguant un tiret orphelin d'un tiret
demande.

Portee : nom de DOSSIER uniquement (le fichier video n'est jamais renomme).
"""

from __future__ import annotations

import unittest

from cinesort.domain.naming import build_naming_context, format_movie_folder


def _ctx():
    return build_naming_context(
        title="Inception",
        year=2010,
        probe_data={"video": {"height": 1080, "width": 1920}},
    )


class DashKeptWhenVariablesFilledTests(unittest.TestCase):
    def test_tiret_conserve_avant_crochet(self):
        self.assertEqual(format_movie_folder("{title} - [{resolution}]", _ctx()), "Inception - [1080p]")

    def test_tiret_conserve_avant_parenthese(self):
        self.assertEqual(format_movie_folder("{title} - ({year})", _ctx()), "Inception - (2010)")


class DashOrphanStillCleanedTests(unittest.TestCase):
    """Non-regression : les cas que le pattern d'origine servait legitimement.

    Doit rester VERT des deux cotes de la mutation.
    """

    def test_variable_videe_apres_le_tiret(self):
        ctx = dict(_ctx())
        ctx["resolution"] = ""
        self.assertEqual(format_movie_folder("{title} - [{resolution}] ({year})", ctx), "Inception (2010)")

    def test_variable_videe_avant_le_crochet(self):
        # {edition-tag} est vide -> "Inception -  [1080p]" (double espace).
        self.assertEqual(
            format_movie_folder("{title} - {edition-tag} [{resolution}]", _ctx()),
            "Inception [1080p]",
        )

    def test_tiret_final_orphelin_toujours_retire(self):
        ctx = dict(_ctx())
        ctx["resolution"] = ""
        self.assertEqual(format_movie_folder("{title} - [{resolution}]", ctx), "Inception")

    def test_tiret_initial_orphelin_toujours_retire(self):
        ctx = dict(_ctx())
        ctx["resolution"] = ""
        self.assertEqual(format_movie_folder("[{resolution}] - {title}", ctx), "Inception")

    def test_tiret_sans_crochet_toujours_conserve(self):
        # Temoin du finding : le pattern fautif ne se declenchait que devant
        # un crochet/parenthese, ce cas etait deja correct.
        self.assertEqual(format_movie_folder("{title} - {resolution}", _ctx()), "Inception - 1080p")

    def test_presets_livres_inchanges(self):
        ctx = _ctx()
        self.assertEqual(format_movie_folder("{title} ({year})", ctx), "Inception (2010)")
        self.assertEqual(format_movie_folder("{title} ({year}) [{resolution}]", ctx), "Inception (2010) [1080p]")


if __name__ == "__main__":
    unittest.main()
