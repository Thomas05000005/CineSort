"""Un fichier ILLISIBLE n'est pas un fichier CORROMPU.

`check_header` rend `(False, <detail>)` dans quatre cas. Trois portent sur des
octets REELLEMENT lus (`empty_file`, `file_too_small`, `header_mismatch`) ; le
quatrieme, `DETAIL_READ_ERROR`, dit seulement que l'ouverture a echoue — verrou
antivirus, partage reseau tombe, permission refusee, fichier disparu depuis le
scan.

`_apply_integrity_check` jetait ce detail (`hdr_valid, _hdr_detail = ...`) et ne
regardait que le booleen : l'ignorance posait donc exactement le meme drapeau
qu'une incoherence de magic bytes. Or ce drapeau n'est pas decoratif, et la
chaine est deja etablie par le depot (cf. le finding #782 / PR #784, qui l'a
jugee de severite HIGH pour le seul cas des `.m2ts`) :

    plan_support_replan._apply_integrity_check
      -> warning_flags += "integrity_header_invalid"
         -> run_read_support._AUTO_INTEGRITY_WARNINGS  (sortie de l'auto-approbation)
         -> dashboard_support._SIDEBAR_CRITICAL_FLAGS  (alerte critique)
         -> get_auto_approved_summary(quarantine_corrupted=True)
            -> auto_quarantine_row_ids : le rejet est PRE-COCHE, le film part
               en quarantaine.

Soit un deplacement de fichier decide sur une ignorance — le motif que ce depot
nomme « l'absence de connaissance doit produire un refus de trancher ».

Les contre-tests ci-dessous sont la partie qui compte : le remede ne doit pas
faire taire le drapeau au-dela du seul cas ou la lecture a echoue.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.app.plan_support_replan import _apply_integrity_check
from cinesort.domain.core import PlanRow
from cinesort.domain.integrity_check import DETAIL_READ_ERROR, check_header

# En-tete EBML d'un Matroska valide.
_MAGIC_MKV = bytes([0x1A, 0x45, 0xDF, 0xA3])
_FLAG = "integrity_header_invalid"


def _row() -> PlanRow:
    """Une PlanRow minimale : seul `warning_flags` est lu par la fonction."""
    return PlanRow(
        row_id="r1",
        kind="single",
        folder="/bibliotheque/Film (2010)",
        video="film.mkv",
        proposed_title="Film",
        proposed_year=2010,
        proposed_source="name",
        confidence=90,
        confidence_label="high",
        candidates=[],
    )


class LectureImpossibleTests(unittest.TestCase):
    """Le cas du defaut : nous n'avons pas pu lire, donc nous ne savons rien."""

    def test_un_dossier_portant_l_extension_video_rend_read_error(self) -> None:
        """Le contrat dont depend le remede, etabli avant de s'en servir.

        Un DOSSIER nomme `film.mkv` est le cas d'illisibilite reproductible sur
        les deux plateformes : `open()` y leve `IsADirectoryError` sous Linux et
        `PermissionError` sous Windows — deux `OSError`, donc `DETAIL_READ_ERROR`
        des deux cotes.
        """
        with tempfile.TemporaryDirectory(prefix="cinesort_integrite_") as tmp:
            illisible = Path(tmp) / "film.mkv"
            illisible.mkdir()

            valide, detail = check_header(illisible)

        self.assertFalse(valide)
        self.assertEqual(detail, DETAIL_READ_ERROR)

    def test_un_fichier_illisible_ne_pose_PAS_le_drapeau(self) -> None:
        """Le coeur du correctif."""
        with tempfile.TemporaryDirectory(prefix="cinesort_integrite_") as tmp:
            illisible = Path(tmp) / "film.mkv"
            illisible.mkdir()
            row = _row()

            _apply_integrity_check(illisible, row)

        self.assertEqual(
            row.warning_flags,
            [],
            "une lecture impossible ne prouve rien sur le contenu : elle ne doit pas "
            "sortir le film de l'auto-approbation ni le faire pre-cocher pour la quarantaine",
        )

    def test_un_fichier_disparu_depuis_le_scan_ne_pose_PAS_le_drapeau(self) -> None:
        """Entre le scan et ce controle, le fichier peut avoir bouge."""
        with tempfile.TemporaryDirectory(prefix="cinesort_integrite_") as tmp:
            absent = Path(tmp) / "jamais_la.mkv"
            row = _row()

            _apply_integrity_check(absent, row)

        self.assertEqual(row.warning_flags, [], "un fichier introuvable n'est pas un fichier corrompu")


class ContreTestsLeDrapeauResteAtteignableTests(unittest.TestCase):
    """Sans eux, « ne plus jamais poser le drapeau » passerait aussi."""

    def _flags_pour(self, contenu: bytes, *, nom: str = "film.mkv") -> list[str]:
        with tempfile.TemporaryDirectory(prefix="cinesort_integrite_") as tmp:
            video = Path(tmp) / nom
            video.write_bytes(contenu)
            row = _row()
            _apply_integrity_check(video, row)
            return list(row.warning_flags)

    def test_des_magic_bytes_incoherents_posent_toujours_le_drapeau(self) -> None:
        """Le but du controle — detecter un fichier renomme — est preserve."""
        self.assertEqual(self._flags_pour(b"PAS UN MKV" + b"\x11" * 512), [_FLAG])

    def test_un_fichier_vide_pose_toujours_le_drapeau(self) -> None:
        """0 octet est un CONSTAT (la lecture a reussi), pas une ignorance."""
        self.assertEqual(self._flags_pour(b""), [_FLAG])

    def test_un_fichier_trop_court_pose_toujours_le_drapeau(self) -> None:
        """`file_too_small` porte lui aussi sur des octets reellement lus."""
        self.assertEqual(self._flags_pour(b"AB"), [_FLAG])

    def test_un_mkv_valide_ne_pose_pas_le_drapeau(self) -> None:
        self.assertEqual(self._flags_pour(_MAGIC_MKV + b"\x00" * 512), [])

    def test_une_extension_inconnue_ne_pose_pas_le_drapeau(self) -> None:
        """`skipped` rend deja `True` : le remede ne change rien ici."""
        self.assertEqual(self._flags_pour(b"n'importe quoi", nom="film.divx"), [])

    def test_le_drapeau_n_est_pas_duplique(self) -> None:
        """Comportement preexistant : la garde d'unicite reste en place."""
        with tempfile.TemporaryDirectory(prefix="cinesort_integrite_") as tmp:
            video = Path(tmp) / "film.mkv"
            video.write_bytes(b"PAS UN MKV" + b"\x11" * 512)
            row = _row()
            row.warning_flags.append(_FLAG)

            _apply_integrity_check(video, row)

        self.assertEqual(row.warning_flags, [_FLAG])


if __name__ == "__main__":
    unittest.main()
