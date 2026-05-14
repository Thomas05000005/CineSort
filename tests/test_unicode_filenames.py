"""Tests Unicode / emoji / CJK / long paths (issue #87).

Verifie que les helpers de naming/sanitization domain gerent correctement les
films aux titres exotiques (real-world : utilisateur asiatique, films d'art
et essai avec emoji dans le nom, releases cyrilliques, etc.).

Pas de mock filesystem — on teste les fonctions pures qui produisent le nom
final destine au disque.
"""

from __future__ import annotations

import unittest

from cinesort.domain.core import windows_safe
from cinesort.domain.naming import (
    build_naming_context,
    check_path_length,
    format_movie_folder,
    folder_matches_template,
)


class WindowsSafeUnicodeTests(unittest.TestCase):
    """windows_safe ne doit pas casser les chars valides Unicode."""

    def test_emoji_preserved(self) -> None:
        """Les emojis dans le titre doivent etre conserves (caracteres valides)."""
        out = windows_safe("Le Film 🎬 (2024)")
        self.assertIn("🎬", out)
        # Pas de chars interdits Windows
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, out)

    def test_cjk_preserved(self) -> None:
        """Caracteres CJK : Sen et Chihiro (Le Voyage de Chihiro)."""
        out = windows_safe("千と千尋の神隠し (2001)")
        self.assertIn("千", out)
        self.assertIn("尋", out)

    def test_cyrillic_preserved(self) -> None:
        """Cyrillique : A zori zdes' tikhie."""
        out = windows_safe("А зори здесь тихие (1972)")
        self.assertIn("А", out)
        self.assertIn("зори", out)

    def test_arabic_preserved(self) -> None:
        """Arabe : caracteres RTL."""
        out = windows_safe("الرسالة (1976)")
        self.assertIn("الرسالة", out)

    def test_accents_preserved(self) -> None:
        """Accents FR/ES/DE preserves."""
        out = windows_safe("Amélie poulain & déjà vu (2001)")
        self.assertIn("é", out)
        self.assertIn("à", out)

    def test_combining_chars_nfc_normalized(self) -> None:
        """e + combining acute → e accent precompose (NFC)."""
        # 'é' (NFC, 1 codepoint) vs 'e' + combining acute (NFD, 2 codepoints)
        nfd = "Amélie"
        out = windows_safe(nfd)
        # Apres NFC, on doit avoir le 'é' precompose
        self.assertIn("Amélie", out)

    def test_forbidden_chars_stripped(self) -> None:
        """<>:\"/\\|?* doivent etre supprimes meme avec Unicode autour."""
        out = windows_safe("Le Film: 🎬 / 千 ? * (2024)")
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, out)
        # Mais l'emoji et le CJK survivent
        self.assertIn("🎬", out)
        self.assertIn("千", out)

    def test_long_title_truncated_to_180_chars(self) -> None:
        """windows_safe coupe a 180 chars (limite Windows MAX_PATH segment)."""
        long_title = "A" * 300
        out = windows_safe(long_title)
        self.assertLessEqual(len(out), 180)

    def test_long_unicode_title_truncated(self) -> None:
        """Truncation marche aussi avec des chars multi-byte."""
        # 200 emojis (4 bytes UTF-8 chacun)
        out = windows_safe("🎬" * 200)
        # NB : on compte en CHARS Python (codepoints), pas en bytes
        self.assertLessEqual(len(out), 180)


class FormatMovieFolderUnicodeTests(unittest.TestCase):
    """format_movie_folder doit produire un nom valide pour des titres exotiques."""

    def test_cjk_movie_with_year(self) -> None:
        ctx = build_naming_context(title="千と千尋の神隠し", year=2001)
        out = format_movie_folder("{title} ({year})", ctx)
        self.assertIn("千と千尋", out)
        self.assertIn("2001", out)

    def test_emoji_movie(self) -> None:
        ctx = build_naming_context(title="Le Film 🎬", year=2024)
        out = format_movie_folder("{title} ({year})", ctx)
        self.assertIn("🎬", out)

    def test_combining_diacritics_normalized(self) -> None:
        """Le NFC est applique par windows_safe en aval — meme normalisation."""
        ctx_nfd = build_naming_context(title="Amélie", year=2001)
        ctx_nfc = build_naming_context(title="Amélie", year=2001)
        out_nfd = format_movie_folder("{title} ({year})", ctx_nfd)
        out_nfc = format_movie_folder("{title} ({year})", ctx_nfc)
        self.assertEqual(out_nfd, out_nfc)


class CheckPathLengthUnicodeTests(unittest.TestCase):
    """check_path_length doit prendre en compte la taille Windows reelle."""

    def test_long_unicode_path_flagged(self) -> None:
        """Un path > 240 chars doit etre flagge (sous limite Windows MAX_PATH = 260)."""
        long_folder = "A" * 250
        # Root court pour s'assurer que c'est le folder qui depasse
        out = check_path_length("C:\\", long_folder)
        # check_path_length retourne un msg si trop long, None sinon
        self.assertIsNotNone(out)

    def test_short_unicode_path_ok(self) -> None:
        out = check_path_length("C:\\Films", "千と千尋の神隠し (2001)")
        self.assertIsNone(out)


class FolderMatchesTemplateUnicodeTests(unittest.TestCase):
    """folder_matches_template doit matcher meme avec Unicode."""

    def test_match_cjk(self) -> None:
        result = folder_matches_template("千と千尋 (2001)", "{title} ({year})", "千と千尋", 2001)
        self.assertTrue(result)

    def test_match_emoji(self) -> None:
        result = folder_matches_template("Le Film 🎬 (2024)", "{title} ({year})", "Le Film 🎬", 2024)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
