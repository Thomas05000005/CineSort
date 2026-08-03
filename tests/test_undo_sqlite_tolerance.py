"""F31 — l'undo doit survivre a une erreur SQLite sur la persistance du statut.

Contexte du finding (revue post-merge 2026-07-18) : `_execute_undo_ops` restaure
les fichiers sur le disque puis ecrit un statut (DONE/SKIPPED/FAILED) en base.
Ce statut est un ARTEFACT DE RAPPORT : la decision filesystem est deja prise
quand on l'ecrit.

Or `sqlite3.Error` n'herite PAS de `OSError` : elle traversait le filet per-op.
Un « database is locked » sortait de la fonction, donc :
  - les ops suivantes n'etaient jamais reverties (FS a moitie restaure) ;
  - le rapport done/skipped/failed n'etait jamais construit (500 cote REST) ;
  - le batch restait affiche comme annulable.

REVUE ADVERSAIRE R1 — trois trous fermes ici :
  1. le 12e appel DB de l'undo (`_undo_mkdir_ops`, mark APRES le `rmdir()`)
     restait NU sous un `contextlib.suppress` sans `sqlite3.Error`, en AVAL du
     perimetre patche ;
  2. la finalisation (`list_apply_operations` + `mark_apply_batch_undo_status`)
     n'etait ni protegee ni testee, alors qu'une DB verrouillee l'est pour TOUS
     les appels, pas seulement les marks per-op ;
  3. les 3 tests d'origine construisaient des ops SANS `src_sha1` (classees
     `legacy_no_hash`) : la branche « hash mismatch » — le site precis nomme par
     le finding — n'etait JAMAIS executee.
"""

from __future__ import annotations

import hashlib
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional

from cinesort.ui.api import apply_support


