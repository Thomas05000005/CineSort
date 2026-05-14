"""Tests pour les fixes #72 open_logs_folder local-only et #73 expandvars REST distant."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from cinesort.infra.log_context import (
    is_remote_request,
    reset_remote_request,
    set_remote_request,
)


class RemoteRequestContextVarTests(unittest.TestCase):
    """ContextVar de base pour distinguer caller local vs REST distant."""

    def setUp(self) -> None:
        # Defaut = local (False)
        self.assertFalse(is_remote_request())

    def test_set_remote_request_true(self) -> None:
        token = set_remote_request(True)
        try:
            self.assertTrue(is_remote_request())
        finally:
            reset_remote_request(token)
        # Apres reset, retour au defaut
        self.assertFalse(is_remote_request())

    def test_set_remote_request_false_explicit(self) -> None:
        token = set_remote_request(False)
        try:
            self.assertFalse(is_remote_request())
        finally:
            reset_remote_request(token)


class OpenLogsFolderLocalOnlyTests(unittest.TestCase):
    """Issue #72 : open_logs_folder refuse les requetes REST distantes."""

    def test_open_logs_folder_blocked_when_remote(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        token = set_remote_request(True)
        try:
            result = api.open_logs_folder()
            self.assertFalse(result["ok"])
            self.assertIn("locale", result.get("error", "").lower())
        finally:
            reset_remote_request(token)

    def test_open_logs_folder_works_when_local_dir_exists(self) -> None:
        """Verifie au moins que le mecanisme de blocage est local-only.

        On ne lance pas vraiment os.startfile (effet de bord). On verifie
        seulement que sans remote_request, la fonction ne retourne pas
        l'erreur de blocage REST.
        """
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        # remote=False par defaut
        result = api.open_logs_folder()
        # Soit ok=True (le dossier existe et startfile a marche),
        # soit ok=False avec message != "locale uniquement" (dossier manquant)
        if not result["ok"]:
            self.assertNotIn("locale uniquement", result.get("error", "").lower())


class NormalizeUserPathRemoteTests(unittest.TestCase):
    """Issue #73 : normalize_user_path bypass expandvars en mode REST distant."""

    def test_expandvars_active_when_local(self) -> None:
        from cinesort.ui.api.settings_support import normalize_user_path

        # Ajoute une env var de test
        os.environ["CINESORT_TEST_PATH"] = "C:\\TestPath"
        try:
            # Local : expandvars doit transformer %CINESORT_TEST_PATH%
            result = normalize_user_path("%CINESORT_TEST_PATH%\\Movies", default=Path("/default"))
            self.assertIn("TestPath", str(result))
            self.assertNotIn("%", str(result))
        finally:
            os.environ.pop("CINESORT_TEST_PATH", None)

    def test_expandvars_blocked_when_remote(self) -> None:
        from cinesort.ui.api.settings_support import normalize_user_path

        os.environ["CINESORT_TEST_PATH2"] = "C:\\Secret"
        token = set_remote_request(True)
        try:
            result = normalize_user_path("%CINESORT_TEST_PATH2%\\Movies", default=Path("/default"))
            # En mode remote : pas d'expandvars, le % reste litteral
            self.assertIn("%CINESORT_TEST_PATH2%", str(result))
        finally:
            reset_remote_request(token)
            os.environ.pop("CINESORT_TEST_PATH2", None)

    def test_expanduser_still_active_when_remote(self) -> None:
        """expanduser reste actif meme en remote (non-amplifiant, juste ~ → home)."""
        from cinesort.ui.api.settings_support import normalize_user_path

        token = set_remote_request(True)
        try:
            result = normalize_user_path("~/Movies", default=Path("/default"))
            self.assertNotIn("~", str(result))
        finally:
            reset_remote_request(token)


class ToolsManagerResolveExplicitPathTests(unittest.TestCase):
    """Issue #73 : _resolve_explicit_path dans tools_manager bypass expandvars en remote."""

    def test_resolve_blocked_expandvars_when_remote(self) -> None:
        from cinesort.infra.probe.tools_manager import _resolve_explicit_path

        os.environ["CINESORT_FFPROBE_TEST"] = "C:\\Tools"
        token = set_remote_request(True)
        try:
            result = _resolve_explicit_path("%CINESORT_FFPROBE_TEST%\\ffprobe.exe")
            self.assertIn("%CINESORT_FFPROBE_TEST%", result)
        finally:
            reset_remote_request(token)
            os.environ.pop("CINESORT_FFPROBE_TEST", None)

    def test_resolve_expandvars_when_local(self) -> None:
        from cinesort.infra.probe.tools_manager import _resolve_explicit_path

        os.environ["CINESORT_FFPROBE_TEST3"] = "C:\\Tools"
        try:
            result = _resolve_explicit_path("%CINESORT_FFPROBE_TEST3%\\ffprobe.exe")
            self.assertIn("Tools", result)
            self.assertNotIn("%", result)
        finally:
            os.environ.pop("CINESORT_FFPROBE_TEST3", None)


class RestDispatchSetsRemoteFlagTests(unittest.TestCase):
    """Verifie que le dispatch REST positionne bien le flag is_remote_request."""

    def test_rest_server_imports_set_remote(self) -> None:
        """Inspection statique : rest_server importe et utilise set_remote_request."""
        src = (Path(__file__).resolve().parents[1] / "cinesort" / "infra" / "rest_server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("set_remote_request", src)
        self.assertIn("reset_remote_request", src)
        self.assertIn("_LOCAL_CLIENT_IPS", src)
        # Doit etre appele dans do_GET ET do_POST
        self.assertGreaterEqual(src.count("set_remote_request(self._client_ip()"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
