"""ITER14 — Couverture defense-en-profondeur : 5 endpoints facade non-loopback.

Couvre :
- 5 endpoints repartis sur 5 facades distinctes (run, settings, quality,
  integrations, library) en POST.
- Avec CINESORT_DISABLE_LOCAL_AUTH=1 (bypass loopback design desactive), tout
  appel SANS token doit renvoyer 401 + X-Request-Id, defense-en-profondeur
  fermee uniformement par le middleware auth unifie (refactor aea6b98).
- Avec un BON token, la facade dispatch normalement (statut 2xx/3xx/4xx
  metier, mais JAMAIS 401/410).

Contexte memoire user :
- AUCUNE deviation comportement auth observable autre que :
  - rate-limit 410 -> 429 (chemin facade)
  - X-Request-Id sur 401
- BYPASS LOOPBACK CONSERVE : seul le kill-switch CINESORT_DISABLE_LOCAL_AUTH=1
  permet de tester le contrat 401 reel en loopback (cf test_dashboard_shell.py
  re-ancrage fd3eba3f).

Ce test verrouille le contrat "5 endpoints facade non-loopback sans token -> 401".
Si un futur refactor accidentellement court-circuite l'auth sur un endpoint
facade specifique (ex : route ajoutee qui oublie de passer par le dispatcher
commun), il rougira ici en premier.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.rest_server import RestApiServer
from tests._helpers import find_free_port as _find_free_port

# 5 endpoints facade NON destructifs / NON state-mutating, choisis pour couvrir
# les 5 facades distinctes. Chacun est un getter simple (pas de side-effect
# si auth passait par erreur — defense en profondeur, mais robuste meme en cas
# de regression). Toute reponse doit etre 401 sans token.
_FACADE_ENDPOINTS = (
    "/api/settings/get_settings",
    "/api/run/list_runs",
    "/api/quality/get_quality_metrics_status",
    "/api/integrations/get_jellyfin_libraries",
    "/api/library/export_films",
)


class FacadeEndpointsAuthUnifieTests(unittest.TestCase):
    """ITER14 : middleware auth unifie ferme les 5 endpoints facade en non-loopback."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_facade_auth_")
        root = Path(cls._tmp) / "root"
        state_dir = Path(cls._tmp) / "state"
        root.mkdir()
        state_dir.mkdir()

        cls.api = backend.CineSortApi()
        cls.api.settings.save_settings(
            {
                "root": str(root),
                "state_dir": str(state_dir),
                "tmdb_enabled": False,
            }
        )

        # ITER14 : kill-switch CINESORT_DISABLE_LOCAL_AUTH=1 desactive le bypass
        # loopback design (rest_server.py L443-462). Le code emprunte alors la
        # branche Bearer nominale (L463-508), exactement comme un client LAN
        # non-loopback sur bind 0.0.0.0. C'est le meme pattern que ITER5 fd3eba3f.
        cls._saved_disable_local_auth = os.environ.get("CINESORT_DISABLE_LOCAL_AUTH")
        os.environ["CINESORT_DISABLE_LOCAL_AUTH"] = "1"

        cls.port = _find_free_port()
        cls.token = "facade-auth-unifie-token-42"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        if cls._saved_disable_local_auth is None:
            os.environ.pop("CINESORT_DISABLE_LOCAL_AUTH", None)
        else:
            os.environ["CINESORT_DISABLE_LOCAL_AUTH"] = cls._saved_disable_local_auth
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _post(self, path: str, token: str | None = None) -> tuple[int, dict, bytes]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", path, body=b"{}", headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        body = resp.read()
        conn.close()
        return status, resp_headers, body

    def test_all_facade_endpoints_no_token_returns_401(self) -> None:
        """Sans header Authorization : tous les endpoints facade -> 401.

        Memoire user : "GATE AUTH = matrice runtime non-loopback no/wrong->401".
        Le middleware auth unifie (refactor aea6b98) doit etre la SEULE porte.
        """
        for endpoint in _FACADE_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                status, headers, _body = self._post(endpoint, token=None)
                self.assertEqual(
                    status,
                    401,
                    f"{endpoint} sans token devait renvoyer 401, got {status}",
                )
                # Defense-en-profondeur : X-Request-Id sur 401 (fix #4).
                rid = headers.get("x-request-id")
                self.assertIsNotNone(
                    rid,
                    f"{endpoint} : X-Request-Id absent sur 401, headers={headers}",
                )

    def test_all_facade_endpoints_wrong_token_returns_401(self) -> None:
        """Avec mauvais token : tous les endpoints facade -> 401."""
        for endpoint in _FACADE_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                status, headers, _body = self._post(endpoint, token="wrong-token")
                self.assertEqual(
                    status,
                    401,
                    f"{endpoint} avec wrong-token devait renvoyer 401, got {status}",
                )
                rid = headers.get("x-request-id")
                self.assertIsNotNone(
                    rid,
                    f"{endpoint} : X-Request-Id absent sur 401, headers={headers}",
                )

    def test_facade_endpoints_valid_token_not_401(self) -> None:
        """Avec bon token : aucun endpoint ne doit renvoyer 401 ou 410.

        On verifie que l'auth passe (status != 401) ET que le dispatcher
        facade fonctionne (status != 410, qui serait l'erreur "use facade
        instead" si on tapait par erreur le chemin legacy). Le statut metier
        exact (200, 4xx, 5xx selon l'API) n'est pas l'objet de ce test.
        """
        for endpoint in _FACADE_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                status, _headers, body = self._post(endpoint, token=self.token)
                self.assertNotEqual(
                    status,
                    401,
                    f"{endpoint} avec bon token NE doit PAS renvoyer 401 (body={body!r})",
                )
                self.assertNotEqual(
                    status,
                    410,
                    f"{endpoint} renvoie 410 -> le path n'est pas reconnu comme facade (body={body!r})",
                )


if __name__ == "__main__":
    unittest.main()
