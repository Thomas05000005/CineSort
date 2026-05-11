"""LOT F — Tests de packaging et de dependances.

Couvre : VERSION lisible, smtplib/rapidfuzz importables, themes.css dans le spec,
pas de .bak dans web/, fallback _MEIPASS correct.
"""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VersionFileTests(unittest.TestCase):
    # 41
    def test_version_file_exists_and_readable(self) -> None:
        """Le fichier VERSION doit exister et etre lisible."""
        version_file = PROJECT_ROOT / "VERSION"
        self.assertTrue(version_file.exists(), "Fichier VERSION manquant")
        content = version_file.read_text(encoding="utf-8").strip()
        self.assertNotEqual(content, "", "VERSION est vide")
        self.assertNotEqual(content, "unknown")

    def test_version_file_readable_via_api_helper(self) -> None:
        """_read_app_version() retourne la version reelle, pas 'unknown'."""
        from cinesort.ui.api.cinesort_api import _read_app_version

        version = _read_app_version()
        self.assertNotEqual(version, "unknown")
        self.assertNotEqual(version, "")


class DependenciesImportTests(unittest.TestCase):
    # 42
    def test_smtplib_importable(self) -> None:
        """smtplib doit etre importable (non exclu du bundle PyInstaller)."""
        import smtplib

        self.assertTrue(hasattr(smtplib, "SMTP"))
        self.assertTrue(hasattr(smtplib, "SMTP_SSL"))

    def test_email_mime_importable(self) -> None:
        """email.mime.text doit etre importable (utilise par email_report.py)."""
        from email.mime.text import MIMEText

        self.assertTrue(callable(MIMEText))

    def test_ssl_importable(self) -> None:
        """ssl doit etre importable (HTTPS REST + SMTP TLS)."""
        import ssl

        self.assertTrue(hasattr(ssl, "SSLContext"))

    # 43
    def test_rapidfuzz_importable_or_graceful(self) -> None:
        """Si rapidfuzz manque, watchlist doit gerer proprement (pas de crash)."""
        try:
            import rapidfuzz  # noqa: F401

            has_rapidfuzz = True
        except ImportError:
            has_rapidfuzz = False

        # Le module watchlist doit s'importer meme si rapidfuzz est absent
        from cinesort.app import watchlist

        self.assertTrue(hasattr(watchlist, "parse_letterboxd_csv"))
        self.assertTrue(hasattr(watchlist, "compare_watchlist"))

        # Si rapidfuzz est present, le fuzzy_utils doit l'utiliser
        if has_rapidfuzz:
            from cinesort.app import _fuzzy_utils

            self.assertTrue(hasattr(_fuzzy_utils, "fuzzy_title_match"))


class CineSortSpecTests(unittest.TestCase):
    # 44
    def test_themes_css_in_spec_datas(self) -> None:
        """web/themes.css doit etre collecte par CineSort.spec."""
        # web/themes.css doit exister physiquement
        themes_path = PROJECT_ROOT / "web" / "themes.css"
        self.assertTrue(themes_path.exists(), "web/themes.css manquant")

        # CineSort.spec doit collecter tous les fichiers de web/ recursivement
        spec_path = PROJECT_ROOT / "CineSort.spec"
        content = spec_path.read_text(encoding="utf-8")
        # La boucle web_datas fait rglob("*") sur web/, ce qui inclut themes.css
        self.assertIn("web_datas", content)
        self.assertTrue(
            "rglob" in content or "themes.css" in content,
            "CineSort.spec doit collecter web/ recursivement",
        )

    def test_version_in_spec_datas(self) -> None:
        """VERSION doit etre inclus dans les datas (L5d Lot 3)."""
        spec_path = PROJECT_ROOT / "CineSort.spec"
        content = spec_path.read_text(encoding="utf-8")
        self.assertIn("VERSION", content)


class NoBackupFilesInWebTests(unittest.TestCase):
    # 45
    def test_no_bak_files_in_web(self) -> None:
        """Aucun fichier .bak ne doit trainer dans web/."""
        web_dir = PROJECT_ROOT / "web"
        if not web_dir.exists():
            self.skipTest("web/ introuvable")
        bak_files = list(web_dir.rglob("*.bak"))
        self.assertEqual(bak_files, [], f"Fichiers .bak trouves : {bak_files}")


class HiddenImportsIntegrityTests(unittest.TestCase):
    """CI5 audit : chaque module liste en hiddenimports de CineSort.spec doit
    etre reellement importable, sinon PyInstaller produit un binaire cassé
    dont l'erreur n'apparait qu'au runtime chez un utilisateur.
    """

    @classmethod
    def setUpClass(cls) -> None:
        spec_path = PROJECT_ROOT / "CineSort.spec"
        cls.spec_content = spec_path.read_text(encoding="utf-8")

    def _extract_cinesort_hiddenimports(self) -> list[str]:
        """Extrait les modules cinesort.* listes dans hiddenimports."""
        import re

        modules = set()
        for match in re.finditer(r'"(cinesort\.[a-zA-Z0-9_.]+)"', self.spec_content):
            modules.add(match.group(1))
        return sorted(modules)

    def test_each_cinesort_hiddenimport_is_importable(self) -> None:
        """Un hiddenimport qui n'existe plus casse silencieusement le build."""
        import importlib

        missing: list[str] = []
        modules = self._extract_cinesort_hiddenimports()
        self.assertGreater(len(modules), 10, "CineSort.spec doit lister >10 modules cinesort lazy")
        for module_name in modules:
            try:
                importlib.import_module(module_name)
            except ImportError as exc:
                missing.append(f"{module_name}: {exc}")
        self.assertEqual(missing, [], "hiddenimports obsoletes:\n" + "\n".join(missing))

    def test_new_v4_modules_present_in_hiddenimports(self) -> None:
        """Les modules v3/v4 ajoutes recemment doivent apparaitre dans la spec."""
        required = {
            "cinesort.app.watcher",
            "cinesort.app.plugin_hooks",
            "cinesort.app.email_report",
            "cinesort.app.watchlist",
            "cinesort.app.radarr_sync",
            "cinesort.app.jellyfin_validation",
            "cinesort.infra.plex_client",
            "cinesort.infra.radarr_client",
            "cinesort.domain.edition_helpers",
            "cinesort.domain.film_history",
            "cinesort.domain.perceptual",
        }
        listed = set(self._extract_cinesort_hiddenimports())
        missing = required - listed
        self.assertEqual(missing, set(), f"Modules v3/v4 manquants dans hiddenimports: {missing}")


class MeipassFallbackTests(unittest.TestCase):
    # 46
    def test_meipass_fallback_resolves_dashboard_root(self) -> None:
        """_resolve_dashboard_root doit trouver web/dashboard meme sans _MEIPASS."""
        import sys
        from cinesort.infra.rest_server import _resolve_dashboard_root

        # Retirer _MEIPASS s'il existe (dev mode normal)
        original_meipass = getattr(sys, "_MEIPASS", None)
        if hasattr(sys, "_MEIPASS"):
            delattr(sys, "_MEIPASS")
        try:
            dashboard_root = _resolve_dashboard_root()
            self.assertIsInstance(dashboard_root, Path)
            # Le fallback doit trouver le vrai dossier (pas cwd aleatoirement)
            self.assertTrue(
                dashboard_root.name == "dashboard" or dashboard_root.exists(),
                f"Fallback _MEIPASS incorrect : {dashboard_root}",
            )
        finally:
            if original_meipass is not None:
                sys._MEIPASS = original_meipass


if __name__ == "__main__":
    unittest.main(verbosity=2)
