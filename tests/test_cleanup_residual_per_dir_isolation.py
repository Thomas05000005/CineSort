"""Le nettoyage residuel doit isoler chaque dossier et ne jamais copier-puis-detruire.

Deux defauts distincts, mesures sur Windows 11 avec un verrou REEL (un simple
`open()` sur un fichier interne suffit : indexeur, antivirus, apercu
Explorateur, editeur de .nfo produisent le meme effet).

1. `_move_dirs_to_bucket` bouclait SANS try/except par item et les callers
   faisaient `res.<compteur> += _move_dirs_to_bucket(...)`. Le garde F10 de
   `apply_core` etant pose autour de la fonction ENTIERE, un verrou sur le 2e
   dossier faisait : dossiers suivants jamais traites, et `+=` saute en bloc
   donc le resume affichait « Dossiers residuels deplaces : 0 » alors qu'un
   dossier complet avait deja quitte la bibliotheque.

2. `shutil.move` (via `atomic_move`) retombe sur copytree + rmtree des que
   `os.rename` echoue. Sur verrou, le dossier etait donc INTEGRALEMENT COPIE
   dans le bucket puis le rmtree source mourait sur le fichier verrouille :
   contenu dedouble, source eventree — et comme `record_apply_op` n'est appele
   qu'APRES le move, cette copie n'etait journalisee nulle part, donc invisible
   de l'undo et non annulable.

FUSION AVEC main (issue #670) : le correctif 2 ne SORT PAS ce site du journal
write-ahead. Il se traduit par `atomic_move(..., allow_copy_fallback=False)`,
qui garde `journaled_move` et ne remplace que `shutil.move` par un `os.rename`
degradable en copie sur le seul EXDEV. La classe `RepliCrossDeviceTests`
ci-dessous couvre ce repli, seul chemin ou la copie reste legitime.
"""

from __future__ import annotations

import errno
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from cinesort.app import cleanup as cleanup_mod
from cinesort.app import move_journal as move_journal_mod
from cinesort.domain import core as core_mod


class _OpRecorder:
    def __init__(self) -> None:
        self.ops: List[Dict[str, Any]] = []

    def __call__(self, payload: Dict[str, Any]) -> None:
        self.ops.append(dict(payload))

    def move_dirs(self) -> List[str]:
        return [str(op.get("src_path")) for op in self.ops if op.get("op_type") == "MOVE_DIR"]


class ResidualCleanupIsolationTests(unittest.TestCase):
    SIDECARS = ("film.nfo", "poster.jpg", "film.srt")

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_residual_"))
        self.root = self._tmp / "Films"
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))

    def _make_residual(self, name: str) -> Path:
        folder = self.root / name
        folder.mkdir()
        for sidecar in self.SIDECARS:
            (folder / sidecar).write_text(sidecar, encoding="utf-8")
        return folder

    def _cfg(self) -> core_mod.Config:
        return core_mod.Config(
            root=self.root,
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_scope="root_all",
        ).normalized()

    def _run(self, cfg: core_mod.Config, record_op: Any) -> core_mod.ApplyResult:
        res = core_mod.ApplyResult()
        cleanup_mod._move_residual_top_level_dirs(
            cfg,
            dry_run=False,
            log=lambda _level, _message: None,
            res=res,
            touched_top_level_dirs=set(),
            record_op=record_op,
        )
        return res

    def test_verrou_sur_un_dossier_n_arrete_pas_les_autres_et_ne_copie_rien(self) -> None:
        aaa = self._make_residual("AAA residuel")
        bbb = self._make_residual("BBB residuel")
        ccc = self._make_residual("CCC residuel")
        bucket = self.root / "_Dossier Nettoyage"
        recorder = _OpRecorder()

        with open(bbb / "film.srt", "rb"):  # verrou Windows reel sur UN fichier interne
            res = self._run(self._cfg(), recorder)

        self.assertFalse(aaa.exists(), "AAA doit avoir ete deplace")
        self.assertFalse(ccc.exists(), "CCC ne doit plus etre saute a cause du verrou sur BBB")
        self.assertTrue((bucket / "AAA residuel").is_dir())
        self.assertTrue((bucket / "CCC residuel").is_dir())

        # Defaut 2 : aucune copie ne doit avoir ete faite pour le dossier verrouille.
        self.assertFalse(
            (bucket / "BBB residuel").exists(),
            "le dossier verrouille ne doit PAS avoir ete copie dans le bucket",
        )
        self.assertEqual(
            sorted(p.name for p in bbb.iterdir()),
            sorted(self.SIDECARS),
            "la source verrouillee doit rester INTACTE (avant : eventree par le rmtree de shutil.move)",
        )

        # Defaut 1 : compteur et erreurs coherents avec la realite disque.
        self.assertEqual(
            res.cleanup_residual_folders_moved_count,
            2,
            "les deux dossiers reellement deplaces doivent etre comptes",
        )
        self.assertEqual(res.errors, 1, "le dossier verrouille doit compter pour exactement une erreur")
        self.assertTrue(
            any("BBB residuel" in str(message) for message in res.error_messages),
            f"le dossier en echec doit etre nomme : {res.error_messages}",
        )

        # Undo : les deux deplacements reels sont journalises, aucun autre.
        self.assertEqual(
            sorted(Path(p).name for p in recorder.move_dirs()),
            ["AAA residuel", "CCC residuel"],
            "seuls les deplacements reellement aboutis doivent etre journalises",
        )

    def test_nominal_sans_verrou_inchange(self) -> None:
        """NON-REGRESSION : sans verrou, les 3 dossiers partent et rien n'est en erreur."""
        self._make_residual("AAA residuel")
        self._make_residual("BBB residuel")
        self._make_residual("CCC residuel")
        bucket = self.root / "_Dossier Nettoyage"
        recorder = _OpRecorder()

        res = self._run(self._cfg(), recorder)

        self.assertEqual(res.cleanup_residual_folders_moved_count, 3)
        self.assertEqual(res.errors, 0, f"aucune erreur attendue : {res.error_messages}")
        self.assertEqual(len(recorder.move_dirs()), 3)
        for name in ("AAA residuel", "BBB residuel", "CCC residuel"):
            self.assertFalse((self.root / name).exists())
            self.assertEqual(
                sorted(p.name for p in (bucket / name).iterdir()),
                sorted(self.SIDECARS),
                "le contenu doit arriver complet dans le bucket",
            )

    def test_dossiers_vides_comptes_dossier_par_dossier(self) -> None:
        """Le second call site (`_Vide`) partage le meme compteur incremental."""
        (self.root / "Vide 1").mkdir()
        (self.root / "Vide 2").mkdir()
        cfg = core_mod.Config(
            root=self.root,
            move_empty_folders_enabled=True,
            empty_folders_scope="root_all",
        ).normalized()
        res = core_mod.ApplyResult()
        recorder = _OpRecorder()

        cleanup_mod._move_empty_top_level_dirs(
            cfg,
            dry_run=False,
            log=lambda _level, _message: None,
            res=res,
            touched_top_level_dirs=set(),
            record_op=recorder,
        )

        self.assertEqual(res.empty_folders_moved_count, 2)
        self.assertEqual(res.errors, 0)
        self.assertTrue((self.root / "_Vide" / "Vide 1").is_dir())
        self.assertTrue((self.root / "_Vide" / "Vide 2").is_dir())


