"""ITER13 - Test du circuit breaker par source UNC pour les probes.

Objectif (BILAN_ITER13 section 3.c) : prouver que
`cinesort/infra/probe/_source_circuit_breaker.py::SourceCircuitBreaker` :
1. Apres N echecs consecutifs sur une source UNC, la source bascule DEGRADED.
2. En mode DEGRADED, `check_or_raise` leve `SourceDegradedError` immediat
   (pas de timeout 30s gaspille).
3. Apres `recovery_timeout` seconds, la source repasse CLOSED automatiquement.
4. Le succes reset le compteur d'echecs et referme la source.
5. Les paths LOCAUX (C:\\, D:\\) ne sont JAMAIS surveilles (no-op).
6. Granularite par source : panne sur \\nas1 ne penalise pas \\nas2.

Test family B : panne SIMULEE, on injecte directement les record_failure.

Identification DECOUPLEE du probe : meme en mode DEGRADED, l'item reste
identifiable+renommable via TMDb/NFO/filename. Le breaker n'influe QUE
sur la lecture des metadonnees probe (acquis racine C iter4).
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.probe._source_circuit_breaker import (
    SourceCircuitBreaker,
    SourceDegradedError,
    extract_network_source,
)


class TestExtractNetworkSource(unittest.TestCase):
    """Identification de la source UNC depuis un Path."""

    def test_unc_classique(self) -> None:
        src = extract_network_source(Path(r"\\nas\films\Inception.mkv"))
        self.assertEqual(src, r"\\nas\films")

    def test_unc_ip(self) -> None:
        src = extract_network_source(Path(r"\\192.168.1.10\media\videos\film.mkv"))
        self.assertEqual(src, r"\\192.168.1.10\media")

    def test_path_local_retourne_none(self) -> None:
        """Paths locaux JAMAIS surveilles (no-op breaker)."""
        self.assertIsNone(extract_network_source(Path(r"C:\Users\films\f.mkv")))
        self.assertIsNone(extract_network_source(Path(r"D:\media\f.mkv")))
        self.assertIsNone(extract_network_source(Path("/home/user/f.mkv")))

    def test_case_insensitive(self) -> None:
        src = extract_network_source(Path(r"\\NAS\Films\f.mkv"))
        self.assertEqual(src, r"\\nas\films")


class TestDegradationApresN(unittest.TestCase):
    """Apres N echecs consecutifs -> DEGRADED."""

    def test_degradation_au_seuil(self) -> None:
        """3 echecs avec seuil 3 -> DEGRADED."""
        breaker = SourceCircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f1.mkv")
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        self.assertFalse(breaker.is_degraded(nas_path),
                         "Pas encore DEGRADED apres 2/3 echecs")
        breaker.record_failure(nas_path)
        self.assertTrue(breaker.is_degraded(nas_path),
                        "DEGRADED apres 3/3 echecs")

    def test_check_or_raise_leve_apres_seuil(self) -> None:
        """En mode DEGRADED, check_or_raise leve immediat."""
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f1.mkv")
        # Ne leve pas avant le seuil.
        breaker.check_or_raise(nas_path)
        # Atteint le seuil.
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        with self.assertRaises(SourceDegradedError):
            breaker.check_or_raise(nas_path)

    def test_returned_just_degraded_flag(self) -> None:
        """record_failure retourne True a l'instant precis du basculement."""
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f1.mkv")
        self.assertFalse(breaker.record_failure(nas_path), "1er echec n'est pas basculement")
        self.assertTrue(breaker.record_failure(nas_path),
                        "2eme echec = basculement DEGRADED")
        # Echecs suivants pendant la fenetre DEGRADED ne re-basculent pas.
        self.assertFalse(breaker.record_failure(nas_path),
                         "Pendant DEGRADED, pas de re-basculement")


