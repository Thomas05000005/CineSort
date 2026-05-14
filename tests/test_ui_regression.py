"""LOT G (suite) — Tests de non-regression UI.

Couvre : _update_splash resilience (apostrophe, caracteres speciaux, splash ferme),
polling stopHomePolling, router appelle stopHomePolling au changement de vue.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import app as app_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeSplash:
    """Capture l'argument passe a evaluate_js."""

    def __init__(self) -> None:
        self.calls: list = []

    def evaluate_js(self, code: str) -> None:
        self.calls.append(code)


class SplashUpdateTests(unittest.TestCase):
    """Tests de non-regression sur _update_splash (H8)."""

    # 53 (test_splash_text_with_apostrophe)
    def test_splash_text_with_apostrophe(self) -> None:
        """_update_splash("l'interface") ne doit pas generer de JS invalide."""
        splash = _FakeSplash()
        app_module._update_splash(splash, 4, "Préparation de l'interface...", 60)
        self.assertEqual(len(splash.calls), 1)
        code = splash.calls[0]
        # Cf issue #64 : json.dumps wrap en doubles quotes, apostrophe preservee
        # (JSON spec : seul " et \ sont echappes). La string JS reste valide
        # car ouverte par " — l'apostrophe ne ferme rien.
        self.assertIn("l'interface", code)
        self.assertTrue(code.startswith('updateProgress(4, "'))

    def test_splash_text_with_backslash(self) -> None:
        splash = _FakeSplash()
        app_module._update_splash(splash, 1, "C:\\Films\\Test", 10)
        code = splash.calls[0]
        self.assertIn("C:\\\\Films\\\\Test", code)

    def test_splash_text_normal(self) -> None:
        splash = _FakeSplash()
        app_module._update_splash(splash, 2, "Chargement", 25)
        code = splash.calls[0]
        self.assertIn("Chargement", code)
        self.assertIn("2", code)
        self.assertIn("25", code)

    def test_splash_resilient_to_closed_splash(self) -> None:
        """Si evaluate_js leve, _update_splash ne crash pas."""

        class _Broken:
            def evaluate_js(self, code: str) -> None:
                raise RuntimeError("splash destroyed")

        try:
            app_module._update_splash(_Broken(), 1, "test", 10)
        except RuntimeError:
            self.fail("_update_splash doit capturer les exceptions du splash")

    def test_splash_injection_neutralized(self) -> None:
        """Injection JS via double-quote ou newline doit etre neutralisee.

        Cf issue #64 : json.dumps wrap en " et echappe ", \\, \\n, U+2028 etc.
        Une string avec ' n'est plus une attaque (pas le delimiteur), mais on
        verifie qu'une attaque via " ou \\n est correctement defusee.
        """
        splash = _FakeSplash()
        evil = 'abc"); alert("pwned"); //'
        app_module._update_splash(splash, 1, evil, 10)
        code = splash.calls[0]
        # Le " injecte doit etre echappe \" dans la sortie
        self.assertNotIn('abc");', code)
        self.assertIn('abc\\"', code)

        # Attaque via newline (was a vulnerability avant json.dumps)
        splash2 = _FakeSplash()
        app_module._update_splash(splash2, 1, "ligne1\nalert('x');//", 10)
        code2 = splash2.calls[0]
        # Le \n litteral ne doit pas casser la string JS
        self.assertNotIn("\nalert", code2)
        self.assertIn("\\n", code2)


class PollingStopContractTests(unittest.TestCase):
    """H5 : home.js doit exposer stopHomePolling + router doit l'appeler."""

    def test_home_js_defines_stop_home_polling(self) -> None:
        """home.js doit definir stopHomePolling() pour H5."""
        home_js = PROJECT_ROOT / "web" / "views" / "home.js"
        content = home_js.read_text(encoding="utf-8")
        self.assertIn("function stopHomePolling", content)
        # Doit clearTimeout/clearInterval et remettre a null
        self.assertIn("clearTimeout", content)
        self.assertIn("state.polling = null", content)

    def test_home_js_uses_recursive_settimeout(self) -> None:
        """home.js doit utiliser setTimeout recursif (_schedulePoll) pour eviter les chevauchements."""
        home_js = PROJECT_ROOT / "web" / "views" / "home.js"
        content = home_js.read_text(encoding="utf-8")
        self.assertIn("_schedulePoll", content)
        self.assertIn("setTimeout(_schedulePoll", content)

    def test_router_calls_stop_home_polling(self) -> None:
        """router.js navigateTo() doit appeler stopHomePolling pour nettoyer."""
        router_js = PROJECT_ROOT / "web" / "core" / "router.js"
        content = router_js.read_text(encoding="utf-8")
        self.assertIn("stopHomePolling", content)


class RestServerStartupErrorTests(unittest.TestCase):
    """app.py catche RuntimeError du serveur REST (M1)."""

    def test_app_py_catches_rest_runtime_error(self) -> None:
        """app.py doit catcher RuntimeError lors de server.start() pour l'afficher a l'user."""
        app_py = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        # Apres M1, server.start() peut lever RuntimeError si HTTPS config invalide
        # On cherche le pattern try/except RuntimeError autour de server.start()
        self.assertIn("RuntimeError", app_py)
        # Le message doit mentionner que le serveur n'est pas demarre
        self.assertTrue(
            "Serveur REST non demarre" in app_py or "non demarre" in app_py,
            "app.py doit afficher un message clair si HTTPS config invalide",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
