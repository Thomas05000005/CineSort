"""VQ-2 QUARANTAINE-TTL v7.7.0 — tests TTL filesystem du bucket `_review`.

Couvre :
- purge_review_bucket : suppression des fichiers > TTL, conservation des fichiers fraichement modifies
- TTL = 0 desactive (no-op)
- by_subdir : `_conflicts`, `_conflicts_sidecars`, `_duplicates_identical`, `_leftovers`
- top-level quarantine rows : purges si > TTL
- `_duplicates_user_decided` : JAMAIS purge (decisions UI explicites)
- bucket absent : ok no_bucket=True
- purge_review_bucket_all : vide tout sauf `_duplicates_user_decided`
- start_quarantine_ttl_cron : retourne None si ttl_days <= 0
- trigger_now : helper synchrone tests
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import json

from cinesort.app.quarantine_ttl import (
    DEFAULT_TTL_DAYS,
    REVIEW_FOLDER_NAME,
    TTL_SUBDIRS,
    _TTL_MANIFEST_NAME,
    list_review_bucket_files,
    purge_review_bucket,
    purge_review_bucket_all,
    review_root,
    start_quarantine_ttl_cron,
    trigger_now,
)


def _make_cfg(root: Path) -> SimpleNamespace:
    """Cfg minimaliste : seul `root` est lu par quarantine_ttl."""
    return SimpleNamespace(root=root)


def _set_mtime(p: Path, days_ago: float) -> None:
    """Force mtime/atime a `days_ago` jours dans le passe."""
    ts = time.time() - (days_ago * 86400.0)
    os.utime(p, (ts, ts))


def _seed_arrival(root: Path, rel: str, days_ago: float) -> None:
    """Inscrit dans le manifest une date d'ENTREE en quarantaine `days_ago` jours
    dans le passe (simule un fichier mis en quarantaine il y a `days_ago` jours).

    AUDIT 2026-06-10 : le TTL se base sur l'arrivee en quarantaine (manifest),
    plus sur le mtime du fichier — les tests doivent donc semer l'arrivee.
    """
    manifest_path = root / "_review" / _TTL_MANIFEST_NAME
    data = {}
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data[rel] = time.time() - (days_ago * 86400.0)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")


def _write_file(
    p: Path, content: bytes = b"x", days_ago: float = 0.0, *, root: Path = None
) -> Path:
    """Ecrit un fichier de quarantaine.

    `days_ago` simule l'anciennete d'ENTREE en quarantaine : on fixe le mtime ET
    on seme le manifest d'arrivee a la meme date (les deux pour rester robuste,
    mais c'est le manifest qui pilote le TTL desormais).
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    if days_ago > 0:
        _set_mtime(p, days_ago)
        if root is not None:
            rel = p.relative_to(root / "_review").as_posix()
            _seed_arrival(root, rel, days_ago)
    return p


class PurgeReviewBucketBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_vq2_")
        self.root = Path(self._tmp)
        self.cfg = _make_cfg(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_review_folder_name_constant(self) -> None:
        self.assertEqual(REVIEW_FOLDER_NAME, "_review")

    def test_review_root_helper(self) -> None:
        self.assertEqual(review_root(self.cfg), self.root / "_review")

    def test_no_bucket_returns_ok(self) -> None:
        # Le bucket n'existe pas du tout.
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("no_bucket"))
        self.assertEqual(res["deleted"], 0)

    def test_ttl_zero_is_noop(self) -> None:
        _write_file(self.root / "_review" / "_conflicts" / "old.mkv", days_ago=999)
        res = purge_review_bucket(self.cfg, ttl_days=0)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("disabled"))
        self.assertEqual(res["deleted"], 0)
        # Fichier doit toujours exister
        self.assertTrue((self.root / "_review" / "_conflicts" / "old.mkv").exists())

    def test_ttl_negative_is_noop(self) -> None:
        _write_file(self.root / "_review" / "_conflicts" / "old.mkv", days_ago=999)
        res = purge_review_bucket(self.cfg, ttl_days=-5)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("disabled"))
        self.assertTrue((self.root / "_review" / "_conflicts" / "old.mkv").exists())

    def test_purge_old_files_in_conflicts(self) -> None:
        # 1 vieux fichier (40j) + 1 recent (1j) avec TTL 30j
        old = _write_file(
            self.root / "_review" / "_conflicts" / "old.mkv", days_ago=40, root=self.root
        )
        recent = _write_file(
            self.root / "_review" / "_conflicts" / "recent.mkv", days_ago=1, root=self.root
        )
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertTrue(res["ok"])
        self.assertEqual(res["deleted"], 1)
        self.assertGreaterEqual(res["bytes_freed"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_old_mtime_recent_arrival_not_purged(self) -> None:
        # GATE AUDIT 2026-06-10 (CRITICAL) : un fichier dont le mtime est tres
        # ancien (film encode il y a 999 jours) mais qui vient d'ENTRER en
        # quarantaine (manifest = maintenant) ne doit PAS etre purge. C'est le
        # scenario exact de la perte de donnees corrigee.
        f = self.root / "_review" / "_conflicts" / "vieux_film.mkv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        _set_mtime(f, 999)  # mtime tres ancien, MAIS pas de seed manifest
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertTrue(res["ok"])
        self.assertEqual(res["deleted"], 0, "arrivee = now -> conserve malgre mtime ancien")
        self.assertTrue(f.exists())
        # 2e cycle apres avoir vieilli l'arrivee de 40j : maintenant purge.
        _seed_arrival(self.root, "_conflicts/vieux_film.mkv", 40)
        res2 = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertEqual(res2["deleted"], 1)
        self.assertFalse(f.exists())

    def test_arrival_manifest_excluded_from_inventory(self) -> None:
        # Le manifest interne ne doit jamais etre compte ni purge comme contenu.
        _write_file(
            self.root / "_review" / "_conflicts" / "a.bin", days_ago=40, root=self.root
        )
        inv = list_review_bucket_files(self.cfg)
        rels = {e["rel"] for e in inv["files"]}
        self.assertNotIn(_TTL_MANIFEST_NAME, rels)
        # Le manifest existe bien sur disque mais hors inventaire.
        self.assertTrue((self.root / "_review" / _TTL_MANIFEST_NAME).is_file())

    def test_purge_all_ttl_subdirs(self) -> None:
        # 1 vieux fichier par sous-dossier TTL
        old_files = []
        for sub in TTL_SUBDIRS:
            f = _write_file(
                self.root / "_review" / sub / "x.bin", days_ago=60, root=self.root
            )
            old_files.append(f)
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertEqual(res["deleted"], len(TTL_SUBDIRS))
        for f in old_files:
            self.assertFalse(f.exists())

    def test_preserve_duplicates_user_decided(self) -> None:
        # _duplicates_user_decided NE doit JAMAIS etre purge (decisions UI).
        preserved = _write_file(
            self.root / "_review" / "_duplicates_user_decided" / "decision.mkv",
            days_ago=999,
            root=self.root,
        )
        # Un fichier conflits ancien pour confirmer que le TTL marche par ailleurs
        purged = _write_file(
            self.root / "_review" / "_conflicts" / "old.mkv", days_ago=40, root=self.root
        )
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertTrue(res["ok"])
        self.assertFalse(purged.exists())
        self.assertTrue(preserved.exists(), "_duplicates_user_decided doit etre preserve")

    def test_top_level_quarantine_row_purged(self) -> None:
        # Row top-level : `_review/<folder>/...` (cas quarantine_unapproved=True)
        old = _write_file(
            self.root / "_review" / "MyFilm (2020)" / "movie.mkv", days_ago=40, root=self.root
        )
        recent = _write_file(
            self.root / "_review" / "MyFilm (2020)" / "subs.srt", days_ago=1, root=self.root
        )
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertTrue(res["ok"])
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        # Le top_quarantine doit etre comptabilise
        self.assertIn("_top_quarantine", res["by_subdir"])

    def test_empty_dirs_removed_after_purge(self) -> None:
        # Fichier ancien dans sous-dossier profond : on purge le fichier + le sous-dossier vide.
        f = _write_file(
            self.root / "_review" / "_leftovers" / "deep" / "x.bin", days_ago=99, root=self.root
        )
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertEqual(res["deleted"], 1)
        self.assertFalse(f.exists())
        # `_review/_leftovers/deep/` doit avoir disparu (vide post-purge)
        self.assertFalse((self.root / "_review" / "_leftovers" / "deep").exists())
        # Mais `_leftovers` lui-meme reste (target preserve)
        self.assertTrue((self.root / "_review" / "_leftovers").exists())

    def test_by_subdir_counters(self) -> None:
        _write_file(self.root / "_review" / "_conflicts" / "a.bin", days_ago=40, root=self.root)
        _write_file(self.root / "_review" / "_conflicts" / "b.bin", days_ago=40, root=self.root)
        _write_file(self.root / "_review" / "_leftovers" / "c.bin", days_ago=40, root=self.root)
        res = purge_review_bucket(self.cfg, ttl_days=30)
        self.assertEqual(res["by_subdir"]["_conflicts"]["deleted"], 2)
        self.assertEqual(res["by_subdir"]["_leftovers"]["deleted"], 1)


class PurgeReviewBucketAllTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_vq2_all_")
        self.root = Path(self._tmp)
        self.cfg = _make_cfg(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_purge_all_wipes_everything_except_user_decided(self) -> None:
        # Fichiers recents (1j) ET anciens (40j) dans TOUS les buckets
        _write_file(self.root / "_review" / "_conflicts" / "a.bin", days_ago=1)
        _write_file(self.root / "_review" / "_conflicts" / "b.bin", days_ago=40)
        _write_file(self.root / "_review" / "_leftovers" / "c.bin", days_ago=1)
        preserved = _write_file(
            self.root / "_review" / "_duplicates_user_decided" / "x.bin",
            days_ago=1,
        )
        top = _write_file(self.root / "_review" / "MyFilm" / "movie.mkv", days_ago=1)
        res = purge_review_bucket_all(self.cfg)
        self.assertTrue(res["ok"])
        self.assertEqual(res["purge_mode"], "all")
        self.assertEqual(res["deleted"], 4)  # tout sauf _duplicates_user_decided
        self.assertTrue(preserved.exists())
        self.assertFalse(top.exists())

    def test_purge_all_dry_run_does_not_delete(self) -> None:
        f = _write_file(self.root / "_review" / "_conflicts" / "a.bin", days_ago=1)
        res = purge_review_bucket_all(self.cfg, dry_run=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["deleted"], 1)
        self.assertTrue(f.exists(), "dry_run ne doit RIEN supprimer")

    def test_purge_all_no_bucket(self) -> None:
        res = purge_review_bucket_all(self.cfg)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("no_bucket"))

    def test_orphan_manifest_tmp_not_counted_as_film(self) -> None:
        """Audit 2026-07-09 : un `.tmp.<pid>.<tid>` orphelin laisse par un crash
        de _save_ttl_manifest ne doit pas etre compte comme un film de quarantaine
        dans l'inventaire du viewer (ni inscrit au manifest d'arrivee)."""
        _write_file(self.root / "_review" / "MyFilm" / "movie.mkv", days_ago=1)
        review = self.root / "_review"
        review.mkdir(parents=True, exist_ok=True)
        orphan = review / f"{_TTL_MANIFEST_NAME}.tmp.12345.67890"
        orphan.write_text("{}", encoding="utf-8")

        listing = list_review_bucket_files(self.cfg)
        rels = {f["rel"] for f in listing["files"]}
        self.assertNotIn(orphan.name, rels)
        self.assertIn("MyFilm/movie.mkv", rels)
        self.assertEqual(listing["files_count"], 1, "seul le vrai film doit compter")

        # L'orphelin ne doit pas non plus etre inscrit au manifest d'arrivee.
        manifest = json.loads((review / _TTL_MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertNotIn(orphan.name, manifest)


class StartQuarantineTtlCronTests(unittest.TestCase):
    def test_cron_disabled_when_ttl_zero(self) -> None:
        api = SimpleNamespace()
        thread = start_quarantine_ttl_cron(api, ttl_days=0)
        self.assertIsNone(thread)

    def test_cron_disabled_when_ttl_negative(self) -> None:
        api = SimpleNamespace()
        thread = start_quarantine_ttl_cron(api, ttl_days=-1)
        self.assertIsNone(thread)

    def test_cron_disabled_when_ttl_invalid(self) -> None:
        api = SimpleNamespace()
        # ttl_days="abc" -> fallback DEFAULT_TTL_DAYS=30 (pas 0 donc demarre).
        # On test ici avec un type strictement invalide qui catch dans int().
        thread = start_quarantine_ttl_cron(api, ttl_days="abc")  # type: ignore[arg-type]
        # Le fallback DEFAULT_TTL_DAYS=30 demarre un thread daemon
        self.assertIsNotNone(thread)
        self.assertTrue(thread.daemon)

    def test_cron_returns_daemon_thread_when_valid(self) -> None:
        # api.run.purge_quarantine_bucket existe mais on ne veut PAS l'invoquer
        # (initial_delay tres long pour eviter le 1er passage).
        calls = []

        class _FakeRun:
            def purge_quarantine_bucket(self, ttl_days: int):
                calls.append(ttl_days)
                return {"ok": True, "deleted": 0}

        api = SimpleNamespace(run=_FakeRun())
        thread = start_quarantine_ttl_cron(
            api, ttl_days=30, initial_delay_s=60.0, interval_s=3600.0
        )
        try:
            self.assertIsNotNone(thread)
            self.assertTrue(thread.is_alive())
            self.assertTrue(thread.daemon)
            self.assertEqual(thread.name, "cinesort-quarantine-ttl")
        finally:
            # Cleanup : pose le stop event pour arreter le thread
            stop_event = getattr(api, "_quarantine_ttl_stop", None)
            if stop_event is not None:
                stop_event.set()


class TriggerNowTests(unittest.TestCase):
    def test_trigger_now_calls_api_run(self) -> None:
        calls = []

        class _FakeRun:
            def purge_quarantine_bucket(self, ttl_days: int):
                calls.append(ttl_days)
                return {"ok": True, "deleted": 7}

        api = SimpleNamespace(run=_FakeRun())
        trigger_now(api, ttl_days=15)
        self.assertEqual(calls, [15])

    def test_trigger_now_swallows_attribute_error(self) -> None:
        # api sans facade.run -> ne doit pas exploser.
        api = SimpleNamespace()
        trigger_now(api, ttl_days=15)  # noqa : assert pas d'exception

    def test_trigger_now_swallows_runtime_error(self) -> None:
        class _BoomRun:
            def purge_quarantine_bucket(self, ttl_days: int):
                raise RuntimeError("boom")

        api = SimpleNamespace(run=_BoomRun())
        trigger_now(api, ttl_days=15)  # noqa : assert pas d'exception


class DefaultTtlDaysTests(unittest.TestCase):
    def test_default_is_30_days(self) -> None:
        self.assertEqual(DEFAULT_TTL_DAYS, 30)


if __name__ == "__main__":
    unittest.main()
