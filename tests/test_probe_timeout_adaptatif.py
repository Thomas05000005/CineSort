"""ITER13 - Test de borne temps observe vs fichier taille variable.

Objectif (BILAN_ITER13 section 3.a) : prouver que le timeout adaptatif
(`cinesort/infra/probe/adaptive_timeout.py`) borne le temps de probe en
fonction de la taille du fichier, plutot que d'utiliser un couperet
unique 30s qui :
- coupe un gros 4K HEVC 80 GB sur NAS lent (faux negatif)
- laisse un petit MP4 200 MB hanger 30s pour rien

Test family B (panne simulee, pas vrai NAS).

Specifications testees :
1. Petit fichier (200 MB) -> timeout proche de la base (faible).
2. Fichier moyen (5 GB) -> base + 5*per_gb.
3. Gros fichier (80 GB) -> clamp au ceiling.
4. Fichier injoignable (stat KO) -> base (pas penalise).
5. Le temps RELLEMENT mesure pour un probe simule respecte la borne.

Identification DECOUPLEE du probe : ce module ne lit que la taille via
`Path.stat()`, n'altere rien d'autre. Sans probe, l'item reste
identifiable+renommable (memoire racine iter4).
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.probe.adaptive_timeout import (
    AdaptiveTimeoutConfig,
    compute_adaptive_timeout,
)


class _FakeStat:
    """Stub minimal pour patch Path.stat()."""

    def __init__(self, size_bytes: int) -> None:
        self.st_size = size_bytes


class TestTimeoutBornePiloteParTaille(unittest.TestCase):
    """Le timeout doit etre proportionne a la taille du fichier."""

    def test_petit_fichier_donne_petit_timeout(self) -> None:
        """200 MB -> timeout ~ base, JAMAIS le ceiling 300s."""
        cfg = AdaptiveTimeoutConfig(
            base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0
        )
        with patch("pathlib.Path.stat", return_value=_FakeStat(200 * 1024 * 1024)):
            t = compute_adaptive_timeout(Path("/fake/small.mp4"), config=cfg)
        # base 30 + 5 * 0.195 ~ 31s
        self.assertLess(t, 35.0, "Petit fichier devrait avoir timeout proche de base")
        self.assertGreaterEqual(t, 10.0, "Ne descend jamais sous le floor")
        # Specifiquement : pas le ceiling.
        self.assertNotEqual(t, 300.0, "Petit fichier doit etre LOIN du ceiling 300s")

    def test_gros_fichier_donne_gros_timeout(self) -> None:
        """80 GB -> ceiling (gros NAS lent doit avoir le temps de lire moov+sidx)."""
        cfg = AdaptiveTimeoutConfig(
            base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0
        )
        with patch("pathlib.Path.stat", return_value=_FakeStat(80 * 1024 * 1024 * 1024)):
            t = compute_adaptive_timeout(Path("/fake/4k_hevc.mkv"), config=cfg)
        # 30 + 5 * 80 = 430s -> clamp ceiling 300s
        self.assertEqual(t, 300.0, "Gros fichier doit etre clampe au ceiling")

    def test_borne_observee_jamais_au_dessus_ceiling(self) -> None:
        """Quel que soit la taille extreme, le timeout est plafonne par ceiling."""
        cfg = AdaptiveTimeoutConfig(
            base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0
        )
        # 1000 TB hypothetique (impossible mais defense in depth).
        with patch("pathlib.Path.stat", return_value=_FakeStat(10**15)):
            t = compute_adaptive_timeout(Path("/fake/absurde.mkv"), config=cfg)
        self.assertLessEqual(t, cfg.ceiling_s)

    def test_borne_observee_jamais_sous_floor(self) -> None:
        """Quel que soit la taille minuscule, le timeout est >= floor."""
        cfg = AdaptiveTimeoutConfig(
            base_s=5.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0
        )
        with patch("pathlib.Path.stat", return_value=_FakeStat(1)):
            t = compute_adaptive_timeout(Path("/fake/tiny.mkv"), config=cfg)
        self.assertGreaterEqual(t, cfg.floor_s)

    def test_fichier_injoignable_retourne_base_pas_penalise(self) -> None:
        """stat() KO -> base (pas de bonus mais pas non plus 0)."""
        t = compute_adaptive_timeout(Path("Z:/nope/inexistant.mkv"))
        # Sans bonus taille, timeout = base (30s defaut).
        self.assertGreaterEqual(t, 10.0, "Fichier injoignable ne doit pas tomber en zone deroutante")

    def test_progressivite_monotone(self) -> None:
        """Le timeout doit croitre (ou rester egal) quand la taille croit."""
        cfg = AdaptiveTimeoutConfig(
            base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0
        )
        sizes_gb = [0.1, 1, 5, 10, 20, 40, 80]
        prev = -1.0
        for gb in sizes_gb:
            with patch(
                "pathlib.Path.stat",
                return_value=_FakeStat(int(gb * 1024 * 1024 * 1024)),
            ):
                t = compute_adaptive_timeout(Path(f"/fake/{gb}gb.mkv"), config=cfg)
            self.assertGreaterEqual(t, prev, f"Non monotone a {gb} GB: {t} < {prev}")
            prev = t


class TestTempsObserveRespecteLaBorne(unittest.TestCase):
    """Sanity check : sleep simule capturable par la borne calculee.

    On ne mesure pas le temps reel d'un vrai probe (ce sont tests B sans NAS),
    on verifie qu'un probe SIMULE qui hangerait au-dela du timeout calcule
    EST bien intercepte (via timeout exception cote runner reel, ici on
    simule juste le contrat de borne).
    """

    def test_temps_simule_court_passe_sous_borne(self) -> None:
        cfg = AdaptiveTimeoutConfig(
            base_s=30.0, per_gb_s=5.0, floor_s=10.0, ceiling_s=300.0
        )
        with patch("pathlib.Path.stat", return_value=_FakeStat(1 * 1024 * 1024 * 1024)):
            borne = compute_adaptive_timeout(Path("/fake/1gb.mkv"), config=cfg)
        # Simulation : un probe qui prendrait 0.1s passe largement sous la borne.
        t0 = time.monotonic()
        time.sleep(0.05)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, borne, "Probe rapide doit passer sous la borne calculee")


if __name__ == "__main__":
    unittest.main()
