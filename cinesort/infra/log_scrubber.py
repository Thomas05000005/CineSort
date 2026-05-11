"""H-3/S-4/S-5 audit QA 20260428 — scrubbing des secrets dans les logs.

Empeche les cles API TMDb, tokens Jellyfin/Plex, X-Api-Key Radarr, etc.
de fuir vers stdout/fichier de log via .error("...", exc_info=True) qui
inclut la traceback complete (souvent l'URL avec api_key= en query, ou
les headers d'auth dans la repr de la requete).

Strategie : un logging.Filter installe sur le root logger qui passe sur
record.msg (apres formatage) et record.args, et remplace les patterns
de secrets par [REDACTED]. Patterns conservatives (faux positifs benins,
faux negatifs evites).
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import traceback
from pathlib import Path
from typing import Iterable, List, Optional, Pattern

# Patterns ordonnes par specificite. Utilisent un capture group pour
# preserver la prefixe et n'effacer que la valeur.
#
# SEC-H1 (Phase 1 remediation v7.8.0) : le pattern JSON est elargi pour couvrir
# n'importe quelle cle se terminant par `_api_key`, `_token`, `_password`,
# `_secret`, ou les variantes `api_key` / `api-key` nues. Cela attrape
# `email_smtp_password`, `omdb_api_key`, etc. sans devoir maintenir une
# liste exhaustive.
_SECRET_PATTERNS: List[Pattern[str]] = [
    # TMDb v3 query string : ?api_key=abc123 ou &api_key=abc123
    re.compile(r"(api_key=)([^&\s\"'>]+)", re.IGNORECASE),
    # Generique : ?token=xxx ou &token=xxx
    re.compile(r"(token=)([^&\s\"'>]+)", re.IGNORECASE),
    # Jellyfin header : Authorization: MediaBrowser Token="xxx"
    re.compile(r'(MediaBrowser Token=")([^"]+)(")', re.IGNORECASE),
    # Bearer token generique (REST CineSort, beaucoup d'API)
    re.compile(r"(Authorization:\s*Bearer\s+)(\S+)", re.IGNORECASE),
    # Plex header : X-Plex-Token: xxx ou X-Plex-Token=xxx
    re.compile(r"(X-Plex-Token[:\s=]+)([^\s;,&\"']+)", re.IGNORECASE),
    # Radarr/Sonarr header : X-Api-Key: xxx
    re.compile(r"(X-Api-Key[:\s=]+)([^\s;,&\"']+)", re.IGNORECASE),
    # Catch-all cle JSON terminant par `_api_key`, `_token`, `_password`,
    # `_secret` OU les variantes "api_key" / "api-key" nues. Couvre :
    #   "tmdb_api_key", "jellyfin_api_key", "omdb_api_key", "osdb_api_key",
    #   "plex_token", "radarr_api_key", "rest_api_token", "email_smtp_password",
    #   "smtp_password", "tmdb_api_key_secret", etc.
    # Limite la longueur du nom de cle a 64 caracteres pour eviter les
    # ReDoS et matchs accidentels sur du texte libre.
    re.compile(
        r'("[\w-]{1,64}(?:_api[_-]?key|_token|_password|_secret|api[_-]?key)"\s*:\s*")([^"]+)(")',
        re.IGNORECASE,
    ),
]

_REDACTED = "[REDACTED]"


def scrub_secrets(text: str) -> str:
    """Retourne `text` avec les secrets remplaces par [REDACTED].

    Tolere les non-strings (passe-through). Aucune exception levee :
    une defaillance du scrubber ne doit JAMAIS supprimer les logs ;
    en pire cas, on retourne le texte brut.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        out = text
        for pattern in _SECRET_PATTERNS:
            # Pour les patterns avec 3 groupes (prefixe, secret, suffixe),
            # on garde groupes 1 et 3. Pour 2 groupes, on garde groupe 1.
            def _replace(match: "re.Match[str]") -> str:
                groups = match.groups()
                if len(groups) >= 3:
                    return f"{groups[0]}{_REDACTED}{groups[2]}"
                return f"{groups[0]}{_REDACTED}"

            out = pattern.sub(_replace, out)
        return out
    except (TypeError, ValueError, re.error):
        return text


