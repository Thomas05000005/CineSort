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
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import mock

from cinesort.app import export_support, plan_support, quarantine_ttl, updater
from cinesort.domain import core
from cinesort.infra import state, tmdb_client
from cinesort.infra.integrations import poster_proxy
from cinesort.infra.probe import disk_cache
from cinesort.infra.state import (
    ATOMIC_TMP_INFIX,
    AtomicWriteError,
    atomic_tmp_path,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    is_atomic_tmp_name,
    sweep_atomic_tmp_orphans,
)
from cinesort.ui.api import library_actions_support, run_data_support, run_flow_support, tmdb_support


@contextlib.contextmanager
def capture_atomic_io():
    """Enregistre les os.fsync / os.replace reellement executes.

    Les deux syscalls sont appeles pour de vrai (`wraps`) : on observe, on ne
    simule pas. Un site qui n'appelle pas fsync, ou qui promeut un `.tmp` de nom
    fixe, est visible dans le journal retourne.
    """
    journal: Dict[str, Any] = {"fsync": 0, "replace_sources": [], "order": [], "sequence": []}
    real_fsync = os.fsync
    real_replace = os.replace

    def fake_fsync(fd):
        journal["fsync"] += 1
        journal["order"].append("fsync")
        journal["sequence"].append(("fsync", None))
        return real_fsync(fd)

    def fake_replace(src, dst, *args, **kwargs):
        journal["replace_sources"].append(str(src))
        journal["order"].append("replace")
        journal["sequence"].append(("replace", str(src)))
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

    def assert_target_written_atomically(self, journal: Dict[str, Any], target_name: str, label: str) -> List[int]:
        """Memes deux invariants, mais pour UNE cible dans un journal partage.

        Necessaire des que l'appelant fait plusieurs ecritures (le scan ecrit
        `plan.jsonl` PUIS `summary.txt`, `start_demo_mode` ecrit aussi en base
        et dans les reglages) : un `assert_durable` global serait vert des
        qu'UN SEUL des ecrivains est correct, et ne dirait rien sur celui qu'on
        veut prouver.

        L'ordre est juge sur la SEQUENCE observee — l'element qui precede
        immediatement le `os.replace` de la cible doit etre un `os.fsync` —, pas
        sur un compteur global ni sur un instant d'horloge.
        """
        prefix = f"{target_name}{ATOMIC_TMP_INFIX}"
        indices = [
            i
            for i, (kind, src) in enumerate(journal["sequence"])
            if kind == "replace" and Path(src).name.startswith(prefix)
        ]
        self.assertTrue(
            indices,
            f"{label} : aucun os.replace d'un `.tmp` derive de {target_name!r} -> "
            f"l'ecriture ne passe pas par le helper atomique commun (elle est faite en place)",
        )
        for i in indices:
            src_name = Path(journal["sequence"][i][1]).name
            self.assertIn(
                str(os.getpid()),
                src_name,
                f"{label} : nom de .tmp SANS pid -> deux ecrivains concurrents partagent le meme intermediaire",
            )
            self.assertIn(
                str(threading.get_ident()),
                src_name,
                f"{label} : nom de .tmp SANS identifiant de thread -> collision entre threads du meme process",
            )
            self.assertGreater(i, 0, f"{label} : {target_name} promu sans aucun appel prealable")
            self.assertEqual(
                journal["sequence"][i - 1][0],
                "fsync",
                f"{label} : le os.replace de {target_name} n'est pas immediatement precede d'un os.fsync -> "
                f"un crash entre l'ecriture et le rename peut promouvoir un fichier tronque",
            )
        return indices


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
            # `mock.patch("os.replace")` est GLOBAL au processus : il intercepte
            # AUSSI les publications atomiques faites par un thread de fond
            # survivant a un test anterieur (job runner, watcher, backup SQLite
            # depuis #669). Un seul de ces `os.replace` etrangers ajoutait un
            # 33e chemin distinct et faisait echouer l'assertion ci-dessous sans
            # qu'aucun des 32 ecrivains ait fauté — faux rouge observe en suite
            # complete, jamais en isolation. On ne retient donc que les
            # publications vers LA cible du test. Le pouvoir discriminant est
            # intact : tout `.tmp` des 32 ecrivains vise `target` et reste
            # compte, donc deux d'entre eux qui partageraient un `.tmp` font
            # toujours tomber le compte a 31.
            if Path(dst) == target:
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

    def test_ecrire_un_fichier_VIDE_est_legitime(self) -> None:
        """Une taille nulle DEMANDEE n'est pas une troncature.

        L'ancienne garde `written == 0 or ...` rendait impossible l'ecriture
        d'un fichier vide. Ce n'est pas un cas d'ecole : l'export NDJSON d'une
        selection de 0 film produit un contenu vide et echouait sur un
        « ecriture atomique incomplete pour ... : 0/0 octets ».
        """
        target = self.root / "vide.ndjson"
        atomic_write_text(target, "")
        self.assertTrue(target.exists(), "un fichier vide DEMANDE doit pouvoir etre ecrit")
        self.assertEqual(target.read_bytes(), b"")

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

    def test_purge_keeps_the_compact_form_of_the_other_writer(self) -> None:
        """Les DEUX ecrivains du cache TMDb doivent produire la MEME forme.

        `_save_cache_atomic` serialise en compact (PERF-6 : cache de 20 Mo
        reecrit ~750 fois par scan). La purge du boot passait par le defaut
        `indent=2` d'`atomic_write_json` et rendait donc un fichier ~2x plus
        gros, relu tel quel par `_load_cache` au demarrage suivant — et
        desormais fsynce en entier, donc paye deux fois.
        """
        cache_path = self.root / "tmdb_cache.json"
        fresh = time.time()
        expired = fresh - (400 * 24 * 3600)
        entries = {f"movie|{i}": {"_cached_at": fresh, "value": {"poster_path": f"/p{i}.jpg"}} for i in range(40)}
        entries["movie|old"] = {"_cached_at": expired, "value": {"poster_path": "/old.jpg"}}
        cache_path.write_text(json.dumps(entries), encoding="utf-8")

        result = tmdb_client.purge_expired_tmdb_cache(cache_path, ttl_days=1)
        self.assertEqual(result["purged"], 1)

        written = cache_path.read_text(encoding="utf-8")
        self.assertNotIn("\n", written, "la purge a reecrit le cache en JSON indente")
        self.assertEqual(len(json.loads(written)), 40)

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


