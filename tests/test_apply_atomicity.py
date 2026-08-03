"""CR-1 audit QA 20260429 — tests d'atomicite des moves apply.

Couvre :
- Helper journaled_move : INSERT pending avant move, DELETE apres succes,
  laisse l'entree si exception dans le with.
- Wrapper RecordOpWithJournal : drop-in autour de record_op qui porte
  store + batch_id pour permettre atomic_move.
- Helper atomic_move : utilise journal si record_op porte journal_store,
  sinon fallback shutil.move direct.
- reconcile_pending_moves : verdicts (completed, rolled_back, duplicated, lost,
  mismatched, unverified) + cleanup de l'entree dans tous les cas.
- Issue #512 : `completed` exige la verification d'identite du fichier a dst
  (src_sha1 + src_size releves avant le move), pas un simple `exists()`.
- Mixin _apply_mixin : insert/delete/list/count pending moves.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cinesort.app.apply_core import sha1_quick
from cinesort.app.move_journal import (
    RecordOpWithJournal,
    atomic_move,
    journaled_move,
)
from cinesort.app.move_reconciliation import (
    _classify_dst_present,
    _classify_pending,
    _dir_contains_fingerprint,
    _file_matches_fingerprint,
    reconcile_at_boot,
    reconcile_pending_moves,
)
from cinesort.infra.db.sqlite_store import SQLiteStore


def _make_store() -> tuple[SQLiteStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_atomicity_"))
    store = SQLiteStore(tmp / "test.sqlite", busy_timeout_ms=5000)
    store.initialize()
    return store, tmp


class JournaledMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_journaled_move_clean_path(self) -> None:
        """Sortie OK du with → entree DELETE apres yield, table vide."""
        with journaled_move(
            self.store,
            src="C:/src.mkv",
            dst="C:/dst.mkv",
            op_type="MOVE_FILE",
            batch_id="batch1",
        ) as pending_id:
            self.assertIsNotNone(pending_id)
            # Pendant le with, l'entree existe
            pending = self.store.apply.list_pending_moves()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["op_type"], "MOVE_FILE")

        # Apres le with sans exception : l'entree est supprimee
        self.assertEqual(self.store.apply.count_pending_moves(), 0)

    def test_journaled_move_with_exception_leaves_entry(self) -> None:
        """Exception dans le with → entree reste pour reconciliation."""
        with (
            self.assertRaises(RuntimeError),
            journaled_move(
                self.store,
                src="C:/src.mkv",
                dst="C:/dst.mkv",
                op_type="MOVE_FILE",
            ),
        ):
            raise RuntimeError("simulated crash mid-move")

        # L'entree pending est restee (sera traitee par reconciliation au boot)
        pending = self.store.apply.list_pending_moves()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["src_path"], "C:/src.mkv")

    def test_journaled_move_no_store_is_noop(self) -> None:
        """store=None → pas d'erreur, pas de journal."""
        with journaled_move(
            None,
            src="C:/src.mkv",
            dst="C:/dst.mkv",
            op_type="MOVE_FILE",
        ) as pending_id:
            self.assertIsNone(pending_id)

    def test_journaled_move_persists_metadata(self) -> None:
        """src_sha1, src_size, row_id sont bien persistes."""
        with journaled_move(
            self.store,
            src="C:/film.mkv",
            dst="D:/films/film.mkv",
            op_type="MOVE_FILE",
            batch_id="b42",
            src_sha1="deadbeef",
            src_size=123456,
            row_id="row_007",
        ):
            pass  # no-op
        # Apres le with, l'entree est supprimee — on doit re-INSERT pour verifier
        with journaled_move(
            self.store,
            src="C:/film2.mkv",
            dst="D:/films/film2.mkv",
            op_type="MOVE_DIR",
            batch_id="b42",
            src_sha1="cafebabe",
            src_size=999,
            row_id="row_008",
        ):
            pending = self.store.apply.list_pending_moves()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["src_sha1"], "cafebabe")
            self.assertEqual(pending[0]["src_size"], 999)
            self.assertEqual(pending[0]["row_id"], "row_008")
            self.assertEqual(pending[0]["batch_id"], "b42")

    def test_journaled_move_filter_by_batch_id(self) -> None:
        """list_pending_moves(batch_id=...) filtre correctement."""
        # Inserer 2 entrees dans 2 batches differents — manuellement, sans
        # cleanup automatique (on simule des entrees orphelines).
        self.store.apply.insert_pending_move(op_type="MOVE_FILE", src_path="a", dst_path="b", batch_id="b1")
        self.store.apply.insert_pending_move(op_type="MOVE_FILE", src_path="c", dst_path="d", batch_id="b2")

        all_pending = self.store.apply.list_pending_moves()
        self.assertEqual(len(all_pending), 2)

        b1_pending = self.store.apply.list_pending_moves(batch_id="b1")
        self.assertEqual(len(b1_pending), 1)
        self.assertEqual(b1_pending[0]["src_path"], "a")


