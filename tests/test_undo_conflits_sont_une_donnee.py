"""Ou est parti mon film ? La reponse ne doit pas vivre dans une chaine de log.

Quand l'undo ne peut pas remettre un film a sa place — sa destination d'origine
est occupee — il le deplace vers `<run_dir>/_review/_undo_conflicts/`. Jusqu'ici,
la SEULE trace de cette nouvelle place etait le texte de `error_message` :

    "Conflit cible existante, deplace vers C:/.../_undo_conflicts/Film"

Aucune surface ne pouvait donc lister ces fichiers, et l'utilisateur qui lit
« Undo terminé avec anomalies » n'a aucun moyen de savoir quels films ont bouge
ni ou. Sur le filet de secours, c'est le pire endroit pour une donnee prisonniere
d'un message.

CE QUE CES TESTS NE COUVRENT PAS : rendre l'operation re-tentable. L'op de
conflit est marquee FAILED, et FAILED est terminal pour les TROIS chemins de
reprise (`undo_selected_rows` ne prend que PENDING, `build_undo_by_row_preview`
ne compte que PENDING, `apply_rollback._revert_one_op` saute FAILED). Ce volet-la
demande sa propre conception mesuree.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from cinesort.ui.api import apply_support


class _StoreMuet:
    def __init__(self) -> None:
        self.apply = self

    # Le nom exact compte : `_require_undo_status_api` est un garde fail-closed
    # qui refuse de deplacer le moindre fichier si cette methode manque.
    def mark_apply_operation_undo_status(self, **_k: Any) -> None:
        return None

    def insert_pending_move(self, **_k: Any) -> int:
        return 1

    def delete_pending_move(self, *_a: Any, **_k: Any) -> None:
        return None

    def list_apply_operations(self, **_k: Any) -> list:
        return []


class ConflitsExposesTests(unittest.TestCase):
    def _undo_avec_conflit(self) -> Dict[str, Any]:
        """Un vrai conflit : la destination de restauration existe deja.

        Le film est a `dst`, l'undo veut le remettre a `src` — mais `src` est
        occupe par un autre dossier. Le chemin de quarantaine se declenche.
        """
        tmp = Path(tempfile.mkdtemp(prefix="cs_conflit_"))
        try:
            root = tmp / "root"
            src = root / "Origine"
            dst = root / "Titre (1980)"
            for d in (src, dst):
                d.mkdir(parents=True)
                (d / "film.mkv").write_bytes(b"x" * 32)

            run_dir = tmp / "run"
            (run_dir / "_review").mkdir(parents=True)

            ops: List[Dict[str, Any]] = [
                {
                    "id": 1,
                    "batch_id": "b1",
                    "op_index": 1,
                    "op_type": "MOVE_DIR",
                    "src_path": str(src),
                    "dst_path": str(dst),
                    "reversible": 1,
                    "undo_status": "PENDING",
                    "row_id": "r1",
                    "src_sha1": None,
                    "src_size": None,
                    "ts": 0.0,
                }
            ]
            return apply_support._execute_undo_ops(
                SimpleNamespace(),
                ops,
                _StoreMuet(),
                lambda *_a: None,
                SimpleNamespace(run_dir=run_dir),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_le_conflit_est_bien_declenche(self) -> None:
        """Sans ca, tout le reste du fichier ne prouverait rien."""
        out = self._undo_avec_conflit()

        self.assertEqual(out["conflict_moves"], 1, f"le chemin de conflit n'a pas ete pris : {out}")

    def test_la_destination_du_film_est_une_DONNEE(self) -> None:
        out = self._undo_avec_conflit()

        details = out.get("conflicts_details") or []
        self.assertEqual(len(details), 1, f"aucun detail de conflit expose : {out}")
        entree = details[0]
        self.assertTrue(entree["dst_path"], "la nouvelle place du film n'est pas dite")
        self.assertIn("_undo_conflicts", entree["dst_path"])

    def test_on_sait_QUEL_film_et_QUI_bloquait(self) -> None:
        """Une liste de chemins sans row_id ni cause n'est pas exploitable."""
        entree = (self._undo_avec_conflit().get("conflicts_details") or [{}])[0]

        self.assertEqual(entree.get("row_id"), "r1")
        self.assertTrue(entree.get("src_path"))
        self.assertIn("Origine", str(entree.get("blocked_by") or ""))

    def test_le_fichier_est_REELLEMENT_a_l_endroit_annonce(self) -> None:
        """Une donnee juste mais fausse serait pire qu'un message : on verifie
        que le chemin annonce existe vraiment sur le disque."""
        tmp = Path(tempfile.mkdtemp(prefix="cs_conflit_reel_"))
        try:
            root = tmp / "root"
            src = root / "Origine"
            dst = root / "Titre (1980)"
            for d in (src, dst):
                d.mkdir(parents=True)
                (d / "film.mkv").write_bytes(b"x" * 32)
            run_dir = tmp / "run"
            (run_dir / "_review").mkdir(parents=True)

            out = apply_support._execute_undo_ops(
                SimpleNamespace(),
                [
                    {
                        "id": 1,
                        "batch_id": "b1",
                        "op_index": 1,
                        "op_type": "MOVE_DIR",
                        "src_path": str(src),
                        "dst_path": str(dst),
                        "reversible": 1,
                        "undo_status": "PENDING",
                        "row_id": "r1",
                        "src_sha1": None,
                        "src_size": None,
                        "ts": 0.0,
                    }
                ],
                _StoreMuet(),
                lambda *_a: None,
                SimpleNamespace(run_dir=run_dir),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,
            )
            annonce = Path((out["conflicts_details"] or [{}])[0]["dst_path"])
            self.assertTrue(annonce.exists(), f"le chemin annonce n'existe pas : {annonce}")
            self.assertTrue((annonce / "film.mkv").exists(), "le film n'est pas dans le dossier annonce")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_un_undo_SANS_conflit_ne_fabrique_rien(self) -> None:
        """Contre-epreuve : la liste doit rester vide sur le chemin nominal."""
        tmp = Path(tempfile.mkdtemp(prefix="cs_sans_conflit_"))
        try:
            root = tmp / "root"
            dst = root / "Titre (1980)"
            dst.mkdir(parents=True)
            (dst / "film.mkv").write_bytes(b"x" * 32)
            run_dir = tmp / "run"
            (run_dir / "_review").mkdir(parents=True)

            out = apply_support._execute_undo_ops(
                SimpleNamespace(),
                [
                    {
                        "id": 1,
                        "batch_id": "b1",
                        "op_index": 1,
                        "op_type": "MOVE_DIR",
                        "src_path": str(root / "Origine"),
                        "dst_path": str(dst),
                        "reversible": 1,
                        "undo_status": "PENDING",
                        "row_id": "r1",
                        "src_sha1": None,
                        "src_size": None,
                        "ts": 0.0,
                    }
                ],
                _StoreMuet(),
                lambda *_a: None,
                SimpleNamespace(run_dir=run_dir),
                empty_bucket=None,
                residual_bucket=None,
                atomic=False,
            )

            self.assertEqual(out["done"], 1)
            self.assertEqual(out.get("conflicts_details"), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
