"""CR-1 audit QA 20260429 — reconciliation des moves orphelins au boot.

Au demarrage de CineSortApi, on examine la table apply_pending_moves :
chaque entree represente un shutil.move qui a commence mais n'a pas
ete confirme termine (DELETE pending) — donc soit l'app a crashe au
milieu, soit le DELETE lui-meme a echoue.

Pour chaque entree, on inspecte l'etat reel du filesystem :

| Etat src | Etat dst | Verdict | Action |
|---|---|---|---|
| absent | present | OK probable (move termine, DELETE rate) | cleanup, pas de notif |
| present | absent | Move pas commence ou rollback FS | cleanup, pas de notif |
| present | present | CONFLIT : duplication, intervention humaine | cleanup + warning HIGH |
| absent | absent | Fichier perdu (FS corruption, AV scan) | cleanup + warning CRITICAL |

L'entree est cleanup dans tous les cas pour eviter qu'elle traine
indefiniment. Les warnings sont remontes via la liste retournee, que
le caller peut afficher dans l'UI / logs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)


def _classify_pending(entry: Dict[str, Any]) -> str:
    """Determine le verdict de reconciliation pour une entree pending.

    Retourne : 'completed' | 'rolled_back' | 'duplicated' | 'lost'
    """
    src = Path(str(entry.get("src_path") or ""))
    dst = Path(str(entry.get("dst_path") or ""))
    src_exists = False
    dst_exists = False
    try:
        src_exists = src.exists()
    except (OSError, PermissionError):
        src_exists = False
    try:
        dst_exists = dst.exists()
    except (OSError, PermissionError):
        dst_exists = False

    if not src_exists and dst_exists:
        return "completed"  # le move a fini, juste le DELETE pending qui a rate
    if src_exists and not dst_exists:
        return "rolled_back"  # le move n'a pas commence ou shutil a rollback
    if src_exists and dst_exists:
        return "duplicated"  # CRITIQUE : fichier present aux 2 endroits
    return "lost"  # CRITIQUE : fichier nulle part


def reconcile_pending_moves(store: Any) -> Dict[str, Any]:
    """Examine les pending moves orphelins et tente une reconciliation.

    Retourne un rapport :
    {
        "examined": int,           # nombre d'entrees examinees
        "completed": int,          # moves termines, juste DELETE rate
        "rolled_back": int,        # moves jamais commences
        "duplicated": List[dict],  # CRITIQUE : fichier aux 2 endroits
        "lost": List[dict],        # CRITIQUE : fichier perdu
        "messages": List[str],     # messages a logger / afficher a l'UI
    }

    Tolere store None (no-op, retourne rapport vide).
    """
    report: Dict[str, Any] = {
        "examined": 0,
        "completed": 0,
        "rolled_back": 0,
        "duplicated": [],
        "lost": [],
        "messages": [],
    }
    if store is None:
        return report

    try:
        pending = store.list_pending_moves()
    except Exception:
        _logger.exception("reconcile_pending_moves: list_pending_moves echoue")
        return report

    if not pending:
        return report

    _logger.info(
        "reconcile_pending_moves: %d entree(s) orpheline(s) detectee(s) au boot",
        len(pending),
    )

    for entry in pending:
        report["examined"] += 1
        verdict = _classify_pending(entry)
        src = entry.get("src_path", "?")
        dst = entry.get("dst_path", "?")
        op_type = entry.get("op_type", "?")

        if verdict == "completed":
            report["completed"] += 1
            _logger.info(
                "reconcile: %s OK (DELETE rate, fichier present a dst): %s -> %s",
                op_type,
                src,
                dst,
            )
        elif verdict == "rolled_back":
            report["rolled_back"] += 1
            _logger.info(
                "reconcile: %s rollback FS (fichier toujours a src): %s",
                op_type,
                src,
            )
        elif verdict == "duplicated":
            report["duplicated"].append(entry)
            msg = (
                f"CONFLIT reconciliation : fichier present a la fois a la source "
                f"et a la destination apres crash ({op_type}). Source : {src}. "
                f"Destination : {dst}. Choisissez la bonne version manuellement "
                f"avant de relancer un apply."
            )
            report["messages"].append(msg)
            _logger.warning("reconcile: %s", msg)
        elif verdict == "lost":
            report["lost"].append(entry)
            msg = (
                f"FICHIER PERDU : ni source ni destination existent apres crash "
                f"({op_type}). Source attendue : {src}. Destination attendue : "
                f"{dst}. Verifiez vos backups et l'antivirus."
            )
            report["messages"].append(msg)
            _logger.error("reconcile: %s", msg)

        # Cleanup l'entree dans tous les cas — elle ne sert plus a rien
        # une fois examinee (ou serait re-examinee a chaque boot).
        try:
            store.delete_pending_move(int(entry.get("id", 0)))
        except Exception:
            _logger.exception(
                "reconcile: delete_pending_move(id=%s) echoue",
                entry.get("id"),
            )

    if report["duplicated"] or report["lost"]:
        report["messages"].insert(
            0,
            f"Reconciliation : {len(report['duplicated'])} conflit(s) et "
            f"{len(report['lost'])} fichier(s) perdu(s) detectes apres crash. "
            f"Verifiez les warnings ci-dessous.",
        )

    return report


def reconcile_at_boot(store: Any, *, notify: Optional[Any] = None) -> Dict[str, Any]:
    """Variante boot : appelle reconcile_pending_moves et notifie l'UI.

    Si `notify` est un NotifyService (avec methode .notify(event, title, body)),
    on push une notification "warning" si conflits/perdus detectes.
    """
    report = reconcile_pending_moves(store)
    if notify is not None and (report["duplicated"] or report["lost"]):
        try:
            n_dup = len(report["duplicated"])
            n_lost = len(report["lost"])
            notify.notify(
                "error",
                "Reconciliation apres crash",
                f"{n_dup} conflit(s) et {n_lost} fichier(s) perdu(s) detectes. Verifiez les logs.",
            )
        except Exception:
            _logger.exception("reconcile_at_boot: notify echoue")
    return report