class _LockedMarkStore:
    """Store factice dont SEULE la persistance du statut d'undo echoue."""

    def __init__(self, fail_on_call: Optional[int] = None) -> None:
        self.apply = self
        self.calls = 0
        self.fail_on_call = fail_on_call
        self.marks: List[Dict[str, Any]] = []

    # --- surface utilisee par _execute_undo_ops / journaled_move ---
    def mark_apply_operation_undo_status(
        self, *, op_id: int, undo_status: str, error_message: Optional[str] = None
    ) -> None:
        self.calls += 1
        if self.fail_on_call is None or self.calls == self.fail_on_call:
            raise sqlite3.OperationalError("database is locked")
        self.marks.append({"op_id": op_id, "undo_status": undo_status, "error": error_message})

    def insert_pending_move(self, **_kwargs: Any) -> int:
        return 1

    def delete_pending_move(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _WriteLockedStore:
    """DB en LECTURE seule : tout WRITE leve « database is locked ».

    Modele fidele d'un verrou d'ecriture SQLite (WAL) : les SELECT passent, les
    UPDATE echouent. C'est le declencheur du finding F31, et il vaut pour TOUS
    les appels d'ecriture de l'undo — pas seulement les marks per-op.
    """

    def __init__(self, ops: Optional[List[Dict[str, Any]]] = None) -> None:
        self.apply = self
        self._ops = list(ops or [])
        self.write_attempts: List[str] = []

    # --- lectures : OK ---
    def list_apply_batches_for_run(self, *, run_id: str, limit: int = 0) -> List[Dict[str, Any]]:
        return [{"batch_id": "b1"}]

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        return list(self._ops)

    # --- ecritures : verrouillees ---
    def mark_apply_operation_undo_status(
        self, *, op_id: int, undo_status: str, error_message: Optional[str] = None
    ) -> None:
        self.write_attempts.append(f"op:{op_id}:{undo_status}")
        raise sqlite3.OperationalError("database is locked")

    def mark_apply_batch_undo_status(self, *, batch_id: str, status: str, summary: Any) -> None:
        self.write_attempts.append(f"batch:{batch_id}:{status}")
        raise sqlite3.OperationalError("database is locked")

    def insert_pending_move(self, **_kwargs: Any) -> int:
        return 1

    def delete_pending_move(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _StoreWithoutMarkApi:
    """Store dont la surface `mark_apply_operation_undo_status` a DERIVE.

    Ce n'est PAS une indisponibilite transitoire mais une erreur de
    programmation : elle doit echouer BRUYAMMENT (cf. spec F31, point d).
    """

    def __init__(self) -> None:
        self.apply = self

    def insert_pending_move(self, **_kwargs: Any) -> int:
        return 1

    def delete_pending_move(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _ApiStub:
    def _unique_path(self, path: Path) -> Path:
        return path


class _RunPathsStub:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir


class UndoSqliteToleranceTests(unittest.TestCase):
    def _build_ops(self, tmp: Path, count: int) -> List[Dict[str, Any]]:
        """Cree `count` fichiers "deplaces" a restaurer (dst existe, src absent)."""
        ops: List[Dict[str, Any]] = []
        for index in range(count):
            src = tmp / "source" / f"Film {index}.mkv"
            dst = tmp / "cible" / f"Film {index}.mkv"
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"contenu")
            ops.append(
                {
                    "id": index + 1,
                    "op_type": "MOVE_FILE",
                    "src_path": str(src),
                    "dst_path": str(dst),
                    "reversible": True,
                }
            )
        return ops

    def test_undo_restaure_tout_malgre_un_lock_db_au_milieu(self) -> None:
        """Le lock DB survient sur la 2e op : les 3 fichiers doivent etre restaures."""
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            ops = self._build_ops(tmp, 3)
            store = _LockedMarkStore(fail_on_call=2)
            logs: List[str] = []

            counts = apply_support._execute_undo_ops(
                _ApiStub(),
                ops,
                store,
                lambda level, message: logs.append(f"{level}:{message}"),
                _RunPathsStub(tmp / "run"),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,
            )

            self.assertEqual(counts["done"], 3, "les 3 restaurations FS doivent avoir eu lieu")
            for op in ops:
                self.assertTrue(
                    Path(op["src_path"]).exists(),
                    f"fichier non restaure : {op['src_path']} — le lock DB a interrompu l'undo",
                )
                self.assertFalse(Path(op["dst_path"]).exists())
            self.assertIn("undo_conflicts_root", counts, "le rapport doit rester construit")
            self.assertTrue(
                any("statut non persiste" in message for message in logs),
                "l'echec de persistance doit rester visible dans le log de run",
            )

    def test_undo_survit_a_un_lock_db_sur_toutes_les_ops(self) -> None:
        """Cas extreme : la DB est verrouillee pour tous les marks."""
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            ops = self._build_ops(tmp, 2)
            store = _LockedMarkStore(fail_on_call=None)
            logs: List[str] = []

            counts = apply_support._execute_undo_ops(
                _ApiStub(),
                ops,
                store,
                lambda level, message: logs.append(f"{level}:{message}"),
                _RunPathsStub(tmp / "run"),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,
            )

            self.assertEqual(counts["done"], 2)
            self.assertEqual(counts["failed"], 0)
            self.assertTrue(all(Path(op["src_path"]).exists() for op in ops))

    def test_statut_persiste_normalement_quand_la_db_repond(self) -> None:
        """Non-regression : sans erreur DB, les statuts sont bien ecrits."""
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            ops = self._build_ops(tmp, 2)

            store = _LockedMarkStore(fail_on_call=-1)  # ne declenche jamais
            counts = apply_support._execute_undo_ops(
                _ApiStub(),
                ops,
                store,
                lambda _level, _message: None,
                _RunPathsStub(tmp / "run"),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,
            )

            self.assertEqual(counts["done"], 2)
            self.assertEqual([mark["undo_status"] for mark in store.marks], ["DONE", "DONE"])

    # ── REVUE R1 (3) : le site EXACT nomme par le finding ──────────────

    def test_mark_hors_try_du_branchement_hash_mismatch(self) -> None:
        """Le finding vise d'abord le mark du branchement « hash mismatch ».

        Les 3 tests ci-dessus n'ont PAS de `src_sha1` : `preverify_undo_operations`
        les classe `legacy_no_hash` et cette branche n'est jamais executee. Ici
        on fabrique une empreinte volontairement non concordante pour l'atteindre.
        """
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            ops = self._build_ops(tmp, 1)
            ops[0]["src_sha1"] = hashlib.sha1(b"un AUTRE contenu").hexdigest()
            ops[0]["src_size"] = len(b"un AUTRE contenu")
            store = _LockedMarkStore(fail_on_call=None)
            logs: List[str] = []

            counts = apply_support._execute_undo_ops(
                _ApiStub(),
                ops,
                store,
                lambda level, message: logs.append(f"{level}:{message}"),
                _RunPathsStub(tmp / "run"),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,  # best-effort : la branche SKIPPED s'execute
            )

            self.assertEqual(counts["skipped"], 1, "la branche hash_mismatch doit avoir ete empruntee")
            self.assertEqual(counts["done"], 0)
            self.assertTrue(
                any("empreinte" in message for message in logs),
                "preuve que le test emprunte bien la branche hash_mismatch et pas legacy_no_hash",
            )
            self.assertTrue(
                any("statut non persiste" in message for message in logs),
                "le mark de ce branchement doit tolerer sqlite3.Error comme les autres",
            )

    # ── REVUE R1 (1) : le 12e appel DB, en AVAL de _execute_undo_ops ───

    def test_undo_mkdir_survit_a_une_db_verrouillee(self) -> None:
        """`_undo_mkdir_ops` marque l'op APRES le `rmdir()`.

        Sans tolerance, la DB verrouillee laissait le dossier supprime, l'op
        PENDING, et l'exception remontait au boundary REST : 500 generique et
        rapport d'undo perdu, alors que le FS etait deja mute.
        """
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            saga = tmp / "_Collection" / "Alien Collection"
            saga.mkdir(parents=True)
            store = _WriteLockedStore([{"id": 7, "op_type": "MKDIR", "dst_path": str(saga), "undo_status": "PENDING"}])
            logs: List[str] = []

            removed = apply_support._undo_mkdir_ops(
                store, "b1", lambda level, message: logs.append(f"{level}:{message}"), run_id="run-1"
            )

            self.assertEqual(removed, 1, "le rmdir doit avoir eu lieu")
            self.assertFalse(saga.exists())
            self.assertEqual(store.write_attempts, ["op:7:DONE"], "le mark doit bien avoir ete TENTE")
            self.assertTrue(
                any("statut non persiste" in message for message in logs),
                "l'echec de persistance doit rester visible dans le log de run",
            )

    # ── REVUE R1 (2) : la finalisation du batch ────────────────────────

    def test_finalisation_du_batch_rend_le_rapport_malgre_une_db_verrouillee(self) -> None:
        """Relecture des ops + statut du batch : le rapport ne doit jamais etre perdu."""
        store = _WriteLockedStore([{"id": 1, "reversible": 1, "undo_status": "DONE"}])
        logs: List[str] = []

        def _log(level: str, message: str) -> None:
            logs.append(f"{level}:{message}")

        # La LECTURE passe : le batch est vu comme entierement resolu.
        self.assertTrue(apply_support._batch_all_ops_resolved(store, _log, batch_id="b1"))

        persisted = apply_support._finalize_batch_undo_status(
            store, _log, batch_id="b1", status="UNDONE_DONE", summary={"done": 1}
        )
        self.assertFalse(persisted, "la persistance a echoue, la fonction doit le dire")
        self.assertTrue(any("statut du batch non persiste" in message for message in logs))

    def test_relecture_des_ops_indisponible_degrade_en_partiel(self) -> None:
        """Si meme la LECTURE echoue, on ne peut pas prouver que tout est resolu.

        Degradation CONSERVATRICE : False -> le batch est classe UNDONE_PARTIAL
        et reste proposable a l'annulation, plutot qu'un UNDONE_DONE menteur.
        """

        class _ReadLockedStore:
            def __init__(self) -> None:
                self.apply = self

            def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
                raise sqlite3.OperationalError("database is locked")

        logs: List[str] = []
        resolved = apply_support._batch_all_ops_resolved(
            _ReadLockedStore(), lambda level, message: logs.append(f"{level}:{message}"), batch_id="b1"
        )
        self.assertFalse(resolved)
        self.assertTrue(any("non verifiable" in message for message in logs))

    # ── REVUE R1 : le drift d'API doit rester BRUYANT ──────────────────

    def test_un_store_sans_lapi_de_mark_echoue_bruyamment(self) -> None:
        """`AttributeError` ne doit PAS etre avalee par le filet de tolerance.

        Avaler le drift d'API rendait les 11 marks silencieusement no-op : le
        batch etait alors classe UNDONE_PARTIAL a chaque passage et reste
        indefiniment propose comme annulable — exactement le « batch mensonger »
        que F31 devait supprimer, deplace du lock vers le drift d'API.
        """
        with self.assertRaises(AttributeError):
            apply_support._mark_undo_status(
                _StoreWithoutMarkApi(), lambda _level, _message: None, op_id=1, undo_status="DONE"
            )

    def test_le_drift_dapi_est_refuse_avant_tout_deplacement(self) -> None:
        """Le drift echoue BRUYAMMENT mais AVANT le 1er move, pas au milieu.

        Laisser l'AttributeError sortir au premier mark abandonnerait l'undo avec
        un filesystem A MOITIE restaure. Le garde fail-closed en tete de
        `_execute_undo_ops` fait echouer avant tout deplacement : le disque est
        exactement dans l'etat ou il etait.
        """
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            ops = self._build_ops(tmp, 3)

            with self.assertRaises(AttributeError):
                apply_support._execute_undo_ops(
                    _ApiStub(),
                    ops,
                    _StoreWithoutMarkApi(),
                    lambda _level, _message: None,
                    _RunPathsStub(tmp / "run"),
                    empty_bucket=None,
                    residual_bucket=None,
                    atomic=False,
                )

            for op in ops:
                self.assertFalse(Path(op["src_path"]).exists(), "aucun fichier ne doit avoir bouge")
                self.assertTrue(Path(op["dst_path"]).exists(), "le filesystem doit etre intact")

    def test_chaine_undo_complete_db_verrouillee_rend_le_rapport(self) -> None:
        """INTEGRATION : `_execute_and_finalize_undo` de bout en bout, DB verrouillee.

        C'est le chemin de PRODUCTION complet (marks per-op + `_undo_mkdir_ops` +
        relecture + statut du batch) : avant la revue R1, il se terminait
        systematiquement par une `sqlite3.OperationalError` remontee au boundary
        REST (500 generique) alors que le filesystem etait deja restaure.
        """
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            ops = self._build_ops(tmp, 2)
            saga = tmp / "_Collection" / "Alien Collection"
            saga.mkdir(parents=True)
            mkdir_op = {"id": 99, "op_type": "MKDIR", "dst_path": str(saga), "undo_status": "PENDING"}
            store = _WriteLockedStore([*ops, mkdir_op])

            run_dir = tmp / "run"
            run_dir.mkdir()
            logs: List[str] = []

            class _FullApiStub:
                def _unique_path(self, path: Path) -> Path:
                    return path

                def _file_logger(self, _run_paths: Any):
                    return lambda level, message: logs.append(f"{level}:{message}")

                def _write_summary_section(self, *_args: Any, **_kwargs: Any) -> None:
                    return None

                _notify = type("_N", (), {"notify": staticmethod(lambda *a, **k: None)})()

                def _dispatch_plugin_hook(self, *_args: Any, **_kwargs: Any) -> None:
                    return None

            payload = apply_support._execute_and_finalize_undo(
                _FullApiStub(),
                "run-1",
                {
                    "batch_id": "b1",
                    "irreversible_count": 0,
                    "preview_categories": {},
                    "empty_bucket": None,
                    "residual_bucket": None,
                    "preview_counts": {},
                },
                ops,
                store,
                atomic=False,
                run_paths=_RunPathsStub(run_dir),
            )

            self.assertTrue(payload["ok"], "le rapport d'undo doit etre rendu, pas un 500")
            self.assertEqual(payload["counts"]["done"], 2)
            for op in ops:
                self.assertTrue(Path(op["src_path"]).exists(), "restauration FS incomplete")
            self.assertFalse(saga.exists(), "le dossier MKDIR vide doit avoir ete retire")
            self.assertIn("batch:b1:UNDONE_DONE", store.write_attempts, "la finalisation doit avoir ete TENTEE")
            self.assertTrue(any("statut du batch non persiste" in message for message in logs))

    def test_non_regression_une_typeerror_de_signature_reste_bruyante(self) -> None:
        """Garde symetrique (verte des deux cotes de la mutation) : une erreur de
        programmation sur la signature du store doit continuer a remonter."""

        class _BadSignatureStore:
            def __init__(self) -> None:
                self.apply = self

            def mark_apply_operation_undo_status(self, op_id: int) -> None:  # signature fausse
                return None

        with self.assertRaises(TypeError):
            apply_support._mark_undo_status(
                _BadSignatureStore(), lambda _level, _message: None, op_id=1, undo_status="DONE"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
