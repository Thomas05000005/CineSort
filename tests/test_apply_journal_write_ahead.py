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

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.app import apply_core
from cinesort.app.apply_core import apply_single, migrate_legacy_collection_root
from cinesort.app.move_journal import RecordOpWithJournal, journal_pose_autour
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
        # `suppress`, pas un `except ... : pass` nu : un `store.close()` qui echoue
        # signifie, sous Windows, un fichier SQLite reste VERROUILLE — donc le
        # `rmtree` qui suit echouera en silence et le test laissera une base
        # derriere lui a chaque execution. On tolere l'echec, on ne le maquille pas.
        with contextlib.suppress(Exception):
            self.store.close()
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


class LiberationSurPreuveTests(unittest.TestCase):
    """`liberer_si_rien_n_a_bouge` doit lire le disque, pas supposer.

    Poser le journal a fait apparaitre un residu : `journaled_move` laisse
    l'entree en place sur exception — et il a raison pour un `shutil.move`, qui
    peut copier a moitie puis echouer. Un `rename` pur ne connait pas de
    demi-etat ; quand il echoue (cas NORMAL sous Windows : VLC ou l'indexeur
    tiennent un handle), le lot CONTINUE et l'entree survivrait a un run
    entierement reussi.

    Les deux sens comptent. Sans le second test, « liberer sur preuve » serait
    indistinguable de « toujours liberer », qui reintroduirait exactement le
    trou que T-PROD-8 vient de fermer.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_liberation_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite", busy_timeout_ms=5000)
        self.store.initialize()
        self.record_op = RecordOpWithJournal(lambda payload: None, store=self.store, batch_id="lot")

    def tearDown(self) -> None:
        # `suppress`, pas un `except ... : pass` nu : un `store.close()` qui echoue
        # signifie, sous Windows, un fichier SQLite reste VERROUILLE — donc le
        # `rmtree` qui suit echouera en silence et le test laissera une base
        # derriere lui a chaque execution. On tolere l'echec, on ne le maquille pas.
        with contextlib.suppress(Exception):
            self.store.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_echec_avec_source_intacte_libere_l_entree(self) -> None:
        src = self._tmp / "source"
        src.mkdir()
        dst = self._tmp / "cible"

        with self.assertRaises(PermissionError):
            with journal_pose_autour(
                self.record_op,
                src=src,
                dst=dst,
                op_type="MOVE_DIR",
                liberer_si_rien_n_a_bouge=True,
            ):
                raise PermissionError("WinError 5 : handle tenu par un tiers")

        self.assertEqual(
            self.store.apply.count_pending_moves(),
            0,
            "la source est intacte et la cible absente : le disque PROUVE que rien "
            "n'a bouge. Garder l'entree ferait trier un fantome a chaque fichier "
            "verrouille, et ils sont la norme sur une vraie bibliotheque.",
        )

    def test_echec_avec_cible_presente_GARDE_l_entree(self) -> None:
        src = self._tmp / "source"
        src.mkdir()
        dst = self._tmp / "cible"
        dst.mkdir()  # etat ambigu : quelque chose est a l'arrivee

        with self.assertRaises(PermissionError):
            with journal_pose_autour(
                self.record_op,
                src=src,
                dst=dst,
                op_type="MOVE_DIR",
                liberer_si_rien_n_a_bouge=True,
            ):
                raise PermissionError("echec apres un deplacement partiel")

        self.assertEqual(
            self.store.apply.count_pending_moves(),
            1,
            "le disque ne prouve RIEN ici : seule la reconciliation au prochain "
            "demarrage peut trancher. Liberer serait reintroduire le trou que "
            "T-PROD-8 vient de fermer.",
        )

    def test_la_liberation_ne_touche_QUE_sa_propre_entree(self) -> None:
        """Un echec d'aujourd'hui ne doit pas effacer la trace d'un crash d'hier.

        `list_pending_moves()` rend TOUS les orphelins, sans distinction d'age :
        une entree laissee par un run precedent qui a reellement plante y figure
        au meme titre que celle qu'on vient de poser. Liberer sans apparier
        src/dst detruirait la seule preuve qu'un deplacement est reste en
        suspens — et la reconciliation du prochain demarrage n'aurait plus rien
        a reconcilier.

        Ce test est ne d'un mutant SURVIVANT : retirer l'appariement laissait la
        batterie entierement verte, parce qu'aucun test n'avait jamais plus
        d'une entree en base.
        """
        veille = self.store.apply.insert_pending_move(
            op_type="MOVE_DIR",
            src_path=str(self._tmp / "run-precedent-source"),
            dst_path=str(self._tmp / "run-precedent-cible"),
            batch_id="lot-de-la-veille",
        )
        self.assertIsNotNone(veille, "le pending temoin n'a pas ete insere")

        src = self._tmp / "source"
        src.mkdir()
        dst = self._tmp / "cible"

        with self.assertRaises(PermissionError):
            with journal_pose_autour(
                self.record_op,
                src=src,
                dst=dst,
                op_type="MOVE_DIR",
                liberer_si_rien_n_a_bouge=True,
            ):
                raise PermissionError("WinError 5")

        restantes = self.store.apply.list_pending_moves()
        self.assertEqual(
            [e["src_path"] for e in restantes],
            [str(self._tmp / "run-precedent-source")],
            "la liberation a emporte une entree qui ne lui appartenait pas : "
            "c'est la trace d'un crash anterieur qui vient de disparaitre.",
        )

    def test_une_INTERRUPTION_laisse_l_entree_meme_si_rien_n_a_bouge(self) -> None:
        """Un KeyboardInterrupt, c'est l'application qui MEURT.

        C'est exactement l'instant ou le journal sert. Laisser l'entree est
        alors le comportement juste : la reconciliation du prochain demarrage
        tranchera, et elle a plus de chances d'aboutir que des ecritures faites
        pendant l'arret. D'ou `except Exception` et non `except BaseException`.
        """
        src = self._tmp / "source"
        src.mkdir()
        dst = self._tmp / "cible"

        with self.assertRaises(KeyboardInterrupt):
            with journal_pose_autour(
                self.record_op,
                src=src,
                dst=dst,
                op_type="MOVE_DIR",
                liberer_si_rien_n_a_bouge=True,
            ):
                raise KeyboardInterrupt

        self.assertEqual(
            self.store.apply.count_pending_moves(),
            1,
            "l'entree a ete liberee pendant un arret de l'application : c'est "
            "le seul moment ou elle avait une chance de servir.",
        )

    def test_une_cible_ILLISIBLE_n_est_pas_une_cible_absente(self) -> None:
        """« Absent » et « je n'ai pas pu lire » ne sont pas la meme reponse.

        `Path.exists()` ne re-leve PAS toutes les `OSError` : il en avale une
        liste, mesuree sur le Python de ce depot (3.13) —
        `_IGNORED_ERRNOS = ENOENT, ENOTDIR, EBADF, WSAELOOP` et
        `_IGNORED_WINERRORS = [21, 123, 1921]`. Le **21** est `ERROR_NOT_READY` :
        le peripherique n'est pas pret. C'est le mode d'echec d'un partage SMB
        tombe, c'est-a-dire l'environnement meme de ce produit.

        Source locale, destination sur un partage qui vient de tomber :
        `src.exists()` rend True, `dst.exists()` rend False SANS erreur, et la
        liberation conclut que rien n'a bouge alors qu'elle n'en sait rien.

        Signale par une revue automatique dont la cause citee (`EACCES`) est
        FAUSSE — une erreur d'acces fait bien remonter l'exception — mais dont le
        mecanisme etait juste. Verifier l'exemple, le trouver faux et classer le
        signal aurait laisse le trou en place.
        """
        src = self._tmp / "source"
        src.mkdir()
        dst = self._tmp / "cible"

        vrai_stat = Path.stat

        def stat_illisible(self_path, *a, **k):
            if self_path == dst:
                exc = OSError("peripherique non pret")
                exc.winerror = 21  # ERROR_NOT_READY, avale par Path.exists()
                raise exc
            return vrai_stat(self_path, *a, **k)

        with mock.patch.object(Path, "stat", stat_illisible):
            self.assertFalse(dst.exists(), "le temoin ne reproduit pas l'avalement")
            with self.assertRaises(PermissionError):
                with journal_pose_autour(
                    self.record_op,
                    src=src,
                    dst=dst,
                    op_type="MOVE_DIR",
                    liberer_si_rien_n_a_bouge=True,
                ):
                    raise PermissionError("echec du renommage")

        self.assertEqual(
            self.store.apply.count_pending_moves(),
            1,
            "la cible etait ILLISIBLE, pas absente : le disque ne prouve rien, "
            "et l'entree vient d'etre liberee sur une lecture qui a echoue.",
        )

    def test_sans_l_option_le_comportement_conservateur_est_inchange(self) -> None:
        src = self._tmp / "source"
        src.mkdir()
        dst = self._tmp / "cible"

        with self.assertRaises(PermissionError):
            with journal_pose_autour(self.record_op, src=src, dst=dst, op_type="MOVE_DIR"):
                raise PermissionError("echec")

        self.assertEqual(
            self.store.apply.count_pending_moves(),
            1,
            "l'option est opt-in : les appelants qui font un shutil.move gardent "
            "le contrat conservateur de journaled_move.",
        )


if __name__ == "__main__":
    unittest.main()
