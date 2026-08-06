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

import errno
import logging
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Union

_logger = logging.getLogger(__name__)

# ERROR_NOT_SAME_DEVICE : Windows ne renseigne pas toujours errno.EXDEV sur un
# rename inter-volumes, on teste donc aussi le winerror brut.
_WINERROR_NOT_SAME_DEVICE = 17

#: Paliers d'attente avant de reessayer un renommage de dossier refuse par
#: Windows. Volontairement minuscules au depart : la fenetre mesuree est de
#: l'ordre de la microseconde (cf. `renommer_avec_reprise`), et le premier
#: palier suffit dans la quasi-totalite des cas. Le total plafonne a ~0,3 s,
#: donc le cout est nul quand tout va bien et borne quand rien ne va.
_REPRISES_RENAME_S = (0.0, 0.005, 0.02, 0.05, 0.1, 0.15)


def _is_cross_device(exc: OSError) -> bool:
    return getattr(exc, "errno", None) == errno.EXDEV or getattr(exc, "winerror", None) == _WINERROR_NOT_SAME_DEVICE


def renommer_avec_reprise(source: Path, cible: Path) -> None:
    """Renomme un dossier, en reessayant brievement sur un refus d'acces Windows.

    MESURE (#965), sur `main`, %TEMP% neuf et vide, machine au repos :

        sans instrumentation                          : 8 echecs / 20
        avec une simple enveloppe Python sur `rename` :  0 echec  / 20
        (Fisher exact bilateral : p ~ 0,004)

    Autrement dit, **le seul fait d'ajouter un appel de fonction Python avant
    le renommage fait disparaitre l'echec**. La fenetre de course se compte
    donc en microsecondes : un handle est en cours de liberation sur un enfant
    du dossier — sur Windows, un fichier ouvert sans `FILE_SHARE_DELETE`
    empeche le renommage de son dossier parent — et l'appel arrive juste avant
    que la fermeture ne soit effective.

    Ce qui a ete ECARTE par la mesure, pour ne pas y revenir :
      - la saturation de `%TEMP%` (l'echec survient dans un `%TEMP%` vide, et
        le remplir ne l'aggrave pas de facon distinguable : p = 0,38) ;
      - un cycle de references retenant un objet fichier (forcer `gc.collect()`
        avant chaque renommage ne previent rien : 3/25 contre 4/25) ;
      - `sha1_quick`, qui ouvre bien le fichier video juste avant mais le ferme
        de facon deterministe (`with path.open`).

    La reprise ne MASQUE pas un vrai verrou : un dossier reellement tenu par un
    autre processus epuise les paliers et l'exception d'origine est relancee
    telle quelle. Elle ne transforme donc jamais un echec en succes silencieux
    — elle cesse de perdre un deplacement pour une course de quelques
    microsecondes, sur le chemin qui deplace les films de l'utilisateur.

    Ce helper habite ce module — et non `apply_core` ou il est ne — parce que
    `_rename_or_cross_device_copy` ci-dessous est le passage OBLIGE de tous les
    deplacements de dossier entier (`atomic_move(..., allow_copy_fallback=False)`) :
    doublons ecartes, marques pour suppression, dossier de collection, mise en
    quarantaine, bucket de nettoyage, rollback et undo. Le laisser dans
    `apply_core` obligeait `move_journal` a l'importer, donc a fabriquer un
    cycle ; ici l'arete existe deja dans le bon sens.
    """
    derniere: Optional[OSError] = None
    for attente in _REPRISES_RENAME_S:
        if attente:
            time.sleep(attente)
        try:
            source.rename(cible)
            if derniere is not None:
                _logger.info(
                    "apply: renommage de %s reussi apres reprise (%s a l'essai precedent)",
                    source.name,
                    derniere.__class__.__name__,
                )
            return
        except PermissionError as exc:
            # Uniquement le refus d'acces : un `FileExistsError` ou un chemin
            # invalide ne se resoudra pas en attendant, et le reessayer
            # retarderait un diagnostic juste.
            if getattr(exc, "winerror", None) not in (5, 32):
                raise
            derniere = exc
    assert derniere is not None
    raise derniere