class RepliCrossDeviceTests(unittest.TestCase):
    """`allow_copy_fallback=False` : rename d'abord, copie SEULEMENT sur EXDEV.

    Ecrite a la fusion avec main. Les deux cotes prouvaient chacun une moitie :
    PR#852 « pas de copie sur un verrou » et #670 « le site reste journalise ».
    Aucun ne couvrait la frontiere entre les deux — le seul cas ou la copie
    reste la bonne reponse, un vrai franchissement de volume.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_exdev_"))
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self.src = self._tmp / "Source"
        self.src.mkdir()
        (self.src / "film.nfo").write_text("nfo", encoding="utf-8")
        self.dst = self._tmp / "bucket" / "Source"
        self.dst.parent.mkdir()

    def test_rename_nominal_ne_passe_jamais_par_shutil(self) -> None:
        with mock.patch.object(move_journal_mod.shutil, "move") as fake_move:
            move_journal_mod._rename_or_cross_device_copy(self.src, self.dst)

        fake_move.assert_not_called()
        self.assertTrue((self.dst / "film.nfo").is_file())
        self.assertFalse(self.src.exists())

    def test_verrou_non_exdev_remonte_sans_copier(self) -> None:
        """Le coeur du correctif : une erreur qui n'est PAS un EXDEV ne copie rien."""
        verrou = PermissionError(errno.EACCES, "verrou")
        verrou.winerror = 32  # type: ignore[attr-defined]

        with mock.patch.object(Path, "rename", side_effect=verrou):
            with mock.patch.object(move_journal_mod.shutil, "move") as fake_move:
                with self.assertRaises(PermissionError):
                    move_journal_mod._rename_or_cross_device_copy(self.src, self.dst)

        fake_move.assert_not_called()
        self.assertTrue((self.src / "film.nfo").is_file(), "la source doit rester INTACTE")
        self.assertFalse(self.dst.exists(), "aucune copie ne doit avoir ete faite")

    def test_exdev_errno_degrade_en_copie(self) -> None:
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(Path, "rename", side_effect=exdev):
            move_journal_mod._rename_or_cross_device_copy(self.src, self.dst)

        self.assertTrue((self.dst / "film.nfo").is_file(), "sur un vrai EXDEV, la copie est l'unique issue")
        self.assertFalse(self.src.exists())

    def test_exdev_winerror_17_degrade_en_copie(self) -> None:
        """Windows ne renseigne pas toujours errno.EXDEV : le winerror brut compte."""
        exdev = OSError(errno.EINVAL, "pas le meme volume")
        exdev.winerror = 17  # type: ignore[attr-defined]

        with mock.patch.object(Path, "rename", side_effect=exdev):
            move_journal_mod._rename_or_cross_device_copy(self.src, self.dst)

        self.assertTrue((self.dst / "film.nfo").is_file())
        self.assertFalse(self.src.exists())

    def test_atomic_move_sans_repli_reste_dans_le_journal(self) -> None:
        """Frontiere avec #670 : couper la copie ne doit pas couper le journal."""
        appels: Dict[str, int] = {"insert": 0, "delete": 0}

        class _Store:
            def __init__(self) -> None:
                self.apply = self

            def insert_pending_move(self, **_kwargs: Any) -> int:
                appels["insert"] += 1
                return 1

            def delete_pending_move(self, _pending_id: int) -> None:
                appels["delete"] += 1

        record_op = move_journal_mod.RecordOpWithJournal(lambda _payload: None, store=_Store(), batch_id="b1")
        move_journal_mod.atomic_move(
            record_op,
            src=self.src,
            dst=self.dst,
            op_type="MOVE_DIR",
            allow_copy_fallback=False,
        )

        self.assertEqual(appels, {"insert": 1, "delete": 1}, "le journal write-ahead doit rester pose")
        self.assertTrue((self.dst / "film.nfo").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
