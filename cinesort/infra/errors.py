"""Gestion centralisee des erreurs top-level.

Audit AUDIT_20260422 finding B1 : le projet contient ~13 `except Exception`
legitimes marques `# except Exception intentionnel : boundary top-level`
ou `# noqa: BLE001`. Ces catchs large-scope sont tous au MEME endroit
semantique : la frontiere externe d'une surface publique (API pywebview,
handler REST, thread daemon) ou l'on veut a la fois :

1. Logger l'erreur pour diagnostic.
2. Retourner un payload generique au client SANS exposer l'exception brute.
3. Eviter que l'exception ne tue l'ensemble du processus.

Ce module fournit un decorateur `@boundary` qui encapsule ce pattern et
rend l'intention explicite. Il ne remplace pas tous les 13 cas d'un coup
(certains ont une logique de retour specifique a leur contexte), mais il
sert de canon pour les nouveaux sites et pour migrer progressivement.

Usage :

    from cinesort.infra.errors import boundary

    @boundary(log_name="api.reset_incremental_cache", default={"ok": False, "message": "Erreur maintenance."})
    def reset_incremental_cache(self) -> dict:
        ...

Si la fonction decoree leve une exception inattendue :
- elle est loggee via `logging.getLogger(log_name).exception(...)` ;
- le `default` est retourne a l'appelant.

`@boundary` est un remplacement ciblé pour les `except Exception` de type
`M8` (REST boundary) et les boundaries threadees. Pour les catchs qui ont
une logique metier specifique dans le branch `except`, garder le bloc
explicite avec le commentaire `# except Exception intentionnel`.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def boundary(
    *,
    log_name: str,
    default: Any = None,
    reraise: bool = False,
) -> Callable[[F], F]:
    """Decorateur de frontiere externe.

    Args:
        log_name: logger utilise pour l'exception trace.
        default: valeur retournee en cas d'exception non geree (ignore si reraise).
        reraise: si True, re-leve l'exception apres l'avoir loggee. Utile pour
            les threads daemons ou l'appelant exterieur a besoin de la voir
            mais on veut tout de meme un trace.

    Notes:
        - Attrape uniquement `Exception` (pas `BaseException`), pour laisser
          passer `KeyboardInterrupt` et `SystemExit`.
        - Respecte les exceptions typees : si la fonction decoree attrape elle
          meme certaines exceptions, elle les traite normalement avant que
          `@boundary` ne voie passer quoi que ce soit.
    """
    logger = logging.getLogger(log_name)

    def _decorate(fn: F) -> F:
        @functools.wraps(fn)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception:
                logger.exception("boundary[%s] exception non geree", log_name)
                if reraise:
                    raise
                return default

        return _wrapper  # type: ignore[return-value]

    return _decorate


__all__ = ["boundary"]
