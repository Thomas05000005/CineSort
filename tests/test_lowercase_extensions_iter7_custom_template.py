"""GATE Template custom ITER7 — fork semantique lowercase_extensions.

Objectif : confirmer que le fix `lowercase_extensions` (helpers
`_video_ext` + `_video_name_with_ext_case` dans `apply_core`) n'introduit
PAS de fork semantique sur les templates utilisateur custom.

Cluster sujet :
- Le fix agit UNIQUEMENT sur `video.suffix` (extension du fichier).
- Le fix ne touche JAMAIS au rendu du template
  (`format_movie_folder(cfg.naming_movie_template, ctx)`).
- Donc un template custom EXISTANT qui ne contient pas l'extension dans
  son corps doit produire la MEME sortie qu'avant le fix : seul l'extension
  collee apres rendering peut changer de casse.

Strategie GATE :
- Template custom `"{title}__{year}"` (separateur double underscore).
- Source .MKV upper (Tears 720p MKV) -> declenche `apply_collection_item`.
- Run ON et OFF.
- Assertion 1 : le DOSSIER cible (rendu du template) est IDENTIQUE entre ON
  et OFF (pas de fork sur template custom).
- Assertion 2 : seule l'EXTENSION du fichier final differe (`.mkv` vs `.MKV`).
- Assertion 3 : le DOSSIER contient bien le separateur custom `__` (preuve
  que le template custom est bien rendu, ce n'est pas le default qui
  s'applique en silence).

Si fork detecte (Assertion 1 echoue), STOP REMONTER conformement MEMOIRE
"FORK SEMANTIQUE CUSTOM TEMPLATE = STOP REMONTER".
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


class CustomTemplateForkGuardTests(unittest.TestCase):
    """GATE Template custom : ON vs OFF -> meme rendu template, ext differente."""

    CUSTOM_TEMPLATE = "{title}__{year}"  # double underscore = signature distincte

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_custom_template_iter7_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        p_min.start()
        self.addCleanup(p_min.stop)

        coll_dir = self.root / "Tears of Steel (2012)"
        _create_file(coll_dir / "Tears of Steel (2012) 1080p.mkv")
        _create_file(coll_dir / "Tears of Steel (2012) 720p.MKV")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _persist_settings(self, lowercase_extensions: bool) -> None:
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
                    "naming_preset": "custom",
                    "naming_movie_template": self.CUSTOM_TEMPLATE,
                    "naming_tv_template": "{series} ({year})",
                    "lowercase_extensions": bool(lowercase_extensions),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _run_pipeline_and_get_preview(self, lowercase_extensions: bool) -> Dict[str, Any]:
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
        for film in preview.get("films", []) or []:
            for op in film.get("ops", []) or []:
                src = str(op.get("src_path") or "")
                if "720p.MKV" in src or "720p.mkv" in src:
                    return op
        self.fail(f"Aucune op MOVE_FILE pour Tears 720p MKV. Preview: {preview}")
        return {}  # unreachable

    def test_custom_template_no_fork_between_on_and_off(self) -> None:
        """GATE : DOSSIER rendu identique ON/OFF, seule ext differe."""
        preview_on = self._run_pipeline_and_get_preview(lowercase_extensions=True)
        op_on = self._extract_target_op(preview_on)
        dst_on = str(op_on.get("dst_path") or "")
        dir_on = os.path.dirname(dst_on)
        ext_on = os.path.splitext(dst_on)[1]

        preview_off = self._run_pipeline_and_get_preview(lowercase_extensions=False)
        op_off = self._extract_target_op(preview_off)
        dst_off = str(op_off.get("dst_path") or "")
        dir_off = os.path.dirname(dst_off)
        ext_off = os.path.splitext(dst_off)[1]

        # 1) Dossier cible (rendu du template custom) IDENTIQUE entre ON et OFF
        self.assertEqual(
            dir_on,
            dir_off,
            f"FORK SEMANTIQUE DETECTE : le rendu du template custom "
            f"{self.CUSTOM_TEMPLATE!r} differe entre ON et OFF. "
            f"ON dir={dir_on!r} OFF dir={dir_off!r}. STOP REMONTER.",
        )

        # 2) L'extension differe dans le sens attendu
        self.assertEqual(ext_on, ".mkv", f"ON doit donner .mkv (vu {ext_on!r})")
        self.assertEqual(ext_off, ".MKV", f"OFF doit preserver .MKV (vu {ext_off!r})")

        # 3) Le DOSSIER (rendu template custom) contient bien le separateur __
        #    Preuve que le template custom est applique, pas le default silencieux
        self.assertIn(
            "__",
            dir_on,
            f"Le template custom {self.CUSTOM_TEMPLATE!r} ne semble pas "
            f"applique. dir_on={dir_on!r}. Soit le preset 'custom' n'est pas "
            f"lu, soit le default a ete substitue en silence.",
        )
        self.assertIn(
            "__",
            dir_off,
            f"Le template custom {self.CUSTOM_TEMPLATE!r} ne semble pas applique. dir_off={dir_off!r}.",
        )


if __name__ == "__main__":
    unittest.main()
