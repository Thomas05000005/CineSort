"""Library Timeline — Films ajoutes par mois (Dashboard).

Endpoint `get_library_timeline(api, months=12)` qui retourne un histogramme
du nombre de films ajoutes a la bibliotheque par mois.

Sources de la date "ajoute" (priorite) :
1. **Jellyfin DateCreated** : si Jellyfin est configure + actif. La date que
   Jellyfin a vu le film pour la premiere fois (= date download typique).
   Authoritative car centralise et inclut le merge de plusieurs roots.
2. **Filesystem mtime** : fallback pour les films non-presents dans Jellyfin
   ou si Jellyfin est desactive. `st_mtime` sur Windows = derniere modif.
   Pas parfait (un copy peut le reset) mais universel.

Le matching Jellyfin <-> CineSort se fait par tmdb_id (le plus fiable).

Cf plan Phase Dashboard Stats - PR feat/dashboard-timeline-monthly.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.infra import state
from cinesort.infra.jellyfin_client import JellyfinClient
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.library_support import _build_library_rows
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


# Bornes acceptables
_MIN_MONTHS = 1
_MAX_MONTHS = 60  # 5 ans max


def _parse_iso_to_month(iso_str: Optional[str]) -> Optional[str]:
    """Parse une date ISO 8601 et retourne 'YYYY-MM', ou None si invalide.

    Examples:
        >>> _parse_iso_to_month("2024-03-15T18:30:00.0000000Z")
        '2024-03'
        >>> _parse_iso_to_month("2024-03-15")
        '2024-03'
        >>> _parse_iso_to_month("")
        None
    """
    if not iso_str:
        return None
    s = str(iso_str).strip()
    if not s:
        return None
    # Tente parse format ISO commun
    # Jellyfin retourne "2024-03-15T18:30:00.0000000Z" (7-digit ms + Z)
    # Python datetime.fromisoformat() supporte la plupart des formats >=3.11
    try:
        # Strip nanoseconds if present (Python doesn't handle 7-digit fractional)
        cleaned = s.replace("Z", "+00:00")
        # Si fractional > 6 digits, troncate
        if "." in cleaned and "+" in cleaned:
            base, tz_part = cleaned.rsplit("+", 1)
            if "." in base:
                main, frac = base.rsplit(".", 1)
                frac = frac[:6]  # max 6 digits pour Python
                cleaned = f"{main}.{frac}+{tz_part}"
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, TypeError) as exc:
        logger.debug("timeline _parse_iso_to_month invalid: %r (%s)", iso_str, exc)
        return None
    # Sanity check : annee plausible
    if dt.year < 1990 or dt.year > 2100:
        return None
    return f"{dt.year:04d}-{dt.month:02d}"


def _file_mtime_to_month(path: str) -> Optional[str]:
    """Lit le mtime d'un fichier et retourne 'YYYY-MM', ou None si stat echoue.

    Sur Windows, mtime = derniere modif. Pour la date d'ajout au volume,
    `st_ctime` est plus precis (= creation time) mais peut etre instable
    sur NAS. On utilise mtime comme compromis universel.
    """
    if not path:
        return None
    try:
        p = Path(path)
        if not p.exists():
            return None
        ts = p.stat().st_mtime
    except (OSError, PermissionError):
        return None
    if ts <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OSError, ValueError, OverflowError):
        return None
    if dt.year < 1990 or dt.year > 2100:
        return None
    return f"{dt.year:04d}-{dt.month:02d}"


def _get_jellyfin_date_map(api: Any, settings: Dict[str, Any]) -> Dict[str, str]:
    """Retourne {tmdb_id: date_created_iso} depuis Jellyfin, ou {} si indispo.

    Echec gracieux : si Jellyfin n'est pas configure / unreachable / sans
    DateCreated, retourne dict vide -> le caller tombera sur file mtime.
    """
    if not settings.get("jellyfin_enabled"):
        return {}
    try:
        client = JellyfinClient(
            base_url=settings.get("jellyfin_url", ""),
            api_key=settings.get("jellyfin_api_key", ""),
            timeout_s=10.0,
        )
        user_id = settings.get("jellyfin_user_id") or ""
        library_id = settings.get("jellyfin_library_id") or None
        if not user_id:
            return {}
        movies = client.get_movies(user_id=user_id, library_id=library_id)
    except (OSError, ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.info("library_timeline jellyfin lookup failed (fallback to fs mtime): %s", exc)
        return {}

    out: Dict[str, str] = {}
    for movie in movies or []:
        tmdb_id = movie.get("tmdb_id")
        date_created = movie.get("date_created")
        if tmdb_id and date_created:
            out[str(tmdb_id)] = str(date_created)
    return out


def _generate_month_range(latest_month: str, n_months: int) -> List[str]:
    """Genere une liste continue de 'YYYY-MM' du plus ancien au plus recent.

    Used pour combler les "trous" (mois sans aucun film) avec count=0.
    """
    try:
        year, month = latest_month.split("-")
        y, m = int(year), int(month)
    except (ValueError, AttributeError):
        return []
    months: List[str] = []
    for _ in range(n_months):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))


def get_library_timeline(api: Any, months: int = 12, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Retourne le nombre de films ajoutes par mois pour les N derniers mois.

    Args:
        api: instance CineSortApi
        months: nombre de mois a afficher (1-60, default 12)
        run_id: run cible pour la liste de films (default: dernier run)

    Returns:
        {
          "ok": True,
          "run_id": "...",
          "source": "jellyfin" | "filesystem" | "mixed",
          "months": [
            {"month": "2025-06", "count": 0},
            {"month": "2025-07", "count": 12},
            ...
          ],
          "total_films": int,
          "films_with_date_pct": 87.5,  # % des films pour lesquels on a une date
        }
    """
    try:
        n_months = max(_MIN_MONTHS, min(_MAX_MONTHS, int(months) if months else 12))
    except (TypeError, ValueError):
        n_months = 12

    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_timeline cannot get store: %s", exc)
        return _err_response(
            f"Impossible de lire les settings: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    if run_id is None:
        try:
            runs = store.get_runs_summary(limit=1)
        except (OSError, AttributeError, KeyError, TypeError, ValueError):
            runs = []
        run_id = str(runs[0]["run_id"]) if runs else None

    if not run_id:
        return {
            "ok": True,
            "run_id": None,
            "source": "filesystem",
            "months": [],
            "total_films": 0,
            "films_with_date_pct": 0.0,
        }

    try:
        rows = _build_library_rows(api, run_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_timeline cannot build rows: %s", exc)
        return _err_response(
            f"Impossible de charger la bibliotheque: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    total = len(rows)
    if total == 0:
        return {
            "ok": True,
            "run_id": run_id,
            "source": "filesystem",
            "months": [],
            "total_films": 0,
            "films_with_date_pct": 0.0,
        }

    # 1. Tente de recuperer les dates Jellyfin par tmdb_id
    jelly_dates = _get_jellyfin_date_map(api, settings)
    using_jellyfin = bool(jelly_dates)
    using_filesystem = False

    # 2. Pour chaque film, resoud le mois
    month_counter: Counter[str] = Counter()
    n_with_date = 0
    for row in rows:
        month: Optional[str] = None
        # Tente Jellyfin via tmdb_id
        tmdb_id = row.get("tmdb_id")
        if tmdb_id and jelly_dates:
            iso = jelly_dates.get(str(tmdb_id))
            if iso:
                month = _parse_iso_to_month(iso)
        # Fallback filesystem
        if month is None:
            path = str(row.get("path") or "")
            month = _file_mtime_to_month(path)
            if month is not None:
                using_filesystem = True
        if month is not None:
            month_counter[month] += 1
            n_with_date += 1

    # 3. Genere le range de mois pour combler les trous (Janvier 0, Fevrier 0, ...)
    if month_counter:
        latest_month = max(month_counter.keys())
        month_range = _generate_month_range(latest_month, n_months)
    else:
        # Aucune date dispo : timeline vide
        now = datetime.now(timezone.utc)
        latest_month = f"{now.year:04d}-{now.month:02d}"
        month_range = _generate_month_range(latest_month, n_months)

    months_list = [{"month": m, "count": month_counter.get(m, 0)} for m in month_range]

    # 4. Determine la source effective
    if using_jellyfin and using_filesystem:
        source = "mixed"
    elif using_jellyfin:
        source = "jellyfin"
    else:
        source = "filesystem"

    return {
        "ok": True,
        "run_id": run_id,
        "source": source,
        "months": months_list,
        "total_films": total,
        "films_with_date_pct": round(n_with_date / total * 100, 1) if total > 0 else 0.0,
    }