# ---------------------------------------------------------------------------
# Ecrivains qui restaient HORS du helper (relecture adversaire, objection 1)
# ---------------------------------------------------------------------------


class TestEcrivainsRestantsRoutes(_AtomicAssertions):
    """Les 4 ecrivains a `.tmp` FIXE que la 1re passe avait laisses derriere.

    La « Reserve » de la PR affirmait qu'`omdb_client` etait le dernier `.tmp`
    fixe du depot. C'etait faux : `library_actions_support` (x2),
    `tmdb_support` et `quarantine_ttl` en portaient aussi. Les deux premiers
    sont le defaut #732 applique au `plan.jsonl` de l'utilisateur — le fichier
    que l'APPLY relit pour renommer les dossiers sur disque.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_reste_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_site_write_plan_jsonl(self) -> None:
        """Ecrivain unique des reecritures de plan.jsonl (#732 sur plan.jsonl)."""
        plan = self.root / "plan.jsonl"
        plan.write_text("", encoding="utf-8")
        rows = [{"row_id": "a", "proposed_title": "Inception"}, {"row_id": "b", "proposed_title": "Heat"}]
        with capture_atomic_io() as journal:
            run_data_support.write_plan_jsonl(plan, rows)
        self.assert_both_invariants(journal, "run_data_support.write_plan_jsonl")
        relu = [json.loads(x) for x in plan.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual(relu, rows, "le contenu du plan doit survivre au round-trip intact")

    def test_site_export_films_ndjson(self) -> None:
        """`export_films` format NDJSON (library_actions_support:1270)."""
        exports = self.root / "exports"
        exports.mkdir()
        rows = [{"row_id": "a", "title": "Inception", "year": 2010}]
        with (
            mock.patch.object(library_actions_support, "_exports_dir", return_value=exports),
            mock.patch.object(library_actions_support, "_resolve_run_id", return_value="run_42"),
            mock.patch.object(library_actions_support, "_build_library_rows", return_value=rows),
            capture_atomic_io() as journal,
        ):
            res = library_actions_support.export_films(object(), [], fmt="ndjson")
        self.assertTrue(res["ok"])
        self.assert_both_invariants(journal, "library_actions_support.export_films(ndjson)")
        produit = Path(res["file_path"]).read_bytes()
        self.assertNotIn(b"\r\n", produit, "l'export NDJSON etait explicitement en LF (newline='\\n')")

    def test_site_quarantine_ttl_manifest(self) -> None:
        """`_save_ttl_manifest` avait le tmp unique mais AUCUN fsync."""
        root = self.root / "_review"
        root.mkdir()
        with capture_atomic_io() as journal:
            quarantine_ttl._save_ttl_manifest(root, {"film.mkv": 1234.0})
        self.assert_both_invariants(journal, "quarantine_ttl._save_ttl_manifest")


class TestPlanJsonlDeuxEcrivainsIsoles(unittest.TestCase):
    """#732 sur `plan.jsonl` : la pire instance de la grappe, restee ouverte.

    `library_actions_support._rematch_tmdb_and_update_plan` et
    `tmdb_support.enrich_tmdb_ids_by_title` derivaient tous les deux
    `plan_jsonl.with_suffix(suffix + '.tmp')` du meme `run_id` — le meme chemin
    au caractere pres. Et ils sont concurrents pour de vrai : l'enrichissement
    tourne dans le thread daemon `tmdb-enrich-<run_id>` lance en fin de scan
    pendant que le rematch part d'un handler `ThreadingHTTPServer`.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_plan_race_")
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "runs" / "tri_films_run_42"
        self.run_dir.mkdir(parents=True)
        self.plan = self.run_dir / "plan.jsonl"

        self.folder = self.root / "Inception (2010)"
        self.folder.mkdir()
        (self.folder / "film.mkv").write_bytes(b"x")

        self._write_initial_plan()

        run_paths = mock.Mock()
        run_paths.plan_jsonl = self.plan
        self.api = mock.Mock()
        self.api._internal_settings.return_value = {"state_dir": str(self.root), "tmdb_api_key": "k"}
        self.api._run_paths_for.return_value = run_paths

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_initial_plan(self) -> None:
        """Remet le plan dans son etat de depart (row SANS tmdb_id).

        Necessaire entre les deux ecrivains : le rematch ecrit `tmdb_id`, apres
        quoi l'enrichissement n'aurait plus rien a resoudre et n'ecrirait pas —
        le test deviendrait vacant sans le dire.
        """
        self.plan.write_text(
            json.dumps(
                {
                    "row_id": "r1",
                    "kind": "single",
                    "folder": str(self.folder),
                    "video": "film.mkv",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _run_rematch(self) -> Dict[str, Any]:
        """Pilote le VRAI `_rematch_tmdb_and_update_plan` jusqu'a son ecriture.

        Seul le pipeline de replanification (lourd, sans rapport avec la
        durabilite) est neutralise : le corps de la fonction, y compris son
        ecriture du plan, est bien execute.
        """
        new_row = {"row_id": "r1", "proposed_title": "Inception", "proposed_year": 2010, "tmdb_id": 27205}
        with (
            mock.patch.object(library_actions_support, "_build_cfg_for_row", return_value=object()),
            mock.patch.object(library_actions_support, "_build_tmdb_client_optional", return_value=None),
            mock.patch.object(library_actions_support, "_resolve_scan_root_for_replan", return_value=None),
            mock.patch.object(library_actions_support, "_scan_subtitle_expected_languages", return_value=[]),
            mock.patch.object(plan_support, "replan_single_row", return_value=object()),
            mock.patch.object(plan_support, "plan_row_to_jsonable", return_value=dict(new_row)),
            mock.patch.object(run_data_support, "resync_run_state_rows", return_value=True),
            capture_atomic_io() as journal,
        ):
            out = library_actions_support._rematch_tmdb_and_update_plan(self.api, "run_42", "r1")
        self.assertIsNotNone(out, "le rematch doit avoir abouti, sinon le test ne prouve rien")
        return journal

    def _run_enrich(self) -> Dict[str, Any]:
        """Pilote le VRAI `enrich_tmdb_ids_by_title` jusqu'a son ecriture."""
        best = mock.Mock()
        best.id = 27205
        best.poster_path = "/p.jpg"
        fake_tmdb = mock.Mock()
        fake_tmdb.search_movie.return_value = [best]
        with (
            mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(fake_tmdb, None)),
            mock.patch.object(run_data_support, "resync_run_state_rows", return_value=True),
            capture_atomic_io() as journal,
        ):
            res = tmdb_support.enrich_tmdb_ids_by_title(self.api, "run_42", ["r1"])
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("resolved"), 1, "l'enrichissement doit avoir ecrit, sinon le test est vacant")
        return journal

    def test_les_deux_ecrivains_du_plan_sont_durables(self) -> None:
        journal_rematch = self._run_rematch()
        self._write_initial_plan()
        journal_enrich = self._run_enrich()
        for label, journal in (("rematch", journal_rematch), ("enrich", journal_enrich)):
            with self.subTest(ecrivain=label):
                self.assertGreaterEqual(journal["fsync"], 1, f"{label} : plan.jsonl promu sans fsync")
                self.assertLess(journal["order"].index("fsync"), journal["order"].index("replace"))

    def test_les_deux_ecrivains_nutilisent_pas_le_meme_tmp(self) -> None:
        rematch_tmps = set(self._run_rematch()["replace_sources"])
        self._write_initial_plan()
        enrich_tmps = set(self._run_enrich()["replace_sources"])

        self.assertTrue(rematch_tmps and enrich_tmps, "les deux ecrivains doivent avoir promu un tmp")
        legacy_fixed_tmp = str(self.plan.with_suffix(self.plan.suffix + ".tmp"))
        self.assertNotIn(
            legacy_fixed_tmp,
            {Path(p).as_posix() for p in rematch_tmps | enrich_tmps} | (rematch_tmps | enrich_tmps),
            "le .tmp fixe historique de plan.jsonl est de retour (#732)",
        )
        self.assertFalse(
            rematch_tmps & enrich_tmps,
            "rematch et enrichissement partagent encore un .tmp -> le thread "
            "daemon tmdb-enrich peut promouvoir le plan partiel du rematch, sur "
            "le fichier que l'apply relit pour renommer les dossiers (#732)",
        )


