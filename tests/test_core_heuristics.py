from __future__ import annotations

import itertools
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
import cinesort.app.plan_support as plan_support
import cinesort.domain.scan_helpers as core_scan_helpers
from cinesort.infra.tmdb_client import TmdbResult
from unittest import mock


class _FakeTmdb:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def search_movie(self, query, year=None, language="fr-FR", max_results=8):
        self.calls += 1
        return list(self._results)[:max_results]


class CoreHeuristicsTests(unittest.TestCase):
    def test_extract_year_prefers_parenthesized_or_last(self) -> None:
        self.assertEqual(core.extract_year("1917 (2019)"), 2019)
        self.assertEqual(core.extract_year("2001, l'Odyssee de l'espace (1968)"), 1968)
        self.assertEqual(core.extract_year("Blade Runner 2049 (2017)"), 2017)
        self.assertEqual(core.extract_year("Wonder Woman 1984 2020"), 2020)
        self.assertEqual(core.extract_year("Frantic 1988"), 1988)

    def test_infer_name_year_handles_remaster_years(self) -> None:
        year, reason, remaster = core.infer_name_year(
            folder_name="Borsalino",
            video_name="Borsalino.1970.REMASTERED.2020.1080p.mkv",
        )
        self.assertEqual(year, 1970)
        self.assertTrue(remaster)
        self.assertIn("remaster", reason.lower())

    def test_infer_name_year_conflict_prefers_video_parenthesized(self) -> None:
        year, reason, remaster = core.infer_name_year(
            folder_name="Angel Heart (1947)",
            video_name="Angel Heart (1987) MULTi 2160p.mkv",
        )
        self.assertEqual(year, 1987)
        self.assertFalse(remaster)
        self.assertIn("conflit", reason.lower())

    def test_looks_tv_like_not_triggered_by_many_movies_without_episode_markers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tv_like_") as tmp:
            folder = Path(tmp)
            videos = [folder / f"Film {i:02d} (200{i % 10}).mkv" for i in range(8)]
            self.assertFalse(core.looks_tv_like(folder, videos))

    def test_looks_tv_like_with_episode_markers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tv_like_") as tmp:
            folder = Path(tmp)
            videos = [
                folder / "Serie.S01E01.mkv",
                folder / "Serie.S01E02.mkv",
                folder / "Serie.S01E03.mkv",
            ]
            self.assertTrue(core.looks_tv_like(folder, videos))

    def test_confidence_levels(self) -> None:
        cfg = core.Config(root=Path("."))
        nfo_high = core.Candidate(title="Inception", year=2010, source="nfo", score=0.9)
        name_med = core.Candidate(title="Inception", year=2010, source="name", score=0.6)

        score_nfo, label_nfo = core.compute_confidence(
            cfg, nfo_high, nfo_ok=True, year_delta_reject=False, tmdb_used=False
        )
        score_name, label_name = core.compute_confidence(
            cfg, name_med, nfo_ok=False, year_delta_reject=False, tmdb_used=False
        )

        self.assertGreaterEqual(score_nfo, 80)
        self.assertEqual(label_nfo, "high")
        self.assertGreaterEqual(score_name, 60)
        self.assertEqual(label_name, "med")

    def test_nfo_consistency_avoids_single_token_false_positive(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        nfo = core.NfoInfo(
            title="The never ending wall",
            originaltitle="The never ending wall",
            year=2008,
            tmdbid=None,
            imdbid=None,
        )
        ok, _, _ = core.nfo_consistent(
            cfg,
            nfo,
            folder_name="WALL-E",
            video_name="WALL-E (2008) MULTi VFF 2160p 10bit 4KLight HDR BluRay AC3 5.1 x265-QTZ.mkv",
        )
        self.assertFalse(ok)

    def test_nfo_consistency_accepts_video_title_before_parenthesized_year(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        nfo = core.NfoInfo(
            title="End of Watch",
            originaltitle="End of Watch",
            year=2012,
            tmdbid=None,
            imdbid=None,
        )
        ok, cov, seq = core.nfo_consistent(
            cfg,
            nfo,
            folder_name="La force de l'ordre (2012)",
            video_name="End of Watch (2012) MULTi-VF2 [1080p] BluRay x264-PopHD (La Force de l ordre).mkv",
        )
        self.assertTrue(ok)
        self.assertGreaterEqual(cov, 1.0)
        self.assertGreaterEqual(seq, 1.0)

    def test_nfo_consistency_keeps_rejecting_bac_nord_wrong_nfo(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        nfo = core.NfoInfo(
            title="Norm of the North: King Sized Adventure",
            originaltitle="Norm of the North: King Sized Adventure",
            year=2019,
            tmdbid=None,
            imdbid=None,
        )
        ok, _, _ = core.nfo_consistent(
            cfg,
            nfo,
            folder_name="BAC Nord (2020)",
            video_name="BAC Nord (2020) French VOF 2160p 10bit 4KLight HDR BluRay DTS-HD MA 5.1 x265-QTZ.mkv",
        )
        self.assertFalse(ok)

    def test_nfo_consistency_keeps_rejecting_burn_e_wrong_nfo(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        nfo = core.NfoInfo(
            title="Finns det ett helvete kommer jag att brinna där",
            originaltitle="Finns det ett helvete kommer jag att brinna där",
            year=2008,
            tmdbid=None,
            imdbid=None,
        )
        ok, _, _ = core.nfo_consistent(
            cfg,
            nfo,
            folder_name="BURN·E (2008)",
            video_name="Burn.E.2008.VOST.FR.EN.1080p.BluRay.AC3.x264-STEGNER.mkv",
        )
        self.assertFalse(ok)

    def test_nfo_soft_consistent_accepts_medium_match_when_year_matches(self) -> None:
        self.assertTrue(core.nfo_soft_consistent(name_year=1988, nfo_year=1988, cov=0.50, seq=0.74))

    def test_should_reject_nfo_year_relaxes_for_remaster_context(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        reject, msg = core.should_reject_nfo_year(
            cfg,
            name_year=2020,
            nfo_year=1970,
            remaster_hint=True,
            cov=1.0,
            seq=1.0,
        )
        self.assertFalse(reject)
        self.assertIn("remaster", msg.lower())

    def test_tmdb_confidence_not_dropped_to_low_after_year_reject(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        chosen = core.Candidate(title="The Hurt Locker", year=2008, source="tmdb", score=0.95)
        score, label = core.compute_confidence(cfg, chosen, nfo_ok=False, year_delta_reject=True, tmdb_used=True)
        self.assertGreaterEqual(score, 70)
        self.assertEqual(label, "med")

    def test_tmdb_confidence_boosts_to_high_when_year_matches(self) -> None:
        cfg = core.Config(root=Path(".")).normalized()
        chosen = core.Candidate(
            title="Les Bronzes 3",
            year=2006,
            source="tmdb",
            score=0.86,
            note="sim=0.80, dY=0",
        )
        score, label = core.compute_confidence(cfg, chosen, nfo_ok=False, year_delta_reject=False, tmdb_used=True)
        self.assertGreaterEqual(score, 80)
        self.assertEqual(label, "high")

    def test_tmdb_poster_thumb_url(self) -> None:
        self.assertEqual(
            core.tmdb_poster_thumb_url("/abc.jpg"),
            "https://image.tmdb.org/t/p/w92/abc.jpg",
        )
        self.assertIsNone(core.tmdb_poster_thumb_url(None))

    def test_clean_title_guess_removes_audio_channel_artifacts(self) -> None:
        cleaned = core.clean_title_guess(
            "Star Wars Episode VI Return of the Jedi (1983) Hybrid MULTi VFI 2160p 10bit 4KLight DOLBY VISION BluRay TrueHD Atmos 7.1 x265-QTZ.mkv"
        )
        self.assertIn("Return of the Jedi", cleaned)
        self.assertNotIn("7 1", cleaned)
        self.assertEqual(core.clean_title_guess("The French Connection 2.avi"), "The French Connection 2")

    def test_extract_trailing_sequel_num(self) -> None:
        self.assertEqual(core._extract_trailing_sequel_num("French Connection II"), 2)
        self.assertEqual(core._extract_trailing_sequel_num("The Raid 2"), 2)
        self.assertIsNone(core._extract_trailing_sequel_num("Star Wars Episode VI Return of the Jedi"))

    def test_tmdb_prefers_matching_sequel_number(self) -> None:
        fake = _FakeTmdb(
            [
                TmdbResult(
                    id=1,
                    title="The Connection",
                    year=2024,
                    original_title="The Connection",
                    popularity=10.0,
                    vote_count=300,
                    vote_average=6.0,
                    poster_path=None,
                ),
                TmdbResult(
                    id=2,
                    title="French Connection II",
                    year=1975,
                    original_title="French Connection II",
                    popularity=7.0,
                    vote_count=120,
                    vote_average=6.4,
                    poster_path=None,
                ),
            ]
        )
        cands = core.build_candidates_from_tmdb(
            fake,
            query="The French Connection 2",
            year=None,
            language="fr-FR",
        )
        self.assertTrue(cands)
        self.assertEqual(cands[0].tmdb_id, 2)

    def test_expand_tmdb_queries_keeps_alias_and_deduplicates(self) -> None:
        queries = core._expand_tmdb_queries(
            [
                "Le Salaire de la peur (The Wages of Fear) - Director's Cut",
                "Le Salaire de la peur (The Wages of Fear) - Director's Cut",
            ]
        )
        self.assertIn("Le Salaire de la peur (The Wages of Fear) - Director's Cut", queries)
        self.assertIn("The Wages of Fear", queries)
        self.assertIn("Le Salaire de la peur (The Wages of Fear)", queries)
        self.assertEqual(len(queries), len(set(q.lower() for q in queries)))

    def test_pick_best_candidate_prefers_consensus_sources(self) -> None:
        cands = [
            core.Candidate(title="Gravity", year=2013, source="name", score=0.70),
            core.Candidate(title="Gravity", year=2013, source="nfo", score=0.69),
            core.Candidate(title="Gravity Falls", year=2012, source="tmdb", score=0.74),
        ]
        best = core.pick_best_candidate(cands)
        self.assertIsNotNone(best)
        assert best is not None
        self.assertEqual(best.title, "Gravity")
        self.assertIn("consensus=+", best.note)

    def test_files_identical_quick_uses_hash_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hash_cache_") as tmp:
            src = Path(tmp) / "src.mkv"
            dst = Path(tmp) / "dst.mkv"
            data = b"a" * (1024 * 128)
            src.write_bytes(data)
            dst.write_bytes(data)

            calls = {"n": 0}
            original = core._sha1_quick

            def wrapped(path: Path) -> str:
                calls["n"] += 1
                return original(path)

            with mock.patch.object(core, "_sha1_quick", wrapped):
                cache = {}
                self.assertTrue(core._files_identical_quick(src, dst, hash_cache=cache))
                first_calls = calls["n"]
                self.assertEqual(first_calls, 2)
                self.assertTrue(core._files_identical_quick(src, dst, hash_cache=cache))
                self.assertEqual(calls["n"], first_calls)

    def test_find_duplicate_targets_marks_existing_folder_as_mergeable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dupe_") as tmp:
            root = Path(tmp)
            existing = root / "Inception (2010)"
            existing.mkdir(parents=True, exist_ok=True)
            src = root / "Inception source"
            src.mkdir(parents=True, exist_ok=True)

            cfg = core.Config(root=root).normalized()
            row = core.PlanRow(
                row_id="S|test",
                kind="single",
                folder=str(src),
                video="Inception.2010.mkv",
                proposed_title="Inception",
                proposed_year=2010,
                proposed_source="name",
                confidence=70,
                confidence_label="med",
                candidates=[core.Candidate(title="Inception", year=2010, source="name", score=0.7)],
            )
            decisions = {"S|test": {"ok": True, "title": "Inception", "year": 2010}}
            dup = core.find_duplicate_targets(cfg, [row], decisions)
            self.assertEqual(dup["checked_rows"], 1)
            self.assertIn("mergeables", dup)
            self.assertIn("mergeable_count", dup)
            self.assertGreaterEqual(int(dup.get("mergeable_count", 0)), 1)
            self.assertEqual(int(dup.get("total_groups", 0)), 0)

    def test_plan_library_cancel_requested_returns_partial_without_exception(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cancel_plan_") as tmp:
            root = Path(tmp)
            for i in range(10):
                folder = root / f"Movie.{i}.2010.1080p"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"Movie.{i}.2010.1080p.mkv").write_bytes(b"x" * 2048)

            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                logs = []
                state = {"cancel": False}

                def log(level: str, msg: str) -> None:
                    logs.append((level, msg))

                def progress(idx: int, total: int, current: str) -> None:
                    _ = (total, current)
                    if idx >= 3:
                        state["cancel"] = True

                def should_cancel() -> bool:
                    return bool(state["cancel"])

                rows, stats = plan_support.plan_library(
                    core.Config(root=root, enable_tmdb=False),
                    tmdb=None,
                    log=log,
                    progress=progress,
                    should_cancel=should_cancel,
                )
            self.assertEqual(stats.planned_rows, len(rows))
            self.assertLess(stats.folders_scanned, 10)
            self.assertTrue(
                any(level == "INFO" and "cancel requested" in msg.lower() for level, msg in logs),
                logs,
            )

    def test_plan_library_scans_nested_collection_folders_recursively(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nested_collection_") as tmp:
            root = Path(tmp)
            coll_root = root / "Films_collection" / "Nom de la collection"
            p1 = coll_root / "Premiere partie"
            p2 = coll_root / "Deuxieme partie"
            p1.mkdir(parents=True, exist_ok=True)
            p2.mkdir(parents=True, exist_ok=True)
            (p1 / "Movie.Part.1.2010.1080p.mkv").write_bytes(b"x" * 4096)
            (p2 / "Movie.Part.2.2011.1080p.mkv").write_bytes(b"x" * 4096)

            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                rows, stats = plan_support.plan_library(
                    core.Config(root=root, enable_tmdb=False),
                    tmdb=None,
                    log=lambda *_args: None,
                    progress=lambda *_args: None,
                )
            self.assertGreaterEqual(len(rows), 2)
            folders = {Path(r.folder).name for r in rows}
            self.assertIn("Premiere partie", folders)
            self.assertIn("Deuxieme partie", folders)
            self.assertGreaterEqual(stats.folders_scanned, 2)

    def test_plan_library_keeps_descending_when_parent_only_has_bonus_video(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nested_bonus_parent_") as tmp:
            root = Path(tmp)
            parent = root / "Collection Mixte"
            part1 = parent / "Premiere partie"
            part2 = parent / "Deuxieme partie"
            part1.mkdir(parents=True, exist_ok=True)
            part2.mkdir(parents=True, exist_ok=True)
            (parent / "Bonus.mkv").write_bytes(b"x" * 4096)
            (part1 / "Movie.Part.1.2010.1080p.mkv").write_bytes(b"x" * 4096)
            (part2 / "Movie.Part.2.2011.1080p.mkv").write_bytes(b"x" * 4096)

            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                rows, stats = plan_support.plan_library(
                    core.Config(root=root, enable_tmdb=False),
                    tmdb=None,
                    log=lambda *_args: None,
                    progress=lambda *_args: None,
                )
            folders = {Path(r.folder).name for r in rows}
            self.assertIn("Premiere partie", folders)
            self.assertIn("Deuxieme partie", folders)
            self.assertNotIn("Collection Mixte", folders)
            self.assertGreaterEqual(stats.folders_scanned, 2)

    def test_plan_library_collects_ignored_extensions_breakdown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ignored_exts_") as tmp:
            root = Path(tmp)
            noise = root / "Dossier Bruit"
            noise.mkdir(parents=True, exist_ok=True)
            (noise / "note.txt").write_text("x", encoding="utf-8")
            (noise / "poster.jpg").write_bytes(b"\x00")
            (noise / "info.nfo").write_text("<movie/>", encoding="utf-8")

            rows, stats = plan_support.plan_library(
                core.Config(root=root, enable_tmdb=False),
                tmdb=None,
                log=lambda *_args: None,
                progress=lambda *_args: None,
            )
            self.assertEqual(len(rows), 0)
            self.assertGreaterEqual(int(stats.analyse_ignores_par_raison.get("ignore_non_supporte", 0)), 1)
            self.assertGreaterEqual(int(stats.analyse_ignores_extensions.get(".txt", 0)), 1)
            self.assertGreaterEqual(int(stats.analyse_ignores_extensions.get(".jpg", 0)), 1)

    def test_stream_scan_targets_is_lazy_and_plan_results_stay_stable_on_large_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream_large_tree_") as tmp:
            root = Path(tmp)
            for idx in range(60):
                folder = root / f"Movie {idx:03d}"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"Movie.{idx:03d}.2010.1080p.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                stream = core_scan_helpers.stream_scan_targets(cfg, min_video_bytes=core.MIN_VIDEO_BYTES)
                self.assertFalse(isinstance(stream, list))
                first_batch = list(itertools.islice(stream, 5))
                self.assertEqual(len(first_batch), 5)
                remaining = list(stream)
                all_targets = first_batch + remaining
                self.assertEqual(len(all_targets), 60)

                progress_calls = []
                rows, stats = plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda *_args: None,
                    progress=lambda idx, total, current: progress_calls.append((idx, total, current)),
                )
            self.assertEqual(len(rows), 60)
            self.assertEqual(int(stats.folders_scanned or 0), 60)
            self.assertEqual(len(progress_calls), 60)
            self.assertTrue(all(total >= idx for idx, total, _current in progress_calls), progress_calls[:5])
            self.assertEqual(progress_calls[-1][0], progress_calls[-1][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
