"""Tests Phase 6 (spec 11 §OMDb) : les 6 etats UI explicites pour OMDb dans
la vue Parametres.

Contexte
--------
La specification 11 (§OMDb) exige que la section OMDb des Parametres affiche
un panneau de statut explicite parmi 6 etats :

  1. non-configure  : toggle OFF
  2. config-pending : toggle ON + cle vide
  3. ok             : toggle ON + cle + dernier test 200 (vert)
  4. ko-401         : test renvoie 401 (rouge)
  5. ko-429         : test renvoie 429 (orange)
  6. ko-reseau      : timeout / connection error (orange)

Ces tests verrouillent :
- Cote JS : presence du helper `_renderOmdbStatus` et des 6 etats en source
  + injection du panneau dans la section OMDb + appel du backend avec capture
  du statut HTTP et du quota.
- Cote backend : `OmdbClient.test_connection` retourne bien les champs
  `error_code` (auth/quota/network/timeout) et `quota_remaining/limit` pour
  chacun des codes HTTP cibles (200/401/429/timeout).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from cinesort.infra.omdb_client import OmdbClient

_ROOT = Path(__file__).resolve().parents[1]
_PARAMETRES_JS = _ROOT / "web" / "dashboard" / "views" / "parametres.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class OmdbStatusJsTests(unittest.TestCase):
    """Verifie que parametres.js implemente bien les 6 etats UI cible."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(_PARAMETRES_JS)

    def test_render_omdb_status_helper_exists(self) -> None:
        """Le helper `_renderOmdbStatus(state, data)` doit etre defini."""
        self.assertIn(
            "function _renderOmdbStatus(",
            self.src,
            "parametres.js doit definir le helper _renderOmdbStatus(state, data)",
        )
        self.assertIn(
            "function _computeOmdbState(",
            self.src,
            "parametres.js doit definir le helper _computeOmdbState(settings, lastTest)",
        )

    def test_six_explicit_states_present(self) -> None:
        """Les 6 etats cible doivent apparaitre litteralement dans le source."""
        for state in (
            "non-configure",
            "config-pending",
            "ok",
            "ko-401",
            "ko-429",
            "ko-reseau",
        ):
            self.assertIn(
                state,
                self.src,
                f"Etat '{state}' absent de parametres.js (Spec 11 §OMDb)",
            )

    def test_state_messages_match_spec(self) -> None:
        """Chaque etat doit afficher le libelle requis par la spec."""
        # non-configure : "OMDb desactive"
        self.assertIn("OMDb desactive", self.src)
        # config-pending : "Renseignez votre cle OMDb"
        self.assertIn("Renseignez votre cle OMDb", self.src)
        # ok : "Connecte" + "quota"
        self.assertIn("Connecte", self.src)
        self.assertIn("quota", self.src.lower())
        # ko-401 : "Cle invalide"
        self.assertIn("Cle invalide", self.src)
        self.assertIn("401", self.src)
        # ko-429 : "Quota depasse"
        self.assertIn("Quota depasse", self.src)
        self.assertIn("429", self.src)
        # ko-reseau : "Reseau inaccessible"
        self.assertIn("Reseau inaccessible", self.src)

    def test_panel_injected_in_omdb_section(self) -> None:
        """Le panneau de statut doit etre injecte au-dessus des champs OMDb."""
        # On verifie que le rendering de section appelle bien _renderOmdbStatus
        # pour la section id == "omdb"
        self.assertIn('section.id === "omdb"', self.src)
        # Et que le panneau porte bien l'attribut data-omdb-status
        self.assertIn("data-omdb-status", self.src)

    def test_test_button_handler_uses_error_code_and_quota(self) -> None:
        """Le handler doit lire `error_code` + `quota_remaining`/`quota_limit`."""
        self.assertIn("omdb_api_key", self.src)
        self.assertIn("error_code", self.src)
        self.assertIn("quota_remaining", self.src)
        self.assertIn("quota_limit", self.src)
        # Le state est invalide quand le toggle ou la cle change
        self.assertIn("_state.omdbLastTest", self.src)


class OmdbStatusCssTests(unittest.TestCase):
    """Verifie que components.css definit bien les 6 variantes visuelles."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(_COMPONENTS_CSS)

    def test_css_variants_present(self) -> None:
        for variant in (
            ".parametres-omdb-status--off",
            ".parametres-omdb-status--pending",
            ".parametres-omdb-status--ok",
            ".parametres-omdb-status--ko-auth",
            ".parametres-omdb-status--ko-quota",
            ".parametres-omdb-status--ko-net",
        ):
            self.assertIn(
                variant,
                self.src,
                f"Variante CSS '{variant}' manquante dans components.css",
            )


# --- Backend : OmdbClient.test_connection ---------------------------------


def _mock_resp(status: int, json_data: dict | None = None, headers: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {}
    r.headers = headers or {}
    return r


class OmdbTestConnectionContractTests(unittest.TestCase):
    """Verrouille le contrat de retour de OmdbClient.test_connection (utilise
    par integrations_facade.test_omdb_connection -> consomme par parametres.js).
    """

    def _client(self, api_key: str = "DEMOKEY") -> OmdbClient:
        tmp_dir = Path(tempfile.mkdtemp(prefix="omdb_status_"))
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        return OmdbClient(api_key=api_key, cache_path=tmp_dir / "omdb_test.json", timeout_s=2.0)

    def test_empty_key_returns_error_code(self) -> None:
        client = self._client(api_key="")
        out = client.test_connection()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "empty_key")

    def test_401_returns_auth_error_code_with_quota(self) -> None:
        client = self._client()
        mock = _mock_resp(
            401,
            json_data={"Response": "False", "Error": "Invalid API key!"},
            headers={"X-RateLimit-Remaining": "247", "X-RateLimit-Limit": "1000"},
        )
        with patch.object(client._session, "get", return_value=mock):
            out = client.test_connection()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "auth")
        self.assertEqual(out["quota_remaining"], 247)
        self.assertEqual(out["quota_limit"], 1000)

    def test_429_returns_quota_error_code(self) -> None:
        client = self._client()
        mock = _mock_resp(
            429,
            json_data={"Response": "False", "Error": "Request limit reached"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "1000"},
        )
        with patch.object(client._session, "get", return_value=mock):
            out = client.test_connection()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "quota")
        self.assertEqual(out["quota_remaining"], 0)

    def test_timeout_returns_timeout_error_code(self) -> None:
        client = self._client()
        with patch.object(client._session, "get", side_effect=requests.Timeout()):
            out = client.test_connection()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "timeout")

    def test_network_error_returns_network_error_code(self) -> None:
        client = self._client()
        with patch.object(client._session, "get", side_effect=requests.ConnectionError("DNS")):
            out = client.test_connection()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "network")

    def test_200_returns_quota_and_sample(self) -> None:
        client = self._client()
        mock = _mock_resp(
            200,
            json_data={
                "Response": "True",
                "imdbID": "tt0111161",
                "Title": "The Shawshank Redemption",
                "Year": "1994",
            },
            headers={"X-RateLimit-Remaining": "873", "X-RateLimit-Limit": "1000"},
        )
        with patch.object(client._session, "get", return_value=mock):
            out = client.test_connection()
        self.assertTrue(out["ok"], f"got: {out}")
        self.assertIsNone(out["error_code"])
        self.assertEqual(out["quota_remaining"], 873)
        self.assertEqual(out["quota_limit"], 1000)
        self.assertEqual(out["sample_title"], "The Shawshank Redemption")
        self.assertEqual(out["sample_year"], 1994)


if __name__ == "__main__":
    unittest.main()
