"""V5bis-00 — Verifie le module shared web/views/_v5_helpers.js.

Tests structurels (parsing texte) qui garantissent les contrats publics
attendus par les vues v5 portees (V5bis-01 a 07).
"""

from __future__ import annotations

import unittest
from pathlib import Path


class V5HelpersStructureTests(unittest.TestCase):
    """Verifie les exports et patterns du module shared."""

    @classmethod
    def setUpClass(cls):
        cls.path = Path("web/views/_v5_helpers.js")
        cls.src = cls.path.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(self.path.exists(), "web/views/_v5_helpers.js doit exister")

    def test_apiPost_exported(self):
        self.assertIn("export async function apiPost", self.src)

    def test_apiPost_uses_rest_first(self):
        # Le wrapper doit importer apiPost depuis le client REST du SPA
        self.assertIn("_spaApiPost", self.src)
        self.assertIn('from "../dashboard/core/api.js"', self.src)

    def test_apiPost_fallback_pywebview(self):
        # Fallback pywebview present pour mode natif
        self.assertIn("window.pywebview", self.src)

    def test_apiGet_exported(self):
        self.assertIn("export async function apiGet", self.src)

    def test_dom_helpers_exported(self):
        # escapeHtml exporte (re-export depuis dashboard/core/dom.js)
        self.assertIn("export const escapeHtml", self.src)
        # $, $$, el exportes
        self.assertIn("export { $, $$, el }", self.src)

    def test_dom_helpers_imported_from_dashboard(self):
        self.assertIn('from "../dashboard/core/dom.js"', self.src)

    def test_init_view_pattern(self):
        # Pattern standardise skeleton -> load -> render | error
        self.assertIn("export async function initView", self.src)
        self.assertIn("renderSkeleton", self.src)
        self.assertIn("renderError", self.src)

    def test_render_skeleton_exported(self):
        self.assertIn("export function renderSkeleton", self.src)

    def test_render_error_exported(self):
        self.assertIn("export function renderError", self.src)

    def test_skeleton_types(self):
        # 4 skeletons de base : default, table, grid, form
        for t in ["default", "table", "grid", "form"]:
            self.assertIn(f'"{t}"', self.src, f"skeleton type {t!r} attendu")

    def test_utility_helpers(self):
        self.assertIn("export function formatSize", self.src)
        self.assertIn("export function formatDuration", self.src)
        self.assertIn("export function isNativeMode", self.src)

    def test_native_mode_uses_global_flag(self):
        # isNativeMode doit s'appuyer sur le flag pose par app.js au boot
        self.assertIn("__CINESORT_NATIVE__", self.src)

    def test_rest_call_precedes_pywebview_fallback(self):
        # Le wrapper apiPost doit appeler REST en premier ; le check pywebview
        # ne doit intervenir qu'en fallback dans le catch.
        # Pour eviter les faux positifs sur les commentaires, on cible les
        # patterns runtime : "_spaApiPost(method" (appel) et
        # "window.pywebview?.api?.[method]" (check fallback).
        idx_rest_call = self.src.find("_spaApiPost(method")
        idx_pywebview_check = self.src.find("window.pywebview?.api?.[method]")
        self.assertGreater(idx_rest_call, 0, "_spaApiPost(method) doit etre appele")
        self.assertGreater(idx_pywebview_check, 0, "window.pywebview?.api?.[method] doit etre check")
        self.assertLess(
            idx_rest_call,
            idx_pywebview_check,
            "Le client REST doit etre tente avant le fallback pywebview",
        )


class V5HelpersResponseFormatTests(unittest.TestCase):
    """Verifie que la normalisation de reponse expose bien {ok, data, status, error}."""

    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/_v5_helpers.js").read_text(encoding="utf-8")

    def test_normalized_format_documented(self):
        # Le commentaire en tete documente le format de retour
        self.assertIn("ok:", self.src)
        self.assertIn("data:", self.src)
        self.assertIn("status:", self.src)

    def test_normalize_rest_response_present(self):
        self.assertIn("_normalizeRestResponse", self.src)

    def test_normalize_pywebview_response_present(self):
        self.assertIn("_normalizePywebviewResponse", self.src)


if __name__ == "__main__":
    unittest.main()
