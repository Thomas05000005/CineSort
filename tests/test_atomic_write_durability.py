"""Durabilite des ecritures : un SEUL helper porte les deux invariants.

Issues #511 / #820 (state.atomic_write_json sans fsync), #622 + #732 (tmdb :
purge sans fsync + `.tmp` fixe partage entre deux ecrivains concurrents), #692
(probe/disk_cache sans fsync), #712 (poster_proxy `.tmp` fixe sous
ThreadingHTTPServer), #787 (updater write_text en place), #822 (export .nfo
write_text en place).

Le depot avait les deux bonnes moities de l'invariant, jamais ensemble :
`omdb_client._save_cache_atomic` faisait flush+fsync+controle de taille avec un
`.tmp` FIXE, `state.py` et `probe/disk_cache.py` faisaient le `.tmp` UNIQUE sans
aucun fsync. Chaque nouveau site recopiait une moitie au hasard.

Ce fichier verrouille la famille entiere : la classe `TestTousLesSitesRoutes`
passe en revue les 7 sites d'ecriture et exige des DEUX invariants a chaque
fois. Un site qui reimplemente sa propre variante (ou qui revient a
`write_text`) fait echouer sa ligne du tableau.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from cinesort.app import export_support, updater
from cinesort.infra import tmdb_client
from cinesort.infra.integrations import poster_proxy
from cinesort.infra.probe import disk_cache
from cinesort.infra.state import (
    ATOMIC_TMP_INFIX,
    AtomicWriteError,
    atomic_tmp_path,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)


@contextlib.contextmanager
def capture_atomic_io():
    """Enregistre les os.fsync / os.replace reellement executes.

    Les deux syscalls sont appeles pour de vrai (`wraps`) : on observe, on ne
    simule pas. Un site qui n'appelle pas fsync, ou qui promeut un `.tmp` de nom
    fixe, est visible dans le journal retourne.
    """
    journal: Dict[str, Any] = {"fsync": 0, "replace_sources": [], "order": []}
    real_fsync = os.fsync
    real_replace = os.replace

    def fake_fsync(fd):
        journal["fsync"] += 1
        journal["order"].append("fsync")
        return real_fsync(fd)

    def fake_replace(src, dst, *args, **kwargs):
        journal["replace_sources"].append(str(src))
        journal["order"].append("replace")
        return real_replace(src, dst, *args, **kwargs)

    with mock.patch("os.fsync", fake_fsync), mock.patch("os.replace", fake_replace):
        yield journal


class _AtomicAssertions(unittest.TestCase):
    """Les deux invariants, exiges site par site."""

    def assert_durable(self, journal: Dict[str, Any], label: str) -> None:
        """Invariant 2 : flush + fsync AVANT le rename."""
        self.assertGreaterEqual(
            journal["fsync"],
            1,
            f"{label} : aucun os.fsync -> un crash entre le write et le rename "
            f"peut promouvoir un fichier tronque (issues #511/#622/#692/#787/#822)",
        )
        self.assertTrue(
            journal["replace_sources"],
            f"{label} : aucun os.replace -> l'ecriture n'est pas atomique du tout",
        )
        self.assertLess(
            journal["order"].index("fsync"),
            journal["order"].index("replace"),
            f"{label} : fsync appele APRES os.replace -> ne protege rien",
        )

    def assert_tmp_unique(self, journal: Dict[str, Any], label: str) -> None:
        """Invariant 1 : nom de `.tmp` unique par process/thread/instant."""
        for src in journal["replace_sources"]:
            name = Path(src).name
            self.assertIn(
                ATOMIC_TMP_INFIX,
                name,
                f"{label} : le fichier promu ({name}) n'est pas un temporaire du helper commun",
            )
            self.assertIn(
                str(os.getpid()),
                name,
                f"{label} : nom de .tmp SANS pid -> deux ecrivains concurrents "
                f"partagent le meme fichier intermediaire (CWE-362, issues #712/#732)",
            )
            self.assertIn(
                str(threading.get_ident()),
                name,
                f"{label} : nom de .tmp SANS identifiant de thread -> collision "
                f"entre threads du meme process (issues #712/#732)",
            )

    def assert_both_invariants(self, journal: Dict[str, Any], label: str) -> None:
        self.assert_durable(journal, label)
        self.assert_tmp_unique(journal, label)


class TestHelperCanonique(_AtomicAssertions):
    """Le couple `atomic_write_bytes` / `atomic_write_json` lui-meme."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_atomic_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tmp_names_are_unique(self) -> None:
        target = self.root / "cible.json"
        names = {atomic_tmp_path(target).name for _ in range(500)}
        self.assertEqual(len(names), 500, "atomic_tmp_path doit produire un nom different a chaque appel")

    def test_concurrent_writers_never_share_a_tmp(self) -> None:
        target = self.root / "concurrent.json"
        target.write_text("{}", encoding="utf-8")
        seen: List[str] = []
        lock = threading.Lock()
        real_replace = os.replace

        def recording_replace(src, dst, *a, **kw):
            with lock:
                seen.append(str(src))
            return real_replace(src, dst, *a, **kw)

        # Aucune tolerance : un ecrivain qui echoue a basculer a PERDU son
        # ecriture, la cible garde son ancienne valeur et l'appelant croit avoir
        # ecrit. Ce test a d'abord tolere ces echecs — ce qui echangeait un
        # defaut de corruption contre un defaut de perte silencieuse. La bonne
        # reponse etait de renforcer la politique de retentative (12 essais,
        # backoff exponentiel + jitter, mesures de PR#718 : 0 echec sur 32
        # threads) plutot que d'abaisser l'exigence du test.
        errors: List[BaseException] = []

        def worker(i: int) -> None:
            try:
                atomic_write_json(target, {"writer": i})
            except BaseException as exc:  # noqa: BLE001 — remonte au thread principal
                with lock:
                    errors.append(exc)

        with mock.patch("os.replace", recording_replace):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(
            errors,
            [],
            "un ecrivain concurrent a echoue : son ecriture est PERDUE, la cible garde son ancienne valeur",
        )
        # `seen` peut contenir plus de 32 entrees : sous Windows os.replace est
        # retente quand un lecteur tient la cible (R8-026). Ce sont les memes
        # chemins, d'ou l'assertion sur le nombre de tmp DISTINCTS.
        self.assertEqual(
            len(set(seen)),
            32,
            "deux ecrivains concurrents ont utilise le MEME .tmp -> l'un peut promouvoir le contenu de l'autre",
        )
        # Le contenu final reste un JSON valide (jamais un melange des deux).
        self.assertIn("writer", json.loads(target.read_text(encoding="utf-8")))

    def test_fsync_before_replace(self) -> None:
        target = self.root / "durable.json"
        with capture_atomic_io() as journal:
            atomic_write_json(target, {"a": 1})
        self.assert_both_invariants(journal, "atomic_write_json")

    def test_truncated_tmp_is_never_promoted(self) -> None:
        """Le controle de taille doit refuser de promouvoir un tmp tronque."""
        target = self.root / "cible.txt"
        target.write_text("ANCIEN CONTENU VALIDE", encoding="utf-8")
        real_fsync = os.fsync

        def truncating_fsync(fd):
            # Simule le cas reel : les octets ne sont pas arrives sur le disque
            # (coupure secteur, NAS qui decroche) -> le tmp est vide au moment
            # ou os.replace le promouvrait.
            real_fsync(fd)
            os.ftruncate(fd, 0)

        with mock.patch("os.fsync", truncating_fsync):
            with self.assertRaises(AtomicWriteError):
                atomic_write_text(target, "NOUVEAU CONTENU")

        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "ANCIEN CONTENU VALIDE",
            "un tmp tronque a ete promu : l'utilisateur a PERDU son ancien fichier valide",
        )
        self.assertEqual([p.name for p in self.root.iterdir()], ["cible.txt"], "un .tmp orphelin subsiste")

    def test_partially_truncated_tmp_is_never_promoted(self) -> None:
        """Troncature PARTIELLE : le cas « NAS qui decroche a mi-chemin ».

        Le controle de taille pose deux conditions, `written == 0` OU
        `written != len(data)`. Le test ci-dessus ne fabrique qu'un tmp VIDE,
        donc seule la premiere etait exercee : muter la garde en
        `if written == 0:` laissait toute la batterie verte. Or c'est la
        troncature partielle que la docstring du helper annonce couvrir, et
        c'est la plus perfide — un JSON coupe en deux reste un fichier
        d'apparence normale, alors qu'un fichier vide se remarque.
        """
        target = self.root / "cible.txt"
        target.write_text("ANCIEN CONTENU VALIDE", encoding="utf-8")
        real_fsync = os.fsync

        def truncating_fsync(fd):
            real_fsync(fd)
            # 3 octets au lieu du contenu complet : non vide, mais incomplet.
            os.ftruncate(fd, 3)

        with mock.patch("os.fsync", truncating_fsync):
            with self.assertRaises(AtomicWriteError):
                atomic_write_text(target, "NOUVEAU CONTENU")

        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "ANCIEN CONTENU VALIDE",
            "un tmp PARTIELLEMENT tronque a ete promu : le fichier de l'utilisateur est corrompu",
        )
        self.assertEqual([p.name for p in self.root.iterdir()], ["cible.txt"], "un .tmp orphelin subsiste")

    def test_no_tmp_left_behind_on_success(self) -> None:
        target = self.root / "ok.json"
        atomic_write_json(target, {"a": 1})
        self.assertEqual([p.name for p in self.root.iterdir()], ["ok.json"])

    # --- non-regression : verte AVANT comme APRES le correctif ---------------

    def test_content_roundtrip_is_unchanged(self) -> None:
        target = self.root / "roundtrip.json"
        payload = {"titre": "Amelie Poulain", "annee": 2001, "accents": "eaiou"}
        atomic_write_json(target, payload)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        atomic_write_bytes(target, b"\x00\x01binaire")
        self.assertEqual(target.read_bytes(), b"\x00\x01binaire")


