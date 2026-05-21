"""Decorateurs et helpers de validation pour les endpoints REST/desktop CineSortApi.

Cf issue #101 : le pattern de validation `run_id` etait duplique 20 fois
dans 8 modules support. Centraliser :
- supprime le boilerplate (~40 LOC)
- garantit un message d'erreur uniforme via i18n
- facilite l'ajout d'observabilite (log structure de l'echec)
- empeche d'oublier la validation sur un nouvel endpoint

Audit C7 P1 (sprint C1 mai 2026) : ajout d'un helper `clamp_timeout` pour
bornir les valeurs `timeout_s` des endpoints de test de connexion
(TMDb, Jellyfin, Plex, Radarr, OMDb). Le clamp evite qu'un caller (REST
distant compromis ou test E2E mal calibre) passe une valeur extreme
(timeout_s=0, timeout_s=86400, NaN, str) qui ferait crasher le client
HTTP ou bloquerait le thread API.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from cinesort.domain.i18n_messages import t


def clamp_timeout(value: Any, default: float = 10.0, lo: float = 1.0, hi: float = 60.0) -> float:
    """Borne un timeout_s entre `lo` et `hi` secondes, avec `default` en fallback.

    Audit C7 P1 : les endpoints de test de connexion (TMDb, Jellyfin, Plex,
    Radarr, OMDb) recevaient `timeout_s` sans aucune validation cote serveur.
    Un caller pouvait passer `timeout_s=0` (division par zero plus bas),
    `timeout_s=99999` (DoS thread API), ou `timeout_s="abc"` (TypeError).

    Ce helper garantit une valeur numerique dans `[lo, hi]`. Les valeurs
    invalides (None, str non-numerique, NaN, inf) tombent sur `default`.

    Args:
        value: la valeur brute fournie par le caller (peut etre None, str, int, float).
        default: valeur de repli si parsing impossible (defaut 10.0s).
        lo: borne inferieure inclusive (defaut 1.0s).
        hi: borne superieure inclusive (defaut 60.0s).

    Returns:
        Un float dans [lo, hi].

    Examples:
        >>> clamp_timeout(None)
        10.0
        >>> clamp_timeout(0)
        1.0
        >>> clamp_timeout(99999)
        60.0
        >>> clamp_timeout("abc")
        10.0
        >>> clamp_timeout(7.5)
        7.5
    """
    try:
        parsed = float(value) if value is not None else float(default)
    except (TypeError, ValueError):
        parsed = float(default)
    # Filtre NaN / inf : float("nan") != float("nan") est True
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        parsed = float(default)
    return max(float(lo), min(float(hi), parsed))


def clamp_non_negative_int(value: Any, default: int = 0) -> int:
    """Convertit une valeur en int >= 0, avec `default` en fallback.

    Audit C7 P1 : `test_reset(min_video_bytes)` acceptait n'importe quoi
    sans validation. Un caller pouvait passer une str ("abc"), un float
    negatif (-1), ou None. Ce helper normalise vers `int(value or default)`
    en garantissant >= 0.

    Args:
        value: la valeur brute (None, str, int, float, etc.).
        default: valeur de repli (defaut 0).

    Returns:
        Un int >= 0.
    """
    try:
        parsed = int(float(value)) if value is not None else int(default)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(0, parsed)


def requires_valid_run_id(fn: Callable) -> Callable:
    """Decore une fonction `def fn(api, run_id, ...)` pour valider run_id en amont.

    Si `api._is_valid_run_id(run_id)` est False, retourne
    `{"ok": False, "run_id": str(run_id or ""), "message": t("errors.run_invalid_id")}`
    sans appeler la fonction sous-jacente.

    Le champ `run_id` dans la reponse aide au debug cote frontend (savoir
    quel run a echoue la validation) — historiquement seul history_support
    incluait ce champ, on l'uniformise.

    Le decorateur cherche `run_id` :
    1. En premier argument positional apres `api`
    2. En kwarg `run_id` si non passe en positional
    """

    @wraps(fn)
    def wrapper(api: Any, *args: Any, **kwargs: Any) -> Any:
        run_id = kwargs.get("run_id") if "run_id" in kwargs else (args[0] if args else None)
        if not api._is_valid_run_id(run_id):
            return {
                "ok": False,
                "run_id": str(run_id or ""),
                "message": t("errors.run_invalid_id"),
            }
        return fn(api, *args, **kwargs)

    return wrapper
