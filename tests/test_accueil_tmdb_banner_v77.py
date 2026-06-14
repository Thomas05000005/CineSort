"""GATE AUDIT 2026-06-14 (R6-G) — la bannière accueil n'affiche plus une fausse
alerte "TMDb n'est pas configuré".

Le GET masque les secrets (tmdb_api_key revient vide), donc tester sa valeur
donnait une fausse alerte alors que la clé est configurée (pastille ☑TMDb verte
+ Paramètres "Configuré"). La bannière doit lire le flag canonique
`_has_tmdb_api_key`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ACCUEIL = Path(__file__).resolve().parent.parent / "web" / "dashboard" / "views" / "accueil.js"


class AccueilTmdbBannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _ACCUEIL.read_text(encoding="utf-8")

    def test_banner_uses_has_tmdb_flag(self) -> None:
        # La fonction de bannière doit s'appuyer sur _has_tmdb_api_key, pas
        # uniquement sur tmdb_api_key (masqué par le GET).
        m = re.search(r"function _renderSetupBanner\(settings\)\s*\{(.+?)\n\}", self.src, re.DOTALL)
        self.assertIsNotNone(m, "_renderSetupBanner introuvable")
        body = m.group(1)
        self.assertIn("_has_tmdb_api_key", body,
                      "La bannière doit lire _has_tmdb_api_key (flag de présence réelle).")

    def test_no_longer_keys_solely_on_masked_value(self) -> None:
        # tmdbMissing ne doit plus être '!tmdbKey || ...' seul.
        self.assertNotIn("const tmdbMissing = !tmdbKey || tmdbEnabled === false;", self.src)


if __name__ == "__main__":
    unittest.main()
