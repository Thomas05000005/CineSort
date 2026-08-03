"""Tests pour Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 1).

Verifie que `_resolve_tool_path` valide l'existence du path explicit AVANT
de l'utiliser. Sans ce check, un settings.json obsolete (relique d'ancien
build) avec un chemin ffprobe disparu cause 100% des probes en FAILED sans
aucun feedback utilisateur (subprocess leve WinError 2 sur chaque appel).

Scenarios :
1. Path explicite valide -> retourne le path tel quel
2. Path explicite obsolete -> fallback PATH via which_fn
3. Pas de path explicite -> which_fn direct
"""

from __future__ import annotations

import unittest
from unittest import mock

from cinesort.infra.probe.tooling import _resolve_tool_path


class ResolveToolPathTests(unittest.TestCase):
    """Tests de la resolution avec validation disque (FIX 1, Vague K)."""

    def test_explicit_path_existing_returns_explicit(self) -> None:
        """Path explicite + fichier existe + nom whiteliste -> retourne explicite."""
        with mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls:
            instance = mock.MagicMock()
            instance.is_file.return_value = True
            instance.name = "ffprobe.exe"  # nom whiteliste (AUDIT 2026-06-10)
            mock_path_cls.return_value = instance
            which_fn = mock.MagicMock(return_value="C:/winget/ffprobe.exe")

            result = _resolve_tool_path(
                "C:/custom/ffprobe.exe",
                "ffprobe",
                which_fn,
            )

            self.assertEqual(result, "C:/custom/ffprobe.exe")
            # which_fn NE doit PAS etre appele si le path explicit est valide
            which_fn.assert_not_called()

    def test_explicit_path_non_whitelisted_binary_falls_back(self) -> None:
        """GATE AUDIT 2026-06-10 : un fichier existant mais dont le nom n'est PAS
        whiteliste (ex calc.exe configure via save_settings) est IGNORE et on
        retombe sur le PATH — empeche l'execution d'un binaire arbitraire."""
        with mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls:
            instance = mock.MagicMock()
            instance.is_file.return_value = True
            instance.name = "calc.exe"  # nom NON whiteliste
            mock_path_cls.return_value = instance
            which_fn = mock.MagicMock(return_value="C:/winget/ffprobe.exe")

            result = _resolve_tool_path("C:/evil/calc.exe", "ffprobe", which_fn)

            self.assertEqual(result, "C:/winget/ffprobe.exe", "doit ignorer le binaire non whiteliste")
            which_fn.assert_called_once_with("ffprobe")

    def test_explicit_path_missing_falls_back_to_PATH(self) -> None:
        """Path explicite + fichier absent (obsolete) -> fallback which_fn PATH."""
        with mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls:
            instance = mock.MagicMock()
            instance.is_file.return_value = False
            mock_path_cls.return_value = instance
            which_fn = mock.MagicMock(return_value="C:/winget/ffprobe.exe")

            result = _resolve_tool_path(
                "C:/obsolete/ffprobe.exe",
                "ffprobe",
                which_fn,
            )

            self.assertEqual(result, "C:/winget/ffprobe.exe")
            which_fn.assert_called_once_with("ffprobe")

    def test_empty_explicit_uses_PATH_directly(self) -> None:
        """Pas de path explicite -> which_fn direct, pas de check disque."""
        with mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls:
            which_fn = mock.MagicMock(return_value="C:/winget/ffprobe.exe")

            result = _resolve_tool_path("", "ffprobe", which_fn)

            self.assertEqual(result, "C:/winget/ffprobe.exe")
            which_fn.assert_called_once_with("ffprobe")
            # Path() ne doit PAS etre appele : pas de chemin a valider
            mock_path_cls.assert_not_called()

    def test_none_explicit_uses_PATH_directly(self) -> None:
        """None comme path explicite (cas frequent en pratique) -> which_fn."""
        which_fn = mock.MagicMock(return_value="/usr/bin/ffprobe")

        result = _resolve_tool_path(None, "ffprobe", which_fn)  # type: ignore[arg-type]

        self.assertEqual(result, "/usr/bin/ffprobe")
        which_fn.assert_called_once_with("ffprobe")

    def test_whitespace_only_explicit_uses_PATH(self) -> None:
        """Path explicite ne contenant que des espaces -> traite comme vide."""
        which_fn = mock.MagicMock(return_value="/usr/bin/mediainfo")

        result = _resolve_tool_path("   ", "mediainfo", which_fn)

        self.assertEqual(result, "/usr/bin/mediainfo")
        which_fn.assert_called_once_with("mediainfo")

    def test_explicit_path_missing_and_PATH_also_missing(self) -> None:
        """Path obsolete + which_fn vide -> retourne string vide."""
        with mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls:
            instance = mock.MagicMock()
            instance.is_file.return_value = False
            mock_path_cls.return_value = instance
            which_fn = mock.MagicMock(return_value=None)

            result = _resolve_tool_path(
                "C:/obsolete/ffprobe.exe",
                "ffprobe",
                which_fn,
            )

            self.assertEqual(result, "")
            which_fn.assert_called_once_with("ffprobe")

    def test_malformed_path_falls_back_gracefully(self) -> None:
        """Path mal forme (Path() leve OSError/ValueError) -> fallback PATH."""
        with mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls:
            mock_path_cls.side_effect = OSError("Invalid path")
            which_fn = mock.MagicMock(return_value="/usr/bin/ffprobe")

            result = _resolve_tool_path(
                "\x00invalid\x00",
                "ffprobe",
                which_fn,
            )

            self.assertEqual(result, "/usr/bin/ffprobe")
            which_fn.assert_called_once_with("ffprobe")

    def test_warning_logged_on_obsolete_path(self) -> None:
        """Une WARNING doit etre loggee quand on fallback PATH."""
        with (
            mock.patch("cinesort.infra.probe.tooling.Path") as mock_path_cls,
            mock.patch("cinesort.infra.probe.tooling.logger") as mock_logger,
        ):
            instance = mock.MagicMock()
            instance.is_file.return_value = False
            mock_path_cls.return_value = instance
            which_fn = mock.MagicMock(return_value="C:/winget/ffprobe.exe")

            _resolve_tool_path("C:/old/ffprobe.exe", "ffprobe", which_fn)

            mock_logger.warning.assert_called_once()
            args, _kwargs = mock_logger.warning.call_args
            self.assertIn("introuvable", args[0])


if __name__ == "__main__":
    unittest.main()
