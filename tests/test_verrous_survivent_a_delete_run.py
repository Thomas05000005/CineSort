"""Un verrou de champ doit SURVIVRE a la suppression du run qui l'a vu naitre.

LE DEFAUT, ET IL EST DE MOI. La PR #1006 a rendu `delete_run` symetrique de la
garde d'unicite `run_id_est_utilise` : les deux iterent la MEME constante, pour
qu'aucune table ne puisse reserver un `run_id` sans le liberer. Cette symetrie
corrigeait un vrai defaut — un identifiant occupe pour toujours.

Mais elle a mis `film_field_locks` dans le lot, et cette table n'est pas de la
meme nature que les autres. L'identite d'un verrou est `(film_id, field_name)` ;
son `run_id` est documente « audit, optionnel » et son schema le declare
`TEXT NOT NULL DEFAULT ''`. Un verrou est une INTENTION DE L'UTILISATEUR : le
titre qu'il a corrige a la main et veut proteger du prochain rematch.

LES DEUX LISTES REPONDENT A DEUX QUESTIONS DIFFERENTES :

    run_id_est_utilise  -> « cet identifiant est-il reference quelque part ? »
    delete_run          -> « qu'est-ce qui APPARTIENT a ce run ? »

Les confondre etait une simplification de trop. La reponse n'est pourtant ni de
retirer la table de la garde (l'identifiant redeviendrait immortel), ni de la
laisser purger (le verrou disparaitrait) : c'est d'EFFACER LE `run_id` sans
toucher la ligne. Les deux invariants tiennent alors ensemble.

PORTEE REELLE, MESUREE. Les deux ecrivains de production laissent `run_id=''` :
aucun verrou n'est perdu AUJOURD'HUI. Le risque est latent — le cron de
retention (90 j) appelle `cleanup_old_runs` -> `delete_run`, et le jour ou un
appelant renseignerait le champ, les verrous permanents disparaitraient sans un
mot. Ces tests posent donc la garde AVANT que le defaut n'arrive.

Signale par l'audit du 2026-08-12 (`docs/internal/audits/findings/`), qui note
lui-meme l'absence de perte actuelle plutot que de dramatiser.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore
from tests._helpers import cleanup_test_tree


class UnVerrouSURVITALaSuppressionDuRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_verrous_run_"))
        self.store = SQLiteStore(self._tmp / "cinesort.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        # Fermer le store AVANT de supprimer l'arbre : sur Windows une connexion
        # SQLite ouverte empeche le rmtree, qui echoue en silence sous
        # `ignore_errors=True` et laisse un dossier dans %TEMP%. Le garde-fou de
        # fuite temporaire du depot l'a signale sur ces tests memes.
        with contextlib.suppress(Exception):
            self.store.close()
        cleanup_test_tree(self._tmp)

    def _semer_verrou(self, run_id: str) -> None:
        with sqlite3.connect(str(self._tmp / "cinesort.sqlite")) as conn:
            conn.execute(
                "INSERT INTO film_field_locks(film_id, run_id, row_id, field_name, locked_value, locked_at, source) "
                "VALUES ('tmdb:603', ?, 'r1', 'proposed_title', 'Matrix', 1.0, 'ui_lock')",
                (run_id,),
            )
            conn.commit()

    def _verrous(self) -> list:
        with sqlite3.connect(str(self._tmp / "cinesort.sqlite")) as conn:
            return conn.execute("SELECT film_id, field_name, run_id FROM film_field_locks").fetchall()

    def test_le_verrou_est_conserve(self) -> None:
        """LE test. Sans le correctif, `delete_run` l'efface purement."""
        self.store.run.insert_run_pending(run_id="run-A", root="R", state_dir=str(self._tmp), config={})
        self._semer_verrou("run-A")
        self.assertEqual(len(self._verrous()), 1, "precondition : le verrou doit exister")

        self.store.run.delete_run("run-A")

        restants = self._verrous()
        self.assertEqual(
            len(restants),
            1,
            "le verrou a ete SUPPRIME avec le run : l'utilisateur perd le titre qu'il protegeait.",
        )
        self.assertEqual(restants[0][0], "tmdb:603")
        self.assertEqual(restants[0][1], "proposed_title")

    def test_son_run_id_est_EFFACE(self) -> None:
        """L'autre moitie de l'invariant : la ligne reste, la reference part."""
        self.store.run.insert_run_pending(run_id="run-B", root="R", state_dir=str(self._tmp), config={})
        self._semer_verrou("run-B")

        self.store.run.delete_run("run-B")

        self.assertEqual(self._verrous()[0][2], "", "le run_id n'a pas ete detache")

    def test_l_identifiant_redevient_LIBRE(self) -> None:
        """C'est l'invariant de #984, et il doit tenir malgre la conservation.

        Si la ligne restait avec son `run_id`, la garde d'unicite continuerait de
        declarer l'identifiant occupe — l'immortalite que #984 a corrigee,
        revenue par la porte de derriere.
        """
        self.store.run.insert_run_pending(run_id="run-C", root="R", state_dir=str(self._tmp), config={})
        self._semer_verrou("run-C")
        self.assertTrue(self.store.run.run_id_est_utilise("run-C"), "precondition")

        self.store.run.delete_run("run-C")

        self.assertFalse(
            self.store.run.run_id_est_utilise("run-C"),
            "l'identifiant reste occupe : il ne pourra JAMAIS etre reattribue.",
        )

    def test_un_verrou_SANS_run_id_n_est_pas_touche(self) -> None:
        """Le cas de production d'aujourd'hui : `set_lock` laisse `run_id=''`.

        Un `UPDATE ... WHERE run_id=?` avec `rid` non vide ne peut pas l'atteindre,
        mais la contre-epreuve coute une ligne et interdit une future
        generalisation maladroite du predicat.
        """
        self.store.run.insert_run_pending(run_id="run-D", root="R", state_dir=str(self._tmp), config={})
        self._semer_verrou("")

        self.store.run.delete_run("run-D")

        self.assertEqual(len(self._verrous()), 1)
        self.assertEqual(self._verrous()[0][2], "")


