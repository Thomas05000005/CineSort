"""LOT 6 (B) — « Recuperer jaquettes » ne peut PAS rafraichir avant 30 jours.

Le bouton envoie `force=1` sur `/api/poster`. `get_or_fetch` honore ce drapeau
en sautant le cache DISQUE des images... puis appelle `fetch_and_cache`, qui
redemande le `poster_path` a `tmdb_client.get_movie_poster_path(tmdb_id)` SANS
`force_refresh`. Ce second cache — le cache JSON de `tmdb_client`, TTL 30 jours
par defaut (`DEFAULT_CACHE_TTL_DAYS`) — rend alors l'ANCIEN chemin.

Consequence : l'URL CDN reconstruite est identique a la precedente, et le
« rafraichissement » retelecharge octet pour octet la meme image. Quand TMDb
publie une nouvelle jaquette, l'utilisateur ne peut pas l'obtenir en cliquant
le bouton prevu pour ca — il doit attendre l'expiration du TTL.

Le parametre existe pourtant deja et sert exactement a ca
(`tmdb_client.get_movie_poster_path(movie_id, force_refresh=...)`, teste par
`tests/test_tmdb_force_refresh_v77.py`) : c'est le CHAINAGE qui manque, sur
toute la longueur `serve_poster -> get_or_fetch -> fetch_and_cache`.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
from unittest import mock

from cinesort.infra.integrations import poster_proxy

_TMDB_ID = 550
_SIZE = "w342"
_CHEMIN_PERIME = "/perime.jpg"
_CHEMIN_NEUF = "/neuf.jpg"


class _TmdbAvecJaquetteRenouvelee:
    """Cache JSON TMDb dont l'entree est perimee mais encore dans le TTL.

    `force_refresh=True` va rechercher le chemin a jour, comme le vrai client.
    """

    def __init__(self) -> None:
        self.appels: List[bool] = []

    def get_movie_poster_path(self, movie_id: int, force_refresh: bool = False) -> str:  # noqa: ARG002
        self.appels.append(bool(force_refresh))
        return _CHEMIN_NEUF if force_refresh else _CHEMIN_PERIME


class _Reponse:
    def __init__(self, corps: bytes = b"\xff\xd8\xff\xe0IMAGE") -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg"}
        self._corps = corps

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:  # noqa: ARG002
        yield self._corps

    def close(self) -> None:
        return None


class _EnTetes:
    def __init__(self, data: Dict[str, str]) -> None:
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, name: str, default: str = "") -> str:
        return self._data.get(name.lower(), default)


class _FakeHandler:
    def __init__(self) -> None:
        self.status_code: Optional[int] = None
        self.body = io.BytesIO()
        self.headers = _EnTetes({})
        self.wfile = self.body

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, key: str, value: str) -> None:
        return None

    def end_headers(self) -> None:
        return None


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lot6_force_")
        self.state_dir = Path(self._tmp.name)
        (self.state_dir / "settings.json").write_text(
            json.dumps({"tmdb_api_key": "FAKE_KEY_XXX"}, ensure_ascii=False),
            encoding="utf-8-sig",
        )
        self.cache_root = self.state_dir / "cache" / "posters"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        poster_proxy._session = None

    def tearDown(self) -> None:
        poster_proxy._session = None
        self._tmp.cleanup()

    def _session(self) -> mock.MagicMock:
        session = mock.MagicMock()
        session.get.return_value = _Reponse()
        return session

    @staticmethod
    def _url_demandee(session: mock.MagicMock) -> str:
        appel = session.get.call_args
        return str(appel.args[0]) if appel.args else str(appel.kwargs.get("url", ""))


class ForceRedemandeLeCheminAJourTests(_Base):
    def test_get_or_fetch_force_va_chercher_le_poster_path_a_jour(self) -> None:
        tmdb = _TmdbAvecJaquetteRenouvelee()
        session = self._session()

        with mock.patch.object(poster_proxy, "_get_session", return_value=session):
            _f, _ct, error_code = poster_proxy.get_or_fetch(tmdb, self.cache_root, _TMDB_ID, _SIZE, force=True)

        self.assertIsNone(error_code)
        self.assertEqual(
            tmdb.appels,
            [True],
            "force=1 a relu le cache JSON TMDb : la jaquette reste figee jusqu'a l'expiration du TTL (30 j)",
        )
        self.assertTrue(
            self._url_demandee(session).endswith(_CHEMIN_NEUF),
            f"l'URL CDN reconstruite pointe encore sur {_CHEMIN_PERIME}",
        )

    def test_bout_en_bout_le_bouton_recupere_la_nouvelle_jaquette(self) -> None:
        """Le site d'appel REEL : `serve_poster` avec `force=1` dans la query."""
        tmdb = _TmdbAvecJaquetteRenouvelee()
        session = self._session()
        handler = _FakeHandler()

        with (
            mock.patch.object(poster_proxy, "_build_or_get_tmdb_client", return_value=tmdb),
            mock.patch.object(poster_proxy, "_get_session", return_value=session),
        ):
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"id": str(_TMDB_ID), "size": _SIZE, "force": "1"},
            )

        self.assertEqual(handler.status_code, 200)
        self.assertTrue(self._url_demandee(session).endswith(_CHEMIN_NEUF))

    def test_temoin_sans_force_le_cache_json_reste_la_source(self) -> None:
        """Contre-test : le correctif ne doit pas forcer un refresh a chaque `<img>`.

        Sans lui, « passer force_refresh=True tout le temps » passerait aussi —
        et chaque vignette de la grille bruleraient le quota de la cle TMDb.
        """
        tmdb = _TmdbAvecJaquetteRenouvelee()
        session = self._session()

        with mock.patch.object(poster_proxy, "_get_session", return_value=session):
            poster_proxy.get_or_fetch(tmdb, self.cache_root, _TMDB_ID, _SIZE, force=False)

        self.assertEqual(tmdb.appels, [False])
        self.assertTrue(self._url_demandee(session).endswith(_CHEMIN_PERIME))


class LaSignatureReelleAccepteForceRefreshTests(unittest.TestCase):
    """Le faux client ci-dessus doit refleter le vrai, sinon il ne prouve rien."""

    def test_le_vrai_client_tmdb_expose_force_refresh(self) -> None:
        import inspect

        from cinesort.infra.tmdb_client import TmdbClient

        params: Tuple[str, ...] = tuple(inspect.signature(TmdbClient.get_movie_poster_path).parameters)
        self.assertIn("force_refresh", params)


if __name__ == "__main__":
    unittest.main()
