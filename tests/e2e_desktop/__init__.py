"""Tests E2E desktop CineSort — nécessitent pytest + CINESORT_E2E=1.

Lancer avec : pytest tests/e2e_desktop/ -v
"""


def load_tests(loader, tests, pattern):
    """Retourne une suite vide pour que unittest discover ignore ce package."""
    import unittest

    return unittest.TestSuite()
