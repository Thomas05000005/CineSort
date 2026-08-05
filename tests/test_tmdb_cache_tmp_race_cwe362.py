"""PR #736 (CWE-362) — le fichier .tmp du cache TMDb doit etre unique par writer.

Deux chemins ecrivent le meme `<state_dir>/tmdb_cache.json` en meme temps :
- `TmdbClient._save_cache_atomic` (scan, poster_proxy...)
- `purge_expired_tmdb_cache`, lance au boot dans le thread daemon
  `cinesort-tmdb-purge` (app.py).

Tant que les deux utilisaient le meme `.tmp` a nom fixe, l'un tronquait le `.tmp`
de l'autre en plein ecriture, puis les `os.replace` s'enchainaient : promotion
d'un JSON partiel ou echec du rename. `os.replace` est atomique mais ne protege
pas d'un `.tmp` source partage.

L'unicite est desormais fournie par `cinesort.infra.state.atomic_write_*`
(PR #857), a qui les DEUX sites delegent : ces tests verifient la propriete
OBSERVABLE (aucun `.tmp` partage, la purge survit a une sauvegarde client
intercalee), pas l'implementation qui la produit. Ils echouent si l'un des deux
sites revient a un `.tmp` a nom fixe.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.state import is_atomic_tmp_name
from cinesort.infra.tmdb_client import TmdbClient, purge_expired_tmdb_cache


class TmdbCacheTmpUniquePerWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmp_race_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"
        self.fixed_tmp = self.cache_path.with_suffix(".tmp")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_disk_cache(self) -> None:
        """Cache disque avec 1 entree fraiche + 1 entree expiree (declenche la purge)."""
        now = time.time()
        payload = {
            "movie|1": {"_cached_at": now, "value": {"poster_path": "/fresh.jpg"}},
            "movie|2": {
                "_cached_at": now - (40 * 24 * 3600),
                "value": {"poster_path": "/old.jpg"},
            },
        }
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_tmp_names_are_unique_across_writers_and_writes(self) -> None:
        """Aucun writer n'utilise le .tmp a nom fixe, et deux ecritures ne le partagent pas."""
        self._seed_disk_cache()
        sources: list[Path] = []
        real_replace = os.replace  # capture avant patch : mock.patch remplace os.replace globalement

        def _spy_replace(src, dst):
            sources.append(Path(src))
            return real_replace(src, dst)

        client = TmdbClient(api_key="x", cache_path=self.cache_path)
        with mock.patch("cinesort.infra.tmdb_client.os.replace", side_effect=_spy_replace):
            client._cache["movie|3"] = {"_cached_at": time.time(), "value": {"poster_path": "/a.jpg"}}
            client._dirty = True
            client._save_cache_atomic(force=True)

            client._cache["movie|4"] = {"_cached_at": time.time(), "value": {"poster_path": "/b.jpg"}}
            client._dirty = True
            client._save_cache_atomic(force=True)

            result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)

        self.assertIsNone(result["error"])
        self.assertEqual(len(sources), 3, "2 sauvegardes client + 1 purge doivent renommer un tmp")
        for src in sources:
            self.assertNotEqual(
                src,
                self.fixed_tmp,
                f"tmp a nom fixe partage entre writers (CWE-362) : {src}",
            )
        self.assertEqual(
            len(set(sources)),
            len(sources),
            f"deux ecritures ont partage le meme tmp : {sources}",
        )
        # Le nom unique doit rester BALAYABLE : `sweep_atomic_tmp_orphans`
        # (app.py, au demarrage) ne reconnait un orphelin que sur la forme
        # EXACTE `<cible>.tmp.<pid>.<thread>.<ns>.<uuid8>`. Un schema maison
        # (ex `with_suffix(".tmp.<pid>.<ns>")`) supprimerait bien la course
        # mais rendrait chaque residu de crash INVISIBLE au balayeur, donc
        # definitif — sur un cache de 20 a 100 Mo reecrit toutes les 2 s.
        for src in sources:
            self.assertTrue(
                is_atomic_tmp_name(src.name),
                f"tmp non reconnu par sweep_atomic_tmp_orphans (orphelin definitif) : {src.name}",
            )

    def test_purge_survives_concurrent_client_save(self) -> None:
        """Course reelle : le client sauvegarde entre le write du tmp de la purge et son rename.

        Avec un .tmp partage, le client tronquait puis consommait (os.replace) le tmp
        de la purge -> le rename de la purge levait FileNotFoundError -> write_error.
        Avec un tmp unique par writer, les deux ecritures sont independantes.

        POINT D'INJECTION — il a change avec la fusion de #857. La purge
        n'ecrit plus son tmp via `Path.write_text` mais via un `open(..., "wb")`
        au fond d'`atomic_write_bytes` : se brancher sur `Path.write_text`
        n'intercalait plus RIEN et le test devenait vacant (il passait en
        n'ayant jamais declenche la course). On se branche donc sur
        `os.replace`, primitive de bascule commune aux deux ecrivains : le spy
        s'execute APRES l'ecriture complete + fsync du tmp de la purge et AVANT
        sa promotion, c'est-a-dire exactement dans la fenetre visee. Les
        assertions metier sont inchangees.
        """
        self._seed_disk_cache()
        client = TmdbClient(api_key="x", cache_path=self.cache_path)
        client._cache["movie|9"] = {"_cached_at": time.time(), "value": {"poster_path": "/c.jpg"}}
        client._dirty = True

        real_replace = os.replace  # capture avant patch : mock.patch remplace os.replace globalement
        state: dict[str, object] = {"fired": False, "purge_tmp": None}

        def _client_save_then_replace(src, dst):
            # Le tmp de la purge est ecrit et fsynce, son rename n'a pas encore
            # eu lieu : on intercale la sauvegarde client. `fired` est arme
            # AVANT l'appel pour que le os.replace de cette sauvegarde imbriquee
            # ne re-declenche pas l'injection.
            if not state["fired"]:
                state["fired"] = True
                state["purge_tmp"] = Path(src)
                client._save_cache_atomic(force=True)
            return real_replace(src, dst)

        with mock.patch("cinesort.infra.state.os.replace", side_effect=_client_save_then_replace):
            result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)

        self.assertTrue(state["fired"], "la sauvegarde client concurrente n'a pas ete declenchee")
        self.assertNotEqual(
            state["purge_tmp"],
            self.fixed_tmp,
            "la purge a promu le .tmp a nom fixe partage (CWE-362)",
        )
        self.assertIsNone(
            result["error"],
            f"la purge a perdu son tmp au profit du writer concurrent : {result['error']}",
        )
        # Le cache final reste un JSON complet et lisible (pas de troncature).
        on_disk = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIsInstance(on_disk, dict)
        # Aucun tmp orphelin ne subsiste dans le state dir. Le motif couvre les
        # DEUX formes possibles (`tmdb_cache.tmp*` d'avant, `tmdb_cache.json.tmp.*`
        # produite par atomic_tmp_path) : un glob trop etroit ne verifierait rien.
        leftovers = [p.name for p in Path(self._tmp.name).glob("tmdb_cache*tmp*")]
        self.assertEqual(leftovers, [], f"tmp orphelins : {leftovers}")


if __name__ == "__main__":
    unittest.main()
