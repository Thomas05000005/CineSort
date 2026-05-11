"""CR-1 audit QA 20260429 — journal write-ahead pour atomicite shutil.move.

Probleme : shutil.move sur volumes differents fait copy + delete. Si l'app
crashe (BSOD, kill task, coupure secteur) entre les deux, on peut avoir :
- Fichier present a src ET a dst (copy partielle ou delete echoue).
- Fichier present nulle part (cas extreme, FS corruption).
- Etat DB qui ne reflete pas la realite (record_apply_op a eu lieu ou pas).

Solution : INSERT dans apply_pending_moves AVANT le shutil.move, DELETE
APRES move reussi. Si crash entre les deux, l'entree reste pour
reconciliation au prochain boot (cf cinesort.app.move_reconciliation).

Ce module est intentionnellement tolerant : un failure du journal ne
DOIT JAMAIS empecher un move legitime. En pire cas, on perd la
garantie d'atomicite mais l'apply continue.
"""

from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Union

_logger = logging.getLogger(__name__)


@contextmanager
def journaled_move(
    store: Any,
    *,
    src: Union[Path, str],
    dst: Union[Path, str],
    op_type: str,
    batch_id: Optional[str] = None,
    src_sha1: Optional[str] = None,
    src_size: Optional[int] = None,
    row_id: Optional[str] = None,
) -> Iterator[Optional[int]]:
    """Context manager wrappant shutil.move avec journal write-ahead.

    Usage :
        with journaled_move(store, src=src, dst=dst, op_type="MOVE_FILE"):
            shutil.move(str(src), str(dst))

    - INSERT pending move dans la DB AVANT d'entrer dans le with.
    - Si le with se termine sans exception : DELETE pending move (move OK).
    - Si exception dans le with : l'entree pending reste, sera detectee par
      reconcile_pending_moves() au prochain boot.

    Parametres :
        store : instance SQLiteStore avec methodes insert_pending_move /
                delete_pending_move. Si None, le context manager devient un
                no-op (le caller fait juste son shutil.move sans journal).
        src, dst : paths source et destination.
        op_type : MOVE_FILE | MOVE_DIR | QUARANTINE_FILE | QUARANTINE_DIR.
        batch_id : optionnel, batch d'apply auquel appartient le move.
        src_sha1, src_size : optionnel, fingerprint pour aide a la
                            reconciliation (verification d'identite du fichier).
        row_id : optionnel, identifiant de la row PlanRow d'origine.

    Yield : pending_id (int) si l'INSERT a reussi, sinon None. Permet aux
            tests d'observer le flux interne.
    """
    pending_id: Optional[int] = None
    if store is not None:
        try:
            pending_id = store.insert_pending_move(
                op_type=op_type,
                src_path=str(src),
                dst_path=str(dst),
                batch_id=batch_id,
                src_sha1=src_sha1,
                src_size=src_size,
                row_id=row_id,
            )
        except Exception as exc:
            _logger.warning(
                "journaled_move: insert_pending_move failed (op=%s, src=%s): %s",
                op_type,
                src,
                exc,
            )
            pending_id = None

    yield pending_id  # exception ici sort du context, l'entree pending reste

    # Sortie sans exception : le move (ou ce qui est dans le with) a reussi.
    # On peut nettoyer le journal.
    if pending_id is not None:
        try:
            store.delete_pending_move(pending_id)
        except Exception as exc:
            _logger.warning(
                "journaled_move: delete_pending_move(id=%d) failed: %s",
                pending_id,
                exc,
            )


def safe_move(
    store: Any,
    *,
    src: Union[Path, str],
    dst: Union[Path, str],
    op_type: str,
    batch_id: Optional[str] = None,
    src_sha1: Optional[str] = None,
    src_size: Optional[int] = None,
    row_id: Optional[str] = None,
) -> None:
    """Drop-in replacement pour `shutil.move(str(src), str(dst))` avec journal.

    Equivalent a :
        with journaled_move(store, ..., op_type=...):
            shutil.move(str(src), str(dst))

    Mais plus concis pour les call sites qui font juste un move atomique
    sans operation supplementaire dans le with.
    """
    with journaled_move(
        store,
        src=src,
        dst=dst,
        op_type=op_type,
        batch_id=batch_id,
        src_sha1=src_sha1,
        src_size=src_size,
        row_id=row_id,
    ):
        shutil.move(str(src), str(dst))


class RecordOpWithJournal:
    """Wrapper callable autour d'un record_op classique, qui porte aussi une
    reference vers le SQLiteStore et le batch_id pour permettre journaled_move().

    Permet de propager le store via la chaine d'appels apply_core sans toucher
    aux signatures des fonctions internes (toutes recoivent deja record_op).
    Les sites de shutil.move recuperent store via :
        store = getattr(record_op, "journal_store", None)
        batch_id = getattr(record_op, "journal_batch_id", None)

    Si record_op est un callable simple (test, code legacy), getattr retourne
    None et le helper atomic_move() retombe sur shutil.move direct.
    """

    def __init__(self, callable_fn: Any, *, store: Any = None, batch_id: Optional[str] = None) -> None:
        self._fn = callable_fn
        self.journal_store = store
        self.journal_batch_id = batch_id

    def __call__(self, payload: Any) -> Any:
        if self._fn is None:
            return None
        return self._fn(payload)


def atomic_move(
    record_op: Any,
    *,
    src: Union[Path, str],
    dst: Union[Path, str],
    op_type: str,
    src_sha1: Optional[str] = None,
    src_size: Optional[int] = None,
    row_id: Optional[str] = None,
) -> None:
    """Helper drop-in pour remplacer `shutil.move(str(src), str(dst))` dans
    apply_core.py / cleanup.py.

    Si record_op est un RecordOpWithJournal (ou tout objet avec attribut
    journal_store), on enrobe shutil.move dans journaled_move(). Sinon on
    fait juste shutil.move direct (rétro-compatibilite tests).
    """
    store = getattr(record_op, "journal_store", None)
    batch_id = getattr(record_op, "journal_batch_id", None)
    if store is None:
        shutil.move(str(src), str(dst))
        return
    with journaled_move(
        store,
        src=src,
        dst=dst,
        op_type=op_type,
        batch_id=batch_id,
        src_sha1=src_sha1,
        src_size=src_size,
        row_id=row_id,
    ):
        shutil.move(str(src), str(dst))
