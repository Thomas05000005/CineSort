"""Un DOSSIER entier ne doit JAMAIS partir en copytree+rmtree sur un verrou.

`shutil.move` retombe sur copytree + rmtree des que `os.rename` echoue, y compris
sur un banal verrou Windows d'UN fichier interne (indexeur, antivirus, apercu
Explorateur, editeur de .nfo). Mesure reportee dans
`move_journal._rename_or_cross_device_copy` :

- `Path.rename` -> PermissionError WinError 5, source INTACTE, destination ABSENTE ;
- `shutil.move`  -> PermissionError WinError 32, destination peuplee ET source
  amputee : contenu dedouble, source eventree.

`cleanup._move_dir_without_destructive_fallback` posait deja le garde
(`allow_copy_fallback=False`), mais il ne couvrait qu'un seul site. Les
deplacements de dossier de l'apply (quarantaine, doublons perdants, marques pour
suppression, collection) et les deux chemins de SECOURS (undo, rollback atomique)
passaient encore par `shutil.move` nu. Ce module verrouille les trois familles.

Les op_type `*_FILE` ne sont PAS concernes et gardent `shutil.move` : pour un
fichier isole, la copie fait justement aboutir un deplacement que `rename` refuse
sur un verrou en lecture partagee, et elle ne peut eventrer aucun dossier.
"""

from __future__ import annotations

import errno
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import cinesort.app.apply_core as apply_core
import cinesort.app.apply_rollback as apply_rollback
import cinesort.app.move_journal as move_journal_mod
import cinesort.domain.core as core


def _verrou_windows() -> PermissionError:
    """Verrou de fichier : une erreur qui n'est PAS un franchissement de volume."""
    exc = PermissionError(errno.EACCES, "utilise par un autre processus")
    exc.winerror = 32  # type: ignore[attr-defined]
    return exc


class _MoveDirBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_movedir_"))
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self.root = self._tmp / "Films"
        self.root.mkdir()

    def _dossier_film(self, name: str) -> Path:
        folder = self.root / name
        folder.mkdir(parents=True)
        (folder / f"{name}.mkv").write_bytes(b"video")
        (folder / f"{name}.nfo").write_text("nfo", encoding="utf-8")
        (folder / f"{name}.fr.srt").write_text("srt", encoding="utf-8")
        return folder

    @staticmethod
    def _log(_level: str, _message: str) -> None:
        return None


class QuarantineDirNeCopiePasTests(_MoveDirBase):
    """`quarantine_row` (kind 'single') deplace le dossier COMPLET sous `_review/`."""

    def _row(self, folder: Path) -> core.PlanRow:
        return core.PlanRow(
            row_id="S|q",
            kind="single",
            folder=str(folder),
            video=f"{folder.name}.mkv",
            proposed_title="Film",
            proposed_year=2020,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title="Film", year=2020, source="name", score=0.7)],
        )

    def test_verrou_ne_dedouble_pas_le_dossier(self) -> None:
        folder = self._dossier_film("Film.2020.1080p")
        cfg = core.Config(root=self.root).normalized()
        res = core.ApplyResult()

        with mock.patch.object(Path, "rename", side_effect=_verrou_windows()):
            with mock.patch.object(move_journal_mod.shutil, "move") as fake_move:
                with self.assertRaises(PermissionError):
                    apply_core.quarantine_row(
                        cfg,
                        folder,
                        self._row(folder),
                        False,
                        self._log,
                        res,
                        self.root / "_review",
                    )

        fake_move.assert_not_called()
        self.assertTrue((folder / "Film.2020.1080p.mkv").is_file(), "la source doit rester INTACTE")
        self.assertTrue((folder / "Film.2020.1080p.nfo").is_file())
        self.assertTrue((folder / "Film.2020.1080p.fr.srt").is_file())
        self.assertFalse((self.root / "_review" / "Film.2020.1080p").exists(), "aucune copie ne doit exister")

    def test_nominal_range_toujours_le_dossier(self) -> None:
        """Non-regression : sans verrou, la quarantaine fonctionne comme avant."""
        folder = self._dossier_film("Film.2021.1080p")
        cfg = core.Config(root=self.root).normalized()
        res = core.ApplyResult()
        # `quarantine_row` ne cree pas `_review` lui-meme (c'est `apply_rows` en
        # amont) : `os.rename` exige un parent existant.
        (self.root / "_review").mkdir(parents=True, exist_ok=True)

        apply_core.quarantine_row(
            cfg,
            folder,
            self._row(folder),
            False,
            self._log,
            res,
            self.root / "_review",
        )

        cible = self.root / "_review" / "Film.2021.1080p"
        self.assertTrue((cible / "Film.2021.1080p.mkv").is_file())
        self.assertTrue((cible / "Film.2021.1080p.nfo").is_file())
        self.assertFalse(folder.exists())
        self.assertEqual(res.quarantined, 1)


class RollbackDirNeCopiePasTests(_MoveDirBase):
    """`apply_rollback._revert_one_op` : le filet de secours ne doit pas eventrer."""

    def _op(self, op_type: str, src: Path, dst: Path) -> Dict[str, Any]:
        return {
            "id": 1,
            "op_index": 0,
            "op_type": op_type,
            "src_path": str(src),
            "dst_path": str(dst),
            "reversible": 1,
            "undo_status": "PENDING",
        }

    def test_move_dir_verrou_ne_copie_rien(self) -> None:
        dst = self._dossier_film("Range.2020.1080p")
        src = self.root / "Origine.2020.1080p"

        with mock.patch.object(Path, "rename", side_effect=_verrou_windows()):
            with mock.patch.object(move_journal_mod.shutil, "move") as fake_move:
                result = apply_rollback._revert_one_op(self._op("MOVE_DIR", src, dst))

        fake_move.assert_not_called()
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue((dst / "Range.2020.1080p.mkv").is_file(), "la destination doit rester INTACTE")
        self.assertTrue((dst / "Range.2020.1080p.nfo").is_file())
        self.assertFalse(src.exists(), "aucune copie partielle ne doit avoir ete faite")

    def test_move_dir_nominal_revert_toujours(self) -> None:
        """Non-regression : sans verrou, le revert dossier aboutit."""
        dst = self._dossier_film("Range.2021.1080p")
        src = self.root / "Origine.2021.1080p"

        result = apply_rollback._revert_one_op(self._op("MOVE_DIR", src, dst))

        self.assertEqual(result["status"], "DONE")
        self.assertTrue((src / "Range.2021.1080p.mkv").is_file())
        self.assertFalse(dst.exists())

    def test_move_file_garde_shutil_move(self) -> None:
        """Un FICHIER isole garde la copie : elle ne peut eventrer aucun dossier."""
        dossier = self._dossier_film("Film.2022.1080p")
        dst = dossier / "Film.2022.1080p.mkv"
        src = self.root / "Ailleurs" / "Film.2022.1080p.mkv"

        with mock.patch.object(move_journal_mod.shutil, "move") as fake_move:
            result = apply_rollback._revert_one_op(self._op("MOVE_FILE", src, dst))

        fake_move.assert_called_once_with(str(dst), str(src))
        self.assertEqual(result["status"], "DONE")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
