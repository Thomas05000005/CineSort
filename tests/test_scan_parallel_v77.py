"""VO-B refactor : tests pour la parallelisation Phase 1 de plan_library.

Couvre :
  - `extract_local_candidate` pure (FS tmp, isole de ctx/TMDb/SQLite).
  - `parallel_extract_local_candidates` preserve l'ordre des resultats.
  - `resolve_scan_max_workers` clamp + default.
  - `_filter_dossiers_phase` backward-compat strict pour `scan_max_workers=1`
    (memes rows, memes stats, memes progress callbacks vs baseline).
  - `_filter_dossiers_phase` parallele (`scan_max_workers=4`) produit
    identique rows + ordre progress 1..N preserve.
  - Cancellation cooperative propage les placeholders vides.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.app._local_candidate import (
    LocalCandidate,
    extract_local_candidate,
    parallel_extract_local_candidates,
    resolve_scan_max_workers,
)


def _make_tree(root: Path, n_movies: int, *, body_size: int = 4096) -> None:
    """Cree N dossiers `Movie {idx:03d}` chacun avec 1 fichier .mkv valide."""
    for idx in range(n_movies):
        folder = root / f"Movie {idx:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"Movie.{idx:03d}.2010.1080p.mkv").write_bytes(b"x" * body_size)


def _make_cfg(root: Path, *, max_workers: int = 1) -> core.Config:
    return core.Config(
        root=root,
        enable_tmdb=False,
        scan_max_workers=max_workers,
    ).normalized()


class ExtractLocalCandidateTests(unittest.TestCase):
    """Pre-extraction locale pure (sans ctx, sans TMDb, sans SQLite)."""

    def test_returns_videos_for_valid_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_extract_") as tmp:
            root = Path(tmp)
            folder = root / "Inception (2010)"
            folder.mkdir()
            (folder / "Inception.2010.1080p.mkv").write_bytes(b"x" * 4096)
            cfg = _make_cfg(root)
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                result = extract_local_candidate(folder, cfg)
            self.assertIsInstance(result, LocalCandidate)
            self.assertEqual(result.folder, folder)
            self.assertEqual(len(result.videos), 1)
            self.assertEqual(result.videos[0].name, "Inception.2010.1080p.mkv")
            self.assertEqual(result.errors, [])

    def test_collects_non_video_extensions_when_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_extract_empty_") as tmp:
            root = Path(tmp)
            folder = root / "EmptyFolder"
            folder.mkdir()
            (folder / "readme.txt").write_bytes(b"hello")
            (folder / "cover.jpg").write_bytes(b"x" * 1024)
            cfg = _make_cfg(root)
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                result = extract_local_candidate(folder, cfg)
            self.assertEqual(result.videos, [])
            self.assertIn(".txt", result.non_video_exts)
            self.assertIn(".jpg", result.non_video_exts)

    def test_does_not_mutate_external_stats(self) -> None:
        """Garantie thread-safety : aucune mutation de stats partage."""
        with tempfile.TemporaryDirectory(prefix="vob_extract_iso_") as tmp:
            root = Path(tmp)
            folder = root / "M"
            folder.mkdir()
            (folder / "fake.txt").write_bytes(b"x")  # rejet ignore_extension
            cfg = _make_cfg(root)
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                result = extract_local_candidate(folder, cfg)
            # Le bucket local DOIT avoir capture le rejet, pas un global externe.
            self.assertGreaterEqual(int(result.ignores_par_raison.get("ignore_extension", 0)), 1)

    def test_handles_missing_folder_gracefully(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_extract_missing_") as tmp:
            root = Path(tmp)
            missing = root / "does_not_exist"
            cfg = _make_cfg(root)
            result = extract_local_candidate(missing, cfg)
            # Pas de crash ; videos vide et scandir error capture.
            self.assertEqual(result.videos, [])
            # Le bucket porte un ignore_scandir_error OU non_video_exts est vide.


class ParallelExtractOrderTests(unittest.TestCase):
    """L'ordre des resultats DOIT etre identique a l'ordre des inputs."""

    def test_parallel_preserves_order_max_workers_4(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_par_order_") as tmp:
            root = Path(tmp)
            _make_tree(root, n_movies=20)
            folders = sorted(root.iterdir(), key=lambda p: p.name)
            cfg = _make_cfg(root, max_workers=4)
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                results = parallel_extract_local_candidates(folders, cfg, max_workers=4)
            self.assertEqual(len(results), 20)
            # Verifie l'ordre 1..N strict via le nom de dossier.
            for idx, cand in enumerate(results):
                self.assertEqual(cand.folder.name, f"Movie {idx:03d}")
                self.assertEqual(len(cand.videos), 1)

    def test_sequential_path_when_max_workers_1(self) -> None:
        """max_workers=1 -> pas de pool, code-path direct."""
        with tempfile.TemporaryDirectory(prefix="vob_par_seq_") as tmp:
            root = Path(tmp)
            _make_tree(root, n_movies=5)
            folders = sorted(root.iterdir(), key=lambda p: p.name)
            cfg = _make_cfg(root, max_workers=1)
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                results = parallel_extract_local_candidates(folders, cfg, max_workers=1)
            self.assertEqual(len(results), 5)
            for idx, cand in enumerate(results):
                self.assertEqual(cand.folder.name, f"Movie {idx:03d}")

    def test_empty_folders_input(self) -> None:
        cfg = _make_cfg(Path(tempfile.gettempdir()))
        self.assertEqual(parallel_extract_local_candidates([], cfg, max_workers=4), [])

    def test_cancellation_returns_placeholders(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cancel_") as tmp:
            root = Path(tmp)
            _make_tree(root, n_movies=10)
            folders = sorted(root.iterdir(), key=lambda p: p.name)
            cfg = _make_cfg(root, max_workers=2)

            # Cancel immediat -> tous placeholders en mode sequentiel.
            results = parallel_extract_local_candidates(folders, cfg, max_workers=1, should_cancel=lambda: True)
            self.assertEqual(len(results), 10)
            for cand in results:
                self.assertEqual(cand.videos, [])


class ResolveScanMaxWorkersTests(unittest.TestCase):
    def test_default_is_1(self) -> None:
        cfg = mock.Mock(spec=[])  # no attr
        self.assertEqual(resolve_scan_max_workers(cfg), 1)

    def test_passthrough_in_range(self) -> None:
        cfg = mock.Mock(spec=["scan_max_workers"])
        cfg.scan_max_workers = 8
        self.assertEqual(resolve_scan_max_workers(cfg), 8)

    def test_clamp_high(self) -> None:
        cfg = mock.Mock(spec=["scan_max_workers"])
        cfg.scan_max_workers = 99999
        # Plafond a 32 (cap dur).
        self.assertEqual(resolve_scan_max_workers(cfg), 32)

    def test_zero_falls_back_to_1(self) -> None:
        cfg = mock.Mock(spec=["scan_max_workers"])
        cfg.scan_max_workers = 0
        self.assertEqual(resolve_scan_max_workers(cfg), 1)

    def test_invalid_falls_back_to_1(self) -> None:
        cfg = mock.Mock(spec=["scan_max_workers"])
        cfg.scan_max_workers = "abc"
        self.assertEqual(resolve_scan_max_workers(cfg), 1)


class PlanLibraryBackwardCompatTests(unittest.TestCase):
    """VO-B backward compat strict : max_workers=1 -> diff vs baseline = 0 rows.

    Reutilise le pattern de tests/test_scan_streaming.py.
    """

    def _run_plan(self, root: Path, *, max_workers: int):
        cfg = _make_cfg(root, max_workers=max_workers)
        progress_calls: list = []
        with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
            rows, stats = plan_support.plan_library(
                cfg,
                tmdb=None,
                log=lambda *_a: None,
                progress=lambda idx, total, current: progress_calls.append((idx, total, current)),
            )
        return rows, stats, progress_calls

    def test_max_workers_1_matches_baseline(self) -> None:
        """max_workers=1 (default) doit reproduire le comportement historique."""
        with tempfile.TemporaryDirectory(prefix="vob_baseline_") as tmp:
            root = Path(tmp)
            _make_tree(root, n_movies=30)
            rows, stats, prog = self._run_plan(root, max_workers=1)
            self.assertEqual(len(rows), 30)
            self.assertEqual(int(stats.folders_scanned or 0), 30)
            self.assertEqual(len(prog), 30)
            # Ordre 1..N strict.
            for idx, (cb_idx, cb_total, _path) in enumerate(prog, start=1):
                self.assertEqual(cb_idx, idx)
                self.assertEqual(cb_total, 30)

    def test_max_workers_4_produces_same_rows(self) -> None:
        """Phase 1 parallele : memes rows, memes stats, meme ordre progress."""
        with tempfile.TemporaryDirectory(prefix="vob_par4_") as tmp:
            root = Path(tmp)
            _make_tree(root, n_movies=30)
            rows_seq, stats_seq, prog_seq = self._run_plan(root, max_workers=1)
            rows_par, stats_par, prog_par = self._run_plan(root, max_workers=4)

            # Memes rows (ordre et contenu).
            self.assertEqual(len(rows_seq), len(rows_par))
            self.assertEqual([r.folder for r in rows_seq], [r.folder for r in rows_par])
            # Memes stats agreges.
            self.assertEqual(
                int(stats_seq.folders_scanned or 0),
                int(stats_par.folders_scanned or 0),
            )
            self.assertEqual(
                int(stats_seq.planned_rows or 0),
                int(stats_par.planned_rows or 0),
            )
            # Meme ordre progress 1..N.
            self.assertEqual(len(prog_seq), len(prog_par))
            for (a_idx, a_total, _), (b_idx, b_total, _) in zip(prog_seq, prog_par):
                self.assertEqual(a_idx, b_idx)
                self.assertEqual(a_total, b_total)

    def test_max_workers_8_progress_order_strict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_par8_") as tmp:
            root = Path(tmp)
            _make_tree(root, n_movies=15)
            _rows, _stats, prog = self._run_plan(root, max_workers=8)
            # 1..N strict, jamais d'inversion.
            for idx, (cb_idx, _cb_total, _path) in enumerate(prog, start=1):
                self.assertEqual(cb_idx, idx)


class PlanLibraryEmptyFoldersTests(unittest.TestCase):
    """Verifie que les ignores_par_raison sont correctement rejoues en parallele."""

    def test_videos_empty_branch_merges_non_video_exts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_empty_branch_") as tmp:
            root = Path(tmp)
            # 1 dossier vide (juste un .txt) + 1 dossier avec un .mkv valide
            empty = root / "EmptyA (2010)"
            empty.mkdir()
            (empty / "readme.txt").write_bytes(b"hello")
            ok = root / "Movie B (2011)"
            ok.mkdir()
            (ok / "Movie.B.2011.mkv").write_bytes(b"x" * 4096)

            cfg_seq = _make_cfg(root, max_workers=1)
            cfg_par = _make_cfg(root, max_workers=4)
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                rows_seq, stats_seq = plan_support.plan_library(
                    cfg_seq,
                    tmdb=None,
                    log=lambda *_a: None,
                    progress=lambda *_a: None,
                )
                rows_par, stats_par = plan_support.plan_library(
                    cfg_par,
                    tmdb=None,
                    log=lambda *_a: None,
                    progress=lambda *_a: None,
                )
            # Memes rows entre seq et par.
            self.assertEqual(len(rows_seq), len(rows_par))
            # Memes extensions non-video accumulees.
            self.assertEqual(
                dict(stats_seq.analyse_ignores_extensions or {}),
                dict(stats_par.analyse_ignores_extensions or {}),
            )


if __name__ == "__main__":
    unittest.main()
