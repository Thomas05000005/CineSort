"""Apres « Reinitialiser la base », l'application doit encore fonctionner.

LE DEFAUT, MESURE. `reset_support.reset_database` appelle
`api._close_infra()` derriere un `if hasattr(api, "_close_infra")` — et
`CineSortApi` NE DEFINISSAIT PAS cette methode. Le garde etait donc toujours
faux, et `_infra_by_state_dir` n'etait jamais purge.

Or `get_or_create_infra` rend le cache SANS rappeler `initialize()` (« idempotent
+ deja appele au premier create »). Apres la suppression du fichier de base,
l'instance cachee pointait donc sur un fichier disparu, le schema n'etait jamais
recree, et la facade repondait quand meme `ok: True` sur une base vide.

A/B A BRAS ALTERNES, UNE SEULE VARIABLE (la presence du hook), 2 tours chacun,
sur `main` et avec `dry_run=False` — car `reset_database` est en apercu PAR
DEFAUT depuis le durcissement des purges, et un appel sans cet argument ne
touche a rien (il ne mesurerait donc rien) :

    SANS hook (etat livre) -> user_version 32 ->  0, 21 tables requises MANQUANTES
    AVEC hook              -> user_version 32 -> 32,  0 table manquante

Une premiere version de cette mesure tournait sur le checkout principal, reste
sur une branche ANTERIEURE a ce durcissement : elle mesurait donc un code qui
n'est plus celui de `main`. Le worktree dit quelle branche il porte ; le
checkout, lui, porte la sienne.

POURQUOI CE FICHIER EXISTE ALORS QU'UN TEST COUVRAIT DEJA LE HOOK.
`test_phase4_parametres_endpoints.py` asserte `_close_infra_called` sur une
FAUSSE api qui definit elle-meme `_close_infra`. Une fixture qui ne vient pas de
la production ne prouve que la coherence du test avec lui-meme : elle serait
restee verte pendant que la vraie application, elle, n'avait pas la methode. Ces
tests-ci passent donc par `CineSortApi`.

CE FICHIER GARDE AUSSI LA VAGUE E. Le plan y prevoit un pool de connexions ; le
jour ou les connexions survivront a l'appel, un cache non purge ne sera plus
seulement un schema manquant, mais un `PermissionError` Windows a la suppression
du fichier. Le hook doit etre vivant AVANT.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.db.sqlite_store import db_path_for_state_dir
from cinesort.ui.api import reset_support
from tests._helpers import cleanup_test_tree


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cinesort_reset_schema_"))
        self.state_dir = self.tmp / "state"
        self.root = self.tmp / "root"
        self.state_dir.mkdir()
        self.root.mkdir()
        # L'API REELLE, pas une doublure : c'est tout l'objet de ce fichier.
        self.api = backend.CineSortApi()
        self.api.settings.save_settings({"root": str(self.root), "state_dir": str(self.state_dir)})

    def tearDown(self) -> None:
        # `cleanup_test_tree` joint d'abord les threads de fond de l'app : sans
        # cela ils RECREENT le state_dir juste apres le rmtree (mesure du depot,
        # 12 dossiers sur 13), et peuvent tomber sur celui d'un test voisin.
        cleanup_test_tree(self.tmp)


class LeHookDeFermetureEXISTEVraimentTests(_Base):
    def test_l_API_REELLE_porte_la_methode_que_le_reset_appelle(self) -> None:
        """`reset_database` fait `hasattr(api, "_close_infra")`. Si la methode
        manque, le garde est toujours faux et le hook est decoratif — c'etait le
        cas, et un test sur une fausse api ne pouvait pas le voir."""
        self.assertTrue(
            hasattr(self.api, "_close_infra"),
            "CineSortApi n'a pas _close_infra : le hook de reset_database est mort",
        )
        self.assertTrue(callable(self.api._close_infra))

    def test_il_OUBLIE_les_stores_caches_et_dit_combien(self) -> None:
        self.api._get_or_create_infra(self.state_dir)
        self.assertEqual(len(self.api._infra_by_state_dir), 1, "aucune infra en cache : le test ne prouverait rien")

        oubliees = self.api._close_infra()

        self.assertEqual(oubliees, 1, "le hook ne rend pas le nombre d'entrees oubliees")
        self.assertEqual(self.api._infra_by_state_dir, {}, "le cache d'infra n'a pas ete purge")

    def test_une_fermeture_EN_ECHEC_n_empeche_pas_l_oubli(self) -> None:
        """L'oubli est ce qui compte : sans lui, l'instance morte est reservie.
        Une `PRAGMA optimize` qui echoue ne doit pas la faire survivre."""
        store, runner = self.api._get_or_create_infra(self.state_dir)

        def boum() -> None:
            raise OSError("disque parti")

        store.close = boum  # type: ignore[method-assign]
        oubliees = self.api._close_infra()

        self.assertEqual(oubliees, 1)
        self.assertEqual(self.api._infra_by_state_dir, {})


class LaBARRIEREEmpecheDeReconstruirePendantLeWipeTests(_Base):
    """PURGER NE SUFFIT PAS, ET C'EST LE POINT LE PLUS SUBTIL DE CE CORRECTIF.

    `get_or_create_infra` passe son `initialize()` — integrity_check,
    sauvegarde, migrations, soit des SECONDES — HORS du verrou, et n'insere
    qu'apres. Un batisseur parti avant la purge re-cache donc son store APRES
    elle. Et la fenetre n'est pas etroite : `_close_infra()` est appele a
    l'etape 1 du wipe, mais la copie de sauvegarde et le `unlink` viennent
    APRES — sur une base de plusieurs Go, la copie dure plusieurs secondes,
    pendant lesquelles le SPA interroge un serveur multi-thread.
    """

    def test_pendant_le_gel_toute_demande_d_infra_est_REFUSEE(self) -> None:
        """Refuser franchement vaut mieux que rendre un handle sur un fichier en
        train de disparaitre : sur un chemin destructif, l'erreur va dans le sens
        restrictif."""
        from cinesort.ui.api.runtime_support import InfraGeleeError

        self.api._get_or_create_infra(self.state_dir)
        with self.api._infra_gelee() as oubliees:
            self.assertEqual(oubliees, 1, "le gel n'a pas commence par purger")
            with self.assertRaises(InfraGeleeError):
                self.api._get_or_create_infra(self.state_dir)

        # Le gel leve : on peut de nouveau construire.
        store, _ = self.api._get_or_create_infra(self.state_dir)
        self.assertIsNotNone(store)

    def test_ce_qu_un_batisseur_insere_PENDANT_le_gel_est_oublie_a_la_sortie(self) -> None:
        """Un batisseur parti AVANT le gel n'a pas vu la barriere : il inserera
        quand meme. La sortie du gel doit donc repurger, sinon le defaut revient
        a l'identique une fois le fichier supprime."""
        self.api._get_or_create_infra(self.state_dir)
        with self.api._infra_gelee():
            # On simule l'insertion tardive du batisseur, qui se fait sous verrou.
            with self.api._runs_lock:
                self.api._infra_by_state_dir["tardif"] = ("faux-store", "faux-runner")

        self.assertEqual(
            self.api._infra_by_state_dir,
            {},
            "l'entree inseree pendant le gel a survecu : le store condamne sera reservi",
        )

    def test_le_gel_est_REENTRANT(self) -> None:
        """Deux routes destructives peuvent se suivre ; la premiere a sortir ne
        doit pas lever la barriere de la seconde."""
        from cinesort.ui.api.runtime_support import InfraGeleeError

        with self.api._infra_gelee():
            with self.api._infra_gelee():
                with self.assertRaises(InfraGeleeError):
                    self.api._get_or_create_infra(self.state_dir)
            with self.assertRaises(InfraGeleeError):
                self.api._get_or_create_infra(self.state_dir)
        self.assertIsNotNone(self.api._get_or_create_infra(self.state_dir))


