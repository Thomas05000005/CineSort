"""Regression test for BOM-prefixed settings.json (REST token 401 bug).

Contexte :
    Si l'utilisateur (ou un editeur Windows / PowerShell `Out-File` par defaut)
    sauvegarde `settings.json` avec un BOM UTF-8 (`\\ufeff` en tete), la lecture
    via `Path.read_text(encoding="utf-8")` decode le BOM comme un caractere
    invisible `\\ufeff` en tete de la chaine. `json.loads` recoit alors une
    chaine qui ne commence pas par `{` -> `json.JSONDecodeError`. Le bloc
    `except Exception` dans `app._start_rest_server` masquait alors le token
    avec `_SECRET_MASK`, ce qui produisait des reponses 401 systematiques
    sur toutes les requetes REST locales (et donc sur l'UI desktop pywebview).

Fix : utiliser `encoding="utf-8-sig"` qui tolere ET supprime le BOM si present,
et reste compatible avec les fichiers sans BOM.

Ce test :
1. Genere un settings.json avec un BOM UTF-8 contenant un `rest_api_token` connu.
2. Reproduit la sequence de lecture de `_start_rest_server` (app.py:~281).
3. Verifie que le token decoded est bien le token attendu (pas `_SECRET_MASK`,
   pas un fallback vide, pas une UnicodeDecodeError).
4. Verifie en bonus qu'un settings.json sans BOM continue de fonctionner
   (compat ascendante absolue, cf. memoire utilisateur).
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PY = REPO_ROOT / "app.py"


class AppSettingsBomTests(unittest.TestCase):
    """Regression tests pour le bug 401 declenche par un BOM dans settings.json."""

    def _write_settings(self, dirpath: Path, payload: dict, *, with_bom: bool) -> Path:
        """Ecrit un settings.json avec ou sans BOM UTF-8."""
        settings_path = dirpath / "settings.json"
        raw = json.dumps(payload, ensure_ascii=False)
        data = raw.encode("utf-8")
        if with_bom:
            data = b"\xef\xbb\xbf" + data
        settings_path.write_bytes(data)
        return settings_path

    def test_bom_settings_loaded_without_unicode_error(self) -> None:
        """Reproduit la lecture de _start_rest_server avec un settings.json BOM."""
        import tempfile

        expected_token = "abcdef0123456789abcdef0123456789"
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = self._write_settings(
                Path(tmp),
                {"rest_api_token": expected_token, "rest_api_port": 8642},
                with_bom=True,
            )

            # Sanity check : le fichier a bien un BOM en tete (sinon le test est trompeur).
            head = settings_path.read_bytes()[:3]
            self.assertEqual(head, b"\xef\xbb\xbf", "Le fichier de test doit contenir un BOM UTF-8")

            # Avant le fix : 'utf-8' strict decodait le BOM en ﻿, puis json.loads
            # plantait sur "Expecting value" (la chaine commencait par ﻿ au lieu
            # de '{'). On reproduit cette regression pour garantir que le bug existait.
            decoded_strict = settings_path.read_text(encoding="utf-8")
            self.assertTrue(
                decoded_strict.startswith("﻿"),
                "utf-8 strict doit conserver le BOM comme caractere \\ufeff",
            )
            with self.assertRaises(json.JSONDecodeError):
                json.loads(decoded_strict)

            # Apres le fix : utf-8-sig supprime le BOM, json.loads passe, le token est OK.
            raw = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                str(raw.get("rest_api_token") or "").strip(),
                expected_token,
                "Le token doit etre lu correctement malgre le BOM",
            )

    def test_no_bom_settings_still_works(self) -> None:
        """Compat ascendante : settings.json sans BOM (cas nominal) toujours OK."""
        import tempfile

        expected_token = "deadbeefdeadbeefdeadbeefdeadbeef"
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = self._write_settings(
                Path(tmp),
                {"rest_api_token": expected_token},
                with_bom=False,
            )
            head = settings_path.read_bytes()[:3]
            self.assertNotEqual(head, b"\xef\xbb\xbf", "Le fichier de test ne doit pas contenir de BOM")

            raw = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                str(raw.get("rest_api_token") or "").strip(),
                expected_token,
            )

    def test_app_py_resolves_token_via_internal_settings(self) -> None:
        """[SEC-2] app.py doit resoudre le token de boot via le chemin DECHIFFRE.

        Depuis SEC-2, rest_api_token est chiffre au repos (enveloppe
        rest_api_token_secret) : le clair n'est plus dans settings.json. Le boot
        du serveur REST (_start_rest_server) doit donc lire le token via
        `api._internal_settings()` (qui dechiffre), PAS via une lecture brute de
        settings.json + fallback sur la valeur masquee. Ce garde-fou empeche une
        regression vers l'ancienne lecture brute (qui redonnait "" -> masque ->
        bind LAN retrograde). Le BOM reste tolere : read_settings lit en utf-8-sig.
        """
        self.assertTrue(APP_PY.is_file(), f"app.py introuvable a {APP_PY}")
        source = APP_PY.read_text(encoding="utf-8")
        self.assertIn(
            "_internal_settings()",
            source,
            "app.py doit resoudre le token de boot via _internal_settings() (SEC-2)",
        )
        # L'ancienne lecture brute du token clair ne doit PAS revenir.
        self.assertNotIn(
            'raw.get("rest_api_token")',
            source,
            "app.py ne doit plus lire le token clair brut de settings.json (SEC-2)",
        )
        # Le BOM reste tolere, mais au bon endroit : read_settings (utf-8-sig).
        settings_support_src = (REPO_ROOT / "cinesort" / "ui" / "api" / "settings_support.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'encoding="utf-8-sig"',
            settings_support_src,
            "read_settings doit lire settings.json en utf-8-sig (tolerance BOM)",
        )

    def test_start_rest_server_uses_internal_settings_token(self) -> None:
        """[SEC-2] Integration : _start_rest_server passe le token CLAIR issu de
        _internal_settings() (dechiffre), PAS la valeur masquee de get_settings.

        Depuis SEC-2 le token est chiffre au repos ; get_settings() renvoie le
        masque "••••••••". Le boot doit lire le token via _internal_settings()
        (qui dechiffre). On mocke une api dont get_settings renvoie le MASQUE et
        _internal_settings renvoie le CLAIR, et on verifie que le serveur recoit
        le CLAIR (une regression le ferait demarrer avec le masque -> bind LAN
        retrograde).
        """
        import sys
        import tempfile
        import types
        from unittest import mock

        from cinesort.ui.api.settings_support import _SECRET_MASK

        # Charger app.py
        spec = importlib.util.spec_from_file_location("cinesort_app_settings_bom", APP_PY)
        assert spec is not None and spec.loader is not None
        app_module = importlib.util.module_from_spec(spec)
        # Stubber pywebview qui peut etre necessaire a l'import
        if "webview" not in sys.modules:
            sys.modules["webview"] = types.SimpleNamespace(
                create_window=lambda *a, **k: None,
                start=lambda *a, **k: None,
            )
        spec.loader.exec_module(app_module)

        expected_token = "0123456789abcdef0123456789abcdef"

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            # settings.json existe (le boot n'a pas a le lire pour le token, mais
            # port/host viennent de get_settings).
            self._write_settings(
                state_dir,
                {"rest_api_port": 18642, "rest_api_enabled": False},
                with_bom=True,
            )

            # get_settings() -> MASQUE (comportement reel post-SEC-2) ;
            # _internal_settings() -> token CLAIR (chemin dechiffre).
            masked_settings = {
                "rest_api_token": _SECRET_MASK,
                "rest_api_port": 18642,
                "rest_api_enabled": False,
            }
            internal_settings = dict(masked_settings)
            internal_settings["rest_api_token"] = expected_token
            fake_api = types.SimpleNamespace(
                _state_dir=str(state_dir),
                _internal_settings=lambda: dict(internal_settings),
                settings=types.SimpleNamespace(
                    get_settings=lambda: dict(masked_settings),
                    save_settings=lambda s: None,
                ),
            )

            # Mocker RestApiServer pour capturer le token effectivement passe.
            captured: dict = {}

            class FakeRestApiServer:
                def __init__(self, api, **kwargs):
                    captured.update(kwargs)
                    self._is_https = False
                    self.host = kwargs.get("host", "127.0.0.1")
                    self.lan_demoted = False
                    self.lan_demotion_reason = ""
                    self.port = kwargs.get("port")

                def start(self) -> None:
                    return None

                def stop(self) -> None:
                    return None

            fake_rest_server_module = types.SimpleNamespace(RestApiServer=FakeRestApiServer)
            with mock.patch.dict(
                sys.modules,
                {"cinesort.infra.rest_server": fake_rest_server_module},
            ):
                app_module._start_rest_server(fake_api)

            self.assertEqual(
                captured.get("token"),
                expected_token,
                "Le token passe au RestApiServer doit etre le CLAIR (_internal_settings), pas le masque",
            )
            self.assertNotEqual(
                captured.get("token"),
                _SECRET_MASK,
                "Le serveur ne doit JAMAIS demarrer avec le masque (bind LAN retrograde)",
            )


if __name__ == "__main__":
    unittest.main()
