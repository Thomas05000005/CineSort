"""Guard test cluster settings iter6 — naming_preset resync au call site.

Sujet : "settings.json persiste avec `naming_preset='plex'` mais sans
resync des templates (cas edit hors UI / migration) DOIT donner un
`cfg.naming_movie_template` aligne sur le preset Plex dans le pipeline
reel start_plan REST".

Pourquoi cette refonte (cluster ITER6) :
- `_apply_naming_preset` (settings_support.py L1239-1261) reecrit
  `naming_movie_template` / `naming_tv_template` UNIQUEMENT au save.
- Si `settings.json` est edite directement OU si une migration insere
  `naming_preset='plex'` SANS toucher aux templates, l'utilisateur s'attend
  a un renommage de type Plex (`{title} ({year}) {tmdb_tag}`), mais
  `build_cfg_from_settings` lisait les anciens templates persistes
  -> drop silencieux du reglage utilisateur.

Strategie :
- Monter une bibliotheque tmpdir minimale avec `Inception.2010.1080p.mkv`.
- Persister un `settings.json` on-disk avec `naming_preset='plex'` mais
  `naming_movie_template='{title} ({year})'` (cas "hors save").
- Patcher `cinesort.ui.api.settings_support.build_cfg_from_settings` pour
  capturer le `cfg` qui sort apres lecture des settings dans le pipeline
  reel (run_flow_support).
- Invoquer `api.run.start_plan(...)`. Attendre la fin du run.
- Assertion : `cfg_captured.naming_movie_template` DOIT contenir `tmdb_tag`
  (template Plex). Pre-fix : `{title} ({year})` (drop silencieux) -> ECHEC.
  Post-fix : `{title} ({year}) {tmdb_tag}` (resync au call site) -> PASSE.

Pattern reference : 7df3af3e + a37852aa (ii.b durcissement + tmdb hydration).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, List
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.settings_support import build_cfg_from_settings as _real_build_cfg
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class NamingPresetResyncCallSiteGuardTests(unittest.TestCase):
    """Guard ITER6 cluster settings : valide resync naming_preset au call site."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_naming_preset_guard_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        p_min.start()
        self.addCleanup(p_min.stop)

        _create_file(self.root / "Inception.2010.1080p" / "Inception.2010.1080p.mkv")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run_dir(self, run_id: str) -> Path:
        return self.state_dir / "runs" / f"tri_films_{run_id}"

    def _persist_settings(self, naming_preset: str, naming_movie_template: str) -> None:
        """Ecrit settings.json on-disk SANS passer par save_settings.

        Simule edit utilisateur hors UI ou insertion par migration.
        """
        settings_path = self.state_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                    "naming_preset": naming_preset,
                    "naming_movie_template": naming_movie_template,
                    "naming_tv_template": "{series} ({year})",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _capture_cfg_via_pipeline(self, naming_preset: str, naming_movie_template: str) -> Any:
        """Lance start_plan et capture le `cfg` construit par build_cfg_from_settings.

        Retourne le dernier `cfg` produit (le pipeline appelle build_cfg
        depuis run_flow_support / scan / replan ; on prend le dernier).
        """
        self._persist_settings(naming_preset, naming_movie_template)
        api = CineSortApi()
        captured: List[Any] = []

        def _capture(*args: Any, **kwargs: Any) -> Any:
            cfg = _real_build_cfg(*args, **kwargs)
            captured.append(cfg)
            return cfg

        # Patcher AU NIVEAU MODULE cinesort_api ou l'alias
        # `_build_cfg_from_settings_payload` est importe en top-level (le
        # pipeline run_flow_support utilise api._build_cfg_from_settings ->
        # cet alias). C'est le call site reel du run REST.
        with mock.patch(
            "cinesort.ui.api.cinesort_api._build_cfg_from_settings_payload",
            side_effect=_capture,
        ):
            payload = {
                "library_path": str(self.root),
                "root": str(self.root),
                "state_dir": str(self.state_dir),
            }
            start = api.run.start_plan(payload)
            self.assertTrue(start.get("ok"), f"start_plan a echoue : {start}")
            run_id = str(start["run_id"])
            _wait_done(api, run_id, timeout_s=20.0)

        self.assertGreater(
            len(captured),
            0,
            "build_cfg_from_settings n'a JAMAIS ete appele dans le pipeline start_plan : le test ne mesure rien.",
        )
        return captured[-1]

    def test_preset_plex_hors_save_resync_au_call_site(self) -> None:
        """settings.json contient preset=plex sans resync templates.

        Pre-fix : build_cfg lit `{title} ({year})` (drop silencieux).
        Post-fix : resync au call site -> `{title} ({year}) {tmdb_tag}`.
        """
        cfg = self._capture_cfg_via_pipeline(
            naming_preset="plex",
            naming_movie_template="{title} ({year})",
        )
        self.assertIn(
            "tmdb_tag",
            cfg.naming_movie_template,
            f"REGRESSION cluster iter6 : naming_preset='plex' DOIT etre resync "
            f"au call site (template Plex='{{title}} ({{year}}) {{tmdb_tag}}'). "
            f"Vu : {cfg.naming_movie_template!r}. "
            "Cf settings_support.build_cfg_from_settings : si preset != 'custom', "
            "resynchroniser les templates depuis PRESETS pour absorber le cas "
            "edit hors UI / migration.",
        )

    def test_preset_jellyfin_hors_save_resync_au_call_site(self) -> None:
        """Meme principe pour preset=jellyfin (`[{resolution}]`)."""
        cfg = self._capture_cfg_via_pipeline(
            naming_preset="jellyfin",
            naming_movie_template="{title} ({year})",
        )
        self.assertIn(
            "resolution",
            cfg.naming_movie_template,
            f"naming_preset='jellyfin' DOIT etre resync au call site. Vu : {cfg.naming_movie_template!r}",
        )

    def test_preset_custom_preserve_template_utilisateur(self) -> None:
        """Garde-fou negatif : preset=custom NE DOIT PAS ecraser le template.

        Verifie que le fix ne casse pas le contrat custom : si l'utilisateur
        a choisi 'custom' avec un template personnalise, on doit le garder
        tel quel (pas de fallback sur un preset).
        """
        cfg = self._capture_cfg_via_pipeline(
            naming_preset="custom",
            naming_movie_template="{title} [{resolution}]",
        )
        self.assertEqual(
            cfg.naming_movie_template,
            "{title} [{resolution}]",
            f"naming_preset='custom' DOIT preserver le template utilisateur. Vu : {cfg.naming_movie_template!r}",
        )

    def test_preset_default_inchange(self) -> None:
        """Garde-fou : preset=default avec template default reste default."""
        cfg = self._capture_cfg_via_pipeline(
            naming_preset="default",
            naming_movie_template="{title} ({year})",
        )
        self.assertEqual(
            cfg.naming_movie_template,
            "{title} ({year})",
            f"naming_preset='default' DOIT donner le template par defaut. Vu : {cfg.naming_movie_template!r}",
        )


if __name__ == "__main__":
    unittest.main()
