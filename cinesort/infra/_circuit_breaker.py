"""Circuit breaker pour les clients HTTP (TMDb, Jellyfin, Plex, Radarr).

Cf issue #76 (audit-2026-05-12:a2b4) :

Probleme : sans circuit breaker, si un service externe (typiquement TMDb)
tombe en panne, chaque film d'un scan attend 3 retries × backoff exponentiel
(~3.5s perdues par film). Sur une bibliotheque de 5000 films, cela
represente ~5h de retry inutile avant que l'utilisateur ne voie l'echec.

Solution : compteur d'echecs consecutifs avec ouverture de circuit. Apres
N echecs (defaut 10), le circuit s'ouvre pour T secondes (defaut 300 =
5 min) : tous les appels suivants levent immediatement `CircuitOpenError`
sans tenter la requete. Un succes apres re-ouverture reset le compteur.

State local memoire (pas besoin de persister entre redemarrages : un
service down restera ouvert apres redemarrage, le breaker se rouvrira
juste apres le 1er retry).

Thread-safe : tous les `failures += 1` / `time.time()` lookups passent
sous lock pour eviter les races sur un client partage entre threads
(probe parallelisme, REST server ThreadingHTTPServer).
"""

from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Leve quand le circuit est ouvert : appel non tente.

    Le caller peut catch pour fallback (typiquement : skip TMDb, accepter
    confidence reduite, et continuer le scan) plutot que rebloquer 5 min.
    """


class CircuitBreaker:
    """Circuit breaker minimal a 2 etats (closed / open).

    - **closed** (defaut) : les appels passent. Chaque echec incremente
      `_failures`. Au seuil `failure_threshold`, transition vers `open`.
    - **open** : les appels levent `CircuitOpenError` immediatement,
      sans tenter la requete. Apres `recovery_timeout` secondes,
      retour automatique a `closed` (et reset du compteur).

    Pas d'etat `half_open` (sample-then-decide) pour rester simple : le
    1er appel apres `recovery_timeout` est tente comme n'importe quel
    autre appel. S'il echoue, le compteur recommence des le seuil-1.

    Usage :
        breaker = CircuitBreaker(failure_threshold=10, recovery_timeout=300)
        try:
            result = breaker.call(lambda: session.get(url, timeout=10))
        except CircuitOpenError:
            # service down depuis 10 echecs, on skip pendant 5 min
            return None
        except RequestException:
            # echec classique, breaker l'a deja compte
            raise
    """

    def __init__(self, *, failure_threshold: int = 10, recovery_timeout: float = 300.0) -> None:
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold doit etre >= 1 (recu {failure_threshold})")
        if recovery_timeout < 0:
            raise ValueError(f"recovery_timeout doit etre >= 0 (recu {recovery_timeout})")
        self._failure_threshold = int(failure_threshold)
        self._recovery_timeout = float(recovery_timeout)
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0

    def call(self, fn: Callable[[], T]) -> T:
        """Execute `fn()` sous protection du breaker.

        - Si circuit ouvert : leve `CircuitOpenError` sans appeler `fn`.
        - Si `fn` reussit : reset `_failures` a 0 et retourne le resultat.
        - Si `fn` echoue : incremente `_failures`, ouvre le circuit si
          le seuil est atteint, puis re-leve l'exception originale.
        """
        with self._lock:
            now = time.time()
            if now < self._open_until:
                remaining = self._open_until - now
                raise CircuitOpenError(f"Circuit ouvert ({self._failures} echecs), retry dans {remaining:.0f}s")
        try:
            result = fn()
        except BaseException:
            with self._lock:
                self._failures += 1
                if self._failures >= self._failure_threshold:
                    self._open_until = time.time() + self._recovery_timeout
            raise
        with self._lock:
            self._failures = 0
        return result

    def reset(self) -> None:
        """Force la fermeture du circuit (utile pour les tests + reconfig manuelle)."""
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        """True si le circuit est actuellement ouvert (appels bloques)."""
        with self._lock:
            return time.time() < self._open_until

    @property
    def failures(self) -> int:
        """Nombre d'echecs consecutifs depuis le dernier succes."""
        with self._lock:
            return self._failures
