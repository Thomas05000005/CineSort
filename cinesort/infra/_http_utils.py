"""Audit ID-ROB-001 : helper mutualise Session HTTP avec retry/backoff."""

from __future__ import annotations

import logging
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_RETRY_METHODS: frozenset[str] = frozenset(("GET", "HEAD", "OPTIONS", "PUT", "DELETE", "POST"))
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 20


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
    """Session avec retry+backoff exponentiel automatique.

    Le backoff suit la formule urllib3 :
        sleep = backoff_base * (2 ** (n_previous_retries))
    avec respect prioritaire du header Retry-After si present (429/503).
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
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = user_agent
    return session
