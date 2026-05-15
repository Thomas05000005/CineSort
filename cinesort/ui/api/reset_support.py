"""V3-09 — Reset all user data (avec backup de securite)."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)


def _resolve_state_dir(api: Any) -> Optional[Path]:
    """Recupere le state_dir de l'API.

    Supporte les deux conventions :
    - methode `_get_state_dir()` (utilisee par les fakes de tests)
    - attribut `_state_dir` (utilise par CineSortApi en production)
    """
    if hasattr(api, "_get_state_dir"):
        try:
            value = api._get_state_dir()
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            logger.warning("reset_support: _get_state_dir a echoue (%s), fallback _state_dir", exc)
            value = None
        if value:
            return Path(value)
    if hasattr(api, "_state_dir"):
        value = getattr(api, "_state_dir", None)
        if value:
            return Path(value)
    return None


def reset_all_user_data(api: Any, confirmation_text: str) -> dict:
    """V3-09 — Reinitialise toutes les donnees utilisateur.

    Etapes :
    1. Verifier que confirmation_text == "RESET"
    2. Creer un backup ZIP du dossier user-data complet
    3. Supprimer : DB SQLite, settings.json, runs/, cache TMDb, perceptual reports
    4. Preserver : logs (utiles pour debug si reset cause un probleme)

    Returns:
        {ok: bool, backup_path?: str, removed?: list[str], error?: str}
    """
    if confirmation_text != "RESET":
        return _err_response(
            "Confirmation invalide (attendu 'RESET')",
            category="validation",
            level="info",
            log_module=__name__,
            key="error",
        )

    state_path = _resolve_state_dir(api)
    if state_path is None or not state_path.exists():
        return _err_response(
            "Dossier user-data introuvable", category="state", level="info", log_module=__name__, key="error"
        )

    backup_stem = state_path.parent / f"cinesort_backup_before_reset_{int(time.time())}"
    backup_path = backup_stem.with_suffix(".zip")

    try:
        # 1. Backup securite : ZIP complet du dossier user-data
        logger.info("V3-09 : creation backup avant reset -> %s", backup_path)
        shutil.make_archive(str(backup_stem), "zip", root_dir=str(state_path))

        # 2. Suppression selective (preserve logs/)
        removed: list[str] = []
        for item in state_path.iterdir():
            if item.name == "logs":
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                try:
                    item.unlink(missing_ok=True)
                except OSError:
                    continue
            removed.append(item.name)

        logger.warning(
            "V3-09 : reset complet effectue (%d items supprimes). Backup : %s",
            len(removed),
            backup_path,
        )
        return {
            "ok": True,
            "backup_path": str(backup_path),
            "removed": removed,
        }
    except (OSError, shutil.Error) as exc:
        logger.exception("V3-09 : echec reset")
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__, key="error")


def get_user_data_size(api: Any) -> dict:
    """V3-09 — Retourne la taille du dossier user-data (pour affichage UI)."""
    state_path = _resolve_state_dir(api)
    if state_path is None or not state_path.exists():
        return {"size_mb": 0, "items": 0}

    total = 0
    items = 0
    for f in state_path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
                items += 1
            except OSError:
                continue
    return {
        "size_mb": round(total / (1024 * 1024), 2),
        "items": items,
    }
