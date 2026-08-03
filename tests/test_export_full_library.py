"""Tests pour export_full_library (issue #95 RGPD Art. 20)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cinesort.ui.api.export_support import (
    _SECRET_KEYS,
    EXPORT_FORMAT_VERSION,
    _resolve_run_dir,
    _sanitize_settings,
    _UnsafeRunId,
    export_full_library,
)


class SanitizeSettingsTests(unittest.TestCase):
    """Les secrets DPAPI doivent etre retires de l'export."""

    def test_redacts_api_keys_when_present(self) -> None:
        s = {
            "tmdb_api_key": "secret123",
            "jellyfin_url": "http://localhost:8096",
            "smtp_password": "supersecret",
        }
        out = _sanitize_settings(s)
        self.assertEqual(out["tmdb_api_key"], "***REDACTED***")
        self.assertEqual(out["smtp_password"], "***REDACTED***")
        # Non-secrets passent tel quel
        self.assertEqual(out["jellyfin_url"], "http://localhost:8096")

    def test_empty_secret_returns_empty_string(self) -> None:
        out = _sanitize_settings({"tmdb_api_key": "", "plex_token": None})
        self.assertEqual(out["tmdb_api_key"], "")
        self.assertEqual(out["plex_token"], "")

    def test_all_known_secret_keys_redacted(self) -> None:
        s = {k: "value" for k in _SECRET_KEYS}
        s["jellyfin_url"] = "http://j"  # un non-secret pour controle
        out = _sanitize_settings(s)
        for k in _SECRET_KEYS:
            self.assertEqual(out[k], "***REDACTED***", f"{k} pas masque")
        self.assertEqual(out["jellyfin_url"], "http://j")


