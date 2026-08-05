"""Regression PR #756 : `get_movies` doit paginer, sinon la borne 10 Mo casse le sync.

Contexte
--------
La PR #756 borne le body a 10 Mo dans `PlexClient._get` (anti-OOM). Mais
`get_movies` tirait `/library/sections/{id}/all` NON PAGINE, avec les blocs
Media/Part/Guid imbriques.

Mesure realisee sur un item Plex realiste (schema PMS d'un listing
`/library/sections/{id}/all?type=1`, serialisation JSON compacte) :

    variante                                        octets/film   films @ 10 Mo
    minimal (sans Guid ni people, resume court)          1 926          5 192
    defaut PMS + Guid (includeGuids=1)                   2 001          4 998
    complet (Guid + Genre/Country/Director/Writer/Role)  2 580          3 876
    complet + resume long                                2 860          3 496

Autrement dit une bibliotheque LEGITIME de ~3 500 a ~5 200 films depassait la
borne : un sync Plex qui fonctionnait devenait un echec dur
« Reponse Plex trop volumineuse ». L'utilisateur a une grosse bibliotheque.

Le correctif est la pagination via les en-tetes Plex `X-Plex-Container-Start`
et `X-Plex-Container-Size` (documentes : « Both headers should be sent in
order to request paginated content »), ce qui rend la borne de 10 Mo valable
PAR PAGE et supprime le probleme a la racine.

Le faux serveur ci-dessous fabrique 6 000 films (~15 Mo non pagine) et honore
les en-tetes de pagination. Avant le correctif, `get_movies` n'envoie aucun
en-tete de pagination -> le serveur renvoie les 6 000 films d'un coup -> le
garde-fou 10 Mo de `_get` leve PlexError -> test ROUGE.
"""

from __future__ import annotations

import json
import sys
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from cinesort.infra.plex_client import PlexClient, PlexError

# Borne appliquee par PlexClient._get (PR #756).
_BODY_LIMIT = 10_000_000

# Assez de films pour depasser 10 Mo au tarif mesure (~2,5 Ko/film).
_LIBRARY_SIZE = 6000


def _fake_movie(i: int) -> Dict[str, Any]:
    """Item Plex realiste : les champs que `get_movies` parse + le bruit du vrai PMS."""
    title = f"Le Titre Du Film Numero {i} Avec Un Sous-Titre"
    year = 1999 + (i % 25)
    return {
        "ratingKey": str(10000 + i),
        "key": f"/library/metadata/{10000 + i}",
        "guid": f"plex://movie/5d776826880197001ec90{i:04d}",
        "slug": f"le-titre-du-film-numero-{i}",
        "studio": "Warner Bros. Pictures",
        "type": "movie",
        "title": title,
        "titleSort": title.replace("Le ", ""),
        "librarySectionTitle": "Films",
        "librarySectionID": 1,
        "librarySectionKey": "/library/sections/1",
        "contentRating": "fr/12",
        "summary": (
            "Dans un futur proche, un programmeur informatique decouvre que la realite "
            "qu'il percoit n'est qu'une simulation elaboree concue par des machines "
            "intelligentes pour asservir l'humanite. Recrute par un groupe de rebelles, "
            "il doit apprendre a plier les regles de ce monde artificiel."
        ),
        "rating": 8.7,
        "audienceRating": 8.5,
        "year": year,
        "tagline": "Bienvenue dans le monde reel.",
        "thumb": f"/library/metadata/{10000 + i}/thumb/1731000000",
        "art": f"/library/metadata/{10000 + i}/art/1731000000",
        "duration": 8181000,
        "originallyAvailableAt": "1999-03-30",
        "addedAt": 1731000000,
        "updatedAt": 1731000000,
        "audienceRatingImage": "rottentomatoes://image.rating.upright",
        "chapterSource": "media",
        "ratingImage": "rottentomatoes://image.rating.ripe",
        "viewCount": 1 if i % 3 == 0 else 0,
        "lastViewedAt": 1731500000,
        "Media": [
            {
                "id": 50000 + i,
                "duration": 8181000,
                "bitrate": 18432,
                "width": 3840,
                "height": 1600,
                "aspectRatio": 2.35,
                "audioChannels": 8,
                "audioCodec": "truehd",
                "videoCodec": "hevc",
                "videoResolution": "4k",
                "container": "mkv",
                "videoFrameRate": "24p",
                "optimizedForStreaming": 0,
                "audioProfile": "",
                "has64bitOffsets": False,
                "videoProfile": "main 10",
                "Part": [
                    {
                        "id": 50000 + i,
                        "key": f"/library/parts/{50000 + i}/1731000000/file.mkv",
                        "duration": 8181000,
                        "file": (f"/mnt/media/Films/{title} ({year})/{title} ({year}) - 2160p HDR TrueHD Atmos.mkv"),
                        "size": 61234567890,
                        "audioProfile": "",
                        "container": "mkv",
                        "has64bitOffsets": False,
                        "optimizedForStreaming": False,
                        "videoProfile": "main 10",
                    }
                ],
            }
        ],
        "Guid": [
            {"id": f"imdb://tt{100000 + i}"},
            {"id": f"tmdb://{600 + i}"},
            {"id": f"tvdb://{160 + i}"},
        ],
        "Genre": [{"tag": t} for t in ("Action", "Science-Fiction", "Aventure")],
        "Country": [{"tag": "Etats-Unis d'Amerique"}],
        "Director": [{"tag": "Lana Wachowski"}, {"tag": "Lilly Wachowski"}],
        "Writer": [{"tag": "Lana Wachowski"}, {"tag": "Lilly Wachowski"}],
        "Role": [{"tag": f"Acteur Numero {k} Nom De Famille"} for k in range(8)],
    }


