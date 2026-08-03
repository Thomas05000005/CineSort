"""VN-E.4 — Tests pour la cabletage de l'ApplyAuditLogger dans apply_rows.

Vague N batch 4 : les 4 methodes publiques du logger d'audit
(row_decision / skip / conflict / error) etaient documentees mais
jamais appelees. Ce test verifie qu'apres cabletage, chaque type d'event
est bien emis dans le journal JSONL lorsqu'un apply rencontre la
condition correspondante.

Couverture :

1. test_row_decision_emitted_per_row : chaque row du batch produit un
   event `row_decision` avec ok + reason + title.

2. test_op_skip_emitted_when_validation_absente : un row sans decision
   tombe en SKIP_REASON_VALIDATION_ABSENTE -> event `op_skip`.

3. test_op_conflict_emitted_when_destination_collision : un row dont la
   cible existe deja avec contenu different declenche merge_dir_safe ->
   conflict quarantined -> event `op_conflict`.

4. test_error_emitted_when_exception_raised : une exception levee
   pendant l'apply (PermissionError mock) declenche event `error`.

5. test_backward_compat_no_audit_logger : si audit_logger=None,
   comportement strictement inchange (aucune regression).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.app.apply_audit import ApplyAuditLogger, audit_path_for_run, read_apply_audit
from cinesort.app.apply_core import apply_rows


def _make_single_row(row_id: str, folder: str, video: str = "film.mkv") -> core.PlanRow:
    """Construit un PlanRow minimal kind='single'."""
    return core.PlanRow(
        row_id=row_id,
        kind="single",
        folder=folder,
        video=video,
        proposed_title="Film",
        proposed_year=2020,
        proposed_source="name",
        confidence=80,
        confidence_label="high",
        candidates=[],
    )


def _make_cfg(root: Path) -> core.Config:
    return core.Config(root=root)


class _LogCollector:
    """Mini collector pour log(level, msg). Aucun besoin de print."""

    def __init__(self) -> None:
        self.entries: list = []

    def __call__(self, level: str, msg: str) -> None:
        self.entries.append((level, msg))


class ApplyAuditEventsEmittedTests(unittest.TestCase):
    """Verifie que apply_rows emet correctement les 4 events sur audit_logger."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_audit_emit_")
        self.tmpdir = Path(self._tmp)
        self.root = self.tmpdir / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_dir = self.tmpdir / "run"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _open_audit(self) -> ApplyAuditLogger:
        return ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b_test", run_id="r_test")

    def _events(self) -> list:
        return read_apply_audit(self.run_dir)

    # ------------------------------------------------------------------
    # 1. row_decision emis pour chaque row
    # ------------------------------------------------------------------

    def test_row_decision_emitted_per_row(self) -> None:
        cfg = _make_cfg(self.root)
        # 2 rows : 1 approuvee, 1 rejetee (mais decision presente)
        film1 = self.root / "film1"
        film1.mkdir()
        (film1 / "film.mkv").write_bytes(b"\x00" * 32)
        film2 = self.root / "film2"
        film2.mkdir()
        (film2 / "film.mkv").write_bytes(b"\x00" * 32)

        rows = [
            _make_single_row("r1", folder=str(film1)),
            _make_single_row("r2", folder=str(film2)),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Film One", "year": 2020},
            "r2": {"ok": False, "title": "Film Two", "year": 2021},
        }
        decision_presence = {"r1", "r2"}

        log = _LogCollector()
        auditor = self._open_audit()
        try:
            apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=True,  # dry_run pour eviter les renames FS
                quarantine_unapproved=False,
                log=log,
                decision_presence=decision_presence,
                audit_logger=auditor,
            )
        finally:
            auditor.close()

        events = self._events()
        decision_events = [e for e in events if e.get("event") == "row_decision"]
        self.assertEqual(len(decision_events), 2, f"Expected 2 row_decision, got {len(decision_events)}: {events}")

        by_rid = {e["row_id"]: e for e in decision_events}
        self.assertIn("r1", by_rid)
        self.assertIn("r2", by_rid)
        self.assertTrue(by_rid["r1"]["ok"])
        self.assertFalse(by_rid["r2"]["ok"])
        # reason populated meaningfully
        self.assertIn("reason", by_rid["r1"])
        self.assertEqual(by_rid["r1"]["reason"], "user_approved")
        self.assertEqual(by_rid["r2"]["reason"], "user_rejected")

    # ------------------------------------------------------------------
    # 2. op_skip emis quand validation absente
    # ------------------------------------------------------------------

    def test_op_skip_emitted_when_validation_absente(self) -> None:
        cfg = _make_cfg(self.root)
        film = self.root / "film_skip"
        film.mkdir()
        (film / "film.mkv").write_bytes(b"\x00" * 16)

        rows = [_make_single_row("r_skip", folder=str(film))]
        # decisions vide -> SKIP_REASON_VALIDATION_ABSENTE (cf apply_core ligne ~1299)
        decisions: dict = {}
        # decision_presence vide aussi : row tombe en validation_absente
        decision_presence: set = set()

        log = _LogCollector()
        auditor = self._open_audit()
        try:
            apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=True,
                quarantine_unapproved=False,
                log=log,
                decision_presence=decision_presence,
                audit_logger=auditor,
            )
        finally:
            auditor.close()

        events = self._events()
        skip_events = [e for e in events if e.get("event") == "op_skip"]
        self.assertGreaterEqual(len(skip_events), 1, f"Expected >= 1 op_skip, got: {events}")
        # Au moins un skip avec le row_id correct
        skip_rids = {e.get("row_id") for e in skip_events}
        self.assertIn("r_skip", skip_rids)
        # Le reason doit contenir 'validation_absente' (SKIP_REASON_VALIDATION_ABSENTE = "skip_validation_absente")
        validation_absente_skips = [
            e for e in skip_events if e.get("row_id") == "r_skip" and "validation_absente" in str(e.get("reason", ""))
        ]
        self.assertGreaterEqual(
            len(validation_absente_skips),
            1,
            f"Expected at least one validation_absente skip, got: {skip_events}",
        )

    # ------------------------------------------------------------------
    # 3. op_conflict emis quand conflit FS detecte
    # ------------------------------------------------------------------

    def test_op_conflict_emitted_when_destination_collision(self) -> None:
        cfg = _make_cfg(self.root)
        # Setup : src folder existe + dst existe deja avec contenu different
        # -> merge_dir_safe + move_file_with_collision_policy -> conflict.
        src = self.root / "Film Source"
        src.mkdir()
        (src / "film.mkv").write_bytes(b"AAAA" * 64)  # contenu A

        # dst aura le nom apres rename (apply_single calcule "Film (2020)").
        dst = self.root / "Film (2020)"
        dst.mkdir()
        (dst / "film.mkv").write_bytes(b"BBBB" * 64)  # contenu B (different)

        rows = [_make_single_row("r_conflict", folder=str(src))]
        rows[0].proposed_title = "Film"
        rows[0].proposed_year = 2020
        decisions = {"r_conflict": {"ok": True, "title": "Film", "year": 2020}}
        decision_presence = {"r_conflict"}

        log = _LogCollector()
        auditor = self._open_audit()
        try:
            apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=False,  # apply reel pour declencher les ops FS
                quarantine_unapproved=False,
                log=log,
                decision_presence=decision_presence,
                audit_logger=auditor,
            )
        finally:
            auditor.close()

        events = self._events()
        conflict_events = [e for e in events if e.get("event") == "op_conflict"]
        self.assertGreaterEqual(
            len(conflict_events),
            1,
            f"Expected >= 1 op_conflict, got events: {[e.get('event') for e in events]}",
        )
        # Le conflit doit etre attache au row_id
        conflict_rids = {e.get("row_id") for e in conflict_events}
        self.assertIn("r_conflict", conflict_rids)

    # ------------------------------------------------------------------
    # 4. error emis quand exception levee
    # ------------------------------------------------------------------

    def test_error_emitted_when_exception_raised(self) -> None:
        cfg = _make_cfg(self.root)
        film = self.root / "film_err"
        film.mkdir()
        (film / "film.mkv").write_bytes(b"\x00" * 16)

        rows = [_make_single_row("r_err", folder=str(film))]
        decisions = {"r_err": {"ok": True, "title": "Film", "year": 2020}}
        decision_presence = {"r_err"}

        log = _LogCollector()
        auditor = self._open_audit()

        # Mock apply_single pour lever une PermissionError (simule fichier verrouille)
        with mock.patch(
            "cinesort.app.apply_core.apply_single",
            side_effect=PermissionError("Mock: file locked by VLC"),
        ):
            try:
                apply_rows(
                    cfg,
                    rows,
                    decisions,
                    dry_run=False,
                    quarantine_unapproved=False,
                    log=log,
                    decision_presence=decision_presence,
                    audit_logger=auditor,
                )
            finally:
                auditor.close()

        events = self._events()
        error_events = [e for e in events if e.get("event") == "error"]
        self.assertGreaterEqual(len(error_events), 1, f"Expected >= 1 error, got: {events}")
        err = error_events[0]
        self.assertEqual(err.get("row_id"), "r_err")
        self.assertIn("PermissionError", str(err.get("message", "")))

    # ------------------------------------------------------------------
    # 5. Backward compat : audit_logger=None ne change rien
    # ------------------------------------------------------------------

    def test_backward_compat_no_audit_logger(self) -> None:
        """Sans audit_logger, apply_rows doit fonctionner comme avant (aucune exception)."""
        cfg = _make_cfg(self.root)
        film = self.root / "film_bc"
        film.mkdir()
        (film / "film.mkv").write_bytes(b"\x00" * 16)

        rows = [_make_single_row("r_bc", folder=str(film))]
        decisions = {"r_bc": {"ok": True, "title": "Film", "year": 2020}}
        decision_presence = {"r_bc"}

        log = _LogCollector()
        # Appel sans audit_logger : default None, aucune exception attendue.
        result = apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=True,
            quarantine_unapproved=False,
            log=log,
            decision_presence=decision_presence,
        )
        # Aucun fichier d'audit ne doit avoir ete cree (audit_logger=None)
        audit_path = audit_path_for_run(self.run_dir)
        self.assertFalse(audit_path.exists(), "Audit file should NOT exist when audit_logger=None")
        # Et le result ApplyResult doit etre normal.
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
