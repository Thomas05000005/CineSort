"""F26 — un rescan 100% servi par le cache DOSSIER ne doit pas vider le cache ROW.

`ctx.video_paths_seen` n'etait alimente que par le chemin MISS
(_classify_and_plan_folder), alors que `ctx.folders_seen_for_prune` l'etait
inconditionnellement. Sur un rescan sans changement (tous les dossiers en HIT),
Phase 3 appelait donc `prune_incremental_row_cache(keep_video_paths=[])`, ce que
le repository traduit par un DELETE de TOUT le cache row du root
(repositories/scan.py:343-348) : le cache row v2 etait structurellement mort des
le 2e scan.
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


class RowCachePruneOnFolderHitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_rowcache_f26_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

        self.folder_a = self.root / "Film A (2020)"
        self.folder_b = self.root / "Film B (2021)"
        self.folder_a.mkdir(parents=True, exist_ok=True)
        self.folder_b.mkdir(parents=True, exist_ok=True)
        self.video_a = self.folder_a / "Film A (2020).mkv"
        self.video_b = self.folder_b / "Film B (2021).mkv"
        self.video_a.write_bytes(b"a" * 4096)
        self.video_b.write_bytes(b"b" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> "core.Config":
        return core.Config(root=self.root, enable_tmdb=False, incremental_scan_enabled=True)

    def _scan(self, run_id: str):
        return plan_support.plan_library(
            self._cfg(),
            tmdb=None,
            log=lambda _lvl, _msg: None,
            progress=lambda _i, _t, _c: None,
            scan_index=self.store.scan,
            run_id=run_id,
        )

    def _row_cache_entry(self, video: Path):
        return self.store.scan.get_incremental_row_cache(
            root_path=str(self.root),
            video_path=str(video),
            cfg_sig=cfg_signature_for_incremental(self._cfg().normalized()),
        )

    def test_rescan_100pct_cache_ne_vide_pas_le_cache_row(self) -> None:
        rows1, _stats1 = self._scan("scan1")
        self.assertEqual(len(rows1), 2)
        self.assertIsNotNone(self._row_cache_entry(self.video_a))
        self.assertIsNotNone(self._row_cache_entry(self.video_b))

        _rows2, stats2 = self._scan("scan2")
        self.assertEqual(
            int(stats2.incremental_cache_hits or 0),
            2,
            "le test doit passer par des HITs dossier, sinon il ne prouve rien",
        )
        self.assertIsNotNone(
            self._row_cache_entry(self.video_a),
            "cache row vide par le prune malgre un rescan sans changement",
        )
        self.assertIsNotNone(self._row_cache_entry(self.video_b))

    def test_cache_row_sert_apres_ajout_dun_sidecar(self) -> None:
        self._scan("scan1")
        self._scan("scan2")
        # Un .srt change folder_signature (miss dossier) mais PAS la cle du
        # cache row (taille/mtime/hash video + nfo_sig + kind + cfg_sig).
        (self.folder_a / "Film A (2020).fr.srt").write_text("", encoding="utf-8")

        _rows3, stats3 = self._scan("scan3")
        self.assertGreaterEqual(
            int(getattr(stats3, "incremental_cache_row_hits", 0) or 0),
            1,
            "le cache row n'a servi a rien : pipeline NFO/TMDb rejoue inutilement",
        )

    def test_prune_ne_wipe_pas_quand_des_dossiers_ont_ete_vus(self) -> None:
        self._scan("scan1")

        captured = {}
        original = self.store.scan.prune_incremental_row_cache

        def _spy(*, root_path: str, keep_video_paths):
            captured["keep"] = list(keep_video_paths or [])
            return original(root_path=root_path, keep_video_paths=keep_video_paths)

        self.store.scan.prune_incremental_row_cache = _spy
        try:
            self._scan("scan2")
        finally:
            self.store.scan.prune_incremental_row_cache = original

        self.assertTrue(
            captured.get("keep"),
            "prune appele avec keep_video_paths vide = DELETE total du cache row",
        )
        self.assertEqual(sorted(captured["keep"]), sorted([str(self.video_a), str(self.video_b)]))

    def test_video_disparue_est_bien_purgee_du_cache_row(self) -> None:
        """Le prune doit continuer a nettoyer les videos reellement supprimees."""
        self._scan("scan1")
        self.assertIsNotNone(self._row_cache_entry(self.video_b))

        self.video_b.unlink()
        self._scan("scan2")
        self.assertIsNone(
            self._row_cache_entry(self.video_b),
            "l'entree de cache d'une video supprimee doit disparaitre",
        )
        self.assertIsNotNone(self._row_cache_entry(self.video_a))

    def test_root_vide_de_films_purge_quand_meme_le_cache_row(self) -> None:
        """Revue adverse : le filet initial etait BINAIRE.

        Des qu'un dossier candidat avait ete vu sans qu'aucune video ne soit
        retenue, le prune etait saute — y compris quand les videos avaient
        REELLEMENT disparu. Les entrees du root n'etaient alors plus jamais
        purgees tant que le root restait vide de films.
        """
        self._scan("scan1")
        self.assertIsNotNone(self._row_cache_entry(self.video_a))
        self.assertIsNotNone(self._row_cache_entry(self.video_b))

        self.video_a.unlink()
        self.video_b.unlink()
        # Les dossiers restent candidats (ils ne sont pas vides).
        (self.folder_a / "poster.jpg").write_bytes(b"\x00")
        (self.folder_b / "poster.jpg").write_bytes(b"\x00")

        rows2, _stats2 = self._scan("scan2")
        self.assertEqual(rows2, [])
        self.assertIsNone(
            self._row_cache_entry(self.video_a),
            "cache row d'une video supprimee jamais purge (croissance non bornee)",
        )
        self.assertIsNone(self._row_cache_entry(self.video_b))

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_dossier_illisible_ne_wipe_pas_le_cache_row(self) -> None:
        """Le seul cas ou « 0 video » n'est pas une observation fiable.

        NAS decroche / permissions : le scan ne voit aucune video alors que la
        bibliotheque est intacte. Un DELETE total du cache row serait une purge a
        tort, coutant un scan a froid complet au retour du partage.
        """
        self._scan("scan1")

        # Sans changement disque le cache DOSSIER hit et iter_videos n'est jamais
        # appele : on force le miss pour exercer reellement le garde.
        (self.folder_a / "poster.jpg").write_bytes(b"\x00")
        (self.folder_b / "poster.jpg").write_bytes(b"\x00")

        def _unreadable(cfg, folder, *, min_video_bytes=None, stats=None):
            core._stats_add_ignore(stats, "ignore_scandir_error")
            return []

        with mock.patch.object(core, "iter_videos", _unreadable):
            rows2, _stats2 = self._scan("scan2")

        self.assertEqual(rows2, [])
        self.assertIsNotNone(
            self._row_cache_entry(self.video_a),
            "cache row purge alors que le scan n'a rien pu LIRE",
        )
        self.assertIsNotNone(self._row_cache_entry(self.video_b))

    def test_rescan_sans_changement_rend_les_memes_rows(self) -> None:
        rows1, _ = self._scan("scan1")
        rows2, _ = self._scan("scan2")
        self.assertEqual(sorted(r.row_id for r in rows1), sorted(r.row_id for r in rows2))
        self.assertEqual(len(rows2), 2)


if __name__ == "__main__":
    unittest.main()
