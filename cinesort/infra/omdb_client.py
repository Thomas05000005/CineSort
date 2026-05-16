"""OMDb API client — cross-check IMDb pour identification (Phase 6.2).

OMDb (Open Movie Database) expose les metadonnees IMDb via une API HTTP simple
avec authentification par cle. CineSort utilise OMDb comme **2eme avis** pour
valider les matches TMDb douteux (confidence < seuil configurable).

Quota free : 1000 req/jour, latence 200-700ms. Cache permanent local pour eviter
de remarteler l'API au scan suivant. TTL court (7 jours) car OMDb met a jour
ses metadonnees regulierement (rating IMDb evolue).

Strategie d'appel (cf cinesort/app/plan_support.py Phase 6.2) :
- Si confidence TMDb >= 90 : on saute OMDb (pas de doute, eviter l'appel)
- Si confidence TMDb < 90 ET on a un imdb_id : cross-check via find_by_imdb_id
  - Convergence (year + title match) -> +20 confidence
  - Convergence faible (year ±1) -> +5
  - Divergence -> -25 + warning omdb_disagree

Backward compat : echec gracieux total. Si la cle est invalide, l'API down,
le quota depasse, ou le cache illisible -> on retourne None sans erreur,
le pipeline plan continue normalement.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from cinesort.infra._circuit_breaker import CircuitBreaker, CircuitOpenError
from cinesort.infra._http_utils import make_session_with_retry

logger = logging.getLogger(__name__)


OMDB_API_BASE = "http://www.omdbapi.com/"

# TTL court : OMDb met a jour les ratings IMDb regulierement. 7 jours est un
# bon compromis (eviter de marteler l'API tout en captant les corrections
# communautaires).
_CACHE_TTL_S = 7 * 24 * 3600

# Rate limit cote client : 1 req/sec pour rester sous le quota 1000/jour
# en repartissant les appels. Sur un scan 5000 films avec 30% de cross-check,
# ca fait ~1500 req etalees sur 25 min, conforme au quota free.
_MIN_INTERVAL_S = 1.0

# Hard cap LRU sur le cache (eviter de derives RAM si l'utilisateur scanne
# 100k films sur plusieurs annees).
_CACHE_MAX_ENTRIES = 50_000


@dataclass(frozen=True)
class OmdbResult:
    """Reponse parsee OMDb.

    Attributes:
        imdb_id: IMDb tt-id (ex: 'tt3896198')
        title: titre canonique IMDb (anglais typiquement)
        year: annee de sortie
        runtime_min: duree en minutes (parsed depuis "136 min")
        genre: liste de genres en CSV
        imdb_rating: note IMDb 0-10 (parsed depuis "7.6")
        imdb_votes: nombre de votes (parsed depuis "828,114")
        awards: chaine awards (info supplementaire)
        plot: synopsis court
    """

    imdb_id: str
    title: str
    year: Optional[int]
    runtime_min: Optional[int]
    genre: str
    imdb_rating: Optional[float]
    imdb_votes: Optional[int]
    awards: str
    plot: str


def _parse_year(raw: Any) -> Optional[int]:
    """Parse l'annee OMDb (format '2017' ou '2017–' pour les series)."""
    if not raw:
        return None
    s = str(raw).strip().split("–")[0].split("-")[0].strip()
    try:
        y = int(s)
    except ValueError:
        return None
    if 1900 <= y <= 2100:
        return y
    return None


def _parse_runtime(raw: Any) -> Optional[int]:
    """Parse '136 min' -> 136. Retourne None si invalide."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s or s.upper() == "N/A":
        return None
    # Extract leading digits
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return None
    try:
        v = int(digits)
    except ValueError:
        return None
    return v if 1 <= v <= 600 else None


def _parse_rating(raw: Any) -> Optional[float]:
    """Parse '7.6' -> 7.6. None si invalide ou 'N/A'."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if 0.0 <= v <= 10.0 else None


def _parse_votes(raw: Any) -> Optional[int]:
    """Parse '828,114' -> 828114. None si invalide."""
    if not raw:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if not s or s.upper() == "N/A":
        return None
    try:
        v = int(s)
    except ValueError:
        return None
    return v if v >= 0 else None


def _parse_omdb_response(data: Dict[str, Any]) -> Optional[OmdbResult]:
    """Convertit la reponse JSON OMDb en OmdbResult, ou None si invalide."""
    if not isinstance(data, dict):
        return None
    if str(data.get("Response", "")).strip().lower() != "true":
        return None
    imdb_id = str(data.get("imdbID") or "").strip()
    title = str(data.get("Title") or "").strip()
    if not imdb_id or not title:
        return None
    return OmdbResult(
        imdb_id=imdb_id,
        title=title,
        year=_parse_year(data.get("Year")),
        runtime_min=_parse_runtime(data.get("Runtime")),
        genre=str(data.get("Genre") or ""),
        imdb_rating=_parse_rating(data.get("imdbRating")),
        imdb_votes=_parse_votes(data.get("imdbVotes")),
        awards=str(data.get("Awards") or ""),
        plot=str(data.get("Plot") or ""),
    )


