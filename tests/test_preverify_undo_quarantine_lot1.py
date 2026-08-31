"""LOT 1 / B — la pre-verification P1.2 etait AVEUGLE aux `UNDO_QUARANTINE`.

`_journaliser_quarantaine_undo` (`apply_support.py`) inscrit l'operation
`UNDO_QUARANTINE` AVEC `src_sha1` et `src_size`, et son commentaire dit
exactement pourquoi : sans eux, la pre-verification de l'undo ne peut pas
detecter qu'un utilisateur a remplace le fichier DANS le bac `_undo_conflicts`
entre la quarantaine et la reprise — elle le restaurerait en croyant que c'est
le sien.

Or `_resolve_hashed_target` ne connaissait que `MOVE_FILE` et `MOVE_DIR` et
rendait `None` pour tout autre `op_type`. L'operation partait donc en
« missing », categorie que `_execute_undo_ops` n'abandonne PAS (seul
`hash_mismatch` declenche l'abandon atomique) : l'empreinte journalisee n'etait
jamais comparee a quoi que ce soit. Le garde etait ECRIT et MORT.

Le contre-test `..._intact_est_sur` verifie que le correctif ne se contente pas
de tout classer en mismatch.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.app.apply_core import sha1_quick
from cinesort.ui.api.apply_support import preverify_undo_operations
from tests._helpers import cleanup_test_tree


class PreverifyUndoQuarantineTests(unittest.TestCase):
    """Une op `UNDO_QUARANTINE` doit etre verifiee comme n'importe quel fichier."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_quarantine_")
        self.base = Path(self._tmp)
        self.bac = self.base / "_review" / "_undo_conflicts"
        self.bac.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _op_quarantaine(self, dst: Path, *, sha1: str, taille: int) -> dict:
        """Reproduit la ligne de journal ecrite par `_journaliser_quarantaine_undo`."""
        return {
            "id": 1,
            "op_type": "UNDO_QUARANTINE",
            "src_path": str(self.base / "Bibliotheque" / dst.name),
            "dst_path": str(dst),
            "reversible": 1,
            "undo_status": "PENDING",
            "src_sha1": sha1,
            "src_size": taille,
        }

    def test_undo_quarantine_remplace_est_un_hash_mismatch(self) -> None:
        """Le fichier du bac a ete remplace par un autre de MEME taille."""
        dans_le_bac = self.bac / "Film (2019).mkv"
        dans_le_bac.write_bytes(b"le film original du bac".ljust(4096, b"\x00"))
        empreinte = sha1_quick(dans_le_bac)
        taille = dans_le_bac.stat().st_size

        # L'utilisateur substitue un AUTRE fichier, de meme taille.
        dans_le_bac.write_bytes(b"un tout autre contenu pose par l'utilisateur".ljust(4096, b"\x00"))
        self.assertEqual(dans_le_bac.stat().st_size, taille, "la taille doit rester identique")

        rapport = preverify_undo_operations([self._op_quarantaine(dans_le_bac, sha1=empreinte, taille=taille)])

        self.assertEqual(len(rapport["hash_mismatch"]), 1, f"attendu 1 mismatch, rapport={rapport}")
        self.assertEqual(len(rapport["missing"]), 0)
        self.assertEqual(len(rapport["safe"]), 0)
        self.assertIn("empreinte", rapport["hash_mismatch"][0]["preverify_reason"])

    def test_undo_quarantine_de_taille_differente_est_un_hash_mismatch(self) -> None:
        dans_le_bac = self.bac / "Autre Film (2020).mkv"
        dans_le_bac.write_bytes(b"contenu remplace, plus court")

        rapport = preverify_undo_operations([self._op_quarantaine(dans_le_bac, sha1="0" * 40, taille=999_999)])

        self.assertEqual(len(rapport["hash_mismatch"]), 1, f"attendu 1 mismatch, rapport={rapport}")
        self.assertIn("taille", rapport["hash_mismatch"][0]["preverify_reason"])

    def test_undo_quarantine_intact_est_sur(self) -> None:
        """CONTRE-TEST : un bac non touche doit rester annulable."""
        dans_le_bac = self.bac / "Film Intact (2021).mkv"
        dans_le_bac.write_bytes(b"contenu jamais touche".ljust(2048, b"\x00"))
        empreinte = sha1_quick(dans_le_bac)
        taille = dans_le_bac.stat().st_size

        rapport = preverify_undo_operations([self._op_quarantaine(dans_le_bac, sha1=empreinte, taille=taille)])

        self.assertEqual(len(rapport["safe"]), 1, f"attendu 1 safe, rapport={rapport}")
        self.assertEqual(len(rapport["hash_mismatch"]), 0)
        self.assertEqual(len(rapport["missing"]), 0)

    def test_undo_quarantine_disparu_reste_missing(self) -> None:
        """CONTRE-TEST : un bac vide reste bien « destination absente »."""
        absent = self.bac / "Disparu (2022).mkv"

        rapport = preverify_undo_operations([self._op_quarantaine(absent, sha1="a" * 40, taille=10)])

        self.assertEqual(len(rapport["missing"]), 1, f"attendu 1 missing, rapport={rapport}")
        self.assertEqual(len(rapport["hash_mismatch"]), 0)


if __name__ == "__main__":
    unittest.main()