class LesAutresTablesSontTOUJOURSPurgeesTests(unittest.TestCase):
    """Contre-epreuve : le detachement ne doit pas s'etendre par megarde.

    Sans ces tests, remplacer toutes les suppressions par des detachements
    passerait la classe ci-dessus — et laisserait la base pleine d'orphelines.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_verrous_autres_"))
        self.chemin = self._tmp / "cinesort.sqlite"
        self.store = SQLiteStore(self.chemin)
        self.store.initialize()

    def tearDown(self) -> None:
        # Fermer le store AVANT de supprimer l'arbre : sur Windows une connexion
        # SQLite ouverte empeche le rmtree, qui echoue en silence sous
        # `ignore_errors=True` et laisse un dossier dans %TEMP%. Le garde-fou de
        # fuite temporaire du depot l'a signale sur ces tests memes.
        with contextlib.suppress(Exception):
            self.store.close()
        cleanup_test_tree(self._tmp)

    def test_une_ligne_errors_est_bien_SUPPRIMEE(self) -> None:
        self.store.run.insert_run_pending(run_id="run-E", root="R", state_dir=str(self._tmp), config={})
        with sqlite3.connect(str(self.chemin)) as conn:
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES ('run-E', 1.0, 'scan', 'X', 'boum')",
            )
            conn.commit()

        self.store.run.delete_run("run-E")

        with sqlite3.connect(str(self.chemin)) as conn:
            restants = conn.execute("SELECT COUNT(*) FROM errors WHERE run_id='run-E'").fetchone()[0]
        self.assertEqual(restants, 0, "une ligne de run doit etre SUPPRIMEE, pas detachee")

    def test_la_liste_de_detachement_reste_MINIMALE(self) -> None:
        """Elle ne doit contenir que des tables dont la ligne survit au run.

        Une entree ajoutee a la legere transformerait une purge en accumulation
        silencieuse d'orphelines.
        """
        from cinesort.infra.db.repositories.run import RunRepository

        self.assertEqual(
            RunRepository._TABLES_DETACHEES_AU_LIEU_D_ETRE_PURGEES,
            ("film_field_locks",),
            "toute nouvelle table detachee doit etre justifiee ici meme",
        )

    def test_toute_table_detachee_est_AUSSI_dans_la_garde(self) -> None:
        """Sinon l'identifiant redeviendrait invisible a `run_id_est_utilise`."""
        from cinesort.infra.db.repositories.run import RunRepository

        for table in RunRepository._TABLES_DETACHEES_AU_LIEU_D_ETRE_PURGEES:
            self.assertIn(table, RunRepository._TABLES_PORTANT_RUN_ID)


if __name__ == "__main__":
    unittest.main()
