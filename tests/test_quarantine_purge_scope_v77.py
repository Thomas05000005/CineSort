"""Gardes FIX #7 / #8 Lot D-fix (verif/totale-2026-07) sur quarantine_ttl.

Contexte : LOTC-DUP-BUCKET-VIEWER a elargi le VIEWER quarantaine aux buckets
`<state_dir>/runs/.../_review`, mais la PURGE reste scopee `<root>/_review`
(sauf `_duplicates_user_decided`, cf gouvernance R8-002). Deux findings :

FIX #8 : `purge_scope_files_count` / `purge_scope_size_bytes` doivent decrire le
perimetre REELLEMENT purge par "Vider maintenant" (`purge_review_bucket_all`) :
<root>/_review MOINS `_duplicates_user_decided`, et JAMAIS les buckets runs.
Avant, le compteur derivait du retour brut de `_collect` -> il incluait
`_duplicates_user_decided` -> l'utilisateur confirmait N et obtenait deleted<<N.

FIX #7 : pour les buckets runs (lecture seule, sans manifest persiste), la date
d'arrivee doit etre ancree sur un timestamp FS STABLE et non reancree a `now` a
chaque appel (sinon `age_days` reste fige a 0 et le tri par arrivee est faux).
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import cinesort.app.quarantine_ttl as qt
import cinesort.domain.core as core


class _RegistryIsolationMixin:
    """Isole le registre module-level `_KNOWN_RUNS_ROOTS` (partage entre tests)."""

    def _isolate_registry(self) -> None:
        with qt._RUNS_ROOTS_LOCK:
            self._saved_roots = set(qt._KNOWN_RUNS_ROOTS)
            qt._KNOWN_RUNS_ROOTS.clear()
        self.addCleanup(self._restore_registry)

    def _restore_registry(self) -> None:
        with qt._RUNS_ROOTS_LOCK:
            qt._KNOWN_RUNS_ROOTS.clear()
            qt._KNOWN_RUNS_ROOTS.update(self._saved_roots)


class PurgeScopeContractTests(_RegistryIsolationMixin, unittest.TestCase):
    """FIX #8 : purge_scope_* == ce que la purge supprime reellement."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_purge_scope_")
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "root"
        self.root.mkdir()
        self.runs = base / "state" / "runs"
        self.cfg = core.Config(root=self.root).normalized()
        self._isolate_registry()

    def _write(self, *parts: str, content: bytes = b"x" * 100) -> Path:
        p = self.root / "_review"
        for part in parts:
            p = p / part
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def _mk_run_file(self, subdir: str, name: str, content: bytes = b"L" * 1024) -> Path:
        d = self.runs / "tri_films_abc" / "_review" / subdir
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_bytes(content)
        return f

    def test_purge_scope_matches_dry_run_purge_all(self) -> None:
        # Perimetre purgeable : _conflicts + _leftovers + fichier top-level.
        self._write("_conflicts", "a.mkv", content=b"a" * 100)
        self._write("_leftovers", "b.mkv", content=b"b" * 200)
        self._write("orphan.mkv", content=b"o" * 50)
        # PRESERVE (jamais purge) : _duplicates_user_decided.
        self._write("_duplicates_user_decided", "keep.mkv", content=b"k" * 999)

        res = qt.list_review_bucket_files(self.cfg)
        # Le viewer agrege tout (informatif).
        self.assertEqual(res["files_count"], 4, res)
        # Le perimetre purgeable exclut la decision preservee.
        self.assertEqual(res["purge_scope_files_count"], 3, res)
        self.assertEqual(res["purge_scope_size_bytes"], 350, res)

        # Ce que la purge supprimerait vraiment (dry_run, aucune mutation FS).
        purged = qt.purge_review_bucket_all(self.cfg, dry_run=True)
        self.assertEqual(purged["deleted"], res["purge_scope_files_count"], purged)
        self.assertEqual(purged["bytes_freed"], res["purge_scope_size_bytes"], purged)

    def test_real_purge_all_matches_scope_and_preserves_decisions(self) -> None:
        self._write("_conflicts", "a.mkv", content=b"a" * 100)
        keep = self._write("_duplicates_user_decided", "keep.mkv", content=b"k" * 42)

        scope = qt.list_review_bucket_files(self.cfg)["purge_scope_files_count"]
        self.assertEqual(scope, 1)

        purged = qt.purge_review_bucket_all(self.cfg)
        self.assertTrue(purged["ok"], purged)
        self.assertEqual(purged["deleted"], scope, purged)
        self.assertTrue(keep.exists(), "_duplicates_user_decided doit etre preserve")

    def test_purge_scope_excludes_run_buckets(self) -> None:
        # <root>/_review absent, seul un bucket run existe -> rien de purgeable.
        self._mk_run_file("_duplicates_user_decided", "loser.mkv")
        qt.register_runs_root(self.runs)

        res = qt.list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 1, res)  # visible dans le viewer
        self.assertEqual(res["purge_scope_files_count"], 0, res)
        self.assertEqual(res["purge_scope_size_bytes"], 0, res)

        purged = qt.purge_review_bucket_all(self.cfg, dry_run=True)
        self.assertEqual(purged["deleted"], 0, purged)

    def test_run_conflict_not_counted_but_root_conflict_is(self) -> None:
        # Meme sous-dossier purgeable (_conflicts) : cote root il compte, cote
        # run il est visible mais HORS perimetre purgeable.
        self._write("_conflicts", "root.mkv", content=b"r" * 128)
        self._mk_run_file("_conflicts", "run.mkv", content=b"R" * 256)
        qt.register_runs_root(self.runs)

        res = qt.list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 2, res)
        self.assertEqual(res["purge_scope_files_count"], 1, res)
        self.assertEqual(res["purge_scope_size_bytes"], 128, res)

    def test_purge_scope_zero_when_only_preserved_subdir(self) -> None:
        self._write("_duplicates_user_decided", "keep.mkv", content=b"k" * 100)
        res = qt.list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 1, res)
        self.assertEqual(res["purge_scope_files_count"], 0, res)
        purged = qt.purge_review_bucket_all(self.cfg, dry_run=True)
        self.assertEqual(purged["deleted"], 0, purged)


