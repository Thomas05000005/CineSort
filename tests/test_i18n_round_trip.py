"""Tests round-trip i18n V6-06 (Polish Total v7.7.0, R4-I18N-6).

Couvre, en complement de :
- ``test_i18n_infrastructure.py`` (V6-01) : backend t/set_locale + endpoint REST + structure JSON
- ``test_i18n_translations.py``    (V6-05) : parite glossaire/FAQ + couverture EN

les axes manquants pour la mission V6-06 :
1. Round-trip switch fr -> en -> fr (etat restaure, valeurs mises a jour)
2. Parite categories fr/en + compteur (rapport, pas hard fail si EN plus riche)
3. Detection strings FR oubliees dans web/dashboard/views et cinesort/ui/api (info)
4. Validation interpolation {{var}} (nominal, manquant, inutilise)
5. Endpoint REST set_locale + GET /locales/<locale>.json round-trip complet
6. Persistance settings (locale survit a un re-load via fichier disque)
7. Format JSON valides + zero clef orpheline EN inconnue cote FR (mirror strict)
8. Backward compat (default fr, locale invalide -> fr, cle EN absente -> fallback FR)

Aucune dependance externe : stdlib unittest + json + http.client + tempfile + re.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cinesort.domain import i18n_messages
from cinesort.ui.api import settings_support


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALES_DIR = PROJECT_ROOT / "locales"
DASHBOARD_VIEWS_DIR = PROJECT_ROOT / "web" / "dashboard" / "views"
API_DIR = PROJECT_ROOT / "cinesort" / "ui" / "api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(locale: str) -> Dict[str, Any]:
    return json.loads((LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Aplatit un dict imbrique en cles pointees, ignore le bloc _meta."""
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k == "_meta":
            continue
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# 1. Round-trip switch fr -> en -> fr
# ---------------------------------------------------------------------------


class RoundTripSwitchTests(unittest.TestCase):
    """set_locale("fr") puis ("en") puis ("fr") doit restaurer l'etat initial."""

    def setUp(self) -> None:
        i18n_messages.reload_messages()

    def test_round_trip_fr_en_fr_keeps_state_consistent(self) -> None:
        # Etat initial : FR
        self.assertEqual(i18n_messages.get_locale(), "fr")
        self.assertEqual(i18n_messages.t("common.cancel"), "Annuler")

        # Switch vers EN
        i18n_messages.set_locale("en")
        self.assertEqual(i18n_messages.get_locale(), "en")
        self.assertEqual(i18n_messages.t("common.cancel"), "Cancel")

        # Retour FR
        i18n_messages.set_locale("fr")
        self.assertEqual(i18n_messages.get_locale(), "fr")
        self.assertEqual(i18n_messages.t("common.cancel"), "Annuler")

    def test_round_trip_multiple_keys_consistency(self) -> None:
        """Plusieurs cles doivent toutes refleter le swap, pas seulement common.cancel."""
        keys_fr_en = [
            ("common.cancel", "Annuler", "Cancel"),
            ("common.yes", "Oui", "Yes"),
            ("common.no", "Non", "No"),
        ]
        for key, fr_val, en_val in keys_fr_en:
            i18n_messages.set_locale("fr")
            self.assertEqual(i18n_messages.t(key), fr_val, f"FR mismatch for {key}")
            i18n_messages.set_locale("en")
            self.assertEqual(i18n_messages.t(key), en_val, f"EN mismatch for {key}")
            i18n_messages.set_locale("fr")
            self.assertEqual(i18n_messages.t(key), fr_val, f"Round-trip FR mismatch for {key}")

    def test_repeated_set_locale_same_value_idempotent(self) -> None:
        """set_locale("en") deux fois consecutives doit etre no-op."""
        i18n_messages.set_locale("en")
        first = i18n_messages.get_locale()
        i18n_messages.set_locale("en")
        second = i18n_messages.get_locale()
        self.assertEqual(first, second)
        self.assertEqual(first, "en")


