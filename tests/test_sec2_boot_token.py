"""[SEC-2 FIX-2] Boot du serveur REST : le token vient du chemin DECHIFFRE.

Regression trouvee par revue adversaire : depuis SEC-2, rest_api_token est
chiffre au repos (enveloppe rest_api_token_secret), le clair n'est plus dans
settings.json. Or app._start_rest_server lisait encore le token en clair depuis
le JSON brut -> vide -> fallback sur la valeur MASQUEE "••••••••" -> le serveur
demarrait avec un token de 8 puces et RETROGRADAIT le bind LAN 0.0.0.0->127.0.0.1
(len < MIN_LAN_TOKEN_LENGTH) -> appareils distants coupes, 401 systematique.

Fix : resoudre le token via api._internal_settings() (dechiffre). Ces tests
verrouillent le contrat.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PY = REPO_ROOT / "app.py"

from cinesort.ui.api.settings_support import (  # noqa: E402
    _SECRET_MASK,
    REST_TOKEN_SECRET_FIELD,
    read_settings,
    write_settings,
)


def _load_app_module():
    spec = importlib.util.spec_from_file_location("cinesort_app_sec2_boot", APP_PY)
    assert spec is not None and spec.loader is not None
    app_module = importlib.util.module_from_spec(spec)
    if "webview" not in sys.modules:
        sys.modules["webview"] = types.SimpleNamespace(
            create_window=lambda *a, **k: None,
            start=lambda *a, **k: None,
        )
    spec.loader.exec_module(app_module)
    return app_module


class _FakeRestApiServer:
    def __init__(self, api, **kwargs):
        self.captured = kwargs
        _CAPTURED.update(kwargs)
        self._is_https = False
        self.host = kwargs.get("host", "127.0.0.1")
        self.lan_demoted = False
        self.lan_demotion_reason = ""
        self.port = kwargs.get("port")

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


_CAPTURED: dict = {}


class Sec2BootTokenSourceTests(unittest.TestCase):
    """Garde-fou SOURCE : app.py resout le token via _internal_settings()."""

    def test_app_py_utilise_internal_settings_pour_le_token(self) -> None:
        source = APP_PY.read_text(encoding="utf-8")
        self.assertIn("_internal_settings()", source)
        # L'ancienne lecture brute du token clair ne doit pas revenir (boot desktop).
        self.assertNotIn('raw.get("rest_api_token")', source)
        # [FIX-4] Le boot headless (--api) ne doit PAS lire le token depuis la
        # valeur MASQUEE de get_settings() (`settings` = get_settings() masque).
        self.assertNotIn(
            'token = str(settings.get("rest_api_token")',
            source,
            "app.py main_api ne doit pas lire le token masque de get_settings (FIX-4)",
        )


class Sec2BootTokenIntegrationTests(unittest.TestCase):
    """Integration : _start_rest_server passe le CLAIR, jamais le masque."""

    def test_boot_passe_le_token_clair_pas_le_masque(self) -> None:
        _CAPTURED.clear()
        app_module = _load_app_module()
        expected = "0123456789abcdef0123456789abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            (state_dir / "settings.json").write_text(
                json.dumps({"rest_api_port": 18642, "rest_api_enabled": False}),
                encoding="utf-8",
            )
            # get_settings() -> MASQUE (reel post-SEC-2) ; _internal_settings() -> CLAIR.
            masked = {"rest_api_token": _SECRET_MASK, "rest_api_port": 18642, "rest_api_enabled": False}
            internal = {**masked, "rest_api_token": expected}
            fake_api = types.SimpleNamespace(
                _state_dir=str(state_dir),
                _internal_settings=lambda: dict(internal),
                settings=types.SimpleNamespace(
                    get_settings=lambda: dict(masked),
                    save_settings=lambda s: None,
                ),
            )
            with mock.patch("cinesort.infra.rest_server.RestApiServer", _FakeRestApiServer):
                app_module._start_rest_server(fake_api)
            self.assertEqual(_CAPTURED.get("token"), expected, "boot doit passer le CLAIR")
            self.assertNotEqual(_CAPTURED.get("token"), _SECRET_MASK, "jamais le masque")


@unittest.skipUnless(os.name == "nt", "DPAPI specifique a Windows")
class Sec2BootBomEnvelopeTests(unittest.TestCase):
    """Le vrai chemin (read_settings) dechiffre un token chiffre malgre un BOM."""

    def test_bom_settings_avec_enveloppe_chiffree_donne_le_clair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            token = "bom-plus-envelope-token-abcdef01"
            # 1) ecrire (chiffre l'enveloppe)
            write_settings(state, {"rest_api_token": token, "rest_api_enabled": True})
            # 2) re-ecrire le fichier AVEC un BOM en tete (editeur Windows)
            p = state / "settings.json"
            p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
            # 3) read_settings tolere le BOM (utf-8-sig) ET dechiffre l'enveloppe.
            got = read_settings(state)
            self.assertEqual(got.get("rest_api_token"), token)
            self.assertNotIn(REST_TOKEN_SECRET_FIELD, got)


if __name__ == "__main__":
    unittest.main()
