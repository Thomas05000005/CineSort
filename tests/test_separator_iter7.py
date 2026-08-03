"""Guard test ITER7 — separator approvisionne dans le pipeline reel (opt-in {sep}).

Sujet : "settings.json persiste avec `separator=<x>` DOIT alimenter la variable
de template `{sep}` consommee par les sites apply_core via build_naming_context,
avec STOP_FORK CUSTOM TEMPLATE preserve (templates existants invariants)".

Pourquoi cette refonte (cluster ITER7, voir BILAN_ITER7_2026-06-08.md section 4) :
- `_save_section_naming` (settings_support.py L1611-1613) persiste la cle UI.
- `build_cfg_from_settings` (settings_support.py L1066+) ajoute desormais
  `separator=...` (coerce-and-default {".", " ", "_", "-"}).
- `domain/naming.build_naming_context` accepte un kwarg `separator` qui peuple
  `ctx["sep"]`, ajoute a `_KNOWN_VARS` et `PREVIEW_MOCK_CONTEXT`.
- `apply_core` (3 sites apply_single L1699-1707, apply_collection_item L1910-1916,
  apply_tv_episode L2018-2030) passe `separator=getattr(cfg, "separator", " ")`.
- `_execute_apply` (apply_support.py) propage `separator=cfg.separator` dans la
  recopie multi-root (lecon ITER7 G.e re-appliquee).

Strategie de mesure differentiel REST :

1. **Preset default `{title} ({year})` — INVARIANCE attendue (STOP_FORK)** :
   le template ne reference pas `{sep}`, donc `separator="_"` et `separator=" "`
   produisent EXACTEMENT le meme dst_path. Ce comportement EST le fix : changer
   le selecteur UI ne casse PAS les templates utilisateur existants.

2. **Template opt-in `{title}{sep}({year})` — DIFFERENTIEL attendu** :
   le template reference `{sep}`, donc `separator="_"` produit `Title_(Year)`
   et `separator=" "` produit `Title (Year)`. C'est le seul chemin pour faire
   bouger la sortie sans fork semantique.

Pattern reference : test_lowercase_extensions_iter7.py.
"""

from __future__ import annotations

import json
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


class SeparatorPipelineGuardTests(unittest.TestCase):
    """Guard ITER7 separator : invariance preset default + differentiel template opt-in."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_separator_iter7_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        p_min.start()
        self.addCleanup(p_min.stop)

        # Dossier "collection" (multi-videos) declenche apply_collection_item.
        # Le rendu du nom de SOUS-dossier passe par format_movie_folder.
        coll_dir = self.root / "the.matrix.1999"
        _create_file(coll_dir / "the.matrix.1999.1080p.mkv")
        _create_file(coll_dir / "the.matrix.1999.720p.mkv")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _persist_settings(self, *, separator: str, naming_movie_template: str) -> None:
        """Ecrit settings.json on-disk avec separator + template voulus."""
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
                    "naming_movie_template": naming_movie_template,
                    "naming_tv_template": "{series} ({year})",
                    "lowercase_extensions": True,
                    "separator": separator,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _run_pipeline_and_get_preview(self, *, separator: str, naming_movie_template: str) -> Dict[str, Any]:
        """Lance start_plan -> attend fin -> build_apply_preview, retourne preview."""
        self._persist_settings(separator=separator, naming_movie_template=naming_movie_template)
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

    def _extract_target_dst(self, preview: Dict[str, Any]) -> str:
        """Recupere le dst_path d'une MOVE_FILE sur le film 'the.matrix.1999'."""
        for film in preview.get("films", []) or []:
            for op in film.get("ops", []) or []:
                src = str(op.get("src_path") or "").lower()
                dst = str(op.get("dst_path") or "")
                if "matrix" in src and dst:
                    return dst
        self.fail(f"Aucune op MOVE_FILE pour the.matrix.1999. Preview: {preview}")
        return ""  # unreachable

    def test_preset_default_invariance_under_vs_space(self) -> None:
        """STOP_FORK CUSTOM TEMPLATE : preset default invariant entre _ et espace.

        Le template `{title} ({year})` ne reference PAS `{sep}` donc le selecteur
        UI n'a aucun chemin d'execution vers la sortie. C'est le contrat opt-in
        choisi en ITER7 section 4 pour preserver MEMOIRE "FORK SEMANTIQUE CUSTOM
        TEMPLATE = STOP REMONTER".
        """
        preview_under = self._run_pipeline_and_get_preview(separator="_", naming_movie_template="{title} ({year})")
        dst_under = self._extract_target_dst(preview_under)

        preview_space = self._run_pipeline_and_get_preview(separator=" ", naming_movie_template="{title} ({year})")
        dst_space = self._extract_target_dst(preview_space)

        self.assertEqual(
            dst_under,
            dst_space,
            "INVARIANCE PRESET DEFAULT VIOLEE : changer le selecteur UI "
            "separator a modifie la sortie d'un template qui ne reference "
            "pas {sep}. STOP_FORK CUSTOM TEMPLATE non preserve. "
            f"under={dst_under!r} vs space={dst_space!r}.",
        )

    def test_template_optin_sep_differentiel_under_vs_space(self) -> None:
        """Differentiel separator effectif via template opt-in `{title}{sep}({year})`.

        C'est le seul chemin par lequel le selecteur UI peut bouger la sortie
        sans rupture des templates existants. ON (`_`) != OFF (` `) dans le
        sens attendu : `_` produit `..._(yyyy)`, espace produit `... (yyyy)`.
        """
        tpl = "{title}{sep}({year})"
        preview_under = self._run_pipeline_and_get_preview(separator="_", naming_movie_template=tpl)
        dst_under = self._extract_target_dst(preview_under)

        preview_space = self._run_pipeline_and_get_preview(separator=" ", naming_movie_template=tpl)
        dst_space = self._extract_target_dst(preview_space)

        self.assertNotEqual(
            dst_under,
            dst_space,
            "REGRESSION DIFFERENTIEL OPT-IN : separator='_' et separator=' ' "
            "produisent le meme dst_path avec template `{title}{sep}({year})`. "
            "Le selecteur UI n'a pas d'effet sur la sortie via {sep}. "
            f"under={dst_under!r} space={dst_space!r}.",
        )

        # Differentiel directionnel : _ doit produire "_(", espace doit produire " ("
        self.assertIn(
            "_(",
            dst_under,
            f"separator='_' devait produire '_(YEAR)' (vu dst={dst_under!r})",
        )
        self.assertIn(
            " (",
            dst_space,
            f"separator=' ' devait produire ' (YEAR)' (vu dst={dst_space!r})",
        )


if __name__ == "__main__":
    unittest.main()