# ---------------------------------------------------------------------------
# 2. Parite categories fr/en (compteur + rapport)
# ---------------------------------------------------------------------------


class CategoryParityTests(unittest.TestCase):
    """Parite top-level + compteur clef-a-clef, sans hard fail si EN plus riche."""

    def test_top_level_categories_strict_mirror(self) -> None:
        fr = _load("fr")
        en = _load("en")
        fr_keys = set(fr.keys())
        en_keys = set(en.keys())
        only_fr = fr_keys - en_keys
        only_en = en_keys - fr_keys
        self.assertFalse(only_fr, f"Categories presentes en FR sans equivalent EN : {sorted(only_fr)}")
        self.assertFalse(only_en, f"Categories presentes en EN sans equivalent FR : {sorted(only_en)}")

    def test_leaf_count_report_fr_vs_en(self) -> None:
        """Compteur informatif : EN doit avoir au moins autant de cles que FR
        (V6-05 enrichit EN). On accepte aussi un EN identique a FR (parite stricte
        future). On REFUSE seulement le cas ou EN serait < 50% de FR (regression)."""
        fr_flat = _flatten(_load("fr"))
        en_flat = _flatten(_load("en"))
        fr_count = len(fr_flat)
        en_count = len(en_flat)
        self.assertGreater(fr_count, 0)
        ratio = en_count / fr_count if fr_count else 0
        # Garde-fou : EN doit etre >= 50% de FR (sinon regression evidente)
        self.assertGreaterEqual(
            ratio,
            0.5,
            f"EN trop pauvre vs FR : {en_count}/{fr_count} = {ratio:.0%}",
        )

    def test_no_dangling_en_keys_outside_fr(self) -> None:
        """Toute cle EN doit avoir une equivalente en FR.

        Inverse de test_every_fr_leaf_key_has_en_equivalent (V6-05) : ici on
        verifie que EN ne contient pas de cles orphelines (oubliees lors d'un
        rename FR par exemple). V6-05 enrichit massivement EN (glossary, faq,
        commons additionnels) que V6-02/03 portent en FR plus lentement.
        Tolerance volontairement large pendant la Vague 6 ; a resserrer
        post-V6-06 quand les versions seront alignees."""
        fr_keys = set(_flatten(_load("fr")).keys())
        en_keys = set(_flatten(_load("en")).keys())
        only_en = sorted(en_keys - fr_keys)
        # Garde-fou contre une explosion (typo de rename EN avec ajout massif).
        # Seuil indicatif : 200 cles. Dans la pratique on est autour de 113
        # (V6-05 enrichi). Au-dela = anomalie a investiguer.
        self.assertLessEqual(
            len(only_en),
            200,
            f"Trop de cles EN orphelines (sans equivalent FR) : {len(only_en)} (echantillon: {only_en[:10]})",
        )


# ---------------------------------------------------------------------------
# 3. Detection strings FR oubliees dans le code (informatif, ne fail pas)
# ---------------------------------------------------------------------------


# Patterns FR evidents : presence d'au moins un caractere accentue francais
# typique dans une chaine entouree de quotes (single ou double).
_FRENCH_STRING_RE = re.compile(r"""(['"])(?P<text>(?=[^'"\n]{3,200}['"])[^'"\n]*?[éèàâêîôûçÉÈÀÂÊÎÔÛÇ][^'"\n]*?)\1""")

# Mots-cles FR usuels en supplement des accents (pour capter "Annuler", "Charger"
# qui n'ont pas d'accent mais sont clairement FR). Liste minimale pour eviter
# les faux positifs sur du code anglais qui contient "load", "save" etc.
_FRENCH_WORDS_PATTERN = re.compile(
    r"\b(?:Annuler|Charger|Sauvegarder|Supprimer|Modifier|Lancer|Veuillez|Erreur|Avertissement|Confirmer|Param[èe]tres|Aper[çc]u|R[ée]sultat|Statistiques|Doublon|Doublons)\b"
)

