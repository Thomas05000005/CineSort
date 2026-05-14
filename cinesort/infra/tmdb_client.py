from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from cinesort.infra._http_utils import make_session_with_retry
import contextlib

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"
_DEBUG_ENV_VALUES = {"1", "true", "yes", "on", "debug"}

# Cf issue #75 : hard cap LRU sur le cache TMDb. ~1 KB par entree (movie detail
# moyen) → 100k entries = ~100 MB max RAM. Au-dela on evict la plus ancienne
# entree non-acedee (popitem(last=False)). Evite la derive memoire sur grosses
# bibliotheques (50k+ films + recherches multi-fuzzy → 200+ MB sans cap).
_TMDB_CACHE_MAX_ENTRIES = 100_000

# V5-03 polish v7.7.0 (R5-STRESS-4) : TTL du cache TMDb configurable.
# Defaut 30 jours = bon compromis : suffisant pour eviter de marteler l'API
# quand on rescanne souvent, mais assez court pour rattraper les corrections
# de titre/annee que TMDb applique (films mal etiquetes corriges par la
# communaute).
DEFAULT_CACHE_TTL_DAYS = 30
MIN_CACHE_TTL_DAYS = 1
MAX_CACHE_TTL_DAYS = 365
_CACHE_TTL_S = DEFAULT_CACHE_TTL_DAYS * 24 * 3600  # legacy (lookup deterministes)

# D-5 audit QA 20260429 : les resultats de recherche (search) sont
# non-deterministes : popularite, vote_count, vote_average evoluent et
# de nouveaux films sortent qui peuvent changer le ranking. TTL plus court.
# V5-03 : ce TTL est fonction du TTL principal (1/4 de TTL principal pour
# garder la proportion historique 30j/7j).
_SEARCH_CACHE_TTL_S = 7 * 24 * 3600  # 7 jours pour les search:* / tv_search:*

# Prefixes de cle qui correspondent a des lookups deterministes (TTL long).
# Les autres (search, tv_search) utilisent _SEARCH_CACHE_TTL_S.
_DETERMINISTIC_PREFIXES = ("movie|", "find_tmdb|", "find_imdb|", "tv_ep:")


def _clamp_ttl_days(ttl_days: int | float | None) -> int:
    """Clamp ttl_days dans [MIN_CACHE_TTL_DAYS, MAX_CACHE_TTL_DAYS].

    V5-03 polish v7.7.0 : helper centralise pour valider la valeur du
    setting `tmdb_cache_ttl_days`. Retourne DEFAULT_CACHE_TTL_DAYS si la
    valeur est invalide (None, NaN, type incorrect).
    """
    try:
        value = int(ttl_days) if ttl_days is not None else DEFAULT_CACHE_TTL_DAYS
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL_DAYS
    return max(MIN_CACHE_TTL_DAYS, min(MAX_CACHE_TTL_DAYS, value))