# ---------------------------------------------------------------------------
# Fuite d'orphelins introduite par le nom de .tmp unique (objection 2)
# ---------------------------------------------------------------------------


class TestBalayageOrphelins(unittest.TestCase):
    """Un `.tmp` UNIQUE n'est jamais reecrase : sans balayage, chaque crash
    laisse un residu DEFINITIF. L'ancien `.tmp` FIXE bornait les orphelins a un
    seul (le suivant le recyclait) : sans ce balayage la PR echangerait une
    borne contre une accumulation — 20 a 100 Mo par kill pour le cache TMDb.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_sweep_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _orphan(self, directory: Path, target_name: str, *, age_s: float) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        p = directory / f"{target_name}{ATOMIC_TMP_INFIX}999.888.777.abcd1234"
        p.write_text("{partiel", encoding="utf-8")
        stamp = time.time() - age_s
        os.utime(p, (stamp, stamp))
        return p

    def test_supprime_un_orphelin_ancien(self) -> None:
        orphan = self._orphan(self.root, "tmdb_cache.json", age_s=7200)
        self.assertEqual(sweep_atomic_tmp_orphans(self.root), 1)
        self.assertFalse(orphan.exists())

    def test_epargne_le_tmp_d_un_ecrivain_VIVANT(self) -> None:
        """La garde qui empeche le balayage de voler un fichier en cours.

        C'est la seule chose qui separe ce nettoyage d'une corruption : entre
        le `close()` et le `os.replace()`, le `.tmp` d'un ecrivain vivant n'a
        plus de handle ouvert et ne se distingue d'un orphelin que par sa date.
        """
        vivant = self._orphan(self.root, "tmdb_cache.json", age_s=0)
        self.assertEqual(sweep_atomic_tmp_orphans(self.root), 0)
        self.assertTrue(vivant.exists(), "le balayage a vole le .tmp d'une ecriture en cours")

    def test_ne_touche_jamais_un_fichier_qui_nest_pas_un_tmp(self) -> None:
        """Non-regression : ce balayage ne doit pas devenir un wipe de cache."""
        vrai = self.root / "tmdb_cache.json"
        vrai.write_text("{}", encoding="utf-8")
        vieux = time.time() - 90 * 24 * 3600
        os.utime(vrai, (vieux, vieux))
        film = self.root / "film.mkv"
        film.write_bytes(b"x")
        os.utime(film, (vieux, vieux))

        self.assertEqual(sweep_atomic_tmp_orphans(self.root), 0)
        self.assertTrue(vrai.exists(), "le cache REEL a ete supprime par le balayage")
        self.assertTrue(film.exists(), "un fichier video a ete supprime par le balayage")

    def test_un_fichier_utilisateur_contenant_tmp_est_epargne(self) -> None:
        """Le trou que `test_ne_touche_jamais_un_fichier_qui_nest_pas_un_tmp` laissait.

        Ce test-la utilise `film.mkv`, qui ne contient pas `.tmp.` : il passait
        donc AUSSI avec le predicat permissif `".tmp." in name`. Le cas dangereux
        est celui d'un fichier de l'utilisateur dont le nom contient la
        sous-chaine.

        Pourquoi ce n'est pas theorique : `app.py` lance
        `sweep_atomic_tmp_orphans(state_dir, recursive=True)` au demarrage, et
        les bacs de quarantaine vivent sous
        `<state_dir>/runs/tri_films_*/_review/`. Le balayage traverse donc des
        repertoires contenant les VIDEOS de l'utilisateur.

        Le filtre d'age ne protege pas ici : il vise les ecrivains vivants, or un
        fichier legitime a par construction plus d'une heure.
        """
        vieux = time.time() - 90 * 24 * 3600
        bac = self.root / "runs" / "tri_films_20260804" / "_review" / "_user_marked_for_deletion"
        bac.mkdir(parents=True, exist_ok=True)
        pieges = [
            bac / "Movie.2020.tmp.1080p.mkv",
            bac / "Film.tmp.mkv",
            self.root / "sauvegarde.tmp.2024.01.01.zip",
            # Forme correcte mais PAS en fin de nom : ce n'est pas un des notres.
            self.root / "cache.tmp.123.456.789.deadbeef.extra.mkv",
        ]
        for p in pieges:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"contenu utilisateur")
            os.utime(p, (vieux, vieux))

        self.assertEqual(sweep_atomic_tmp_orphans(self.root, recursive=True), 0)
        for p in pieges:
            self.assertTrue(p.exists(), f"fichier utilisateur supprime par le balayage : {p.name}")

    def test_un_vrai_orphelin_reste_balaye(self) -> None:
        """Contrepartie : resserrer le predicat ne doit pas le rendre inerte."""
        orphelin = self._orphan(self.root, "tmdb_cache.json", age_s=7200)
        self.assertTrue(is_atomic_tmp_name(orphelin.name), orphelin.name)
        self.assertEqual(sweep_atomic_tmp_orphans(self.root), 1)
        self.assertFalse(orphelin.exists())

    def test_target_name_restreint_a_une_seule_cible(self) -> None:
        mien = self._orphan(self.root, "film.nfo", age_s=7200)
        voisin = self._orphan(self.root, "autre.json", age_s=7200)
        self.assertEqual(sweep_atomic_tmp_orphans(self.root, target_name="film.nfo"), 1)
        self.assertFalse(mien.exists())
        self.assertTrue(voisin.exists(), "le balayage cible a debordé sur un voisin")

    def test_recursif_atteint_le_cache_posters(self) -> None:
        """`<state_dir>/cache/posters/` n'a AUCUN pruner : sans recursion, ses
        orphelins ne sont balayes par personne."""
        poster = self._orphan(self.root / "cache" / "posters" / "w185", "603.jpg", age_s=7200)
        self.assertEqual(sweep_atomic_tmp_orphans(self.root, recursive=False), 0)
        self.assertTrue(poster.exists())
        self.assertEqual(sweep_atomic_tmp_orphans(self.root, recursive=True), 1)
        self.assertFalse(poster.exists())


class TestBalayageCable(unittest.TestCase):
    """Le balayage doit etre CABLE, pas seulement disponible.

    Avant, `is_atomic_tmp_name` n'avait que 2 usages, tous deux dans
    `probe/disk_cache.py` : le cache TMDb (20-100 Mo, reecrit toutes les 2 s
    pendant un scan), le cache posters et le `.nfo` depose a cote du `.mkv`
    n'avaient aucun nettoyeur.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_sweep_cable_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _orphan(self, directory: Path, target_name: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        p = directory / f"{target_name}{ATOMIC_TMP_INFIX}999.888.777.abcd1234"
        p.write_text("residu", encoding="utf-8")
        vieux = time.time() - 7200
        os.utime(p, (vieux, vieux))
        return p

    def test_export_nfo_balaie_le_residu_visible_dans_le_dossier_du_film(self) -> None:
        """Cas le plus visible : le `.tmp` atterrit a cote du `.mkv`."""
        folder = self.root / "Inception (2010)"
        folder.mkdir()
        (folder / "film.mkv").write_bytes(b"x")
        orphan = self._orphan(folder, "film.nfo")

        rows = [{"folder": str(folder), "video": "film.mkv", "proposed_title": "Inception", "proposed_year": 2010}]
        res = export_support.export_nfo_for_run(rows, dry_run=False, overwrite=True)

        self.assertEqual(res["written"], 1)
        self.assertFalse(
            orphan.exists(),
            "un .tmp d'export interrompu reste a vie dans le dossier du film, "
            "visible par l'utilisateur et scanne par Jellyfin/Kodi",
        )
        self.assertTrue((folder / "film.mkv").exists(), "le balayage a touche au fichier video")

    def test_boot_balaie_le_state_dir_en_recursif(self) -> None:
        """Le cache TMDb (20-100 Mo) et le cache posters vivent sous state_dir."""
        cache_tmdb = self._orphan(self.root, "tmdb_cache.json")
        poster = self._orphan(self.root / "cache" / "posters" / "w185", "603.jpg")
        garde = self.root / "tmdb_cache.json"
        garde.write_text("{}", encoding="utf-8")

        api = mock.Mock()
        api._state_dir = str(self.root)
        app_entry = _load_app_entry()
        app_entry._purge_tmdb_cache_in_background(api, {"tmdb_cache_ttl_days": 30})
        _join_named_thread("cinesort-tmdb-purge")

        self.assertFalse(cache_tmdb.exists(), "orphelin de 20-100 Mo jamais balaye -> un par kill, a vie")
        self.assertFalse(poster.exists(), "le cache posters n'a aucun autre pruner")
        self.assertTrue(garde.exists(), "le balayage au boot a supprime le VRAI cache")


