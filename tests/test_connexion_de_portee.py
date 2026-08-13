"""Partager une connexion doit gagner l'OUVERTURE sans toucher a la DURABILITE.

LE COUT EST DANS L'OUVERTURE, PAS DANS LES PRAGMA. Mesure du depot : les MEMES
huit PRAGMA coutent x139 sur un handle neuf, et en retirer six sur quatorze ne
rend que 1,7 %. Un scan a froid de 10 000 films ouvre 60 003 connexions et passe
23 % de son temps a les ouvrir.

CE QUE CES TESTS PROTEGENT, ET C'EST LE POINT DELICAT. Le `with conn:` de sqlite3
COMMITE a la sortie. Partager un handle entre repositories deplacerait donc les
frontieres de commit — sauf si chaque appel garde son propre `with`. C'est le
choix fait ici : on partage le HANDLE, jamais la TRANSACTION. Sur une application
qui deplace des fichiers sur disque, ce n'etait pas negociable.

Ce choix ne tient QUE SI les appels ne s'imbriquent pas : sur un handle partage,
la sortie d'un appel INTERNE commiterait le travail partiel de l'appel externe.
La profondeur maximale est donc MESUREE ici, pas supposee.
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir, portee_de_requete


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cinesort_portee_"))
        # `addCleanup` et pas `tearDown` : il s'execute meme si `setUp` echoue a
        # mi-parcours, et le garde-fou de fuite `%TEMP%` du depot compte les
        # dossiers laisses derriere (la suite en abandonnait 259 par execution).
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = SQLiteStore(db_path_for_state_dir(self.tmp))
        self.store.initialize()

    def _ouvertures(self) -> list:
        """Compte les ouvertures REELLES de connexion pendant un bloc."""
        vues = []
        vrai = self.store._connect

        def _compte():
            conn = vrai()
            vues.append(conn)
            return conn

        self.store._connect = _compte  # type: ignore[method-assign]
        return vues


class UnePorteeNOuvreQuUneConnexionTests(_Base):
    def test_sans_portee_chaque_appel_ouvre_la_sienne(self) -> None:
        """L'etat de reference : c'est ce cout que la portee supprime."""
        vues = self._ouvertures()
        for _ in range(5):
            with self.store._managed_conn() as conn:
                conn.execute("SELECT 1").fetchone()

        self.assertEqual(len(vues), 5, "le comportement historique a change hors portee")

    def test_dans_une_portee_les_appels_PARTAGENT_le_handle(self) -> None:
        vues = self._ouvertures()
        with portee_de_requete():
            handles = []
            for _ in range(5):
                with self.store._managed_conn() as conn:
                    handles.append(conn)
                    conn.execute("SELECT 1").fetchone()

        self.assertEqual(len(vues), 1, f"{len(vues)} connexions ouvertes au lieu d'une seule")
        self.assertEqual(len(set(id(h) for h in handles)), 1, "les appels n'ont pas partage le meme handle")

    def test_la_portee_est_REENTRANTE(self) -> None:
        """Une portee imbriquee doit reutiliser celle du dessus : deux handles
        sur la meme base depuis le meme contexte, et le second attendrait le
        verrou du premier."""
        vues = self._ouvertures()
        handles = []
        with portee_de_requete():
            with portee_de_requete():
                with self.store._managed_conn() as c:
                    handles.append(c)
            with self.store._managed_conn() as c:
                handles.append(c)

        self.assertEqual(len(vues), 1, "la portee imbriquee a ouvert une seconde connexion")
        self.assertEqual(len(set(id(h) for h in handles)), 1)

    def test_une_portee_SANS_acces_a_la_base_n_ouvre_RIEN(self) -> None:
        """PARESSEUSE : ouvrir a l'entree ferait payer une connexion — et une
        construction d'infra — aux requetes qui ne touchent jamais la base, et
        les ferait echouer pendant un effacement (barriere de gel)."""
        vues = self._ouvertures()
        with portee_de_requete():
            pass

        self.assertEqual(len(vues), 0, "la portee a ouvert une connexion que personne n'a demandee")

    def test_deux_bases_dans_la_MEME_portee_ne_partagent_pas_leur_handle(self) -> None:
        """Partager un handle entre deux fichiers ecrirait dans la mauvaise base."""
        autre_dir = Path(tempfile.mkdtemp(prefix="cinesort_portee2_"))
        self.addCleanup(shutil.rmtree, autre_dir, ignore_errors=True)
        autre = SQLiteStore(db_path_for_state_dir(autre_dir))
        autre.initialize()

        with portee_de_requete():
            with self.store._managed_conn() as a, autre._managed_conn() as b:
                self.assertIsNot(a, b, "deux bases distinctes ont partage un handle")

    def test_a_la_SORTIE_la_portee_est_rendue(self) -> None:
        """Sinon la connexion suivante croirait etre dans une portee morte."""
        with portee_de_requete():
            pass
        vues = self._ouvertures()
        with self.store._managed_conn() as conn:
            conn.execute("SELECT 1").fetchone()

        self.assertEqual(len(vues), 1, "la portee a survecu a son bloc")


class LesFRONTIERESDeCommitNeBougentPASTests(_Base):
    """LE test qui compte. Le gain de performance ne vaut rien s'il rend une
    ecriture moins durable qu'avant."""

    def _lire(self, chemin: Path) -> list:
        """Relit la base par une connexion INDEPENDANTE : seule une ecriture
        reellement COMMITEE y est visible."""
        # `closing` EN PLUS du `with` : le context manager de sqlite3 COMMITE
        # mais ne FERME PAS. Sans lui, le fichier restait verrouille, `rmtree`
        # echouait en silence, et le garde-fou de fuite `%TEMP%` du depot
        # rougissait — sur une connexion ouverte par le test lui-meme.
        with closing(sqlite3.connect(str(chemin))) as autre:
            return autre.execute("SELECT valeur FROM t_portee ORDER BY valeur").fetchall()

    def test_chaque_appel_commite_son_unite_MEME_dans_une_portee(self) -> None:
        chemin = self.store.db_path
        with self.store._managed_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t_portee (valeur INTEGER)")

        with portee_de_requete():
            with self.store._managed_conn() as conn:
                conn.execute("INSERT INTO t_portee VALUES (1)")
            # Une connexion INDEPENDANTE doit deja voir la valeur : si elle ne la
            # voit pas, la portee a repousse le commit a sa propre sortie, et une
            # panne d'ici la perdrait un travail qui etait acquis AVANT.
            vues_pendant = self._lire(chemin)
            with self.store._managed_conn() as conn:
                conn.execute("INSERT INTO t_portee VALUES (2)")

        self.assertEqual(vues_pendant, [(1,)], "le premier appel n'avait pas commite : la durabilite a recule")
        self.assertEqual(self._lire(chemin), [(1,), (2,)])

    def test_un_ECHEC_tardif_n_annule_pas_ce_qui_etait_acquis(self) -> None:
        """C'est la contrepartie de la frontiere par appel, et la raison de ce
        choix : un echec au troisieme appel ne doit pas defaire les deux
        premiers, comme aujourd'hui."""
        chemin = self.store.db_path
        with self.store._managed_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t_portee (valeur INTEGER)")

        with self.assertRaises(sqlite3.OperationalError):
            with portee_de_requete():
                with self.store._managed_conn() as conn:
                    conn.execute("INSERT INTO t_portee VALUES (1)")
                with self.store._managed_conn() as conn:
                    conn.execute("INSERT INTO t_portee VALUES (2)")
                with self.store._managed_conn() as conn:
                    conn.execute("INSERT INTO table_qui_n_existe_pas VALUES (3)")

        self.assertEqual(
            self._lire(chemin),
            [(1,), (2,)],
            "l'echec du troisieme appel a emporte les deux premiers",
        )

    def test_l_echec_d_un_appel_annule_SON_appel_et_lui_seul(self) -> None:
        chemin = self.store.db_path
        with self.store._managed_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t_portee (valeur INTEGER)")

        with portee_de_requete():
            with self.assertRaises(sqlite3.OperationalError):
                with self.store._managed_conn() as conn:
                    conn.execute("INSERT INTO t_portee VALUES (7)")
                    conn.execute("INSERT INTO table_qui_n_existe_pas VALUES (8)")
            with self.store._managed_conn() as conn:
                conn.execute("INSERT INTO t_portee VALUES (9)")

        self.assertEqual(self._lire(chemin), [(9,)], "le rollback de l'appel en echec n'a pas eu lieu")


