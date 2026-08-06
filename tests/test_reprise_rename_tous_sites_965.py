"""La reprise de #965 couvre TOUS les renommages de dossier, pas seulement `apply_single`.

#965 a mesure une course de quelques microsecondes qui fait perdre un
deplacement (`PermissionError [WinError 5]`, `errors=1`, rien de deplace, rien
de journalise), et l'a corrigee par `renommer_avec_reprise`. Le correctif
n'avait ete pose que sur UN site : `apply_single`.

Or le renommage de dossier passe aussi par `move_journal._rename_or_cross_device_copy`,
qui est le passage OBLIGE d'`atomic_move(..., allow_copy_fallback=False)`, donc
des huit sites qui deplacent un dossier entier : doublons ecartes, marques pour
suppression, dossier de collection, mise en quarantaine, bucket de nettoyage,
rollback, et les deux sites de l'undo. Sur ces deux derniers la course coute le
plus cher : c'est le filet de secours de l'utilisateur.

Meme motif que l'audit du 2026-08-05 (`allow_copy_fallback=False` pose sur un
seul site alors qu'il en manquait six) : une garde n'est acquise que lorsqu'elle
couvre tous ses sites.

Ce que ces tests verrouillent, et qu'une mesure de taux ne peut pas verrouiller
(elle est statistique, donc inutilisable en CI) :
  - une course qui se resout ne perd plus le deplacement, sur le chemin partage ;
  - un vrai EXDEV degrade TOUJOURS en copie : la reprise ne doit pas manger le
    cas qui justifie l'existence de `_rename_or_cross_device_copy` ;
  - un verrou PERSISTANT echoue toujours, avec l'exception d'origine ;
  - le renommage de casse seule (`.__tmp_ren`) ne part plus en rollback inutile ;
  - le CABLAGE reel : `atomic_move` de bout en bout, sur un vrai systeme de
    fichiers. Sans ce dernier test, remettre `Path(src).rename(dst)` dans
    `_rename_or_cross_device_copy` laisse tous les tests unitaires VERTS — c'est
    le « piege du test vide au site d'appel » deja rencontre trois fois ici.
"""

from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app.apply_core import _case_only_rename_with_rollback
from cinesort.app.move_journal import _rename_or_cross_device_copy, atomic_move

_VRAI_RENAME = Path.rename


def _refus(winerror: int) -> PermissionError:
    """Le refus d'acces Windows mesure par #965 (WinError 5) ou un partage (32)."""
    exc = PermissionError(13, "Acces refuse")
    exc.winerror = winerror
    return exc


def _exdev() -> OSError:
    """Un VRAI franchissement de volume : le seul cas qui doit degrader en copie."""
    exc = OSError(errno.EXDEV, "Invalid cross-device link")
    exc.errno = errno.EXDEV
    return exc


class RenameCheminPartageTests(unittest.TestCase):
    """`_rename_or_cross_device_copy` : le passage oblige des 8 sites de MOVE_DIR."""

    def test_une_course_qui_se_resout_ne_perd_plus_le_deplacement(self) -> None:
        appels: list = []

        def _rename(self, cible):  # noqa: ANN001, ARG001
            appels.append(cible)
            if len(appels) == 1:
                raise _refus(5)

        with mock.patch.object(Path, "rename", _rename):
            _rename_or_cross_device_copy(Path("source"), Path("cible"))

        self.assertEqual(len(appels), 2, "le renommage aurait du etre reessaye exactement une fois")

    def test_un_vrai_exdev_degrade_toujours_en_copie(self) -> None:
        """Garde anti-regression : la reprise ne doit pas avaler le cas EXDEV."""

        def _rename(self, cible):  # noqa: ANN001, ARG001
            raise _exdev()

        with mock.patch.object(Path, "rename", _rename):
            with mock.patch("cinesort.app.move_journal.shutil.move") as move:
                _rename_or_cross_device_copy(Path("source"), Path("cible"))

        move.assert_called_once_with("source", "cible")

    def test_un_verrou_PERSISTANT_echoue_toujours(self) -> None:
        """La reprise ne doit JAMAIS transformer un vrai verrou en succes silencieux."""

        def _rename(self, cible):  # noqa: ANN001, ARG001
            raise _refus(5)

        with mock.patch.object(Path, "rename", _rename):
            with mock.patch("cinesort.app.move_journal.shutil.move") as move:
                with self.assertRaises(PermissionError) as ctx:
                    _rename_or_cross_device_copy(Path("source"), Path("cible"))

        self.assertEqual(ctx.exception.winerror, 5, "l'exception d'origine doit remonter telle quelle")
        move.assert_not_called()


class RenommageDeCasseTests(unittest.TestCase):
    """`_case_only_rename_with_rollback` : 3 renommages de DOSSIER, tous exposes."""

    def test_une_course_sur_le_2e_rename_ne_declenche_plus_de_rollback(self) -> None:
        """Perdre le 2e rename declenche un rollback qui n'avait aucune raison d'etre."""
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            folder = racine / "Film"
            folder.mkdir()
            dst = racine / "film"
            echecs: list = []

            def _rename(self, cible):  # noqa: ANN001
                # Le 2e renommage (tmp -> dst) echoue une seule fois.
                if cible == dst and not echecs:
                    echecs.append(cible)
                    raise _refus(5)
                return _VRAI_RENAME(self, cible)

            with mock.patch.object(Path, "rename", _rename):
                _case_only_rename_with_rollback(folder, dst)

            self.assertEqual(len(echecs), 1, "la course doit bien avoir eu lieu")
            restants = sorted(p.name for p in racine.iterdir())
            self.assertEqual(restants, ["film"], "le dossier ne doit pas rester en .__tmp_ren")


class CablageAtomicMoveTests(unittest.TestCase):
    """Le site d'appel REEL, sur un vrai systeme de fichiers.

    C'est ce test qui echoue si `_rename_or_cross_device_copy` reprend
    `Path(src).rename(dst)` : les tests unitaires ci-dessus, eux, resteraient
    verts puisqu'ils appellent le helper directement.
    """

    def test_atomic_move_dossier_survit_a_la_course(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            src = racine / "Film (2010)"
            src.mkdir()
            (src / "film.mkv").write_bytes(b"x" * 32)
            dst = racine / "_review" / "Film (2010)"
            dst.parent.mkdir(parents=True, exist_ok=True)
            echecs: list = []

            def _rename(self, cible):  # noqa: ANN001
                if cible == dst and not echecs:
                    echecs.append(cible)
                    raise _refus(5)
                return _VRAI_RENAME(self, cible)

            with mock.patch.object(Path, "rename", _rename):
                atomic_move(None, src=src, dst=dst, op_type="MOVE_DIR", allow_copy_fallback=False)

            self.assertEqual(len(echecs), 1, "la course doit bien avoir eu lieu")
            self.assertFalse(src.exists(), "la source doit avoir ete deplacee")
            self.assertTrue((dst / "film.mkv").is_file(), "le contenu doit etre arrive intact a destination")


if __name__ == "__main__":
    unittest.main()
