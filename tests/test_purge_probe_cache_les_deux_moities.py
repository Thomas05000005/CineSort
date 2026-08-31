"""Le cache de sonde a DEUX moities — « Vider le cache de sonde » n'en vidait qu'une.

`ProbeService._upsert_probe_cache_combined` ecrit la MEME entree dans la base ET
dans `<state_dir>/cache/probe/<hash>.json` ; en lecture,
`_get_probe_cache_combined` interroge la base PUIS retombe sur le disque, et
RE-PROMEUT en base ce qu'il y trouve (warm-up). Vider la seule base ne purgeait
donc rien de durable : la purge etait annulee entree par entree au premier acces
suivant, et le message « relance un scan pour re-probe les films » etait faux —
le scan relisait le disque au lieu de re-sonder.

Second defaut, dans le meme geste : `clear_disk_cache` et `prune_disk_cache`
consultaient `_disk_cache_enabled()` et rendaient donc **0 sur un repertoire
plein** des que `CINESORT_PROBE_DISK_CACHE=0`. Le drapeau gouverne la PRODUCTION
d'entrees, pas leur nettoyage : le poser, c'est justement ne plus vouloir de ce
cache. Les deux classes du bas separent les deux roles pour qu'un futur
correctif ne retire pas la garde des DEUX cotes.

Les fixtures sont produites par le code de PRODUCTION (`upsert_disk_cache`) et
non ecrites a la main : c'est la parade du depot contre la forme imaginee.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.probe import disk_cache

#: Horodatage largement au-dela de la retention testee (90 jours).
_AGE_HORS_RETENTION_S = 120 * 24 * 3600


def _restaurer(nom: str, valeur: Optional[str]) -> None:
    if valeur is None:
        os.environ.pop(nom, None)
    else:
        os.environ[nom] = valeur


class _CacheDisqueTemporaire(unittest.TestCase):
    """Redirige le cache disque de sonde vers un bac a sable jetable."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_purge_probe_")
        self.cache_dir = Path(self._tmp) / "cache" / "probe"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._prev_dir = os.environ.get("CINESORT_PROBE_CACHE_DIR")
        self._prev_flag = os.environ.get("CINESORT_PROBE_DISK_CACHE")
        os.environ["CINESORT_PROBE_CACHE_DIR"] = str(self.cache_dir)
        os.environ.pop("CINESORT_PROBE_DISK_CACHE", None)

    def tearDown(self) -> None:
        _restaurer("CINESORT_PROBE_CACHE_DIR", self._prev_dir)
        _restaurer("CINESORT_PROBE_DISK_CACHE", self._prev_flag)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ecrire_entrees(self, nombre: int) -> None:
        for i in range(nombre):
            ecrit = disk_cache.upsert_disk_cache(
                path=f"/films/f{i}.mkv",
                size=1024 + i,
                mtime=1.0,
                tool="auto",
                raw_json={"r": i},
                normalized_json={"n": i},
            )
            self.assertTrue(ecrit, "la fixture doit etre produite par le code de production")
        self.assertEqual(len(list(self.cache_dir.glob("*.json"))), nombre)

    def _entrees_restantes(self) -> int:
        return len(list(self.cache_dir.glob("*.json")))


