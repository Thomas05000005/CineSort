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

EXTENSION 2026-08-27 — la lecon n'avait ete portee qu'a DEUX des cinq coerceurs
« tolerants » du depot. Les trois restants la contredisaient chacun a sa facon,
et deux d'entre eux etaient asymetriques avec un frere du MEME fichier :

    conversions.to_optional_bitrate      `int(round(value))` nu, la ou
                                         `to_optional_int` (30 lignes plus haut)
                                         est garde depuis la PR#908 ;
    settings_support._coerce_int_with_default  contrat « ValueError/TypeError ->
                                         default » que l'infini contournait ;
    _validators.clamp_non_negative_int   `int(float(value))` nu, la ou
                                         `clamp_timeout` (meme fichier, dix
                                         lignes plus haut) filtre deja inf/nan.

ATTEIGNABILITE MESUREE, pas supposee : `_coerce_int_with_default` est appele sur
`payload.get(...)` a une dizaine de sites de `save_settings` (email_smtp_port,
plugins_timeout_s, perceptual_*), donc un corps REST `{"email_smtp_port":
Infinity}` suffit — `json.loads` accepte `Infinity` par DEFAUT.
"""

from __future__ import annotations

import json
import unittest

from cinesort.domain.conversions import to_int, to_optional_bitrate, to_optional_int
from cinesort.domain.resolution_class import RES_UNKNOWN, classify_resolution
from cinesort.ui.api._validators import clamp_non_negative_int
from cinesort.ui.api.settings_support import _coerce_int_with_default


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


class ToOptionalBitrateInfinityTests(unittest.TestCase):
    """AVANT : `int(round(value))` nu — l'exception traversait un helper qui
    promet `None`. Son frere `to_optional_int` du MEME module etait garde."""

    def test_infini_rend_none_au_lieu_de_lever(self) -> None:
        self.assertIsNone(to_optional_bitrate(float("inf")))
        self.assertIsNone(to_optional_bitrate(float("-inf")))

    def test_nan_rend_none_au_lieu_de_lever(self) -> None:
        """`round(nan)` leve ValueError : ce cas AUSSI traversait le helper."""
        self.assertIsNone(to_optional_bitrate(float("nan")))

    def test_une_chaine_absurde_devient_inf_sans_lever_puis_est_arrondie(self) -> None:
        """Le chemin par les UNITES, distinct du precedent.

        La premisse est MESUREE avant d'etre exploitee : `float()` d'un litteral
        decimal trop grand rend `inf` SANS lever (contrairement a `float(10**400)`
        sur un int Python, qui leve). Si cette ligne rougit un jour, c'est ma
        premisse qui est fausse, pas le correctif.
        """
        self.assertEqual(float("9" * 400), float("inf"))
        self.assertIsNone(to_optional_bitrate("9" * 400 + " Mb/s"))

    def test_les_bitrates_reels_sont_inchanges(self) -> None:
        """Contre-test : interdit le correctif trop large qui rendrait `None`
        partout. Ces quatre valeurs sont celles que le probe produit vraiment."""
        self.assertEqual(to_optional_bitrate(8_500_000), 8_500_000)
        self.assertEqual(to_optional_bitrate(8_500_000.4), 8_500_000)
        self.assertEqual(to_optional_bitrate("8 Mb/s"), 8_000_000)
        self.assertEqual(to_optional_bitrate("1,5 Gb/s"), 1_500_000_000)

    def test_zero_reste_zero_et_le_vide_reste_none(self) -> None:
        """La sentinelle ne doit pas bouger : `0` est une mesure, `""` une absence."""
        self.assertEqual(to_optional_bitrate(0.0), 0)
        self.assertIsNone(to_optional_bitrate(""))
        self.assertIsNone(to_optional_bitrate(None))


class CoerceIntWithDefaultInfinityTests(unittest.TestCase):
    """`_coerce_int_with_default` annonce « ValueError/TypeError -> default ».
    L'infini n'est ni l'un ni l'autre : il ressortait par le haut."""

    def test_infini_rend_le_defaut(self) -> None:
        self.assertEqual(_coerce_int_with_default(float("inf"), 30), 30)
        self.assertEqual(_coerce_int_with_default(float("-inf"), 30), 30)

    def test_la_chaine_inf_rend_le_defaut(self) -> None:
        """La branche str : `int("inf")` leve ValueError, puis `int(float("inf"))`
        levait OverflowError — le second `except` ne le voyait pas."""
        self.assertEqual(_coerce_int_with_default("inf", 30), 30)
        self.assertEqual(_coerce_int_with_default("Infinity", 30), 30)

    def test_depuis_un_corps_REST(self) -> None:
        """Le chemin reel : `save_settings` coerce `payload.get(...)`."""
        payload = json.loads('{"email_smtp_port": Infinity}')
        self.assertEqual(_coerce_int_with_default(payload["email_smtp_port"], 587), 587)

    def test_les_valeurs_normales_sont_inchangees(self) -> None:
        """Contre-test : la garde ne doit pas repeindre tout en `default`."""
        self.assertEqual(_coerce_int_with_default(0, 30), 0)
        self.assertEqual(_coerce_int_with_default("0", 30), 0)
        self.assertEqual(_coerce_int_with_default("45", 30), 45)
        self.assertEqual(_coerce_int_with_default(45.9, 30), 45)
        self.assertEqual(_coerce_int_with_default(None, 30), 30)
        self.assertEqual(_coerce_int_with_default(True, 30), 30)
        self.assertEqual(_coerce_int_with_default(float("nan"), 30), 30)


class ClampNonNegativeIntInfinityTests(unittest.TestCase):
    """Asymetrie interne : `clamp_timeout` filtrait deja inf/nan dix lignes
    au-dessus, dans le meme fichier."""

    def test_infini_rend_le_defaut(self) -> None:
        self.assertEqual(clamp_non_negative_int(float("inf"), 5), 5)
        self.assertEqual(clamp_non_negative_int(float("-inf"), 5), 5)
        self.assertEqual(clamp_non_negative_int("inf", 5), 5)

    def test_les_valeurs_normales_sont_inchangees(self) -> None:
        """Contre-test, dont le clamp a zero qui est la raison d'etre du helper."""
        self.assertEqual(clamp_non_negative_int(12), 12)
        self.assertEqual(clamp_non_negative_int("12"), 12)
        self.assertEqual(clamp_non_negative_int(-3), 0)
        self.assertEqual(clamp_non_negative_int(None, 7), 7)
        self.assertEqual(clamp_non_negative_int("abc", 7), 7)
        self.assertEqual(clamp_non_negative_int(float("nan"), 5), 5)


if __name__ == "__main__":
    unittest.main()
