"""Tests de regression pour la deduplication des helpers de conversion (Vague M, M-04).

Vague M : les helpers prives _to_int / _to_float / _to_bitrate_int / _bool_from_text
de cinesort.infra.probe.normalize partageaient leur logique avec
cinesort.domain.conversions (audit MAINT-DUP-CONVERT). Centralisation des
variantes Optional dans le module domain pour eliminer la duplication.

Ce test verifie la conformite des deux APIs (default vs Optional) et la
non-regression des cas limite : nombres groupes, espaces insecables, unites
de bitrate, virgule decimale, booleens FR/EN.
"""

from __future__ import annotations

import unittest

from cinesort.domain.conversions import (
    to_optional_bitrate,
    to_optional_bool,
    to_optional_float,
    to_optional_int,
)
from cinesort.infra.probe._normalize_helpers import (
    _bool_from_text,
    _to_bitrate_int,
    _to_float,
    _to_int,
)


class TestConversionsDedup(unittest.TestCase):
    """Verifie que les helpers Probe delegueent strictement au module domain."""

    def test_to_int_delegates(self) -> None:
        cases = [
            (None, None),
            ("", None),
            ("invalid", None),
            (42, 42),
            (3.7, 4),  # int(round())
            (True, 1),
            ("3 840", 3840),  # espace insecable NBSP
            ("12,500,000", 12_500_000),  # groupes virgule
            ("12.500.000", 12_500_000),  # groupes point
            ("1080p", 1080),  # premiere sequence digits
        ]
        for raw, expected in cases:
            self.assertEqual(_to_int(raw), to_optional_int(raw), f"{raw!r}")
            self.assertEqual(_to_int(raw), expected, f"{raw!r} -> {expected}")

    def test_to_float_delegates(self) -> None:
        cases = [
            (None, None),
            ("", None),
            ("invalid", None),
            (3.14, 3.14),
            ("1.5", 1.5),
            ("1,5", 1.5),  # virgule decimale
            (0, 0.0),
        ]
        for raw, expected in cases:
            self.assertEqual(_to_float(raw), to_optional_float(raw), f"{raw!r}")
            self.assertEqual(_to_float(raw), expected, f"{raw!r} -> {expected}")

    def test_to_bitrate_int_delegates(self) -> None:
        cases = [
            (None, None),
            ("", None),
            (27000000, 27000000),
            (27.5, 28),
            ("27 Mb/s", 27_000_000),
            ("27 Mbit/s", 27_000_000),
            ("1.5 Gb/s", 1_500_000_000),
            ("128 Kb/s", 128_000),
            ("27000000", 27000000),
        ]
        for raw, expected in cases:
            self.assertEqual(_to_bitrate_int(raw), to_optional_bitrate(raw), f"{raw!r}")
            self.assertEqual(_to_bitrate_int(raw), expected, f"{raw!r} -> {expected}")

    def test_bool_from_text_delegates(self) -> None:
        cases = [
            (None, None),
            ("", None),
            ("maybe", None),
            ("1", True),
            ("true", True),
            ("yes", True),
            ("oui", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("non", False),
            ("YES", True),  # case insensitive
        ]
        for raw, expected in cases:
            self.assertEqual(_bool_from_text(raw), to_optional_bool(raw), f"{raw!r}")
            self.assertEqual(_bool_from_text(raw), expected, f"{raw!r} -> {expected}")

    def test_optional_bool_preserves_native_false_and_zero(self) -> None:
        """Audit 2026-06-25 : un booleen/entier natif falsy ne doit pas
        devenir None (confusion sentinelle absent vs False).

        La delegation est verifiee sur les types NATIFS, pas seulement sur les
        str de `test_bool_from_text_delegates` : c'est ce que consomme
        `_normalize_ffprobe`, qui arbitre sur `forced_tag is not None` et
        distingue donc reellement None de False.
        """
        for raw, expected in [
            (False, False),
            (True, True),
            (0, False),
            (1, True),
            (0.0, False),
            (None, None),
            ("", None),
        ]:
            self.assertIs(to_optional_bool(raw), expected, f"{raw!r}")
            self.assertIs(_bool_from_text(raw), expected, f"_bool_from_text({raw!r})")

    def test_canonical_module_does_not_import_probe(self) -> None:
        """cinesort.domain.conversions ne doit pas dependre de cinesort.infra.*."""
        import inspect

        import cinesort.domain.conversions as mod

        src = inspect.getsource(mod)
        self.assertNotIn("from cinesort.infra", src)
        self.assertNotIn("import cinesort.infra", src)


if __name__ == "__main__":
    unittest.main()
