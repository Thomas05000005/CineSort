"""LOT E — Tests de robustesse pour la couche settings.

Couvre : JSON corrompu, champs manquants, mauvais types, race save/run,
secrets masques dans get_settings.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from cinesort.ui.api import settings_support
from cinesort.ui.api.cinesort_api import CineSortApi


class SettingsRobustnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_settings_robust_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = settings_support.settings_path(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, content: str) -> None:
        self.settings_path.write_text(content, encoding="utf-8")

    # 36
    def test_settings_json_corrupt_starts_with_defaults(self) -> None:
        """JSON invalide → read_settings retourne {} → defaults appliques."""
        self._write("{ this is not valid json")
        data = settings_support.read_settings(self.state_dir)
        self.assertEqual(data, {})

        # L'app peut demarrer avec les defaults
        payload = settings_support.get_settings_payload(
            state_dir=self.state_dir,
            default_root="C:/Films",
            default_state_dir_example="C:/Users/Test/AppData",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Dossier Nettoyage",
            default_probe_backend="auto",
            debug_enabled=False,
        )
        self.assertIn("root", payload)
        self.assertTrue(payload.get("tmdb_enabled"))  # default True

    # 37
    def test_settings_json_incomplete_fills_defaults(self) -> None:
        """Settings {} → defaults appliques pour tous les champs."""
        self._write("{}")
        payload = settings_support.get_settings_payload(
            state_dir=self.state_dir,
            default_root="C:/Films",
            default_state_dir_example="X",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Dossier Nettoyage",
            default_probe_backend="auto",
            debug_enabled=False,
        )
        # Check defaults critiques (note: root peut etre "" apres migration root→roots)
        self.assertIn("root", payload)
        self.assertTrue(payload["tmdb_enabled"])
        self.assertFalse(payload["rest_api_enabled"])
        self.assertIn("theme", payload)
        self.assertIn("auto_approve_threshold", payload)
        self.assertEqual(payload["auto_approve_threshold"], 85)

    # 38
    def test_settings_json_bad_values_normalized(self) -> None:
        """port=-1, root=null → normalisation en save_settings."""
        # Prepare un root valide
        good_root = self.state_dir / "root"
        good_root.mkdir()
        bad_payload = {
            "root": str(good_root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": "not-a-bool",
            "auto_approve_threshold": "999",
            "rest_api_port": -1,
        }
        new_state, result = settings_support.save_settings_payload(
            bad_payload,
            current_state_dir=self.state_dir,
            default_root="C:/Films",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Dossier Nettoyage",
            default_probe_backend="auto",
            debug_enabled=False,
        )
        # save_settings doit reussir malgre les types invalides
        self.assertIsNotNone(result)
        # Recharger et verifier les normalisations
        reloaded = settings_support.read_settings(new_state)
        if "rest_api_port" in reloaded:
            port = reloaded["rest_api_port"]
            self.assertGreaterEqual(port, 1024, f"port doit etre clampe >= 1024 : {port}")
        if "auto_approve_threshold" in reloaded:
            th = reloaded["auto_approve_threshold"]
            self.assertLessEqual(th, 100)
            self.assertGreaterEqual(th, 70)

    # 39
    def test_settings_save_during_active_run_no_crash(self) -> None:
        """save_settings pendant qu'un run est actif : pas de corruption cross-thread."""
        api = CineSortApi()
        api.save_settings(
            {
                "root": str(self.state_dir / "root"),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        (self.state_dir / "root").mkdir(exist_ok=True)
        (self.state_dir / "root" / "F.2020").mkdir()
        (self.state_dir / "root" / "F.2020" / "F.2020.mkv").write_bytes(b"x" * 2048)
        import cinesort.domain.core as core

        _orig_min = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1
        try:
            start = api.start_plan(
                {
                    "root": str(self.state_dir / "root"),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                }
            )
            self.assertTrue(start.get("ok"), start)

            errors: list = []

            def _save_repeatedly():
                for _ in range(10):
                    try:
                        api.save_settings(
                            {
                                "root": str(self.state_dir / "root"),
                                "state_dir": str(self.state_dir),
                                "tmdb_enabled": False,
                                "notifications_enabled": True,
                            }
                        )
                    except Exception as exc:
                        errors.append(exc)
                    time.sleep(0.005)

            t = threading.Thread(target=_save_repeatedly)
            t.start()
            # Attendre fin du scan
            deadline = time.time() + 10
            while time.time() < deadline:
                s = api.get_status(start["run_id"], 0)
                if s.get("done"):
                    break
                time.sleep(0.02)
            t.join(timeout=5)

            self.assertEqual(errors, [], f"Erreurs save pendant run : {errors}")
        finally:
            core.MIN_VIDEO_BYTES = _orig_min

    # 40
    def test_secrets_masked_in_get_settings(self) -> None:
        """H2 : secrets externes (plex, radarr, email) sont masques.
        BUG 1 : rest_api_token N'EST PLUS masque (c'est le propre token de l'utilisateur,
        il doit pouvoir le voir pour se connecter depuis d'autres appareils).

        SEC-H2 (Phase 1 v7.8.0) : tmdb_api_key et jellyfin_api_key sont aussi masques.
        Avant ce fix, ils etaient retournes en clair via POST /api/get_settings.
        """
        api = CineSortApi()
        good_root = self.state_dir / "root"
        good_root.mkdir()
        # remember_key=True pour persister la cle TMDb (sinon settings_support
        # nettoie la cle a la sauvegarde par defaut).
        api.save_settings(
            {
                "root": str(good_root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "remember_key": True,
                "tmdb_api_key": "my-tmdb-secret-key",
                "jellyfin_api_key": "my-jellyfin-secret-key",
                "plex_token": "my-plex-secret-xyz",
                "radarr_api_key": "my-radarr-secret",
                "rest_api_token": "my-rest-secret",
                "email_smtp_password": "my-email-password",
            }
        )
        loaded = api.get_settings()
        mask = "\u2022" * 8

        # SEC-H2 : tmdb_api_key et jellyfin_api_key sont MAINTENANT masques aussi
        for field in ("tmdb_api_key", "jellyfin_api_key", "plex_token",
                      "radarr_api_key", "email_smtp_password"):
            self.assertEqual(loaded[field], mask, f"{field} doit etre masque : {loaded.get(field)}")
            self.assertTrue(loaded.get(f"_has_{field}"), f"_has_{field} doit etre True")

        # Le token REST est retourne EN CLAIR (BUG 1 fix, comportement preserve)
        self.assertEqual(loaded["rest_api_token"], "my-rest-secret")

        # SEC-H2 : aucun des secrets ne doit fuiter dans le JSON serialise
        import json
        serialized = json.dumps(loaded)
        for secret in (
            "my-tmdb-secret-key",
            "my-jellyfin-secret-key",
            "my-plex-secret-xyz",
            "my-radarr-secret",
            "my-email-password",
        ):
            self.assertNotIn(
                secret, serialized,
                f"Secret '{secret}' fuit dans get_settings JSON : {serialized[:200]}"
            )

    def test_save_settings_with_mask_preserves_existing_keys_sec_h2(self) -> None:
        """SEC-H2 : si le frontend renvoie le masque (user n'a pas modifie), la
        valeur existante (TMDb/Jellyfin) doit etre preservee \u2014 sinon la save
        ecraserait la cle avec le masque."""
        api = CineSortApi()
        good_root = self.state_dir / "root"
        good_root.mkdir()
        api.save_settings(
            {
                "root": str(good_root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "remember_key": True,
                "tmdb_api_key": "original-tmdb",
                "jellyfin_api_key": "original-jellyfin",
            }
        )
        # Le frontend renvoie le masque (user n'a pas touche aux champs)
        mask = "\u2022" * 8
        api.save_settings(
            {
                "root": str(good_root),
                "state_dir": str(self.state_dir),
                "tmdb_api_key": mask,
                "jellyfin_api_key": mask,
                "auto_approve_threshold": 90,  # User a juste modifie ce champ
            }
        )
        # Les cles originales doivent etre preservees (pas remplacees par le masque)
        from cinesort.ui.api.settings_support import read_settings
        raw = read_settings(self.state_dir)
        self.assertEqual(raw.get("tmdb_api_key"), "original-tmdb")
        self.assertEqual(raw.get("jellyfin_api_key"), "original-jellyfin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