class _FakePlexServer:
    """Faux PMS qui honore X-Plex-Container-Start / X-Plex-Container-Size.

    Reproduit le comportement documente : sans en-tete de pagination, le
    serveur renvoie TOUTE la section d'un coup. `content` est le VRAI JSON
    serialise, donc la borne 10 Mo de `_get` s'applique reellement.
    """

    def __init__(self, total: int = _LIBRARY_SIZE) -> None:
        self._movies = [_fake_movie(i) for i in range(total)]
        self.total = total
        self.requests: List[Dict[str, Any]] = []
        self.max_body_seen = 0

    def __call__(self, url: str, **kwargs: Any) -> MagicMock:
        headers = kwargs.get("headers") or {}
        self.requests.append({"url": url, "headers": dict(headers), "params": dict(kwargs.get("params") or {})})

        raw_start = headers.get("X-Plex-Container-Start")
        raw_size = headers.get("X-Plex-Container-Size")
        if raw_start is None or raw_size is None:
            # Pas de pagination demandee -> tout le catalogue (comportement PMS).
            start, size = 0, self.total
        else:
            start = int(raw_start)
            size = int(raw_size)

        page = self._movies[start : start + size]
        body = {
            "MediaContainer": {
                "size": len(page),
                "totalSize": self.total,
                "offset": start,
                "identifier": "com.plexapp.plugins.library",
                "librarySectionID": 1,
                "librarySectionTitle": "Films",
                "viewGroup": "movie",
                "Metadata": page,
            }
        }
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.max_body_seen = max(self.max_body_seen, len(raw))

        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        resp.json.return_value = body
        resp.raise_for_status.return_value = None
        return resp


class PlexLargeLibraryPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _FakePlexServer()
        self.client = PlexClient("http://plex.local:32400", "token-test", timeout_s=5.0)

    def tearDown(self) -> None:
        self.client.close()

    def test_unpaginated_library_would_exceed_the_10mb_bound(self) -> None:
        """Garde-fou de la mesure : la bibliotheque simulee depasse bien 10 Mo d'un bloc.

        Cette assertion doit rester verte des deux cotes du correctif : elle
        documente que le probleme est reel, pas que le correctif est present.
        """
        resp = self.server("http://plex.local:32400/library/sections/1/all")
        self.assertGreater(
            len(resp.content),
            _BODY_LIMIT,
            "La bibliotheque simulee doit depasser la borne 10 Mo, sinon le test ne prouve rien",
        )

    def test_get_movies_survives_a_large_library(self) -> None:
        """ROUGE avant le correctif : PlexError « Reponse Plex trop volumineuse »."""
        with patch.object(self.client._session, "get", side_effect=self.server):
            try:
                movies = self.client.get_movies("1")
            except PlexError as exc:  # pragma: no cover - chemin d'echec avant correctif
                self.fail(
                    f"get_movies a echoue sur une bibliotheque legitime de {_LIBRARY_SIZE} "
                    f"films : {exc}. La reponse doit etre paginee "
                    f"(X-Plex-Container-Start / X-Plex-Container-Size)."
                )
        self.assertEqual(len(movies), _LIBRARY_SIZE)

    def test_every_response_stays_under_the_bound(self) -> None:
        """La borne 10 Mo doit rester valable PAR PAGE."""
        with patch.object(self.client._session, "get", side_effect=self.server):
            self.client.get_movies("1")
        self.assertGreater(len(self.server.requests), 1, "get_movies doit emettre plusieurs pages")
        self.assertLessEqual(
            self.server.max_body_seen,
            _BODY_LIMIT,
            f"Une page pese {self.server.max_body_seen} octets, au-dela de la borne {_BODY_LIMIT}",
        )

    def test_pagination_headers_are_sent_on_every_request(self) -> None:
        with patch.object(self.client._session, "get", side_effect=self.server):
            self.client.get_movies("1")
        self.assertTrue(self.server.requests)
        starts = []
        for req in self.server.requests:
            headers = req["headers"]
            self.assertIn("X-Plex-Container-Start", headers, f"en-tete start manquant : {req}")
            self.assertIn("X-Plex-Container-Size", headers, f"en-tete size manquant : {req}")
            # Ce sont des EN-TETES HTTP, pas des query params (cf fix Vague H #2).
            self.assertNotIn("X-Plex-Container-Start", req["params"])
            self.assertNotIn("X-Plex-Container-Size", req["params"])
            starts.append(int(headers["X-Plex-Container-Start"]))
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts, sorted(starts), "l'offset doit progresser")
        self.assertEqual(len(set(starts)), len(starts), "aucun offset ne doit etre rejoue")

    def test_include_guids_is_sent_on_every_request(self) -> None:
        """Sans `includeGuids=1`, Plex ne joint PAS le tableau Guid a un listing.

        Le parsing lit `item["Guid"]` pour en extraire le tmdb_id : sans ce
        parametre, le champ remontait TOUJOURS None et le rapport de sync
        appariait les films sur le seul chemin de fichier. C'est un query
        PARAMETRE (pas un en-tete, contrairement a la pagination).
        """
        with patch.object(self.client._session, "get", side_effect=self.server):
            self.client.get_movies("1")
        self.assertTrue(self.server.requests)
        for req in self.server.requests:
            self.assertEqual(
                req["params"].get("includeGuids"),
                "1",
                f"includeGuids absent de la requete : {req['params']}",
            )
            # C'est bien un query param, pas un en-tete.
            self.assertNotIn("includeGuids", req["headers"])

    def test_content_is_complete_and_ordered(self) -> None:
        """La pagination ne doit ni perdre, ni dupliquer, ni desordonner les films."""
        with patch.object(self.client._session, "get", side_effect=self.server):
            movies = self.client.get_movies("1")
        self.assertEqual(len(movies), _LIBRARY_SIZE)
        ids = [m["id"] for m in movies]
        self.assertEqual(len(set(ids)), _LIBRARY_SIZE, "doublons detectes")
        self.assertEqual(ids, [str(10000 + i) for i in range(_LIBRARY_SIZE)])
        first = movies[0]
        self.assertEqual(first["name"], "Le Titre Du Film Numero 0 Avec Un Sous-Titre")
        self.assertEqual(first["year"], 1999)
        self.assertEqual(first["tmdb_id"], "600")
        self.assertTrue(first["path"].endswith(".mkv"))
        self.assertTrue(first["played"])
        self.assertFalse(movies[1]["played"])


