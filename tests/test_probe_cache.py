"""ITER13 - Test du cache disque probe (zero binaire au 2eme appel).

Objectif (BILAN_ITER13 section 3.d) : prouver que
`cinesort/infra/probe/disk_cache.py` :
1. Apres un upsert, get_disk_cache(meme cle) retourne la valeur cachee.
2. Si mtime ou taille change, le cache hit est INVALIDE (rejet defense
   en profondeur).
3. Si le fichier de cache est corrompu, retour None (best-effort, ne
   casse pas le probe).
4. La version du schema sert d'invalidant : version differente -> miss.
5. Le cache est ATOMIQUE : ecriture via tmp + os.replace (pas de fichier
   corrompu si interruption).
6. Le cache peut etre desactive via CINESORT_PROBE_DISK_CACHE=0.

Test family B : pas de subprocess reel, le "0 binaire" est verifie par
le fait qu'aucun appel a un binaire externe n'est necessaire pour le hit.

Identification DECOUPLEE du probe : le cache n'est qu'une couche
secondaire. Le contenu identifie+renommable ne depend pas du cache.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.probe.disk_cache import (
    DISK_CACHE_VERSION,
    clear_disk_cache,
    get_disk_cache,
    upsert_disk_cache,
)


class _CacheBase(unittest.TestCase):
    """Base : redirige le cache vers un tmp dir isole, reset env vars."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="cinesort_test_diskcache_")
        os.environ["CINESORT_PROBE_CACHE_DIR"] = self._tmpdir
        os.environ.pop("CINESORT_PROBE_DISK_CACHE", None)

    def tearDown(self) -> None:
        os.environ.pop("CINESORT_PROBE_CACHE_DIR", None)
        os.environ.pop("CINESORT_PROBE_DISK_CACHE", None)
        # Cleanup recursif.
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestCacheHitSansBinaire(_CacheBase):
    """Le 2eme appel sur meme cle (path+size+mtime+tool) retourne le cache."""

    def test_upsert_puis_get_hit(self) -> None:
        key = dict(path="/fake/inception.mkv", size=1024, mtime=1234.5, tool="ffprobe")
        raw = {"streams": [{"codec_name": "hevc"}]}
        normalized = {"video": {"codec": "hevc"}, "probe_quality": "FULL"}
        ok = upsert_disk_cache(**key, raw_json=raw, normalized_json=normalized, ts=1700000000.0)
        self.assertTrue(ok, "Ecriture cache doit reussir")

        hit = get_disk_cache(**key)
        self.assertIsNotNone(hit, "Le 2eme appel doit hit")
        assert hit is not None  # mypy
        self.assertEqual(hit["raw_json"], raw)
        self.assertEqual(hit["normalized_json"], normalized)
        self.assertEqual(hit["size"], 1024)
        self.assertEqual(hit["mtime"], 1234.5)
        self.assertEqual(hit["tool"], "ffprobe")

    def test_cache_hit_zero_appel_subprocess(self) -> None:
        """Verifie que get_disk_cache n'execute AUCUN subprocess externe.

        On patche subprocess.Popen pour lever ; si get_disk_cache l'appelle
        le test echoue.
        """
        key = dict(path="/fake/f.mkv", size=42, mtime=1.0, tool="mediainfo")
        upsert_disk_cache(**key, raw_json={"a": 1}, normalized_json={"b": 2})

        with (
            patch("subprocess.Popen", side_effect=AssertionError("Cache ne doit PAS spawn de subprocess")),
            patch("subprocess.run", side_effect=AssertionError("Cache ne doit PAS run de subprocess")),
        ):
            hit = get_disk_cache(**key)
        self.assertIsNotNone(hit)


class TestInvalidationParChangement(_CacheBase):
    """Si la cle change (mtime ou size), le cache est invalide."""

    def test_mtime_change_invalide(self) -> None:
        upsert_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="ffprobe",
            raw_json={"r": 1},
            normalized_json={"n": 1},
        )
        # mtime change : doit miss (hash key different).
        miss = get_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=2.0,
            tool="ffprobe",
        )
        self.assertIsNone(miss, "Mtime change -> cache invalide")

    def test_size_change_invalide(self) -> None:
        upsert_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="ffprobe",
            raw_json={"r": 1},
            normalized_json={"n": 1},
        )
        miss = get_disk_cache(
            path="/fake/f.mkv",
            size=2048,
            mtime=1.0,
            tool="ffprobe",
        )
        self.assertIsNone(miss, "Size change -> cache invalide")

    def test_tool_change_invalide(self) -> None:
        """Cache par tool : ffprobe et mediainfo ne partagent pas le hit."""
        upsert_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="ffprobe",
            raw_json={"r": 1},
            normalized_json={"n": 1},
        )
        miss = get_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="mediainfo",
        )
        self.assertIsNone(miss, "Tool different -> cache miss")


