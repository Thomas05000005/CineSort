"""T-PROD-8 : deux deplacements de DOSSIER ne posaient pas le journal write-ahead.

`apply_single` (le chemin le plus frequent du produit) et
`migrate_legacy_collection_root` renommaient puis appelaient `record_apply_op`.
Entre les deux, rien ne tracait l'operation : si l'application meurt dans cette
fenetre, les octets ont bouge et aucune ligne ne le dit. Le dossier est
introuvable a l'ancien emplacement, inconnu du nouveau, et
`reconcile_pending_moves()` n'a rien a reconcilier au prochain demarrage.

C'est exactement ce que la docstring d'`atomic_move` decrit, mot pour mot :

    Le journal write-ahead reste pose dans les deux cas : c'est lui qui rend le
    deplacement reconciliable si l'app meurt entre le deplacement et le
    `record_apply_op` du call site.

Ce n'est PAS une regression : la ligne etait deja un `rename` nu avant la
PR #969, qui n'a fait qu'y ajouter la reprise.

Le remede n'est PAS de remplacer les appels par `atomic_move` : les deux sites
appellent `renommer_avec_reprise` et `_case_only_rename_with_rollback`, qui
portent des comportements propres (reprise sur course Windows, renommage a
casse seule). Les remplacer ETEINDRAIT ces gardes. Le journal s'enroule donc
AUTOUR du deplacement existant, via le gestionnaire de contexte deja present.

Les deux tests observent le journal PENDANT le deplacement, seul instant ou la
difference est visible : avant, il n'existe pas encore ; apres, il est deja
relache. Chacun verifie AUSSI qu'il ne reste rien en fin de course — un journal
pose mais jamais relache ferait voir un fantome a chaque demarrage, ce qui
serait un second defaut a la place du premier.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.app import apply_core
from cinesort.app.apply_core import apply_single, migrate_legacy_collection_root
from cinesort.app.move_journal import RecordOpWithJournal
from cinesort.infra.db.sqlite_store import SQLiteStore


def _config(root: Path, *, collection: bool = False) -> "core.Config":
    """La VRAIE Config, pas une doublure.

    Une doublure minimale echoue ici sur `video_exts` avant meme d'atteindre le
    deplacement : le test serait rouge sans le correctif ET avec lui — un rouge
    qui ne prouve rien. Le seul producteur fiable de la forme attendue est la
    classe elle-meme.
    """
    # `Config` est un dataclass FROZEN : les champs se passent au constructeur,
    # ils ne s'affectent pas apres coup. C'est voulu — une config qui derive en
    # cours d'apply produirait deux moities de plan incoherentes.
    return core.Config(
        root=root,
        enable_collection_folder=collection,
        collection_root_name="_Collection",
    ).normalized()


class ApplyJournalWriteAheadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_wal_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite", busy_timeout_ms=5000)
        self.store.initialize()
        self.root = self._tmp / "root"
        self.root.mkdir()
        self.review = self.root / "_review"
        self.roots = {
            "conflicts_root": self.review / "_conflicts",
            "conflicts_sidecars_root": self.review / "_conflicts_sidecars",
            "duplicates_identical_root": self.review / "_duplicates_identical",
            "leftovers_root": self.review / "_leftovers",
        }

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _record_op(self) -> RecordOpWithJournal:
        return RecordOpWithJournal(lambda payload: None, store=self.store, batch_id="lot-test")

    def test_apply_single_pose_le_journal_pendant_le_deplacement(self) -> None:
        folder = self.root / "un film 2019"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        vus: list[list] = []

        def espion(source: Path, cible: Path) -> None:
            # Instant unique ou la difference est observable.
            vus.append(self.store.apply.list_pending_moves())
            source.rename(cible)

        logs: list[tuple[str, str]] = []
        with mock.patch.object(apply_core, "renommer_avec_reprise", espion):
            apply_single(
                _config(self.root),
                folder,
                title="Un Film",
                year=2019,
                dry_run=False,
                log=lambda niveau, msg: logs.append((niveau, msg)),
                res=core.ApplyResult(),
                record_op=self._record_op(),
                **self.roots,
            )

        self.assertEqual(len(vus), 1, f"le deplacement n'a pas eu lieu : logs={logs}")
        self.assertEqual(
            len(vus[0]),
            1,
            "aucune entree pending PENDANT le deplacement : si l'app meurt ici, "
            "les octets ont bouge et rien ne le dit. reconcile_pending_moves() "
            "n'aura rien a reconcilier au prochain demarrage.",
        )
        self.assertEqual(vus[0][0]["op_type"], "MOVE_DIR")
        self.assertEqual(
            self.store.apply.count_pending_moves(),
            0,
            "le journal a ete pose mais jamais relache : chaque demarrage verrait "
            "un fantome, ce qui remplace le defaut par un autre.",
        )

    def test_migration_collection_pose_le_journal_pendant_le_deplacement(self) -> None:
        cfg = _config(self.root, collection=True)
        legacy = apply_core.legacy_collection_root(cfg)
        legacy.mkdir(parents=True)
        (legacy / "saga").mkdir()

        cible = self.root / cfg.collection_root_name
        self.assertFalse(cible.exists(), "le test doit emprunter la branche rename, pas le merge")

        vus: list[list] = []
        vrai_rename = Path.rename

        def espion(self_path: Path, cible_path):  # noqa: ANN001 — signature de Path.rename
            vus.append(self.store.apply.list_pending_moves())
            return vrai_rename(self_path, cible_path)

        with mock.patch.object(Path, "rename", espion):
            migrate_legacy_collection_root(
                cfg,
                dry_run=False,
                log=lambda niveau, msg: None,
                res=core.ApplyResult(),
                record_op=self._record_op(),
                **self.roots,
            )

        self.assertEqual(len(vus), 1, "la migration n'a pas renomme")
        self.assertEqual(
            len(vus[0]),
            1,
            "aucune entree pending PENDANT la migration de la racine de collection",
        )
        self.assertEqual(self.store.apply.count_pending_moves(), 0, "journal jamais relache")


if __name__ == "__main__":
    unittest.main()
