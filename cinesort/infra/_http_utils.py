"""Audit ID-ROB-001 : helper mutualise Session HTTP avec retry/backoff.

Porte aussi la garde SSRF au moment de la CONNEXION (issue #624) : voir
`SsrfGuardHTTPAdapter`.
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Iterable

import requests
import urllib3.connection
import urllib3.connectionpool
import urllib3.poolmanager
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cinesort.infra.network_utils import BlockedAddressError, blocked_ip_reason

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_RETRY_METHODS: frozenset[str] = frozenset(("GET", "HEAD", "OPTIONS", "PUT", "DELETE"))
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 20


# ---------------------------------------------------------------------------
# Issue #624 — garde SSRF au moment de la connexion (anti DNS rebinding)
# ---------------------------------------------------------------------------
# `is_safe_external_url` valide l'URL a la CONSTRUCTION du client. Meme en
# resolvant le DNS a ce moment-la, il reste un TOCTOU : l'attaquant peut publier
# un enregistrement TTL=0 qui renvoie une IP publique pendant la validation puis
# 169.254.169.254 quand la requete part reellement.
#
# La seule verification qui ne peut pas etre contournee par un changement de DNS
# est celle faite sur la socket DEJA CONNECTEE. On l'accroche a `_new_conn()`,
# qui retourne la socket TCP brute : le controle a donc lieu AVANT le handshake
# TLS et AVANT l'emission du moindre octet applicatif (donc avant tout header
# d'authentification).
#
# Ce qui reste hors de portee, honnetement :
# - les connexions faites SANS passer par `make_session_with_retry` (appel direct
#   a `requests.get`, autre bibliotheque HTTP) ;
# - les connexions via proxy HTTP : la socket est alors ouverte vers le PROXY,
#   c'est donc l'adresse du proxy qui est validee, pas la destination finale —
#   celle-ci est choisie par le proxy et nous echappe par construction ;
# - une redirection suivie par requests refait un `_new_conn()`, donc elle EST
#   couverte ; mais un serveur qui repond 200 tout en etant lui-meme un relais
#   ne l'est pas (aucune garde reseau ne peut le voir).


def _assert_peer_allowed(sock: socket.socket, host: str) -> None:
    """Refuse la socket si son pair est une adresse interdite (link-local/metadata).

    Ferme la socket avant de lever : ne jamais rendre au pool une connexion
    ouverte vers une cible refusee.
    """
    try:
        peer = sock.getpeername()
    except OSError as exc:
        # Fail-closed : si on ne peut pas savoir a qui on parle, on ne parle pas.
        sock.close()
        raise BlockedAddressError(f"Connexion refusee vers '{host}' : adresse distante illisible ({exc})") from exc
    address = peer[0] if isinstance(peer, tuple) and peer else peer
    reason = blocked_ip_reason(address)
    if reason:
        sock.close()
        logger.warning("http: connexion refusee vers '%s' -> %s", host, reason)
        raise BlockedAddressError(f"Connexion refusee vers '{host}' : {reason}")


class _PeerGuardMixin:
    """Valide l'adresse reellement jointe (cf issue #624).

    Une SEULE implementation, partagee par HTTP et HTTPS : en HTTPS `_new_conn`
    retourne la socket TCP brute, donc le controle a lieu avant le handshake TLS.
    """

    def _new_conn(self) -> socket.socket:
        sock = super()._new_conn()  # type: ignore[misc]
        _assert_peer_allowed(sock, str(self.host))  # type: ignore[attr-defined]
        return sock


class _SsrfGuardHTTPConnection(_PeerGuardMixin, urllib3.connection.HTTPConnection):
    """HTTPConnection gardee."""


class _SsrfGuardHTTPSConnection(_PeerGuardMixin, urllib3.connection.HTTPSConnection):
    """HTTPSConnection gardee."""


class _SsrfGuardHTTPConnectionPool(urllib3.connectionpool.HTTPConnectionPool):
    ConnectionCls = _SsrfGuardHTTPConnection


class _SsrfGuardHTTPSConnectionPool(urllib3.connectionpool.HTTPSConnectionPool):
    ConnectionCls = _SsrfGuardHTTPSConnection


class SsrfGuardPoolManager(urllib3.poolmanager.PoolManager):
    """PoolManager dont les pools construisent des connexions gardees."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # urllib3 lit `self.pool_classes_by_scheme` (attribut d'INSTANCE, pose
        # par PoolManager.__init__ precisement pour permettre cette surcharge).
        self.pool_classes_by_scheme = {
            "http": _SsrfGuardHTTPConnectionPool,
            "https": _SsrfGuardHTTPSConnectionPool,
        }


class SsrfGuardHTTPAdapter(HTTPAdapter):
    """HTTPAdapter dont chaque connexion est validee apres resolution DNS.

    C'est ce point de controle — et non `is_safe_external_url` — qui ferme la
    fenetre de DNS rebinding pour les requetes emises via
    `make_session_with_retry`.
    """

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> None:
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block
        self.poolmanager = SsrfGuardPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def make_session_with_retry(
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    status_forcelist: Iterable[int] = DEFAULT_RETRY_STATUS_CODES,
    methods: Iterable[str] = DEFAULT_RETRY_METHODS,
    user_agent: str = "CineSort/7.6",
    pool_connections: int = DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = DEFAULT_POOL_MAXSIZE,
) -> requests.Session:
    """Session avec retry+backoff exponentiel automatique et garde SSRF.

    Le backoff suit la formule urllib3 :
        sleep = backoff_base * (2 ** (n_previous_retries))
    avec respect prioritaire du header Retry-After si present (429/503).

    Issue #624 : l'adaptateur monte est un `SsrfGuardHTTPAdapter`, qui refuse
    toute connexion dont l'adresse resolue est link-local ou une IP de metadata
    cloud — verification faite sur la socket connectee, donc immunisee au
    changement de DNS entre la validation de l'URL et la requete.
    """
    retry = Retry(
        total=max_attempts,
        connect=max_attempts,
        read=max_attempts,
        status=max_attempts,
        backoff_factor=backoff_base,
        status_forcelist=tuple(status_forcelist),
        allowed_methods=frozenset(methods),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = SsrfGuardHTTPAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = user_agent
    return session
