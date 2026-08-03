"""GATE AUDIT 2026-06-10 (REAL 2/2) — _hydrate_settings_from_store ne doit pas
laisser un secret MASQUE ("••••••••") venant du caller ecraser la vraie cle
dechiffree on-disk.

Contexte : les callers UI (accueil.js _triggerStartPlan, watcher) renvoient le
payload de settings/get_settings dont les secrets sont masques. Avant le fix, le
masque ecrasait tmdb_api_key/omdb_api_key on-disk -> scan avec cle invalide (401).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.ui.api.run_flow_support import _hydrate_settings_from_store
from cinesort.ui.api.settings_support import _SECRET_MASK


def _write_settings(state_dir: Path, data: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")


class HydrateSecretsMaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_hydrate_")
        self.state_dir = Path(self._tmp)
        # On-disk : vraies cles dechiffrees
        _write_settings(
            self.state_dir,
            {
                "tmdb_api_key": "REAL_tmdb_key_123",
                "omdb_api_key": "REAL_omdb_key_456",
                "tmdb_enabled": True,
                "library_path": "C:/old",
            },
        )
        self.api = SimpleNamespace(
            _resolve_payload_state_dir=lambda s: (self.state_dir, True),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_masked_secret_does_not_override_real_key(self) -> None:
        """Le masque du caller ne doit PAS ecraser la vraie cle on-disk."""
        caller = {"library_path": "C:/new", "tmdb_api_key": _SECRET_MASK, "omdb_api_key": _SECRET_MASK}
        merged = _hydrate_settings_from_store(self.api, caller)
        self.assertEqual(merged["tmdb_api_key"], "REAL_tmdb_key_123")
        self.assertEqual(merged["omdb_api_key"], "REAL_omdb_key_456")
        # Les cles non-secretes du caller priment bien
        self.assertEqual(merged["library_path"], "C:/new")

    def test_real_secret_from_caller_still_overrides(self) -> None:
        """Une VRAIE cle passee par le caller (ex tests) prime toujours on-disk."""
        caller = {"tmdb_api_key": "explicit_test_key"}
        merged = _hydrate_settings_from_store(self.api, caller)
        self.assertEqual(merged["tmdb_api_key"], "explicit_test_key")

    def test_non_secret_keys_override_as_before(self) -> None:
        """Comportement inchange pour les cles non-secretes."""
        caller = {"tmdb_enabled": False, "library_path": "C:/x"}
        merged = _hydrate_settings_from_store(self.api, caller)
        self.assertFalse(merged["tmdb_enabled"])
        self.assertEqual(merged["library_path"], "C:/x")


if __name__ == "__main__":
    unittest.main()