class TestResetApresDelay(unittest.TestCase):
    """Apres recovery_timeout, la source repasse CLOSED automatiquement."""

    def test_auto_reset_apres_recovery(self) -> None:
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
        nas_path = Path(r"\\nas\films\f1.mkv")
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        self.assertTrue(breaker.is_degraded(nas_path))

        # Avance le temps de 2s pour passer le recovery_timeout.
        future = time.time() + 2.0
        with patch("time.time", return_value=future):
            # check_or_raise auto-reset si le timeout expire.
            breaker.check_or_raise(nas_path)
            # is_degraded retourne False apres expiration.
            self.assertFalse(breaker.is_degraded(nas_path),
                             "Apres recovery_timeout, source revient CLOSED")


class TestSuccesResetCompteur(unittest.TestCase):
    """Un succes referme la source et reset le compteur."""

    def test_succes_avant_seuil_reset(self) -> None:
        breaker = SourceCircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f1.mkv")
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        breaker.record_success(nas_path)
        # Apres reset, faudrait 3 NOUVEAUX echecs pour DEGRADER.
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        self.assertFalse(breaker.is_degraded(nas_path),
                         "Compteur doit avoir ete reset par le succes")

    def test_succes_referme_breaker_ouvert(self) -> None:
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f1.mkv")
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        self.assertTrue(breaker.is_degraded(nas_path))
        breaker.record_success(nas_path)
        self.assertFalse(breaker.is_degraded(nas_path),
                         "Succes referme aussi le breaker en DEGRADED")


class TestPathLocauxNoOp(unittest.TestCase):
    """Paths locaux JAMAIS surveilles (gain resilience nul + risque blocage)."""

    def test_local_path_pas_de_breaker(self) -> None:
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        local_path = Path(r"C:\Users\films\f.mkv")
        # Meme apres 100 echecs locaux : pas de breaker.
        for _ in range(100):
            breaker.record_failure(local_path)
        self.assertFalse(breaker.is_degraded(local_path))
        # check_or_raise no-op sans exception.
        breaker.check_or_raise(local_path)


class TestGranulariteParSource(unittest.TestCase):
    """Panne sur une source ne penalise PAS les autres."""

    def test_isolation_sources(self) -> None:
        """\\nas1 DEGRADED, \\nas2 reste sain."""
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        nas1 = Path(r"\\nas1\films\f.mkv")
        nas2 = Path(r"\\nas2\films\f.mkv")
        breaker.record_failure(nas1)
        breaker.record_failure(nas1)
        self.assertTrue(breaker.is_degraded(nas1))
        self.assertFalse(breaker.is_degraded(nas2),
                         "Une source en panne ne doit pas affecter l'autre")
        # Probe sur nas2 doit passer.
        breaker.check_or_raise(nas2)


class TestConfigInvalideResiste(unittest.TestCase):
    """Config invalide -> raise ValueError, pas crash silencieux."""

    def test_threshold_negatif_raise(self) -> None:
        with self.assertRaises(ValueError):
            SourceCircuitBreaker(failure_threshold=0, recovery_timeout=60.0)

    def test_recovery_negatif_raise(self) -> None:
        with self.assertRaises(ValueError):
            SourceCircuitBreaker(failure_threshold=2, recovery_timeout=-1.0)


class TestSnapshotEtReset(unittest.TestCase):
    """Diagnostics breaker snapshot + reset manuel."""

    def test_snapshot_etat_degraded(self) -> None:
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f.mkv")
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        snap = breaker.snapshot()
        self.assertIn(r"\\nas\films", snap)
        self.assertEqual(snap[r"\\nas\films"]["degraded"], 1.0)
        self.assertGreater(snap[r"\\nas\films"]["failures"], 0)

    def test_reset_complet(self) -> None:
        breaker = SourceCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        nas_path = Path(r"\\nas\films\f.mkv")
        breaker.record_failure(nas_path)
        breaker.record_failure(nas_path)
        breaker.reset()
        self.assertFalse(breaker.is_degraded(nas_path))
        self.assertEqual(breaker.snapshot(), {})


if __name__ == "__main__":
    unittest.main()
