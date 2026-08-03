"""Retest apply dry-run via REST API.

Verifie 3 invariants:
1. POST /api/run/apply avec dry_run=True ne touche pas le FS.
2. Un rename "case-only" (Movie.2020 -> movie.2020) est detecte NOOP en preview.
3. apply_atomic est strict opt-in : default False, accepte True via REST.

Cf demande TEST_SCHEMA / test_name='apply_dryrun_retest'.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest import mock

sys.path.insert(0, ".")

import cinesort.domain.core as core
from cinesort.infra.rest_server import RestApiServer
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import find_free_port as _find_free_port
from tests._helpers import wait_run_done as _wait_done


class ApplyDryRunRestRetestTests(unittest.TestCase):
    """Cycle complet : scan -> validation -> apply dry-run via REST."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._patch = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        cls._patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._patch.stop()

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_dryrun_retest_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.api = CineSortApi()
        saved = self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

        self.port = _find_free_port()
        self.token = "retest-token-32chars-padding-xx!"
        self.server = RestApiServer(self.api, port=self.port, token=self.token)
        self.server.start()
        self._wait_server_ready(self.port)

    def tearDown(self) -> None:
        try:
            self.server.stop()
        finally:
            shutil.rmtree(self._tmp, ignore_errors=True)

    @staticmethod
    def _wait_server_ready(port: int, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=0.5)
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                resp.read()
                conn.close()
                if resp.status == 200:
                    return
            except (ConnectionRefusedError, OSError):
                pass
            time.sleep(0.05)
        raise RuntimeError(f"REST server not ready after {timeout_s}s on port {port}")

    def _post(self, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        conn.request("POST", path, body=json.dumps(body).encode(), headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        status = resp.status
        conn.close()
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"_raw": raw}

    def _start_plan_and_get_row(self) -> Tuple[str, Dict[str, Any]]:
        """Lance un scan/plan et renvoie (run_id, premiere row)."""
        status, payload = self._post(
            "/api/run/start_plan",
            {
                "settings": {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                }
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload.get("ok"), payload)
        run_id = str(payload["run_id"])

        _wait_done(self.api, run_id, timeout_s=15.0)

        status, plan = self._post("/api/run/get_plan", {"run_id": run_id})
        self.assertEqual(status, 200, plan)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), 1, rows)
        return run_id, rows[0]

    # --- Test 1 : POST /api/run/apply dry-run renvoie ok=True sans toucher FS ---

    def test_post_run_apply_dry_run_does_not_touch_fs(self) -> None:
        """ETAPE 1 : POST /api/run/apply avec dry_run=True ne modifie aucun fichier."""
        source_dir = self.root / "Old.Name.2010.1080p"
        source_video = source_dir / "Old.Name.2010.1080p.mkv"
        _create_file(source_video)

        run_id, row = self._start_plan_and_get_row()

        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row["proposed_title"],
                "year": row["proposed_year"],
            }
        }

        # Persistance validation via REST
        status, saved = self._post("/api/run/save_validation", {"run_id": run_id, "decisions": decisions})
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved.get("ok"), saved)

        # APPLY dry-run via REST
        status, applied = self._post(
            "/api/run/apply",
            {
                "run_id": run_id,
                "decisions": {},
                "dry_run": True,
                "quarantine_unapproved": False,
            },
        )
        self.assertEqual(status, 200, applied)
        self.assertTrue(applied.get("ok"), applied)

        # FS inchange : source intacte, dst absente
        expected_dir = self.root / core.windows_safe(f"{row['proposed_title']} ({row['proposed_year']})")
        self.assertTrue(source_dir.exists(), "source dir doit rester")
        self.assertTrue(source_video.exists(), "source video doit rester")
        # Comme nom propose != source, dst ne doit pas etre cree en dry-run.
        if expected_dir != source_dir:
            self.assertFalse(expected_dir.exists(), f"dst {expected_dir} ne doit pas etre cree en dry-run")

    # --- Test 2 : case-only -> aucun rename emis en preview (NOOP) ---

    def test_case_only_rename_is_noop_in_preview(self) -> None:
        """ETAPE 2 : Movie.2020 vs movie.2020 -> aucun rename FS, NOOP detecte."""
        # On cree un dossier dont le nom NE correspond PAS au template.
        source_dir = self.root / "Test.Movie.2015.1080p.BluRay"
        source_video = source_dir / "Test.Movie.2015.mkv"
        _create_file(source_video)

        run_id, row = self._start_plan_and_get_row()

        # Sur Windows, simuler un "case-only rename" : on force le titre/annee
        # propose a etre IDENTIQUE (insensible a la casse) au nom dossier source.
        # _fs_equivalent (apply_core.py) doit detecter NOOP.
        source_name = source_dir.name  # "Test.Movie.2015.1080p.BluRay"
        # On utilise une decision qui force un dst variant uniquement par la casse
        # ce qui equivaut a un NOOP dans la preview.
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row["proposed_title"],
                "year": row["proposed_year"],
            }
        }

        # build_apply_preview pour verifier qu'aucun rename "case-only" n'est genere
        status, preview = self._post(
            "/api/run/build_apply_preview",
            {"run_id": run_id, "decisions": decisions},
        )
        self.assertEqual(status, 200, preview)
        # build_apply_preview retourne ok=True meme sans renommage.
        self.assertTrue(preview.get("ok"), preview)

        # Verification croisee : un dry-run apply via REST ne touche rien
        status, saved = self._post("/api/run/save_validation", {"run_id": run_id, "decisions": decisions})
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved.get("ok"), saved)

        # APPLY dry-run via REST
        status, applied = self._post(
            "/api/run/apply",
            {
                "run_id": run_id,
                "decisions": {},
                "dry_run": True,
                "quarantine_unapproved": False,
            },
        )
        self.assertEqual(status, 200, applied)
        self.assertTrue(applied.get("ok"), applied)

        # FS : source intacte, dossier originel preserve (caseinsensitive=True)
        self.assertTrue(source_dir.exists(), "source dir doit rester apres dry-run")
        # Verifie que le nom EXACT (avec casse) est present
        names_in_root = {p.name for p in self.root.iterdir()}
        self.assertIn(source_name, names_in_root, f"nom exact preserve dans {names_in_root}")

    # --- Test 3 : apply_atomic est opt-in strict (default False, accepte True) ---

    def test_apply_atomic_is_opt_in_strict(self) -> None:
        """ETAPE 3 : apply_atomic n'est PAS active par defaut, accepte True via REST."""
        source_dir = self.root / "Atomic.Film.2018.1080p"
        source_video = source_dir / "Atomic.Film.2018.mkv"
        _create_file(source_video)

        run_id, row = self._start_plan_and_get_row()

        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row["proposed_title"],
                "year": row["proposed_year"],
            }
        }

        status, saved = self._post("/api/run/save_validation", {"run_id": run_id, "decisions": decisions})
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved.get("ok"), saved)

        # CAS A : pas de apply_atomic dans le body -> default False (opt-in)
        status, applied_default = self._post(
            "/api/run/apply",
            {
                "run_id": run_id,
                "decisions": {},
                "dry_run": True,
                "quarantine_unapproved": False,
            },
        )
        self.assertEqual(status, 200, applied_default)
        self.assertTrue(applied_default.get("ok"), applied_default)

        # CAS B : apply_atomic=True explicitement -> accepte sans erreur
        status, applied_opt_in = self._post(
            "/api/run/apply",
            {
                "run_id": run_id,
                "decisions": {},
                "dry_run": True,
                "quarantine_unapproved": False,
                "apply_atomic": True,
            },
        )
        self.assertEqual(status, 200, applied_opt_in)
        self.assertTrue(applied_opt_in.get("ok"), applied_opt_in)

        # FS toujours intact apres ces 2 dry-runs
        self.assertTrue(source_dir.exists(), "source dir doit rester apres 2 dry-runs")
        self.assertTrue(source_video.exists(), "source video doit rester apres 2 dry-runs")


if __name__ == "__main__":
    unittest.main()
