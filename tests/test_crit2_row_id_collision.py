"""Non-regression AUDIT 2026-07-13 [CRIT-2] : row_id dupliques -> fail-closed.

Bug : dans move_duplicate_losers_to_user_decided et move_marked_for_deletion_to_bucket
(apply_core), l'index `by_row` etait construit en `by_row[rid] = r` LAST-WINS
SILENCIEUX. Si deux PlanRow partagent un row_id (collision possible tant que des
row_id legacy 32 bits circulent), le row_id choisi par l'utilisateur resolvait vers
le DERNIER PlanRow vu, c.-a-d. potentiellement le MAUVAIS film : un film JAMAIS
marque sortait de la bibliotheque (bucket que l'utilisateur vide lui-meme => perte
definitive), pendant que le film reellement vise y restait.

Fix : _index_rows_by_id detecte la collision -> log ERROR + le row_id ambigu est
ABANDONNE par les deux operations destructives (fail-closed : ne rien deplacer vaut
mieux que deplacer au hasard).

AVANT le fix, ces tests ECHOUENT (un des deux films est deplace) ; APRES ils PASSENT.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class _CollisionTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_crit2_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket = Path(self._tmp) / "state" / "_review" / "_bucket"
        self.bucket.mkdir(parents=True, exist_ok=True)
        self.logs: List[tuple] = []
        self.ops: List[dict] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _record_op(self, payload: dict) -> None:
        self.ops.append(dict(payload))

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _row(self, row_id: str, kind: str, folder: Path, video: str) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind=kind,
            folder=str(folder),
            video=video,
            proposed_title="Titre",
            proposed_year=2010,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
        )

    def _make_movie(self, name: str) -> Path:
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(b"X" * 64)
        return folder

    def _errors(self) -> List[str]:
        return [msg for lvl, msg in self.logs if lvl == "ERROR"]

    def _bucket_files(self) -> List[Path]:
        return [p for p in self.bucket.rglob("*") if p.is_file()]

    def _colliding_rows(self) -> tuple:
        """Deux films DIFFERENTS qui partagent le meme row_id (collision 32 bits)."""
        victim = self._make_movie("Le Parrain (1972)")  # JAMAIS vise par l'utilisateur
        target = self._make_movie("Le Parrain 2 (1974)")  # le vrai doublon/marque
        rows = [
            self._row("R_COLLIDE", "single", target, "movie.mkv"),
            # last-wins : c'est CE row (la victime) que l'index resolvait avant le fix
            self._row("R_COLLIDE", "single", victim, "movie.mkv"),
        ]
        return victim, target, rows


class MarkedForDeletionCollisionTests(_CollisionTestBase):
    def _run(self, rows: List[core.PlanRow], marked: set) -> core.ApplyResult:
        res = core.ApplyResult()
        apply_core.move_marked_for_deletion_to_bucket(
            self._cfg(),
            rows,
            marked,
            marked_for_deletion_root=self.bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        return res

    def test_duplicate_row_id_moves_nothing_and_logs_error(self) -> None:
        victim, target, rows = self._colliding_rows()

        res = self._run(rows, {"R_COLLIDE"})

        # FAIL-CLOSED : aucun des deux films ne sort de la bibliotheque.
        self.assertTrue(
            (victim / "movie.mkv").exists(),
            msg="PERTE DE FICHIERS : un film JAMAIS marque a ete emporte par une collision de row_id",
        )
        self.assertTrue((target / "movie.mkv").exists())
        self.assertEqual(self._bucket_files(), [], msg="aucun fichier ne doit atteindre le bucket")
        self.assertEqual(self.ops, [], msg="aucune operation destructive ne doit etre journalisee")
        self.assertEqual(res.marked_for_deletion_moved_count, 0)

        # Signal explicite (log ERROR + remontee UI).
        errors = self._errors()
        self.assertTrue(
            any("R_COLLIDE" in msg for msg in errors),
            msg=f"un log ERROR doit signaler le row_id duplique ; logs={self.logs}",
        )
        self.assertTrue(
            any("R_COLLIDE" in msg for msg in res.error_messages),
            msg=f"l'abandon doit remonter dans res.error_messages ; got={res.error_messages}",
        )

    def test_unique_row_ids_still_move(self) -> None:
        """Non-regression : sans collision, l'operation destructive fonctionne."""
        keep = self._make_movie("Le Parrain (1972)")
        target = self._make_movie("Le Parrain 2 (1974)")
        rows = [
            self._row("R_KEEP", "single", keep, "movie.mkv"),
            self._row("R_MARK", "single", target, "movie.mkv"),
        ]

        res = self._run(rows, {"R_MARK"})

        self.assertTrue((keep / "movie.mkv").exists())
        self.assertFalse(target.exists())
        self.assertTrue((self.bucket / "Le Parrain 2 (1974)" / "movie.mkv").exists())
        self.assertEqual(res.marked_for_deletion_moved_count, 1)
        self.assertEqual(self._errors(), [])


class DuplicateLoserCollisionTests(_CollisionTestBase):
    def _run(self, rows: List[core.PlanRow], losers: set) -> core.ApplyResult:
        res = core.ApplyResult()
        apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            rows,
            losers,
            duplicates_user_decided_root=self.bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        return res

    def test_duplicate_row_id_moves_nothing_and_logs_error(self) -> None:
        victim, target, rows = self._colliding_rows()

        res = self._run(rows, {"R_COLLIDE"})

        self.assertTrue(
            (victim / "movie.mkv").exists(),
            msg="PERTE DE FICHIERS : un film JAMAIS designe loser a ete emporte par une collision",
        )
        self.assertTrue((target / "movie.mkv").exists())
        self.assertEqual(self._bucket_files(), [])
        self.assertEqual(self.ops, [])
        self.assertEqual(res.duplicates_user_decided_moved_count, 0)

        errors = self._errors()
        self.assertTrue(
            any("R_COLLIDE" in msg for msg in errors),
            msg=f"un log ERROR doit signaler le row_id duplique ; logs={self.logs}",
        )
        self.assertTrue(any("R_COLLIDE" in msg for msg in res.error_messages))

    def test_unique_row_ids_still_move(self) -> None:
        keep = self._make_movie("Heat (1995) 1080p")
        loser = self._make_movie("Heat (1995) 720p")
        rows = [
            self._row("R_WINNER", "single", keep, "movie.mkv"),
            self._row("R_LOSER", "single", loser, "movie.mkv"),
        ]

        res = self._run(rows, {"R_LOSER"})

        self.assertTrue((keep / "movie.mkv").exists())
        self.assertFalse(loser.exists())
        self.assertEqual(res.duplicates_user_decided_moved_count, 1)
        self.assertEqual(self._errors(), [])


class PlanRowKindDocumentationTests(unittest.TestCase):
    """[CRIT-1] cause racine documentaire : le commentaire de PlanRow.kind omettait
    "extra", et la garde destructive avait ete ecrite contre cette liste fausse."""

    def test_kind_comment_lists_extra(self) -> None:
        src = Path(core.__file__).read_text(encoding="utf-8")
        line = next(ln for ln in src.splitlines() if ln.strip().startswith("kind: str"))
        for kind in ("single", "collection", "tv_episode", "extra"):
            self.assertIn(
                kind,
                line,
                msg=f"le commentaire de PlanRow.kind doit lister {kind!r} ; got: {line!r}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
