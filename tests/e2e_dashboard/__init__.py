"""Tests E2E dashboard workflow — necessite pytest + serveur REST CineSort.

Lancer avec : pytest tests/e2e_dashboard/ -v
"""


def load_tests(loader, tests, pattern):
    """Retourne une suite vide pour que unittest discover ignore ce package."""
    import unittest

    return unittest.TestSuite()
