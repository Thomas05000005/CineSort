from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class AppBridgeSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("cinesort_app_bridge_smoke", cls.repo_root / "app.py")
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        cls.app_module = module

    def test_main_bootstraps_stable_webview_with_real_api(self) -> None:
        windows: list[dict] = []

        def fake_create_window(title: str, **kwargs: object) -> object:
            win = {"title": title, **kwargs}
            # Simuler un objet fenetre avec les attributs necessaires
            obj = types.SimpleNamespace(
                evaluate_js=lambda js: None,
                show=lambda: None,
                destroy=lambda: None,
                **kwargs,
            )
            win["_obj"] = obj
            windows.append(win)
            return obj

        def fake_start(func=None, **kwargs: object) -> None:
            # Executer la fonction de startup si fournie.
            # **kwargs absorbe tous les args optionnels (debug, private_mode,
            # storage_path, etc.) pour rester drop-in si la signature de
            # webview.start evolue.
            if func is not None:
                func()

        fake_webview = types.SimpleNamespace(
            create_window=fake_create_window,
            start=fake_start,
        )

        with mock.patch.dict(sys.modules, {"webview": fake_webview}):
            with mock.patch.object(sys, "argv", ["app.py"]):
                with mock.patch.dict(os.environ, {"DEV_MODE": "", "CINESORT_UI": ""}, clear=False):
                    self.app_module.main()

        # 2 fenetres creees : splash (0) + main (1)
        self.assertEqual(len(windows), 2, f"Expected 2 windows, got {len(windows)}")

        splash = windows[0]
        main = windows[1]

        # Splash : frameless, petite, on_top
        self.assertIn("frameless", splash)
        self.assertTrue(splash.get("frameless"))
        self.assertEqual(splash.get("width"), 520)
        self.assertEqual(splash.get("height"), 320)
        self.assertTrue(splash.get("on_top"))

        # Main : titre correct, dimensions, hidden au depart
        self.assertEqual(
            main.get("title"),
            "CineSort - Tri & normalisation de bibliotheque films",
        )
        # UI unifiee : le main charge soit le dashboard via HTTP local (si serveur REST demarre)
        # soit web/dashboard/index.html en fallback. Les deux sont acceptables.
        url = main.get("url", "")
        valid_urls = [
            "http://127.0.0.1",  # dashboard via REST local
            (self.repo_root / "web" / "dashboard" / "index.html").resolve().as_uri(),  # fallback dashboard
            (self.repo_root / "web" / "index.html").resolve().as_uri(),  # fallback legacy
        ]
        self.assertTrue(
            any(str(url).startswith(u) for u in valid_urls),
            f"URL inattendue : {url}",
        )
        self.assertEqual(main.get("width"), 1250)
        self.assertEqual(main.get("height"), 820)
        self.assertEqual(main.get("min_size"), (1000, 700))
        self.assertTrue(main.get("hidden"))
        # js_api doit etre passe a create_window (pas assigne apres coup)
        self.assertIsNotNone(main.get("js_api"), "js_api doit etre passe a create_window")
        self.assertTrue(hasattr(main.get("js_api"), "get_settings"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
