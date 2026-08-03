"""GATE AUDIT 2026-06-11 (R3e, gap[2]) — le row cache compare enfin le kind.

Avant : la cle de cache row v2 = (root_path, video_path, cfg_sig) SANS kind, et
le check de validite ne verifiait que size/mtime/hash/nfo_sig. Un meme fichier
bascule single<->collection quand on ajoute une 2e video au dossier ; ses
octets/NFO ne changent pas -> le check passait et renvoyait la row STALE du
mauvais kind (row_id prefix S vs C, collection_name, semantique de rename
divergents).

Apres : _try_lookup_row_cache compare cached['kind'] au kind demande ; un kind
different -> cache miss (re-plan a froid) au lieu d'un hit toxique.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cinesort.domain.core as core_mod
from cinesort.app.plan_support_core import plan_row_to_jsonable
from cinesort.app.plan_support_replan import _try_lookup_row_cache

_FIXED_HASH = "HASHCAFE0001"


class _FakeScanIndex:
    """Index minimal : hash fixe + une seule row cachee (kind parametrable)."""

    def __init__(self, cached_kind: str, *, size: int, mtime_ns: int, row_json: dict) -> None:
        self._cached_kind = cached_kind
        self._size = size
        self._mtime_ns = mtime_ns
        self._row_json = row_json

    def get_incremental_file_hash(self, *, path: str, size: int, mtime_ns: int) -> str:
        return _FIXED_HASH

    def get_incremental_row_cache(self, *, root_path: str, video_path: str, cfg_sig: str) -> dict:
        return {
            "video_size": self._size,
            "video_mtime_ns": self._mtime_ns,
            "video_hash": _FIXED_HASH,
            "nfo_sig": None,  # pas de NFO -> _nfo_signature(None) == None
            "kind": self._cached_kind,
            "row_json": self._row_json,
        }


class RowCacheKindGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_rowkind_")
        self.folder = Path(self._tmp) / "Inception (2010)"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.video = self.folder / "Inception.2010.1080p.mkv"
        self.video.write_bytes(b"x" * 2048)
        st = self.video.stat()
        self.cfg = SimpleNamespace(root=self.folder)
        # PlanRow 'single' serialisee (ce qui est cache).
        row = core_mod.PlanRow(
            row_id="S|deadbeef",
            kind="single",
            folder=str(self.folder),
            video=self.video.name,
            proposed_title="Inception",
            proposed_year=2010,
            proposed_source="bluray",
            confidence=90,
            confidence_label="high",
            candidates=[],
            notes="",
            detected_year=2010,
            detected_year_reason="folder",
            warning_flags=[],
        )
        self._row_json = plan_row_to_jsonable(row)
        self._size = int(st.st_size)
        self._mtime_ns = int(st.st_mtime_ns)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _lookup(self, cached_kind: str, requested_kind: str):
        idx = _FakeScanIndex(cached_kind, size=self._size, mtime_ns=self._mtime_ns, row_json=self._row_json)
        return _try_lookup_row_cache(
            self.cfg,
            self.folder,
            self.video,
            kind=requested_kind,
            cfg_sig="sig-1",
            scan_index=idx,
            run_hash_cache={},
            row_cache_stats={},
        )

    def test_same_kind_hits(self) -> None:
        # kind identique -> hit normal (non-regression).
        row = self._lookup("single", "single")
        self.assertIsNotNone(row, "kind identique : le cache doit toujours faire hit")
        self.assertEqual(row.kind, "single")

    def test_cross_kind_miss(self) -> None:
        # Coeur du gap : cache 'single' mais on demande 'collection' -> miss.
        row = self._lookup("single", "collection")
        self.assertIsNone(
            row,
            "kind different : le cache NE doit PAS renvoyer la row stale du mauvais kind",
        )

    def test_cross_kind_miss_reverse(self) -> None:
        row = self._lookup("collection", "single")
        self.assertIsNone(row, "kind different (sens inverse) : miss attendu")


if __name__ == "__main__":
    unittest.main()