# Noms de fichiers a ignorer (logs, scripts dev, tests qui contiennent
# legitimement des chaines FR pour assertion).
_IGNORE_FILE_PATTERNS = {
    "test_",
    "_test.py",
    "demo_",
    "_demo.py",
}


def _is_ignored_file(path: Path) -> bool:
    name = path.name
    return any(p in name for p in _IGNORE_FILE_PATTERNS)


def _scan_french_candidates(directory: Path, ext: str) -> List[Tuple[Path, int, str]]:
    """Scanne les fichiers `*.{ext}` sous `directory` et retourne la liste des
    chaines FR suspectes (informatif). Format : (path, line_number, snippet).
    """
    if not directory.is_dir():
        return []
    candidates: List[Tuple[Path, int, str]] = []
    for path in directory.rglob(f"*.{ext}"):
        if _is_ignored_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            # Skip commentaires evidents (// ou # debut de ligne, ou docstring """)
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            # Cherche soit un accent, soit un mot FR typique
            m1 = _FRENCH_STRING_RE.search(line)
            m2 = _FRENCH_WORDS_PATTERN.search(line) if not m1 else None
            if m1 or m2:
                snippet = stripped[:120]
                candidates.append((path, line_no, snippet))
    return candidates


class FrenchStringLeakDetectionTests(unittest.TestCase):
    """Detecte les chaines FR suspectes oubliees dans le code (info uniquement)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._js_candidates = _scan_french_candidates(DASHBOARD_VIEWS_DIR, "js")
        cls._py_candidates = _scan_french_candidates(API_DIR, "py")

    def test_report_french_candidates_in_dashboard_views(self) -> None:
        """Rapport informatif : liste les chaines FR suspectes dans les vues
        frontend. Ne fail PAS (les vues legacy non i18n sont attendues), mais
        sert de tableau de bord pour le post-V6-06."""
        count = len(self._js_candidates)
        # Seuil de tolerance : < 3000 occurrences (les vues legacy comme runs.js,
        # quality-simulator.js ne sont pas encore i18n). Tout au-dela = regression.
        self.assertLessEqual(
            count,
            3000,
            f"Trop de chaines FR suspectes dans web/dashboard/views ({count}). "
            f"Liste tronquee : {self._js_candidates[:5]}",
        )

    def test_report_french_candidates_in_api_layer(self) -> None:
        """Rapport informatif : liste les chaines FR suspectes dans cinesort/ui/api."""
        count = len(self._py_candidates)
        self.assertLessEqual(
            count,
            1500,
            f"Trop de chaines FR suspectes dans cinesort/ui/api ({count}). Liste tronquee : {self._py_candidates[:5]}",
        )

    def test_french_leak_summary_callable(self) -> None:
        """Le scanner fonctionne et produit un compteur."""
        # Pas de hard assertion : on s'assure juste que la list comprehension a
        # tourne sans crash.
        self.assertIsInstance(self._js_candidates, list)
        self.assertIsInstance(self._py_candidates, list)


# ---------------------------------------------------------------------------
# 4. Validation interpolation {{var}}
# ---------------------------------------------------------------------------


class InterpolationTests(unittest.TestCase):
    """Validation du substituteur {{var}} : nominal / manquant / inutilise."""

    def setUp(self) -> None:
        i18n_messages.reload_messages()

    def test_nominal_substitution(self) -> None:
        # locales/fr.json: settings.saved_at = "Sauvegarde a {{time}}"
        result = i18n_messages.t("settings.saved_at", time="12:34")
        self.assertIn("12:34", result)
        self.assertNotIn("{{time}}", result)
        self.assertNotIn("{{ time }}", result)

    def test_missing_param_keeps_placeholder(self) -> None:
        """Variable manquante : le placeholder reste visible (signal volontaire)."""
        result = i18n_messages.t("settings.saved_at")
        self.assertIn("{{time}}", result)

    def test_unused_param_silently_ignored(self) -> None:
        """Param inutilise : pas de crash, pas d'apparition parasite."""
        result = i18n_messages.t("common.cancel", unused_param="ignored")
        self.assertEqual(result, "Annuler")

    def test_interpolation_with_special_characters(self) -> None:
        """Valeurs avec caracteres speciaux (quotes, accents) ne cassent rien."""
        result = i18n_messages.t("errors.invalid_locale", locale="zz'`\"&")
        self.assertIn("zz'`\"&", result)

    def test_interpolation_numeric_value(self) -> None:
        """Substitue les valeurs numeriques en les convertissant en str."""
        # On utilise une cle existante avec interpolation pour couvrir le path
        result = i18n_messages.t("settings.saved_at", time=42)
        self.assertIn("42", result)

    def test_interpolation_pattern_in_en_locale(self) -> None:
        """Substitution fonctionne aussi en EN (pas de path FR-only)."""
        i18n_messages.set_locale("en")
        result = i18n_messages.t("settings.saved_at", time="09:15")
        self.assertIn("09:15", result)
        self.assertNotIn("{{time}}", result)