class TestResilience(_CacheBase):
    """Cache best-effort : fichier corrompu ou taille anormale -> None."""

    def test_fichier_corrompu_retourne_none(self) -> None:
        key = dict(path="/fake/f.mkv", size=1024, mtime=1.0, tool="ffprobe")
        upsert_disk_cache(**key, raw_json={"r": 1}, normalized_json={"n": 1})

        # Corrompt tous les fichiers cache.
        cache_dir = Path(self._tmpdir)
        for entry in cache_dir.glob("*.json"):
            entry.write_text("NOT-JSON-AT-ALL{{{", encoding="utf-8")

        result = get_disk_cache(**key)
        self.assertIsNone(result, "Fichier cache corrompu -> miss silencieux")

    def test_version_differente_retourne_none(self) -> None:
        """Si version schema change, cache obsolete invalide."""
        key = dict(path="/fake/f.mkv", size=1024, mtime=1.0, tool="ffprobe")
        upsert_disk_cache(**key, raw_json={"r": 1}, normalized_json={"n": 1})

        # Patch la version pour simuler upgrade.
        cache_dir = Path(self._tmpdir)
        for entry in cache_dir.glob("*.json"):
            data = json.loads(entry.read_text(encoding="utf-8"))
            data["version"] = DISK_CACHE_VERSION + 99
            entry.write_text(json.dumps(data), encoding="utf-8")

        result = get_disk_cache(**key)
        self.assertIsNone(result, "Version schema differente -> miss")

    def test_cache_desactive_via_env(self) -> None:
        os.environ["CINESORT_PROBE_DISK_CACHE"] = "0"
        ok = upsert_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="ffprobe",
            raw_json={"r": 1},
            normalized_json={"n": 1},
        )
        self.assertFalse(ok, "Cache desactive : upsert no-op")
        hit = get_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="ffprobe",
        )
        self.assertIsNone(hit, "Cache desactive : get retourne None")

    def test_path_inexistant_dans_cache_dir_retourne_none(self) -> None:
        """get_disk_cache sur cle jamais ecrite -> None propre, pas d'exception."""
        result = get_disk_cache(
            path="/fake/never-seen.mkv",
            size=1,
            mtime=1.0,
            tool="ffprobe",
        )
        self.assertIsNone(result)


class TestAtomicite(_CacheBase):
    """Ecriture atomique : tmp + os.replace evite corruption en cas crash."""

    def test_upsert_ecrit_un_seul_fichier_final(self) -> None:
        upsert_disk_cache(
            path="/fake/f.mkv",
            size=1024,
            mtime=1.0,
            tool="ffprobe",
            raw_json={"r": 1},
            normalized_json={"n": 1},
        )
        cache_dir = Path(self._tmpdir)
        # Apres ecriture reussie, AUCUN fichier .tmp ne doit subsister.
        tmps = list(cache_dir.glob("*.tmp.*"))
        self.assertEqual(tmps, [], "Aucun .tmp residuel apres ecriture reussie")
        finals = list(cache_dir.glob("*.json"))
        self.assertEqual(len(finals), 1, "Un seul .json final ecrit")


class TestPurge(_CacheBase):
    """Purge totale du cache."""

    def test_clear_supprime_tout(self) -> None:
        for i in range(5):
            upsert_disk_cache(
                path=f"/fake/f{i}.mkv",
                size=1024 + i,
                mtime=1.0,
                tool="ffprobe",
                raw_json={"r": i},
                normalized_json={"n": i},
            )
        cache_dir = Path(self._tmpdir)
        self.assertEqual(len(list(cache_dir.glob("*.json"))), 5)

        n = clear_disk_cache()
        self.assertEqual(n, 5)
        self.assertEqual(list(cache_dir.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