class AtomicMoveTests(unittest.TestCase):
    """Tests du helper atomic_move : journaled si record_op a journal_store."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src = self._tmp / "source.mkv"
        self.dst = self._tmp / "subdir" / "dest.mkv"
        self.src.write_bytes(b"video data")
        self.dst.parent.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_atomic_move_with_record_op_with_journal(self) -> None:
        """RecordOpWithJournal → atomic_move utilise le journal."""
        record_op_calls = []
        plain_record = lambda payload: record_op_calls.append(payload)
        wrapped = RecordOpWithJournal(plain_record, store=self.store, batch_id="batch_x")

        atomic_move(wrapped, src=self.src, dst=self.dst, op_type="MOVE_FILE")

        # Move s'est bien fait
        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())
        # Journal pending vide (DELETE apres succes)
        self.assertEqual(self.store.apply.count_pending_moves(), 0)

    def test_atomic_move_with_plain_record_op_falls_back(self) -> None:
        """record_op simple (function) → atomic_move fait shutil.move direct."""
        record_op_calls = []
        plain_record = lambda payload: record_op_calls.append(payload)

        atomic_move(plain_record, src=self.src, dst=self.dst, op_type="MOVE_FILE")

        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())
        self.assertEqual(self.store.apply.count_pending_moves(), 0)

    def test_atomic_move_with_none_record_op(self) -> None:
        """record_op=None → atomic_move fait shutil.move direct."""
        atomic_move(None, src=self.src, dst=self.dst, op_type="MOVE_FILE")
        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())

    def test_record_op_with_journal_is_callable(self) -> None:
        """RecordOpWithJournal proxie l'appel vers le record_op original."""
        record_op_calls = []
        plain_record = lambda payload: record_op_calls.append(payload)
        wrapped = RecordOpWithJournal(plain_record, store=self.store)

        wrapped({"op_type": "TEST"})
        self.assertEqual(len(record_op_calls), 1)
        self.assertEqual(record_op_calls[0]["op_type"], "TEST")

    def test_record_op_with_journal_handles_none_callable(self) -> None:
        """Si callable_fn=None, __call__ ne plante pas."""
        wrapped = RecordOpWithJournal(None, store=self.store)
        self.assertIsNone(wrapped({"op_type": "TEST"}))

    def test_per_row_wrapper_preserves_journal_write_ahead(self) -> None:
        """GATE AUDIT 2026-06-10 (HIGH) : le wrapper par-row d'apply_core doit
        conserver journal_store/batch_id (avant le fix, la fonction nue les
        perdait -> atomic_move tombait sur shutil.move SANS journal write-ahead).

        On reproduit la construction exacte d'apply_core : un record_op porteur
        de journal, enrobe d'un wrapper qui injecte row_id.
        """
        # Spy sur insert_pending_move pour prouver que le write-ahead se declenche.
        orig_insert = self.store.apply.insert_pending_move
        insert_calls = []

        def _spy(**kw):
            insert_calls.append(kw)
            return orig_insert(**kw)

        self.store.apply.insert_pending_move = _spy  # type: ignore[method-assign]

        recorded = []
        outer = RecordOpWithJournal(lambda payload: recorded.append(payload), store=self.store, batch_id="b1")

        # --- Construction identique a apply_core (boucle apply par-row) ---
        def _inject_row_id(payload, _rid="row-42", _ref=outer):
            if isinstance(payload, dict) and not payload.get("row_id"):
                payload["row_id"] = _rid
            _ref(payload)

        row_record_op = RecordOpWithJournal(
            _inject_row_id,
            store=getattr(outer, "journal_store", None),
            batch_id=getattr(outer, "journal_batch_id", None),
        )
        # -----------------------------------------------------------------

        # (a) le write-ahead doit passer par le journal a travers le wrapper
        atomic_move(row_record_op, src=self.src, dst=self.dst, op_type="MOVE_FILE")
        self.assertEqual(len(insert_calls), 1, "journal write-ahead non declenche")
        self.assertEqual(insert_calls[0]["op_type"], "MOVE_FILE")
        self.assertEqual(insert_calls[0]["batch_id"], "b1", "batch_id non propage")
        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())
        self.assertEqual(self.store.apply.count_pending_moves(), 0)

        # (b) l'appel du wrapper injecte toujours row_id et forwarde au record_op
        row_record_op({"op_type": "MOVE_FILE"})
        self.assertEqual(recorded[-1]["row_id"], "row-42")


