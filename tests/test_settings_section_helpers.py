"""V2-01 — Tests isoles pour les helpers _save_section_* extraits de save_settings_payload.

Audit ID-CODE-001 : save_settings_payload est passe de F=74 a B=6 grace au decoupage
en 15 helpers de section + 5 helpers de finalisation. Ces tests figent le comportement
de chaque helper, isolement, pour detecter toute regression silencieuse.

Couvre 16 helpers :
- _save_section_tmdb / cleanup / probe / scan_flags / jellyfin / plex / radarr
- _save_section_notifications / rest_api / watch / plugins / email / subtitles
- _save_section_perceptual / appearance
- _normalize_enum, _coerce_appearance_int, _normalize_scopes,
  _apply_tmdb_key_persistence, _apply_jellyfin_key_persistence, _build_save_result
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.ui.api.settings_support import (
    SECRET_PROTECTION_NONE,
    _apply_jellyfin_key_persistence,
    _apply_tmdb_key_persistence,
    _build_save_result,
    _coerce_appearance_int,
    _normalize_enum,
    _normalize_scopes,
    _save_section_appearance,
    _save_section_cleanup,
    _save_section_email,
    _save_section_jellyfin,
    _save_section_notifications,
    _save_section_perceptual,
    _save_section_plex,
    _save_section_plugins,
    _save_section_probe,
    _save_section_radarr,
    _save_section_rest_api,
    _save_section_scan_flags,
    _save_section_subtitles,
    _save_section_tmdb,
    _save_section_watch,
)


class NormalizeEnumTests(unittest.TestCase):
    def test_returns_value_when_in_allowed(self) -> None:
        self.assertEqual(_normalize_enum("luxe", ("cinema", "luxe", "neon"), "cinema"), "luxe")

    def test_returns_default_when_not_in_allowed(self) -> None:
        self.assertEqual(_normalize_enum("invalid", ("a", "b"), "a"), "a")

    def test_strips_and_lowers(self) -> None:
        self.assertEqual(_normalize_enum("  LUXE  ", ("luxe",), "default"), "luxe")

    def test_returns_default_for_none(self) -> None:
        self.assertEqual(_normalize_enum(None, ("a", "b"), "a"), "a")

    def test_returns_default_for_empty_string(self) -> None:
        self.assertEqual(_normalize_enum("", ("a", "b"), "a"), "a")


class CoerceAppearanceIntTests(unittest.TestCase):
    def test_returns_value_when_present_and_not_none(self) -> None:
        self.assertEqual(_coerce_appearance_int({"effect_speed": 75}, "effect_speed", 50), 75)

    def test_returns_default_when_key_missing(self) -> None:
        self.assertEqual(_coerce_appearance_int({}, "effect_speed", 50), 50)

    def test_returns_default_when_value_is_none(self) -> None:
        self.assertEqual(_coerce_appearance_int({"effect_speed": None}, "effect_speed", 50), 50)

    def test_zero_is_kept(self) -> None:
        # Audit important : 0 est valide pour glow_intensity/light_intensity
        self.assertEqual(_coerce_appearance_int({"glow_intensity": 0}, "glow_intensity", 30), 0)


class SaveSectionTmdbTests(unittest.TestCase):
    def test_defaults_when_empty_payload(self) -> None:
        result = _save_section_tmdb({})
        # V5-03 polish v7.7.0 : ajout tmdb_cache_ttl_days (defaut 30, clamp [1, 365]).
        self.assertEqual(
            result,
            {"tmdb_enabled": True, "tmdb_timeout_s": 10.0, "tmdb_cache_ttl_days": 30},
        )

    def test_explicit_disabled(self) -> None:
        result = _save_section_tmdb({"tmdb_enabled": False, "tmdb_timeout_s": 30})
        self.assertEqual(result["tmdb_enabled"], False)
        self.assertEqual(result["tmdb_timeout_s"], 30.0)

    def test_tmdb_cache_ttl_days_clamps_lower(self) -> None:
        result = _save_section_tmdb({"tmdb_cache_ttl_days": 0})
        self.assertEqual(result["tmdb_cache_ttl_days"], 1)

    def test_tmdb_cache_ttl_days_clamps_upper(self) -> None:
        result = _save_section_tmdb({"tmdb_cache_ttl_days": 9999})
        self.assertEqual(result["tmdb_cache_ttl_days"], 365)

    def test_tmdb_cache_ttl_days_explicit_value(self) -> None:
        result = _save_section_tmdb({"tmdb_cache_ttl_days": 60})
        self.assertEqual(result["tmdb_cache_ttl_days"], 60)


class SaveSectionCleanupTests(unittest.TestCase):
    DEFAULTS = {
        "default_collection_folder_name": "Saga",
        "default_empty_folders_folder_name": "EmptyDeleted",
        "default_residual_cleanup_folder_name": "Residus",
    }

    def test_defaults_applied(self) -> None:
        result = _save_section_cleanup({}, **self.DEFAULTS)
        self.assertEqual(result["collection_folder_enabled"], True)
        self.assertEqual(result["collection_folder_name"], "Saga")
        self.assertEqual(result["empty_folders_folder_name"], "EmptyDeleted")
        self.assertEqual(result["empty_folders_scope"], "root_all")
        self.assertEqual(result["cleanup_residual_folders_scope"], "touched_only")
        for key in (
            "cleanup_residual_include_nfo",
            "cleanup_residual_include_images",
            "cleanup_residual_include_subtitles",
            "cleanup_residual_include_texts",
        ):
            self.assertEqual(result[key], True)

    def test_empty_string_falls_back_to_default(self) -> None:
        # Le `or default` + `.strip() or default` doit renvoyer default si saisie vide
        result = _save_section_cleanup({"collection_folder_name": "   "}, **self.DEFAULTS)
        self.assertEqual(result["collection_folder_name"], "Saga")

    def test_custom_folder_name_kept(self) -> None:
        result = _save_section_cleanup({"collection_folder_name": "MaSaga"}, **self.DEFAULTS)
        self.assertEqual(result["collection_folder_name"], "MaSaga")


class SaveSectionProbeTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_probe({}, default_probe_backend="ffprobe")
        self.assertEqual(result["mediainfo_path"], "")
        self.assertEqual(result["ffprobe_path"], "")
        self.assertEqual(result["probe_timeout_s"], 30.0)

    def test_probe_timeout_clamped_low(self) -> None:
        result = _save_section_probe({"probe_timeout_s": 1.0}, default_probe_backend="ffprobe")
        self.assertEqual(result["probe_timeout_s"], 5.0)

    def test_probe_timeout_clamped_high(self) -> None:
        result = _save_section_probe({"probe_timeout_s": 9999}, default_probe_backend="ffprobe")
        self.assertEqual(result["probe_timeout_s"], 300.0)


class SaveSectionScanFlagsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_scan_flags({})
        self.assertEqual(result["incremental_scan_enabled"], False)
        self.assertEqual(result["dry_run_apply"], True)
        self.assertEqual(result["auto_approve_enabled"], False)
        self.assertEqual(result["auto_approve_threshold"], 85)
        self.assertEqual(result["enable_tv_detection"], False)

    def test_auto_approve_threshold_clamped(self) -> None:
        # min 70, max 100
        self.assertEqual(_save_section_scan_flags({"auto_approve_threshold": 50})["auto_approve_threshold"], 70)
        self.assertEqual(_save_section_scan_flags({"auto_approve_threshold": 150})["auto_approve_threshold"], 100)


class SaveSectionJellyfinTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_jellyfin({})
        self.assertEqual(result["jellyfin_enabled"], False)
        self.assertEqual(result["jellyfin_url"], "")
        self.assertEqual(result["jellyfin_timeout_s"], 10.0)

    def test_timeout_clamped(self) -> None:
        self.assertEqual(_save_section_jellyfin({"jellyfin_timeout_s": 0.1})["jellyfin_timeout_s"], 1.0)
        self.assertEqual(_save_section_jellyfin({"jellyfin_timeout_s": 999})["jellyfin_timeout_s"], 60.0)


class SaveSectionPlexTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_plex({})
        self.assertEqual(result["plex_enabled"], False)
        self.assertEqual(result["plex_url"], "")
        self.assertEqual(result["plex_token"], "")

    def test_url_trailing_slash_stripped(self) -> None:
        self.assertEqual(
            _save_section_plex({"plex_url": "http://localhost:32400/"})["plex_url"], "http://localhost:32400"
        )


class SaveSectionRadarrTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_radarr({})
        self.assertEqual(result["radarr_enabled"], False)
        self.assertEqual(result["radarr_url"], "")
        self.assertEqual(result["radarr_api_key"], "")

    def test_url_trailing_slash_stripped(self) -> None:
        self.assertEqual(_save_section_radarr({"radarr_url": "http://radarr/"})["radarr_url"], "http://radarr")


class SaveSectionNotificationsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_notifications({})
        # enabled defaults to False, individuels a True
        self.assertEqual(result["notifications_enabled"], False)
        self.assertEqual(result["notifications_scan_done"], True)
        self.assertEqual(result["notifications_apply_done"], True)
        self.assertEqual(result["notifications_undo_done"], True)
        self.assertEqual(result["notifications_errors"], True)


class SaveSectionRestApiTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_rest_api({})
        self.assertEqual(result["rest_api_enabled"], False)
        self.assertEqual(result["rest_api_port"], 8642)
        self.assertEqual(result["rest_api_https_enabled"], False)

    def test_port_clamped(self) -> None:
        self.assertEqual(_save_section_rest_api({"rest_api_port": 80})["rest_api_port"], 1024)
        self.assertEqual(_save_section_rest_api({"rest_api_port": 99999})["rest_api_port"], 65535)


class SaveSectionWatchTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(_save_section_watch({}), {"watch_enabled": False, "watch_interval_minutes": 5})

    def test_interval_clamped(self) -> None:
        # 0 declenche le `or 5` → fallback 5, pas le clamp min(1)
        self.assertEqual(_save_section_watch({"watch_interval_minutes": 0})["watch_interval_minutes"], 5)
        self.assertEqual(_save_section_watch({"watch_interval_minutes": 999})["watch_interval_minutes"], 60)


class SaveSectionPluginsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(_save_section_plugins({}), {"plugins_enabled": False, "plugins_timeout_s": 30})

    def test_timeout_clamped(self) -> None:
        self.assertEqual(_save_section_plugins({"plugins_timeout_s": 1})["plugins_timeout_s"], 5)
        self.assertEqual(_save_section_plugins({"plugins_timeout_s": 999})["plugins_timeout_s"], 120)


class SaveSectionEmailTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_email({})
        self.assertEqual(result["email_enabled"], False)
        self.assertEqual(result["email_smtp_port"], 587)
        self.assertEqual(result["email_smtp_tls"], True)
        self.assertEqual(result["email_smtp_password"], "")

    def test_password_not_stripped(self) -> None:
        # On garde le password exact (espaces compris) car SMTP peut accepter des passwords avec espaces
        result = _save_section_email({"email_smtp_password": "  pa ss  "})
        self.assertEqual(result["email_smtp_password"], "  pa ss  ")


class SaveSectionSubtitlesTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_subtitles({})
        self.assertEqual(result["subtitle_detection_enabled"], True)
        # _normalize_lang_list({}) renvoie une liste (peut-etre vide ou avec defaults)
        self.assertIsInstance(result["subtitle_expected_languages"], list)


class SaveSectionPerceptualTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_perceptual({})
        self.assertEqual(result["perceptual_enabled"], False)
        self.assertEqual(result["perceptual_auto_on_quality"], True)
        self.assertEqual(result["perceptual_timeout_per_film_s"], 120)
        self.assertEqual(result["perceptual_frames_count"], 10)
        self.assertEqual(result["perceptual_dark_weight"], 1.5)
        self.assertEqual(result["perceptual_parallelism_mode"], "auto")

    def test_parallelism_mode_normalized(self) -> None:
        for mode in ("auto", "max", "safe", "serial"):
            self.assertEqual(
                _save_section_perceptual({"perceptual_parallelism_mode": mode})["perceptual_parallelism_mode"],
                mode,
            )

    def test_parallelism_mode_invalid_falls_back_to_auto(self) -> None:
        self.assertEqual(
            _save_section_perceptual({"perceptual_parallelism_mode": "invalid"})["perceptual_parallelism_mode"],
            "auto",
        )

    def test_dark_weight_clamped(self) -> None:
        self.assertEqual(_save_section_perceptual({"perceptual_dark_weight": 0.5})["perceptual_dark_weight"], 1.0)
        self.assertEqual(_save_section_perceptual({"perceptual_dark_weight": 5.0})["perceptual_dark_weight"], 3.0)


class SaveSectionAppearanceTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = _save_section_appearance({}, debug_enabled=False)
        self.assertEqual(result["theme"], "luxe")
        self.assertEqual(result["animation_level"], "moderate")
        self.assertEqual(result["effect_speed"], 50)
        self.assertEqual(result["glow_intensity"], 30)
        self.assertEqual(result["light_intensity"], 20)
        self.assertEqual(result["effects_mode"], "restraint")
        self.assertEqual(result["debug_enabled"], False)

    def test_debug_enabled_uses_default_when_absent(self) -> None:
        # Cle absente du payload → valeur de l'argument debug_enabled
        self.assertEqual(_save_section_appearance({}, debug_enabled=True)["debug_enabled"], True)

    def test_invalid_theme_falls_back_to_luxe(self) -> None:
        self.assertEqual(_save_section_appearance({"theme": "invalid"}, debug_enabled=False)["theme"], "luxe")

    def test_valid_themes(self) -> None:
        for theme in ("cinema", "studio", "luxe", "neon"):
            self.assertEqual(_save_section_appearance({"theme": theme}, debug_enabled=False)["theme"], theme)

    def test_sliders_clamped(self) -> None:
        # effect_speed: 1-100
        self.assertEqual(_save_section_appearance({"effect_speed": 0}, debug_enabled=False)["effect_speed"], 1)
        self.assertEqual(_save_section_appearance({"effect_speed": 200}, debug_enabled=False)["effect_speed"], 100)
        # glow_intensity: 0-100 (peut etre 0)
        self.assertEqual(_save_section_appearance({"glow_intensity": 0}, debug_enabled=False)["glow_intensity"], 0)
        self.assertEqual(_save_section_appearance({"glow_intensity": -5}, debug_enabled=False)["glow_intensity"], 0)

    def test_slider_none_uses_default(self) -> None:
        # Audit : payload[k] = None doit utiliser default, pas crasher avec int(None)
        result = _save_section_appearance({"effect_speed": None}, debug_enabled=False)
        self.assertEqual(result["effect_speed"], 50)


class NormalizeScopesTests(unittest.TestCase):
    def test_invalid_empty_folders_scope_falls_back(self) -> None:
        d = {"empty_folders_scope": "invalid", "cleanup_residual_folders_scope": "touched_only"}
        _normalize_scopes(d)
        self.assertEqual(d["empty_folders_scope"], "root_all")

    def test_invalid_residual_scope_falls_back(self) -> None:
        d = {"empty_folders_scope": "root_all", "cleanup_residual_folders_scope": "garbage"}
        _normalize_scopes(d)
        self.assertEqual(d["cleanup_residual_folders_scope"], "touched_only")

    def test_valid_scopes_preserved(self) -> None:
        d = {"empty_folders_scope": "touched_only", "cleanup_residual_folders_scope": "root_all"}
        _normalize_scopes(d)
        self.assertEqual(d["empty_folders_scope"], "touched_only")
        self.assertEqual(d["cleanup_residual_folders_scope"], "root_all")


class ApplyTmdbKeyPersistenceTests(unittest.TestCase):
    def test_remember_off_clears_key(self) -> None:
        to_save: dict = {}
        _apply_tmdb_key_persistence(to_save, {"remember_key": False, "tmdb_api_key": "abc"}, {"tmdb_api_key": "old"})
        self.assertEqual(to_save["remember_key"], False)
        self.assertEqual(to_save["tmdb_api_key"], "")

    def test_remember_on_with_new_key(self) -> None:
        to_save: dict = {}
        _apply_tmdb_key_persistence(to_save, {"remember_key": True, "tmdb_api_key": "newkey"}, {})
        self.assertEqual(to_save["remember_key"], True)
        self.assertEqual(to_save["tmdb_api_key"], "newkey")

    def test_remember_on_no_key_keeps_existing(self) -> None:
        to_save: dict = {}
        _apply_tmdb_key_persistence(to_save, {"remember_key": True}, {"tmdb_api_key": "old"})
        self.assertEqual(to_save["tmdb_api_key"], "old")

    def test_remember_default_inferred_from_existing(self) -> None:
        # Si remember_key absent du payload : True ssi une cle existait deja
        to_save: dict = {}
        _apply_tmdb_key_persistence(to_save, {}, {"tmdb_api_key": "existing"})
        self.assertEqual(to_save["remember_key"], True)
        self.assertEqual(to_save["tmdb_api_key"], "existing")


class ApplyJellyfinKeyPersistenceTests(unittest.TestCase):
    def test_payload_overrides_existing(self) -> None:
        to_save: dict = {}
        _apply_jellyfin_key_persistence(to_save, {"jellyfin_api_key": "new"}, {"jellyfin_api_key": "old"})
        self.assertEqual(to_save["jellyfin_api_key"], "new")

    def test_missing_payload_keeps_existing(self) -> None:
        to_save: dict = {}
        _apply_jellyfin_key_persistence(to_save, {}, {"jellyfin_api_key": "old"})
        self.assertEqual(to_save["jellyfin_api_key"], "old")

    def test_explicit_empty_overrides(self) -> None:
        # Si l'utilisateur efface la cle (envoie ""), on respecte
        to_save: dict = {}
        _apply_jellyfin_key_persistence(to_save, {"jellyfin_api_key": ""}, {"jellyfin_api_key": "old"})
        self.assertEqual(to_save["jellyfin_api_key"], "")


class BuildSaveResultTests(unittest.TestCase):
    def test_minimal_meta(self) -> None:
        result = _build_save_result(Path("/tmp/state"), {})
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["state_dir"], str(Path("/tmp/state")))
        self.assertEqual(result["tmdb_key_persisted"], False)
        self.assertEqual(result["tmdb_key_protection"], SECRET_PROTECTION_NONE)
        self.assertEqual(result["jellyfin_key_persisted"], False)
        self.assertNotIn("tmdb_key_warning", result)
        self.assertNotIn("jellyfin_key_warning", result)

    def test_warnings_propagated(self) -> None:
        meta = {
            "tmdb_key_persisted": True,
            "tmdb_key_protection": "dpapi",
            "jellyfin_key_persisted": True,
            "tmdb_key_warning": "DPAPI fallback",
            "jellyfin_key_warning": "no DPAPI",
        }
        result = _build_save_result(Path("/tmp/state"), meta)
        self.assertEqual(result["tmdb_key_persisted"], True)
        self.assertEqual(result["tmdb_key_protection"], "dpapi")
        self.assertEqual(result["tmdb_key_warning"], "DPAPI fallback")
        self.assertEqual(result["jellyfin_key_warning"], "no DPAPI")


if __name__ == "__main__":
    unittest.main()