class ExportFullLibraryShapeTests(unittest.TestCase):
    """Forme du payload retourne par export_full_library."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_export_"))
        self.state_dir = self._tmp / "state"
        self.state_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_versioned_payload(self) -> None:
        """Meme sans aucun run, l'export doit retourner un payload bien forme."""
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {"data": {"tmdb_enabled": True}}
        # Mock store with no runs
        store = MagicMock()
        store.run.get_runs_summary.return_value = []
        api._get_or_create_infra.return_value = (store, MagicMock())

        out = export_full_library(api)
        self.assertTrue(out["ok"])
        self.assertEqual(out["version"], EXPORT_FORMAT_VERSION)
        self.assertIn("exported_at", out)
        self.assertEqual(out["runs"], [])
        self.assertEqual(out["films"], [])
        self.assertEqual(out["film_count"], 0)

    def test_settings_sanitized_in_export(self) -> None:
        """Les settings dans l'export ne contiennent pas les secrets clairs."""
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {
            "data": {
                "tmdb_api_key": "MY-REAL-KEY",
                "tmdb_enabled": True,
                "jellyfin_url": "http://lan.local:8096",
            }
        }
        store = MagicMock()
        store.run.get_runs_summary.return_value = []
        api._get_or_create_infra.return_value = (store, MagicMock())

        out = export_full_library(api)
        self.assertNotIn("MY-REAL-KEY", json.dumps(out))
        self.assertEqual(out["settings"]["tmdb_api_key"], "***REDACTED***")
        self.assertEqual(out["settings"]["jellyfin_url"], "http://lan.local:8096")

    def test_films_extracted_from_last_done_run(self) -> None:
        """Si un run DONE existe, ses films sont serialises avec decisions + scores."""
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {"data": {}}

        # Creer un run DONE avec plan.jsonl + validation.json
        run_id = "test_run_001"
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True)
        plan_jsonl = run_dir / "plan.jsonl"
        plan_jsonl.write_text(
            json.dumps(
                {
                    "row_id": "row1",
                    "kind": "single",
                    "folder": "C:\\Films\\Inception",
                    "video": "Inception.mkv",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "confidence": 95,
                    "confidence_label": "high",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "validation.json").write_text(
            json.dumps({"row1": {"ok": True, "title": "Inception", "year": 2010}}),
            encoding="utf-8",
        )

        store = MagicMock()
        store.run.get_runs_summary.return_value = [
            {
                "run_id": run_id,
                "status": "DONE",
                "start_ts": 0.0,
                "duration_s": 10.0,
                "total_rows": 1,
            }
        ]
        store.quality.get_quality_report.return_value = {"score": 92, "tier": "premium"}
        api._get_or_create_infra.return_value = (store, MagicMock())

        out = export_full_library(api)
        self.assertTrue(out["ok"])
        self.assertEqual(out["last_done_run_id"], run_id)
        self.assertEqual(out["film_count"], 1)
        f = out["films"][0]
        self.assertEqual(f["title"], "Inception")
        self.assertEqual(f["year"], 2010)
        self.assertEqual(f["decision"]["ok"], True)
        self.assertEqual(f["quality_score"], 92)
        self.assertEqual(f["quality_tier"], "premium")

    def test_serializable_to_json(self) -> None:
        """Le payload doit etre serialisable JSON sans erreur."""
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {"data": {"tmdb_enabled": True}}
        store = MagicMock()
        store.run.get_runs_summary.return_value = []
        api._get_or_create_infra.return_value = (store, MagicMock())

        out = export_full_library(api)
        # Doit etre serialisable sans TypeError
        try:
            json.dumps(out, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            self.fail(f"Payload pas serializable: {e}")


class RunIdValidationTests(unittest.TestCase):
    """Issue #427 (CWE-22) — `last_done_run_id` sort de la base et doit etre valide.

    Les deux gardes sont eprouvees SEPAREMENT : un run_id hors format qui reste
    lexicalement sous state_dir/runs n'active que la premiere ; un run_id qui
    s'echappe du repertoire n'active que la seconde.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_runid_"))
        self.state_dir = self._tmp / "state"
        (self.state_dir / "runs").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _api_with_run_id(self, run_id: str) -> MagicMock:
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {"data": {}}
        store = MagicMock()
        store.run.get_runs_summary.return_value = [
            {"run_id": run_id, "status": "DONE", "start_ts": 0.0, "duration_s": 1.0, "total_rows": 0}
        ]
        api._get_or_create_infra.return_value = (store, MagicMock())
        return api

    def test_malformed_run_id_in_db_is_refused(self) -> None:
        """Garde 1 : hors format. `ab` reste sous runs/, seul le regex peut le rejeter."""
        out = export_full_library(self._api_with_run_id("ab"))
        self.assertFalse(out["ok"])

    def test_run_id_with_forbidden_characters_is_refused(self) -> None:
        out = export_full_library(self._api_with_run_id("run id!"))
        self.assertFalse(out["ok"])

    def test_legitimate_run_id_formats_still_export(self) -> None:
        """Garde-fou anti-regression : les formats reellement produits passent."""
        for run_id in ("20260803_141500_123", "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "demo_1754200000_ab12cd"):
            with self.subTest(run_id=run_id):
                out = export_full_library(self._api_with_run_id(run_id))
                self.assertTrue(out["ok"], f"{run_id} refuse a tort")
                self.assertEqual(out["last_done_run_id"], run_id)

    def test_resolve_run_dir_refuses_directory_outside_runs(self) -> None:
        """Garde 2 : containment, eprouvee directement sur le helper."""
        outside = self._tmp / "outside"
        outside.mkdir()
        with self.assertRaises(_UnsafeRunId):
            _resolve_run_dir(self.state_dir, "../../outside")

    def test_resolve_run_dir_returns_none_when_run_purged(self) -> None:
        self.assertIsNone(_resolve_run_dir(self.state_dir, "20260803_141500_123"))

    def test_resolve_run_dir_finds_prefixed_directory(self) -> None:
        run_dir = self.state_dir / "runs" / "tri_films_20260803_141500_123"
        run_dir.mkdir()
        self.assertEqual(_resolve_run_dir(self.state_dir, "20260803_141500_123"), run_dir.resolve())


class ExportFullLibraryEdgeCasesTests(unittest.TestCase):
    def test_missing_state_dir_returns_error(self) -> None:
        api = MagicMock()
        api._state_dir = None
        out = export_full_library(api)
        self.assertFalse(out["ok"])

    def test_get_settings_failure_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = MagicMock()
            api._state_dir = Path(tmp)
            api.settings.get_settings.side_effect = TypeError("settings broken")
            store = MagicMock()
            store.run.get_runs_summary.return_value = []
            api._get_or_create_infra.return_value = (store, MagicMock())

            out = export_full_library(api)
            # Doit retourner ok=True meme si get_settings echoue (settings vides)
            self.assertTrue(out["ok"])
            self.assertEqual(out["settings"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
