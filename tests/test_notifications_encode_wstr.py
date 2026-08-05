"""Tests pour cinesort.infra.notifications._encode_wstr.

Cf issue audit-bot:10246e74 — la troncature historique se faisait par code points
Python (`text[: max_chars - 1]`), ce qui cassait les surrogate pairs UTF-16 quand
le texte contenait des emojis (1 code point Python = 2 code units UTF-16).
Apres truncate-puis-encode, struct.pack tronquait a `max_chars * 2` octets,
laissant potentiellement un high-surrogate orphelin dans le buffer Windows.

Ces tests verifient :
- ASCII pur reste correct (chemin nominal).
- Le buffer fait toujours exactement max_chars * 2 octets (contrat struct).
- Les emojis hors-BMP ne produisent pas de surrogate orphelin (au pire, le
  caractere est coupe proprement avant le high-surrogate).
- Le null terminator est preserve quand le texte tient dans le buffer.
"""

from __future__ import annotations

import unittest

from cinesort.infra.notifications import _encode_wstr


def _has_orphan_surrogate(buf: bytes) -> bool:
    """Retourne True si `buf` (UTF-16-LE) contient un high surrogate sans
    low surrogate qui suit (ou inversement). Le helper Windows ne doit JAMAIS
    produire ca, sinon Shell_NotifyIconW affiche un glyphe de remplacement."""
    if len(buf) % 2 != 0:
        return True
    i = 0
    while i < len(buf):
        cu = int.from_bytes(buf[i : i + 2], "little")
        if 0xD800 <= cu <= 0xDBFF:  # high surrogate
            if i + 2 >= len(buf):
                return True
            next_cu = int.from_bytes(buf[i + 2 : i + 4], "little")
            if not (0xDC00 <= next_cu <= 0xDFFF):
                return True
            i += 4
        elif 0xDC00 <= cu <= 0xDFFF:  # lone low surrogate
            return True
        else:
            i += 2
    return False


class EncodeWstrAsciiTests(unittest.TestCase):
    def test_ascii_fits_full(self) -> None:
        out = _encode_wstr("Hello", 64)
        self.assertEqual(len(out), 64 * 2)
        # "Hello" puis padding null
        self.assertEqual(out[: len("Hello") * 2], "Hello".encode("utf-16-le"))
        # Tail rempli de zeros (apres "Hello\x00\x00\x00\x00...")
        self.assertTrue(all(b == 0 for b in out[len("Hello") * 2 :]))

    def test_ascii_truncated_keeps_null_terminator(self) -> None:
        text = "A" * 100
        max_chars = 64
        out = _encode_wstr(text, max_chars)
        self.assertEqual(len(out), max_chars * 2)
        # On garde au plus max_chars - 1 = 63 'A' encodes en UTF-16
        ascii_a = b"\x41\x00"
        self.assertEqual(out[: 63 * 2], ascii_a * 63)
        # Le dernier code unit (octets 126-127) est le null terminator
        self.assertEqual(out[-2:], b"\x00\x00")


class EncodeWstrEmojiTests(unittest.TestCase):
    """Verifie qu'un emoji ne casse pas le buffer en surrogate orphelin."""

    def test_emoji_count_under_capacity(self) -> None:
        # Trois emojis = 6 UTF-16 code units = 12 octets, largement sous 128
        out = _encode_wstr("🎬🎬🎬", 64)
        self.assertEqual(len(out), 128)
        self.assertFalse(_has_orphan_surrogate(out))
        # Les 12 premiers octets doivent etre exactement les 3 emojis
        self.assertEqual(out[:12], "🎬🎬🎬".encode("utf-16-le"))

    def test_emoji_overflow_no_orphan_surrogate(self) -> None:
        """Cas critique : plus d'emojis que ne peut contenir le buffer.

        40 emojis = 80 UTF-16 code units = 160 octets, qui depassent largement
        szInfoTitle (max_chars=64, 128 octets capacity).

        Le buffer retourne DOIT :
        - Faire exactement max_chars * 2 octets.
        - Ne contenir aucun surrogate orphelin.
        """
        text = "🎬" * 40
        max_chars = 64
        out = _encode_wstr(text, max_chars)
        self.assertEqual(len(out), max_chars * 2)
        self.assertFalse(_has_orphan_surrogate(out))

    def test_mixed_ascii_emoji_overflow(self) -> None:
        """Force une troncature pile sur la frontiere d'une surrogate pair."""
        # 62 'A' (62 UTF-16 code units = 124 octets) + 1 emoji (2 code units = 4
        # octets) => 128 octets. max_chars=64 reserve 1 code unit pour le null
        # terminator => 126 octets effectifs. L'emoji doit etre retire en entier,
        # jamais coupe au milieu de sa paire de surrogates.
        text = "A" * 62 + "🎬"
        max_chars = 64
        out = _encode_wstr(text, max_chars)
        self.assertEqual(len(out), max_chars * 2)
        self.assertFalse(_has_orphan_surrogate(out))

    def test_lone_surrogate_not_produced_when_capacity_too_small(self) -> None:
        """Si max_chars est trop petit pour contenir l'emoji + null, le helper
        doit retomber sur une chaine vide plutot que de laisser un orphelin."""
        out = _encode_wstr("🎬", 2)
        self.assertEqual(len(out), 4)
        self.assertFalse(_has_orphan_surrogate(out))


if __name__ == "__main__":
    unittest.main()