def _rename_or_cross_device_copy(src: Union[Path, str], dst: Union[Path, str]) -> None:
    """`os.rename` d'abord ; ne degrade en copie que sur un VRAI EXDEV.

    `shutil.move` retombe sur copytree + rmtree des que `os.rename` echoue, y
    compris sur un banal verrou Windows sur UN fichier interne (indexeur,
    antivirus, apercu Explorateur, editeur de .nfo). Mesure sur Windows 11 avec
    un simple `open()` sur `BBB/film.srt` :

    - `Path.rename` -> PermissionError WinError 5, source INTACTE (3 fichiers),
      destination ABSENTE ; rien n'a bouge.
    - `shutil.move`  -> PermissionError WinError 32, destination contenant les
      3 fichiers ET source amputee de `film.nfo` : contenu dedouble, source
      eventree.

    Sur un chemin destructif, l'erreur doit aller dans le sens RESTRICTIF : ne
    rien deplacer plutot que dedoubler. La copie reste le seul recours quand les
    deux chemins sont sur des volumes differents, et ce cas-la seul la declenche.

    Le renommage passe par `renommer_avec_reprise` (#965) : la course de quelques
    microsecondes qui faisait perdre un deplacement dans `apply_single` frappe
    ICI AUSSI, et sur des chemins ou elle coute plus cher — le rollback et l'undo
    sont le filet de secours de l'utilisateur. La reprise ne change RIEN au
    partage des roles ci-dessous : `renommer_avec_reprise` ne rattrape que le
    refus d'acces Windows (WinError 5/32), donc un vrai EXDEV la traverse intact
    et tombe comme avant dans la degradation en copie.
    """
    try:
        renommer_avec_reprise(Path(src), Path(dst))
    except OSError as exc:
        if not _is_cross_device(exc):
            raise
        shutil.move(str(src), str(dst))


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

    - INSERT pending move dans la DB AVANT d'entrer dans le with. Une erreur
      inattendue ici REMONTE (rien n'a encore bouge sur le disque : fail-closed).
    - Si le with se termine sans exception : DELETE pending move (move OK).
      Une erreur ici est AVALEE et loggee (issue #670) : les octets ont deja
      bouge, et laisser l'exception sortir ferait sauter le `record_apply_op`
      qui suit chez l'appelant — le move deviendrait non annulable.
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
            pending_id = store.apply.insert_pending_move(
                op_type=op_type,
                src_path=str(src),
                dst_path=str(dst),
                batch_id=batch_id,
                src_sha1=src_sha1,
                src_size=src_size,
                row_id=row_id,
            )
        except (sqlite3.Error, OSError, AttributeError) as exc:
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
    #
    # Issue #670 — ce nettoyage est POST-DEPLACEMENT : les octets ont deja bouge
    # sur le disque quand on arrive ici. Toute exception qui s'echappe d'ici
    # remonte au call site (apply_core), qui execute `record_apply_op` APRES
    # `atomic_move` : le move ne serait alors JAMAIS journalise dans
    # apply_operations, donc plus annulable, alors que le dossier a bel et bien
    # change de place. Le tuple etroit (sqlite3.Error, OSError, AttributeError)
    # laissait passer tout le reste, et `delete_pending_move` peut lever hors de
    # ce tuple : `_ensure_schema_group` -> `_schema_group_tables` leve KeyError,
    # le bootstrap de schema leve RuntimeError, un pending_id non convertible
    # leve TypeError/ValueError.
    #
    # Sur ce chemin destructif, le sens RESTRICTIF est donc d'AVALER : perdre
    # l'entree pending ne coute rien (la reconciliation au boot la classera
    # "completed" puisque src a disparu et dst existe), alors que perdre l'undo
    # laisse un etat mixte non annulable. L'asymetrie avec l'INSERT ci-dessus est
    # deliberee : la, rien n'a encore bouge, donc une erreur inattendue doit
    # remonter (fail-closed avant tout deplacement).
    if pending_id is not None:
        try:
            store.apply.delete_pending_move(pending_id)
        except Exception:  # noqa: BLE001 - nettoyage best-effort, ne doit jamais invalider un move reussi
            _logger.exception(
                "journaled_move: delete_pending_move(id=%s) a echoue ; le move est DEJA "
                "applique sur disque et reste journalise/annulable, l'entree pending "
                "sera reconciliee au prochain boot",
                pending_id,
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
    allow_copy_fallback: bool = True,
) -> None:
    """Helper drop-in pour remplacer `shutil.move(str(src), str(dst))` dans
    apply_core.py / cleanup.py.

    Si record_op est un RecordOpWithJournal (ou tout objet avec attribut
    journal_store), on enrobe le deplacement dans journaled_move(). Sinon on
    deplace direct (rétro-compatibilite tests).

    `allow_copy_fallback=False` (chemins qui deplacent un DOSSIER entier, cf.
    `cleanup._move_dirs_to_bucket`) : `os.rename` d'abord, degradation en copie
    UNIQUEMENT sur un vrai EXDEV. Cf. `_rename_or_cross_device_copy` — un verrou
    Windows sur un seul fichier interne ne doit pas dedoubler le contenu et
    eventrer la source. Le journal write-ahead reste pose dans les deux cas :
    c'est lui qui rend le deplacement reconciliable si l'app meurt entre le
    deplacement et le `record_apply_op` du call site.
    """
    move_fn = shutil.move if allow_copy_fallback else _rename_or_cross_device_copy
    store = getattr(record_op, "journal_store", None)
    batch_id = getattr(record_op, "journal_batch_id", None)
    if store is None:
        move_fn(str(src), str(dst))
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
        move_fn(str(src), str(dst))