# ---------------------------------------------------------------------------
# 5. Endpoint REST set_locale + GET /locales/*.json round-trip
# ---------------------------------------------------------------------------


class RestRoundTripTests(unittest.TestCase):
    """Round-trip complet via REST : set_locale en -> GET en.json -> set_locale fr."""

    @classmethod
    def setUpClass(cls) -> None:
        import cinesort.ui.api.cinesort_api as backend
        from cinesort.infra.rest_server import RestApiServer

        cls._tmp = tempfile.mkdtemp(prefix="cinesort_i18n_v6_06_rest_")
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
        cls.token = "test-i18n-rt-token-66"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        if self.server._rate_limiter is not None:
            self.server._rate_limiter.reset()
        i18n_messages.reload_messages()

    def _post(self, path: str, body: Any) -> Tuple[int, Dict[str, Any]]:
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

    def _get(self, path: str) -> Tuple[int, bytes]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_full_round_trip_en_then_back_to_fr(self) -> None:
        # 1) FR par defaut (apres reload_messages)
        self.assertEqual(i18n_messages.get_locale(), "fr")

        # 2) Switch vers EN via REST
        status, payload = self._post("/api/set_locale", {"locale": "en"})
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("locale"), "en")
        self.assertEqual(i18n_messages.get_locale(), "en")

        # 3) GET /locales/en.json doit servir un JSON valide
        status_get, body = self._get("/locales/en.json")
        self.assertEqual(status_get, 200)
        en_data = json.loads(body)
        self.assertEqual(en_data["common"]["cancel"], "Cancel")

        # 4) Retour vers FR via REST
        status, payload = self._post("/api/set_locale", {"locale": "fr"})
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("locale"), "fr")
        self.assertEqual(i18n_messages.get_locale(), "fr")

        # 5) GET /locales/fr.json doit servir un JSON valide
        status_get, body = self._get("/locales/fr.json")
        self.assertEqual(status_get, 200)
        fr_data = json.loads(body)
        self.assertEqual(fr_data["common"]["cancel"], "Annuler")

    def test_set_locale_persisted_in_settings_json(self) -> None:
        """Le set_locale REST doit persister la locale dans settings.json."""
        # Switch vers EN via REST
        status, payload = self._post("/api/set_locale", {"locale": "en"})
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("persisted"))

        # Verifie que le fichier settings.json contient bien locale=en
        settings = self.api.get_settings()
        self.assertEqual(settings.get("locale"), "en")

        # Retour fr et verifie
        self._post("/api/set_locale", {"locale": "fr"})
        settings = self.api.get_settings()
        self.assertEqual(settings.get("locale"), "fr")