class SecretsScrubFilter(logging.Filter):
    """logging.Filter qui scrub les secrets dans record.msg et record.args.

    Installe via :
        logging.getLogger().addFilter(SecretsScrubFilter())

    Doit etre installe sur le root logger (ou sur chaque handler) pour
    capturer tous les logs y compris ceux de bibliotheques tierces
    (requests, urllib3, etc.).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Scrub le message format string lui-meme.
        try:
            if isinstance(record.msg, str):
                record.msg = scrub_secrets(record.msg)
        except (AttributeError, TypeError):
            pass

        # Scrub les args (substitues dans le message a getMessage()).
        try:
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: scrub_secrets(v) if isinstance(v, str) else v for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(scrub_secrets(v) if isinstance(v, str) else v for v in record.args)
        except (AttributeError, TypeError):
            pass

        # Scrub la traceback. Le formatter du handler appelle formatException()
        # SEULEMENT si record.exc_text est None (cf logging.Formatter.format).
        # On pre-format ici et on scrub : le handler verra exc_text deja set
        # et le concatenera tel quel.
        try:
            if record.exc_info and not record.exc_text:
                record.exc_text = "".join(traceback.format_exception(*record.exc_info))
            if record.exc_text:
                record.exc_text = scrub_secrets(record.exc_text)
        except (AttributeError, TypeError, ValueError):
            pass

        return True


_INSTALLED = False


def install_global_scrubber(loggers: Iterable[logging.Logger] = ()) -> None:
    """Installe le SecretsScrubFilter sur le root logger (et optionnellement sur
    une liste de loggers nommes). Idempotent : peut etre appele plusieurs fois
    sans dupliquer le filter.

    A appeler une seule fois au boot, dans app.py ou cinesort_api.py.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    flt = SecretsScrubFilter()
    root = logging.getLogger()
    if not any(isinstance(f, SecretsScrubFilter) for f in root.filters):
        root.addFilter(flt)
    # Egalement sur tous les handlers existants du root, sinon les filters de
    # logger seul ne s'appliquent pas aux records propaguees vers handlers
    # (cf https://docs.python.org/3/library/logging.html#filter-objects).
    for handler in root.handlers:
        if not any(isinstance(f, SecretsScrubFilter) for f in handler.filters):
            handler.addFilter(flt)
    for logger in loggers:
        if not any(isinstance(f, SecretsScrubFilter) for f in logger.filters):
            logger.addFilter(flt)
        for handler in logger.handlers:
            if not any(isinstance(f, SecretsScrubFilter) for f in handler.filters):
                handler.addFilter(flt)
    _INSTALLED = True


def reset_for_tests() -> None:
    """A utiliser uniquement dans les tests : reset l'etat _INSTALLED."""
    global _INSTALLED, _ROTATING_INSTALLED
    _INSTALLED = False
    _ROTATING_INSTALLED = False


# H-6 audit QA 20260429 : rotation des logs Python
# Defaults : 50 MB max par fichier, 5 backups (donc max 300 MB total).
# V3-04 polish v7.7.0 : format enrichi avec [run=... req=...] via LogContextFilter
# (cf cinesort/infra/log_context.py).
DEFAULT_LOG_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5
DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [run=%(run_id)s req=%(request_id)s] %(message)s"

_ROTATING_INSTALLED = False


def install_rotating_log(
    log_dir: Path,
    *,
    filename: str = "cinesort.log",
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
    level: int = logging.INFO,
) -> Optional[Path]:
    """Installe un RotatingFileHandler sur le root logger.

    Idempotent : si deja installe, no-op (retourne None).
    Le scrubber est aussi attache au handler pour que les fichiers
    de log soient scrubbed (defense en profondeur).

    Retourne le path absolu du fichier de log courant, ou None si
    l'install a deja eu lieu / est impossible.
    """
    global _ROTATING_INSTALLED
    if _ROTATING_INSTALLED:
        return None
    log_dir = Path(log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        return None
    log_path = log_dir / filename

    try:
        handler = logging.handlers.RotatingFileHandler(
            str(log_path),
            maxBytes=int(max_bytes),
            backupCount=int(backup_count),
            encoding="utf-8",
        )
    except (OSError, PermissionError):
        return None

    handler.setLevel(int(level))
    handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
    # H-3 : scrubber sur le handler pour proteger le fichier de log
    handler.addFilter(SecretsScrubFilter())
    # V3-04 polish v7.7.0 : injecter run_id + request_id dans chaque record
    # ecrit dans le fichier (le filter sur le root logger ne suffit pas pour
    # les records propages vers ce handler). Import local pour eviter cycle.
    try:
        from cinesort.infra.log_context import attach_filter_to_handler

        attach_filter_to_handler(handler)
    except ImportError:  # pragma: no cover — defensive
        pass

    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > int(level):
        root.setLevel(int(level))

    _ROTATING_INSTALLED = True
    return log_path