class LaRouteVideLesDEUXMoitiesTests(_CacheDisqueTemporaire):
    """Le VRAI corps de `_purge_probe_cache_impl` est execute : seule l'infra est
    remplacee. Tester la decision sans le site d'appel ne dit rien de lui."""

    def _api(self) -> backend.CineSortApi:
        api = backend.CineSortApi()
        state_dir = Path(self._tmp) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        api._state_dir = state_dir  # type: ignore[attr-defined]
        return api

    def test_le_miroir_disque_est_purge(self) -> None:
        self._ecrire_entrees(3)
        api = self._api()
        with patch.object(api, "_get_or_create_infra") as infra:
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 7
            infra.return_value = (store, MagicMock())

            res = api._purge_probe_cache_impl()

        self.assertTrue(res["ok"])
        self.assertEqual(res["entries_deleted"], 7, "le compte BASE ne change pas de sens")
        self.assertEqual(res["disk_entries_deleted"], 3)
        self.assertEqual(
            self._entrees_restantes(),
            0,
            "le miroir disque survit a la purge : le prochain acces le re-promeut en base",
        )

    def test_le_message_annonce_le_total_des_deux_moities(self) -> None:
        """Le message est le SEUL canal qui atteint l'utilisateur : l'ecran rend
        `message` (`parametres.js`, `rendu: "message"`) et ne lit ni
        `entries_deleted` ni `disk_entries_deleted`."""
        self._ecrire_entrees(2)
        api = self._api()
        with patch.object(api, "_get_or_create_infra") as infra:
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 5
            infra.return_value = (store, MagicMock())

            res = api._purge_probe_cache_impl()

        self.assertIn("7 entrees", res["message"], "le message annoncait la seule moitie base")

    def test_un_echec_du_disque_ne_perd_pas_la_purge_base(self) -> None:
        """Contre-test : la purge base a DEJA eu lieu quand le disque echoue.
        La faire echouer ici serait le defaut inverse — annoncer perdu ce qui est
        fait.

        On patche `clear_disk_cache_DETAILLE`, celle que la route appelle. La
        patcher sur la facade `clear_disk_cache` laisserait ce test s'executer
        sans plus rien simuler : la vraie purge tournerait, et seule
        l'assertion sur `disk_entries_deleted` le revelerait."""
        self._ecrire_entrees(1)
        api = self._api()
        with (
            patch.object(api, "_get_or_create_infra") as infra,
            patch.object(
                backend._probe_disk_cache,
                "clear_disk_cache_detaille",
                side_effect=OSError("disque occupe"),
            ),
        ):
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 4
            infra.return_value = (store, MagicMock())

            res = api._purge_probe_cache_impl()

        self.assertTrue(res["ok"])
        self.assertEqual(res["entries_deleted"], 4)
        self.assertEqual(res["disk_entries_deleted"], 0)
        self.assertFalse(
            res["disk_scan_complete"],
            "le miroir n'a pas ete balaye du tout : ne pas promettre un re-probe",
        )
        self.assertNotIn("re-probe les films", res["message"])

    def test_une_purge_sans_rien_a_supprimer_reste_honnete(self) -> None:
        """Contre-test de non-regression : aucun compte invente sur un cache vide."""
        api = self._api()
        with patch.object(api, "_get_or_create_infra") as infra:
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 0
            infra.return_value = (store, MagicMock())

            res = api._purge_probe_cache_impl()

        self.assertTrue(res["ok"])
        self.assertEqual(res["entries_deleted"], 0)
        self.assertEqual(res["disk_entries_deleted"], 0)
        self.assertIn("0 entrees", res["message"])


class LeNettoyageTravailleMemeCacheDESACTIVETests(_CacheDisqueTemporaire):
    """`CINESORT_PROBE_DISK_CACHE=0` est pose par quelqu'un qui ne veut plus de ce
    cache. Lui refuser d'effacer ce qu'il a deja produit inverse l'intention."""

    def test_clear_purge_meme_quand_le_cache_est_desactive(self) -> None:
        self._ecrire_entrees(2)  # ecrites AVANT la desactivation
        os.environ["CINESORT_PROBE_DISK_CACHE"] = "0"

        supprimes = disk_cache.clear_disk_cache()

        self.assertEqual(supprimes, 2, "la purge rendait 0 sur un repertoire plein")
        self.assertEqual(self._entrees_restantes(), 0)

    def test_prune_purge_meme_quand_le_cache_est_desactive(self) -> None:
        self._ecrire_entrees(1)
        vieux = time.time() - _AGE_HORS_RETENTION_S
        for entree in self.cache_dir.glob("*.json"):
            os.utime(entree, (vieux, vieux))
        os.environ["CINESORT_PROBE_DISK_CACHE"] = "0"

        supprimes = disk_cache.prune_disk_cache(retention_days=90)

        self.assertEqual(supprimes, 1, "la retention rendait 0 sur un repertoire plein")
        self.assertEqual(self._entrees_restantes(), 0)


class LeDrapeauGouverneTOUJOURSLaProductionTests(_CacheDisqueTemporaire):
    """Contre-test du precedent : le nettoyage a perdu la garde, pas l'ecriture
    ni la lecture. Sans ce bloc, retirer la garde des QUATRE fonctions passerait."""

    def test_ecriture_toujours_refusee_quand_desactive(self) -> None:
        os.environ["CINESORT_PROBE_DISK_CACHE"] = "0"

        ecrit = disk_cache.upsert_disk_cache(
            path="/films/x.mkv",
            size=10,
            mtime=1.0,
            tool="auto",
            raw_json={"r": 1},
            normalized_json={"n": 1},
        )

        self.assertFalse(ecrit)
        self.assertEqual(self._entrees_restantes(), 0)

    def test_lecture_toujours_refusee_quand_desactive(self) -> None:
        self._ecrire_entrees(1)
        os.environ["CINESORT_PROBE_DISK_CACHE"] = "0"

        lu = disk_cache.get_disk_cache(path="/films/f0.mkv", size=1024, mtime=1.0, tool="auto")

        self.assertIsNone(lu)


