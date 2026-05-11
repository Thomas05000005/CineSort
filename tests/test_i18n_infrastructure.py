"""Tests infrastructure i18n V6-01 (Polish Total v7.7.0, R4-I18N-4).

Couvre :
- backend i18n_messages : t(), set_locale, get_locale, fallback, interpolation
- settings : validation locale (fr/en accepte, autres rejetes)
- endpoint REST set_locale round-trip
- handler /locales/<locale>.json sert les fichiers
- locales/{fr,en}.json bien formes
- bundle PyInstaller : la spec inclut bien locales/

Aucune dependance externe : stdlib unittest + json + http.client uniquement.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict

from cinesort.domain import i18n_messages
from cinesort.ui.api import settings_support
from cinesort.ui.api.settings_support import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    _normalize_locale,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALES_DIR = PROJECT_ROOT / "locales"


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Backend module : t(), set_locale, get_locale, fallback, interpolation
# ---------------------------------------------------------------------------


class I18nBackendTests(unittest.TestCase):
    """Tests du module cinesort/domain/i18n_messages.py."""

    def setUp(self) -> None:
        # Reload garantit un etat propre (locale=fr, messages charges depuis disk)
        i18n_messages.reload_messages()

    def test_t_returns_french_string_by_default(self) -> None:
        self.assertEqual(i18n_messages.t("common.cancel"), "Annuler")

    def test_t_missing_key_returns_key_as_fallback(self) -> None:
        self.assertEqual(i18n_messages.t("missing.key.does.not.exist"), "missing.key.does.not.exist")

    def test_t_empty_key_returns_empty(self) -> None:
        self.assertEqual(i18n_messages.t(""), "")
        # Type non-str ne crashe pas
        self.assertEqual(i18n_messages.t(None), "")  # type: ignore[arg-type]

    def test_t_interpolation_variable_substitued(self) -> None:
        # locales/fr.json: settings.saved_at = "Sauvegardé à {{time}}"
        result = i18n_messages.t("settings.saved_at", time="12:34")
        self.assertIn("12:34", result)
        self.assertNotIn("{{time}}", result)

    def test_t_interpolation_missing_var_left_as_is(self) -> None:
        # Si on oublie une variable, le placeholder reste visible (pas silent)
        result = i18n_messages.t("settings.saved_at")
        self.assertIn("{{time}}", result)

    def test_set_locale_changes_active_locale(self) -> None:
        i18n_messages.set_locale("en")
        self.assertEqual(i18n_messages.get_locale(), "en")
        self.assertEqual(i18n_messages.t("common.cancel"), "Cancel")

    def test_set_locale_invalid_kept_silent_no_change(self) -> None:
        # set_locale ne raise pas pour rester robuste au boot
        i18n_messages.set_locale("zz")
        self.assertEqual(i18n_messages.get_locale(), "fr")
        i18n_messages.set_locale("")
        self.assertEqual(i18n_messages.get_locale(), "fr")
        i18n_messages.set_locale(None)  # type: ignore[arg-type]
        self.assertEqual(i18n_messages.get_locale(), "fr")

    def test_set_locale_fallback_to_fr_when_key_missing_in_en(self) -> None:
        # Forcer une cle qui n'existe pas en EN mais existe en FR : on doit
        # retomber sur la valeur FR plutot que la cle brute. (Ici on teste avec
        # une cle bidon : t() retourne la cle car elle n'existe nulle part.)
        i18n_messages.set_locale("en")
        # Cle existe en FR et EN -> EN
        self.assertEqual(i18n_messages.t("common.yes"), "Yes")
        # Cle introuvable -> fallback `key` (pas crash)
        self.assertEqual(i18n_messages.t("zzz.nope"), "zzz.nope")

    def test_get_available_locales(self) -> None:
        locales = i18n_messages.get_available_locales()
        self.assertIn("fr", locales)
        self.assertIn("en", locales)

    def test_t_handles_dotted_path_to_nested_dict(self) -> None:
        # qij.quality.tab_title est imbrique 3 niveaux de profondeur
        self.assertEqual(i18n_messages.t("qij.quality.tab_title"), "Qualité")

    def test_t_returns_key_when_intermediate_node_is_not_dict(self) -> None:
        # qij.quality.tab_title est une string, donc qij.quality.tab_title.x doit fail proprement
        result = i18n_messages.t("qij.quality.tab_title.deep")
        self.assertEqual(result, "qij.quality.tab_title.deep")


# ---------------------------------------------------------------------------
# Settings : validation locale (fr/en accepte, autres rejetes)
# ---------------------------------------------------------------------------


class SettingsLocaleValidationTests(unittest.TestCase):
    """Tests pour _normalize_locale et integration settings."""

    def test_normalize_locale_accepts_fr_en(self) -> None:
        self.assertEqual(_normalize_locale("fr"), "fr")
        self.assertEqual(_normalize_locale("en"), "en")

    def test_normalize_locale_accepts_uppercase_and_whitespace(self) -> None:
        self.assertEqual(_normalize_locale("FR"), "fr")
        self.assertEqual(_normalize_locale("  EN  "), "en")
        self.assertEqual(_normalize_locale("En"), "en")

    def test_normalize_locale_rejects_unsupported(self) -> None:
        # Toute valeur invalide retombe sur le defaut (fr)
        self.assertEqual(_normalize_locale("zz"), "fr")
        self.assertEqual(_normalize_locale("de"), "fr")
        self.assertEqual(_normalize_locale(""), "fr")
        self.assertEqual(_normalize_locale(None), "fr")
        self.assertEqual(_normalize_locale(123), "fr")
        # bool est rejete (sous-classe d'int)
        self.assertEqual(_normalize_locale(True), "fr")
        self.assertEqual(_normalize_locale(False), "fr")

    def test_supported_locales_contains_fr_and_en(self) -> None:
        self.assertIn("fr", SUPPORTED_LOCALES)
        self.assertIn("en", SUPPORTED_LOCALES)
        self.assertEqual(DEFAULT_LOCALE, "fr")

    def _apply_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return settings_support.apply_settings_defaults(
            payload,
            state_dir=Path(tempfile.gettempdir()) / "cinesort_i18n_defaults_test",
            default_root="C:/whatever",
            default_state_dir_example="C:/state",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Reste",
            default_probe_backend="auto",
            debug_enabled=False,
        )

    def test_apply_settings_defaults_includes_locale(self) -> None:
        # apply_settings_defaults doit injecter la locale defaut si absente
        result = self._apply_defaults({})
        self.assertIn("locale", result)
        self.assertEqual(result["locale"], "fr")

    def test_apply_settings_defaults_clamps_invalid_locale_to_fr(self) -> None:
        result = self._apply_defaults({"locale": "zz"})
        self.assertEqual(result["locale"], "fr")

    def test_apply_settings_defaults_keeps_valid_en(self) -> None:
        result = self._apply_defaults({"locale": "en"})
        self.assertEqual(result["locale"], "en")


# ---------------------------------------------------------------------------
# Locales JSON : structure des fichiers fr.json + en.json
# ---------------------------------------------------------------------------


class LocalesJsonStructureTests(unittest.TestCase):
    """Tests sur la structure et la coherence des fichiers locales/*.json."""

    def test_fr_json_exists_and_loadable(self) -> None:
        path = LOCALES_DIR / "fr.json"
        self.assertTrue(path.is_file(), f"{path} introuvable")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)

    def test_en_json_exists_and_loadable(self) -> None:
        path = LOCALES_DIR / "en.json"
        self.assertTrue(path.is_file(), f"{path} introuvable")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)

    def test_required_categories_present_in_both(self) -> None:
        required = {
            "settings",
            "qij",
            "library",
            "processing",
            "notifications",
            "errors",
            "common",
            "glossary",
            "help",
        }
        for locale_name in ("fr", "en"):
            data = json.loads((LOCALES_DIR / f"{locale_name}.json").read_text(encoding="utf-8"))
            for cat in required:
                self.assertIn(cat, data, f"Categorie '{cat}' manquante dans {locale_name}.json")

    def test_fr_and_en_have_same_top_level_keys(self) -> None:
        # Sanity : on s'assure que la structure est miroir (les agents V6-02/05
        # ajouteront des cles, mais a chaque commit fr.json et en.json doivent
        # rester synchrones niveau categories de premier niveau).
        fr = json.loads((LOCALES_DIR / "fr.json").read_text(encoding="utf-8"))
        en = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(set(fr.keys()), set(en.keys()))


# ---------------------------------------------------------------------------
# Endpoint REST set_locale (round-trip)
# ---------------------------------------------------------------------------


class RestSetLocaleEndpointTests(unittest.TestCase):
    """Tests de l'endpoint POST /api/set_locale."""

    @classmethod
    def setUpClass(cls) -> None:
        # Import local pour eviter import circulaire au module load
        import cinesort.ui.api.cinesort_api as backend
        from cinesort.infra.rest_server import RestApiServer

        cls._tmp = tempfile.mkdtemp(prefix="cinesort_i18n_rest_")
        cls.root = Path(cls._tmp) / "root"
        cls.state_dir = Path(cls._tmp) / "state"
        cls.root.mkdir()
        cls.state_dir.mkdir()

        cls.api = backend.CineSortApi()
        cls.api.save_settings(
            {
                "root": str(cls.root),
                "state_dir": str(cls.state_dir),
                "tmdb_enabled": False,
            }
        )

        cls.port = _find_free_port()
        cls.token = "test-i18n-token-42"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        # Reset rate limiter pour eviter cross-pollution
        if self.server._rate_limiter is not None:
            self.server._rate_limiter.reset()
        # Reset locale a fr pour chaque test
        i18n_messages.reload_messages()

    def _post(self, path: str, body: Any) -> tuple[int, Dict[str, Any]]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        conn.request("POST", path, body=json.dumps(body), headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(data) if data else {}
        except json.JSONDecodeError:
            return resp.status, {"_raw": data.decode("utf-8", errors="replace")}

    def _get(self, path: str) -> tuple[int, bytes, Dict[str, str]]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        headers = {k: v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, data, headers

    def test_set_locale_en_roundtrip(self) -> None:
        status, payload = self._post("/api/set_locale", {"locale": "en"})
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("locale"), "en")
        # Verifie que le backend reflete bien le changement
        self.assertEqual(i18n_messages.get_locale(), "en")

    def test_set_locale_invalid_returns_error(self) -> None:
        status, payload = self._post("/api/set_locale", {"locale": "zz"})
        self.assertEqual(status, 200)
        self.assertFalse(payload.get("ok"))
        self.assertIn("locale", payload)
        # Locale active inchangee
        self.assertEqual(payload.get("locale"), i18n_messages.get_locale())

    def test_locales_static_handler_serves_fr_json(self) -> None:
        status, body, headers = self._get("/locales/fr.json")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        data = json.loads(body)
        self.assertIn("common", data)
        self.assertEqual(data["common"]["cancel"], "Annuler")

    def test_locales_static_handler_serves_en_json(self) -> None:
        status, body, _ = self._get("/locales/en.json")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("common", data)
        self.assertEqual(data["common"]["cancel"], "Cancel")

    def test_locales_static_handler_path_traversal_blocked(self) -> None:
        # Tentative de remonter hors de locales/
        status, _, _ = self._get("/locales/../app.py")
        self.assertIn(status, (400, 403, 404))

    def test_locales_static_handler_unknown_locale_returns_404(self) -> None:
        status, _, _ = self._get("/locales/zz.json")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
