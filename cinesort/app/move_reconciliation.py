"""CR-1 audit QA 20260429 — reconciliation des moves orphelins au boot.

Au demarrage de CineSortApi, on examine la table apply_pending_moves :
chaque entree represente un shutil.move qui a commence mais n'a pas
ete confirme termine (DELETE pending) — donc soit l'app a crashe au
milieu, soit le DELETE lui-meme a echoue.

Pour chaque entree, on inspecte l'etat reel du filesystem :

| Etat src | Etat dst | Verdict | Action |
|---|---|---|---|
| absent | present, empreinte OK | move termine, DELETE rate | cleanup, pas de notif |
| absent | present, empreinte KO | `mismatched` : autre fichier a dst | cleanup + warning CRITICAL |
| absent | present, empreinte illisible | `unverified` : doute non leve | cleanup + warning |
| present | absent | Move pas commence ou rollback FS | cleanup, pas de notif |
| present | present | CONFLIT : duplication, intervention humaine | cleanup + warning HIGH |
| absent | absent | Fichier perdu (FS corruption, AV scan) | cleanup + warning CRITICAL |

L'entree est cleanup dans tous les cas pour eviter qu'elle traine
indefiniment. Les warnings sont remontes via la liste retournee, que
le caller peut afficher dans l'UI / logs.

Verification d'identite (issue #512) : `exists()` seul ne prouve RIEN. Un
homonyme a dst (ancien apply skippe, re-scan, fichier remis a la main) suffisait
a rendre un verdict `completed` sur un fichier DIFFERENT. `apply_pending_moves`
stocke justement l'empreinte capturee AVANT le move (`src_sha1` + `src_size`) :
on la confronte au contenu reel de dst avant de conclure.

Ce que ce controle change, exactement — et ce qu'il ne change PAS. L'entree
pending est supprimee apres examen dans TOUS les cas, `mismatched` compris : il
ne s'agit donc pas de rendre un deplacement annulable. La trace que lisent
l'undo et le rollback est `apply_operations` (cf. `apply_rollback.py`), pas
cette table, qui n'est qu'un journal write-ahead d'atomicite. Ce qui change,
c'est qu'un `completed` mensonger devient une alerte honnete : l'operateur
apprend que la destination ne contient pas son fichier, au lieu de croire le
deplacement termine.

Portee reelle de la branche MOVE_DIR. Le SEUL site de production qui ecrit
aujourd'hui une empreinte dans `apply_pending_moves` est le MOVE_FILE de
`apply_core` (`atomic_move(..., src_sha1=..., src_size=...)`). Les moves de
DOSSIER n'en passent aucune, et `apply_single` renomme le dossier hors journal
(son empreinte part dans `record_apply_op` -> `apply_operations`, une autre
table). `_dir_contains_fingerprint` est donc atteinte depuis la production dans
le seul cas ou la destination d'un MOVE_FILE se trouve occupee par un DOSSIER ;
pour un vrai MOVE_DIR elle est PREVENTIVE, prete pour le jour ou ces sites
porteront une empreinte.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from cinesort.app.apply_core import sha1_quick

_logger = logging.getLogger(__name__)


def _expected_fingerprint(entry: Dict[str, Any]) -> tuple[str, Optional[int]]:
    """Empreinte du fichier capturee AVANT le move : (sha1_quick, taille).

    `src_sha1` vaut None quand la capture avait echoue (NAS deconnecte, timeout
    sha1) ; `src_size` vaut None sur les lignes ecrites avant l'ajout de ces
    colonnes. Une taille de 0 est une valeur legitime, d'ou le test
    `is not None` plutot qu'une verite booleenne.
    """
    sha1 = str(entry.get("src_sha1") or "").strip().lower()
    raw_size = entry.get("src_size")
    try:
        size = int(raw_size) if raw_size is not None else None
    except (TypeError, ValueError):
        size = None
    return sha1, size


def _file_matches_fingerprint(path: Path, expected_sha1: str, expected_size: int) -> Optional[bool]:
    """True / False / None (verification impossible : lecture en echec)."""
    try:
        actual_size = path.stat().st_size
    except (OSError, PermissionError):
        return None
    if actual_size != expected_size:
        # Ce n'est PAS qu'une optimisation, c'est une garde a part entiere :
        # `sha1_quick` (apply_core.py:273) ne hashe que les 8 premiers Mo + les 8
        # derniers Mo des le moment ou le fichier atteint 16 Mio. Deux fichiers de
        # TAILLES DIFFERENTES qui partagent ces deux extremites ont donc exactement
        # le meme sha1_quick : seule la comparaison de taille les separe.
        return False
    actual_sha1 = sha1_quick(path).strip().lower()
    if not actual_sha1:
        # sha1_quick renvoie "" sur OSError/timeout : on ne sait pas, on ne
        # transforme pas cette ignorance en succes.
        return None
    return actual_sha1 == expected_sha1


def _dir_contains_fingerprint(dst: Path, expected_sha1: str, expected_size: int) -> Optional[bool]:
    """dst est un DOSSIER : l'empreinte est celle d'un fichier, pas du dossier.

    Deux cas y menent : la destination d'un MOVE_FILE occupee par un dossier (le
    seul atteignable depuis la production aujourd'hui, cf. docstring du module),
    et un vrai MOVE_DIR le jour ou ces sites poseront une empreinte.

    `apply_core.find_main_video_in_folder` prend le plus gros fichier video du
    dossier, sans recursion : on cherche donc, a la racine de dst, un fichier
    qui porte l'empreinte enregistree (taille ET sha1, cf.
    `_file_matches_fingerprint`).
    """
    try:
        entries = [child for child in dst.iterdir() if child.is_file()]
    except (OSError, PermissionError):
        return None
    unverifiable = False
    for child in entries:
        matched = _file_matches_fingerprint(child, expected_sha1, expected_size)
        if matched is True:
            return True
        if matched is None:
            unverifiable = True
    # Aucun fichier ne correspond : on ne conclut a l'absence que si on a pu
    # tous les examiner.
    return None if unverifiable else False


def _classify_dst_present(entry: Dict[str, Any], dst: Path) -> str:
    """src absent + dst present : `completed` seulement si dst EST bien notre fichier."""
    expected_sha1, expected_size = _expected_fingerprint(entry)
    if not expected_sha1 or expected_size is None:
        # Aucune empreinte enregistree (capture en echec, ligne d'une version
        # anterieure) : rien de plus a affirmer que l'ancien comportement.
        return "completed"
    matched: Optional[bool]
    if dst.is_file():
        matched = _file_matches_fingerprint(dst, expected_sha1, expected_size)
    elif dst.is_dir():
        # dst est un dossier : l'empreinte est celle d'un fichier, on la cherche
        # a l'interieur (MOVE_FILE dont la cible est squattee par un dossier, ou
        # MOVE_DIR le jour ou ces sites poseront une empreinte).
        matched = _dir_contains_fingerprint(dst, expected_sha1, expected_size)
    else:
        # Ni fichier ni dossier alors que `exists()` etait vrai juste avant :
        # dst a disparu entre-temps, ou est un objet non fingerprintable.
        # Indecidable — surtout pas un `completed`.
        matched = None
    if matched is True:
        return "completed"
    if matched is None:
        return "unverified"
    return "mismatched"


def _classify_pending(entry: Dict[str, Any]) -> str:
    """Determine le verdict de reconciliation pour une entree pending.

    Retourne : 'completed' | 'rolled_back' | 'duplicated' | 'lost'
               | 'mismatched' | 'unverified'
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
        # Le DELETE pending a peut-etre juste rate — mais il faut le PROUVER :
        # un homonyme a dst n'est pas notre fichier (issue #512).
        return _classify_dst_present(entry, dst)
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
        "completed": int,          # moves termines (identite verifiee), DELETE rate
        "rolled_back": int,        # moves jamais commences
        "duplicated": List[dict],  # CRITIQUE : fichier aux 2 endroits
        "lost": List[dict],        # CRITIQUE : fichier perdu
        "mismatched": List[dict],  # CRITIQUE : dst occupe par un AUTRE fichier
        "unverified": List[dict],  # identite de dst non verifiable (lecture KO)
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
        "mismatched": [],
        "unverified": [],
        "messages": [],
    }
    if store is None:
        return report

    try:
        pending = store.apply.list_pending_moves()
    except (sqlite3.Error, OSError, AttributeError):
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
        elif verdict == "mismatched":
            report["mismatched"].append(entry)
            msg = (
                f"IDENTITE INCOHERENTE : apres crash, la destination existe mais ne "
                f"contient PAS le fichier qui avait ete deplace ({op_type}) — son "
                f"empreinte (taille + sha1) ne correspond pas a celle relevee avant "
                f"le deplacement. Source : {src}. Destination : {dst}. Le fichier "
                f"d'origine est probablement perdu et la destination appartient a "
                f"autre chose : verifiez manuellement AVANT tout undo ou nouvel apply."
            )
            report["messages"].append(msg)
            _logger.error("reconcile: %s", msg)
        elif verdict == "unverified":
            report["unverified"].append(entry)
            msg = (
                f"IDENTITE NON VERIFIEE : la destination existe apres crash mais n'a "
                f"pas pu etre lue pour confirmer qu'il s'agit bien du fichier deplace "
                f"({op_type}). Source : {src}. Destination : {dst}. Verifiez que le "
                f"support est accessible, puis controlez ce fichier a la main."
            )
            report["messages"].append(msg)
            _logger.warning("reconcile: %s", msg)

        # Cleanup l'entree dans tous les cas — elle ne sert plus a rien
        # une fois examinee (ou serait re-examinee a chaque boot).
        try:
            store.apply.delete_pending_move(int(entry.get("id", 0)))
        except (sqlite3.Error, OSError, AttributeError):
            _logger.exception(
                "reconcile: delete_pending_move(id=%s) echoue",
                entry.get("id"),
            )

    if report["duplicated"] or report["lost"] or report["mismatched"]:
        report["messages"].insert(
            0,
            f"Reconciliation : {len(report['duplicated'])} conflit(s), "
            f"{len(report['lost'])} fichier(s) perdu(s) et "
            f"{len(report['mismatched'])} destination(s) occupee(s) par un autre "
            f"fichier detectes apres crash. Verifiez les warnings ci-dessous.",
        )

    return report


def reconcile_at_boot(store: Any, *, notify: Optional[Any] = None) -> Dict[str, Any]:
    """Variante boot : appelle reconcile_pending_moves et notifie l'UI.

    Si `notify` est un NotifyService (avec methode .notify(event, title, body)),
    on push une notification si des conflits, des fichiers perdus ou des
    destinations d'identite incoherente sont detectes. `unverified` n'y figure
    pas : c'est un doute a lever, pas une perte constatee.
    """
    report = reconcile_pending_moves(store)
    if notify is not None and (report["duplicated"] or report["lost"] or report["mismatched"]):
        try:
            n_dup = len(report["duplicated"])
            n_lost = len(report["lost"])
            n_mismatched = len(report["mismatched"])
            notify.notify(
                "error",
                "Reconciliation apres crash",
                f"{n_dup} conflit(s), {n_lost} fichier(s) perdu(s) et {n_mismatched} "
                f"destination(s) incoherente(s) detectes. Verifiez les logs.",
            )
        except Exception:
            # Robustesse boot : un notify defaillant (RuntimeError, ValueError, etc.)
            # ne doit JAMAIS empecher la suite du boot. On logge et on continue.
            _logger.exception("reconcile_at_boot: notify echoue")
    return report
