"""VP-A rollback_forward integration tests.

Couvre l'AC-3 (rollback FS+DB atomique) du plan VP-A :
- Rollback `MOVE_FILE` : fichier deja deplace est replace dans src.
- Rollback `MOVE_DIR` : dossier deplace est replace dans src.
- Rollback partiel (5 sur 10 ops echouent -> tous annules avec status='PARTIAL'
  ou 'DONE' selon le cas).
- Si DB rollback echoue (mock), FS revert est quand meme tente + log d'audit.
- Coordination avec undo classique : rollback_status='ROLLED_BACK_BY_ATOMIC'
  est SEPARE de undo_status (memo plan VP-A open question #5).

Tests non couverts ici (cf. test_apply_atomic_mode_v77 pour migrations + repo
unit tests, et integration full apply_changes au niveau test_apply_undo_*).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

from cinesort.app.apply_rollback import (
    ROLLBACK_DONE,
    ROLLBACK_FAILED,
    ROLLBACK_PARTIAL,
    rollback_forward,
)
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.cinesort_api import CineSortApi


def _make_store() -> tuple[SQLiteStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_atomic_rb_"))
    store = SQLiteStore(tmp / "test.sqlite", busy_timeout_ms=5000)
    store.initialize()
    return store, tmp


def _create_file(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class RollbackForwardEmptyBatchTests(unittest.TestCase):
    """Edge cases : batch_id vide, batch sans ops, etc."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_batch_id_returns_failed(self) -> None:
        result = rollback_forward(self.store, "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["rollback_status"], ROLLBACK_FAILED)

    def test_batch_with_no_ops_returns_done(self) -> None:
        """Batch existe mais aucune op journalisee : rollback success no-op."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)
        self.assertEqual(result["counts"]["done"], 0)


class RollbackForwardMoveFileTests(unittest.TestCase):
    """Rollback FS : fichiers deja deplaces sont restaures dans src."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rollback_reverts_move_file(self) -> None:
        """AC-3 : fichier au dst doit revenir au src apres rollback."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        src = self.src_root / "movie1.mkv"
        dst = self.dst_root / "movie1.mkv"
        # Simuler un MOVE_FILE deja execute : fichier present a dst, absent a src
        _create_file(dst, size=128)
        self.assertFalse(src.exists())

        # Journaliser l'op
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"], f"Rollback should succeed, got {result}")
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)
        self.assertEqual(result["counts"]["done"], 1)
        self.assertEqual(result["counts"]["failed"], 0)
        # FS : fichier revenu au src
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())

        # DB : status final marque
        mode = self.store.apply.get_atomic_mode(batch_id)
        self.assertEqual(mode["rollback_status"], ROLLBACK_DONE)

    def test_rollback_reverts_quarantine_ops(self) -> None:
        """GATE AUDIT 2026-06-10 (HIGH) : QUARANTINE_FILE et QUARANTINE_DIR sont
        journalisees reversible=True et DOIVENT etre revertees (dst _review ->
        src). Avant le fix elles etaient SKIPPED 'non revert-able', laissant les
        fichiers en quarantaine tout en retournant ok=True (FS non restaure)."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=True,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        # QUARANTINE_FILE : un fichier video deplace en _review
        src_file = self.src_root / "film.mkv"
        dst_file = self.dst_root / "_review" / "film" / "film.mkv"
        _create_file(dst_file, size=256)
        # QUARANTINE_DIR : un dossier complet deplace en _review
        src_dir = self.src_root / "MonFilm (2020)"
        dst_dir = self.dst_root / "_review" / "MonFilm (2020)"
        dst_dir.mkdir(parents=True, exist_ok=True)
        _create_file(dst_dir / "movie.mkv", size=128)

        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="QUARANTINE_FILE",
            src_path=str(src_file),
            dst_path=str(dst_file),
            reversible=True,
        )
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=2,
            op_type="QUARANTINE_DIR",
            src_path=str(src_dir),
            dst_path=str(dst_dir),
            reversible=True,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"], f"got {result}")
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)
        self.assertEqual(result["counts"]["done"], 2, "les 2 QUARANTINE doivent etre revertees")
        self.assertEqual(result["counts"]["skipped"], 0)
        # FS reellement restaure : tout est revenu a src, plus rien en _review
        self.assertTrue(src_file.exists())
        self.assertFalse(dst_file.exists())
        self.assertTrue((src_dir / "movie.mkv").exists())
        self.assertFalse(dst_dir.exists())

    def test_rollback_skips_irreversible_ops(self) -> None:
        """Op avec reversible=False : skipped, pas FS touch."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        src = self.src_root / "irr.mkv"
        dst = self.dst_root / "irr.mkv"
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=False,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertEqual(result["counts"]["skipped"], 1)
        self.assertEqual(result["counts"]["done"], 0)
        # FS inchange : fichier reste au dst
        self.assertTrue(dst.exists())
        self.assertFalse(src.exists())

    def test_rollback_skips_when_dst_missing(self) -> None:
        """Si le fichier a dst a disparu (manuel, cleanup), skip + log audit."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        src = self.src_root / "ghost.mkv"
        dst = self.dst_root / "ghost.mkv"
        # On NE CREE PAS dst — il est manquant
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        audit_calls = []

        def audit_fn(level, msg):
            audit_calls.append((level, msg))

        result = rollback_forward(self.store, batch_id, audit_fn=audit_fn)
        self.assertEqual(result["counts"]["skipped"], 1)
        self.assertEqual(result["counts"]["done"], 0)
        # Log d'audit emis
        self.assertTrue(any("dst manquant" in msg for _, msg in audit_calls))

    def test_rollback_skips_when_src_already_exists(self) -> None:
        """Si src existe deja (collision), skip + log."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        src = self.src_root / "exists.mkv"
        dst = self.dst_root / "exists.mkv"
        _create_file(src)
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertEqual(result["counts"]["skipped"], 1)
        # Les 2 fichiers restent en place
        self.assertTrue(src.exists())
        self.assertTrue(dst.exists())


class RollbackForwardMixedBatchTests(unittest.TestCase):
    """Plusieurs ops dans un meme batch : reverse order + partial status."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rollback_5_of_10_partial(self) -> None:
        """Plan VP-A test integration : 5 sur 10 deplacements echouent.

        On simule 10 ops : 5 sont revertables (dst present), 5 sont skipped
        (dst manquant). Le rollback final est DONE (aucun FAILED) avec 5
        done + 5 skipped.
        """
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        for i in range(10):
            src = self.src_root / f"movie{i}.mkv"
            dst = self.dst_root / f"movie{i}.mkv"
            if i < 5:
                _create_file(dst)  # revert-able
            # i >= 5 : dst manquant -> skip
            self.store.apply.append_apply_operation(
                batch_id=batch_id,
                op_index=i + 1,
                op_type="MOVE_FILE",
                src_path=str(src),
                dst_path=str(dst),
                reversible=True,
            )

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["done"], 5)
        self.assertEqual(result["counts"]["skipped"], 5)
        self.assertEqual(result["counts"]["failed"], 0)
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)

        # Verifier que les 5 fichiers reverted sont au src
        for i in range(5):
            self.assertTrue((self.src_root / f"movie{i}.mkv").exists())
            self.assertFalse((self.dst_root / f"movie{i}.mkv").exists())

    def test_rollback_reverse_order_execution(self) -> None:
        """Les ops sont revertes dans l'ordre inverse (LIFO) du journal."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )

        for i in range(3):
            src = self.src_root / f"m{i}.mkv"
            dst = self.dst_root / f"m{i}.mkv"
            _create_file(dst)
            self.store.apply.append_apply_operation(
                batch_id=batch_id,
                op_index=i + 1,
                op_type="MOVE_FILE",
                src_path=str(src),
                dst_path=str(dst),
                reversible=True,
            )

        result = rollback_forward(self.store, batch_id)
        # On verifie via le tableau details : op_index doit etre decroissant
        op_indices = [d["op_index"] for d in result["details"]]
        self.assertEqual(op_indices, [3, 2, 1], "Rollback en ordre inverse (LIFO)")


class RollbackForwardDbFailureTests(unittest.TestCase):
    """AC-3 : si DB rollback echoue, FS revert tente + audit log."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_db_mark_failure_degrades_to_partial(self) -> None:
        """Si mark_rollback_status final echoue, on retourne ROLLBACK_PARTIAL
        avec FS revert deja effectue (audit log emis)."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        src = self.src_root / "m.mkv"
        dst = self.dst_root / "m.mkv"
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        original_mark = self.store.apply.mark_rollback_status
        call_count = {"n": 0}

        def flaky_mark(*args, **kwargs):
            call_count["n"] += 1
            # Premier appel (IN_PROGRESS) OK ; deuxieme (final) leve
            if call_count["n"] >= 2:
                raise sqlite3.OperationalError("DB locked simulated")
            return original_mark(*args, **kwargs)

        audit_calls = []

        def audit_fn(level, msg):
            audit_calls.append((level, msg))

        with patch.object(self.store.apply, "mark_rollback_status", side_effect=flaky_mark):
            result = rollback_forward(self.store, batch_id, audit_fn=audit_fn)

        # FS revert a quand meme eu lieu
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())
        # Statut degrade en PARTIAL (DB tracking failed)
        self.assertEqual(result["rollback_status"], ROLLBACK_PARTIAL)
        # Audit log emis sur l'echec DB
        self.assertTrue(any("FAILED" in msg for _, msg in audit_calls))


class RollbackForwardCoordinationUndoTests(unittest.TestCase):
    """Plan VP-A open question #5 : rollback_status SEPARE de undo_status.

    Verifie que rollback_forward NE TOUCHE PAS aux flags undo_status
    existants sur apply_operations. La chaine undo manuelle
    (`get_last_reversible_apply_batch` + `mark_apply_operation_undo_status`)
    reste autorite, et rollback_status est dans la table apply_batch_modes.
    """

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rollback_marks_undo_status_done(self) -> None:
        # R8-012 (F2-c) : apres un revert atomique REUSSI, l'undo_status OP-LEVEL doit
        # refleter que l'op est annulee ('DONE'). Avant, rollback_forward ne touchait
        # PAS undo_status (restait 'PENDING') -> l'historique (history_support.py:300)
        # et les compteurs undone_ops/pending_ops (apply.py:391) affichaient un batch
        # deja reverti comme "pending_ops=total, undone_ops=0" = jamais annule. Le
        # rollback_status reste SEPARE et coherent dans apply_batch_modes (les deux
        # co-existent : op-level DONE + rollback_status DONE). Aucune interaction avec
        # l'undo manuel : un batch rollback-atomique n'est pas status='DONE' donc jamais
        # propose a l'undo (cf test_get_last_reversible_apply_batch_not_impacted).
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        src = self.src_root / "m.mkv"
        dst = self.dst_root / "m.mkv"
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        rollback_forward(self.store, batch_id)

        ops = self.store.apply.list_apply_operations(batch_id=batch_id)
        # R8-012 : undo_status reflete desormais le revert ('DONE')
        self.assertEqual(ops[0]["undo_status"], "DONE")

        # rollback_status SEPARE dans apply_batch_modes (coherent)
        mode = self.store.apply.get_atomic_mode(batch_id)
        self.assertEqual(mode["rollback_status"], ROLLBACK_DONE)

    def test_get_last_reversible_apply_batch_not_impacted(self) -> None:
        """`get_last_reversible_apply_batch` se base sur status='DONE'.
        Un batch rollback-atomique (status='FAILED') ne doit PAS apparaitre.
        """
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1",
            dry_run=False,
            quarantine_unapproved=False,
        )
        # Le batch reste PENDING -> get_last_reversible doit NE PAS le voir
        result = self.store.apply.get_last_reversible_apply_batch("r1")
        self.assertIsNone(result)

        # Apres rollback atomique (qui ne change pas status='DONE'), idem.
        self.store.apply.upsert_atomic_mode(batch_id, True)
        rollback_forward(self.store, batch_id)

        result_after = self.store.apply.get_last_reversible_apply_batch("r1")
        # Toujours None (batch n'est jamais passe a DONE)
        self.assertIsNone(result_after)


class ApplyChangesAtomicRollbackIntegrationTests(unittest.TestCase):
    """AC-3 BOUT-EN-BOUT : apply REEL + `apply_atomic=True` + crash injecte.

    Pourquoi cette classe existe (finding N38) : les tests de signature de
    `ApplyChangesBackwardCompatTests` ci-dessous n'exercent AUCUN
    comportement. Mesure : en remplacant `apply_support._atomic_rollback_forward`
    par un no-op qui MENT (`{'ok': True, 'rollback_status':
    'ROLLED_BACK_BY_ATOMIC', counts a 0}`), les 20 tests des deux fichiers
    apply/undo cites par l'audit restaient VERTS — le cablage
    `apply_support.py:2891` n'etait couvert par rien.

    Ici on monte une vraie bibliotheque jetable, on scanne, on applique pour de
    vrai, et on fait exploser le 3e film APRES que les deux premiers aient ete
    deplaces sur disque. Ce qui doit tenir :
      - le filesystem revient STRICTEMENT au snapshot initial ;
      - `apply_batches.status` = 'ROLLED_BACK_BY_ATOMIC' ;
      - `apply_batch_modes.rollback_status` = 'ROLLED_BACK_BY_ATOMIC' ;
      - la reponse porte `atomic_rollback` avec `counts.done >= 2, failed == 0`.

    Le test-temoin `..._without_atomic_flag_leaves_half_moved_library` prouve
    que l'injection deplace REELLEMENT des dossiers : sans lui, un rollback
    fictif sur une bibliotheque jamais touchee passerait pour un succes.
    """

    _SCAN_TIMEOUT_S = 60.0

    def setUp(self) -> None:
        import cinesort.domain.core as core_mod

        self._base = Path(tempfile.mkdtemp(prefix="cinesort_atomic_e2e_"))
        self.root = self._base / "root"
        self.state_dir = self._base / "state"
        self.root.mkdir()
        self.state_dir.mkdir()
        self._patcher = patch.object(core_mod, "MIN_VIDEO_BYTES", 1)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        # rmtree tolerant : sous Windows le store SQLite du JobRunner peut
        # garder un handle quelques instants apres le test.
        shutil.rmtree(self._base, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def _settings(self) -> dict:
        return {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
            "probe_backend": "none",
        }

    def _snapshot(self) -> dict:
        """{D:relpath -> '', F:relpath -> sha1[:12]} sous self.root."""
        import hashlib
        import os

        out: dict = {}
        for dirpath, _dirnames, filenames in os.walk(self.root):
            d = Path(dirpath)
            rel = d.relative_to(self.root)
            if rel != Path("."):
                out[f"D:{rel.as_posix()}"] = ""
            for fn in filenames:
                p = d / fn
                out[f"F:{(rel / fn).as_posix()}"] = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
        return out

    def _build_library(self) -> None:
        for folder, video in (
            ("Alpha.Film.2011.1080p", "Alpha.Film.2011.1080p.mkv"),
            ("Beta.Film.2012.1080p", "Beta.Film.2012.1080p.mkv"),
            ("Gamma.Film.2013.1080p", "Gamma.Film.2013.1080p.mkv"),
        ):
            _create_file(self.root / folder / video, size=2048)
            (self.root / folder / "movie.nfo").write_text("<movie/>", encoding="utf-8")

    def _scan_and_decide(self):
        from tests._helpers import wait_run_done

        api = CineSortApi()
        start = api.run.start_plan(self._settings())
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        wait_run_done(api, run_id, timeout_s=self._SCAN_TIMEOUT_S)
        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), 3, [r.get("folder") for r in rows])
        decisions = {
            str(r["row_id"]): {
                "ok": True,
                "title": r.get("proposed_title"),
                "year": r.get("proposed_year"),
            }
            for r in rows
        }
        return api, run_id, decisions

    def _crash_on_third_row(self):
        """patch context : les 2 premiers films sont VRAIMENT deplaces, le 3e explose.

        RuntimeError est choisi a dessein : la boucle de `apply_rows` rattrape
        PermissionError / OSError / ValueError / TypeError par row (echec propre
        sans interrompre le batch). Il faut une exception NON rattrapee pour
        atteindre le `except Exception` de `apply_changes` et donc le rollback.
        """
        from cinesort.app import apply_core

        real = apply_core.apply_single
        calls = {"n": 0}

        def _boom(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 3:
                raise RuntimeError("crash injecte (test N38) apres 2 films deplaces")
            return real(*args, **kwargs)

        return patch.object(apply_core, "apply_single", _boom), calls

    # -- tests ------------------------------------------------------------
    def test_atomic_rollback_restores_fs_and_marks_batch(self) -> None:
        self._build_library()
        api, run_id, decisions = self._scan_and_decide()
        snap0 = self._snapshot()

        patcher, calls = self._crash_on_third_row()
        with patcher:
            res = api.run.apply(run_id, decisions, False, False, apply_atomic=True)

        self.assertEqual(calls["n"], 3, "l'injection n'a pas atteint le 3e film")
        self.assertFalse(res.get("ok"), res)

        # 1) Le filesystem est revenu A L'IDENTIQUE (coeur de l'AC-3).
        snap_end = self._snapshot()
        self.assertEqual(
            snap_end,
            snap0,
            "rollback atomique incomplet : "
            f"en trop={sorted(set(snap_end) - set(snap0))} "
            f"manquants={sorted(set(snap0) - set(snap_end))}",
        )

        # 2) Synthese remontee au caller.
        summary = res.get("atomic_rollback") or {}
        self.assertEqual(summary.get("rollback_status"), ROLLBACK_DONE, summary)
        self.assertTrue(summary.get("ok"), summary)
        counts = summary.get("counts") or {}
        self.assertGreaterEqual(int(counts.get("done") or 0), 2, summary)
        self.assertEqual(int(counts.get("failed") or 0), 0, summary)

        # 3) Etat DB : batch + mode atomique tous deux marques rollback.
        store, _runner = api._get_or_create_infra(self.state_dir)
        batch_id = str(res.get("apply_batch_id") or "")
        self.assertTrue(batch_id, res)
        batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=10)
        self.assertEqual([b.get("status") for b in batches], ["ROLLED_BACK_BY_ATOMIC"], batches)
        mode = store.apply.get_atomic_mode(batch_id) or {}
        self.assertEqual(mode.get("rollback_status"), ROLLBACK_DONE, mode)

        # 4) Le batch rollback ne doit PAS etre propose a l'undo classique.
        self.assertIsNone(store.apply.get_last_reversible_apply_batch(run_id))

    def test_without_atomic_flag_leaves_half_moved_library(self) -> None:
        """Temoin : sans `apply_atomic`, le meme crash laisse la biblio A MOITIE
        deplacee. C'est ce qui prouve que l'injection touche vraiment le disque
        et que le test ci-dessus ne verifie pas un rollback sur un no-op."""
        self._build_library()
        api, run_id, decisions = self._scan_and_decide()
        snap0 = self._snapshot()

        patcher, calls = self._crash_on_third_row()
        with patcher:
            res = api.run.apply(run_id, decisions, False, False)

        self.assertEqual(calls["n"], 3)
        self.assertFalse(res.get("ok"), res)
        self.assertNotIn("atomic_rollback", res)

        snap_end = self._snapshot()
        self.assertNotEqual(snap_end, snap0, "le crash injecte n'a deplace AUCUN dossier")
        created = sorted(k for k in set(snap_end) - set(snap0) if k.startswith("D:") and "/" not in k[2:])
        self.assertEqual(created, ["D:Alpha Film (2011)", "D:Beta Film (2012)"], created)

        store, _runner = api._get_or_create_infra(self.state_dir)
        batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=10)
        self.assertEqual([b.get("status") for b in batches], ["FAILED"], batches)


class ApplyChangesBackwardCompatTests(unittest.TestCase):
    """AC-1 : signature `apply_changes(apply_atomic=...)` retourne {ok: bool}.

    NB (N38) : ces trois tests sont des tests de SIGNATURE, pas de
    comportement. Le comportement du cablage est couvert par
    `ApplyChangesAtomicRollbackIntegrationTests` ci-dessus — ne pas les
    considerer comme une garde du rollback.
    """

    def test_signature_accepts_apply_atomic_kwarg(self) -> None:
        """`apply_atomic` est un kwarg accepte par apply_changes."""
        import inspect

        from cinesort.ui.api import apply_support

        sig = inspect.signature(apply_support.apply_changes)
        self.assertIn("apply_atomic", sig.parameters)
        # Default = False (opt-in strict)
        self.assertFalse(sig.parameters["apply_atomic"].default)

    def test_signature_run_facade_apply_accepts_atomic(self) -> None:
        import inspect

        from cinesort.ui.api.facades.run_facade import RunFacade

        sig = inspect.signature(RunFacade.apply)
        self.assertIn("apply_atomic", sig.parameters)
        self.assertFalse(sig.parameters["apply_atomic"].default)

    def test_signature_apply_impl_accepts_atomic(self) -> None:
        import inspect

        from cinesort.ui.api.cinesort_api import CineSortApi

        sig = inspect.signature(CineSortApi._apply_impl)
        self.assertIn("apply_atomic", sig.parameters)
        self.assertFalse(sig.parameters["apply_atomic"].default)


if __name__ == "__main__":
    unittest.main()
