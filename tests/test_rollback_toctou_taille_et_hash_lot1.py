"""LOT 1 / A — la garde anti-TOCTOU du rollback concluait « meme fichier » sur
le SEUL `sha1_quick`, puis effacait definitivement le fichier de l'utilisateur.

`sha1_quick` (`apply_core.py`) ne hache que les 8 PREMIERS et les 8 DERNIERS Mo
d'un fichier. Deux fichiers de TAILLES DIFFERENTES qui partagent leur tete et
leur queue rendent donc le MEME digest — c'est la premisse de ce module, et le
test `test_deux_tailles_differentes_rendent_le_meme_sha1_quick` la MESURE au
lieu de la supposer.

`src_size` est pourtant journalise a cote de `src_sha1`
(`infra/db/repositories/apply.py::list_apply_operations`) et `apply_rollback`
ne le lisait nulle part. Les deux verdicts « c'est le meme fichier » du module
menaient chacun a une destruction definitive :

  - le fichier apparu a `src` pendant la course est renomme en `.rollback_bak`
    puis `unlink()` apres le move ;
  - un `.rollback_bak` orphelin est `unlink()` directement.

Le correctif exige l'egalite TAILLE **et** hash, et REFUSE d'ecraser quand
`src_size` est absent du journal (lignes anterieures a la migration 013) : sens
restrictif sur un chemin destructif.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app.apply_core import sha1_quick
from cinesort.app.apply_rollback import _revert_one_op
from tests._helpers import cleanup_test_tree

MO = 1024 * 1024
# Les deux tailles doivent depasser 16 Mo, sinon `sha1_quick` hache le fichier
# ENTIER et la collision n'existe pas.
TAILLE_ORIGINE = 20 * MO
TAILLE_USER = 24 * MO


def _fabriquer(chemin: Path, taille: int) -> None:
    """Ecrit un fichier de `taille` octets avec une tete et une queue COMMUNES.

    Le milieu est laisse a zero : deux fichiers fabriques ainsi ne different
    que par leur taille, et leurs 8 Mo de tete comme leurs 8 Mo de queue sont
    identiques octet pour octet.
    """
    with chemin.open("wb") as fh:
        fh.write(b"TETE-COMMUNE-16")
        fh.truncate(taille)
        fh.seek(taille - 16)
        fh.write(b"QUEUE-COMMUNE-16")


class RollbackTocTouTailleEtHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_rb_toctou_")
        self.base = Path(self._tmp)
        self.dossier_src = self.base / "Bibliotheque"
        self.dossier_dst = self.base / "Triee"
        self.dossier_src.mkdir(parents=True, exist_ok=True)
        self.dossier_dst.mkdir(parents=True, exist_ok=True)
        self.src = self.dossier_src / "Film (2019).mkv"
        self.dst = self.dossier_dst / "Film (2019).mkv"

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _op(self, *, sha1: str, taille: int | None) -> dict:
        op: dict = {
            "id": 7,
            "op_index": 1,
            "op_type": "MOVE_FILE",
            "src_path": str(self.src),
            "dst_path": str(self.dst),
            "reversible": 1,
            "undo_status": "PENDING",
            "src_sha1": sha1,
        }
        if taille is not None:
            op["src_size"] = taille
        return op

    def _revert_avec_course(self, op: dict, fabriquer_pendant_la_course) -> dict:
        """Fait apparaitre un fichier a `src` DANS la fenetre TOCTOU du module.

        La fenetre est exactement entre le `src.exists()` initial et le
        `src.exists()` qui suit `src.parent.mkdir(...)`. On se greffe donc sur
        ce `mkdir`, seul appel qui les separe.
        """
        vrai_mkdir = Path.mkdir
        deja_joue: list[bool] = []

        def mkdir_avec_course(self_path: Path, *args, **kwargs):
            resultat = vrai_mkdir(self_path, *args, **kwargs)
            if not deja_joue:
                deja_joue.append(True)
                fabriquer_pendant_la_course()
            return resultat

        with mock.patch.object(Path, "mkdir", mkdir_avec_course):
            resultat = _revert_one_op(op)
        self.assertTrue(deja_joue, "la course n'a pas ete injectee : test invalide")
        return resultat

    def test_deux_tailles_differentes_rendent_le_meme_sha1_quick(self) -> None:
        """PREMISSE MESUREE : la collision existe bel et bien."""
        petit = self.dossier_dst / "petit.mkv"
        grand = self.dossier_dst / "grand.mkv"
        _fabriquer(petit, TAILLE_ORIGINE)
        _fabriquer(grand, TAILLE_USER)

        self.assertNotEqual(petit.stat().st_size, grand.stat().st_size)
        self.assertEqual(
            sha1_quick(petit),
            sha1_quick(grand),
            "sans collision, les tests de ce module ne prouvent rien",
        )

    def test_un_fichier_user_de_taille_differente_nest_pas_efface(self) -> None:
        """Le coeur du defaut : meme tete, meme queue, taille differente."""
        _fabriquer(self.dst, TAILLE_ORIGINE)
        op = self._op(sha1=sha1_quick(self.dst), taille=TAILLE_ORIGINE)

        resultat = self._revert_avec_course(op, lambda: _fabriquer(self.src, TAILLE_USER))

        self.assertEqual(resultat["status"], "SKIPPED", f"resultat={resultat}")
        self.assertEqual(resultat["reason"], "src_appeared_during_rollback")
        self.assertTrue(self.src.exists(), "le fichier de l'utilisateur a ete EFFACE")
        self.assertEqual(
            self.src.stat().st_size,
            TAILLE_USER,
            "le fichier de l'utilisateur a ete remplace par la destination du rollback",
        )
        self.assertTrue(self.dst.exists(), "rien ne devait bouger")

    def test_un_backup_orphelin_de_taille_differente_nest_pas_efface(self) -> None:
        """Le second `unlink` : un `.rollback_bak` qui n'est pas le notre."""
        _fabriquer(self.dst, TAILLE_ORIGINE)
        orphelin = self.src.with_suffix(self.src.suffix + ".rollback_bak")
        _fabriquer(orphelin, TAILLE_USER)
        op = self._op(sha1=sha1_quick(self.dst), taille=TAILLE_ORIGINE)

        # Le fichier qui apparait a `src` est, lui, REELLEMENT identique : la
        # garde de `src` passe legitimement, et c'est bien l'orphelin qui est
        # en jeu.
        resultat = self._revert_avec_course(op, lambda: _fabriquer(self.src, TAILLE_ORIGINE))

        self.assertEqual(resultat["status"], "SKIPPED", f"resultat={resultat}")
        self.assertEqual(resultat["reason"], "orphan_backup_present")
        self.assertTrue(orphelin.exists(), "le backup orphelin a ete EFFACE")
        self.assertEqual(orphelin.stat().st_size, TAILLE_USER)

    def test_une_ligne_de_journal_sans_src_size_refuse_decraser(self) -> None:
        """Lignes anterieures a la migration 013 : sens RESTRICTIF."""
        _fabriquer(self.dst, TAILLE_ORIGINE)
        op = self._op(sha1=sha1_quick(self.dst), taille=None)
        self.assertNotIn("src_size", op)

        resultat = self._revert_avec_course(op, lambda: _fabriquer(self.src, TAILLE_ORIGINE))

        self.assertEqual(resultat["status"], "SKIPPED", f"resultat={resultat}")
        self.assertEqual(resultat["reason"], "src_appeared_during_rollback")
        self.assertTrue(self.dst.exists(), "rien ne devait bouger sans taille de reference")

    def test_un_fichier_reellement_identique_est_toujours_ecrase(self) -> None:
        """CONTRE-TEST : le correctif ne doit pas refuser TOUT ecrasement."""
        _fabriquer(self.dst, TAILLE_ORIGINE)
        op = self._op(sha1=sha1_quick(self.dst), taille=TAILLE_ORIGINE)

        resultat = self._revert_avec_course(op, lambda: _fabriquer(self.src, TAILLE_ORIGINE))

        self.assertEqual(resultat["status"], "DONE", f"resultat={resultat}")
        self.assertTrue(self.src.exists())
        self.assertEqual(self.src.stat().st_size, TAILLE_ORIGINE)
        self.assertFalse(self.dst.exists(), "la destination doit avoir ete rendue a la source")
        self.assertFalse(
            self.src.with_suffix(self.src.suffix + ".rollback_bak").exists(),
            "le backup temporaire doit avoir ete nettoye",
        )


if __name__ == "__main__":
    unittest.main()
