"""Tests pour export_full_library (issue #95 RGPD Art. 20)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cinesort.ui.api._validators as _validators
from cinesort.ui.api.export_support import (
    _SECRET_KEYS,
    EXPORT_FORMAT_VERSION,
    _resolve_run_dir,
    _sanitize_settings,
    _UnsafeRunId,
    export_full_library,
)
from cinesort.ui.api.settings_support import _mask_secrets

_IS_WINDOWS = os.name == "nt"


def _make_dir_link(link: Path, target: Path) -> None:
    """Cree un lien de dossier vers `target` (meme approche que l'issue #517).

    Sous Windows : une VRAIE jonction NTFS (`mklink /J`). C'est le seul vecteur
    par lequel la garde de containment peut se declencher en production, un
    run_id bien forme ne pouvant pas contenir de `..`. La creation de jonction
    ne demande aucun privilege : un echec est une erreur dure, jamais un skip.

    Ailleurs : un lien symbolique de dossier, equivalent fonctionnel.
    """
    if _IS_WINDOWS:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not link.exists():
            raise AssertionError(f"mklink /J a echoue (rc={proc.returncode}): {proc.stdout} {proc.stderr}")
        return
    link.symlink_to(target, target_is_directory=True)


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

    def test_masking_upstream_does_not_turn_an_absent_secret_into_a_present_one(self) -> None:
        """#526 (volet ECARTE) : un secret ABSENT reste distinguable d'un secret pose.

        L'issue affirmait que `_mask_secrets` (applique en amont par
        `get_settings_payload`) rend TOUTES les valeurs truthy — un secret vide
        deviendrait alors `***REDACTED***`, faisant croire a une cle configuree.
        C'est faux : `_mask_secrets` ne substitue le masque que si la valeur est
        non vide apres `strip()`. Ce test enchaine les deux etages exactement
        comme la production, pour que l'affirmation ne se re-fabrique pas.
        """
        payload = _mask_secrets({"tmdb_api_key": "", "plex_token": None, "smtp_password": "hunter2"})
        out = _sanitize_settings(payload)
        self.assertEqual(out["tmdb_api_key"], "")
        self.assertEqual(out["plex_token"], "")
        self.assertEqual(out["smtp_password"], "***REDACTED***")


class ExportFullLibraryShapeTests(unittest.TestCase):
    """Forme du payload retourne par export_full_library.

    #526 : ces tests mockaient `get_settings()` avec une enveloppe
    `{"data": {...}}` que la production ne renvoie PAS — `_get_settings_impl`
    rend le dict de settings A PLAT. Le mock FABRIQUAIT donc la forme que le
    code deballait, et la seule forme reellement servie par l'application
    n'etait couverte par aucun test. Les mocks disent desormais ce que
    `get_settings()` dit.
    """

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
        api.settings.get_settings.return_value = {"tmdb_enabled": True}
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
            "tmdb_api_key": "MY-REAL-KEY",
            "tmdb_enabled": True,
            "jellyfin_url": "http://lan.local:8096",
        }
        store = MagicMock()
        store.run.get_runs_summary.return_value = []
        api._get_or_create_infra.return_value = (store, MagicMock())

        out = export_full_library(api)
        self.assertNotIn("MY-REAL-KEY", json.dumps(out))
        self.assertEqual(out["settings"]["tmdb_api_key"], "***REDACTED***")
        self.assertEqual(out["settings"]["jellyfin_url"], "http://lan.local:8096")

    def test_a_settings_key_named_data_does_not_hijack_the_export(self) -> None:
        """#526 : l'export rend les REGLAGES, jamais le contenu d'une cle `data`.

        `get_settings()` rend le dict de settings a plat. L'ancien
        `settings_resp.get("data", settings_resp)` deballait une enveloppe qui
        n'existe pas — et `settings.json` n'etant filtre par aucune whitelist,
        une cle utilisateur nommee `data` prenait sa place : l'export RGPD
        repartait avec le contenu de cette cle, `ok: True`, sans avertissement.
        Mutation de controle : reintroduire le `.get("data", ...)` fait tomber
        ce test sur `KeyError: 'root'`.
        """
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {
            "tmdb_api_key": "MY-REAL-KEY",
            "root": "C:\\Films",
            "data": {"piege": 1},
        }
        store = MagicMock()
        store.run.get_runs_summary.return_value = []
        api._get_or_create_infra.return_value = (store, MagicMock())

        out = export_full_library(api)
        self.assertTrue(out["ok"])
        self.assertEqual(out["settings"]["root"], "C:\\Films")
        self.assertEqual(out["settings"]["tmdb_api_key"], "***REDACTED***")
        # La cle homonyme est exportee comme n'importe quel reglage non secret.
        self.assertEqual(out["settings"]["data"], {"piege": 1})

    def test_films_extracted_from_last_done_run(self) -> None:
        """Si un run DONE existe, ses films sont serialises avec decisions + scores."""
        api = MagicMock()
        api._state_dir = self.state_dir
        api.settings.get_settings.return_value = {}

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
        api.settings.get_settings.return_value = {"tmdb_enabled": True}
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
        """Fabrique une api dont la BASE renvoie `run_id` comme dernier run DONE.

        Le run_id est injecte par la source reelle (`get_runs_summary`), pas en
        court-circuitant la garde : aucun mock ne fabrique la condition testee.
        """
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
        """Un run_id porteur d'espaces et de ponctuation est refuse."""
        out = export_full_library(self._api_with_run_id("run id!"))
        self.assertFalse(out["ok"])

    def test_refused_run_id_is_not_reflected_back_to_the_caller(self) -> None:
        """La valeur alteree est loggee, jamais renvoyee : pas de reflexion vers l'UI."""
        tampered = "run id!<script>"
        out = export_full_library(self._api_with_run_id(tampered))
        self.assertFalse(out["ok"])
        self.assertNotIn(tampered, json.dumps(out, ensure_ascii=False))

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

    def test_resolve_run_dir_refuses_a_junction_pointing_outside(self) -> None:
        """Garde 2 sur son SEUL vecteur reel : un run_id BIEN FORME qui echappe.

        `../../outside` ne prouve pas grand-chose : `is_valid_run_id` le rejette
        en amont, la garde de containment n'est jamais atteinte en production
        avec une telle valeur. Le cas exploitable est un run_id conforme au
        regex dont le dossier `runs/tri_films_<id>` est une jonction NTFS (ou
        un lien symbolique) vers l'exterieur de `state_dir`.
        """
        run_id = "20260803_141500_123"
        self.assertTrue(_validators.is_valid_run_id(run_id), "le run_id du test doit passer la garde 1")
        outside = self._tmp / "outside"
        (outside / "runs_voles").mkdir(parents=True)
        _make_dir_link(self.state_dir / "runs" / f"tri_films_{run_id}", outside / "runs_voles")

        with self.assertRaises(_UnsafeRunId):
            _resolve_run_dir(self.state_dir, run_id)

    def test_export_refuses_a_run_whose_directory_escapes_state_dir(self) -> None:
        """Bout en bout : l'echappement remonte en refus d'export, pas en export vide."""
        run_id = "20260803_141500_123"
        outside = self._tmp / "outside"
        (outside / "runs_voles").mkdir(parents=True)
        _make_dir_link(self.state_dir / "runs" / f"tri_films_{run_id}", outside / "runs_voles")

        out = export_full_library(self._api_with_run_id(run_id))
        self.assertFalse(out["ok"])
        self.assertNotIn("films", out)

    def test_resolve_run_dir_returns_none_when_run_purged(self) -> None:
        """Un run efface du disque est un cas NORMAL : None, pas une exception."""
        self.assertIsNone(_resolve_run_dir(self.state_dir, "20260803_141500_123"))

    def test_resolve_run_dir_finds_prefixed_directory(self) -> None:
        """Le dossier reellement produit par `state.new_run` porte le prefixe `tri_films_`."""
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