class UnAppelIMBRIQUENePartagePasTests(_Base):
    """LA MESURE A CONTREDIT L'HYPOTHESE, ET LA CONCEPTION A SUIVI.

    Une premiere sonde, limitee aux tests de repositories, donnait une
    profondeur maximale de 1 — et j'en avais conclu que l'imbrication n'existait
    pas. La sonde sur le perimetre CI **complet** rend 20 052 ouvertures et une
    profondeur maximale de **2**.

    Sur un handle partage, la sortie d'un appel INTERNE commiterait le travail
    partiel de l'appel EXTERNE. Les deux echappatoires changent la semantique :
    ne commiter qu'au niveau le plus externe repousse la durabilite de l'appel
    interne ; commiter a chaque niveau avance celle de l'externe. La seule
    option qui ne change RIEN est de rendre a l'appel imbrique ce qu'il avait
    deja : sa propre connexion.
    """

    def test_un_appel_imbrique_ouvre_SA_propre_connexion(self) -> None:
        vues = self._ouvertures()
        handles = []
        with portee_de_requete():
            with self.store._managed_conn() as externe:
                handles.append(externe)
                with self.store._managed_conn() as interne:
                    handles.append(interne)

        self.assertEqual(len(vues), 2, "l'appel imbrique a reutilise le handle de l'appel qui l'englobe")
        self.assertIsNot(handles[0], handles[1])

    def test_apres_l_imbrication_le_partage_REPREND(self) -> None:
        """Le refus de partager ne doit valoir que pour la duree de
        l'imbrication : sinon un seul appel imbrique ferait perdre le benefice
        de toute la portee."""
        vues = self._ouvertures()
        handles = []
        with portee_de_requete():
            with self.store._managed_conn() as a:
                handles.append(a)
                with self.store._managed_conn() as interne:
                    interne.execute("SELECT 1").fetchone()
            with self.store._managed_conn() as b:
                handles.append(b)

        self.assertEqual(len(vues), 2, "le partage n'a pas repris apres l'imbrication")
        self.assertIs(handles[0], handles[1])

    def test_l_imbrication_se_comporte_EXACTEMENT_comme_avant(self) -> None:
        """LE contrat de cette vague : gagner l'ouverture sans rien changer
        d'autre. On ne postule donc pas un comportement « correct » pour
        l'imbrication — on exige qu'il soit LE MEME qu'aujourd'hui.

        Mesure a bras alternes, deux tours chacun : les deux bras rendent le
        meme etat de base ET les memes erreurs, `database is locked` comprise.
        Cette erreur est un defaut PREEXISTANT — un ecrivain imbrique sur une
        seconde connexion se heurte au verrou de celui qui l'englobe — et ce
        n'est pas cette vague qui l'introduit ni ne le corrige.
        """
        observations = []
        for avec_portee in (False, True, False, True):
            observations.append(self._scenario_imbrique(avec_portee))

        sans = [o for i, o in enumerate(observations) if i % 2 == 0]
        avec = [o for i, o in enumerate(observations) if i % 2 == 1]
        self.assertEqual(sans[0], sans[1], "le bras de reference n'est pas reproductible")
        self.assertEqual(
            avec,
            sans,
            "la portee a change le comportement de l'imbrication : "
            f"sans={sans[0]} vs avec={avec[0]}",
        )

    def _scenario_imbrique(self, avec_portee: bool) -> tuple:
        """Un ecrivain imbrique dans un ecrivain, puis l'externe echoue.

        Rend `(etat de la base, erreurs vues)` — deux grandeurs observables,
        comparables entre les deux bras.
        """
        dossier = Path(tempfile.mkdtemp(prefix="cinesort_imb_"))
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        store = SQLiteStore(db_path_for_state_dir(dossier))
        store.initialize()
        with store._managed_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t_portee (valeur INTEGER)")

        erreurs = []
        portee = portee_de_requete() if avec_portee else contextlib.nullcontext()
        try:
            with portee:
                with store._managed_conn() as externe:
                    externe.execute("INSERT INTO t_portee VALUES (1)")
                    try:
                        with store._managed_conn() as interne:
                            interne.execute("INSERT INTO t_portee VALUES (2)")
                    except sqlite3.Error as exc:
                        erreurs.append(f"interne:{type(exc).__name__}")
                    externe.execute("INSERT INTO table_qui_n_existe_pas VALUES (3)")
        except sqlite3.Error as exc:
            erreurs.append(f"externe:{type(exc).__name__}")

        with closing(sqlite3.connect(str(store.db_path))) as autre:
            base = autre.execute("SELECT valeur FROM t_portee ORDER BY valeur").fetchall()
        return base, tuple(erreurs)