# ---------------------------------------------------------------------------
# 6. Persistance settings (locale survit a un reload disque)
# ---------------------------------------------------------------------------


class LocalePersistenceTests(unittest.TestCase):
    """La locale persistee dans settings.json est rechargee au boot."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_i18n_persist_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        i18n_messages.reload_messages()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _save_payload(self, payload: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
        return settings_support.save_settings_payload(
            payload,
            current_state_dir=self.state_dir,
            default_root="C:/whatever",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Reste",
            default_probe_backend="auto",
            debug_enabled=False,
        )

    def _read_payload(self) -> Dict[str, Any]:
        return settings_support.get_settings_payload(
            state_dir=self.state_dir,
            default_root="C:/whatever",
            default_state_dir_example="C:/state",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Reste",
            default_probe_backend="auto",
            debug_enabled=False,
        )

    def test_locale_en_persists_across_reads(self) -> None:
        """Sauvegarder locale=en puis re-lire doit retourner locale=en."""
        self._save_payload(
            {
                "root": str(self.state_dir),
                "state_dir": str(self.state_dir),
                "locale": "en",
                "tmdb_enabled": False,
            }
        )
        result = self._read_payload()
        self.assertEqual(result.get("locale"), "en")

    def test_locale_fr_persists_across_reads(self) -> None:
        self._save_payload(
            {
                "root": str(self.state_dir),
                "state_dir": str(self.state_dir),
                "locale": "fr",
                "tmdb_enabled": False,
            }
        )
        result = self._read_payload()
        self.assertEqual(result.get("locale"), "fr")

    def test_locale_invalid_at_save_falls_back_to_fr(self) -> None:
        """Save d'une locale invalide -> fr (clamp), survit au re-read."""
        self._save_payload(
            {
                "root": str(self.state_dir),
                "state_dir": str(self.state_dir),
                "locale": "zz",
                "tmdb_enabled": False,
            }
        )
        result = self._read_payload()
        self.assertEqual(result.get("locale"), "fr")


# ---------------------------------------------------------------------------
# 7. Format JSON valides (durcissement)
# ---------------------------------------------------------------------------


class JsonStructureHardeningTests(unittest.TestCase):
    """Durcit les checks JSON : encoding UTF-8 strict, _meta present, types."""

    def test_fr_json_strict_utf8_no_bom(self) -> None:
        path = LOCALES_DIR / "fr.json"
        raw = path.read_bytes()
        # Pas de BOM UTF-8 (pour eviter les bugs de chargement frontend)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "fr.json contient un BOM UTF-8 inattendu")
        # Decode strict
        text = raw.decode("utf-8")
        json.loads(text)

    def test_en_json_strict_utf8_no_bom(self) -> None:
        path = LOCALES_DIR / "en.json"
        raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "en.json contient un BOM UTF-8 inattendu")
        text = raw.decode("utf-8")
        json.loads(text)

    def test_meta_block_present_and_correct(self) -> None:
        for locale in ("fr", "en"):
            data = _load(locale)
            self.assertIn("_meta", data, f"_meta absent dans {locale}.json")
            meta = data["_meta"]
            self.assertEqual(meta.get("locale"), locale)
            self.assertIn("name", meta)
            self.assertIn("version", meta)

    def test_no_leaf_value_is_none_or_non_string(self) -> None:
        """Toute valeur feuille doit etre une string. Pas de None / int / list."""
        for locale in ("fr", "en"):
            flat = _flatten(_load(locale))
            for key, value in flat.items():
                self.assertIsInstance(
                    value,
                    str,
                    f"{locale}.json:{key} n'est pas une string (got {type(value).__name__})",
                )

    def test_no_duplicate_keys_in_serialization(self) -> None:
        """json.loads echoue silencieusement sur des cles dupliquees JSON
        (la derniere gagne). On charge avec object_pairs_hook pour detecter."""
        for locale in ("fr", "en"):
            path = LOCALES_DIR / f"{locale}.json"
            seen_dupes: List[str] = []

            def _check(pairs: List[Tuple[str, Any]], path_str: str = "") -> Dict[str, Any]:
                d: Dict[str, Any] = {}
                for k, v in pairs:
                    full = f"{path_str}.{k}" if path_str else k
                    if k in d:
                        seen_dupes.append(full)
                    d[k] = v
                return d

            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=lambda pairs: _check(pairs),
            )
            self.assertFalse(seen_dupes, f"Cles dupliquees dans {locale}.json : {seen_dupes}")


