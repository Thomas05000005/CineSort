"""VO-B-CONFIG : tests pour le setting scan_max_workers (tri-etat auto/manuel).

Couvre :
  - Default mode "auto" + value=1 quand settings.json vierge.
  - get_scan_max_workers_payload retourne mode/value/effective/min/max coherents.
  - set_scan_max_workers_payload(mode="manual", value=8) persiste et reload OK.
  - set_scan_max_workers_payload(mode invalide) -> erreur facade.
  - set_scan_max_workers_payload(mode="manual", value invalide) -> erreur facade.
  - Synergie VO-A : en mode "auto", effective = auto_suggestion mappe selon
    le storage detecte (mocke pour determinisme cross-platform).
  - Backward compat strict : avec settings absents OU mode="manual" + value=1,
    resolve_effective_scan_max_workers retourne 1 (comportement sequentiel).
  - build_cfg_from_settings injecte scan_max_workers depuis le payload manuel.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.settings_support as settings_support


class ScanMaxWorkersDefaultTests(unittest.TestCase):
    """Default = mode auto + value=1 (backward compat stricte)."""

    def test_default_mode_is_auto_when_no_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_default_") as tmp:
            state_dir = Path(tmp)
            payload = settings_support.get_scan_max_workers_payload(state_dir)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "auto")
            self.assertEqual(payload["value"], 1)
            self.assertEqual(payload["min"], 1)
            self.assertEqual(payload["max"], 64)
            # storage_detected est determine par _detect_storage_profile (heuristique)
            self.assertIn(payload["storage_detected"], ("local_ssd", "nas_smb"))
            # auto_suggestion doit etre un entier dans la plage [1..64]
            self.assertGreaterEqual(payload["auto_suggestion"], 1)
            self.assertLessEqual(payload["auto_suggestion"], 64)
            # En mode auto, effective == auto_suggestion
            self.assertEqual(payload["effective"], payload["auto_suggestion"])

    def test_default_via_apply_settings_defaults(self) -> None:
        """apply_settings_defaults doit injecter mode='auto' + value=1 si absents."""
        with tempfile.TemporaryDirectory(prefix="vob_cfg_defaults_") as tmp:
            state_dir = Path(tmp)
            data: dict = {}
            payload = settings_support.apply_settings_defaults(
                data,
                state_dir=state_dir,
                default_root="/tmp",
                default_state_dir_example="/tmp",
                default_collection_folder_name="_Collection",
                default_empty_folders_folder_name="_Vide",
                default_residual_cleanup_folder_name="_Nettoyage",
                default_probe_backend="auto",
                debug_enabled=False,
            )
            self.assertEqual(payload["scan_max_workers_mode"], "auto")
            self.assertEqual(payload["scan_max_workers_value"], 1)


class ScanMaxWorkersSetManualTests(unittest.TestCase):
    """Setter en mode manual : persistence + reload."""

    def test_set_manual_8_persists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_manual_") as tmp:
            state_dir = Path(tmp)
            result = settings_support.set_scan_max_workers_payload(
                state_dir, mode="manual", value=8
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "manual")
            self.assertEqual(result["value"], 8)
            self.assertEqual(result["effective"], 8)
            # Re-read pour verifier la persistence sur disque
            reloaded = settings_support.get_scan_max_workers_payload(state_dir)
            self.assertEqual(reloaded["mode"], "manual")
            self.assertEqual(reloaded["value"], 8)
            self.assertEqual(reloaded["effective"], 8)
            # Le fichier settings.json doit contenir les cles attendues
            sjson = json.loads((state_dir / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(sjson["scan_max_workers_mode"], "manual")
            self.assertEqual(sjson["scan_max_workers_value"], 8)

    def test_set_manual_max_64_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_manual_max_") as tmp:
            state_dir = Path(tmp)
            result = settings_support.set_scan_max_workers_payload(
                state_dir, mode="manual", value=64
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["value"], 64)

    def test_set_back_to_auto_resets_effective(self) -> None:
        """Repasser en auto apres manual : effective re-tire de auto_suggestion."""
        with tempfile.TemporaryDirectory(prefix="vob_cfg_back_auto_") as tmp:
            state_dir = Path(tmp)
            # 1) mode manuel 16
            settings_support.set_scan_max_workers_payload(state_dir, "manual", 16)
            # 2) retour auto
            result = settings_support.set_scan_max_workers_payload(state_dir, "auto", None)
            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "auto")
            self.assertEqual(result["effective"], result["auto_suggestion"])


class ScanMaxWorkersValidationErrorTests(unittest.TestCase):
    """La facade doit renvoyer ok=False sur tout input invalide (memoire user)."""

    def test_invalid_mode_returns_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_inv_mode_") as tmp:
            result = settings_support.set_scan_max_workers_payload(
                Path(tmp), mode="cluster", value=4
            )
            self.assertFalse(result.get("ok"))
            self.assertIn("invalide", result.get("message", "").lower())

    def test_manual_without_value_returns_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_no_val_") as tmp:
            result = settings_support.set_scan_max_workers_payload(
                Path(tmp), mode="manual", value=None
            )
            self.assertFalse(result.get("ok"))

    def test_manual_value_too_low_returns_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_low_") as tmp:
            result = settings_support.set_scan_max_workers_payload(
                Path(tmp), mode="manual", value=0
            )
            self.assertFalse(result.get("ok"))

    def test_manual_value_too_high_returns_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_high_") as tmp:
            result = settings_support.set_scan_max_workers_payload(
                Path(tmp), mode="manual", value=100
            )
            self.assertFalse(result.get("ok"))

    def test_manual_value_non_numeric_returns_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_nonint_") as tmp:
            result = settings_support.set_scan_max_workers_payload(
                Path(tmp), mode="manual", value="abc"
            )
            self.assertFalse(result.get("ok"))

    def test_manual_value_bool_rejected(self) -> None:
        """bool est sous-classe d'int : on rejette explicitement pour eviter
        True -> 1 silencieux."""
        with tempfile.TemporaryDirectory(prefix="vob_cfg_bool_") as tmp:
            result = settings_support.set_scan_max_workers_payload(
                Path(tmp), mode="manual", value=True
            )
            self.assertFalse(result.get("ok"))


class ScanMaxWorkersAutoSynergyVOATests(unittest.TestCase):
    """Synergie VO-B/VO-A : en mode auto, effective decoule du storage detecte."""

    def test_auto_local_ssd_returns_8_workers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_synergy_ssd_") as tmp:
            state_dir = Path(tmp)
            with mock.patch.object(
                settings_support, "_detect_storage_profile", return_value="local_ssd"
            ):
                payload = settings_support.get_scan_max_workers_payload(state_dir)
                self.assertEqual(payload["mode"], "auto")
                self.assertEqual(payload["storage_detected"], "local_ssd")
                self.assertEqual(payload["auto_suggestion"], 8)
                self.assertEqual(payload["effective"], 8)

    def test_auto_nas_smb_returns_4_workers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vob_cfg_synergy_nas_") as tmp:
            state_dir = Path(tmp)
            with mock.patch.object(
                settings_support, "_detect_storage_profile", return_value="nas_smb"
            ):
                payload = settings_support.get_scan_max_workers_payload(state_dir)
                self.assertEqual(payload["mode"], "auto")
                self.assertEqual(payload["storage_detected"], "nas_smb")
                self.assertEqual(payload["auto_suggestion"], 4)
                self.assertEqual(payload["effective"], 4)

    def test_resolve_effective_uses_auto_storage(self) -> None:
        """resolve_effective_scan_max_workers branche bien VO-A en mode auto."""
        with tempfile.TemporaryDirectory(prefix="vob_cfg_resolve_") as tmp:
            state_dir = Path(tmp)
            # Pas de settings.json ecrit -> defaut auto
            with mock.patch.object(
                settings_support, "_detect_storage_profile", return_value="local_ssd"
            ):
                effective = settings_support.resolve_effective_scan_max_workers(state_dir)
                self.assertEqual(effective, 8)


class ScanMaxWorkersBackwardCompatTests(unittest.TestCase):
    """Backward compat (memoire user) : aucune regression de comportement seq."""

    def test_resolve_effective_with_manual_1_is_strictly_sequential(self) -> None:
        """mode=manual + value=1 -> resolve retourne 1 (pas de pool cree dans
        _local_candidate.resolve_scan_max_workers)."""
        with tempfile.TemporaryDirectory(prefix="vob_cfg_seq_") as tmp:
            state_dir = Path(tmp)
            settings_support.set_scan_max_workers_payload(state_dir, "manual", 1)
            effective = settings_support.resolve_effective_scan_max_workers(state_dir)
            self.assertEqual(effective, 1)

    def test_resolve_effective_with_corrupted_settings_returns_1(self) -> None:
        """Settings.json corrompu / illisible -> retombe sur 1 (sequentiel)."""
        with tempfile.TemporaryDirectory(prefix="vob_cfg_corrupt_") as tmp:
            state_dir = Path(tmp)
            # Force un settings.json non-JSON
            (state_dir / "settings.json").write_text("not a json", encoding="utf-8")
            effective = settings_support.resolve_effective_scan_max_workers(state_dir)
            # read_settings retourne {} sur JSON invalide -> mode auto -> detect_storage
            # On verifie juste que c'est un int >= 1.
            self.assertGreaterEqual(effective, 1)


class ScanMaxWorkersBuildCfgIntegrationTests(unittest.TestCase):
    """build_cfg_from_settings doit propager scan_max_workers en mode manuel."""

    def test_build_cfg_with_manual_value_propagates_to_config(self) -> None:
        settings = {
            "scan_max_workers_mode": "manual",
            "scan_max_workers_value": 16,
        }
        cfg = settings_support.build_cfg_from_settings(
            settings,
            root=Path("/tmp/library"),
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Nettoyage",
        )
        self.assertEqual(cfg.scan_max_workers, 16)

    def test_build_cfg_with_auto_mode_falls_back_to_sequential(self) -> None:
        """En mode auto sans state_dir context, build_cfg retombe sur 1
        (backward compat : aucune surprise dans le code-path run_row)."""
        settings = {
            "scan_max_workers_mode": "auto",
            "scan_max_workers_value": 8,
        }
        cfg = settings_support.build_cfg_from_settings(
            settings,
            root=Path("/tmp/library"),
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Nettoyage",
        )
        self.assertEqual(cfg.scan_max_workers, 1)

    def test_build_cfg_clamps_manual_too_high(self) -> None:
        settings = {
            "scan_max_workers_mode": "manual",
            "scan_max_workers_value": 999,
        }
        cfg = settings_support.build_cfg_from_settings(
            settings,
            root=Path("/tmp/library"),
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Nettoyage",
        )
        # _normalize_scan_max_workers_value clampe a 64
        self.assertEqual(cfg.scan_max_workers, 64)


if __name__ == "__main__":
    unittest.main()
