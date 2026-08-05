"""Issue #414 — le journal d'audit JSONL passe par le scrubbing de secrets.

Asymetrie corrigee : les logs UI traversaient `SecretsScrubFilter`, le JSONL
d'apply (exportable via `export_apply_audit`, archive longue duree) non.

L'exception assumee — `src`/`dst`/`path`/`resolved_path`/`title` restent
VERBATIM — est verrouillee ici aussi : `scrub_secrets` est un scrubber de forme
`cle=valeur` dont la capture ne s'arrete qu'au blanc, donc l'appliquer a un
chemin en tronque la fin. Un chemin tronque dans un journal d'apply ment sur ce
qui a ete deplace sur le disque.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.app.apply_audit import ApplyAuditLogger, audit_path_for_run, read_apply_audit

# Sentinelle volontairement a faible entropie et sans forme de vrai secret :
# elle doit disparaitre du JSONL, sans faire hurler les scanners de secrets.
CANARY = "canary-aaaa-bbbb-cccc"


class AuditScrubTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_audit_scrub_")
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _raw(self) -> str:
        return audit_path_for_run(self.run_dir).read_text(encoding="utf-8")

    # --- ce qui DOIT etre redige -------------------------------------------

    def test_error_message_url_api_key_is_redacted(self) -> None:
        # Vecteur reel : apply_core passe `message=f"{type(exc).__name__}: {exc}"`,
        # et une chaine d'exception HTTP embarque l'URL complete, query comprise.
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.error(
                context="apply_row_state_error",
                message=f"HTTPError: 401 for url: https://api.themoviedb.org/3/movie/1?api_key={CANARY}",
                row_id="abc123",
            )
        raw = self._raw()
        self.assertNotIn(CANARY, raw)
        self.assertIn("[REDACTED]", raw)
        self.assertIn("api.themoviedb.org", raw)  # le contexte de diagnostic survit

    def test_skip_detail_plex_header_is_redacted(self) -> None:
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.skip(row_id="r1", reason="integration_error", detail=f"X-Plex-Token: {CANARY}")
        raw = self._raw()
        self.assertNotIn(CANARY, raw)
        self.assertIn("[REDACTED]", raw)

    def test_conflict_resolution_field_is_scrubbed(self) -> None:
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.conflict(
                row_id="r1",
                src="/lib/a/film.mkv",
                dst="/lib/b/film.mkv",
                conflict_type="duplicate",
                resolution=f"retry with token={CANARY}",
            )
        raw = self._raw()
        self.assertNotIn(CANARY, raw)
        self.assertIn("[REDACTED]", raw)

    # --- ce qui doit rester FIDELE -----------------------------------------

    def test_paths_are_written_verbatim(self) -> None:
        # Chemin volontairement piege : `scrub_secrets` y verrait un `api_key=`
        # et avalerait tout le reste du chemin (`]/film.mkv`).
        src = r"C:/Films/Le Film (2020) [api_key=notreallyasecret]/film.mkv"
        dst = r"D:/Bibliotheque/Le Film (2020)/film.mkv"
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.op_move_file(src=src, dst=dst, row_id="r1")
        event = read_apply_audit(self.run_dir)[0]
        self.assertEqual(src, event["src"])
        self.assertEqual(dst, event["dst"])

    def test_mkdir_path_is_written_verbatim(self) -> None:
        path = r"D:/Bibliotheque/Token=Rage (2018)/"
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.op_mkdir(path=path)
        self.assertEqual(path, read_apply_audit(self.run_dir)[0]["path"])

    def test_title_is_not_mutilated(self) -> None:
        title = "Token=Rage"
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1") as log:
            log.row_decision(row_id="r1", ok=True, title=title, year=2018)
        self.assertEqual(title, read_apply_audit(self.run_dir)[0]["title"])

    # --- non-regression : le journal ordinaire est inchange ----------------

    def test_ordinary_event_untouched(self) -> None:
        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1", run_id="r1") as log:
            log.start(dry_run=False, total_rows=3)
            log.op_move_dir(src="/src/A", dst="/dst/A", row_id="r1")
            log.end(counts={"moves": 1}, status="DONE")
        events = read_apply_audit(self.run_dir)
        self.assertEqual(["apply_start", "op_move_dir", "apply_end"], [e["event"] for e in events])
        self.assertEqual("/src/A", events[1]["src"])
        self.assertEqual({"moves": 1}, events[2]["counts"])
        self.assertNotIn("[REDACTED]", self._raw())


if __name__ == "__main__":
    unittest.main()
