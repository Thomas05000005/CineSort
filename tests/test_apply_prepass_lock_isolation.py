"""F10 — un verrou dans la pre-passe collection ne doit plus avorter tout l'apply.

Contexte du finding (revue post-merge 2026-07-18) : trois zones de `apply_rows`
deplacent des dossiers HORS du try per-row :
  - `migrate_legacy_collection_root`
  - la pre-passe collection (`merge_dir_safe` / `move_collection_folder`)
  - le nettoyage post-boucle (residuel + dossiers vides)

Aucune n'attrapait `PermissionError`. Sur Windows — le cas frequent d'un fichier
ouvert dans VLC ou indexe — l'exception remontait jusqu'au boundary de l'apply :
batch clos FAILED, log brut « [WinError 32] » au lieu du message « FICHIER
VERROUILLE » du handler per-row, resultat et resume perdus, et en mode atomique
le rollback annulait les rows deja appliquees avec succes.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.app import apply_core
from cinesort.app.apply_core import apply_rows


class _LogCollector:
    def __init__(self) -> None:
        self.entries: list = []

    def __call__(self, level: str, msg: str) -> None:
        self.entries.append((level, msg))

    def messages(self) -> str:
        return "\n".join(msg for _level, msg in self.entries)


def _single_row(row_id: str, folder: str, video: str = "film.mkv") -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="single",
        folder=folder,
        video=video,
        proposed_title="Film Seul",
        proposed_year=2020,
        proposed_source="name",
        confidence=90,
        confidence_label="high",
        candidates=[],
    )


def _collection_row(row_id: str, folder: str, video: str = "saga.mkv") -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="collection",
        folder=folder,
        video=video,
        proposed_title="Saga Film",
        proposed_year=1979,
        proposed_source="name",
        confidence=90,
        confidence_label="high",
        candidates=[],
    )


class ApplyPrepassLockIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_f10_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _fixture(self) -> tuple:
        saga = self.root / "Saga.Film.1979"
        saga.mkdir()
        (saga / "saga.mkv").write_bytes(b"\x00" * 64)
        seul = self.root / "Film.Seul.2020"
        seul.mkdir()
        (seul / "film.mkv").write_bytes(b"\x00" * 64)

        cfg = core.Config(root=self.root, enable_collection_folder=True).normalized()
        rows = [_collection_row("c1", str(saga)), _single_row("s1", str(seul))]
        decisions = {
            "c1": {"ok": True, "title": "Saga Film", "year": 1979},
            "s1": {"ok": True, "title": "Film Seul", "year": 2020},
        }
        return cfg, rows, decisions, saga, seul

    def test_verrou_en_prepasse_collection_n_avorte_pas_le_batch(self) -> None:
        cfg, rows, decisions, saga, _seul = self._fixture()
        log = _LogCollector()

        with mock.patch.object(
            apply_core,
            "move_collection_folder",
            side_effect=PermissionError(32, "The process cannot access the file"),
        ):
            res = apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=log,
                decision_presence={"c1", "s1"},
            )

        self.assertIsInstance(res, core.ApplyResult, "apply_rows ne doit plus laisser fuiter PermissionError")
        self.assertGreaterEqual(res.errors, 1, "le verrou doit etre compte comme une erreur")
        self.assertTrue(
            any("FICHIER VERROUILLE" in message for message in res.error_messages),
            f"message utilisateur attendu au lieu d'un WinError brut ; recu : {res.error_messages}",
        )
        self.assertGreaterEqual(
            res.renames + res.moves,
            1,
            "le film SANS verrou doit avoir ete traite : le batch ne doit pas etre avorte",
        )
        self.assertTrue(saga.exists(), "la row collection en echec doit rester en place (fail-closed)")

    def test_toutes_les_rows_du_dossier_en_echec_sont_protegees(self) -> None:
        """Un dossier collection porte PLUSIEURS rows : toutes doivent etre skippees.

        Defaut trouve en revue adversaire : le garde etait memorise par row_id,
        mais le `continue` sur `ctx.folder_map` s'execute avant le try. Les rows
        suivantes du meme dossier n'etaient donc jamais marquees et creaient un
        sous-dossier + deplacaient leur video A L'INTERIEUR du dossier dont la
        migration venait d'echouer.
        """
        anthologie = self.root / "Alien.Anthology"
        anthologie.mkdir()
        (anthologie / "Alien.mkv").write_bytes(b"\x00" * 64)
        (anthologie / "Aliens.mkv").write_bytes(b"\x00" * 64)

        cfg = core.Config(root=self.root, enable_collection_folder=True).normalized()
        rows = [
            _collection_row("c1", str(anthologie), "Alien.mkv"),
            _collection_row("c2", str(anthologie), "Aliens.mkv"),
        ]
        rows[1].proposed_title = "Aliens"
        rows[1].proposed_year = 1986
        decisions = {
            "c1": {"ok": True, "title": "Alien", "year": 1979},
            "c2": {"ok": True, "title": "Aliens", "year": 1986},
        }
        log = _LogCollector()

        with mock.patch.object(
            apply_core,
            "move_collection_folder",
            side_effect=PermissionError(32, "locked"),
        ):
            res = apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=log,
                decision_presence={"c1", "c2"},
            )

        self.assertEqual(
            res.moves,
            0,
            "aucune video ne doit bouger dans un dossier dont la migration vient d'echouer",
        )
        self.assertEqual(res.mkdirs, 0, "aucun sous-dossier ne doit etre cree dans ce dossier")
        sous_dossiers = [p.name for p in anthologie.iterdir() if p.is_dir()]
        self.assertEqual(sous_dossiers, [], f"sous-dossiers crees a tort : {sous_dossiers}")
        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_ERREUR_PRECEDENTE),
            2,
            "les DEUX rows du dossier doivent etre skippees, pas seulement la premiere",
        )

    def test_verrou_au_nettoyage_residuel_preserve_le_resultat(self) -> None:
        cfg, rows, decisions, _saga, _seul = self._fixture()
        cfg = core.Config(
            root=self.root, enable_collection_folder=True, cleanup_residual_folders_enabled=True
        ).normalized()
        log = _LogCollector()

        with mock.patch.object(
            apply_core,
            "_move_residual_top_level_dirs",
            side_effect=PermissionError(32, "locked"),
        ):
            res = apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=log,
                decision_presence={"c1", "s1"},
            )

        self.assertIsInstance(res, core.ApplyResult, "le resultat de l'apply ne doit pas etre perdu")
        self.assertGreaterEqual(res.errors, 1)
        self.assertIsInstance(
            res.cleanup_residual_diagnostic,
            dict,
            "le diagnostic residuel doit rester produit malgre l'echec du nettoyage",
        )

    def test_apply_nominal_sans_verrou_inchange(self) -> None:
        """NON-REGRESSION : sans verrou, aucune erreur et le batch s'applique."""
        cfg, rows, decisions, _saga, _seul = self._fixture()
        log = _LogCollector()

        res = apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=log,
            decision_presence={"c1", "s1"},
        )

        self.assertEqual(res.errors, 0, f"apply nominal ne doit produire aucune erreur : {res.error_messages}")
        self.assertGreaterEqual(res.renames + res.moves + res.collection_moves, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
