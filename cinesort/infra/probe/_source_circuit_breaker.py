r"""Circuit breaker par source reseau pour les probes (iter13 fix).

Cf BILAN_ITER13 section 3 mecanisme CIRCUIT_BREAKER :

Probleme : sans circuit breaker par source, un NAS / partage UNC injoignable
fait payer 30s de timeout PAR FICHIER. Sur 5000 films d'une biblio reseau qui
tombe en panne, c'est ~41h de hang inutile avant que l'utilisateur ne voie
le probleme.

Le `cinesort/infra/_circuit_breaker.py` existant cible les clients HTTP
(TMDb / Jellyfin / Plex / Radarr) et compte les echecs GLOBAUX par client.
Ici on a besoin d'un comportement DIFFERENT :
- granularite = SOURCE reseau (racine UNC \\host\share), pas le binaire probe
- la meme installation peut prober simultanement un disque local sain (C:\)
  et un partage SMB en panne (\\nas\films) : on ne doit pas bloquer le local
  parce que le NAS rame
- les chemins locaux (C:\, D:\) ne doivent JAMAIS etre mis en breaker (gain
  resilience nul, risque de masquer un bug differemment)

Strategie :
1. Pour chaque probe path, on extrait la "source" = racine UNC `\\host\share`
   (lowercase). Les paths locaux retournent None -> jamais en breaker.
2. On compte les echecs CONSECUTIFS par source. Au seuil `failure_threshold`
   (defaut 5), la source bascule en DEGRADED pendant `recovery_timeout`
   (defaut 300s = 5min).
3. Pendant DEGRADED : le breaker leve `SourceDegradedError` immediatement.
   Le caller convertit en "unavailable" (PAS score 0 invente, PAS ligne
   disparue : memoire utilisateur "degradation JAMAIS silencieuse").
4. Au premier succes, le compteur est reset (et le breaker se referme si
   le timeout s'est ecoule).

Identification DECOUPLEE du probe (acquis iter4 racine C) : meme quand la
source est DEGRADED, l'item reste identifiable+renommable via TMDb/NFO/
filename. Le breaker n'influe QUE sur le probe (lecture metadonnees).

Configurable via env CINESORT_PROBE_BREAKER_THRESHOLD / _RECOVERY_S
ou via parametres constructeur (pour tests).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional


class SourceDegradedError(Exception):
    """Leve quand la source reseau est marquee DEGRADED.

    Le caller doit catch et retourner un probe `unavailable` visible :
    PAS score invente, PAS ligne disparue (cf memoire user "degradation
    JAMAIS silencieuse").
    """


def extract_network_source(media_path: Path) -> Optional[str]:
    r"""Retourne la racine UNC \\host\share (lowercase) ou None si path local.

    Exemples :
        \\nas\films\... -> '\\nas\films'
        \\192.168.1.10\media\videos\... -> '\\192.168.1.10\media'
        C:\Users\... -> None (local, pas de breaker)
        relative\path -> None (pas de breaker)

    Les paths locaux retournent None : le breaker ne les surveille pas
    car (a) gain resilience nul, (b) risque de bloquer un disque sain.
    """
    try:
        path_str = str(media_path)
    except (TypeError, ValueError):
        return None
    if not path_str:
        return None
    # Normalise les slashes pour matcher \\host\share et //host/share
    normalized = path_str.replace("/", "\\")
    if not normalized.startswith("\\\\"):
        return None
    # Skip les 2 backslashes initiaux, split sur le reste
    parts = normalized[2:].split("\\", 2)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    host = parts[0].lower()
    share = parts[1].lower()
    return f"\\\\{host}\\{share}"


def _env_int(name: str, default: int) -> int:
    """Lit une var d'env entiere avec fallback silencieux sur erreur."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    """Lit une var d'env float avec fallback silencieux sur erreur."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class _SourceState:
    """Etat d'une source UNC (interne au breaker)."""

    __slots__ = ("failures", "open_until")

    def __init__(self) -> None:
        self.failures: int = 0
        self.open_until: float = 0.0


class SourceCircuitBreaker:
    """Circuit breaker par source UNC pour les probes media.

    Etats par source :
    - CLOSED (defaut) : probes passent. Echecs incrementent un compteur.
      Au seuil `failure_threshold`, transition DEGRADED.
    - DEGRADED : `check_or_raise` leve `SourceDegradedError` immediatement,
      sans tenter de probe. Apres `recovery_timeout` secondes, retour
      automatique en CLOSED (compteur reset).

    Les paths locaux (`extract_network_source` retourne None) ne sont
    JAMAIS surveilles : `check_or_raise` no-op, `record_failure` no-op,
    `record_success` no-op.

    Thread-safe : tous les acces a `_states` passent sous lock.

    Defaults raisonnables :
    - failure_threshold=5 : 5 echecs consecutifs avant degradation
    - recovery_timeout=300s = 5min : delai de reprise automatique

    Configurable via env :
    - CINESORT_PROBE_BREAKER_THRESHOLD
    - CINESORT_PROBE_BREAKER_RECOVERY_S
    """

    def __init__(
        self,
        *,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[float] = None,
    ) -> None:
        threshold = (
            failure_threshold if failure_threshold is not None else _env_int("CINESORT_PROBE_BREAKER_THRESHOLD", 5)
        )
        recovery = (
            recovery_timeout if recovery_timeout is not None else _env_float("CINESORT_PROBE_BREAKER_RECOVERY_S", 300.0)
        )
        if threshold < 1:
            raise ValueError(f"failure_threshold doit etre >= 1 (recu {threshold})")
        if recovery < 0:
            raise ValueError(f"recovery_timeout doit etre >= 0 (recu {recovery})")
        self._failure_threshold = int(threshold)
        self._recovery_timeout = float(recovery)
        self._lock = threading.Lock()
        self._states: Dict[str, _SourceState] = {}

    def check_or_raise(self, media_path: Path) -> None:
        """Leve `SourceDegradedError` si la source est en DEGRADED.

        No-op sur paths locaux (None source). Auto-reset apres expiration
        du timeout de recovery.
        """
        source = extract_network_source(media_path)
        if source is None:
            return
        with self._lock:
            state = self._states.get(source)
            if state is None:
                return
            now = time.time()
            if state.open_until == 0.0 or now >= state.open_until:
                # Auto-reset : timeout expire, on referme et on retente.
                if state.open_until and now >= state.open_until:
                    state.failures = 0
                    state.open_until = 0.0
                return
            remaining = state.open_until - now
            raise SourceDegradedError(
                f"Source reseau '{source}' degradee ({state.failures} echecs), retry dans {remaining:.0f}s"
            )

    def record_failure(self, media_path: Path) -> bool:
        """Incremente le compteur d'echecs pour la source du `media_path`.

        Retourne True si l'echec a fait basculer la source en DEGRADED
        (info utile pour logger / notifier l'UI une seule fois).
        No-op + retourne False sur paths locaux.
        """
        source = extract_network_source(media_path)
        if source is None:
            return False
        just_degraded = False
        with self._lock:
            state = self._states.get(source)
            if state is None:
                state = _SourceState()
                self._states[source] = state
            now = time.time()
            # Si on est encore dans la fenetre DEGRADED, on n'incremente pas
            # (autrement le compteur explose pendant les ~5min de fenetre).
            if state.open_until and now < state.open_until:
                return False
            state.failures += 1
            if state.failures >= self._failure_threshold:
                state.open_until = now + self._recovery_timeout
                just_degraded = True
        return just_degraded

    def record_success(self, media_path: Path) -> None:
        """Reset le compteur d'echecs pour la source au premier succes.

        Referme aussi la fenetre DEGRADED si elle etait active (le timeout
        peut etre raccourci par un succes premature : si on retente
        manuellement et que ca passe, pas de raison de bloquer).
        No-op sur paths locaux.
        """
        source = extract_network_source(media_path)
        if source is None:
            return
        with self._lock:
            state = self._states.get(source)
            if state is None:
                return
            state.failures = 0
            state.open_until = 0.0

    def is_degraded(self, media_path: Path) -> bool:
        """True si la source du path est actuellement en DEGRADED.

        Utile pour l'UI / les diagnostics, pas pour la decision de probe
        (preferer `check_or_raise` qui auto-reset apres expiration).
        """
        source = extract_network_source(media_path)
        if source is None:
            return False
        with self._lock:
            state = self._states.get(source)
            if state is None:
                return False
            return state.open_until > time.time()

    def reset(self, source: Optional[str] = None) -> None:
        """Reset l'etat d'une source specifique ou de toutes les sources.

        Utile pour les tests + reset manuel post-fix NAS.
        """
        with self._lock:
            if source is None:
                self._states.clear()
            else:
                self._states.pop(source, None)

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        """Snapshot non-destructif de l'etat (diagnostics / UI)."""
        now = time.time()
        out: Dict[str, Dict[str, float]] = {}
        with self._lock:
            for src, state in self._states.items():
                remaining = max(0.0, state.open_until - now) if state.open_until else 0.0
                out[src] = {
                    "failures": float(state.failures),
                    "degraded": float(1 if state.open_until > now else 0),
                    "remaining_s": remaining,
                }
        return out


# Singleton process-wide. Le probe est appele depuis plusieurs threads
# (ThreadPoolExecutor) + plusieurs entrees (REST handler, scan, recheck) :
# un singleton garantit un etat coherent sans repasser par les facades.
_default_breaker: Optional[SourceCircuitBreaker] = None
_default_breaker_lock = threading.Lock()


def get_default_breaker() -> SourceCircuitBreaker:
    """Retourne le breaker singleton (lazy init)."""
    global _default_breaker
    if _default_breaker is None:
        with _default_breaker_lock:
            if _default_breaker is None:
                _default_breaker = SourceCircuitBreaker()
    return _default_breaker


def reset_default_breaker() -> None:
    """Reset complet du breaker singleton (utilise par tests + reset manuel)."""
    global _default_breaker
    with _default_breaker_lock:
        _default_breaker = None