class ReconcilePendingMovesTests(unittest.TestCase):
    """Tests de reconcile_pending_moves : 4 verdicts + cleanup."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src = self._tmp / "src.mkv"
        self.dst = self._tmp / "dst.mkv"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_pending_entry(self, src_exists: bool, dst_exists: bool) -> dict:
        if src_exists:
            self.src.write_bytes(b"src")
        if dst_exists:
            self.dst.write_bytes(b"dst")
        return {
            "id": 1,
            "src_path": str(self.src),
            "dst_path": str(self.dst),
            "op_type": "MOVE_FILE",
        }

    def test_classify_completed(self) -> None:
        """src absent + dst present → completed (le DELETE pending a juste rate)."""
        entry = self._make_pending_entry(src_exists=False, dst_exists=True)
        self.assertEqual(_classify_pending(entry), "completed")

    def test_classify_rolled_back(self) -> None:
        """src present + dst absent → rolled_back (move pas commence)."""
        entry = self._make_pending_entry(src_exists=True, dst_exists=False)
        self.assertEqual(_classify_pending(entry), "rolled_back")

    def test_classify_duplicated(self) -> None:
        """src present + dst present → duplicated (CONFLIT critique)."""
        entry = self._make_pending_entry(src_exists=True, dst_exists=True)
        self.assertEqual(_classify_pending(entry), "duplicated")

    def test_classify_lost(self) -> None:
        """src absent + dst absent → lost (CRITIQUE, fichier perdu)."""
        entry = self._make_pending_entry(src_exists=False, dst_exists=False)
        self.assertEqual(_classify_pending(entry), "lost")

    def test_reconcile_empty_returns_empty_report(self) -> None:
        """Pas d'entrees pending → rapport vide, pas d'effet."""
        report = reconcile_pending_moves(self.store)
        self.assertEqual(report["examined"], 0)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 0)
        self.assertEqual(report["duplicated"], [])
        self.assertEqual(report["lost"], [])

    def test_reconcile_completed_cleanup(self) -> None:
        """completed → entree supprimee, pas de message warning."""
        # Move termine : src absent, dst present
        self.dst.write_bytes(b"dst data")
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self.src),
            dst_path=str(self.dst),
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(report["examined"], 1)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(self.store.apply.count_pending_moves(), 0)
        # Pas de warning critique
        self.assertEqual(report["duplicated"], [])
        self.assertEqual(report["lost"], [])

    def test_reconcile_duplicated_warning(self) -> None:
        """duplicated → message warning + entree supprimee."""
        self.src.write_bytes(b"src")
        self.dst.write_bytes(b"dst")
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self.src),
            dst_path=str(self.dst),
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(len(report["duplicated"]), 1)
        # Au moins un message warning + un message d'entete
        self.assertTrue(any("CONFLIT" in m for m in report["messages"]))
        self.assertEqual(self.store.apply.count_pending_moves(), 0)

    def test_reconcile_lost_warning(self) -> None:
        """lost → message critique + entree supprimee."""
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self.src),
            dst_path=str(self.dst),
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(len(report["lost"]), 1)
        self.assertTrue(any("FICHIER PERDU" in m for m in report["messages"]))
        self.assertEqual(self.store.apply.count_pending_moves(), 0)

    def test_reconcile_with_none_store_returns_empty(self) -> None:
        """store=None → no-op, rapport vide, pas d'erreur."""
        report = reconcile_pending_moves(None)
        self.assertEqual(report["examined"], 0)


