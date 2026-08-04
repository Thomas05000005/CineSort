"""Audit ID-ROB-001 : helper mutualise Session HTTP avec retry/backoff.

Contient aussi la borne de taille des corps de reponse (issues #425, #753,
#798, #824, #423, #433, #539, #664) : voir `request_bounded` / `get_bounded`.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_RETRY_METHODS: frozenset[str] = frozenset(("GET", "HEAD", "OPTIONS", "PUT", "DELETE"))
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 20

# Borne par defaut d'un corps de reponse d'API JSON (10 Mo). C'est la valeur
# historiquement ecrite en dur dans les 18 copies du garde-fou anti-OOM des
# clients TMDb/OMDb/Jellyfin/Radarr.
DEFAULT_MAX_BODY_BYTES = 10_000_000

# Taille de lecture du flux. 64 Kio = le plafond de sur-lecture au-dela de la
# borne (on detecte le depassement au chunk qui le franchit, pas apres).
STREAM_CHUNK_BYTES = 64 * 1024


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


# ----------------------------------------------------------------------------
# Borne de taille des corps de reponse
# ----------------------------------------------------------------------------
# Issues #425 #753 #798 #824 #423 #433 #539 #664.
#
# Le motif historique, copie-colle 18 fois dans tmdb/omdb/jellyfin/radarr :
#
#     _body = getattr(resp, "content", b"")
#     if _body and len(_body) > 10_000_000:
#         raise ValueError("Response too large")
#     data = resp.json()
#
# ne protegeait de RIEN : `requests` a deja telecharge et alloue tout le corps
# en RAM au retour de `session.get()` (stream=False par defaut), et
# `resp.content` ne fait que rendre ce buffer. La borne n'evitait donc que le
# `json.loads`, jamais l'allocation — un serveur usurpe, un on-path, ou
# simplement une reponse aberrante pouvaient faire exploser la memoire du
# processus AVANT que la ligne de garde ne soit atteinte.
#
# Le present helper deplace la borne AU BON ENDROIT : requete en `stream=True`,
# refus immediat si `Content-Length` annonce deja trop, puis lecture par chunks
# avec un compteur et abandon (`close()` de la connexion) DES le franchissement.


class ResponseTooLargeError(ValueError):
    """Corps de reponse HTTP au-dela de la borne autorisee.

    Herite de `ValueError` **a dessein** : les 18 sites remplaces levaient
    `ValueError("Response too large")` et sont entoures de `except (...,
    ValueError, ...)` qui doivent continuer a l'attraper a l'identique. Le
    message conserve le fragment historique « Response too large » pour ne pas
    casser les traces/logs existants.
    """

    def __init__(self, *, limit: int, observed: Optional[int] = None, declared: bool = False) -> None:
        if observed is None:
            detail = f"limite {limit} octets"
        elif declared:
            detail = f"Content-Length annonce {observed} octets > limite {limit}"
        else:
            detail = f"plus de {observed} octets lus > limite {limit}"
        super().__init__(f"Response too large ({detail})")
        self.limit = int(limit)
        self.observed = observed
        self.declared = bool(declared)


def _safe_close(resp: Any) -> None:
    """Libere la connexion sous-jacente, best-effort (jamais bloquant)."""
    closer = getattr(resp, "close", None)
    if not callable(closer):
        return
    try:
        closer()
    except Exception:  # noqa: BLE001 — cleanup best-effort, ne doit jamais masquer l'erreur d'origine
        logger.debug("fermeture de la reponse HTTP impossible", exc_info=True)


def _declared_length(resp: Any) -> Optional[int]:
    """Content-Length annonce, ou None s'il est absent/illisible.

    Attention : sur une reponse compressee (`Content-Encoding: gzip`) cet
    en-tete decrit la taille COMPRESSEE. Il permet de refuser tot les cas
    evidents, mais il ne remplace pas le comptage a la lecture — d'ou les deux
    barrieres.
    """
    headers = getattr(resp, "headers", None)
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    try:
        raw = getter("Content-Length")
        return int(raw)
    except (TypeError, ValueError):
        return None


def _read_stream_bounded(resp: requests.Response, *, max_bytes: int, chunk_size: int) -> bytes:
    """Lit le flux de `resp` en abandonnant des que `max_bytes` est franchi."""
    chunks: list[bytes] = []
    total = 0
    stream: Iterator[bytes] = resp.iter_content(chunk_size)
    for chunk in stream:
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            # On coupe la connexion : le reste du corps ne sera JAMAIS
            # telecharge ni alloue. C'est tout l'objet du correctif.
            _safe_close(resp)
            raise ResponseTooLargeError(limit=max_bytes, observed=total)
        chunks.append(chunk)
    return b"".join(chunks)


def enforce_body_limit(resp: Any, *, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
    """Borne le corps de `resp` a `max_bytes`, puis le rend exploitable.

    Sur une vraie `requests.Response` (le seul cas en production) le corps est
    lu par chunks depuis le flux et l'exces est refuse AVANT allocation. Les
    octets lus sont ensuite reinjectes dans la reponse, si bien que
    `resp.content`, `resp.text` et `resp.json()` continuent de fonctionner
    normalement chez l'appelant — c'est ce qui permet de router les 18 sites
    sans reecrire leur parsing.

    Pour un objet qui n'est PAS une `requests.Response` (doubles de test), il
    n'y a pas de flux a lire : on se rabat sur la verification historique de
    `resp.content`. Cette branche est explicitement un repli de compatibilite,
    pas la protection.

    Leve `ResponseTooLargeError` (sous-classe de `ValueError`).
    """
    if max_bytes <= 0:
        raise ValueError(f"max_bytes doit etre > 0 (recu {max_bytes})")

    declared = _declared_length(resp)
    if declared is not None and declared > max_bytes:
        _safe_close(resp)
        raise ResponseTooLargeError(limit=max_bytes, observed=declared, declared=True)

    if isinstance(resp, requests.Response):
        body = _read_stream_bounded(resp, max_bytes=max_bytes, chunk_size=STREAM_CHUNK_BYTES)
        # Reinjection : `Response.content` rend `_content` tel quel des lors
        # que `_content_consumed` est vrai. Les appelants voient une reponse
        # ordinaire, deja materialisee et bornee.
        resp._content = body
        resp._content_consumed = True
        return

    already = getattr(resp, "content", None)
    if isinstance(already, (bytes, bytearray)) and len(already) > max_bytes:
        raise ResponseTooLargeError(limit=max_bytes, observed=len(already))


def request_bounded(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BODY_BYTES,
    **kwargs: Any,
) -> requests.Response:
    """Emet une requete dont le corps de reponse est borne A LA LECTURE.

    `stream=True` est impose (sauf override explicite) : sans lui, `requests`
    materialise tout le corps avant de rendre la main et la borne redeviendrait
    cosmetique.

    La methode est dispatchee via `getattr(session, method.lower())` — et non
    `session.request(...)` — pour rester compatible avec les tests existants
    qui patchent `client._session.get` / `.post` / `.delete`.
    """
    verb = str(method or "GET").strip().lower()
    sender = getattr(session, verb, None)
    if not callable(sender):
        raise ValueError(f"methode HTTP non supportee : {method!r}")
    kwargs.setdefault("stream", True)
    resp = sender(url, **kwargs)
    try:
        enforce_body_limit(resp, max_bytes=max_bytes)
    except BaseException:
        _safe_close(resp)
        raise
    return resp


def get_bounded(
    session: requests.Session,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BODY_BYTES,
    **kwargs: Any,
) -> requests.Response:
    """GET dont le corps de reponse est borne a `max_bytes` (cf `request_bounded`)."""
    return request_bounded(session, "GET", url, max_bytes=max_bytes, **kwargs)
