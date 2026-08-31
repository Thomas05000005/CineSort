"""LOT 6 (C + D) — un corps JSON valide mais NON-DICT traverse les gardes.

`resp.json()` ne rend pas forcement un objet : `[]`, `"texte"` et `12` sont du
JSON parfaitement valide. Quatre sites appellent `.get()` dessus sans verifier
le type, et l'`AttributeError` qui en resulte n'est attrapee NULLE PART :

  - `ollama_client._invoke` : `data.get("response", "")` est bien DANS le
    `try`, mais celui-ci n'attrape que `(ValueError, json.JSONDecodeError)` ;
    et `parsed.get(key)` est carrement HORS du `try`.
  - `tmdb_client.find_by_imdb_id`   : `data.get("movie_results")` hors `try`.
  - `tmdb_client.search_tv`         : `data.get("results")` hors `try`, plus
    `item.get(...)` sans filtre par element.
  - `tmdb_client.get_tv_episode_title` : `data.get("name")` hors `try`.

Le contrat de ces quatre fonctions est le repli gracieux (`None` / `[]` /
`{ok: False}`) : c'est ce que les appelants attendent, et ils n'entourent pas
l'appel d'un `except`. Une exception qui s'echappe casse donc l'enrichissement
au lieu de le degrader.

Le module `tmdb_client` porte DEJA la garde `isinstance(data, dict)` a six
autres endroits (`search`, `_get_movie_detail_cached`, `get_movie_extras`...) :
ces trois sites sont les oublies du meme motif, pas une nouveaute.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from cinesort.infra.integrations.ollama_client import OllamaClient
from cinesort.infra.tmdb_client import TmdbClient


class _FausseReponse:
    """Reponse HTTP dont le corps JSON est pilote par le test."""

    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


# ---------------------------------------------------------------------------
# C — ollama_client._invoke
# ---------------------------------------------------------------------------


class OllamaCorpsNonDictTests(unittest.TestCase):
    def _client(self) -> OllamaClient:
        return OllamaClient(endpoint="http://localhost:11434")

    def _generer(self, payload: Any) -> dict:
        client = self._client()
        with mock.patch(
            "cinesort.infra.integrations.ollama_client.request_bounded",
            return_value=_FausseReponse(payload),
        ):
            return client.generate_synopsis("Inception", 2010)

    def test_corps_json_liste_rend_un_echec_gracieux(self) -> None:
        """`resp.json()` -> `[]` : `data.get` leve AttributeError, non attrapee."""
        resultat = self._generer([])
        self.assertFalse(resultat["ok"])
        self.assertEqual(resultat["reason"], "invalid_json")
        self.assertFalse(resultat["ai_generated"])

    def test_corps_json_chaine_rend_un_echec_gracieux(self) -> None:
        resultat = self._generer("pas un objet")
        self.assertFalse(resultat["ok"])
        self.assertEqual(resultat["reason"], "invalid_json")

    def test_champ_response_contenant_un_tableau_rend_un_echec_gracieux(self) -> None:
        """Le second site : `parsed.get(key)` est HORS du try.

        `{"response": "[1, 2]"}` est un corps que le vrai Ollama peut rendre
        (le modele n'a pas suivi le schema) : `json.loads` reussit et donne une
        LISTE, sur laquelle `.get` n'existe pas.
        """
        resultat = self._generer({"response": "[1, 2]"})
        self.assertFalse(resultat["ok"])
        self.assertFalse(resultat["ai_generated"])

    def test_temoin_un_corps_conforme_reussit_toujours(self) -> None:
        """Sans ce temoin, « rendre toujours ok:False » passerait aussi."""
        resultat = self._generer({"response": '{"synopsis": "Un reve dans un reve."}'})
        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["generated"], "Un reve dans un reve.")


# ---------------------------------------------------------------------------
# D — tmdb_client : trois sites du meme motif
# ---------------------------------------------------------------------------


class TmdbCorpsNonDictTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lot6_tmdb_")
        self.client = TmdbClient(api_key="k", cache_path=Path(self._tmp.name) / "tmdb_cache.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _reponse(self, payload: Any) -> mock._patch:
        return mock.patch.object(self.client, "_http_get", return_value=_FausseReponse(payload))

    def test_find_by_imdb_id_rend_none_sur_corps_non_dict(self) -> None:
        with self._reponse([]):
            self.assertIsNone(self.client.find_by_imdb_id("tt0111161"))

    def test_find_by_imdb_id_ignore_un_element_non_dict(self) -> None:
        """`movies[0]` n'est pas force d'etre un objet non plus."""
        with self._reponse({"movie_results": ["pas un objet"]}):
            self.assertIsNone(self.client.find_by_imdb_id("tt0111162"))

    def test_search_tv_rend_liste_vide_sur_corps_non_dict(self) -> None:
        with self._reponse([]):
            self.assertEqual(self.client.search_tv("Kaamelott"), [])

    def test_search_tv_ignore_les_elements_non_dict(self) -> None:
        with self._reponse({"results": ["pas un objet", {"id": 7, "name": "Kaamelott"}]}):
            resultats = self.client.search_tv("Kaamelott 2")
        self.assertEqual([r.id for r in resultats], [7])

    def test_get_tv_episode_title_rend_none_sur_corps_non_dict(self) -> None:
        with self._reponse(["pas un objet"]):
            self.assertIsNone(self.client.get_tv_episode_title(1399, 1, 1))

    def test_temoin_les_trois_endpoints_repondent_toujours_sur_corps_conforme(self) -> None:
        """Temoin : sans lui, « rendre toujours None/[] » passerait aussi."""
        with self._reponse({"movie_results": [{"id": 278, "title": "Les Evades", "release_date": "1994-09-23"}]}):
            trouve = self.client.find_by_imdb_id("tt0111163")
        self.assertIsNotNone(trouve)
        assert trouve is not None
        self.assertEqual(trouve.id, 278)

        with self._reponse({"results": [{"id": 1399, "name": "Le Trone de fer"}]}):
            series = self.client.search_tv("Trone")
        self.assertEqual([s.id for s in series], [1399])

        with self._reponse({"name": "L'hiver vient"}):
            titre = self.client.get_tv_episode_title(1399, 1, 1)
        self.assertEqual(titre, "L'hiver vient")


if __name__ == "__main__":
    unittest.main()
