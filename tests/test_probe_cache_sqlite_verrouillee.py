"""Regle inviolable n4 : le cache probe tombait avec la base, sur les TROIS acces.

`sqlite3.Error` n'herite PAS d'`OSError`. Les trois `try` de
`infra/probe/service.py` qui touchent `store.probe` — lecture DB, warm-up depuis
le disque, ecriture — nommaient `(OSError, RuntimeError, TypeError, ValueError)`
et laissaient donc passer `sqlite3.OperationalError: database is locked`.

Ce sont des chemins de CACHE, pas des chemins destructifs : c'est exactement le
geste que `tests/test_sqlite_error_hors_oserror_cliquet.py` documente comme
correct. Rien n'y devient un succes silencieux — les trois sites journalisaient
deja leur echec, ils ne pouvaient simplement pas l'atteindre.

CE QUE LE DEFAUT COUTAIT, SITE PAR SITE
---------------------------------------
1. LECTURE. Le commentaire sur place nomme « lock SQLite » parmi les causes pour
   lesquelles on « tente quand meme le cache disque ». Or c'est precisement cette
   cause-la qui sortait de la fonction avant d'atteindre le repli. Le module
   `disk_cache.py` justifie pourtant son existence par ce cas : « sur partage
   reseau lent, SQLite peut subir [...] une contention WAL ; le cache disque JSON
   est independant de la DB et survit a une indisponibilite ponctuelle de
   celle-ci ». Le repli existait, il etait INATTEIGNABLE pour son cas d'usage.

2. WARM-UP. Il s'execute APRES un echec de lecture DB, donc typiquement pendant
   que la base est encore verrouillee : il perdait le hit disque qu'il venait
   d'obtenir, sur l'optimisation censee l'accompagner.

3. ECRITURE. Sa docstring promet « si l'une des deux ecritures echoue, on logue
   mais on continue ». Le cache DISQUE est ecrit JUSTE APRES la DB : sur un
   verrou, il n'etait jamais atteint et l'exception quittait `probe_file`. Un
   probe REUSSI — subprocess deja paye, metadonnees deja lues — etait alors
   perdu, et `get_quality_report` rendait « Impossible de generer le rapport
   qualite. Relance un scan ou verifie l'etat du run », un message qui accuse le
   run pour un verrou transitoire.

POURQUOI LA BATTERIE EXISTANTE NE POUVAIT PAS LE VOIR
------------------------------------------------------
La branche PARALLELE de `probe_files` nomme `sqlite3.Error` depuis R8-024 (F2-d),
avec le commentaire qui decrit la panne au mot pres : « Une OperationalError
(ecriture cache probe sur verrou DB) sortait de la boucle as_completed ». La
meme exception, sur le meme appel, etait donc TOLEREE via le pool et FATALE par
le chemin direct — celui qu'empruntent `quality_report_support`,
`probe_support`, `perceptual_support` et `runtime_probe_check`, et celui que
prend `probe_files` lui-meme des qu'il ne reste qu'un fichier a sonder.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cinesort.infra.probe.disk_cache import get_disk_cache, upsert_disk_cache
from cinesort.infra.probe.service import ProbeService, reset_tools_status_cache

_VERROU = "database is locked"

_FFPROBE_JSON: Dict[str, Any] = {
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
        {"codec_type": "audio", "codec_name": "aac", "channels": 6, "tags": {"language": "fre"}},
    ],
    "format": {
        "duration": "5400.0",
        "size": "2048",
        "bit_rate": "8000000",
        "format_name": "matroska,webm",
    },
}


class _ProbeRepoDouble:
    """Repository `store.probe` minimal : `probe_file` n'en utilise que deux methodes."""

    def __init__(
        self,
        *,
        lecture_leve: bool = False,
        ecriture_leve: bool = False,
        hit_db: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.lecture_leve = lecture_leve
        self.ecriture_leve = ecriture_leve
        self.hit_db = hit_db
        self.lectures = 0
        self.ecritures = 0

    def get_probe_cache(self, *, path: str, size: int, mtime: float, tool: str) -> Optional[Dict[str, Any]]:
        self.lectures += 1
        if self.lecture_leve:
            raise sqlite3.OperationalError(_VERROU)
        return self.hit_db

    def upsert_probe_cache(self, **kwargs: Any) -> None:
        self.ecritures += 1
        if self.ecriture_leve:
            raise sqlite3.OperationalError(_VERROU)


class _StoreDouble:
    def __init__(self, probe: _ProbeRepoDouble) -> None:
        self.probe = probe


class _RunnerEspion:
    """Runner de sonde qui COMPTE ses appels.

    Le compte est une assertion a part entiere : sur un hit de cache, il doit
    rester VIDE. Une valeur servie alors qu'aucun subprocess n'a tourne ne peut
    venir que du cache — c'est ce que le correctif produit, et rien d'autre ne le
    produit.
    """

    def __init__(self) -> None:
        self.appels: List[List[str]] = []

    def __call__(self, cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
        self.appels.append([str(x) for x in cmd])
        if any(str(a).lower() in ("-version", "--version") for a in cmd):
            return 0, "ffprobe version 7.1.1", ""
        return 0, json.dumps(_FFPROBE_JSON), ""


class _BaseProbeCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="probe_cache_verrou_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

        self._ancien_dir = os.environ.get("CINESORT_PROBE_CACHE_DIR")
        self._ancien_flag = os.environ.get("CINESORT_PROBE_DISK_CACHE")
        os.environ["CINESORT_PROBE_CACHE_DIR"] = str(self.root / "cache_probe")
        os.environ.pop("CINESORT_PROBE_DISK_CACHE", None)
        self.addCleanup(self._restaurer_env)

        self.media = self.root / "Inception (2010).mkv"
        self.media.write_bytes(b"\x00" * 2048)
        self.ffprobe = self.root / "ffprobe.exe"
        self.ffprobe.write_bytes(b"x")

        self.runner = _RunnerEspion()
        reset_tools_status_cache()
        self.addCleanup(reset_tools_status_cache)

    def _restaurer_env(self) -> None:
        self._poser_env("CINESORT_PROBE_CACHE_DIR", self._ancien_dir)
        self._poser_env("CINESORT_PROBE_DISK_CACHE", self._ancien_flag)

    @staticmethod
    def _poser_env(nom: str, valeur: Optional[str]) -> None:
        if valeur is None:
            os.environ.pop(nom, None)
        else:
            os.environ[nom] = valeur

    def _settings(self) -> Dict[str, Any]:
        return {"probe_backend": "ffprobe", "ffprobe_path": str(self.ffprobe), "mediainfo_path": ""}

    def _cle_de_cache(self) -> Dict[str, Any]:
        """La cle EXACTE que `ProbeService._cache_key` construit pour ce media."""
        st = self.media.stat()
        return {
            "path": str(self.media.resolve()),
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
            "tool": "ffprobe",
        }

    def _service(self, repo: _ProbeRepoDouble) -> ProbeService:
        return ProbeService(_StoreDouble(repo), runner=self.runner, which_fn=lambda _name: None)


class LectureSousVerrouTests(_BaseProbeCache):
    """La base verrouille -> le repli disque doit etre SERVI, pas court-circuite."""

    def test_le_hit_disque_est_servi_quand_la_db_verrouille(self) -> None:
        upsert_disk_cache(
            **self._cle_de_cache(),
            raw_json={"ffprobe": {"_source": "disque"}},
            normalized_json={"probe_quality": "OK", "duration_s": 5400.0, "_temoin": "cache-disque"},
        )
        repo = _ProbeRepoDouble(lecture_leve=True)

        # Sans le correctif, cet appel LEVE `sqlite3.OperationalError`.
        result = self._service(repo).probe_file(media_path=self.media, settings=self._settings())

        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("cache_hit"), result)
        self.assertEqual(repo.lectures, 1)
        # Le temoin n'existe que dans l'entree disque : aucune autre source de ce
        # payload ne peut le produire.
        self.assertEqual((result.get("normalized") or {}).get("_temoin"), "cache-disque", result)
        # Et aucun subprocess n'a tourne : la valeur ne vient pas d'une sonde.
        self.assertEqual(self.runner.appels, [], self.runner.appels)

    def test_la_db_saine_reste_prioritaire(self) -> None:
        """Contre-test : le correctif ne doit RIEN changer au chemin nominal.

        Sans lui, l'entree disque deviendrait la source de verite des qu'elle
        existe, ce qui remplacerait un defaut par un autre.
        """
        upsert_disk_cache(
            **self._cle_de_cache(),
            raw_json={"ffprobe": {"_source": "disque"}},
            normalized_json={"_temoin": "cache-disque"},
        )
        repo = _ProbeRepoDouble(
            hit_db={
                "raw_json": {"ffprobe": {"_source": "db"}},
                "normalized_json": {"probe_quality": "OK", "_temoin": "cache-db"},
            }
        )

        result = self._service(repo).probe_file(media_path=self.media, settings=self._settings())

        self.assertTrue(result.get("cache_hit"), result)
        self.assertEqual((result.get("normalized") or {}).get("_temoin"), "cache-db", result)
        self.assertEqual(self.runner.appels, [], self.runner.appels)


class EcritureSousVerrouTests(_BaseProbeCache):
    """La base verrouille -> le probe REUSSI doit etre rendu, et le disque ecrit."""

    def test_le_probe_reussi_survit_au_verrou_et_atteint_le_cache_disque(self) -> None:
        repo = _ProbeRepoDouble(ecriture_leve=True)

        # Sans le correctif, cet appel LEVE — apres avoir paye le subprocess.
        result = self._service(repo).probe_file(media_path=self.media, settings=self._settings())

        self.assertTrue(result.get("ok"), result)
        self.assertFalse(result.get("cache_hit"), result)
        self.assertEqual(repo.ecritures, 1)
        normalise = result.get("normalized") or {}
        # Le travail que le verrou faisait perdre : la sonde avait REUSSI.
        self.assertEqual(str((normalise.get("video") or {}).get("codec") or ""), "h264", normalise)
        self.assertEqual(normalise.get("duration_s"), 5400.0, normalise)

        # Le cache DISQUE, ecrit juste APRES la DB, a bien ete atteint : c'est la
        # promesse « best-effort » de la docstring de `_upsert_probe_cache_combined`.
        entree = get_disk_cache(**self._cle_de_cache())
        self.assertIsNotNone(entree, "le miroir disque n'a pas ete ecrit")
        self.assertIsInstance((entree or {}).get("normalized_json"), dict)

    def test_le_second_appel_sert_le_disque_sans_relancer_le_subprocess(self) -> None:
        """La consequence utile, bout a bout : base verrouillee dans les DEUX sens.

        Premier appel : la sonde tourne, la DB refuse l'ecriture, le disque prend
        le relais. Second appel : la DB refuse la lecture, et le disque evite de
        repayer le subprocess.
        """
        repo = _ProbeRepoDouble(lecture_leve=True, ecriture_leve=True)
        service = self._service(repo)

        service.probe_file(media_path=self.media, settings=self._settings())
        appels_apres_premier = len(self.runner.appels)
        self.assertGreater(appels_apres_premier, 0)

        second = service.probe_file(media_path=self.media, settings=self._settings())

        self.assertTrue(second.get("cache_hit"), second)
        self.assertEqual(len(self.runner.appels), appels_apres_premier, self.runner.appels)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
