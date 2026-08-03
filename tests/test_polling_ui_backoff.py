"""ITER13 - Test statique du polling UI backoff (web/dashboard/views/traitement.js).

Objectif (BILAN_ITER13 section 3.e) : prouver que le polling UI
1. Definit une sequence de backoff exponentielle [1s, 2s, 4s, 8s].
2. Plafonne a 8s (pas de 16s, 32s qui ralentiraient inutilement la reprise).
3. Reset le streak sur succes (premier ok -> retour interval contextuel).
4. Borne le streak via POLL_BACKOFF_MAX_ATTEMPTS (pas infini).
5. Reset complet au unmount (pas de fantome au remount).
6. Expose un signal visible "Reconnexion dans Xs" + cause (pas silencieux).

Test family B : test STATIQUE (parse du JS), pas Playwright -> evite
dependance navigateur dans CI. Verifie le contrat structurel du code.
Le scenario runtime complet est documente dans BILAN_ITER13 §5.e.

Identification DECOUPLEE du probe : le polling UI ne touche QUE l'affichage
du run, pas l'identification des films. Les acquis iter4 sont preserves.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_TRAITEMENT_JS = Path(__file__).resolve().parent.parent / "web" / "dashboard" / "views" / "traitement.js"


class TestSequenceBackoff(unittest.TestCase):
    """Sequence 1s, 2s, 4s, 8s presente dans le JS."""

    def setUp(self) -> None:
        self.assertTrue(_TRAITEMENT_JS.is_file(), f"Fichier absent: {_TRAITEMENT_JS}")
        self.src = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_sequence_1_2_4_8_present(self) -> None:
        """Sequence exacte declaree dans POLL_BACKOFF_SEQUENCE_MS."""
        # Regex tolerante aux espaces / multilignes.
        match = re.search(
            r"POLL_BACKOFF_SEQUENCE_MS\s*=\s*\[\s*1000\s*,\s*2000\s*,\s*4000\s*,\s*8000\s*\]",
            self.src,
        )
        self.assertIsNotNone(
            match,
            "Sequence backoff [1000, 2000, 4000, 8000] absente dans traitement.js",
        )

    def test_plafond_8s_pas_depasse(self) -> None:
        """Aucune valeur > 8000 dans la sequence (eviterait reprise rapide)."""
        match = re.search(
            r"POLL_BACKOFF_SEQUENCE_MS\s*=\s*\[([^\]]*)\]",
            self.src,
        )
        self.assertIsNotNone(match)
        values = [int(v.strip()) for v in match.group(1).split(",") if v.strip()]
        self.assertTrue(
            all(v <= 8000 for v in values),
            f"Valeur > 8000ms dans sequence: {values}",
        )

    def test_max_attempts_defini(self) -> None:
        """POLL_BACKOFF_MAX_ATTEMPTS borne le compteur (pas infini)."""
        match = re.search(
            r"POLL_BACKOFF_MAX_ATTEMPTS\s*=\s*(\d+)",
            self.src,
        )
        self.assertIsNotNone(match)
        max_attempts = int(match.group(1))
        self.assertGreaterEqual(max_attempts, 4, "Min 4 pour parcourir la sequence")
        self.assertLessEqual(max_attempts, 20, "Borne souple raisonnable (<20)")


class TestSetTimeoutRecursifPasSetInterval(unittest.TestCase):
    """Ordonnancement recursif setTimeout (vs ancien setInterval fixe)."""

    def setUp(self) -> None:
        self.src = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_scheduleNextPoll_existe(self) -> None:
        """La fonction _scheduleNextPoll doit programmer le prochain tick."""
        self.assertIn("function _scheduleNextPoll", self.src)

    def test_pollTick_appelle_scheduleNextPoll(self) -> None:
        """_pollTick doit re-armer via _scheduleNextPoll (recursif setTimeout)."""
        # Capture le corps de _pollTick.
        match = re.search(
            r"async function _pollTick\s*\(\s*\)\s*\{(.+?)^}",
            self.src,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match, "_pollTick introuvable")
        body = match.group(1)
        self.assertIn(
            "_scheduleNextPoll",
            body,
            "_pollTick doit appeler _scheduleNextPoll pour re-armer",
        )


class TestResetAuSucces(unittest.TestCase):
    """Premier succes -> streak=0 + erreur effacee (signal visible)."""

    def setUp(self) -> None:
        self.src = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_succes_reset_streak(self) -> None:
        """_pollErrorStreak = 0 doit etre assigne au succes."""
        # Cherche la sequence de reset en cas de succes.
        match = re.search(
            r"if\s*\(\s*okStatus\s*&&\s*okInfo\s*\).*?_pollErrorStreak\s*=\s*0",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Le succes doit reset _pollErrorStreak a 0",
        )

    def test_succes_efface_lastError(self) -> None:
        """_pollLastError = null sur succes (pas de fantome d'erreur)."""
        match = re.search(
            r"if\s*\(\s*okStatus\s*&&\s*okInfo\s*\).*?_pollLastError\s*=\s*null",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Succes doit effacer _pollLastError",
        )


class TestEchecIncrementeStreak(unittest.TestCase):
    """Echec incremente le streak (en cappant a MAX_ATTEMPTS)."""

    def setUp(self) -> None:
        self.src = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_echec_incremente_avec_cap(self) -> None:
        """_pollErrorStreak = Math.min(_pollErrorStreak + 1, MAX_ATTEMPTS)."""
        pattern = re.compile(
            r"_pollErrorStreak\s*=\s*Math\.min\(\s*_pollErrorStreak\s*\+\s*1\s*,\s*POLL_BACKOFF_MAX_ATTEMPTS\s*\)"
        )
        self.assertIsNotNone(
            pattern.search(self.src),
            "Increment du streak doit etre cape par MAX_ATTEMPTS",
        )


class TestResetAuUnmount(unittest.TestCase):
    """Au unmount, reset complet du state polling (pas de fantome au remount)."""

    def setUp(self) -> None:
        self.src = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_unmount_reset_streak(self) -> None:
        """Quelque part dans le fichier, on doit voir _pollErrorStreak = 0 dans unmount."""
        # Pas de regex parfaite pour unmount, on cherche le reset complet du state.
        # Le code BILAN doit avoir _pollErrorStreak = 0; au unmount.
        # On verifie au moins 2 occurrences (une au _startPolling, une au unmount).
        occurrences = re.findall(r"_pollErrorStreak\s*=\s*0", self.src)
        self.assertGreaterEqual(
            len(occurrences),
            2,
            "Reset _pollErrorStreak doit apparaitre au moins 2 fois (startPolling + unmount)",
        )


class TestEffectivePollInterval(unittest.TestCase):
    """En mode degrade -> sequence backoff, sinon interval contextuel."""

    def setUp(self) -> None:
        self.src = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_effective_interval_degrade_utilise_sequence(self) -> None:
        match = re.search(
            r"function _effectivePollInterval\s*\(\s*\)\s*\{(.+?)^}",
            self.src,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match, "_effectivePollInterval introuvable")
        body = match.group(1)
        self.assertIn("POLL_BACKOFF_SEQUENCE_MS", body)
        # Mode degrade detectable via _pollErrorStreak >= 1
        self.assertIn("_pollErrorStreak", body)


class TestBadgeReconnexion(unittest.TestCase):
    """L'UI doit afficher un badge "Reconnexion" pour visibilite (memoire user)."""

    def test_badge_classe_css_traitement_run_backoff(self) -> None:
        """Le CSS doit contenir le style du badge backoff (selon BILAN §3.e)."""
        css = Path(__file__).resolve().parent.parent / "web" / "shared" / "components.css"
        self.assertTrue(css.is_file())
        css_src = css.read_text(encoding="utf-8")
        self.assertIn(
            "traitement-run-backoff",
            css_src,
            "Badge 'traitement-run-backoff' attendu dans components.css",
        )


if __name__ == "__main__":
    unittest.main()