class TestTousLesSitesRoutes(_AtomicAssertions):
    """Les 7 sites d'ecriture passent bien par le helper commun.

    C'est le test qui empeche la famille de se reconstituer : un site qui
    reimplemente sa propre ecriture (ou revient a `write_text`) perd fsync,
    l'unicite du tmp, ou les deux.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_atomic_sites_")
        self.root = Path(self._tmp.name)
        self._prev_cache_dir = os.environ.get("CINESORT_PROBE_CACHE_DIR")
        os.environ["CINESORT_PROBE_CACHE_DIR"] = str(self.root / "probe")

    def tearDown(self) -> None:
        if self._prev_cache_dir is None:
            os.environ.pop("CINESORT_PROBE_CACHE_DIR", None)
        else:
            os.environ["CINESORT_PROBE_CACHE_DIR"] = self._prev_cache_dir
        self._tmp.cleanup()

    # 1. cinesort/infra/state.py : atomic_write_json (#511, #820)
    def test_site_state_atomic_write_json(self) -> None:
        with capture_atomic_io() as journal:
            atomic_write_json(self.root / "validation.json", {"rows": []})
        self.assert_both_invariants(journal, "state.atomic_write_json")

    # 2. cinesort/infra/tmdb_client.py : TmdbClient._save_cache_atomic (#732)
    def test_site_tmdb_save_cache(self) -> None:
        cache_path = self.root / "tmdb_cache.json"
        client = tmdb_client.TmdbClient(api_key="x", cache_path=cache_path)
        client._cache["movie|1"] = {"_cached_at": time.time(), "value": {"poster_path": "/p.jpg"}}
        client._dirty = True
        with capture_atomic_io() as journal:
            client._save_cache_atomic(force=True)
        self.assert_both_invariants(journal, "tmdb_client.TmdbClient._save_cache_atomic")

    # 3. cinesort/infra/tmdb_client.py : purge_expired_tmdb_cache (#622, #732)
    def test_site_tmdb_purge(self) -> None:
        cache_path = self.root / "tmdb_cache.json"
        expired = time.time() - (400 * 24 * 3600)
        cache_path.write_text(
            json.dumps({"movie|1": {"_cached_at": expired, "value": {"poster_path": "/p.jpg"}}}),
            encoding="utf-8",
        )
        with capture_atomic_io() as journal:
            result = tmdb_client.purge_expired_tmdb_cache(cache_path, ttl_days=1)
        self.assertEqual(result["purged"], 1)
        self.assertIsNone(result["error"])
        self.assert_both_invariants(journal, "tmdb_client.purge_expired_tmdb_cache")

    # 4. cinesort/infra/integrations/poster_proxy.py : _atomic_write (#712)
    def test_site_poster_proxy(self) -> None:
        target = self.root / "posters" / "w185" / "603.jpg"
        with capture_atomic_io() as journal:
            poster_proxy._atomic_write(target, b"\xff\xd8\xff-jpeg-bytes")
        self.assertEqual(target.read_bytes(), b"\xff\xd8\xff-jpeg-bytes")
        self.assert_both_invariants(journal, "poster_proxy._atomic_write")

    # 5. cinesort/infra/probe/disk_cache.py : upsert_disk_cache (#692)
    def test_site_probe_disk_cache(self) -> None:
        with capture_atomic_io() as journal:
            ok = disk_cache.upsert_disk_cache(
                path="C:/films/Inception.mkv",
                size=123,
                mtime=1.0,
                tool="ffprobe",
                raw_json={"streams": []},
                normalized_json={"width": 1920},
            )
        self.assertTrue(ok)
        self.assert_both_invariants(journal, "probe.disk_cache.upsert_disk_cache")

    # 6. cinesort/app/updater.py : _write_cache (#787)
    def test_site_updater_cache(self) -> None:
        cache_path = self.root / "update_cache.json"
        with capture_atomic_io() as journal:
            updater._write_cache(cache_path, {"tag_name": "v1.5.3"})
        self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8"))["payload"]["tag_name"], "v1.5.3")
        self.assert_both_invariants(journal, "updater._write_cache")

    # 7. cinesort/app/export_support.py : export_nfo_for_run (#822)
    def test_site_export_nfo(self) -> None:
        folder = self.root / "Inception (2010)"
        folder.mkdir(parents=True)
        (folder / "film.mkv").write_bytes(b"x")
        rows = [{"folder": str(folder), "video": "film.mkv", "proposed_title": "Inception", "proposed_year": 2010}]
        with capture_atomic_io() as journal:
            res = export_support.export_nfo_for_run(rows, dry_run=False)
        self.assertEqual(res["written"], 1)
        self.assertIn("Inception", (folder / "film.nfo").read_text(encoding="utf-8"))
        self.assert_both_invariants(journal, "export_support.export_nfo_for_run")


class TestTmdbDeuxEcrivainsIsoles(unittest.TestCase):
    """#732 : les DEUX ecrivains du cache TMDb visaient le meme `.tmp` fixe.

    `TmdbClient._save_cache_atomic` (thread applicatif) et
    `purge_expired_tmdb_cache` (thread daemon lance au boot) faisaient tous les
    deux `cache_path.with_suffix('.tmp')` -> chemin identique au caractere pres.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_race_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_les_deux_ecrivains_nutilisent_pas_le_meme_tmp(self) -> None:
        expired = time.time() - (400 * 24 * 3600)
        self.cache_path.write_text(
            json.dumps({"movie|1": {"_cached_at": expired, "value": {"poster_path": "/p.jpg"}}}),
            encoding="utf-8",
        )
        client = tmdb_client.TmdbClient(api_key="x", cache_path=self.cache_path)
        client._cache["movie|2"] = {"_cached_at": time.time(), "value": {"poster_path": "/q.jpg"}}
        client._dirty = True

        with capture_atomic_io() as journal_save:
            client._save_cache_atomic(force=True)
        with capture_atomic_io() as journal_purge:
            tmdb_client.purge_expired_tmdb_cache(self.cache_path, ttl_days=1)

        save_tmps = set(journal_save["replace_sources"])
        purge_tmps = set(journal_purge["replace_sources"])
        self.assertTrue(save_tmps and purge_tmps, "les deux ecrivains doivent avoir promu un tmp")

        legacy_fixed_tmp = str(self.cache_path.with_suffix(".tmp"))
        self.assertNotIn(legacy_fixed_tmp, save_tmps | purge_tmps, "le .tmp fixe historique est de retour")
        self.assertFalse(
            save_tmps & purge_tmps,
            "sauvegarde et purge partagent encore un .tmp -> la purge au boot peut "
            "promouvoir le JSON partiel de la sauvegarde (CWE-362, issue #732)",
        )


