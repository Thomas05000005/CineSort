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

from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import HTTPError, Timeout

T = TypeVar("T")

# Statuts HTTP consideres comme "service en panne" : on ouvre le circuit dessus.
# - 5xx : erreur cote serveur (panne, surcharge, bug)
# - 429 : rate-limit (le serveur nous dit explicitement de ralentir)
# Les 4xx (hors 429) sont des erreurs du caller (mauvais token, mauvais id,
# requete malformee) : pas un signal pour fermer le robinet.
_SERVER_DOWN_STATUSES = frozenset({429})


class CircuitOpenError(Exception):
    """Leve quand le circuit est ouvert : appel non tente.

    Le caller peut catch pour fallback (typiquement : skip TMDb, accepter
    confidence reduite, et continuer le scan) plutot que rebloquer 5 min.
    """


def _is_server_down(exc: HTTPError) -> bool:
    """True si l'HTTPError correspond a un serveur en panne (5xx ou 429).

    Les 4xx (hors 429) signalent une erreur de la requete cote client
    (auth, id inexistant, params invalides) : le serveur fonctionne, c'est
    notre appel qui est mauvais — ne pas ouvrir le circuit dessus.
    """
    response = getattr(exc, "response", None)
    if response is None:
        # Pas de reponse attachee : on ne peut pas distinguer 4xx vs 5xx.
        # Par defaut on considere ca comme un echec serveur (cas suspect,
        # mieux vaut ouvrir le circuit que de masquer un probleme).
        return True
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        return True
    return status >= 500 or status in _SERVER_DOWN_STATUSES


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
        - Si `fn` leve une erreur "service down" (ConnectionError, Timeout,
          HTTPError 5xx/429) : incremente `_failures`, ouvre le circuit
          si le seuil est atteint, puis re-leve l'exception originale.
        - Si `fn` leve une autre `Exception` (ValueError, JSONDecodeError,
          KeyError, TypeError, HTTPError 4xx hors 429, ...) : remonte
          telle quelle SANS toucher au compteur. Ces erreurs sont
          applicatives (contrat client, parsing, mauvais identifiant) :
          le service distant n'est pas en panne, ouvrir le circuit
          bloquerait 5 min toute la chaine pour une raison invalide
          (cf audit C5 P1).
        - Si `fn` leve `BaseException` non-`Exception` (`KeyboardInterrupt`,
          `SystemExit`, `GeneratorExit`) : remonte tel quel SANS toucher
          au compteur. Ces exceptions signalent un arret administre du
          processus, pas un echec du service distant — incrementer
          `_failures` ouvrirait le circuit a tort apres un Ctrl+C
          repete (cf audit-bot 2026-05-16, issue #173).
        """
        with self._lock:
            now = time.time()
            if now < self._open_until:
                remaining = self._open_until - now
                raise CircuitOpenError(f"Circuit ouvert ({self._failures} echecs), retry dans {remaining:.0f}s")
        try:
            result = fn()
        except (ReqConnectionError, Timeout):
            self._record_failure()
            raise
        except HTTPError as exc:
            if _is_server_down(exc):
                self._record_failure()
            raise
        # Autres Exception (ValueError, JSONDecodeError, KeyError, TypeError,
        # HTTPError 4xx, ...) : erreurs applicatives, on ne touche pas au
        # compteur — le service distant repond, c'est le contrat client qui
        # est en cause.
        with self._lock:
            self._failures = 0
        return result

    def _record_failure(self) -> None:
        """Incremente le compteur d'echecs et ouvre le circuit si seuil atteint.

        Helper interne extrait pour partager la logique entre les differentes
        branches except.
        """
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._open_until = time.time() + self._recovery_timeout

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