class ReconcileAtBootTests(unittest.TestCase):
    """Tests de reconcile_at_boot : variante avec notification UI."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_reconcile_at_boot_no_conflicts_no_notify(self) -> None:
        """Pas de conflits → notify pas appele."""
        notify = MagicMock()
        notify.notify = MagicMock()
        # Une entree completed (sans warning)
        dst = self._tmp / "ok.mkv"
        dst.write_bytes(b"data")
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "missing.mkv"),
            dst_path=str(dst),
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(report["completed"], 1)
        notify.notify.assert_not_called()

    def test_reconcile_at_boot_with_conflicts_notifies(self) -> None:
        """Conflits → notify.notify appele avec event 'error'."""
        notify = MagicMock()
        notify.notify = MagicMock()
        # Entree duplicated (les 2 fichiers existent)
        src = self._tmp / "src.mkv"
        dst = self._tmp / "dst.mkv"
        src.write_bytes(b"a")
        dst.write_bytes(b"b")
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(len(report["duplicated"]), 1)
        notify.notify.assert_called_once()
        args, kwargs = notify.notify.call_args
        self.assertEqual(args[0], "error")  # event = "error"

    def test_reconcile_at_boot_notify_failure_does_not_crash(self) -> None:
        """Si notify.notify lance, le boot continue (rapport quand meme retourne)."""
        notify = MagicMock()
        notify.notify = MagicMock(side_effect=RuntimeError("notify down"))
        # Entree lost
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "ghost1.mkv"),
            dst_path=str(self._tmp / "ghost2.mkv"),
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(len(report["lost"]), 1)


class ClassifyPendingIdentityTests(unittest.TestCase):
    """Issue #512 — `completed` doit etre PROUVE, pas deduit de `exists()`.

    `apply_pending_moves` stocke l'empreinte relevee avant le move (`src_sha1`,
    `src_size`). Sans la consulter, un simple homonyme a dst (ancien apply
    skippe, re-scan, fichier remis a la main) faisait rendre `completed` sur un
    fichier DIFFERENT : l'entree pending etait supprimee, la trace du
    deplacement perdue, et l'undo n'avait plus rien a defaire.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_reconcile_identity_"))
        self.src = self._tmp / "src.mkv"
        self.dst = self._tmp / "dst.mkv"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @staticmethod
    def _entry(src: Path, dst: Path, *, sha1: str | None, size: int | None, op_type: str = "MOVE_FILE") -> dict:
        return {
            "id": 1,
            "src_path": str(src),
            "dst_path": str(dst),
            "op_type": op_type,
            "src_sha1": sha1,
            "src_size": size,
        }

    def _write(self, path: Path, payload: bytes) -> tuple[str, int]:
        """Ecrit `payload` et retourne l'empreinte telle que l'apply la releve."""
        path.write_bytes(payload)
        return sha1_quick(path), path.stat().st_size

    # --- MOVE_FILE ---------------------------------------------------------

    def test_dst_est_bien_le_fichier_deplace_donne_completed(self) -> None:
        sha1, size = self._write(self.dst, b"le vrai film" * 64)
        entry = self._entry(self.src, self.dst, sha1=sha1, size=size)
        self.assertEqual(_classify_pending(entry), "completed")

    def test_homonyme_de_meme_taille_mais_autre_contenu_nest_pas_completed(self) -> None:
        """Le coeur du defaut : meme nom, meme taille, contenu DIFFERENT."""
        payload = b"le vrai film" * 64
        reference = self._tmp / "reference.mkv"
        expected_sha1, expected_size = self._write(reference, payload)
        # Un AUTRE fichier, exactement de la meme taille, occupe la destination.
        self.dst.write_bytes(b"un autre film" * 59 + b"@" * (len(payload) - len(b"un autre film" * 59)))
        self.assertEqual(self.dst.stat().st_size, expected_size, "le leurre doit avoir la meme taille")
        entry = self._entry(self.src, self.dst, sha1=expected_sha1, size=expected_size)
        self.assertEqual(_classify_pending(entry), "mismatched")

    def test_homonyme_de_taille_differente_nest_pas_completed(self) -> None:
        _, expected_size = self._write(self._tmp / "reference.mkv", b"x" * 4096)
        self.dst.write_bytes(b"y" * 128)
        entry = self._entry(self.src, self.dst, sha1="a" * 40, size=expected_size)
        self.assertEqual(_classify_pending(entry), "mismatched")

    def test_sans_empreinte_enregistree_le_verdict_reste_completed(self) -> None:
        """Retro-compat : lignes anterieures aux colonnes d'empreinte."""
        self.dst.write_bytes(b"peu importe")
        self.assertEqual(_classify_pending(self._entry(self.src, self.dst, sha1=None, size=None)), "completed")
        self.assertEqual(_classify_pending(self._entry(self.src, self.dst, sha1="", size=0)), "completed")

    def test_taille_illisible_dans_la_ligne_ne_bloque_pas(self) -> None:
        """Une `src_size` non entiere (ligne corrompue) ne fait pas planter le boot."""
        self.dst.write_bytes(b"peu importe")
        entry = self._entry(self.src, self.dst, sha1="a" * 40, size=None)
        entry["src_size"] = "pas-un-entier"
        self.assertEqual(_classify_pending(entry), "completed")

    # --- MOVE_DIR : l'empreinte est celle de la video INTERNE ---------------

    def test_move_dir_contenant_la_video_attendue_donne_completed(self) -> None:
        """`apply_single` hashe la video principale, pas le dossier."""
        moved_dir = self._tmp / "Inception (2010)"
        moved_dir.mkdir()
        (moved_dir / "Extras").mkdir()
        (moved_dir / "movie.nfo").write_bytes(b"<nfo/>")
        sha1, size = self._write(moved_dir / "movie.mkv", b"pellicule" * 512)
        entry = self._entry(self.src, moved_dir, sha1=sha1, size=size, op_type="MOVE_DIR")
        self.assertEqual(_classify_pending(entry), "completed")

    def test_move_dir_sans_la_video_attendue_nest_pas_completed(self) -> None:
        payload = b"pellicule" * 512
        expected_sha1, expected_size = self._write(self._tmp / "reference.mkv", payload)
        squatter = self._tmp / "Inception (2010)"
        squatter.mkdir()
        # Meme taille, autre contenu : le pre-filtre taille ne suffit pas.
        (squatter / "movie.mkv").write_bytes(b"autre film" * 460 + b"#" * (len(payload) - 4600))
        self.assertEqual((squatter / "movie.mkv").stat().st_size, expected_size)
        entry = self._entry(self.src, squatter, sha1=expected_sha1, size=expected_size, op_type="MOVE_DIR")
        self.assertEqual(_classify_pending(entry), "mismatched")

    # --- indecidable -------------------------------------------------------

    def test_dst_disparu_entre_exists_et_stat_donne_unverified(self) -> None:
        """TOCTOU reel : `exists()` a dit oui, la verification ne trouve plus rien.

        On ne transforme pas cette ignorance en `completed`.
        """
        entry = self._entry(self.src, self.dst, sha1="a" * 40, size=1024)
        self.assertFalse(self.dst.exists())
        self.assertEqual(_classify_dst_present(entry, self.dst), "unverified")

    def test_scan_de_dossier_impossible_donne_unverified(self) -> None:
        """`iterdir()` sur ce qui n'est pas un dossier -> indecidable, pas False."""
        self.dst.write_bytes(b"je suis un fichier")
        self.assertIsNone(_dir_contains_fingerprint(self.dst, "a" * 40, 18))

    def test_empreinte_de_fichier_disparu_est_indecidable(self) -> None:
        self.assertIsNone(_file_matches_fingerprint(self._tmp / "jamais.mkv", "a" * 40, 10))


