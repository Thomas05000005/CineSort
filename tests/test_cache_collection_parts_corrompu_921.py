"""Un cache TMDb malforme doit etre traite comme ABSENT, pas servi.

Remarque de revue sur la PR #921. `_fetch_collection_parts` ne validait que le
CONTENEUR (`isinstance(cached, list)`), donc une entree comme `["corrompu"]`
passait. `get_incomplete_sagas` appelait ensuite `part.get("title")` sur une
chaine -> `AttributeError`, et l'endpoint echouait au lieu de refaire la
requete TMDb.

Le commentaire du code promettait pourtant qu'une entree corrompue « ne doit
pas etre servie telle quelle » : il decrivait une intention que le code ne
tenait pas.

Le bon sens de l'erreur : un miss de cache coute UN appel reseau, un endpoint
en echec coute la fonctionnalite entiere.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest import mock

from cinesort.ui.api import library_audit_support as mod


class _FakeTmdb:
    """Client TMDb minimal : sert une entree de cache et compte les appels HTTP."""

    api_key = "k"

    def __init__(self, entree: Any) -> None:
        self._entree = entree
        self.appels_http = 0

    def _cache_get(self, _key: str) -> Any:
        return self._entree

    def _cache_set(self, _key: str, _val: Any) -> None:
        pass

    def _save_cache_atomic(self) -> None:
        pass

    def _http_get(self, _url: str, params: Dict[str, Any] | None = None) -> Any:
        self.appels_http += 1

        class _Resp:
            @staticmethod
            def raise_for_status() -> None:
                pass

            @staticmethod
            def json() -> Dict[str, Any]:
                return {"parts": [{"id": 7, "title": "Heat", "release_date": "1995-12-15"}]}

        return _Resp()


class CacheCollectionPartsCorrompuTests(unittest.TestCase):
    def _appel(self, entree: Any) -> tuple[Any, _FakeTmdb]:
        tmdb = _FakeTmdb(entree)
        res = mod._fetch_collection_parts(mock.MagicMock(), 42, client=tmdb)
        return res, tmdb

    def test_liste_de_chaines_est_traitee_comme_un_cache_ABSENT(self) -> None:
        """Le cas exact de la revue : `["corrompu"]` ne doit pas etre servi."""
        res, tmdb = self._appel(["corrompu"])

        self.assertEqual(tmdb.appels_http, 1, "le cache malforme aurait du declencher une VRAIE requete")
        self.assertIsInstance(res, list)
        self.assertTrue(all(isinstance(p, dict) for p in res), f"forme non normalisee rendue : {res}")

    def test_le_consommateur_ne_leve_plus_AttributeError(self) -> None:
        """La consequence, pas seulement la cause : `.get()` sur une chaine."""
        res, _ = self._appel(["corrompu"])
        for part in res:
            part.get("title")  # levait AttributeError quand une chaine passait

    def test_un_cache_BIEN_FORME_est_servi_sans_requete(self) -> None:
        """Contre-epreuve : la validation ne doit pas tuer le cache legitime."""
        bon: List[Dict[str, Any]] = [{"tmdb_id": 7, "title": "Heat", "year": 1995}]
        res, tmdb = self._appel(bon)

        self.assertEqual(res, bon)
        self.assertEqual(tmdb.appels_http, 0, "un cache valide ne doit declencher AUCUNE requete")

    def test_une_liste_VIDE_reste_un_cache_valide(self) -> None:
        """Une collection sans partie manquante est un resultat LEGITIME.

        La refuser relancerait un appel TMDb a chaque consultation — le cache
        ne servirait plus a rien precisement dans le cas le plus frequent.
        """
        res, tmdb = self._appel([])

        self.assertEqual(res, [])
        self.assertEqual(tmdb.appels_http, 0, "une liste vide a ete prise pour un cache absent")

    def test_un_dict_incomplet_est_refuse(self) -> None:
        """Forme partielle : `title` sans `year` ne suffit pas."""
        res, tmdb = self._appel([{"title": "Heat"}])
        self.assertEqual(tmdb.appels_http, 1, "entree incomplete servie telle quelle")
        self.assertIsInstance(res, list)


if __name__ == "__main__":
    unittest.main()