class TestDiskCacheOrphelins(unittest.TestCase):
    """Le nom de tmp etant unique, un orphelin de crash n'est JAMAIS reecrase :
    les purges doivent donc savoir le reconnaitre, sinon il s'accumule a vie.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_orphan_")
        self.cache_dir = Path(self._tmp.name)
        self._prev = os.environ.get("CINESORT_PROBE_CACHE_DIR")
        os.environ["CINESORT_PROBE_CACHE_DIR"] = str(self.cache_dir)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("CINESORT_PROBE_CACHE_DIR", None)
        else:
            os.environ["CINESORT_PROBE_CACHE_DIR"] = self._prev
        self._tmp.cleanup()

    def _make_orphan(self) -> Path:
        orphan = self.cache_dir / f"deadbeef.json{ATOMIC_TMP_INFIX}999.888.777.abcd1234"
        orphan.write_text("{partiel", encoding="utf-8")
        return orphan

    def test_clear_removes_orphan_tmp(self) -> None:
        (self.cache_dir / "abc123.json").write_text("{}", encoding="utf-8")
        orphan = self._make_orphan()
        removed = disk_cache.clear_disk_cache()
        self.assertEqual(removed, 2)
        self.assertFalse(orphan.exists(), "un .tmp orphelin de crash survit a la purge du cache probe")

    def test_prune_removes_old_orphan_tmp(self) -> None:
        orphan = self._make_orphan()
        old = time.time() - (120 * 24 * 3600)
        os.utime(orphan, (old, old))
        removed = disk_cache.prune_disk_cache(retention_days=90)
        self.assertEqual(removed, 1)
        self.assertFalse(orphan.exists())

    def test_prune_preserves_recent_entries(self) -> None:
        """Non-regression : la retention ne doit pas devenir un wipe."""
        recent = self.cache_dir / "recent.json"
        recent.write_text("{}", encoding="utf-8")
        self.assertEqual(disk_cache.prune_disk_cache(retention_days=90), 0)
        self.assertTrue(recent.exists())


if __name__ == "__main__":
    unittest.main()
