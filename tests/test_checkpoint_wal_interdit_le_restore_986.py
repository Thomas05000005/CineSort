"""Un verdict d'integrite non fiable ne doit pas autoriser d'ecraser la base.

LE DEFAUT (#986). `_check_integrity` force un `PRAGMA wal_checkpoint(RESTART)`
avant `PRAGMA integrity_check`, precisement parce que — le commentaire du code
le dit — sans checkpoint « des pages encore dans le WAL pouvaient masquer une
corruption (OU EN SIGNALER UNE FANTOME) ».

Quand ce checkpoint ECHOUE, le code se contentait d'un WARNING et poursuivait.
Le verdict, de son propre aveu non fiable, redescendait ensuite dans
`initialize()` ou il etait traite comme assez autoritaire pour appeler
`_attempt_auto_restore()` — c'est-a-dire un `os.replace` SUR LA BASE VIVANTE.

Or un checkpoint echoue precisement quand un AUTRE lecteur/ecrivain tient la
base. Les commits de cet autre ecrivain disparaissaient, sur la foi d'un
diagnostic qui pouvait etre une corruption fantome.

LE PATRON EXISTAIT DEJA VINGT LIGNES PLUS HAUT. La nuance N23 a tranche la meme
forme : « je n'ai pas pu OUVRIR le fichier » ne dit rien du CONTENU, donc pose
`_integrity_unreadable`, que `initialize()` lit pour NE PAS restaurer. Un
checkpoint en echec est le meme cas, avec une autre cause.

LE SENS RESTRICTIF. La restauration est DESTRUCTIVE. Sur un chemin destructif, le
doute doit aller vers le refus : ne pas restaurer une base saine mais mal
diagnostiquee est recuperable ; ecraser les commits d'un autre ecrivain ne l'est
pas.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.db.sqlite_store import SQLiteStore


class _EchecDeCheckpoint:
    """Connexion qui fait echouer le seul `wal_checkpoint`, rien d'autre.

    On enveloppe une VRAIE connexion : `integrity_check` doit continuer de
    repondre, sinon on mesurerait « la base ne s'ouvre pas » (le cas N23) et non
    « le checkpoint a echoue ».
    """

    def __init__(self, vraie: sqlite3.Connection, verdict: str) -> None:
        self._vraie = vraie
        self._verdict = verdict
        self.checkpoints_tentes = 0

    def execute(self, sql: str, *a, **kw):
        if "wal_checkpoint" in sql:
            self.checkpoints_tentes += 1
            raise sqlite3.OperationalError("database is locked")
        if "integrity_check" in sql:
            return _Curseur([(self._verdict,)])
        return self._vraie.execute(sql, *a, **kw)

    def close(self) -> None:
        self._vraie.close()

    def __getattr__(self, nom):
        return getattr(self._vraie, nom)


class _Curseur:
    def __init__(self, lignes) -> None:
        self._lignes = lignes

    def fetchone(self):
        return self._lignes[0] if self._lignes else None

    def fetchall(self):
        return self._lignes


class _BaseJetable(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_986_"))
        self.db = self._tmp / "cinesort.sqlite"
        # Base creee par le VRAI chemin d'initialisation, migrations comprises.
        # Une base fabriquee a la main (`CREATE TABLE runs (id INTEGER)`) entre
        # en conflit avec la migration 001, qui attend d'autres colonnes : on
        # mesurerait alors « les migrations echouent » et non le sujet.
        SQLiteStore(db_path=self.db).initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _verifier(self, verdict: str) -> tuple[SQLiteStore, str]:
        """Joue `_check_integrity` avec un checkpoint qui echoue."""
        store = SQLiteStore(db_path=self.db)
        vraie = sqlite3.connect(str(self.db))
        fausse = _EchecDeCheckpoint(vraie, verdict)
        with mock.patch.object(store, "_connect", return_value=fausse):
            statut = store._check_integrity()
        self.assertGreaterEqual(fausse.checkpoints_tentes, 1, "le checkpoint n'a meme pas ete tente")
        return store, statut


class UnCheckpointEnEchecRendLeVerdictNonConcluantTests(_BaseJetable):
    def test_le_drapeau_est_POSE(self) -> None:
        """Le coeur du correctif."""
        store, _ = self._verifier("ok")

        self.assertTrue(
            store._integrity_non_concluant,
            "un checkpoint echoue ne marque pas le verdict comme non concluant",
        )

    def test_il_est_pose_MEME_si_le_verdict_annonce_une_corruption(self) -> None:
        """C'est le cas qui compte : la corruption annoncee peut etre FANTOME,
        produite par des pages WAL perimees que le checkpoint n'a pas pu
        fusionner."""
        store, statut = self._verifier("*** in database main *** corruption")

        self.assertTrue(store._integrity_non_concluant)
        self.assertIn("corruption", statut, "le verdict brut doit rester lisible pour l'operateur")

    def test_il_est_REMIS_A_ZERO_a_chaque_passe(self) -> None:
        """Un drapeau collant ferait refuser toute restauration future, y compris
        legitime — un correctif qui eteint une garde."""
        store, _ = self._verifier("ok")
        self.assertTrue(store._integrity_non_concluant)

        # Seconde passe, checkpoint qui fonctionne : le drapeau doit retomber.
        store._check_integrity()

        self.assertFalse(store._integrity_non_concluant, "le drapeau est COLLANT")

    def test_un_checkpoint_qui_REUSSIT_ne_pose_rien(self) -> None:
        """Contre-epreuve : sans elle, un drapeau toujours vrai passerait."""
        store = SQLiteStore(db_path=self.db)

        store._check_integrity()

        self.assertFalse(store._integrity_non_concluant)


class InitializeREFUSEDeRestaurerTests(_BaseJetable):
    """La preuve qui compte : ce n'est pas le drapeau qui protege, c'est ce que
    `initialize()` en fait."""

    def _initialiser(self, verdict: str) -> tuple[SQLiteStore, list]:
        store = SQLiteStore(db_path=self.db)
        restaurations: list = []

        def _restore_espionne():
            restaurations.append(True)

        vraie = sqlite3.connect(str(self.db))
        fausse = _EchecDeCheckpoint(vraie, verdict)
        vrai_connect = store._connect

        appels = {"n": 0}

        def _connect_qui_echoue_une_fois(*a, **kw):
            # Seule la connexion du CHECK doit etre piegee ; les suivantes
            # (migrations, bootstrap) doivent etre vraies, sinon on mesurerait
            # une base cassee et non un checkpoint echoue.
            appels["n"] += 1
            if appels["n"] == 1:
                return fausse
            return vrai_connect(*a, **kw)

        with (
            mock.patch.object(store, "_connect", side_effect=_connect_qui_echoue_une_fois),
            mock.patch.object(store, "_attempt_auto_restore", side_effect=_restore_espionne),
        ):
            store.initialize()
        return store, restaurations

    def test_AUCUNE_restauration_quand_le_verdict_est_non_concluant(self) -> None:
        """Le defaut lui-meme : avant, la base vivante etait ECRASEE ici."""
        _store, restaurations = self._initialiser("*** in database main *** corruption")

        self.assertEqual(
            restaurations,
            [],
            "la base vivante est ecrasee sur un diagnostic que le code lui-meme dit non fiable",
        )

    def test_l_evenement_dit_INCONCLUSIVE_et_non_unreadable(self) -> None:
        """L'operateur doit distinguer « je n'ai pas pu lire » de « je n'ai pas
        pu conclure » : la base est lisible, c'est le verdict qui ne fait pas
        autorite."""
        store, _ = self._initialiser("*** in database main *** corruption")

        evenement = store._integrity_event or {}
        self.assertEqual(evenement.get("status"), "inconclusive", evenement)
        self.assertIsNone(evenement.get("backup_used"))
        self.assertIn("corruption", str(evenement.get("raw", "")), "le verdict brut est perdu")


if __name__ == "__main__":
    unittest.main()
