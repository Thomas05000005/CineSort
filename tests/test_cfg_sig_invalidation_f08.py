"""F08 — cfg_signature_for_incremental doit couvrir TOUS les reglages qui
changent la sortie du plan.

Avant le correctif, `enable_tv_detection`, `min_video_bytes`,
`naming_movie_template` et les langues de sous-titres attendues n'entraient pas
dans la signature : sur une install `incremental_scan_enabled=True`, les
modifier ne changeait NI cfg_sig NI folder_signature -> le rescan rejouait
l'ancien resultat (0 row TV, flags sous-titres figes) jusqu'a modification
physique des dossiers.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.app.plan_support_core import cfg_signature_for_incremental
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir


class CfgSignatureFieldsTests(unittest.TestCase):
    """La signature doit BOUGER pour chacun des reglages oublies."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_cfgsig_f08_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _sig(self, **kwargs) -> str:
        subs = kwargs.pop("subtitle_expected_languages", None)
        api_key = kwargs.pop("tmdb_api_key", None)
        cfg = core.Config(root=self.root, **kwargs).normalized()
        return cfg_signature_for_incremental(cfg, subtitle_expected_languages=subs, tmdb_api_key=api_key)

    def test_cfg_sig_varie_avec_enable_tv_detection(self) -> None:
        self.assertNotEqual(self._sig(), self._sig(enable_tv_detection=True))

    def test_cfg_sig_varie_avec_min_video_bytes(self) -> None:
        self.assertNotEqual(self._sig(), self._sig(min_video_bytes=1))
        self.assertNotEqual(self._sig(min_video_bytes=1), self._sig(min_video_bytes=10_000_000))

    def test_cfg_sig_varie_avec_naming_movie_template(self) -> None:
        self.assertNotEqual(
            self._sig(),
            self._sig(naming_movie_template="{title} ({year}) {edition-tag}"),
        )

    def test_cfg_sig_varie_avec_subtitle_expected_languages(self) -> None:
        self.assertNotEqual(
            self._sig(subtitle_expected_languages=["fr"]),
            self._sig(subtitle_expected_languages=["fr", "en"]),
        )

    def test_cfg_sig_distingue_none_et_liste_vide(self) -> None:
        """None = detection desactivee ; [] = activee sans langue attendue."""
        self.assertNotEqual(
            self._sig(subtitle_expected_languages=None),
            self._sig(subtitle_expected_languages=[]),
        )

    def test_cfg_sig_varie_avec_le_seuil_min_video_bytes_EFFECTIF(self) -> None:
        """Revue adverse : `cfg.min_video_bytes` n'est jamais cable par les reglages.

        Il vaut toujours None et le seuil reellement applique au scan est la
        globale de module `core.MIN_VIDEO_BYTES`. Signer le champ nu rendait donc
        la cle inerte : c'est le seuil EFFECTIF qui doit entrer dans la signature.
        """
        avant = self._sig()
        with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
            apres = self._sig()
        self.assertNotEqual(avant, apres)

    def test_cfg_sig_varie_avec_la_cle_tmdb(self) -> None:
        """Revue adverse : `enable_tmdb` reste True avec une cle VIDE.

        Sans empreinte de la cle, coller sa cle TMDb apres un premier scan ne
        changeait NI cfg_sig NI folder_signature -> aucun enrichissement TMDb au
        rescan, jusqu'a modification physique de chaque dossier.
        """
        sans = self._sig(tmdb_api_key=None)
        vide = self._sig(tmdb_api_key="   ")
        posee = self._sig(tmdb_api_key="0123456789abcdef")
        autre = self._sig(tmdb_api_key="fedcba9876543210")

        self.assertEqual(sans, vide, "cle vide == pas de client TMDb construit")
        self.assertNotEqual(sans, posee, "poser une cle doit invalider les caches")
        self.assertNotEqual(posee, autre, "changer de cle doit invalider les caches")

    def test_la_cle_tmdb_n_apparait_jamais_en_clair(self) -> None:
        """La signature est un hash, mais on verifie l'absence de fuite en amont."""
        secret = "SECRET-TMDB-KEY-0123456789"
        self.assertNotIn(secret.lower(), self._sig(tmdb_api_key=secret).lower())

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_cfg_sig_stable_et_sensible_aux_champs_deja_couverts(self) -> None:
        self.assertEqual(self._sig(), self._sig())
        self.assertNotEqual(self._sig(), self._sig(skip_tv_like=False))
        self.assertNotEqual(self._sig(), self._sig(enable_tmdb=False))

    def test_appel_sans_kwarg_reste_supporte(self) -> None:
        """Retro-compat : le kwarg est optionnel (re-export plan_support)."""
        cfg = core.Config(root=self.root).normalized()
        self.assertEqual(
            cfg_signature_for_incremental(cfg),
            cfg_signature_for_incremental(cfg, subtitle_expected_languages=None),
        )


