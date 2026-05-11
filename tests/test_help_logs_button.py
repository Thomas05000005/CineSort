"""V3-13 — Bouton "Ouvrir les logs" dans la vue Aide.

Reduit la friction "envoie-moi tes logs" pour le support utilisateur :
- Endpoints get_log_paths (info) + open_logs_folder (action locale Windows)
- V2-09 (4 mai 2026) : open_logs_folder est ACCESSIBLE via REST. Le mode
  supervision web (dashboard distant) en a besoin sinon le bouton echoue avec
  "Endpoint inconnu". Cote serveur, la methode invoque os.startfile() : cela
  ouvre l'explorateur sur la machine serveur, pas sur le client. Acceptable en
  LAN supervision normal (l'utilisateur supervise sa propre instance).
- Boutons "Ouvrir le dossier", "Copier le chemin", "Signaler un bug" dans la
  section Support de la vue Aide (parite desktop + dashboard)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class HelpLogsApiTests(unittest.TestCase):
    """Backend : methodes presentes sur CineSortApi."""

    def test_get_log_paths_method_exists(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertTrue(hasattr(CineSortApi, "get_log_paths"))

    def test_open_logs_folder_method_exists(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertTrue(hasattr(CineSortApi, "open_logs_folder"))

    def test_get_log_paths_returns_data(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        # Appel sur classe sans instancier (method binding via descriptor)
        # On utilise un objet leger qui simule self : seul os.environ est lu.
        result = CineSortApi.get_log_paths(object())
        self.assertIn("data", result)
        data = result["data"]
        self.assertIn("log_dir", data)
        self.assertIn("main_log", data)
        self.assertIn("exists", data)
        self.assertIsInstance(data["exists"], bool)

    def test_open_logs_folder_missing_dir_returns_error(self):
        """Si %LOCALAPPDATA% pointe ailleurs, on doit avoir un retour propre."""
        from cinesort.ui.api.cinesort_api import CineSortApi

        with tempfile.TemporaryDirectory() as tmp:
            # Pointer sur un dir vide pour garantir absence de logs/
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
                result = CineSortApi.open_logs_folder(object())
        self.assertFalse(result.get("ok"))
        self.assertIn("error", result)


class HelpLogsRestSecurityTests(unittest.TestCase):
    """Politique d'exposition REST des methodes locales."""

    def test_open_logs_folder_exposed_via_rest(self):
        """V2-09 (H18) : open_logs_folder doit etre EXPOSE pour le mode supervision web.

        Le bouton "Ouvrir les logs" dans web/dashboard/views/help.js et
        web/views/help.js fait apiPost("open_logs_folder"). Sans cet endpoint
        dispatchable, le bouton echoue avec "Endpoint inconnu" en mode
        supervision distante.
        Note : invoque os.startfile() cote serveur. LAN trust + auth Bearer +
        rate-limiter atterissent le risque.
        """
        from cinesort.infra.rest_server import _EXCLUDED_METHODS

        self.assertNotIn("open_logs_folder", _EXCLUDED_METHODS)

    def test_open_path_still_excluded(self):
        """Regression guard : open_path reste exclu (path arbitraire en parametre)."""
        from cinesort.infra.rest_server import _EXCLUDED_METHODS

        self.assertIn("open_path", _EXCLUDED_METHODS)


@unittest.skip("V5C-01: dashboard/views/help.js supprime — la vue Aide est desormais portee en v5 (web/views/help.js, couvert par test_help_v5_ported)")
class HelpViewSupportSectionTests(unittest.TestCase):
    """Frontend : section Support enrichie (parite desktop + dashboard)."""

    @classmethod
    def setUpClass(cls):
        cls.dashboard_js = (ROOT / "web" / "dashboard" / "views" / "help.js").read_text(encoding="utf-8")
        cls.desktop_js = (ROOT / "web" / "views" / "help.js").read_text(encoding="utf-8")

    def test_dashboard_help_has_open_logs_button(self):
        self.assertIn("btnOpenLogs", self.dashboard_js)

    def test_dashboard_help_has_copy_path_button(self):
        self.assertIn("btnCopyLogPath", self.dashboard_js)

    def test_dashboard_help_calls_get_log_paths(self):
        self.assertIn("get_log_paths", self.dashboard_js)

    def test_dashboard_help_calls_open_logs_folder(self):
        self.assertIn("open_logs_folder", self.dashboard_js)

    def test_dashboard_help_has_support_actions_container(self):
        self.assertIn("support-actions", self.dashboard_js)

    def test_desktop_help_has_open_logs_button(self):
        self.assertIn("btnOpenLogs", self.desktop_js)

    def test_desktop_help_has_copy_path_button(self):
        self.assertIn("btnCopyLogPath", self.desktop_js)

    def test_desktop_help_calls_get_log_paths(self):
        self.assertIn("get_log_paths", self.desktop_js)

    def test_desktop_help_calls_open_logs_folder(self):
        self.assertIn("open_logs_folder", self.desktop_js)


class HelpViewSupportCssTests(unittest.TestCase):
    """CSS du design system v5 partage (web/shared/components.css)."""

    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_help_support_class(self):
        self.assertIn(".help-support", self.css)

    def test_support_actions_class(self):
        self.assertIn(".support-actions", self.css)

    def test_help_support_hint_class(self):
        self.assertIn(".help-support-hint", self.css)


if __name__ == "__main__":
    unittest.main()
