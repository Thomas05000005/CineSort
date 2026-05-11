"""P2.3 : tests pour apply_audit (logger JSONL + reader)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.app.apply_audit import (
    AUDIT_FILENAME,
    ApplyAuditLogger,
    audit_path_for_run,
    read_apply_audit,
)


class AuditLoggerWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_audit_")
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _read_events(self):
        return read_apply_audit(self.run_dir)

    def test_writes_apply_start(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1", run_id="r1") as log:
            log.start(dry_run=False, total_rows=3)
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "apply_start")
        self.assertEqual(events[0]["batch_id"], "b1")
        self.assertEqual(events[0]["total_rows"], 3)
        self.assertFalse(events[0]["dry_run"])

    def test_writes_multiple_events_ordered(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.start(dry_run=False, total_rows=2)
            log.op_move_file(src="a.mkv", dst="b.mkv", row_id="r1", sha1="abc", size=1234)
            log.op_move_dir(src="/src", dst="/dst", row_id="r2")
            log.end(counts={"moves": 1, "renames": 1}, status="DONE")
        events = self._read_events()
        self.assertEqual(len(events), 4)
        names = [e["event"] for e in events]
        self.assertEqual(names, ["apply_start", "op_move_file", "op_move_dir", "apply_end"])

    def test_op_move_file_includes_sha1_and_size(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir)) as log:
            log.op_move_file(src="a.mkv", dst="b.mkv", row_id="x", sha1="deadbeef", size=42)
        events = self._read_events()
        self.assertEqual(events[0]["sha1"], "deadbeef")
        self.assertEqual(events[0]["size"], 42)

    def test_none_values_are_omitted(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir)) as log:
            log.op_move_file(src="a.mkv", dst="b.mkv")  # row_id/sha1/size None
        events = self._read_events()
        ev = events[0]
        self.assertNotIn("sha1", ev)
        self.assertNotIn("size", ev)
        self.assertNotIn("row_id", ev)

    def test_skip_writes_reason(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir)) as log:
            log.skip(row_id="r1", reason="SKIP_NOOP", detail="already conforming")
        events = self._read_events()
        self.assertEqual(events[0]["event"], "op_skip")
        self.assertEqual(events[0]["reason"], "SKIP_NOOP")
        self.assertEqual(events[0]["detail"], "already conforming")

    def test_conflict_writes_resolution(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir)) as log:
            log.conflict(
                row_id="r1",
                src="/src/a.mkv",
                dst="/dst/a.mkv",
                conflict_type="duplicate_identical",
                resolution="moved_to_review",
                resolved_path="/_review/a.mkv",
            )
        events = self._read_events()
        self.assertEqual(events[0]["conflict_type"], "duplicate_identical")
        self.assertEqual(events[0]["resolution"], "moved_to_review")

    def test_row_decision(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir)) as log:
            log.row_decision(row_id="r1", ok=True, title="Inception", year=2010, reason="user_approved")
        events = self._read_events()
        self.assertEqual(events[0]["event"], "row_decision")
        self.assertTrue(events[0]["ok"])
        self.assertEqual(events[0]["title"], "Inception")

    def test_audit_path_for_run(self):
        path = audit_path_for_run(self.run_dir)
        self.assertEqual(path.name, AUDIT_FILENAME)
        self.assertEqual(path.parent, self.run_dir)


class AuditLoggerAppendOnlyTests(unittest.TestCase):
    """Vérifie que les writes successifs n'écrasent pas l'historique."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_audit_append_")
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_two_batches_coexist(self):
        # Batch 1
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.start(dry_run=False, total_rows=1)
            log.end(counts={"moves": 1}, status="DONE")
        # Batch 2 — ré-ouvre le même fichier
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b2") as log:
            log.start(dry_run=False, total_rows=2)
            log.end(counts={"moves": 2}, status="DONE")

        all_events = read_apply_audit(self.run_dir)
        # 2 batchs × 2 events = 4
        self.assertEqual(len(all_events), 4)
        b1_events = read_apply_audit(self.run_dir, batch_id="b1")
        b2_events = read_apply_audit(self.run_dir, batch_id="b2")
        self.assertEqual(len(b1_events), 2)
        self.assertEqual(len(b2_events), 2)


class AuditReaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_audit_read_")
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_read_empty_file_returns_empty_list(self):
        events = read_apply_audit(self.run_dir)
        self.assertEqual(events, [])

    def test_read_ignores_malformed_lines(self):
        # Écrire directement un mélange valide + invalide
        path = audit_path_for_run(self.run_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"event": "apply_start", "batch_id": "b1"}\nnot json at all\n{"event": "apply_end", "batch_id": "b1"}\n',
            encoding="utf-8",
        )
        events = read_apply_audit(self.run_dir)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "apply_start")
        self.assertEqual(events[1]["event"], "apply_end")

    def test_read_with_limit(self):
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            for i in range(10):
                log.op_move_file(src=f"s{i}", dst=f"d{i}")
        events = read_apply_audit(self.run_dir, limit=3)
        self.assertEqual(len(events), 3)


class AuditLoggerRobustnessTests(unittest.TestCase):
    def test_write_after_close_is_noop(self):
        tmp = tempfile.mkdtemp(prefix="cinesort_audit_closed_")
        try:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir(parents=True)
            log = ApplyAuditLogger(audit_path_for_run(run_dir))
            log.close()
            # Plusieurs écritures après close → no-op silencieux
            log.op_move_file(src="a", dst="b")
            log.end(counts={}, status="CLOSED")
            events = read_apply_audit(run_dir)
            self.assertEqual(events, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_double_close_is_safe(self):
        tmp = tempfile.mkdtemp(prefix="cinesort_audit_dclose_")
        try:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir(parents=True)
            log = ApplyAuditLogger(audit_path_for_run(run_dir))
            log.close()
            log.close()  # doit pas crasher
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