class UnRunACTIFInterditLEffacementTests(_Base):
    """Le `JobRunner` cache est le SEUL verrou d'exclusion mutuelle du depot :
    `start_job` refuse un second run via `_active_run_locked()`, et rien au
    niveau REST ne double cette garde. Oublier l'instance — ce que fait la
    purge — remettrait ce verrou a zero, et deux workers pourraient ecrire en
    parallele sur la meme base.

    Plutot que d'inventer un mecanisme pour survivre a cela, on le refuse :
    supprimer la base pendant qu'un scan tourne est destructeur avec ou sans ce
    correctif."""

    def _avec_un_run_actif(self) -> None:
        class _RunEnCours:
            running = True

        self.api._runs["run-en-cours"] = _RunEnCours()

    def test_reset_database_REFUSE_pendant_un_run(self) -> None:
        self.api._get_or_create_infra(self.state_dir)
        self._avec_un_run_actif()

        res = reset_support.reset_database(self.api, dry_run=False)

        self.assertFalse(res.get("ok"), "la base a ete supprimee pendant un traitement")
        self.assertIn("run-en-cours", str(res.get("error", "")), "le refus ne nomme pas le run qui bloque")
        self.assertTrue(
            db_path_for_state_dir(self.state_dir).is_file(),
            "le fichier de base a disparu malgre le refus",
        )

    def test_reset_all_user_data_REFUSE_aussi(self) -> None:
        """La route jumelle supprime le `state_dir` ENTIER : elle a encore plus
        besoin de ce garde."""
        self.api._get_or_create_infra(self.state_dir)
        self._avec_un_run_actif()

        res = reset_support.reset_all_user_data(self.api, "RESET")

        self.assertFalse(res.get("ok"))
        self.assertTrue(self.state_dir.exists(), "le dossier d'etat a ete vide pendant un traitement")

    def test_la_route_JUMELLE_efface_sous_BARRIERE(self) -> None:
        """`reset_all_user_data` supprime le `state_dir` ENTIER — donc le dossier
        `db/`. Sans barriere, le store cache etait resservi ensuite alors qu'il ne
        pouvait meme plus ouvrir de connexion, son dossier ayant disparu. On
        observe l'effet visible du gel : a la sortie, plus rien en cache."""
        self.api._get_or_create_infra(self.state_dir)
        self.assertEqual(len(self.api._infra_by_state_dir), 1, "rien en cache : le test ne prouverait rien")

        res = reset_support.reset_all_user_data(self.api, "RESET")

        self.assertTrue(res.get("ok"), f"le reset a echoue : {res}")
        self.assertEqual(
            self.api._infra_by_state_dir,
            {},
            "le store d'avant survit au wipe : il sera reservi sur un dossier disparu",
        )

    def test_l_APERCU_reste_possible_pendant_un_run(self) -> None:
        """Un apercu ne touche a rien : le refuser priverait l'utilisateur de la
        seule information qui l'aiderait a decider."""
        self.api._get_or_create_infra(self.state_dir)
        self._avec_un_run_actif()

        res = reset_support.reset_database(self.api, dry_run=True)

        self.assertTrue(res.get("ok"), f"l'apercu a ete refuse : {res}")