class ReconcileIdentityReportTests(unittest.TestCase):
    """Issue #512 — le verdict d'identite doit remonter dans le rapport."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_dst_occupe_par_un_autre_fichier_nest_pas_compte_completed(self) -> None:
        payload = b"le vrai film" * 128
        reference = self._tmp / "reference.mkv"
        reference.write_bytes(payload)
        expected_sha1 = sha1_quick(reference)
        expected_size = reference.stat().st_size

        dst = self._tmp / "dst.mkv"
        dst.write_bytes(b"impostuer!!!" * 128)
        self.assertEqual(dst.stat().st_size, expected_size, "le leurre doit avoir la meme taille")

        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "src.mkv"),
            dst_path=str(dst),
            src_sha1=expected_sha1,
            src_size=expected_size,
        )
        report = reconcile_pending_moves(self.store)

        self.assertEqual(report["examined"], 1)
        self.assertEqual(report["completed"], 0, "un fichier different n'est pas un move termine")
        self.assertEqual(len(report["mismatched"]), 1)
        self.assertTrue(
            any("IDENTITE INCOHERENTE" in m for m in report["messages"]),
            f"message d'alerte attendu: {report['messages']}",
        )
        self.assertEqual(self.store.apply.count_pending_moves(), 0, "l'entree reste nettoyee")

    def test_dst_verifie_reste_compte_completed(self) -> None:
        dst = self._tmp / "dst.mkv"
        dst.write_bytes(b"le vrai film" * 128)
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "src.mkv"),
            dst_path=str(dst),
            src_sha1=sha1_quick(dst),
            src_size=dst.stat().st_size,
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(report["mismatched"], [])
        self.assertEqual(report["messages"], [])

    def test_mismatch_declenche_la_notification_de_boot(self) -> None:
        notify = MagicMock()
        notify.notify = MagicMock()
        dst = self._tmp / "dst.mkv"
        dst.write_bytes(b"impostuer" * 100)
        self.store.apply.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "src.mkv"),
            dst_path=str(dst),
            src_sha1="d" * 40,
            src_size=dst.stat().st_size,
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(len(report["mismatched"]), 1)
        notify.notify.assert_called_once()
        args, _kwargs = notify.notify.call_args
        self.assertEqual(args[0], "error")


if __name__ == "__main__":
    unittest.main()