# ---------------------------------------------------------------------------
# Issue #479 : les 3 derniers ecrivains en place
# ---------------------------------------------------------------------------


class TestSitesIssue479(_AtomicAssertions):
    """`plan.jsonl` du scan, `summary.txt`, export CSV : ecrits EN PLACE.

    Le plus grave des trois est le premier. `plan.jsonl` n'est pas un cache :
    c'est le fichier que l'APPLY relit pour renommer et DEPLACER des dossiers
    de films. Une ecriture interrompue (disque plein, kill, antivirus) y
    laissait un JSONL tronque, et `load_rows_from_plan_jsonl` saute les lignes
    invalides SANS le dire : des films disparaissaient en silence d'un plan
    destructif. Route par le helper canonique, un echec laisse la cible
    INCHANGEE — sens restrictif.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_479_")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _plan_row(self, row_id: str, title: str) -> core.PlanRow:
        folder = self.root / "films" / f"{title} (2010)"
        folder.mkdir(parents=True, exist_ok=True)
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="film.mkv",
            proposed_title=title,
            proposed_year=2010,
            proposed_source="nfo",
            confidence=90,
            confidence_label="high",
            candidates=[core.Candidate(title=title, year=2010, tmdb_id=27205, score=90, source="tmdb")],
        )

    # --- site 1 : run_flow_support._save_plan_artifacts ----------------------

    def test_site_save_plan_artifacts(self) -> None:
        run_paths = state.new_run(self.root, "20260805_101112_a1b2c3", exclusive=True)
        rows = [self._plan_row("r1", "Inception"), self._plan_row("r2", "Heat")]
        rs = mock.Mock()
        rs.paths = run_paths
        stats = SimpleNamespace(planned_rows=2, folders_scanned=2, collections_seen=0, singles_seen=2)

        with capture_atomic_io() as journal:
            run_flow_support._save_plan_artifacts(rs, rows, stats, "C:/films", self.root, lambda *_a: None)

        rs.log.assert_not_called()  # sinon l'ecriture a echoue et le test ne prouve rien
        self.assert_target_written_atomically(journal, "plan.jsonl", "run_flow_support._save_plan_artifacts")
        self.assert_target_written_atomically(journal, "summary.txt", "run_flow_support._save_plan_artifacts")

    def test_save_plan_artifacts_contenu_inchange(self) -> None:
        """Non-regression : meme serialisation qu'avant (asdict + candidates)."""
        run_paths = state.new_run(self.root, "20260805_101113_a1b2c4", exclusive=True)
        rows = [self._plan_row("r1", "Inception"), self._plan_row("r2", "Heat")]
        rs = mock.Mock()
        rs.paths = run_paths
        stats = SimpleNamespace(planned_rows=2, folders_scanned=2, collections_seen=0, singles_seen=2)

        run_flow_support._save_plan_artifacts(rs, rows, stats, "C:/films", self.root, lambda *_a: None)

        lignes = [json.loads(x) for x in run_paths.plan_jsonl.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual([r["row_id"] for r in lignes], ["r1", "r2"])
        self.assertEqual([r["proposed_title"] for r in lignes], ["Inception", "Heat"])
        self.assertEqual(lignes[0]["candidates"][0]["tmdb_id"], 27205)
        self.assertTrue(run_paths.summary_txt.read_text(encoding="utf-8").startswith("=== RESUME ANALYSE ==="))
        self.assertEqual(
            sorted(p.name for p in run_paths.run_dir.iterdir()),
            ["plan.jsonl", "summary.txt"],
            "un .tmp orphelin subsiste dans le dossier du run",
        )

    # --- site 2 : library_actions_support.export_films(csv) ------------------

    def test_site_export_films_csv(self) -> None:
        exports = self.root / "exports"
        exports.mkdir()
        rows = [{"row_id": "a", "title": "Amelie Poulain", "year": 2001}]
        with (
            mock.patch.object(library_actions_support, "_exports_dir", return_value=exports),
            mock.patch.object(library_actions_support, "_resolve_run_id", return_value="run_42"),
            mock.patch.object(library_actions_support, "_build_library_rows", return_value=rows),
            capture_atomic_io() as journal,
        ):
            res = library_actions_support.export_films(object(), [], fmt="csv")
        self.assertTrue(res["ok"], res)
        produit = Path(res["file_path"])
        self.assert_target_written_atomically(journal, produit.name, "library_actions_support.export_films(csv)")

        # Convention Excel-FR (M15) preservee a l'octet pres : BOM + ";" + CRLF.
        raw = produit.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM UTF-8 perdu en passant par le helper")
        texte = raw.decode("utf-8-sig")
        self.assertIn("row_id;", texte.splitlines()[0])
        self.assertIn(b"\r\n", raw, "csv.writer emet du CRLF : la traduction de fin de ligne a change")
        self.assertEqual([p.name for p in exports.iterdir()], [produit.name], "un .tmp orphelin subsiste")


class TestDemoPlanJsonlDurable(_AtomicAssertions):
    """Site 3 de #479 : `start_demo_mode` ecrivait son `plan.jsonl` en place.

    Le run demo n'est pas un decor : la Bibliotheque, les Doublons et l'Apply
    le consomment par le meme chemin que n'importe quel run reel.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_479_demo_")
        self.root = Path(self._tmp.name)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        import cinesort.ui.api.cinesort_api as backend  # noqa: PLC0415 - import lourd, borne au test

        self.api = backend.CineSortApi()
        saved = self.api.settings.save_settings(
            {"root": str(self.root / "fake_root"), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.assertTrue(saved.get("ok"), saved)

    def tearDown(self) -> None:
        with contextlib.suppress(Exception):
            self.api.runtime.stop_demo_mode()
        self._tmp.cleanup()

    def test_start_demo_mode_ecrit_le_plan_atomiquement(self) -> None:
        with capture_atomic_io() as journal:
            res = self.api.runtime.start_demo_mode()
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("count"), 15, "sans les 15 films le test serait vacant")
        self.assert_target_written_atomically(journal, "plan.jsonl", "demo_support.start_demo_mode")

        run_dir = self.state_dir / "runs" / f"tri_films_{res['run_id']}"
        lignes = [json.loads(x) for x in (run_dir / "plan.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual(len(lignes), 15)
        self.assertNotIn(
            ATOMIC_TMP_INFIX,
            " ".join(p.name for p in run_dir.iterdir()),
            "un .tmp orphelin subsiste dans le dossier du run demo",
        )


def _load_app_entry() -> Any:
    """Charge `app.py` (racine du depot) sans l'ajouter a `sys.modules`."""
    import importlib.util  # noqa: PLC0415

    app_py = Path(__file__).resolve().parent.parent / "app.py"
    spec = importlib.util.spec_from_file_location("cinesort_app_entry_test", app_py)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _join_named_thread(name: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [t for t in threading.enumerate() if t.name == name]
        if not alive:
            return
        alive[0].join(timeout=deadline - time.time())
    raise AssertionError(f"le thread {name} n'a pas termine en {timeout}s")


if __name__ == "__main__":
    unittest.main()
