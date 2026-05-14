"""Decorateurs de validation pour les endpoints REST/desktop CineSortApi.

Cf issue #101 : le pattern de validation `run_id` etait duplique 20 fois
dans 8 modules support. Centraliser :
- supprime le boilerplate (~40 LOC)
- garantit un message d'erreur uniforme via i18n
- facilite l'ajout d'observabilite (log structure de l'echec)
- empeche d'oublier la validation sur un nouvel endpoint
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from cinesort.domain.i18n_messages import t


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
