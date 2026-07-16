"""Non-regression [HIGH-20 / relecture adversaire] : le fix row_id doit ATTEINDRE
les bibliotheques existantes.

Le passage du row_id a blake2b/64 bits (_compute_row_id) est un NO-OP pour toute
install avec `incremental_scan_enabled=True` tant que les caches persistants ne
sont pas invalides : ils rejouent des PlanRow COMPLETES (row_id inclus) sans
jamais rappeler _compute_row_id, et aucun de leurs checks de validite ne porte
sur le row_id.

  1. incremental_row_cache (par video)   -> _plan_item : `return [cached_row]`
  2. incremental_scan_cache (par dossier) -> _try_apply_folder_cache

Seul levier d'invalidation : `cfg_sig`, qui embarque `_PLAN_CACHE_VERSION` et est
dans la cle de LECTURE des deux caches (WHERE ... AND cfg_sig=?). Ces tests
seedent les caches comme le ferait le code PRE-fix (version 4 + row_id legacy 32
bits), relancent un scan incremental, et exigent des row_id 64 bits.

ECHOUENT tant que _PLAN_CACHE_VERSION vaut 4.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.app.plan_support_core as plan_support_core
import cinesort.app.plan_support_replan as plan_support_replan
import cinesort.domain.core as core
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir

# Version du cache en vigueur AVANT le fix row_id (HIGH-20).
_LEGACY_PLAN_CACHE_VERSION = 4

# `prefix|<16 hex>` : 64 bits. Le legacy produisait 8 hex chars (32 bits).
_ROW_ID_RE = re.compile(r"^[SCT]\|[0-9a-f]{16}$")


def _legacy_row_id(prefix: str, folder: Path, video_name: str) -> str:
    """Imite le row_id pre-fix : un digest tronque a 32 bits (8 hex chars).

    Deterministe ici (le vrai legacy utilisait `hash()`, randomise) : ce qui
    compte est la FORME persistee dans le cache, pas la fonction de hachage.
    """
    key = f"{folder}\x00{video_name}".encode("utf-8", "surrogatepass")
    return f"{prefix}|{hashlib.blake2b(key, digest_size=4).hexdigest()}"


class RowIdCacheInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_rowid_cache_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

        self.folder = self.root / "Inception.2010.1080p"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.video = self.folder / "Inception.2010.1080p.mkv"
        self.video.write_bytes(b"a" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> "core.Config":
        return core.Config(root=self.root, enable_tmdb=False, incremental_scan_enabled=True)

    def _run_plan(self, run_id: str):
        rows, _stats = plan_support.plan_library(
            self._cfg(),
            tmdb=None,
            log=lambda _level, _msg: None,
            progress=lambda _idx, _total, _cur: None,
            scan_index=self.store.scan,
            run_id=run_id,
        )
        return rows

    def _seed_legacy_caches(self) -> str:
        """Rejoue un scan tel que le code PRE-fix l'aurait persiste.

        Version de cache 4 + row_id legacy 32 bits -> peuple incremental_row_cache
        ET incremental_scan_cache avec des row_id tronques, sous l'ancien cfg_sig.
        Retourne le row_id legacy attendu pour la video de test.
        """
        with mock.patch.object(
            plan_support_core, "_PLAN_CACHE_VERSION", _LEGACY_PLAN_CACHE_VERSION
        ), mock.patch.object(plan_support_replan, "_compute_row_id", _legacy_row_id):
            rows = self._run_plan("legacy_seed")

        self.assertEqual(len(rows), 1, "le seed doit produire exactement 1 row")
        legacy_id = _legacy_row_id("S", self.folder, self.video.name)
        self.assertEqual(rows[0].row_id, legacy_id)
        return legacy_id

    def _assert_row_cache_seeded(self, legacy_id: str) -> None:
        cached = self.store.scan.get_incremental_row_cache(
            root_path=str(self.root),
            video_path=str(self.video),
            cfg_sig=self._legacy_cfg_sig(),
        )
        self.assertIsNotNone(cached, "incremental_row_cache non seede : test inoperant")
        self.assertEqual(
            str((cached.get("row_json") or {}).get("row_id") or ""),
            legacy_id,
            "le row_json cache doit porter le row_id legacy",
        )

    def _legacy_cfg_sig(self) -> str:
        with mock.patch.object(
            plan_support_core, "_PLAN_CACHE_VERSION", _LEGACY_PLAN_CACHE_VERSION
        ):
            return plan_support_core.cfg_signature_for_incremental(self._cfg().normalized())

    # --- Gate 1 : le bump doit exister (les deux caches n'ont pas d'autre levier) ---

    def test_cache_version_bumped_past_legacy(self) -> None:
        self.assertGreater(
            int(plan_support_core._PLAN_CACHE_VERSION),
            _LEGACY_PLAN_CACHE_VERSION,
            "_PLAN_CACHE_VERSION n'a pas ete bumpe : cfg_sig est identique a celui du "
            "code pre-fix, donc les caches row/folder rejouent leurs row_id 32 bits.",
        )

    def test_cfg_sig_changes_with_cache_version(self) -> None:
        """cfg_sig = SEULE cle d'invalidation des deux caches -> doit bouger."""
        current = plan_support_core.cfg_signature_for_incremental(self._cfg().normalized())
        self.assertNotEqual(
            current,
            self._legacy_cfg_sig(),
            "cfg_sig inchange : get_incremental_row_cache / get_incremental_folder_cache "
            "(WHERE ... AND cfg_sig=?) referont HIT sur les entrees legacy.",
        )

    # --- Gate 2 : cache row (par video) seede legacy -> le scan doit le rejeter ---

    def test_seeded_row_cache_does_not_replay_legacy_row_id(self) -> None:
        legacy_id = self._seed_legacy_caches()
        self._assert_row_cache_seeded(legacy_id)

        # On purge le cache DOSSIER : seul incremental_row_cache peut servir la row.
        self.store.scan.prune_incremental_scan_cache(root_path=str(self.root), keep_folders=[])

        rows = self._run_plan("post_fix_row")
        self.assertEqual(len(rows), 1)
        row_id = str(rows[0].row_id)

        self.assertNotEqual(
            row_id,
            legacy_id,
            "incremental_row_cache a rejoue la row cachee telle quelle : le row_id "
            "legacy 32 bits survit au fix (_plan_item fait `return [cached_row]`).",
        )
        self.assertRegex(
            row_id,
            _ROW_ID_RE,
            f"row_id {row_id!r} n'est pas la cle stable 64 bits attendue",
        )

    # --- Gate 3 : cache dossier seede legacy -> le scan doit le rejeter aussi ---

    def test_seeded_folder_cache_does_not_replay_legacy_row_id(self) -> None:
        legacy_id = self._seed_legacy_caches()

        # On purge le cache VIDEO : seul incremental_scan_cache peut servir la row.
        self.store.scan.prune_incremental_row_cache(root_path=str(self.root), keep_video_paths=[])

        rows = self._run_plan("post_fix_folder")
        self.assertEqual(len(rows), 1)
        row_id = str(rows[0].row_id)

        self.assertNotEqual(
            row_id,
            legacy_id,
            "incremental_scan_cache (par dossier) a rejoue les rows cachees telles "
            "quelles : le row_id legacy 32 bits survit au fix.",
        )
        self.assertRegex(row_id, _ROW_ID_RE)

    # --- Gate 4 : les DEUX caches seedes ensemble (cas reel d'une install existante) ---

    def test_both_caches_seeded_legacy_are_invalidated(self) -> None:
        legacy_id = self._seed_legacy_caches()

        rows = self._run_plan("post_fix_both")
        self.assertEqual(len(rows), 1)
        row_id = str(rows[0].row_id)

        self.assertNotEqual(row_id, legacy_id)
        self.assertRegex(row_id, _ROW_ID_RE)
        # Et la valeur doit etre celle du helper de production.
        self.assertEqual(
            row_id,
            plan_support_replan._compute_row_id("S", self.folder, self.video.name),
        )

    def test_second_scan_after_bump_still_reuses_cache(self) -> None:
        """Pas d'effet de bord : apres le rescan force, le cache re-sert normalement."""
        self._seed_legacy_caches()
        rows_1 = self._run_plan("bumped_1")
        rows_2 = self._run_plan("bumped_2")

        self.assertEqual(len(rows_2), 1)
        self.assertEqual(rows_1[0].row_id, rows_2[0].row_id)
        self.assertRegex(str(rows_2[0].row_id), _ROW_ID_RE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