class LesDOUBLURESNeDoiventPasDeriverDuVraiContratTests(unittest.TestCase):
    """LA CAUSE RACINE DU FAUX VERT D'ORIGINE.

    `test_phase4_parametres_endpoints.py` assertait `_close_infra_called` sur une
    FAUSSE api qui definissait elle-meme la methode — pendant que `CineSortApi`,
    elle, ne l'avait pas. Le test prouvait sa coherence avec lui-meme et serait
    reste vert quoi qu'il arrive a l'application.

    Ce test verrouille le lien : toute methode que `reset_support` appelle sur
    `api` doit exister sur le VRAI objet.
    """

    #: Ce que `reset_support` attend de l'api, en plus des facades.
    _CONTRAT = ("_close_infra", "_infra_gelee")

    def test_le_vrai_CineSortApi_porte_tout_ce_que_reset_support_appelle(self) -> None:
        for nom in self._CONTRAT:
            self.assertTrue(
                hasattr(backend.CineSortApi, nom),
                f"CineSortApi n'a pas `{nom}` : le garde `hasattr` de reset_support sera toujours faux",
            )

    def test_la_doublure_de_phase4_porte_le_MEME_contrat(self) -> None:
        """Une doublure qui derive du vrai objet cesse de prouver quoi que ce
        soit — sans faire rougir personne."""
        from tests.test_phase4_parametres_endpoints import _FakeApi

        for nom in self._CONTRAT:
            self.assertTrue(
                hasattr(_FakeApi, nom),
                f"la doublure n'a pas `{nom}` : elle n'eprouve plus le chemin reel",
            )


class UnRESETLaisseUneBaseUTILISABLETests(_Base):
    """LE scenario utilisateur : « ma base est cassee, je la reinitialise »."""

    def test_le_schema_est_RECREE_apres_un_reset(self) -> None:
        store, _ = self.api._get_or_create_infra(self.state_dir)
        version_avant = store.get_user_version()
        self.assertGreater(version_avant, 0, "la base de depart n'a pas de schema : le test ne prouverait rien")

        # `dry_run=False` EXPLICITE : l'apercu est le defaut, et il ne ferme
        # aucune connexion — un test qui l'oublie n'eprouve rien.
        res = reset_support.reset_database(self.api, dry_run=False)
        self.assertTrue(res.get("ok"), f"le reset lui-meme a echoue : {res}")
        self.assertFalse(db_path_for_state_dir(self.state_dir).is_file(), "le fichier de base n'a pas ete supprime")

        # Ce que fait l'application juste apres : elle redemande son infra.
        store2, _ = self.api._get_or_create_infra(self.state_dir)

        self.assertIsNot(store2, store, "le store SUPPRIME a ete reservi depuis le cache")
        self.assertEqual(
            store2.get_user_version(),
            version_avant,
            "le schema n'a pas ete recree : toute lecture suivante porterait sur une base vide",
        )
        self.assertEqual(
            store2._missing_required_tables(),
            set(),
            "des tables requises manquent apres le reset",
        )

    def test_la_FACADE_repond_sur_une_base_reellement_reconstruite(self) -> None:
        """AVANT correctif, `run.get_dashboard()` repondait `ok: True` sur une
        base sans aucune table — un echec devenu succes silencieux. On verifie
        donc l'ETAT DE LA BASE derriere la reponse, pas seulement la reponse."""
        self.api._get_or_create_infra(self.state_dir)
        reset_support.reset_database(self.api, dry_run=False)

        reponse = self.api.run.get_dashboard()

        self.assertNotEqual(reponse.get("ok"), False, f"le dashboard est en erreur apres reset : {reponse}")
        store, _ = self.api._get_or_create_infra(self.state_dir)
        self.assertEqual(
            store._missing_required_tables(),
            set(),
            "le dashboard a repondu OK alors que la base n'a pas ses tables",
        )


if __name__ == "__main__":
    unittest.main()
