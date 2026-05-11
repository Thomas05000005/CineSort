"""V3-04 audit polish v7.7.0 — contexte de log transversal (run_id + request_id).

Resout R4-LOG-1 et R4-LOG-2 : injecter automatiquement le ``run_id`` du scan
en cours et le ``request_id`` de la requete REST courante dans CHAQUE
``LogRecord`` via un ``logging.Filter`` connecte a des ``contextvars``.

Strategie :
- Une ContextVar `run_id` propagee implicitement a travers les threads (chaque
  worker `JobRunner` qui appelle `set_run_id(run_id)` au demarrage propage la
  valeur dans toute la pile d'appels qu'il declenche).
- Une ContextVar `request_id` positionnee au debut de chaque do_GET/do_POST du
  serveur REST (uuid4 hex 8 chars) et nettoyee en fin de requete.
- Un ``logging.Filter`` (LogContextFilter) ajoute systematiquement les attributs
  ``run_id`` et ``request_id`` a la LogRecord (avec valeur "-" si non defini)
  pour que les formatters puissent les referencer sans KeyError.

Compatibilite : aucune dependance externe (stdlib `contextvars` + `logging`).
La signature `logging.getLogger(name)` reste inchangee. Les loggers existants
beneficient automatiquement de l'enrichissement.

Note sur la propagation contextvars :
- ``threading.Thread`` ne copie PAS automatiquement le contexte parent. Pour le
  job_runner, l'appel `set_run_id` est fait DANS le worker apres son demarrage,
  donc l'enrichissement est effectif pour tous les logs emis depuis ce thread
  (Python conserve le ContextVar par thread).
- ``ThreadPoolExecutor.submit`` et ``concurrent.futures`` ne copient pas non
  plus. Les sous-threads spawnes par un worker doivent appeler `set_run_id`
  manuellement s'ils veulent l'heritage (rare en pratique : la majorite des
  modules cinesort restent dans le thread du worker).
- ``asyncio`` propage automatiquement le contexte (Task copie le contexte
  parent). Aucune action requise.
"""

from __future__ import annotations

import contextvars
import logging
import os
from typing import Optional

# Sentinelle "valeur absente" pour les formatters texte. "-" est conventionnel
# (cf logs syslog/Apache) et plus lisible que "None" ou chaine vide.
_UNSET = "-"

# Champ injecte dans LogRecord. Centralise pour eviter les typos cross-module.
LOG_FIELD_RUN_ID = "run_id"
LOG_FIELD_REQUEST_ID = "request_id"

# Format texte par defaut enrichi avec run_id + request_id. Compact pour rester
# lisible meme quand les deux champs sont a "-".
DEFAULT_LOG_FORMAT_WITH_CONTEXT = (
    "%(asctime)s [%(levelname)s] %(name)s [run=%(run_id)s req=%(request_id)s] %(message)s"
)

_run_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "cinesort_run_id", default=None
)
_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "cinesort_request_id", default=None
)


# --- API publique : run_id ----------------------------------------------------


def set_run_id(run_id: Optional[str]) -> contextvars.Token:
    """Positionne le run_id du contexte courant.

    Retourne un Token qui peut etre passe a `reset_run_id` pour restaurer
    l'etat anterieur (utile en cas de runs imbriques ou de tests).
    """
    return _run_id_var.set(str(run_id) if run_id else None)


def get_run_id() -> Optional[str]:
    """Retourne le run_id courant, ou None s'il n'est pas defini."""
    return _run_id_var.get()


def clear_run_id() -> None:
    """Efface le run_id du contexte courant (set None)."""
    _run_id_var.set(None)


def reset_run_id(token: contextvars.Token) -> None:
    """Restaure l'etat du run_id ContextVar d'avant un set_run_id."""
    _run_id_var.reset(token)


# --- API publique : request_id ------------------------------------------------


def set_request_id(request_id: Optional[str]) -> contextvars.Token:
    """Positionne le request_id de la requete REST courante."""
    return _request_id_var.set(str(request_id) if request_id else None)


def get_request_id() -> Optional[str]:
    """Retourne le request_id courant, ou None s'il n'est pas defini."""
    return _request_id_var.get()


def clear_request_id() -> None:
    """Efface le request_id du contexte courant."""
    _request_id_var.set(None)


def reset_request_id(token: contextvars.Token) -> None:
    """Restaure l'etat du request_id ContextVar d'avant un set_request_id."""
    _request_id_var.reset(token)


# --- Filter logging stdlib ----------------------------------------------------


