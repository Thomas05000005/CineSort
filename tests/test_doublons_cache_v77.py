"""GATE AUDIT 2026-06-14 (R6-C) — cache des doublons entre navigations.

Avant : chaque entree dans la vue Doublons relancait check_duplicates (scan de
~1000 films + disque) -> plusieurs secondes a chaque navigation. Desormais, un
cache module-level (_groupsCache) cle par runId est restitue instantanement ;
"Actualiser" et les decisions forcent un re-scan.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_DOUBLONS = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "doublons.js"


class DoublonsCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS.read_text(encoding="utf-8")

    def test_module_cache_exists(self) -> None:
        self.assertIn("let _groupsCache", self.js)

    def test_load_groups_has_force_param(self) -> None:
        self.assertIn("async function _loadGroups(force = false)", self.js)

    def test_cache_hit_short_circuits_scan(self) -> None:
        self.assertIn("!force && _groupsCache && _groupsCache.runId === runId", self.js)

    def test_refresh_action_forces_rescan(self) -> None:
        self.assertIn('if (action === "refresh") _loadGroups(true)', self.js)

    def test_init_navigation_uses_cache(self) -> None:
        # initDoublons (entree de vue) appelle _loadGroups() SANS force.
        m = re.search(r"export async function initDoublons\(container\)\s*\{(.+?)\n\}", self.js, re.DOTALL)
        self.assertIsNotNone(m)
        self.assertIn("await _loadGroups();", m.group(1))

    def test_decision_paths_force_resync(self) -> None:
        # Les chemins de decision resynchronisent en forcant (pas de cache stale).
        self.assertEqual(self.js.count("await _loadGroups(true)"), 2,
                         "Les 2 resync de decision (_decideFromCard + _autoDecideAll) doivent forcer.")


if __name__ == "__main__":
    unittest.main()