class OmdbClient:
    """Client OMDb API + cache local JSON.

    Le cache est partage entre toutes les instances (load/save atomique).
    Rate limit : 1 req/sec en interne (token bucket simple).
    Circuit breaker : ouvert apres 5 echecs consecutifs, ferme apres 5 min.
    """

    def __init__(
        self,
        api_key: str,
        cache_path: Path,
        timeout_s: float = 10.0,
    ):
        self.api_key = (api_key or "").strip()
        self.cache_path = cache_path
        self.timeout_s = max(1.0, min(30.0, float(timeout_s or 10.0)))

        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = {}
        self._last_request_ts: float = 0.0

        self._session = make_session_with_retry(
            user_agent="CineSort/7.7 OmdbClient",
            max_attempts=3,
            backoff_base=0.5,
        )

        # Circuit breaker : 5 echecs consecutifs (plus strict que TMDb car
        # OMDb gere mal le rate limit excessif et bloque sur quota depasse).
        self._breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=300.0)

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    # --- Cache ---

    def _load_cache(self) -> None:
        try:
            if self.cache_path.exists():
                raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # Hard cap : ne charger que les MAX entries (plus recentes = fin)
                    if len(raw) > _CACHE_MAX_ENTRIES:
                        items = list(raw.items())[-_CACHE_MAX_ENTRIES:]
                        self._cache = dict(items)
                    else:
                        self._cache = raw
                else:
                    self._cache = {}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("omdb cache load failed: %s", exc)
            self._cache = {}

    def _save_cache_atomic(self) -> None:
        try:
            tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_path)
        except (OSError, PermissionError) as exc:
            logger.debug("omdb cache save warning: %s", exc)

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(key)
        if not isinstance(entry, dict):
            return None
        ts = entry.get("_ts")
        if not isinstance(ts, (int, float)):
            return None
        if (time.time() - ts) > _CACHE_TTL_S:
            return None
        return entry.get("data") if isinstance(entry.get("data"), dict) else None

    def _cache_set(self, key: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._cache[key] = {"_ts": time.time(), "data": data}
            if len(self._cache) > _CACHE_MAX_ENTRIES:
                # FIFO evict : pop first inserted
                first_key = next(iter(self._cache))
                self._cache.pop(first_key, None)

    # --- Rate limit ---

    def _rate_limit_wait(self) -> None:
        """Bloque jusqu'a ce que _MIN_INTERVAL_S se soit ecoule depuis le dernier appel."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_ts
            if elapsed < _MIN_INTERVAL_S:
                wait = _MIN_INTERVAL_S - elapsed
                # Release le lock pendant le sleep pour ne pas bloquer d'autres
                # appelants qui pourraient batcher.
                self._last_request_ts = now + wait
            else:
                self._last_request_ts = now
                wait = 0.0
        if wait > 0:
            time.sleep(wait)

    # --- HTTP ---

    def _http_get(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """GET /?{params}&apikey=X. Retourne le JSON parsed ou None sur echec."""
        if not self.api_key:
            return None
        full_params = dict(params)
        full_params["apikey"] = self.api_key

        self._rate_limit_wait()
        try:
            response = self._breaker.call(
                lambda: self._session.get(OMDB_API_BASE, params=full_params, timeout=self.timeout_s)
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, CircuitOpenError, ValueError, KeyError, TypeError) as exc:
            logger.debug("omdb HTTP error: %s", exc)
            return None
        if not isinstance(data, dict):
            return None
        return data

    # --- Public API ---

    def find_by_imdb_id(self, imdb_id: str) -> Optional[OmdbResult]:
        """Cherche un film par IMDb tt-id. Retourne OmdbResult ou None."""
        if not imdb_id:
            return None
        clean_id = str(imdb_id).strip().lower()
        if not clean_id.startswith("tt"):
            return None

        cache_key = f"imdb|{clean_id}"
        cached = self._cache_get(cache_key)
        if cached:
            return _parse_omdb_response(cached)

        data = self._http_get({"i": clean_id})
        if data is None:
            return None
        # Cache meme les reponses "Movie not found" (Response=False) pour eviter
        # de remarteler l'API avec le meme tt-id mort.
        self._cache_set(cache_key, data)
        with contextlib.suppress(OSError, PermissionError):
            self._save_cache_atomic()
        return _parse_omdb_response(data)

    def search_by_title(self, title: str, year: Optional[int] = None) -> Optional[OmdbResult]:
        """Cherche un film par titre + annee (optionnel). Retourne OmdbResult ou None.

        Note : OMDb retourne le meilleur match (mode `t=` = title direct), pas une
        liste. Si tu veux plusieurs matches, utiliser `s=` (search) — non implemente
        ici car non utilise par CineSort pour le cross-check.
        """
        if not title:
            return None
        clean_title = str(title).strip()
        if not clean_title:
            return None

        cache_key = f"title|{clean_title.lower()}|{year or ''}"
        cached = self._cache_get(cache_key)
        if cached:
            return _parse_omdb_response(cached)

        params: Dict[str, Any] = {"t": clean_title}
        if year and 1900 <= int(year) <= 2100:
            params["y"] = str(int(year))

        data = self._http_get(params)
        if data is None:
            return None
        self._cache_set(cache_key, data)
        with contextlib.suppress(OSError, PermissionError):
            self._save_cache_atomic()
        return _parse_omdb_response(data)

    def test_connection(self) -> Dict[str, Any]:
        """Teste la cle API. Retourne {ok, message, sample_title}.

        Utilise pour le bouton "Tester" dans les settings UI.
        """
        if not self.api_key:
            return {"ok": False, "message": "Cle API vide"}
        # Test avec un IMDb id connu (tt0111161 = The Shawshank Redemption)
        result = self.find_by_imdb_id("tt0111161")
        if not result:
            return {"ok": False, "message": "Aucune reponse OMDb (cle invalide ou API down)"}
        return {
            "ok": True,
            "message": f"Connexion OK. Reponse OMDb : {result.title} ({result.year})",
            "sample_title": result.title,
            "sample_year": result.year,
        }