def _ttl_for_key(key: str, ttl_days: int | None = None) -> int:
    """Retourne le TTL applicable a une cle de cache TMDb.

    D-5 : 7 jours pour search/* (resultats non-deterministes), 30 jours
    pour les lookups deterministes (movie/{id}, find/{tmdb_id}, etc).

    V5-03 polish v7.7.0 : si ttl_days est fourni (>0), on l'utilise comme
    TTL pour les lookups deterministes. Pour les recherches non-det, on
    garde un quart de ce TTL (proportion historique 30j/7j).
    """
    if ttl_days is not None and ttl_days > 0:
        long_ttl = ttl_days * 24 * 3600
        short_ttl = max(24 * 3600, long_ttl // 4)  # min 1 jour pour search
    else:
        long_ttl = _CACHE_TTL_S
        short_ttl = _SEARCH_CACHE_TTL_S
    if key.startswith(_DETERMINISTIC_PREFIXES):
        return long_ttl
    # Toutes les autres cles (search|..., tv_search:..., autres) ont TTL court
    return short_ttl


@dataclass(frozen=True)
class TmdbTvResult:
    id: int
    name: str
    first_air_date_year: Optional[int]
    original_name: Optional[str]
    popularity: Optional[float]
    vote_count: Optional[int]
    poster_path: Optional[str] = None


@dataclass(frozen=True)
class TmdbResult:
    id: int
    title: str
    year: Optional[int]
    original_title: Optional[str]
    popularity: Optional[float]
    vote_count: Optional[int]
    vote_average: Optional[float]
    poster_path: Optional[str] = None


class TmdbClient:
    """
    Client TMDb minimal + cache local JSON.
    - Le cache est local PC (pas sur le NAS) pour eviter WinError 5 + accelerer.
    - On ne log jamais la cle API en clair.
    """

    def __init__(
        self,
        api_key: str,
        cache_path: Path,
        timeout_s: float = 10.0,
        *,
        cache_ttl_days: int | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.cache_path = cache_path
        self.timeout_s = max(1.0, min(60.0, float(timeout_s or 10.0)))
        # V5-03 polish v7.7.0 : TTL configurable. None -> defaut historique.
        self.cache_ttl_days = _clamp_ttl_days(cache_ttl_days) if cache_ttl_days is not None else None
        self._lock = threading.Lock()
        # Cf issue #75 : OrderedDict pour LRU eviction. Comportement Dict
        # identique pour le code existant (get/set/contains/iter).
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._dirty = False
        self._last_save_ts = 0.0

        # V2-09 (audit ID-ROB-001) : Session avec retry automatique sur 5xx + 429
        # et backoff exponentiel. Respecte Retry-After (rate-limiting TMDb).
        self._session = make_session_with_retry(
            user_agent="CineSort/7.6 TmdbClient",
            max_attempts=3,
            backoff_base=0.5,
        )

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    def _debug(self, message: str) -> None:
        if str(os.environ.get("CINESORT_DEBUG", "")).strip().lower() not in _DEBUG_ENV_VALUES:
            return
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            debug_path = self.cache_path.parent / "debug_tmdb.log"
            with open(debug_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
        except (OSError, PermissionError):
            return

    def _load_cache(self) -> None:
        try:
            if self.cache_path.exists():
                raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
                # OrderedDict preserve l'ordre d'insertion JSON. Si le cache
                # depasse MAX_ENTRIES (cache historique pre-#75), on garde
                # les MAX_ENTRIES dernieres entrees ecrites (heuristique :
                # plus recentes = plus probables d'etre reaccedees).
                if isinstance(raw, dict):
                    if len(raw) > _TMDB_CACHE_MAX_ENTRIES:
                        items = list(raw.items())[-_TMDB_CACHE_MAX_ENTRIES:]
                        self._cache = OrderedDict(items)
                        self._debug(f"cache pruned to {_TMDB_CACHE_MAX_ENTRIES} entries (was {len(raw)})")
                    else:
                        self._cache = OrderedDict(raw)
                else:
                    self._cache = OrderedDict()
            else:
                self._cache = OrderedDict()
        except (OSError, PermissionError, json.JSONDecodeError, ValueError) as exc:
            # Cache corrompu -> on repart propre.
            self._cache = OrderedDict()
            self._debug(f"cache load warning path={self.cache_path} error={exc}")

    def _cache_get(self, key: str) -> Any:
        """Lit une entree du cache avec verification TTL.

        H1 : les entrees stockees en nouveau format {"_cached_at": ts, "value": ...}
        sont verifiees contre _CACHE_TTL_S. Si expirees -> retourne None et la
        cle est supprimee du cache en memoire pour forcer un re-fetch.
        Les entrees en ancien format (valeur directe, sans wrapper) sont
        considerees fraiches en attendant leur prochaine ecriture.

        V5-03 polish v7.7.0 (R5-STRESS-4) : utilise self.cache_ttl_days si
        configure, sinon TTL par defaut. L'entree expiree est juste detachee
        en memoire (le caller peut la recuperer via _cache_get_stale en
        fallback si l'API echoue).
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            # Nouveau format avec TTL
            if isinstance(entry, dict) and "_cached_at" in entry and "value" in entry:
                try:
                    cached_at = float(entry.get("_cached_at") or 0.0)
                except (TypeError, ValueError):
                    cached_at = 0.0
                # D-5 + V5-03 : TTL adapte selon type de cle, et configurable.
                ttl = _ttl_for_key(key, self.cache_ttl_days)
                if time.time() - cached_at > ttl:
                    # Expire : retire de la memoire pour forcer le re-fetch.
                    # On ne persiste pas la suppression ici : si l'API echoue,
                    # _cache_get_stale (lu depuis disque) peut servir de fallback.
                    self._cache.pop(key, None)
                    self._dirty = True
                    return None
                return entry.get("value")
            # Ancien format : valeur directe, considered fresh
            return entry

    def _cache_get_stale(self, key: str) -> Any:
        """Lit une entree du cache SANS verification TTL.

        V5-03 polish v7.7.0 : utilise comme fallback graceful quand l'API
        TMDb echoue. Retourne la valeur cachee meme si elle est expiree
        (mieux qu'aucun resultat). Relit depuis disque car _cache_get a
        peut-etre deja retire l'entree de la memoire.
        """
        with self._lock:
            entry = self._cache.get(key)
        # Si l'entree a ete purgee de la memoire par _cache_get, on tente de
        # la relire depuis le disque (fichier).
        if entry is None:
            try:
                if self.cache_path.exists():
                    raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
                    entry = raw.get(key)
            except (OSError, PermissionError, json.JSONDecodeError, ValueError):
                return None
        if entry is None:
            return None
        if isinstance(entry, dict) and "_cached_at" in entry and "value" in entry:
            return entry.get("value")
        return entry

    def _cache_set(self, key: str, value: Any) -> None:
        """Ecrit une entree avec timestamp pour le TTL (H1).

        Cf issue #75 : LRU eviction si on depasse _TMDB_CACHE_MAX_ENTRIES.
        move_to_end marque l'entree comme la plus recente. popitem(last=False)
        retire la plus ancienne.
        """
        with self._lock:
            self._cache[key] = {"_cached_at": time.time(), "value": value}
            self._cache.move_to_end(key)
            while len(self._cache) > _TMDB_CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)
            self._dirty = True

    def _save_cache_atomic(self, *, force: bool = False) -> None:
        """
        Sauvegarde atomique (tmp -> rename) pour eviter les fichiers partiels.
        """
        with self._lock:
            if not self._dirty:
                return
            now = time.time()
            # throttle: max 1 save / 2s (except explicit flush)
            if (not force) and (now - self._last_save_ts < 2.0):
                return
            self._last_save_ts = now

            tmp = self.cache_path.with_suffix(".tmp")
            # PERF-6 (v7.8.0) : drop indent=2 + separators compacts.
            # Avant : cache 20MB x 750 writes par scan x indent = 15GB IO + 112s CPU.
            # Apres : ~50% taille, ~30% temps serialize. Format toujours valide JSON.
            tmp.write_text(
                json.dumps(self._cache, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(tmp, self.cache_path)
            self._dirty = False

    def flush(self) -> None:
        try:
            self._save_cache_atomic(force=True)
        except (OSError, PermissionError) as exc:
            self._debug(f"cache flush warning path={self.cache_path} error={exc}")

    # ---------------------------
    # API calls
    # ---------------------------
    def validate_key(self) -> Tuple[bool, str]:
        """
        TMDb: endpoint "Authentication" (validate key).
        GET /authentication?api_key=...
        """
        if not self.api_key:
            return False, "Cle TMDb vide."

        url = f"{TMDB_API_BASE}/authentication"
        _t0 = time.monotonic()
        try:
            r = self._session.get(url, params={"api_key": self.api_key}, timeout=self.timeout_s)
            logger.debug("TMDb: GET /authentication -> %d (%.1fs)", r.status_code, time.monotonic() - _t0)
        except (requests.RequestException, ConnectionError, TimeoutError) as e:
            logger.warning("TMDb: echec validate_key — %s", e)
            return False, f"Erreur reseau: {e}"

        try:
            data = r.json()
        except (KeyError, TypeError, ValueError):
            data = {}

        if r.status_code == 200:
            # Souvent: {"success": True, "status_code": 1, "status_message": "Success."}
            if isinstance(data, dict) and data.get("success") is True:
                return True, "OK (cle valide)."
            # Certains retours ne mettent pas success
            return True, "OK (HTTP 200)."

        msg = None
        if isinstance(data, dict):
            # TMDb retourne `status_message` en lowercase ; le fallback .upper()
            # precedent etait mort (le or short-circuit sur la 1re cle).
            msg = data.get("status_message")
        return False, f"HTTP {r.status_code}: {msg or r.text[:200]}"

    def search_movie(
        self, query: str, year: Optional[int] = None, *, language: str = "fr-FR", max_results: int = 8
    ) -> List[TmdbResult]:
        """
        TMDb: GET /search/movie?query=...&year=...
        Cache par (query_norm, year, language).
        """
        q = (query or "").strip()
        if not q:
            return []

        # Cle cache
        q_norm = " ".join(q.lower().split())
        cache_key = f"search|{language}|{q_norm}|{year or ''}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return [TmdbResult(**x) for x in cached]

        url = f"{TMDB_API_BASE}/search/movie"
        params: Dict[str, Any] = {
            "api_key": self.api_key,
            "query": q,
            "include_adult": "false",
            "language": language,
        }
        if year:
            params["year"] = int(year)

        _t0 = time.monotonic()
        try:
            r = self._session.get(url, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            logger.debug(
                "TMDb: search '%s' (%s) -> %d resultats (%.1fs)",
                q_norm,
                year or "?",
                len(data.get("results") or []),
                time.monotonic() - _t0,
            )
        except (requests.RequestException, KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.debug("TMDb: echec search '%s' (%s) — %s", q_norm, year or "?", exc)
            self._debug(f"search_movie warning query={q_norm} year={year} error={exc}")
            # V5-03 polish v7.7.0 : fallback graceful — utiliser cache meme expire
            stale = self._cache_get_stale(cache_key)
            if isinstance(stale, list):
                logger.info(
                    "TMDb: search '%s' (%s) — fallback cache expire (%d items)", q_norm, year or "?", len(stale)
                )
                return [TmdbResult(**x) for x in stale]
            return []
        if not isinstance(data, dict):
            self._debug(f"search_movie warning query={q_norm} year={year} error=payload_non_dict")
            return []

        results: List[TmdbResult] = []
        for it in (data.get("results") or [])[:max_results]:
            if not isinstance(it, dict):
                continue
            title = it.get("title") or it.get("name") or ""
            release = it.get("release_date") or ""
            y = None
            if isinstance(release, str) and len(release) >= 4 and release[:4].isdigit():
                y = int(release[:4])
            try:
                item_id = int(it.get("id") or 0)
            except (TypeError, ValueError):
                item_id = 0
            results.append(
                TmdbResult(
                    id=item_id,
                    title=title,
                    year=y,
                    original_title=it.get("original_title"),
                    popularity=it.get("popularity"),
                    vote_count=it.get("vote_count"),
                    vote_average=it.get("vote_average"),
                    poster_path=it.get("poster_path"),
                )
            )

        self._cache_set(cache_key, [r.__dict__ for r in results])
        # best-effort save
        try:
            self._save_cache_atomic()
        except (OSError, PermissionError) as exc:
            self._debug(f"search_movie cache save warning key={cache_key} error={exc}")
        return results

    def _get_movie_detail_cached(self, movie_id: int) -> Optional[Dict[str, Any]]:
        """Recupere le detail d'un film TMDb (cache local). Stocke poster + collection."""
        mid = int(movie_id or 0)
        if mid <= 0:
            return None

        cache_key = f"movie|{mid}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, dict):
            return cached

        url = f"{TMDB_API_BASE}/movie/{mid}"
        params = {
            "api_key": self.api_key,
            "language": "fr-FR",
        }
        _t0 = time.monotonic()
        try:
            r = self._session.get(url, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            logger.debug("TMDb: GET /movie/%d -> %d (%.1fs)", mid, r.status_code, time.monotonic() - _t0)
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            logger.debug("TMDb: echec /movie/%d — %s", mid, exc)
            self._debug(f"_get_movie_detail_cached warning movie_id={mid} error={exc}")
            # V5-03 polish v7.7.0 : fallback graceful — utiliser cache meme expire
            stale = self._cache_get_stale(cache_key)
            if isinstance(stale, dict):
                logger.info("TMDb: /movie/%d — fallback cache expire", mid)
                return stale
            return None
        if not isinstance(data, dict):
            self._debug(f"_get_movie_detail_cached warning movie_id={mid} error=payload_non_dict")
            return None

        # Extraire poster_path + belongs_to_collection + metadata perceptuelle
        poster_path = data.get("poster_path")
        collection = data.get("belongs_to_collection")
        cache_entry: Dict[str, Any] = {"poster_path": poster_path or ""}
        if isinstance(collection, dict):
            cache_entry["collection_id"] = int(collection.get("id") or 0) or None
            cache_entry["collection_name"] = str(collection.get("name") or "").strip() or None
        else:
            cache_entry["collection_id"] = None
            cache_entry["collection_name"] = None
        # Champs pour l'analyse perceptuelle (backward compatible via .get())
        cache_entry["genres"] = [str(g.get("name", "")) for g in (data.get("genres") or []) if isinstance(g, dict)]
        cache_entry["budget"] = int(data.get("budget") or 0)
        cache_entry["production_companies"] = [
            str(c.get("name", "")) for c in (data.get("production_companies") or []) if isinstance(c, dict)
        ]

        self._cache_set(cache_key, cache_entry)
        try:
            self._save_cache_atomic()
        except (OSError, PermissionError) as exc:
            self._debug(f"movie detail cache save warning movie_id={mid} error={exc}")
        return cache_entry

    def get_movie_poster_path(self, movie_id: int) -> Optional[str]:
        """Retourne poster_path pour un film TMDb (cache local)."""
        detail = self._get_movie_detail_cached(movie_id)
        if not detail:
            return None
        poster = detail.get("poster_path")
        return str(poster) if poster else None

    def get_movie_collection(self, movie_id: int) -> Tuple[Optional[int], Optional[str]]:
        """Retourne (collection_id, collection_name) depuis TMDb ou cache. None si pas de collection."""
        detail = self._get_movie_detail_cached(movie_id)
        if not detail:
            return None, None
        cid = detail.get("collection_id")
        cname = detail.get("collection_name")
        return (int(cid) if cid else None, str(cname) if cname else None)

    def get_movie_metadata_for_perceptual(self, movie_id: int) -> Optional[Dict[str, Any]]:
        """Retourne genres, budget, production_companies pour l'analyse perceptuelle."""
        detail = self._get_movie_detail_cached(movie_id)
        if not detail:
            return None
        return {
            "genres": list(detail.get("genres") or []),
            "budget": int(detail.get("budget") or 0),
            "production_companies": list(detail.get("production_companies") or []),
        }

    def get_movie_poster_thumb_url(self, movie_id: int, size: str = "w92") -> Optional[str]:
        poster = self.get_movie_poster_path(movie_id)
        if not poster:
            return None
        p = str(poster).strip()
        if not p:
            return None
        if not p.startswith("/"):
            p = "/" + p
        return f"https://image.tmdb.org/t/p/{size}{p}"

    # --- Lookup par ID externe (IMDb → TMDb) ---

    def find_by_tmdb_id(self, tmdb_id: int | str) -> Optional[TmdbResult]:
        """Lookup direct TMDb via /movie/{id}. Cache local.

        P1.1.c : symétrique à find_by_imdb_id. Permet de cross-checker un NFO
        qui contient <tmdbid>27205</tmdbid> contre le titre officiel TMDb
        (détection NFO pollué/copié-collé).
        """
        try:
            mid = int(str(tmdb_id).strip())
        except (TypeError, ValueError):
            return None
        if mid <= 0:
            return None

        cache_key = f"find_tmdb|{mid}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            if not cached:
                return None
            if isinstance(cached, dict):
                try:
                    return TmdbResult(**cached)
                except TypeError:
                    pass

        url = f"{TMDB_API_BASE}/movie/{mid}"
        params = {"api_key": self.api_key, "language": "fr-FR"}
        _t0 = time.monotonic()
        try:
            r = self._session.get(url, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            logger.debug("TMDb: find_by_tmdb_id %d -> %d (%.1fs)", mid, r.status_code, time.monotonic() - _t0)
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            logger.debug("TMDb: echec find_by_tmdb_id %d — %s", mid, exc)
            self._debug(f"find_by_tmdb_id warning tmdb_id={mid} error={exc}")
            return None

        if not isinstance(data, dict) or not data.get("id"):
            self._cache_set(cache_key, "")
            with contextlib.suppress(OSError, PermissionError):
                self._save_cache_atomic()
            return None

        release = data.get("release_date") or ""
        y = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else None
        result = TmdbResult(
            id=int(data.get("id") or 0),
            title=str(data.get("title") or ""),
            year=y,
            original_title=data.get("original_title"),
            popularity=data.get("popularity"),
            vote_count=data.get("vote_count"),
            vote_average=data.get("vote_average"),
            poster_path=data.get("poster_path"),
        )
        self._cache_set(cache_key, result.__dict__)
        with contextlib.suppress(OSError, PermissionError):
            self._save_cache_atomic()
        logger.info("TMDb: find_by_tmdb_id %d -> '%s' (%s)", mid, result.title, result.year)
        return result

    def find_by_imdb_id(self, imdb_id: str) -> Optional[TmdbResult]:
        """Lookup TMDb via /find endpoint avec un IMDb ID externe.

        Retourne le premier film trouve ou None.
        """
        iid = (imdb_id or "").strip()
        if not iid or not iid.startswith("tt"):
            return None

        cache_key = f"find_imdb|{iid}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            if not cached:
                return None
            return TmdbResult(**cached) if isinstance(cached, dict) else None

        url = f"{TMDB_API_BASE}/find/{iid}"
        params = {"api_key": self.api_key, "external_source": "imdb_id", "language": "fr-FR"}
        _t0 = time.monotonic()
        try:
            r = self._session.get(url, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            logger.debug("TMDb: find_by_imdb_id %s -> %d (%.1fs)", iid, r.status_code, time.monotonic() - _t0)
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            logger.debug("TMDb: echec find_by_imdb_id %s — %s", iid, exc)
            self._debug(f"find_by_imdb_id warning imdb_id={iid} error={exc}")
            return None

        movies = data.get("movie_results") or []
        if not movies:
            self._cache_set(cache_key, "")
            with contextlib.suppress(OSError, PermissionError):
                self._save_cache_atomic()
            return None

        m = movies[0]
        release = m.get("release_date") or ""
        y = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else None
        result = TmdbResult(
            id=int(m.get("id") or 0),
            title=str(m.get("title") or ""),
            year=y,
            original_title=m.get("original_title"),
            popularity=m.get("popularity"),
            vote_count=m.get("vote_count"),
            vote_average=m.get("vote_average"),
            poster_path=m.get("poster_path"),
        )
        self._cache_set(cache_key, result.__dict__)
        with contextlib.suppress(OSError, PermissionError):
            self._save_cache_atomic()
        logger.info("TMDb: find_by_imdb_id %s -> id=%d '%s' (%s)", iid, result.id, result.title, result.year)
        return result

    # --- TV series methods ---

    def search_tv(
        self,
        query: str,
        year: Optional[int] = None,
        language: str = "fr-FR",
        max_results: int = 5,
    ) -> List[TmdbTvResult]:
        """Search TV shows on TMDb."""
        q = str(query or "").strip()
        if not q:
            return []
        q_norm = " ".join(q.lower().split())
        cache_key = f"tv_search:{q_norm}|{year or ''}|{language}"

        # NB: pas de with self._lock ici — _cache_get gere son propre lock
        cached = self._cache_get(cache_key)
        if cached is not None and isinstance(cached, list):
            return [
                TmdbTvResult(
                    id=int(item.get("id") or 0),
                    name=str(item.get("name") or ""),
                    first_air_date_year=int(item["first_air_date_year"]) if item.get("first_air_date_year") else None,
                    original_name=item.get("original_name"),
                    popularity=item.get("popularity"),
                    vote_count=item.get("vote_count"),
                    poster_path=item.get("poster_path"),
                )
                for item in cached[:max_results]
            ]

        try:
            params: Dict[str, Any] = {
                "api_key": self.api_key,
                "query": q,
                "language": language,
                "page": 1,
            }
            if year:
                params["first_air_date_year"] = int(year)
            resp = self._session.get(f"{TMDB_API_BASE}/search/tv", params=params, timeout=self.timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []

        results_raw = data.get("results") or []
        out: List[TmdbTvResult] = []
        cache_items: List[Dict[str, Any]] = []
        for item in results_raw[:max_results]:
            fad = str(item.get("first_air_date") or "")
            fad_year = int(fad[:4]) if len(fad) >= 4 and fad[:4].isdigit() else None
            tv = TmdbTvResult(
                id=int(item.get("id") or 0),
                name=str(item.get("name") or ""),
                first_air_date_year=fad_year,
                original_name=str(item.get("original_name") or "") or None,
                popularity=float(item.get("popularity") or 0.0),
                vote_count=int(item.get("vote_count") or 0),
                poster_path=str(item.get("poster_path") or "") or None,
            )
            out.append(tv)
            cache_items.append(
                {
                    "id": tv.id,
                    "name": tv.name,
                    "first_air_date_year": tv.first_air_date_year,
                    "original_name": tv.original_name,
                    "popularity": tv.popularity,
                    "vote_count": tv.vote_count,
                    "poster_path": tv.poster_path,
                }
            )

        # _cache_set et _save_cache_atomic gerent leur propre lock
        self._cache_set(cache_key, cache_items)
        self._save_cache_atomic(force=False)
        return out

    def get_tv_episode_title(
        self,
        series_id: int,
        season_number: int,
        episode_number: int,
        language: str = "fr-FR",
    ) -> Optional[str]:
        """Get the title of a specific TV episode."""
        cache_key = f"tv_ep:{series_id}|{season_number}|{episode_number}|{language}"

        # NB: pas de with self._lock ici — _cache_get gere son propre lock
        cached = self._cache_get(cache_key)
        if cached is not None:
            return str(cached) if cached else None

        try:
            params = {"api_key": self.api_key, "language": language}
            url = f"{TMDB_API_BASE}/tv/{series_id}/season/{season_number}/episode/{episode_number}"
            resp = self._session.get(url, params=params, timeout=self.timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return None

        title = str(data.get("name") or "").strip() or None

        # _cache_set et _save_cache_atomic gerent leur propre lock
        self._cache_set(cache_key, title or "")
        self._save_cache_atomic(force=False)
        return title


# ---------------------------------------------------------------------------
# V5-03 polish v7.7.0 (R5-STRESS-4) : purge auto au boot.
# ---------------------------------------------------------------------------


def purge_expired_tmdb_cache(
    cache_path: Path,
    ttl_days: int | None = None,
) -> Dict[str, int]:
    """Purge les entrees expirees du cache TMDb sur disque.

    V5-03 polish v7.7.0 (R5-STRESS-4) : evite l'accumulation indefinie
    d'entrees orphelines apres 1 an d'usage. Appelee au boot de l'app
    via un thread daemon non-bloquant (cf `app.py:main()`).

    Backward compat : les entrees au format ancien (valeur directe sans
    wrapper `_cached_at`) sont preservees (TTL infini, refresh a la
    prochaine modification ou prochaine purge avec entree neuve).

    Parameters
    ----------
    cache_path : Path
        Chemin vers le fichier `tmdb_cache.json`.
    ttl_days : int, optional
        TTL en jours. Si None, utilise DEFAULT_CACHE_TTL_DAYS (30).
        Clamp dans [MIN_CACHE_TTL_DAYS, MAX_CACHE_TTL_DAYS].

    Returns
    -------
    dict
        {"checked": int, "purged": int, "preserved_legacy": int, "error": str|None}
        - checked : nombre total d'entrees inspectees
        - purged : nombre d'entrees expirees supprimees
        - preserved_legacy : nombre d'entrees ancien format conservees
        - error : message d'erreur si echec de lecture/ecriture, sinon None

    Notes
    -----
    Reecrit le fichier de maniere atomique (tmp -> rename). Aucune
    exception levee : retourne `error` non-vide en cas de probleme
    (le caller log et continue).
    """
    result: Dict[str, int] = {"checked": 0, "purged": 0, "preserved_legacy": 0, "error": None}
    if not cache_path.exists():
        return result

    effective_ttl_days = _clamp_ttl_days(ttl_days)
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except (OSError, PermissionError) as exc:
        result["error"] = f"read_error: {exc}"
        return result

    try:
        cache = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        result["error"] = f"parse_error: {exc}"
        return result

    if not isinstance(cache, dict):
        result["error"] = "cache_not_dict"
        return result

    now = time.time()
    new_cache: Dict[str, Any] = {}
    for key, entry in cache.items():
        result["checked"] += 1
        # Backward compat : ancien format (valeur directe, pas de _cached_at)
        if not (isinstance(entry, dict) and "_cached_at" in entry and "value" in entry):
            new_cache[key] = entry
            result["preserved_legacy"] += 1
            continue

        try:
            cached_at = float(entry.get("_cached_at") or 0.0)
        except (TypeError, ValueError):
            cached_at = 0.0

        ttl = _ttl_for_key(key, effective_ttl_days)
        if now - cached_at > ttl:
            # Expire : on n'inclut pas dans new_cache
            result["purged"] += 1
        else:
            new_cache[key] = entry

    if result["purged"] == 0:
        # Rien a faire : pas d'ecriture inutile
        return result

    # Reecriture atomique (tmp -> rename)
    try:
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, cache_path)
    except (OSError, PermissionError) as exc:
        result["error"] = f"write_error: {exc}"
        return result

    return result