class LogContextFilter(logging.Filter):
    """Injecte les attributs ``run_id`` et ``request_id`` dans chaque LogRecord.

    Les attributs sont toujours presents (valeur "-" si non defini) ce qui
    permet aux formatters d'utiliser ``%(run_id)s`` sans KeyError.

    Idempotent et thread-safe : `ContextVar.get()` est lock-free et propre
    par thread (Python alloue une copie du contexte par thread/task).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.run_id = _run_id_var.get() or _UNSET
        except LookupError:  # pragma: no cover — defaut=None ne devrait jamais lever
            record.run_id = _UNSET
        try:
            record.request_id = _request_id_var.get() or _UNSET
        except LookupError:  # pragma: no cover
            record.request_id = _UNSET
        # Toujours True : ce filter ne supprime jamais de record, il enrichit.
        return True


_INSTALLED = False


def install_log_context_filter() -> None:
    """Installe LogContextFilter sur le root logger ET sur tous ses handlers.

    Idempotent : appelable plusieurs fois sans dupliquer le filter. A appeler
    une fois au boot (dans app.py:main / app.py:main_api), apres
    `install_global_scrubber` mais avant `install_rotating_log` (l'ordre n'est
    pas critique car le filter est aussi attache aux handlers existants).
    """
    global _INSTALLED
    if _INSTALLED:
        return
    flt = LogContextFilter()
    root = logging.getLogger()
    if not any(isinstance(f, LogContextFilter) for f in root.filters):
        root.addFilter(flt)
    for handler in root.handlers:
        if not any(isinstance(f, LogContextFilter) for f in handler.filters):
            handler.addFilter(flt)
    _INSTALLED = True


def attach_filter_to_handler(handler: logging.Handler) -> None:
    """Attache LogContextFilter a un handler precis.

    Utile lorsqu'un nouveau handler est cree apres `install_log_context_filter`
    (par exemple `install_rotating_log`) — le filter sur le root logger ne
    s'applique pas automatiquement aux handlers ajoutes plus tard sur les
    records propages, donc on attache le filter directement sur le handler.
    """
    if not any(isinstance(f, LogContextFilter) for f in handler.filters):
        handler.addFilter(LogContextFilter())


def reset_for_tests() -> None:
    """A utiliser uniquement dans les tests : remet l'etat global a zero.

    Reset le flag _INSTALLED + clear les ContextVars du contexte courant.
    Ne touche PAS aux filters deja installes sur des loggers/handlers — le
    test doit gerer sa propre isolation logger si besoin.
    """
    global _INSTALLED
    _INSTALLED = False
    clear_run_id()
    clear_request_id()


# --- Resolution log_level depuis settings + env vars --------------------------

_TRUTHY = {"1", "true", "yes", "on", "debug"}

_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def resolve_log_level(
    settings_value: Optional[str] = None,
    *,
    env: Optional[dict] = None,
) -> int:
    """Resout le niveau de log effectif a partir des settings et env vars.

    Priorite (du plus prioritaire au moins) :
    1. ``CINESORT_LOG_LEVEL`` env var (override total — DEBUG/INFO/...)
    2. ``CINESORT_DEBUG=1`` env var (force DEBUG, R4-LOG-4)
    3. ``settings_value`` (passe en argument, lu depuis settings.json)
    4. Defaut : ``INFO``

    Retourne un entier ``logging.LEVEL`` directement utilisable par
    ``logging.basicConfig(level=...)``.
    """
    environ = env if env is not None else os.environ

    # 1. CINESORT_LOG_LEVEL = override prioritaire
    env_level = str(environ.get("CINESORT_LOG_LEVEL") or "").strip().upper()
    if env_level in _VALID_LOG_LEVELS:
        return getattr(logging, env_level)

    # 2. CINESORT_DEBUG=1 force DEBUG
    if str(environ.get("CINESORT_DEBUG") or "").strip().lower() in _TRUTHY:
        return logging.DEBUG

    # 3. Settings
    candidate = str(settings_value or "").strip().upper()
    if candidate in _VALID_LOG_LEVELS:
        return getattr(logging, candidate)

    # 4. Defaut
    return logging.INFO


def normalize_log_level_setting(value: Optional[str]) -> str:
    """Normalise une valeur de setting log_level vers une chaine valide.

    Retourne une des valeurs de _VALID_LOG_LEVELS, defaut "INFO".
    Utilisee par `settings_support.py` pour valider/persister la valeur.
    """
    candidate = str(value or "").strip().upper()
    if candidate in _VALID_LOG_LEVELS:
        return candidate
    return "INFO"