class PlexPaginationRobustnessTests(unittest.TestCase):
    """Serveurs qui n'honorent pas la pagination : pas de boucle infinie, pas de doublon."""

    def setUp(self) -> None:
        self.client = PlexClient("http://plex.local:32400", "token-test", timeout_s=5.0)

    def tearDown(self) -> None:
        self.client.close()

    def _server_ignoring_pagination(self, total: int, *, announce_total: bool):
        calls = {"n": 0}

        def _get(url: str, **kwargs: Any) -> MagicMock:
            calls["n"] += 1
            mc: Dict[str, Any] = {
                "size": total,
                "Metadata": [
                    {"ratingKey": str(i), "title": f"F{i}", "year": 2000, "Media": [], "Guid": []} for i in range(total)
                ],
            }
            if announce_total:
                mc["totalSize"] = total
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"{}"
            resp.json.return_value = {"MediaContainer": mc}
            resp.raise_for_status.return_value = None
            return resp

        return _get, calls

    def test_server_ignoring_headers_with_totalsize(self) -> None:
        server, calls = self._server_ignoring_pagination(1200, announce_total=True)
        with patch.object(self.client._session, "get", side_effect=server):
            movies = self.client.get_movies("1")
        self.assertEqual(len(movies), 1200, "aucun film perdu")
        self.assertEqual(calls["n"], 1, "un serveur qui ignore la pagination ne doit pas etre re-interroge")

    def test_server_ignoring_headers_without_totalsize(self) -> None:
        """Sans totalSize, il ne faut PAS reboucler : sinon accumulation infinie de doublons."""
        server, calls = self._server_ignoring_pagination(1200, announce_total=False)
        with patch.object(self.client._session, "get", side_effect=server):
            movies = self.client.get_movies("1")
        self.assertEqual(len(movies), 1200)
        self.assertEqual(len(set(m["id"] for m in movies)), 1200, "doublons : la boucle a rejoue la page")
        self.assertEqual(calls["n"], 1)

    def test_empty_library_does_one_request(self) -> None:
        def _get(url: str, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"{}"
            resp.json.return_value = {"MediaContainer": {"size": 0, "totalSize": 0, "Metadata": []}}
            resp.raise_for_status.return_value = None
            return resp

        with patch.object(self.client._session, "get", side_effect=_get) as mock_get:
            self.assertEqual(self.client.get_movies("1"), [])
        self.assertEqual(mock_get.call_count, 1)

    def test_invalid_library_id_still_rejected(self) -> None:
        """Non-regression : la validation anti-path-injection precede tout appel reseau."""
        with patch.object(self.client._session, "get") as mock_get:
            with self.assertRaises(PlexError):
                self.client.get_movies("1/../../etc")
            with self.assertRaises(PlexError):
                self.client.get_movies("")
        mock_get.assert_not_called()

    def test_http_error_is_propagated(self) -> None:
        """Non-regression : une PlexError du transport remonte telle quelle."""
        with patch.object(self.client._session, "get", side_effect=PlexError("boom")):
            with self.assertRaises(PlexError):
                self.client.get_movies("1")


if __name__ == "__main__":
    unittest.main()
