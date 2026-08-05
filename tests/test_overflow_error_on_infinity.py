"""`OverflowError` n'herite PAS de `ValueError` — meme famille que la regle 4.

Le CLAUDE.md avertit que `sqlite3.Error` n'herite pas d'`OSError`, et que ce
piege a deja avorte des apply. Voici la meme forme, sur les conversions :

    OverflowError -> ArithmeticError      (PAS ValueError)

Donc `except (TypeError, ValueError)` ne l'attrape pas.

ATTEIGNABLE, et pas seulement en theorie : `json.loads` accepte `Infinity` et
`NaN` par DEFAUT (extension non standard de la bibliotheque standard), et ces
helpers sont nourris de valeurs PERSISTEES en JSON dans SQLite.

    int(float("nan"))  -> ValueError      (attrape de longue date)
    int(float("inf"))  -> OverflowError   (ne l'etait pas)
    round(float("inf")) -> OverflowError  (leve avant meme le `int()`)

Releve par CodeRabbit sur la PR#908, verifie et etendu : le defaut existait
aussi dans `conversions.to_int` (100+ sites d'appel) et
`conversions.to_optional_int`, que l'issue d'origine ne mentionnait pas.
"""

from __future__ import annotations

import json
import unittest

from cinesort.domain.conversions import to_int, to_optional_int
from cinesort.domain.resolution_class import RES_UNKNOWN, classify_resolution


class OverflowErrorHierarchyTests(unittest.TestCase):
    def test_overflow_error_ne_derive_pas_de_value_error(self) -> None:
        """Le fait qui rend tout le reste necessaire."""
        self.assertFalse(issubclass(OverflowError, ValueError))
        self.assertTrue(issubclass(OverflowError, ArithmeticError))

    def test_json_loads_accepte_infinity_par_defaut(self) -> None:
        """La porte d'entree : ce n'est pas une valeur qu'on fabrique a la main."""
        charge = json.loads('{"height": Infinity, "width": NaN}')
        self.assertEqual(charge["height"], float("inf"))
        self.assertNotEqual(charge["width"], charge["width"])  # NaN != NaN


class ToIntInfinityTests(unittest.TestCase):
    def test_to_int_rend_le_defaut_sur_infini(self) -> None:
        self.assertEqual(to_int(float("inf"), 0), 0)
        self.assertEqual(to_int(float("-inf"), -1), -1)

    def test_to_int_rend_le_defaut_sur_nan(self) -> None:
        """Non-regression : ce cas passait deja par ValueError."""
        self.assertEqual(to_int(float("nan"), 7), 7)

    def test_to_int_depuis_un_json_persiste(self) -> None:
        """Le chemin reel : une valeur relue depuis SQLite."""
        detected = json.loads('{"height": Infinity}')
        self.assertEqual(to_int(detected["height"], 0), 0)

    def test_to_optional_int_rend_none_sur_infini(self) -> None:
        self.assertIsNone(to_optional_int(float("inf")))
        self.assertIsNone(to_optional_int(float("-inf")))


class ClassifyResolutionInfinityTests(unittest.TestCase):
    def test_une_dimension_infinie_ne_leve_pas_et_classe_sur_l_autre(self) -> None:
        """Le gain reel : AVANT, ces appels LEVAIENT `OverflowError`.

        Le contrat de `classify_resolution` est « RES_UNKNOWN quand AUCUNE des
        deux dimensions n'est exploitable » — donc avec une largeur saine, le
        classement doit continuer. (Premiere version de ce test : j'attendais
        RES_UNKNOWN des qu'une dimension etait infinie, c'etait MON assertion
        qui etait fausse, pas le code.)
        """
        self.assertEqual(classify_resolution(1920, float("inf")), "1080p")
        self.assertEqual(classify_resolution(float("inf"), 1080), "1080p")
        self.assertEqual(classify_resolution(3840, float("inf")), "2160p")

    def test_deux_dimensions_infinies_donnent_pas_de_verdict(self) -> None:
        """Aucune dimension exploitable -> pas de verdict, jamais une bande par defaut."""
        self.assertEqual(classify_resolution(float("inf"), float("inf")), RES_UNKNOWN)
        self.assertEqual(classify_resolution(float("nan"), float("inf")), RES_UNKNOWN)

    def test_valeurs_saines_toujours_classees(self) -> None:
        """Non-regression : la garde ne doit pas avaler les cas normaux."""
        self.assertNotEqual(classify_resolution(1920, 1080), RES_UNKNOWN)
        self.assertNotEqual(classify_resolution(3840, 2160), RES_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
