"""GATE AUDIT 2026-06-14 (R7-10) — reveal_rest_token (localhost-only).

GET settings masque rest_api_token -> Afficher/Copier exposait '********' (401
sur l'appareil distant). Endpoint dedie qui revele le vrai Bearer, refuse aux
requetes distantes (is_remote_request).
"""
from __future__ import annotations
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_API = _ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py"
_FAC = _ROOT / "cinesort" / "ui" / "api" / "facades" / "settings_facade.py"
_STATUS = _ROOT / "web" / "dashboard" / "views" / "status.js"


class RevealRestTokenTests(unittest.TestCase):
    def test_impl_localhost_only(self):
        src = _API.read_text(encoding="utf-8")
        self.assertIn("def _reveal_rest_token_impl(self)", src)
        idx = src.find("def _reveal_rest_token_impl")
        body = src[idx:idx + 1500]
        self.assertIn("if is_remote_request():", body)
        self.assertIn('"rest_api_token": token', body)

    def test_facade_exposes(self):
        self.assertIn("def reveal_rest_token(self)", _FAC.read_text(encoding="utf-8"))

    def test_front_fetches_real_token(self):
        js = _STATUS.read_text(encoding="utf-8")
        self.assertIn('apiPost("settings/reveal_rest_token")', js)


if __name__ == "__main__":
    unittest.main()
