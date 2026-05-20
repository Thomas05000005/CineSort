"""Tests Phase 4 backend-parametres-endpoints (spec 11 §2.9 + §5).

Couvre les 5 endpoints :
- settings/get_profiles
- settings/save_profile
- settings/set_active_profile
- settings/reset_settings(scope)
- settings/reset_database
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, ".")

from cinesort.domain import default_quality_profile
from cinesort.ui.api import profiles_support, reset_support


class _FakeSettingsFacade:
    """Stub minimal qui imite la facade `api.settings` pour les tests."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._payload: Dict[str, Any] = {}

    def get_settings(self) -> Dict[str, Any]:
        return copy.deepcopy(self._payload)

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        self._payload = copy.deepcopy(settings)
        return {"ok": True}


class _FakeApi:
    """Stub d'API qui imite CineSortApi pour les helpers profiles_support /
    reset_support sans demarrer pywebview ni la DB SQLite reelle."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self.settings = _FakeSettingsFacade(state_dir)
        self._db_active_profile: Dict[str, Any] = default_quality_profile()
        # Pour reset_database : flag indiquant qu'un infra a ete ferme
        self._close_infra_called = False

    def _get_state_dir(self) -> str:
        return str(self._state_dir)

    def _active_quality_profile_payload(self) -> Dict[str, Any]:
        return {
            "active_row": self._db_active_profile,
            "profile_json": self._db_active_profile,
            "profile_id": str(self._db_active_profile.get("id") or "CinemaLux_v1"),
            "profile_version": int(self._db_active_profile.get("version") or 1),
            "is_active": True,
        }

    def _save_active_quality_profile(self, profile_json: Dict[str, Any]) -> Dict[str, Any]:
        self._db_active_profile = copy.deepcopy(profile_json)
        return {
            "profile_id": str(profile_json["id"]),
            "profile_version": int(profile_json["version"]),
            "profile_json": copy.deepcopy(profile_json),
        }

    def _close_infra(self) -> None:
        self._close_infra_called = True


# ---------------------------------------------------------------------------
# 1) get_profiles
# ---------------------------------------------------------------------------


class GetProfilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.api = _FakeApi(self.state_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_returns_ok(self) -> None:
        out = profiles_support.get_profiles(self.api)
        self.assertTrue(out["ok"], out)
        self.assertIn("profiles", out)
        self.assertIsInstance(out["profiles"], list)

    def test_at_least_4_presets(self) -> None:
        """Spec 11 §2.9 : on doit fournir au moins 4 presets predefinis
        (CinemaLux_v1, RemuxStrict_v1, StreamingOptimal_v1, Compact_v1)."""
        out = profiles_support.get_profiles(self.api)
        preset_rows = [p for p in out["profiles"] if not p["is_custom"]]
        self.assertGreaterEqual(len(preset_rows), 4, f"Presets manquants : {preset_rows}")

    def test_preset_ids_contain_streaming_and_compact(self) -> None:
        out = profiles_support.get_profiles(self.api)
        profile_ids = {p["id"] for p in out["profiles"]}
        self.assertIn("StreamingOptimal_v1", profile_ids)
        self.assertIn("Compact_v1", profile_ids)

    def test_profile_shape(self) -> None:
        out = profiles_support.get_profiles(self.api)
        for prof in out["profiles"]:
            for key in (
                "id",
                "name",
                "version",
                "is_active",
                "tiers",
                "weights",
            ):
                self.assertIn(key, prof, f"Clef {key} manquante dans {prof}")

    def test_custom_profile_listed(self) -> None:
        """Profil custom stocke dans settings.custom_quality_profiles -> liste."""
        self.api.settings._payload = {
            "custom_quality_profiles": [
                {
                    "id": "MyCustom_v1",
                    "version": 1,
                    "label": "Mon profil",
                    "tiers": {"platinum": 90, "gold": 80, "silver": 65, "bronze": 45},
                    "weights": {"video": 60, "audio": 30, "extras": 10},
                }
            ]
        }
        out = profiles_support.get_profiles(self.api)
        ids = {p["id"]: p for p in out["profiles"]}
        self.assertIn("MyCustom_v1", ids)
        self.assertTrue(ids["MyCustom_v1"]["is_custom"])

    def test_active_profile_flag(self) -> None:
        """Le flag is_active doit etre True pour le profil correspondant a
        settings.active_quality_profile_id."""
        self.api.settings._payload = {
            "active_quality_profile_id": "StreamingOptimal_v1",
        }
        out = profiles_support.get_profiles(self.api)
        active = [p for p in out["profiles"] if p["is_active"]]
        self.assertEqual(len(active), 1, f"1 seul profil actif attendu, recu {len(active)}")
        self.assertEqual(active[0]["id"], "StreamingOptimal_v1")


# ---------------------------------------------------------------------------
# 2) save_profile
# ---------------------------------------------------------------------------


class SaveProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.api = _FakeApi(self.state_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _valid_profile(self) -> Dict[str, Any]:
        prof = copy.deepcopy(default_quality_profile())
        prof["id"] = "TestCustom_v1"
        return prof

    def test_save_valid_profile(self) -> None:
        out = profiles_support.save_profile(self.api, self._valid_profile())
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["profile_id"], "TestCustom_v1")
        self.assertEqual(out["profile_version"], 1)

    def test_save_rejects_non_dict(self) -> None:
        out = profiles_support.save_profile(self.api, "not a dict")
        self.assertFalse(out["ok"])

    def test_rejects_tiers_not_decreasing(self) -> None:
        """Spec : platinum > gold > silver > bronze."""
        prof = self._valid_profile()
        prof["tiers"] = {"platinum": 50, "gold": 80, "silver": 65, "bronze": 45}  # platinum trop bas
        out = profiles_support.save_profile(self.api, prof)
        self.assertFalse(out["ok"])
        self.assertIn("errors", out)

    def test_rejects_equal_tiers(self) -> None:
        """Verifie qu'on rejette l'egalite (decroissance strict)."""
        prof = self._valid_profile()
        prof["tiers"] = {"platinum": 80, "gold": 80, "silver": 65, "bronze": 45}
        out = profiles_support.save_profile(self.api, prof)
        self.assertFalse(out["ok"])

    def test_rejects_weights_sum_off(self) -> None:
        """Spec : somme des poids ~1.00 (ou ~100). Hors tolerance => reject."""
        prof = self._valid_profile()
        # 60 + 30 + 10 = 100 OK. On envoie 60 + 30 + 50 = 140 = hors tolerance.
        prof["weights"] = {"video": 60, "audio": 30, "extras": 50}
        out = profiles_support.save_profile(self.api, prof)
        self.assertFalse(out["ok"])

    def test_weights_sum_validator_accepts_fraction(self) -> None:
        """Le validator local de profiles_support accepte les fractions (~1.0)
        meme si la suite du pipeline (validate_quality_profile backend) reclame
        des pourcentages. On teste l'unite, pas l'integration complete."""
        ok, errors, total = profiles_support._normalize_weights_sum({"video": 0.6, "audio": 0.3, "extras": 0.1})
        self.assertTrue(ok, f"Validator a rejete poids fractionnaire: {errors}")
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_weights_sum_validator_accepts_percent(self) -> None:
        """Validator accepte aussi les pourcentages (~100)."""
        ok, errors, total = profiles_support._normalize_weights_sum({"video": 60, "audio": 30, "extras": 10})
        self.assertTrue(ok, f"Validator a rejete poids percent: {errors}")
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_persists_in_settings(self) -> None:
        prof = self._valid_profile()
        out = profiles_support.save_profile(self.api, prof)
        self.assertTrue(out["ok"], out)
        current = self.api.settings.get_settings()
        custom_list = current.get("custom_quality_profiles") or []
        ids = {p.get("id") for p in custom_list if isinstance(p, dict)}
        self.assertIn("TestCustom_v1", ids)

    def test_replaces_existing_custom(self) -> None:
        """Resauvegarder le meme id remplace (et ne duplique pas)."""
        prof = self._valid_profile()
        profiles_support.save_profile(self.api, prof)
        # Modifie la version et resauvegarde
        prof["version"] = 2
        out = profiles_support.save_profile(self.api, prof)
        self.assertTrue(out["ok"])
        self.assertTrue(out["replaced"])
        custom = self.api.settings.get_settings().get("custom_quality_profiles") or []
        matching = [p for p in custom if p.get("id") == "TestCustom_v1"]
        self.assertEqual(len(matching), 1)


# ---------------------------------------------------------------------------
# 3) set_active_profile
# ---------------------------------------------------------------------------


class SetActiveProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.api = _FakeApi(self.state_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_activate_preset_by_preset_id(self) -> None:
        out = profiles_support.set_active_profile(self.api, "streaming_optimal")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["active_profile_id"], "streaming_optimal")
        current = self.api.settings.get_settings()
        self.assertEqual(current["active_quality_profile_id"], "streaming_optimal")

    def test_activate_preset_by_profile_id(self) -> None:
        out = profiles_support.set_active_profile(self.api, "StreamingOptimal_v1")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["active_profile_id"], "StreamingOptimal_v1")

    def test_activate_custom_profile(self) -> None:
        # Pre-store un profil custom
        prof = copy.deepcopy(default_quality_profile())
        prof["id"] = "MyActiveCustom_v1"
        self.api.settings._payload = {"custom_quality_profiles": [prof]}

        out = profiles_support.set_active_profile(self.api, "MyActiveCustom_v1")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["active_profile_id"], "MyActiveCustom_v1")
        current = self.api.settings.get_settings()
        self.assertEqual(current["active_quality_profile_id"], "MyActiveCustom_v1")
        # Verifie aussi que la DB a recu le profil
        self.assertEqual(self.api._db_active_profile["id"], "MyActiveCustom_v1")

    def test_reject_unknown_profile(self) -> None:
        out = profiles_support.set_active_profile(self.api, "DoesNotExist_v999")
        self.assertFalse(out["ok"])

    def test_reject_empty_id(self) -> None:
        out = profiles_support.set_active_profile(self.api, "")
        self.assertFalse(out["ok"])

    def test_flag_persisted(self) -> None:
        """Apres set_active, get_profiles doit renvoyer is_active=True
        sur le profil active."""
        profiles_support.set_active_profile(self.api, "compact")
        out = profiles_support.get_profiles(self.api)
        active = [p for p in out["profiles"] if p["is_active"]]
        self.assertEqual(len(active), 1)
        # set_active stocke l'id raw ("compact"), pas le profile_json["id"]
        self.assertEqual(active[0]["preset_id"], "compact")


# ---------------------------------------------------------------------------
# 4) reset_settings(scope)
# ---------------------------------------------------------------------------


class ResetSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.api = _FakeApi(self.state_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reject_unknown_scope(self) -> None:
        out = reset_support.reset_settings(self.api, "marsupial")
        self.assertFalse(out["ok"])

    def test_scope_all_returns_ok(self) -> None:
        out = reset_support.reset_settings(self.api, "all")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["scope"], "all")
        self.assertIsInstance(out["reset_keys"], list)
        self.assertGreater(len(out["reset_keys"]), 10)

    def test_scope_apparence_restores_default_theme(self) -> None:
        # Pre-store un theme custom
        self.api.settings._payload = {"theme": "neon-extra-extra"}
        out = reset_support.reset_settings(self.api, "apparence")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["scope"], "apparence")
        self.assertIn("theme", out["reset_keys"])
        # Verifie que la valeur a bien ete reset au default "studio"
        current = self.api.settings.get_settings()
        self.assertEqual(current.get("theme"), "studio")

    def test_scope_profils_qualite_clears_active_id(self) -> None:
        self.api.settings._payload = {
            "active_quality_profile_id": "compact",
            "custom_quality_profiles": [{"id": "Foo", "version": 1}],
        }
        out = reset_support.reset_settings(self.api, "profils-qualite")
        self.assertTrue(out["ok"], out)
        # Apres reset, ces 2 cles doivent etre dans reset_keys
        self.assertIn("active_quality_profile_id", out["reset_keys"])
        self.assertIn("custom_quality_profiles", out["reset_keys"])

    def test_scope_integrations_resets_tmdb_enabled(self) -> None:
        self.api.settings._payload = {"tmdb_enabled": False}
        out = reset_support.reset_settings(self.api, "integrations")
        self.assertTrue(out["ok"], out)
        current = self.api.settings.get_settings()
        self.assertTrue(current.get("tmdb_enabled"))

    def test_scope_nommage_resets_template(self) -> None:
        self.api.settings._payload = {"naming_movie_template": "totally custom"}
        out = reset_support.reset_settings(self.api, "nommage")
        self.assertTrue(out["ok"], out)
        current = self.api.settings.get_settings()
        self.assertEqual(current.get("naming_movie_template"), "{title} ({year})")

    def test_all_documented_scopes_accepted(self) -> None:
        """Spec 11 §5 + §2 enumere 10 categories : on les accepte toutes
        en plus de "all"."""
        for scope in (
            "all",
            "sources",
            "analyse",
            "nommage",
            "bibliotheque",
            "integrations",
            "notifications",
            "serveur",
            "apparence",
            "profils-qualite",
            "avance",
        ):
            out = reset_support.reset_settings(self.api, scope)
            self.assertTrue(out["ok"], f"Scope {scope} a echoue: {out}")


# ---------------------------------------------------------------------------
# 5) reset_database
# ---------------------------------------------------------------------------


class ResetDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.state_dir.mkdir(exist_ok=True)
        self.api = _FakeApi(self.state_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_db_returns_ok_with_empty_backup(self) -> None:
        """Pas de DB existante : reset_database retourne ok=True sans backup."""
        out = reset_support.reset_database(self.api)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["backup_path"], "")

    def test_backup_created_before_wipe(self) -> None:
        # Cree une fausse DB
        db_path = self.state_dir / "cinesort.db"
        db_path.write_bytes(b"SQLite format 3\x00" + b"DUMMY DATABASE CONTENT")

        out = reset_support.reset_database(self.api)
        self.assertTrue(out["ok"], out)
        # Backup cree
        backup = Path(out["backup_path"])
        self.assertTrue(backup.exists(), f"Backup absent: {backup}")
        self.assertTrue(backup.name.startswith("wipe_"))
        self.assertTrue(backup.name.endswith(".bak"))
        # Backup dans backups/
        self.assertEqual(backup.parent.name, "backups")
        # DB supprimee
        self.assertFalse(db_path.exists())

    def test_backup_contents_preserved(self) -> None:
        db_path = self.state_dir / "cinesort.db"
        magic = b"SQLite format 3\x00CONTENU_MAGIQUE"
        db_path.write_bytes(magic)
        out = reset_support.reset_database(self.api)
        self.assertTrue(out["ok"], out)
        backup = Path(out["backup_path"])
        self.assertEqual(backup.read_bytes(), magic)

    def test_wal_and_shm_files_deleted(self) -> None:
        db_path = self.state_dir / "cinesort.db"
        db_path.write_bytes(b"db")
        (self.state_dir / "cinesort.db-wal").write_bytes(b"wal")
        (self.state_dir / "cinesort.db-shm").write_bytes(b"shm")
        out = reset_support.reset_database(self.api)
        self.assertTrue(out["ok"], out)
        self.assertFalse(db_path.exists())
        self.assertFalse((self.state_dir / "cinesort.db-wal").exists())
        self.assertFalse((self.state_dir / "cinesort.db-shm").exists())

    def test_close_infra_called(self) -> None:
        db_path = self.state_dir / "cinesort.db"
        db_path.write_bytes(b"db")
        reset_support.reset_database(self.api)
        self.assertTrue(self.api._close_infra_called)


# ---------------------------------------------------------------------------
# 6) Endpoint wiring (facades + cinesort_api)
# ---------------------------------------------------------------------------


class EndpointWiringTests(unittest.TestCase):
    """Verifie que les 5 endpoints sont bien exposes sur les facades."""

    def test_settings_facade_has_new_endpoints(self) -> None:
        from cinesort.ui.api.facades.settings_facade import SettingsFacade

        for method in (
            "get_profiles",
            "save_profile",
            "set_active_profile",
            "reset_settings",
            "reset_database",
        ):
            self.assertTrue(
                callable(getattr(SettingsFacade, method, None)),
                f"Method {method} manquante sur SettingsFacade",
            )

    def test_quality_facade_has_profile_endpoints(self) -> None:
        """Spec 11 §7 cite aussi quality/get_profiles + quality/save_profile."""
        from cinesort.ui.api.facades.quality_facade import QualityFacade

        for method in ("get_profiles", "save_profile", "set_active_profile"):
            self.assertTrue(
                callable(getattr(QualityFacade, method, None)),
                f"Method {method} manquante sur QualityFacade",
            )

    def test_impl_methods_on_cinesort_api(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        for method in (
            "_get_profiles_impl",
            "_save_profile_impl",
            "_set_active_profile_impl",
            "_reset_settings_impl",
            "_reset_database_impl",
        ):
            self.assertTrue(
                callable(getattr(CineSortApi, method, None)),
                f"Method {method} manquante sur CineSortApi",
            )


if __name__ == "__main__":
    unittest.main()
