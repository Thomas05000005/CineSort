"""Tests pour ITER13 TIMEOUT_ADAPTATIF (cinesort/infra/probe/adaptive_timeout.py).

Couvre :
- Calcul timeout = base + per_gb * GB, borne [floor, ceiling].
- Precedence env > settings.probe_timeout_base_s > settings.probe_timeout_s (legacy) > const.
- Fichier inexistant -> base (pas penalise par stat KO).
- Config invalide -> retombe sur defauts (resilience).
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.probe.adaptive_timeout import (
    AdaptiveTimeoutConfig,
    compute_adaptive_timeout,
    resolve_adaptive_timeout_config,
)
from cinesort.infra.probe.constants import (
    PROBE_TIMEOUT_BASE_S,
    PROBE_TIMEOUT_CEILING_S,
    PROBE_TIMEOUT_FLOOR_S,
    PROBE_TIMEOUT_PER_GB_S,
)


class _FakeStat:
    """Stub minimal pour patch Path.stat()."""

    def __init__(self, size_bytes: int) -> None:
        self.st_size = size_bytes


class TestResolveAdaptiveTimeoutConfig(unittest.TestCase):
    """Precedence et defauts."""

    def setUp(self) -> None:
        # Nettoie les env vars potentielles avant chaque test.
        for k in (
            "CINESORT_PROBE_TIMEOUT_BASE",
            "CINESORT_PROBE_TIMEOUT_PER_GB",
            "CINESORT_PROBE_TIMEOUT_FLOOR",
            "CINESORT_PROBE_TIMEOUT_CEILING",
        ):
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        self.setUp()

    def test_defaut_constants(self) -> None:
        cfg = resolve_adaptive_timeout_config()
        self.assertEqual(cfg.base_s, float(PROBE_TIMEOUT_BASE_S))
        self.assertEqual(cfg.per_gb_s, float(PROBE_TIMEOUT_PER_GB_S))
        self.assertEqual(cfg.floor_s, float(PROBE_TIMEOUT_FLOOR_S))
        self.assertEqual(cfg.ceiling_s, float(PROBE_TIMEOUT_CEILING_S))

    def test_env_override_base(self) -> None:
        os.environ["CINESORT_PROBE_TIMEOUT_BASE"] = "60"
        cfg = resolve_adaptive_timeout_config()
        self.assertEqual(cfg.base_s, 60.0)

    def test_env_override_all(self) -> None:
        os.environ["CINESORT_PROBE_TIMEOUT_BASE"] = "45"
        os.environ["CINESORT_PROBE_TIMEOUT_PER_GB"] = "10"
        os.environ["CINESORT_PROBE_TIMEOUT_FLOOR"] = "15"
        os.environ["CINESORT_PROBE_TIMEOUT_CEILING"] = "600"
        cfg = resolve_adaptive_timeout_config()
        self.assertEqual(cfg.base_s, 45.0)
        self.assertEqual(cfg.per_gb_s, 10.0)
        self.assertEqual(cfg.floor_s, 15.0)
        self.assertEqual(cfg.ceiling_s, 600.0)

    def test_settings_probe_timeout_base_s(self) -> None:
        cfg = resolve_adaptive_timeout_config({"probe_timeout_base_s": 90.0})
        self.assertEqual(cfg.base_s, 90.0)

    def test_legacy_probe_timeout_s_used_as_base(self) -> None:
        """Retro-compat : si pas de probe_timeout_base_s, on prend probe_timeout_s."""
        cfg = resolve_adaptive_timeout_config({"probe_timeout_s": 45.0})
        self.assertEqual(cfg.base_s, 45.0)

    def test_precedence_base_s_over_legacy(self) -> None:
        """probe_timeout_base_s doit primer sur probe_timeout_s."""
        cfg = resolve_adaptive_timeout_config(
            {"probe_timeout_s": 45.0, "probe_timeout_base_s": 90.0}
        )
        self.assertEqual(cfg.base_s, 90.0)

    def test_env_primes_over_settings(self) -> None:
        os.environ["CINESORT_PROBE_TIMEOUT_BASE"] = "120"
        cfg = resolve_adaptive_timeout_config({"probe_timeout_base_s": 90.0})
        self.assertEqual(cfg.base_s, 120.0)

    def test_env_invalide_ignore(self) -> None:
        os.environ["CINESORT_PROBE_TIMEOUT_BASE"] = "pas-un-float"
        cfg = resolve_adaptive_timeout_config()
        # Retombe sur la constante par defaut.
        self.assertEqual(cfg.base_s, float(PROBE_TIMEOUT_BASE_S))

    def test_settings_invalide_ignore(self) -> None:
        cfg = resolve_adaptive_timeout_config({"probe_timeout_base_s": "lol"})
        self.assertEqual(cfg.base_s, float(PROBE_TIMEOUT_BASE_S))

    def test_negatif_clamp_to_default(self) -> None:
        cfg = resolve_adaptive_timeout_config({"probe_timeout_base_s": -10.0})
        self.assertEqual(cfg.base_s, float(PROBE_TIMEOUT_BASE_S))


class TestComputeAdaptiveTimeout(unittest.TestCase):
    """Calcul timeout fonction de la taille."""

    def test_fichier_inexistant_retourne_base(self) -> None:
        # stat() leve OSError -> size=0 -> timeout = base + 0 = base.
        t = compute_adaptive_timeout(Path("Z:/nope/inexistant.mkv"))
        self.assertEqual(t, float(PROBE_TIMEOUT_BASE_S))

    def test_petit_fichier_clampe_floor_si_base_basse(self) -> None:
        cfg = AdaptiveTimeoutConfig(base_s=5.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0)
        with patch("pathlib.Path.stat", return_value=_FakeStat(100 * 1024 * 1024)):
            t = compute_adaptive_timeout(Path("/fake/100mb.mp4"), config=cfg)
        # 5 + 5 * 0.0977 = 5.49 -> clampe floor 10s
        self.assertEqual(t, 10.0)

    def test_taille_moyenne_formule(self) -> None:
        cfg = AdaptiveTimeoutConfig(base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0)
        with patch("pathlib.Path.stat", return_value=_FakeStat(5 * 1024 * 1024 * 1024)):
            t = compute_adaptive_timeout(Path("/fake/5gb.mkv"), config=cfg)
        # 30 + 5 * 5 = 55s
        self.assertEqual(t, 55.0)

    def test_gros_fichier_clampe_ceiling(self) -> None:
        cfg = AdaptiveTimeoutConfig(base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0)
        with patch("pathlib.Path.stat", return_value=_FakeStat(80 * 1024 * 1024 * 1024)):
            t = compute_adaptive_timeout(Path("/fake/80gb.mkv"), config=cfg)
        # 30 + 5 * 80 = 430s -> clampe 300
        self.assertEqual(t, 300.0)

    def test_config_invalide_floor_gt_ceiling_retourne_ceiling(self) -> None:
        """Config corrompue ne casse pas le scan : retombe sur ceiling."""
        cfg = AdaptiveTimeoutConfig(base_s=30.0, per_gb_s=5.0, floor_s=500.0, ceiling_s=100.0)
        with patch("pathlib.Path.stat", return_value=_FakeStat(1024)):
            t = compute_adaptive_timeout(Path("/fake/small.mkv"), config=cfg)
        self.assertEqual(t, 100.0)

    def test_settings_passe_via_compute(self) -> None:
        """compute_adaptive_timeout doit accepter settings en place de config."""
        with patch("pathlib.Path.stat", return_value=_FakeStat(2 * 1024 * 1024 * 1024)):
            t = compute_adaptive_timeout(
                Path("/fake/2gb.mkv"),
                settings={"probe_timeout_base_s": 20.0, "probe_timeout_per_gb_s": 3.0},
            )
        # 20 + 3 * 2 = 26s
        self.assertEqual(t, 26.0)


if __name__ == "__main__":
    unittest.main()
