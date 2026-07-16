"""RELECTURE R2 du garde-fou fail-closed [CRIT-2] : 5 defauts.

D1 : deux PlanRow STRICTEMENT IDENTIQUES (meme folder + video + kind, cas ROUTINIER
     des roots imbriques : _compute_row_id ne hashe pas le root) etaient declarees
     "ambigues" -> l'operation destructive de l'utilisateur etait abandonnee a tort
     (+ un log ERROR par row_id duplique du plan ENTIER = spam).
D2 : l'abandon fail-closed n'incrementait PAS res.errors et res.error_messages n'avait
     aucun lecteur -> "Erreurs : 0" affiche alors que l'action n'a pas eu lieu.
D3 : les rows abandonnees etaient quand meme retirees de la boucle apply normale ->
     le film n'etait ni deplace, ni renomme/range. Disparition silencieuse.
D4 : branche non-single, `+= _rid_count` comptait des FICHIERS (video + sidecars) sous
     un libelle "Films ... deplaces" (et `+= 1` par FILM dans la branche single).
D5 : les `res.error_messages.append` du fail-closed n'etaient pas proteges (AttributeError
     sur un `res` duck-type -> crash de tout l'apply).

AVANT les fixes ces tests ECHOUENT, APRES ils PASSENT.
"""

from __future__ import annotations