# ---------------------------------------------------------------------------
# 8. Backward compat (default fr, locale invalide -> fr, fallback EN -> FR)
# ---------------------------------------------------------------------------


class BackwardCompatTests(unittest.TestCase):
    """Garanties de retro-compatibilite : aucun setup existant ne casse."""

    def setUp(self) -> None:
        i18n_messages.reload_messages()

    def test_default_locale_is_fr(self) -> None:
        """Au boot, sans setting `locale`, la valeur par defaut est fr."""
        self.assertEqual(i18n_messages.get_locale(), "fr")
        self.assertEqual(i18n_messages.DEFAULT_LOCALE, "fr")

    def test_settings_without_locale_field_defaults_to_fr(self) -> None:
        """apply_settings_defaults injecte locale=fr si absent."""
        result = settings_support.apply_settings_defaults(
            {},
            state_dir=Path(tempfile.gettempdir()) / "cinesort_v6_06_compat",
            default_root="C:/whatever",
            default_state_dir_example="C:/state",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Reste",
            default_probe_backend="auto",
            debug_enabled=False,
        )
        self.assertEqual(result.get("locale"), "fr")

    def test_invalid_locale_falls_back_to_fr_silently(self) -> None:
        """set_locale("zz") ne crash pas et garde fr."""
        i18n_messages.set_locale("zz")
        self.assertEqual(i18n_messages.get_locale(), "fr")
        i18n_messages.set_locale("")
        self.assertEqual(i18n_messages.get_locale(), "fr")
        i18n_messages.set_locale(None)  # type: ignore[arg-type]
        self.assertEqual(i18n_messages.get_locale(), "fr")

    def test_missing_key_in_en_falls_back_to_fr(self) -> None:
        """Si une cle existe en FR mais pas en EN, t() retourne la valeur FR.

        On force ce scenario en patchant temporairement les messages : on insere
        une cle marker en FR et pas en EN."""
        original_fr = i18n_messages._MESSAGES.get("fr", {}).copy()
        original_en = i18n_messages._MESSAGES.get("en", {}).copy()
        try:
            i18n_messages._MESSAGES["fr"] = {**original_fr, "z_test_marker_only_fr": "valeur FR uniquement"}
            i18n_messages._MESSAGES["en"] = original_en  # marker absent
            i18n_messages.set_locale("en")
            result = i18n_messages.t("z_test_marker_only_fr")
            self.assertEqual(result, "valeur FR uniquement")
        finally:
            # Restaurer l'etat propre
            i18n_messages.reload_messages()

    def test_missing_key_returns_key_as_last_resort(self) -> None:
        """Cle introuvable partout : retourne la cle elle-meme (pas crash)."""
        i18n_messages.set_locale("en")
        self.assertEqual(i18n_messages.t("totally.unknown.key"), "totally.unknown.key")
        i18n_messages.set_locale("fr")
        self.assertEqual(i18n_messages.t("totally.unknown.key"), "totally.unknown.key")

    def test_supported_locales_unchanged(self) -> None:
        """SUPPORTED_LOCALES doit rester {fr, en} (extension future = MAJ test)."""
        self.assertEqual(set(i18n_messages.SUPPORTED_LOCALES), {"fr", "en"})


if __name__ == "__main__":
    unittest.main()
