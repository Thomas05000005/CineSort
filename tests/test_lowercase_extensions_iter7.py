"""Guard test ITER7 — lowercase_extensions appliqué dans le pipeline reel.

Sujet : "settings.json persiste avec `lowercase_extensions=False` DOIT
preserver la casse FS source (.MKV reste .MKV) dans la preview construite
par le pipeline reel start_plan REST -> build_apply_preview".

Pourquoi cette refonte (cluster ITER7) :
- `_save_section_naming` (settings_support.py L1608-1609) persiste la cle UI.
- `build_cfg_from_settings` (settings_support.py L1066) ajoute desormais
  `lowercase_extensions=to_bool(settings.get("lowercase_extensions"), True)`.
- `apply_core` (helpers `_video_ext` et `_video_name_with_ext_case`) consomme
  `cfg.lowercase_extensions` aux call sites apply_collection_item (L1928),
  apply_tv_episode (L1996/L1998) et quarantine_row (L2146).
- `_execute_apply` (apply_support.py L1340-1367) recopie cfg pour multi-root
  et DOIT propager `lowercase_extensions` (sinon default True ecrase OFF).

Strategie :
- Monter une bibliotheque tmpdir minimale avec un dossier "collection"
  contenant 2 .MKV (upper) — declenche apply_collection_item.
- Persister `settings.json` avec `lowercase_extensions=False` puis True.
- Invoquer `api.run.start_plan(...)`, attendre fin, puis `build_apply_preview`.
- Assertion ON : dst_path contient `.mkv` (lower).
- Assertion OFF : dst_path preserve `.MKV` (upper source).

Pre-fix : ON==OFF == `.mkv` (drop silencieux) -> ECHEC test OFF.
Post-fix : ON != OFF dans le sens attendu -> PASSE.

Pattern reference : test_plan_naming_preset_resync_guard.py (cluster ITER6).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class LowercaseExtensionsPipelineGuardTests(unittest.TestCase):
    """Guard ITER7 : valide differentiel ON/OFF lowercase_extensions via REST."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_lowercase_ext_iter7_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        p_min.start()
        self.addCleanup(p_min.stop)

        # Dossier "collection" (2+ videos) declenche apply_collection_item.
        # On utilise un .MKV upper pour observer le drop silencieux.
        coll_dir = self.root / "Tears of Steel (2012)"
        _create_file(coll_dir / "Tears of Steel (2012) 1080p.mkv")
        _create_file(coll_dir / "Tears of Steel (2012) 720p.MKV")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _persist_settings(self, lowercase_extensions: bool) -> None:
        """Ecrit settings.json on-disk avec le toggle voulu."""
        settings_path = self.state_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "root": str(self.root),
                    "roots": [str(self.root)],
                    "state_dir": str(self.state_dir),
                    "library_path": str(self.root),
                    "tmdb_enabled": False,
                    "omdb_enabled": False,
                    "perceptual_enabled": False,
                    "perceptual_auto_on_scan": False,
                    "auto_recompute_quality_on_scan": False,
                    "naming_preset": "default",
                    "naming_movie_template": "{title} ({year})",
                    "naming_tv_template": "{series} ({year})",
                    "lowercase_extensions": bool(lowercase_extensions),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _run_pipeline_and_get_preview(self, lowercase_extensions: bool) -> Dict[str, Any]:
        """Lance start_plan -> attend fin -> build_apply_preview, retourne preview."""
        self._persist_settings(lowercase_extensions)
        api = CineSortApi()
        payload = {
            "library_path": str(self.root),
            "root": str(self.root),
            "roots": [str(self.root)],
            "state_dir": str(self.state_dir),
        }
        start = api.run.start_plan(payload)
        self.assertTrue(start.get("ok"), f"start_plan a echoue : {start}")
        run_id = str(start["run_id"])
        _wait_done(api, run_id, timeout_s=30.0)

        # Charger plan.jsonl pour decisions
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        plan_jsonl = run_dir / "plan.jsonl"
        self.assertTrue(plan_jsonl.exists(), f"plan.jsonl manquant: {plan_jsonl}")
        decisions: Dict[str, Dict[str, Any]] = {}
        with open(plan_jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                row_id = row.get("row_id")
                if not row_id:
                    continue
                decisions[row_id] = {
                    "ok": True,
                    "title": row.get("proposed_title"),
                    "year": row.get("proposed_year"),
                    "decision": "accepted",
                }
        self.assertGreater(len(decisions), 0, "Aucune row decidable trouvee")
        preview = api.run.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"), f"build_apply_preview a echoue : {preview}")
        return preview

    def _extract_target_op(self, preview: Dict[str, Any]) -> Dict[str, Any]:
        """Recupere l'op MOVE_FILE qui touche le fichier 720p.MKV (collection)."""
        for film in preview.get("films", []) or []:
            for op in film.get("ops", []) or []:
                src = str(op.get("src_path") or "")
                if "720p.MKV" in src or "720p.mkv" in src:
                    return op
        self.fail(f"Aucune op MOVE_FILE pour Tears 720p MKV. Preview: {preview}")
        return {}  # unreachable

    def test_lower_on_produces_lowercase_ext(self) -> None:
        """ON : `.MKV` source -> `.mkv` cible (normalisation)."""
        preview = self._run_pipeline_and_get_preview(lowercase_extensions=True)
        op = self._extract_target_op(preview)
        dst = str(op.get("dst_path") or "")
        ext = os.path.splitext(dst)[1]
        self.assertEqual(
            ext,
            ".mkv",
            f"REGRESSION ITER7 ON : lowercase_extensions=True DOIT donner "
            f"une extension cible minuscule. Vu dst={dst!r}, ext={ext!r}.",
        )

    def test_lower_off_preserves_uppercase_ext(self) -> None:
        """OFF : `.MKV` source preserve sa casse (`.MKV` cible)."""
        preview = self._run_pipeline_and_get_preview(lowercase_extensions=False)
        op = self._extract_target_op(preview)
        dst = str(op.get("dst_path") or "")
        ext = os.path.splitext(dst)[1]
        self.assertEqual(
            ext,
            ".MKV",
            f"REGRESSION ITER7 OFF : lowercase_extensions=False DOIT preserver "
            f"la casse FS source (.MKV). Vu dst={dst!r}, ext={ext!r}. "
            "Cause probable : _execute_apply (apply_support.py L1340-1367) "
            "recopie cfg sans propager lowercase_extensions, le default True "
            "ecrase le toggle OFF.",
        )

    def test_on_off_differentiel_strict(self) -> None:
        """Gate principal : ON != OFF dans le sens attendu (ON minuscule, OFF preserve)."""
        preview_on = self._run_pipeline_and_get_preview(lowercase_extensions=True)
        op_on = self._extract_target_op(preview_on)
        dst_on = str(op_on.get("dst_path") or "")
        ext_on = os.path.splitext(dst_on)[1]

        preview_off = self._run_pipeline_and_get_preview(lowercase_extensions=False)
        op_off = self._extract_target_op(preview_off)
        dst_off = str(op_off.get("dst_path") or "")
        ext_off = os.path.splitext(dst_off)[1]

        self.assertNotEqual(
            ext_on,
            ext_off,
            f"REGRESSION ITER7 GATE : ON et OFF produisent la meme extension "
            f"cible ({ext_on!r}). Le toggle UI 'Extensions en minuscule' "
            f"est silencieusement ignore dans le pipeline reel.",
        )
        self.assertEqual(ext_on, ".mkv", f"ON doit donner .mkv (vu {ext_on!r})")
        self.assertEqual(ext_off, ".MKV", f"OFF doit preserver .MKV (vu {ext_off!r})")


if __name__ == "__main__":
    unittest.main()