class LaPorteeNeFUITEPasEntreThreadsTests(_Base):
    """Un `ContextVar` suit le contexte d'execution. Si la portee d'un thread
    etait visible d'un autre, deux threads ecriraient sur le MEME handle sqlite3
    — que le module n'autorise pas par defaut (`check_same_thread`)."""

    def test_un_thread_voisin_ouvre_SA_propre_connexion(self) -> None:
        vues = self._ouvertures()
        resultat = {}

        def voisin() -> None:
            with self.store._managed_conn() as conn:
                resultat["id"] = id(conn)
                conn.execute("SELECT 1").fetchone()

        with portee_de_requete():
            # La portee etant PARESSEUSE, il faut d'abord la faire naitre : sans
            # cette ligne, le contexte principal n'aurait ouvert aucune connexion
            # et le test compterait 1 au lieu de 2 sans rien prouver.
            with self.store._managed_conn() as mienne:
                mienne.execute("SELECT 1").fetchone()
            t = threading.Thread(target=voisin)
            t.start()
            t.join()

        self.assertNotEqual(resultat.get("id"), id(mienne), "un thread voisin a repris la portee d'un autre")
        self.assertEqual(len(vues), 2, "le thread voisin n'a pas ouvert sa propre connexion")


if __name__ == "__main__":
    unittest.main()