class RunBucketArrivalStabilityTests(_RegistryIsolationMixin, unittest.TestCase):
    """FIX #7 : les buckets runs ancrent l'arrivee sur un TS FS stable."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_arrival_")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.bucket = self.base / "runbucket" / "_review"
        (self.bucket / "_duplicates_user_decided").mkdir(parents=True)
        self.rel = "_duplicates_user_decided/loser.mkv"
        (self.bucket / self.rel).write_bytes(b"L" * 256)
        self._isolate_registry()

    def test_run_bucket_arrival_stable_not_reanchored(self) -> None:
        # persist=False (bucket run) : l'arrivee NE doit PAS suivre `now`, sinon
        # deux appels renvoient deux valeurs differentes -> age_days fige a 0.
        # R2 : le dating stable des buckets runs passe desormais par le flag
        # explicite stable_arrival=True (decouple de persist pour ne plus faire
        # diverger le dry-run purge). C'est ainsi que _collect appelle pour les runs.
        a1 = qt._sync_arrival_manifest(self.bucket, persist=False, stable_arrival=True, now=1_000_000.0)
        a2 = qt._sync_arrival_manifest(self.bucket, persist=False, stable_arrival=True, now=9_000_000.0)
        self.assertIn(self.rel, a1)
        self.assertEqual(
            a1[self.rel],
            a2[self.rel],
            "arrivee reancree a `now` a chaque appel -> age_days permanent 0 (FIX #7)",
        )
        # Ancre FS reelle (~maintenant), jamais la valeur `now` injectee.
        self.assertNotEqual(a1[self.rel], 1_000_000.0, a1)
        self.assertNotEqual(a2[self.rel], 9_000_000.0, a2)
        # Aucun manifest ecrit dans le bucket run (gouvernance R8-002).
        self.assertFalse((self.bucket / qt._TTL_MANIFEST_NAME).exists())

    def test_root_bucket_first_observation_still_now(self) -> None:
        # persist=True (<root>/_review) : la 1re observation reste ancree a `now`
        # (semantique AUDIT 2026-06-10 anti-purge retroactive, inchangee).
        a = qt._sync_arrival_manifest(self.bucket, persist=True, now=1_000_000.0)
        self.assertEqual(a[self.rel], 1_000_000.0)
        self.assertTrue((self.bucket / qt._TTL_MANIFEST_NAME).exists())

    def test_viewer_run_entry_arrival_stable_across_calls(self) -> None:
        # Bout-en-bout : l'arrival_ts d'une entree run est identique entre deux
        # appels list_review_bucket_files (sinon age_days=0 en permanence).
        runs = self.base / "state" / "runs"
        d = runs / "tri_films_z" / "_review" / "_duplicates_user_decided"
        d.mkdir(parents=True)
        (d / "loser.mkv").write_bytes(b"L" * 256)
        qt.register_runs_root(runs)
        cfg_root = self.base / "root2"
        cfg_root.mkdir()
        cfg = core.Config(root=cfg_root).normalized()

        r1 = qt.list_review_bucket_files(cfg)
        time.sleep(0.01)  # garantit que `now` avance entre les deux appels
        r2 = qt.list_review_bucket_files(cfg)
        self.assertEqual(r1["files_count"], 1, r1)
        self.assertEqual(
            r1["files"][0]["arrival_ts"],
            r2["files"][0]["arrival_ts"],
            "arrival_ts d'un bucket run doit etre stable (FIX #7)",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
