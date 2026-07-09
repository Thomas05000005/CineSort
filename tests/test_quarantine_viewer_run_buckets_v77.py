"""Gardes unitaires LOTD-DUP-BUCKET-VIEWER (Lot D-fix 2026-07).

Le viewer quarantaine (list_review_bucket_files) doit voir les buckets que
l'apply ecrit REELLEMENT sous <state_dir>/runs/tri_films_<run>/_review/ et les
quarantaines preservees par la retention sous runs/_preserved_review/<run_id>/
(decision R8-002 : les ECRITURES restent sous run_dir — on elargit le VIEWER,
en LECTURE SEULE, on ne deplace pas les buckets).

Invariants verrouilles ici :
  - le loser d'un doublon decide est LISTE (fin de l'invisible UI) ;
  - AUCUN manifest TTL n'est ecrit dans les buckets runs (sinon clean_old_runs
    preserverait des _review ne contenant que le manifest, pollution R8-002) ;
  - purge_scope_files_count = perimetre reel de "Vider maintenant"/TTL
    (<root>/_review uniquement) ; les purges ne touchent JAMAIS les buckets runs.

Chaine complete correspondante : tests/test_lotd_chain_doublons.py
(garde nominative [LOTD-DUP-BUCKET-VIEWER] redevenue passante).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cinesort.app.quarantine_ttl as qt
import cinesort.domain.core as core


class RunBucketViewerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_viewer_runs_")
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "root"
        self.root.mkdir()
        self.runs = base / "state" / "runs"
        self.cfg = core.Config(root=self.root).normalized()

        # Isolation du registre module-level (partage entre tests du process).
        with qt._RUNS_ROOTS_LOCK:
            self._saved_roots = set(qt._KNOWN_RUNS_ROOTS)
            qt._KNOWN_RUNS_ROOTS.clear()
        self.addCleanup(self._restore_registry)

    def _restore_registry(self) -> None:
        with qt._RUNS_ROOTS_LOCK:
            qt._KNOWN_RUNS_ROOTS.clear()
            qt._KNOWN_RUNS_ROOTS.update(self._saved_roots)

    def _mk_run_bucket_file(self, run_id: str, subdir: str, name: str) -> Path:
        d = self.runs / f"tri_films_{run_id}" / "_review" / subdir
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_bytes(b"L" * 1024)
        return f

    def _mk_preserved_file(self, run_id: str, subdir: str, name: str) -> Path:
        d = self.runs / "_preserved_review" / f"tri_films_{run_id}" / subdir
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_bytes(b"P" * 512)
        return f

    def test_loser_in_run_bucket_is_visible(self) -> None:
        loser = self._mk_run_bucket_file("abc", "_duplicates_user_decided", "Loser.720p.mkv")
        qt.register_runs_root(self.runs)

        res = qt.list_review_bucket_files(self.cfg)
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["exists"], "exists doit refleter les buckets runs aussi")
        self.assertEqual(res["files_count"], 1, res)
        entry = res["files"][0]
        self.assertEqual(entry["path"], str(loser))
        self.assertEqual(entry["subdir"], "_duplicates_user_decided")
        self.assertIn("source_root", entry, "les entrees runs doivent porter leur origine")
        self.assertEqual(res["by_subdir"]["_duplicates_user_decided"]["count"], 1)
        # Perimetre purgeable reel : rien (le loser est HORS <root>/_review).
        self.assertEqual(res["purge_scope_files_count"], 0, res)

    def test_preserved_review_buckets_are_visible(self) -> None:
        self._mk_preserved_file("old", "_conflicts", "Old.Conflict.mkv")
        qt.register_runs_root(self.runs)

        res = qt.list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 1, res)
        self.assertEqual(res["files"][0]["subdir"], "_conflicts")

    def test_no_ttl_manifest_written_into_run_buckets(self) -> None:
        self._mk_run_bucket_file("abc", "_duplicates_user_decided", "Loser.mkv")
        qt.register_runs_root(self.runs)

        qt.list_review_bucket_files(self.cfg)
        manifests = list(self.runs.rglob(qt._TTL_MANIFEST_NAME))
        self.assertEqual(
            manifests, [],
            "manifest TTL ecrit dans un bucket runs : clean_old_runs preserverait "
            "des _review vides (pollution gouvernance R8-002)",
        )

    def test_root_and_run_buckets_are_aggregated(self) -> None:
        conflict = self.root / "_review" / "_conflicts"
        conflict.mkdir(parents=True)
        (conflict / "Root.Conflict.mkv").write_bytes(b"R" * 256)
        self._mk_run_bucket_file("abc", "_duplicates_user_decided", "Loser.mkv")
        qt.register_runs_root(self.runs)

        res = qt.list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 2, res)
        self.assertEqual(res["purge_scope_files_count"], 1, res)
        self.assertEqual(res["by_subdir"]["_conflicts"]["count"], 1)
        self.assertEqual(res["by_subdir"]["_duplicates_user_decided"]["count"], 1)

    def test_without_registration_legacy_behavior_kept(self) -> None:
        self._mk_run_bucket_file("abc", "_duplicates_user_decided", "Loser.mkv")
        res = qt.list_review_bucket_files(self.cfg)
        self.assertFalse(res["exists"], res)
        self.assertEqual(res["files_count"], 0, res)

    def test_purges_never_touch_run_buckets(self) -> None:
        loser = self._mk_run_bucket_file("abc", "_duplicates_user_decided", "Loser.mkv")
        qt.register_runs_root(self.runs)

        purged = qt.purge_review_bucket(self.cfg, ttl_days=30)
        self.assertTrue(purged["ok"], purged)
        purged_all = qt.purge_review_bucket_all(self.cfg)
        self.assertTrue(purged_all["ok"], purged_all)
        self.assertTrue(
            loser.exists(),
            "gouvernance R8-002 violee : une purge a detruit un bucket runs",
        )

    def test_register_runs_root_tolerates_bad_input(self) -> None:
        qt.register_runs_root(None)  # ne doit pas lever
        qt.register_runs_root("")
        res = qt.list_review_bucket_files(self.cfg)
        self.assertTrue(res["ok"], res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
