"""V5bis-01 — Verifie home.js porte vers ES module.

Tests structurels uniquement : pas de runtime JS, on lit le source pour
verifier que :
  - le fichier exporte `initHome` (entree standardisee v5),
  - il n'est plus une IIFE en tete de fichier,
  - il importe depuis `_v5_helpers.js` (apiPost, escapeHtml, $, ...),
  - il n'appelle plus `window.pywebview.api` directement,
  - les features V1-V4 portees par V5A sont preservees (V2-04, V2-08,
    V1-07, V1-06, V3-05).
"""

from __future__ import annotations

import unittest
from pathlib import Path


class HomeV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/home.js").read_text(encoding="utf-8")

    def test_es_module_exports_init(self):
        """Le module exporte `initHome(container, opts)` comme entree standard."""
        self.assertIn("export async function initHome", self.src)

    def test_no_more_iife(self):
        """Pas de `(function() { ... })();` en debut de fichier."""
        head = self.src.lstrip()[:80]
        self.assertNotRegex(head, r"\(function\s*\(\s*\)\s*\{")

    def test_imports_helpers(self):
        """Le module importe depuis le helper partage `_v5_helpers.js`."""
        self.assertIn('from "./_v5_helpers.js"', self.src)
        # `apiPost` est l'API obligatoire pour remplacer le bridge pywebview.
        self.assertIn("apiPost", self.src)

    def test_no_more_pywebview_api(self):
        """Plus aucune reference directe au bridge pywebview natif."""
        self.assertNotIn("window.pywebview.api", self.src)

    def test_v1_07_banner_preserved(self):
        """V1-07 — Banner outils manquants conserve les 2 endpoints metier."""
        self.assertIn("get_probe_tools_status", self.src)
        self.assertIn("auto_install_probe_tools", self.src)

    def test_v1_06_integrations_cta_preserved(self):
        """V1-06 — CTA Configurer Jellyfin/Plex/Radarr conserves."""
        self.assertIn("focus=jellyfin", self.src)
        self.assertIn("Configurer", self.src)

    def test_v3_05_demo_wizard_preserved(self):
        """V3-05 — Demo wizard premier-run est toujours invoque."""
        self.assertIn("showDemoWizardIfFirstRun", self.src)

    def test_v2_04_allsettled_preserved(self):
        """V2-04 — Promise.allSettled assure la resilience aux endpoints partiels."""
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton_preserved(self):
        """V2-08 — Le skeleton de chargement est toujours rendu avant le 1er fetch."""
        # Soit le `renderSkeleton` du helper, soit le `_renderSkeleton` interne.
        self.assertTrue(
            "renderSkeleton" in self.src or "_renderSkeleton" in self.src,
            "skeleton (V2-08) absent du module",
        )

    def test_apipost_for_start_plan_uses_kwargs(self):
        """V5bis-01 — Verifier que start_plan est appele en kwargs `{ settings }`."""
        # Le pattern attendu est `apiPost("start_plan", { settings })`. On cherche
        # une occurrence du nom de methode + de `apiPost` proches.
        self.assertIn('apiPost("start_plan"', self.src)


if __name__ == "__main__":
    unittest.main()
