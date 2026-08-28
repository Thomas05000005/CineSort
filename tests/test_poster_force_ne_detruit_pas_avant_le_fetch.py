"""« Recuperer jaquettes » hors ligne detruisait la jaquette qu'il devait rafraichir.

`serve_poster` honorait `force=1` en effacant le cache disque `(id, size)` AVANT
d'appeler `get_or_fetch`. Detruire d'abord, c'est detruire sans savoir si l'on
saura remplacer :

    force=1 + TMDb injoignable  ->  le fichier est supprime, le fetch echoue,
                                    503, et l'utilisateur n'a plus de jaquette

Le filet existait pourtant : `get_or_fetch` documente « si fetch TMDb echoue
mais qu'un cache disque existe (meme ancien), on sert le cache » et relit le
cache a son etape 3. La purge prealable le vidait de sa matiere — une garde
correcte privee de ce qu'elle protege, motif deja paye dans ce depot.

Le correctif transmet `force` a `get_or_fetch` (qui saute la LECTURE du cache)
et ne purge qu'APRES un fetch reussi, sur les seules extensions devenues
obsoletes. Les deux dernieres classes verifient que le refresh continue de
rafraichir : sans elles, « ne rien purger du tout » passerait aussi.

Harnais : `serve_poster` est invoque directement avec un faux handler, pattern
etabli par `tests/test_runtime_poster_proxy_cache.py`. Le site d'appel REEL est
donc execute — c'est lui qui portait le defaut, pas la decision.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional, Tuple
from unittest import mock

import requests

from cinesort.infra.integrations import poster_proxy


class _FakeHandler:
    """Interface minimale de BaseHTTPRequestHandler exigee par serve_poster."""

    def __init__(self) -> None:
        self.status_code: Optional[int] = None
        self.headers_sent: List[Tuple[str, str]] = []
        self.body = io.BytesIO()
        self.headers = _EnTetesInsensibles({})
        self.wfile = self.body

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, str(value)))

    def end_headers(self) -> None:
        return None

    def _send_cors_headers(self) -> None:
        return None

    def _send_request_id_header(self) -> None:
        return None


class _EnTetesInsensibles:
    def __init__(self, data: Dict[str, str]) -> None:
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, name: str, default: str = "") -> str:
        return self._data.get(name.lower(), default)


class _FakeTmdbClient:
    def __init__(self, poster_path: str = "/abc123.jpg") -> None:
        self.poster_path = poster_path

    def get_movie_poster_path(self, movie_id: int) -> str:  # noqa: ARG002
        return self.poster_path


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "image/jpeg", status_code: int = 200) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = {"Content-Type": content_type}

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002
        if self._body:
            yield self._body

    def close(self) -> None:
        return None


_ANCIENNE = b"\xff\xd8\xff\xe0ANCIENNE_JAQUETTE"
_NOUVELLE = b"\xff\xd8\xff\xe0NOUVELLE_JAQUETTE"
_TMDB_ID = 550
_SIZE = "w342"


class _ProxyPosterBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="poster_force_")
        self.state_dir = Path(self._tmp.name)
        (self.state_dir / "settings.json").write_text(
            json.dumps({"tmdb_api_key": "FAKE_KEY_XXX"}, ensure_ascii=False),
            encoding="utf-8-sig",
        )
        self.cache_root = self.state_dir / "cache" / "posters"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        poster_proxy._tmdb_client_cache["client"] = None
        poster_proxy._tmdb_client_cache["api_key_hash"] = ""
        poster_proxy._tmdb_client_cache["state_dir"] = ""
        poster_proxy._session = None

    def tearDown(self) -> None:
        poster_proxy._tmdb_client_cache["client"] = None
        poster_proxy._tmdb_client_cache["api_key_hash"] = ""
        poster_proxy._tmdb_client_cache["state_dir"] = ""
        poster_proxy._session = None
        self._tmp.cleanup()

    def _servir(self, *, query: Dict[str, str], session: object, poster_path: str = "/abc123.jpg") -> _FakeHandler:
        """Execute le VRAI `serve_poster` avec une session HTTP controlee."""
        handler = _FakeHandler()
        with (
            mock.patch.object(poster_proxy, "_build_or_get_tmdb_client", return_value=_FakeTmdbClient(poster_path)),
            mock.patch.object(poster_proxy, "_get_session", return_value=session),
        ):
            poster_proxy.serve_poster(handler, self.state_dir, self.cache_root, query)
        return handler

    def _session_qui_repond(self, body: bytes, content_type: str = "image/jpeg") -> mock.MagicMock:
        session = mock.MagicMock()
        session.get.return_value = _FakeResponse(body, content_type=content_type)
        return session

    def _session_hors_ligne(self) -> mock.MagicMock:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("reseau injoignable")
        return session

    def _peupler_le_cache(self) -> None:
        """Fixture produite par le CODE DE PRODUCTION, pas ecrite a la main."""
        handler = self._servir(
            query={"id": str(_TMDB_ID), "size": _SIZE},
            session=self._session_qui_repond(_ANCIENNE),
        )
        self.assertEqual(handler.status_code, 200)
        self.assertEqual(self._fichiers_en_cache(), [f"{_TMDB_ID}.jpg"])

    def _fichiers_en_cache(self) -> List[str]:
        return sorted(p.name for p in (self.cache_root / _SIZE).glob(f"{_TMDB_ID}.*"))


class LeRefreshHorsLigneNeDetruitPasLaJaquetteTests(_ProxyPosterBase):
    def test_la_jaquette_survit_a_un_refresh_sans_reseau(self) -> None:
        self._peupler_le_cache()

        handler = self._servir(
            query={"id": str(_TMDB_ID), "size": _SIZE, "force": "1", "v": "123"},
            session=self._session_hors_ligne(),
        )

        self.assertEqual(
            self._fichiers_en_cache(),
            [f"{_TMDB_ID}.jpg"],
            "le refresh a detruit la jaquette qu'il ne pouvait pas remplacer",
        )
        self.assertEqual(handler.status_code, 200, "503 au lieu du repli sur le cache documente par get_or_fetch")
        self.assertEqual(handler.body.getvalue(), _ANCIENNE)

    def test_sans_cache_prealable_un_refresh_hors_ligne_reste_une_erreur(self) -> None:
        """Contre-test : le correctif ne transforme pas une absence en succes."""
        handler = self._servir(
            query={"id": str(_TMDB_ID), "size": _SIZE, "force": "1"},
            session=self._session_hors_ligne(),
        )

        self.assertEqual(handler.status_code, 503)
        self.assertEqual(self._fichiers_en_cache(), [])


class LeRefreshRafraichitToujoursTests(_ProxyPosterBase):
    """Sans ces deux tests, « ne plus rien purger du tout » passerait aussi —
    et le defaut de 2026-06-14 (R7-8, refresh sans effet visuel) reviendrait."""

    def test_force_remplace_le_contenu_par_celui_de_tmdb(self) -> None:
        self._peupler_le_cache()

        handler = self._servir(
            query={"id": str(_TMDB_ID), "size": _SIZE, "force": "1"},
            session=self._session_qui_repond(_NOUVELLE),
        )

        self.assertEqual(handler.status_code, 200)
        self.assertEqual(handler.body.getvalue(), _NOUVELLE, "force=1 a resservi le cache au lieu de re-telecharger")

    def test_force_efface_l_extension_devenue_obsolete(self) -> None:
        """`resolve_cache_file` rend la 1re extension de la whitelist (jpg avant
        webp) : un ancien `.jpg` laisse a cote d'un nouveau `.webp` serait
        resservi 30 jours (Cache-Control immuable)."""
        self._peupler_le_cache()

        handler = self._servir(
            query={"id": str(_TMDB_ID), "size": _SIZE, "force": "1"},
            session=self._session_qui_repond(b"RIFFxxxxWEBP", content_type="image/webp"),
            poster_path="/abc123.webp",
        )

        self.assertEqual(handler.status_code, 200)
        self.assertEqual(self._fichiers_en_cache(), [f"{_TMDB_ID}.webp"])


class LeCacheResteServiSansForceTests(_ProxyPosterBase):
    """Non-regression : `force` absent, le cache repond sans toucher au reseau."""

    def test_un_hit_ne_declenche_aucun_appel_reseau(self) -> None:
        self._peupler_le_cache()
        # Pas de `side_effect` qui leve : la frontiere `except Exception` de
        # `fetch_and_cache` avalerait l'echec et le test passerait quand meme.
        # On CONSTATE l'absence d'appel a la place.
        session = self._session_qui_repond(_NOUVELLE)

        handler = self._servir(query={"id": str(_TMDB_ID), "size": _SIZE}, session=session)

        session.get.assert_not_called()
        self.assertEqual(handler.status_code, 200)
        self.assertEqual(handler.body.getvalue(), _ANCIENNE)
        self.assertEqual(self._fichiers_en_cache(), [f"{_TMDB_ID}.jpg"])


if __name__ == "__main__":
    unittest.main()