import shutil
import tempfile
import types
import unittest
from pathlib import Path
from typing import Callable, List

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core
import cinesort.ui.api.apply_support as apply_support


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_r2_failclosed_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_review_root = Path(self._tmp) / "state" / "runs" / "r1" / "_review"
        self.bucket = self.run_review_root / "_bucket"
        self.bucket.mkdir(parents=True, exist_ok=True)
        self.logs: List[tuple] = []
        self.ops: List[dict] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _record_op(self, payload: dict) -> None:
        self.ops.append(dict(payload))

    def _errors(self) -> List[str]:
        return [msg for lvl, msg in self.logs if lvl == "ERROR"]

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _write(self, path: Path, data: bytes = b"X" * 64) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _row(
        self,
        row_id: str,
        kind: str,
        folder: Path,
        video: str,
        title: str = "Titre",
        year: int = 2010,
    ) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind=kind,
            folder=str(folder),
            video=video,
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title=title, year=year, source="name", score=0.7)],
        )

    def _bucket_files(self) -> List[Path]:
        return [p for p in self.bucket.rglob("*") if p.is_file()]

    def _run_marked(self, rows: List[core.PlanRow], marked: set, res=None):
        res = res if res is not None else core.ApplyResult()
        abandoned = apply_core.move_marked_for_deletion_to_bucket(
            self._cfg(),
            rows,
            marked,
            marked_for_deletion_root=self.bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        return res, abandoned

    def _run_losers(self, rows: List[core.PlanRow], losers: set, res=None):
        res = res if res is not None else core.ApplyResult()
        abandoned = apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            rows,
            losers,
            duplicates_user_decided_root=self.bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        return res, abandoned


# ---------------------------------------------------------------------------
# D1 : rows STRICTEMENT IDENTIQUES -> pas d'ambiguite (regression du garde-fou)
# ---------------------------------------------------------------------------
class D1IdenticalRowsAreNotAmbiguousTests(_Base):
    def _duplicated_plan(self) -> tuple:
        """Root imbrique : le meme film est plane deux fois, row_id identique."""
        folder = self.root / "Heat (1995) 720p"
        self._write(folder / "movie.mkv")
        rows = [
            self._row("R_SAME", "single", folder, "movie.mkv"),
            self._row("R_SAME", "single", folder, "movie.mkv"),  # STRICTEMENT identique
        ]
        return folder, rows

    def test_marked_identical_rows_still_move(self) -> None:
        folder, rows = self._duplicated_plan()

        res, abandoned = self._run_marked(rows, {"R_SAME"})

        self.assertEqual(abandoned, set(), msg="rows identiques -> aucun abandon")
        self.assertFalse(folder.exists(), msg="le film marque doit avoir ete deplace")
        self.assertTrue((self.bucket / "Heat (1995) 720p" / "movie.mkv").exists())
        self.assertEqual(res.marked_for_deletion_moved_count, 1)
        self.assertEqual(int(res.errors or 0), 0)
        self.assertEqual(self._errors(), [], msg=f"aucun ERROR (spam) attendu ; logs={self.logs}")
        self.assertEqual(list(res.error_messages), [])

    def test_losers_identical_rows_still_move(self) -> None:
        folder, rows = self._duplicated_plan()

        res, abandoned = self._run_losers(rows, {"R_SAME"})

        self.assertEqual(abandoned, set())
        self.assertFalse(folder.exists())
        self.assertEqual(res.duplicates_user_decided_moved_count, 1)
        self.assertEqual(self._errors(), [])

    def test_index_casefold_identical_targets(self) -> None:
        """La cle de cible est insensible a la casse (FS Windows)."""
        folder = self.root / "Heat (1995)"
        rows = [
            self._row("R_SAME", "single", folder, "Movie.MKV"),
            self._row("R_SAME", "single", folder, "movie.mkv"),
        ]
        by_row, ambiguous = apply_core._index_rows_by_id(rows, log=self._log, prefix="T")
        self.assertEqual(ambiguous, set())
        self.assertIs(by_row["R_SAME"], rows[0], msg="on garde la PREMIERE row")

    def test_different_targets_still_fail_closed(self) -> None:
        """Non-regression [CRIT-2] : cibles DIFFERENTES -> toujours fail-closed."""
        victim = self.root / "Le Parrain (1972)"
        target = self.root / "Le Parrain 2 (1974)"
        self._write(victim / "movie.mkv")
        self._write(target / "movie.mkv")
        rows = [
            self._row("R_COLLIDE", "single", target, "movie.mkv"),
            self._row("R_COLLIDE", "single", victim, "movie.mkv"),
        ]

        res, abandoned = self._run_marked(rows, {"R_COLLIDE"})

        self.assertEqual(abandoned, {"R_COLLIDE"})
        self.assertTrue((victim / "movie.mkv").exists())
        self.assertTrue((target / "movie.mkv").exists())
        self.assertEqual(self._bucket_files(), [])
        self.assertEqual(res.marked_for_deletion_moved_count, 0)
        self.assertTrue(any("R_COLLIDE" in msg for msg in self._errors()))


# ---------------------------------------------------------------------------
# D2 : l'abandon est VISIBLE (res.errors + resume utilisateur)
# ---------------------------------------------------------------------------
class D2AbandonIsVisibleTests(_Base):
    def _colliding(self) -> List[core.PlanRow]:
        victim = self.root / "Le Parrain (1972)"
        target = self.root / "Le Parrain 2 (1974)"
        self._write(victim / "movie.mkv")
        self._write(target / "movie.mkv")
        return [
            self._row("R_COLLIDE", "single", target, "movie.mkv"),
            self._row("R_COLLIDE", "single", victim, "movie.mkv"),
        ]

    def test_marked_abandon_increments_errors(self) -> None:
        res, _ = self._run_marked(self._colliding(), {"R_COLLIDE"})
        self.assertEqual(
            int(res.errors or 0),
            1,
            msg="un abandon destructif doit compter comme une ERREUR (UI: 'Erreurs : N')",
        )

    def test_losers_abandon_increments_errors(self) -> None:
        res, _ = self._run_losers(self._colliding(), {"R_COLLIDE"})
        self.assertEqual(int(res.errors or 0), 1)

    def test_summary_shows_abandoned_messages(self) -> None:
        """_summarize_apply doit LIRE result.error_messages (avant: aucun lecteur)."""
        result = core.ApplyResult()
        result.errors = 1
        result.error_messages.append(
            "MARKED_FOR_DELETION R_COLLIDE: row_id duplique dans le plan, "
            "deplacement abandonne (fail-closed)"
        )
        summary_txt = Path(self._tmp) / "summary.txt"
        run_paths = types.SimpleNamespace(
            run_dir=Path(self._tmp) / "run",
            summary_txt=summary_txt,
        )
        label: Callable[..., str] = lambda *a, **k: "n/a"  # noqa: E731

        apply_support._summarize_apply(
            result,
            {key: 0 for key in core.SKIP_REASON_LABELS_FR},
            0,
            0,
            {},
            cfg=self._cfg(),
            run_paths=run_paths,
            log_fn=self._log,
            dry_run=False,
            rows=[],
            cleanup_scope_label=label,
            cleanup_status_label=label,
            cleanup_reason_label=label,
        )

        text = summary_txt.read_text(encoding="utf-8")
        self.assertIn("ABANDONNE", text, msg=f"le resume doit exposer l'abandon ; got:\n{text}")
        self.assertIn("R_COLLIDE", text)
        self.assertNotIn(
            "- Aucun point d'attention bloquant apres apply.",
            text,
            msg="un abandon ne peut pas etre resume par 'aucun point d'attention'",
        )


# ---------------------------------------------------------------------------
# D3 : une row abandonnee reste dans l'apply normal (rien n'a bouge pour elle)
# ---------------------------------------------------------------------------
class D3AbandonedRowsStayInApplyLoopTests(_Base):
    def test_apply_rows_still_processes_abandoned_rows(self) -> None:
        victim = self.root / "Parrain.1972.720p"
        other = self.root / "Parrain2.1974.720p"
        self._write(victim / "movie.mkv")
        self._write(other / "movie.mkv")
        rows = [
            self._row("R_COLLIDE", "single", other, "movie.mkv", title="Le Parrain 2", year=1974),
            self._row("R_COLLIDE", "single", victim, "movie.mkv", title="Le Parrain", year=1972),
        ]
        decisions = {"R_COLLIDE": {"ok": True}}

        result = apply_core.apply_rows(
            self._cfg(),
            rows,
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
            record_op=self._record_op,
            marked_for_deletion_row_ids={"R_COLLIDE"},
        )

        # Fail-closed : rien dans le bucket destructif.
        bucket = self.run_review_root / "_user_marked_for_deletion"
        self.assertEqual(
            [p for p in bucket.rglob("*") if p.is_file()] if bucket.exists() else [],
            [],
        )
        # ... mais les deux films sont bien RANGES par la boucle apply normale.
        self.assertTrue(
            (self.root / "Le Parrain (1972)").exists(),
            msg=f"film abandonne ni deplace ni range (silencieux). root={list(self.root.iterdir())}",
        )
        self.assertTrue((self.root / "Le Parrain 2 (1974)").exists())
        self.assertEqual(int(result.errors or 0), 1, msg="l'abandon reste signale")


# ---------------------------------------------------------------------------
# D4 : compteur = FILMS (rows), pas FICHIERS (video + sidecars)
# ---------------------------------------------------------------------------
class D4CounterCountsFilmsTests(_Base):
    def _episode_with_sidecars(self) -> Path:
        season = self.root / "Breaking Bad S01"
        self._write(season / "Breaking Bad S01E01.mkv")
        self._write(season / "Breaking Bad S01E02.mkv")
        self._write(season / "Breaking Bad S01E02.fr.srt", b"1\n")
        self._write(season / "Breaking Bad S01E02.nfo", b"<m></m>")
        return season

    def test_marked_non_single_counts_one_film(self) -> None:
        season = self._episode_with_sidecars()
        row = self._row("R_EP2", "tv_episode", season, "Breaking Bad S01E02.mkv")

        res, _ = self._run_marked([row], {"R_EP2"})

        moved = {p.name for p in self._bucket_files()}
        self.assertIn("Breaking Bad S01E02.mkv", moved)
        self.assertEqual(
            res.marked_for_deletion_moved_count,
            1,
            msg=f"1 FILM deplace (video + {len(moved) - 1} sidecars), pas {len(moved)} 'films'",
        )

    def test_losers_non_single_counts_one_film(self) -> None:
        season = self._episode_with_sidecars()
        row = self._row("R_EP2", "tv_episode", season, "Breaking Bad S01E02.mkv")

        res, _ = self._run_losers([row], {"R_EP2"})

        self.assertEqual(res.duplicates_user_decided_moved_count, 1)


# ---------------------------------------------------------------------------
# D5 : `res` duck-type sans error_messages -> pas de crash
# ---------------------------------------------------------------------------
class _LegacyRes:
    """ApplyResult "ancienne" : aucun champ error_messages (retro-compat)."""

    def __init__(self) -> None:
        self.errors = 0
        self.marked_for_deletion_moved_count = 0
        self.duplicates_user_decided_moved_count = 0


class D5LegacyResultTests(_Base):
    def _colliding(self) -> List[core.PlanRow]:
        victim = self.root / "Le Parrain (1972)"
        target = self.root / "Le Parrain 2 (1974)"
        self._write(victim / "movie.mkv")
        self._write(target / "movie.mkv")
        return [
            self._row("R_COLLIDE", "single", target, "movie.mkv"),
            self._row("R_COLLIDE", "single", victim, "movie.mkv"),
        ]

    def test_marked_abandon_does_not_crash_on_legacy_res(self) -> None:
        res = _LegacyRes()
        self._run_marked(self._colliding(), {"R_COLLIDE"}, res=res)  # ne doit pas lever
        self.assertEqual(res.errors, 1)
        self.assertEqual(self._bucket_files(), [])

    def test_losers_abandon_does_not_crash_on_legacy_res(self) -> None:
        res = _LegacyRes()
        self._run_losers(self._colliding(), {"R_COLLIDE"}, res=res)
        self.assertEqual(res.errors, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