if __name__ == "__main__":
    unittest.main()


class LeMessageNePROMETPasCeQueLaPurgeNAPasFaitTests(_CacheDisqueTemporaire):
    """`clear_disk_cache` est best-effort : `except OSError: continue` laisse
    derriere lui les fichiers que l'OS refuse de supprimer (lock Windows,
    fichier ouvert par un autre process). Ces survivants restent des entrees de
    repli VALIDES : le prochain scan les relit et les RE-PROMEUT en base.

    Le message disait pourtant « Relance un scan pour re-probe les films » —
    une promesse que la purge n'a pas tenue, et que rien ne dementait : le
    compte des echecs existait dans la boucle, il etait simplement jete.

    Le `continue` reste la bonne decision (echouer la route perdrait la purge
    base deja faite). Ce qui change, c'est que le nombre de survivants REMONTE
    jusqu'a l'utilisateur.
    """

    def _api(self) -> backend.CineSortApi:
        api = backend.CineSortApi()
        state_dir = Path(self._tmp) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        api._state_dir = state_dir  # type: ignore[attr-defined]
        return api

    def _purger_avec_un_fichier_indelebile(self) -> dict:
        """Un `unlink` qui refuse UN fichier sur les trois, comme un lock."""
        self._ecrire_entrees(3)
        refuses = {sorted(p.name for p in self.cache_dir.iterdir())[0]}
        vrai_unlink = Path.unlink

        def _unlink(self_path: Path, *a: object, **k: object) -> None:
            if self_path.name in refuses:
                raise PermissionError(13, "fichier verrouille")
            vrai_unlink(self_path, *a, **k)

        api = self._api()
        with (
            patch.object(api, "_get_or_create_infra") as infra,
            patch.object(Path, "unlink", _unlink),
        ):
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 0
            infra.return_value = (store, MagicMock())
            return api._purge_probe_cache_impl()

    def test_les_survivants_du_disque_sont_COMPTES(self) -> None:
        res = self._purger_avec_un_fichier_indelebile()

        self.assertEqual(res["disk_entries_deleted"], 2)
        self.assertEqual(
            res["disk_entries_kept"],
            1,
            "le fichier verrouille a survecu et sera re-promu : il doit se compter",
        )
        self.assertEqual(self._entrees_restantes(), 1, "temoin : le lock a bien tenu")

    def test_le_message_ne_promet_PLUS_un_re_probe_complet(self) -> None:
        res = self._purger_avec_un_fichier_indelebile()

        self.assertIn("1", res["message"], "le nombre de survivants doit atteindre l'utilisateur")
        self.assertNotIn(
            "re-probe les films",
            res["message"],
            "promesse d'un re-probe COMPLET alors qu'une entree de repli survit",
        )

    def test_sans_aucun_survivant_la_promesse_reste_ENTIERE(self) -> None:
        """Contre-test : le cas nominal ne doit pas heriter d'une reserve
        inutile. Une purge integrale PEUT promettre le re-probe."""
        self._ecrire_entrees(3)
        api = self._api()
        with patch.object(api, "_get_or_create_infra") as infra:
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 4
            infra.return_value = (store, MagicMock())
            res = api._purge_probe_cache_impl()

        self.assertEqual(res["disk_entries_kept"], 0)
        self.assertIn("re-probe les films", res["message"])

    def test_un_echec_GLOBAL_du_balayage_ne_compte_pas_zero_survivant(self) -> None:
        """Le `except OSError` EXTERNE (autour de `iterdir`) arrete le balayage
        en cours de route. Les entrees non visitees survivent sans avoir ete
        comptees : rendre `0` survivant serait alors une affirmation FAUSSE, pas
        une mesure. La purge doit se declarer incomplete."""
        self._ecrire_entrees(3)
        api = self._api()
        with (
            patch.object(api, "_get_or_create_infra") as infra,
            patch.object(Path, "iterdir", side_effect=OSError(5, "E/S")),
        ):
            store = MagicMock()
            store.probe.clear_probe_cache.return_value = 4
            infra.return_value = (store, MagicMock())
            res = api._purge_probe_cache_impl()

        self.assertTrue(res["ok"], "la purge base a eu lieu, la route reussit")
        self.assertFalse(
            res["disk_scan_complete"],
            "le balayage s'est arrete : on ne sait pas ce qui reste",
        )
        self.assertNotIn("re-probe les films", res["message"])
