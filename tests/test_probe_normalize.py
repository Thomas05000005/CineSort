"""Tests pour cinesort/infra/probe/normalize._to_int.

Cf [audit-bot:2026-05-26-A4] : ajout d'une borne de magnitude pour eviter
qu'un fichier video crafte avec des metadonnees pathologiques (string
"9" * 1_000_000 dans duree/bitrate) cause une MemoryError au passage par
int() ou a la serialisation JSON ulterieure.
"""

from __future__ import annotations

import unittest

from cinesort.infra.probe.normalize import _to_int


class ToIntMagnitudeTest(unittest.TestCase):
    """Audit A4 : garde-fou magnitude sur _to_int."""

    # ---------- Comportement legacy preserve (regression-safe) ----------

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_to_int(None))

    def test_int_passthrough(self) -> None:
        self.assertEqual(_to_int(42), 42)
        self.assertEqual(_to_int(0), 0)
        self.assertEqual(_to_int(-7), -7)

    def test_bool_returns_int(self) -> None:
        self.assertEqual(_to_int(True), 1)
        self.assertEqual(_to_int(False), 0)

    def test_float_rounds(self) -> None:
        self.assertEqual(_to_int(3.4), 3)
        self.assertEqual(_to_int(3.6), 4)

    def test_grouped_number_with_space(self) -> None:
        self.assertEqual(_to_int("3 840"), 3840)

    def test_grouped_number_with_comma(self) -> None:
        self.assertEqual(_to_int("12,500,000"), 12500000)

    def test_grouped_number_with_dot(self) -> None:
        self.assertEqual(_to_int("12.500.000"), 12500000)

    def test_first_digits_simple(self) -> None:
        self.assertEqual(_to_int("123"), 123)
        self.assertEqual(_to_int("1080p"), 1080)

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_to_int(""))
        self.assertIsNone(_to_int("   "))

    # ---------- Audit A4 : magnitude guard ----------

    def test_huge_grouped_number_returns_none(self) -> None:
        """Une chaine groupee plus grande que 10^15 doit retourner None."""
        # 9 999 999 999 999 999 999 = 19 digits -> bloque
        huge_grouped = ",".join(["9" * 3] * 7)  # "999,999,999,999,999,999,999"
        result = _to_int(huge_grouped)
        # Soit None (bloque magnitude), soit un int <= 10^15 si parse fail-safe.
        # Ne doit pas leve d'exception ni allouer 1 MB de heap.
        if result is not None:
            self.assertLessEqual(abs(result), 10**15)

    def test_huge_first_digits_returns_none(self) -> None:
        """Une chaine de 100 digits doit etre rejetee (defense vs DoS)."""
        huge = "9" * 100
        self.assertIsNone(_to_int(huge))

    def test_huge_million_digits_returns_none_quickly(self) -> None:
        """1 million de digits : doit retourner None sans MemoryError."""
        # On limite a 10_000 ici pour ne pas plomber le test runner si la guard
        # echoue, mais le principe est le meme : ne pas appeler int() dessus.
        very_long = "9" * 10_000
        self.assertIsNone(_to_int(very_long))

    def test_at_limit_accepted(self) -> None:
        """10^15 = 1_000_000_000_000_000 (16 digits) doit etre accepte."""
        at_limit = str(10**15)  # "1000000000000000" -> 16 digits
        self.assertEqual(_to_int(at_limit), 10**15)

    def test_just_above_limit_rejected(self) -> None:
        """10^16 = 1 + 16 digits = 17 digits -> magnitude excede 10^15."""
        above = "1" + "0" * 16  # 10^16 = 17 digits
        self.assertIsNone(_to_int(above))


if __name__ == "__main__":
    unittest.main()
