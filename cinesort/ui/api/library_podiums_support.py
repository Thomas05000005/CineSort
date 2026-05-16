"""Library Podiums — Top release groups, codecs, sources (Dashboard).

Endpoint `get_library_podiums(api, run_id=None, limit=10)` qui retourne les
trois podiums du dernier run (ou run specifie) :

- **release_groups** : top N groupes scene (RARBG, T4KT, VeXHD, ...) extraits
  des noms de fichiers
- **codecs** : top N codecs video (x265, x264, AV1, ...) extraits des probes
  ffprobe
- **sources** : top N sources scene (BluRay, WEB-DL, HDTV, Remux, ...) extraites
  des noms de fichiers

Le calcul est on-demand : pas de stockage en DB, juste une iteration sur les
PlanRows + extraction regex via scene_parser. Sur 5000 films, ~5s max.

Cf plan Phase Dashboard Podiums (PR feat/dashboard-stats-podiums).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from cinesort.domain.scene_parser import extract_release_group, extract_source
from cinesort.infra import state
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.library_support import _build_library_rows
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


# Cap superieur sur le N retourne (eviter DoS / payload monstre)
_MAX_LIMIT = 50


def _resolve_latest_run_id(api: Any) -> Optional[str]:
    """Retourne le run_id du run le plus recent, ou None si aucun."""
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.get_runs_summary(limit=1)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_podiums cannot resolve latest run: %s", exc)
        return None
    return str(runs[0]["run_id"]) if runs else None


def _aggregate_top(values: List[Optional[str]], limit: int) -> List[Dict[str, Any]]:
    """Agrege une liste de valeurs en top N, ignorant les None/vides.

    Returns:
        Liste triee par count desc puis name asc, format
        [{"name": str, "count": int}, ...], longueur max=limit.
    """
    counter: Counter[str] = Counter()
    for v in values:
        if v is None:
            continue
        clean = str(v).strip()
        if not clean:
            continue
        counter[clean] += 1
    # Tri par count desc, name asc (alphabetique pour egalites)
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [{"name": name, "count": count} for name, count in items[:limit]]


def get_library_podiums(
    api: Any,
    run_id: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Retourne les podiums (release groups, codecs, sources) pour le run cible.

    Args:
        api: instance CineSortApi
        run_id: run cible (default: dernier run)
        limit: nombre d'entrees par podium (1-50, default 10)

    Returns:
        {
          "ok": True,
          "run_id": "...",
          "total_films": int,
          "release_groups": [{"name": "RARBG", "count": 142}, ...],
          "codecs": [{"name": "x265", "count": 1200}, ...],
          "sources": [{"name": "BluRay", "count": 800}, ...],
          # Coverage : combien de films avaient l'info disponible
          "coverage": {
              "release_groups_pct": 65.3,
              "codecs_pct": 98.1,
              "sources_pct": 82.0,
          },
        }
        ou err dict si le run_id n'est pas resolvable.
    """
    # Note : `limit or 10` traite 0 comme "default" — comportement souhaite
    # car limit=0 n'a pas de sens (le caller veut soit un nombre, soit le defaut).
    try:
        raw_limit = int(limit) if limit else 10
    except (TypeError, ValueError):
        raw_limit = 10
    lim = max(1, min(_MAX_LIMIT, raw_limit))

    resolved_rid = run_id or _resolve_latest_run_id(api)
    if not resolved_rid:
        return {
            "ok": True,
            "run_id": None,
            "total_films": 0,
            "release_groups": [],
            "codecs": [],
            "sources": [],
            "coverage": {
                "release_groups_pct": 0.0,
                "codecs_pct": 0.0,
                "sources_pct": 0.0,
            },
        }

    try:
        rows = _build_library_rows(api, resolved_rid)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_podiums cannot build rows for %s: %s", resolved_rid, exc)
        return _err_response(
            f"Impossible de charger la bibliotheque pour le run {resolved_rid}: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    total = len(rows)
    if total == 0:
        return {
            "ok": True,
            "run_id": resolved_rid,
            "total_films": 0,
            "release_groups": [],
            "codecs": [],
            "sources": [],
            "coverage": {
                "release_groups_pct": 0.0,
                "codecs_pct": 0.0,
                "sources_pct": 0.0,
            },
        }

    # Extraction des 3 signaux pour chaque film
    release_groups: List[Optional[str]] = []
    codecs: List[Optional[str]] = []
    sources: List[Optional[str]] = []

    for row in rows:
        path = str(row.get("path") or "")
        # Le filename suffit pour les extractions (pas besoin du chemin complet)
        filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
        release_groups.append(extract_release_group(filename))
        sources.append(extract_source(filename))
        # Codec : deja normalise par _build_library_rows via _normalize_codec()
        codec = row.get("codec")
        codecs.append(str(codec).strip() if codec else None)

    # Coverage = % des films pour lesquels on a extrait la donnee
    rg_have = sum(1 for v in release_groups if v)
    cd_have = sum(1 for v in codecs if v)
    sr_have = sum(1 for v in sources if v)

    return {
        "ok": True,
        "run_id": resolved_rid,
        "total_films": total,
        "release_groups": _aggregate_top(release_groups, lim),
        "codecs": _aggregate_top(codecs, lim),
        "sources": _aggregate_top(sources, lim),
        "coverage": {
            "release_groups_pct": round(rg_have / total * 100, 1),
            "codecs_pct": round(cd_have / total * 100, 1),
            "sources_pct": round(sr_have / total * 100, 1),
        },
    }