class _TmdbSpy:
    """Client TMDb minimal : ce que `plan_library` consomme + `api_key`."""

    def __init__(self, api_key: str = "0123456789abcdef") -> None:
        self.api_key = api_key
        self.calls = []

    def search_movie(self, *, query, year=None, language=None, max_results=8):
        self.calls.append((query, year))
        return []


class TmdbKeyRescanTests(unittest.TestCase):
    """E2E : coller sa cle TMDb apres un premier scan doit reprendre effet.

    C'est le chemin nominal documente par le WARN 'TMDb active mais cle vide' :
    l'utilisateur scanne, voit le message, colle sa cle, rescanne.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_cfgsig_f08_tmdb_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

        folder = self.root / "Inception (2010)"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Inception (2010).mkv").write_bytes(b"a" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, run_id: str, *, tmdb):
        cfg = core.Config(root=self.root, enable_tmdb=True, incremental_scan_enabled=True)
        return plan_support.plan_library(
            cfg,
            tmdb=tmdb,
            log=lambda _lvl, _msg: None,
            progress=lambda _i, _t, _c: None,
            scan_index=self.store.scan,
            run_id=run_id,
        )

    def test_cle_collee_apres_le_1er_scan_reprend_effet(self) -> None:
        rows1, _stats1 = self._scan("scan1", tmdb=None)
        self.assertEqual(len(rows1), 1)

        spy = _TmdbSpy()
        _rows2, stats2 = self._scan("scan2", tmdb=spy)
        self.assertEqual(
            int(stats2.incremental_cache_hits or 0),
            0,
            "cfg_sig n'a pas bouge : le cache dossier a rejoue le plan SANS TMDb",
        )
        self.assertTrue(spy.calls, "TMDb n'a jamais ete interroge malgre la cle posee")

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_rescan_avec_la_meme_cle_reste_un_hit_cache(self) -> None:
        self._scan("scan1", tmdb=_TmdbSpy())
        _rows2, stats2 = self._scan("scan2", tmdb=_TmdbSpy())
        self.assertGreaterEqual(int(stats2.incremental_cache_hits or 0), 1)


class TvDetectionRescanTests(unittest.TestCase):
    """E2E : activer la detection TV doit reprendre effet au rescan."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_cfgsig_f08_e2e_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

        self.folder = self.root / "Breaking Bad S01"
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "Breaking.Bad.S01E01.mkv").write_bytes(b"a" * 4096)
        (self.folder / "Breaking.Bad.S01E02.mkv").write_bytes(b"b" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, run_id: str, *, enable_tv_detection: bool):
        cfg = core.Config(
            root=self.root,
            enable_tmdb=False,
            incremental_scan_enabled=True,
            enable_tv_detection=enable_tv_detection,
        )
        return plan_support.plan_library(
            cfg,
            tmdb=None,
            log=lambda _lvl, _msg: None,
            progress=lambda _i, _t, _c: None,
            scan_index=self.store.scan,
            run_id=run_id,
        )

    def test_activation_tv_detection_reprend_effet_sur_rescan(self) -> None:
        rows1, stats1 = self._scan("scan1", enable_tv_detection=False)
        self.assertEqual(len(rows1), 0)
        self.assertEqual(int(stats1.skipped_tv_like or 0), 1)

        rows2, stats2 = self._scan("scan2", enable_tv_detection=True)
        self.assertEqual(
            len(rows2),
            2,
            "cfg_sig n'a pas bouge : le cache dossier a rejoue '0 row, serie ignoree'",
        )
        self.assertEqual({r.kind for r in rows2}, {"tv_episode"})
        self.assertEqual(
            int(stats2.incremental_cache_hits or 0),
            0,
            "un HIT dossier prouverait que le cache n'a pas ete invalide",
        )

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_rescan_a_reglages_identiques_reste_un_hit_cache(self) -> None:
        rows1, _ = self._scan("scan1", enable_tv_detection=True)
        self.assertEqual(len(rows1), 2)
        rows2, stats2 = self._scan("scan2", enable_tv_detection=True)
        self.assertEqual(len(rows2), 2)
        self.assertGreaterEqual(int(stats2.incremental_cache_hits or 0), 1)


if __name__ == "__main__":
    unittest.main()
