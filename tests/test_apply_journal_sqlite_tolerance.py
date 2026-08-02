"""F11 — le journal des operations apply doit tolerer une erreur SQLite.

Contexte du finding (revue post-merge 2026-07-18) : `record_apply_op` est appelee
APRES que `atomic_move` a deja deplace le fichier sur disque. Son role est
purement de journaliser l'operation pour permettre l'undo. L'invariant est
documente dans move_journal.py:13-15 : « un failure du journal ne DOIT JAMAIS
empecher un move legitime ».

Or `sqlite3.Error` n'herite PAS de `OSError` (c'est une sous-classe directe de
`Exception`). Le tuple d'exceptions ne la listait pas -> un « database is locked »
traversait les deux couches de tolerance, atteignait le boundary de l'apply, et
avortait tout le batch alors que le fichier etait deja deplace : etat mixte sur
disque + rows restantes jamais traitees + move non journalise donc non annulable.
"""

from __future__ import annotations

import logging
import sqlite3
import unittest
from unittest import mock
from pathlib import Path

from cinesort.app import apply_core


class RecordApplyOpSqliteToleranceTests(unittest.TestCase):
    """record_apply_op absorbe sqlite3.Error comme elle absorbe deja OSError."""

    def test_tolere_sqlite_operational_error_database_is_locked(self) -> None:
        def _locked(_payload: dict) -> None:
            raise sqlite3.OperationalError("database is locked")

        with self.assertLogs("cinesort.app.apply_core", level=logging.WARNING) as cm:
            ok = apply_core.record_apply_op(
                _locked,
                op_type="MOVE_FILE",
                src_path=Path("/src/Film.mkv"),
                dst_path=Path("/dst/Film.mkv"),
            )

        self.assertFalse(ok, "l'echec de journalisation doit etre signale par False")
        self.assertTrue(
            any("echec journalisation" in message for message in cm.output),
            "l'echec doit rester visible dans les logs (la reversibilite se degrade)",
        )

    def test_tolere_sqlite_database_error_corruption(self) -> None:
        def _corrupt(_payload: dict) -> None:
            raise sqlite3.DatabaseError("database disk image is malformed")

        with self.assertLogs("cinesort.app.apply_core", level=logging.WARNING):
            ok = apply_core.record_apply_op(
                _corrupt,
                op_type="MOVE_DIR",
                src_path=Path("/src"),
                dst_path=Path("/dst"),
            )
        self.assertFalse(ok)

    def test_une_exception_hors_tuple_reste_fatale(self) -> None:
        """Garde anti-sur-correction : on ne veut pas d'un `except Exception`.

        Une erreur de programmation (mauvaise signature, attribut manquant) doit
        continuer a remonter bruyamment, sinon on masque des bugs reels.
        """

        def _bug(_payload: dict) -> None:
            raise KeyError("champ manquant")

        with self.assertRaises(KeyError):
            apply_core.record_apply_op(
                _bug,
                op_type="MOVE_FILE",
                src_path=Path("/a"),
                dst_path=Path("/b"),
            )

    def test_apply_rows_continue_quand_le_journal_est_verrouille(self) -> None:
        """Chemin de PRODUCTION : un journal verrouille ne doit pas avorter le batch.

        Les tests unitaires ci-dessus n'exercent que la defense en profondeur de
        `record_apply_op`. Ici on passe par `apply_rows` avec un `record_op` qui
        echoue a CHAQUE appel : les deux films doivent etre ranges quand meme,
        car le deplacement physique a deja reussi quand la journalisation echoue.
        """
        import shutil
        import tempfile
        from pathlib import Path as _Path

        from cinesort.app.apply_core import apply_rows
        from cinesort.domain import core as core_mod

        def _journal_verrouille(_payload: dict) -> None:
            raise sqlite3.OperationalError("database is locked")

        tmp = _Path(tempfile.mkdtemp(prefix="cinesort_f11_"))
        try:
            root = tmp / "root"
            root.mkdir()
            rows = []
            decisions = {}
            for index, titre in enumerate(("Alien", "Aliens"), start=1):
                folder = root / f"Film.{index}"
                folder.mkdir()
                (folder / f"film{index}.mkv").write_bytes(b"\x00" * 64)
                rows.append(
                    core_mod.PlanRow(
                        row_id=f"s{index}",
                        kind="single",
                        folder=str(folder),
                        video=f"film{index}.mkv",
                        proposed_title=titre,
                        proposed_year=1979 + index,
                        proposed_source="name",
                        confidence=90,
                        confidence_label="high",
                        candidates=[],
                    )
                )
                decisions[f"s{index}"] = {"ok": True, "title": titre, "year": 1979 + index}

            res = apply_rows(
                core_mod.Config(root=root).normalized(),
                rows,
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=lambda _lvl, _msg: None,
                decision_presence=set(decisions),
                record_op=_journal_verrouille,
            )

            self.assertEqual(res.errors, 0, f"un echec de journal ne doit pas compter comme erreur : {res.error_messages}")
            self.assertGreaterEqual(
                res.renames + res.moves,
                2,
                "les DEUX films doivent avoir ete ranges malgre le journal verrouille",
            )
            self.assertTrue((root / "Alien (1980)").exists(), "premier film non range")
            self.assertTrue((root / "Aliens (1981)").exists(), "second film non range : le batch a ete avorte")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_creation_du_batch_reste_fail_closed(self) -> None:
        """Un lock DB AVANT tout deplacement doit empecher l'apply de demarrer.

        Garde-fou trouve en revue adversaire : la tolerance a sqlite3.Error vaut
        pour les operations journalisees APRES un move deja effectue. Elle ne
        doit PAS s'etendre a `insert_apply_batch`, qui s'execute avant que quoi
        que ce soit ne bouge : sans batch, `record_apply_op` retourne tot, donc
        l'apply se deroulerait integralement SANS AUCUNE OPERATION JOURNALISEE —
        aucun undo possible — et serait rapporte ok.
        """
        import tempfile
        from pathlib import Path as _Path
        from types import SimpleNamespace

        from cinesort.domain import core as core_mod
        from cinesort.ui.api import apply_support

        class _BatchLockedStore:
            def __init__(self) -> None:
                self.apply = self

            def insert_apply_batch(self, **_kwargs: object) -> str:
                raise sqlite3.OperationalError("database is locked")

            def list_duplicate_decisions(self, *_a: object, **_k: object) -> list:
                return []

        appels_apply_rows: list = []

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = _Path(tmp_name)
            root = tmp / "root"
            root.mkdir()
            run_paths = SimpleNamespace(
                run_dir=tmp / "run",
                summary_txt=tmp / "run" / "summary.txt",
                ui_log=tmp / "run" / "ui_log.txt",
            )
            (tmp / "run").mkdir(parents=True, exist_ok=True)

            row = core_mod.PlanRow(
                row_id="s1",
                kind="single",
                folder=str(root / "Film"),
                video="film.mkv",
                proposed_title="Film",
                proposed_year=2020,
                proposed_source="name",
                confidence=90,
                confidence_label="high",
                candidates=[],
            )

            with mock.patch.object(
                apply_support,
                "_apply_rows_fn",
                side_effect=lambda *a, **k: appels_apply_rows.append(1) or core_mod.ApplyResult(),
            ):
                with self.assertRaises(sqlite3.Error):
                    apply_support._execute_apply(
                        core_mod.Config(root=root),
                        [row],
                        {},
                        None,
                        dry_run=False,
                        quarantine_unapproved=False,
                        log_fn=lambda _lvl, _msg: None,
                        run_paths=run_paths,
                        store=_BatchLockedStore(),
                        api=SimpleNamespace(_app_version="test"),
                        run_id="r1",
                        batch_state=[None, 0],
                    )

        self.assertEqual(
            appels_apply_rows,
            [],
            "aucun deplacement ne doit etre tente quand le journal d'undo ne peut pas etre cree",
        )

    def test_succes_nominal_inchange(self) -> None:
        ops: list = []
        ok = apply_core.record_apply_op(
            ops.append,
            op_type="MOVE_FILE",
            src_path=Path("/a"),
            dst_path=Path("/b"),
            row_id="S|deadbeef",
        )
        self.assertTrue(ok)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["op_type"], "MOVE_FILE")
        self.assertEqual(ops[0]["row_id"], "S|deadbeef")


if __name__ == "__main__":
    unittest.main(verbosity=2)
