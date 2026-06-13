r"""GATE AUDIT 2026-06-13 (R5-P2) — build_apply_preview classe un film à la
racine comme un DÉPLACEMENT, pas un renommage de la racine.

Contexte (analyse captures + run réel 20260612_234833) : 111 films posés
DIRECTEMENT à la racine \\OMV\Media\downloads. L'aperçu de l'Étape 5 affichait
côté CLIENT "Dossier renommé : <racine> -> <titre>" + "945 renommages /
0 déplacement" — un mensonge alarmant. Le backend, lui, range correctement
chaque film dans un sous-dossier "Titre (Année)/" (cf summary.txt du run +
plan_support_core.py:674 qui force la logique collection à la racine).

Le fix R5-P2 fait consommer à l'Étape 5 le VRAI plan backend
(run/build_apply_preview : totals + films[].ops via _formatPreviewEntry). Ce
GATE verrouille le contrat de données dont dépend désormais l'UI :
  1. un film à la racine produit une op de DÉPLACEMENT (move), pas folder_rename ;
  2. totals.moves >= 1 (donc l'UI n'affiche plus "0 déplacement") ;
  3. AUCUNE op ne renomme/déplace le dossier RACINE lui-même (sûreté données).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done


class ApplyPreviewRootFilmTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_preview_root_")
        self.root = Path(self._tmp) / "downloads"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plan_root_film(self):
        # Film posé DIRECTEMENT à la racine (pas de sous-dossier).
        (self.root / "Inception 2010.mkv").write_bytes(b"x" * 4096)
        api = CineSortApi()
        start = api.run.start_plan(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)
        rows = api.run.get_plan(run_id).get("rows", [])
        self.assertTrue(rows, "le scan doit produire au moins 1 row pour le film à la racine")
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")}
            for r in rows
        }
        return api, run_id, rows, decisions

    def test_root_film_is_a_move_not_root_rename(self) -> None:
        api, run_id, rows, decisions = self._plan_root_film()
        preview = api.run.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"), preview)
        totals = preview.get("totals") or {}
        films = preview.get("films") or []

        # (1) le film à la racine est classé "déplacement", PAS "renommage de dossier".
        movey = [f for f in films if f.get("change_type") in ("move_files", "move_mixed")]
        self.assertTrue(
            movey,
            f"un film à la racine doit être un déplacement (move_files/move_mixed), "
            f"change_types={[f.get('change_type') for f in films]}",
        )

        # (2) au moins une op est un MOVE de fichier avec action de déplacement,
        #     jamais un simple folder_rename de la racine.
        move_ops = []
        for f in films:
            for op in (f.get("ops") or []):
                move_ops.append(op)
        self.assertTrue(
            any(op.get("action_summary") in ("video_move", "folder_rename_and_video_move") for op in move_ops),
            f"au moins une op doit déplacer le fichier dans le nouveau dossier ; "
            f"actions={[op.get('action_summary') for op in move_ops]}",
        )
        self.assertGreaterEqual(
            int(totals.get("moves") or 0), 1,
            f"totals.moves doit compter le déplacement (UI ne doit plus afficher 0 déplacement) : {totals}",
        )

    def test_root_folder_itself_is_never_renamed(self) -> None:
        # SÛRETÉ : aucune op ne doit renommer/déplacer le dossier RACINE lui-même.
        api, run_id, rows, decisions = self._plan_root_film()
        preview = api.run.build_apply_preview(run_id, decisions)
        root_resolved = str(self.root.resolve())
        for f in preview.get("films") or []:
            for op in (f.get("ops") or []):
                src = str(op.get("src_path") or "")
                if not src:
                    continue
                try:
                    src_resolved = str(Path(src).resolve())
                except (OSError, ValueError):
                    src_resolved = src
                self.assertNotEqual(
                    src_resolved, root_resolved,
                    f"op qui renomme/déplace la RACINE elle-même : {op!r} (catastrophe données)",
                )

    def test_destination_is_a_subfolder_of_root(self) -> None:
        # Le fichier doit aller dans un sous-dossier "Inception (2010)/" SOUS la racine.
        api, run_id, rows, decisions = self._plan_root_film()
        preview = api.run.build_apply_preview(run_id, decisions)
        dsts = []
        for f in preview.get("films") or []:
            for op in (f.get("ops") or []):
                if op.get("dst_path"):
                    dsts.append(str(op["dst_path"]))
        self.assertTrue(dsts, "au moins une op avec destination attendue")
        root_resolved = self.root.resolve()
        self.assertTrue(
            any(root_resolved in Path(d).resolve().parents for d in dsts),
            f"la destination doit être SOUS la racine (sous-dossier créé) : {dsts}",
        )


if __name__ == "__main__":
    unittest.main()
