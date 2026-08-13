"""Une portee de requete OUVERTE pendant qu'une autre requete efface la base.

LE POINT AVEUGLE QUE CE FICHIER COMBLE. Deux lots ont ete fusionnes le meme jour
et chacun etait vert SEUL, parce que leurs batteries etaient DISJOINTES :

  * `test_connexion_de_portee.py` n'appelle jamais un reset et ne supprime jamais
    le fichier de base ;
  * `test_reset_database_recree_le_schema.py` n'ouvre jamais `portee_de_requete`
    — il appelle `reset_support` en direct, hors du `with portee_de_requete()`
    par lequel passe pourtant TOUTE requete POST en production
    (`rest_server.py`, dispatch de `_handle_post`).

Aucun test ne placait donc une portee ouverte et un wipe dans le meme processus,
et c'est la SEULE configuration ou l'interaction existe.

CE QU'ELLE COUTAIT, MESURE (A/B a bras alternes, deux tours chacun) :

    voisin sans connexion    -> ok=True   base supprimee
    voisin qui en tient une  -> ok=False  base TOUJOURS LA, `WinError 32`

Sous Windows, `unlink` refuse tant qu'un seul handle reste ouvert. Et le SPA
sonde `run/get_dashboard` toutes les 5 s : la configuration n'a rien d'exotique,
c'est le cas NORMAL. « Reinitialiser la base » ne reinitialisait rien, et rendait
un message Windows brut.

CE QUI EST EPROUVE ICI :

1. le cas normal — une requete voisine qui se termine — ne fait PLUS echouer le
   wipe (la barriere attend qu'elle relache) ;
2. le cas pathologique — une requete qui ne relache jamais — echoue en le DISANT,
   avec une consigne actionnable plutot qu'un `WinError`.

Le second compte autant que le premier : sur un chemin destructif, l'erreur va
dans le sens RESTRICTIF, et elle doit expliquer quoi faire.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.db.sqlite_store import db_path_for_state_dir, portee_de_requete, portees_ouvertes
from cinesort.ui.api import reset_support


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cinesort_portee_wipe_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state_dir = self.tmp / "state"
        self.root = self.tmp / "root"
        self.state_dir.mkdir()
        self.root.mkdir()
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)
        self.db = db_path_for_state_dir(self.state_dir)

    def _requete_voisine(self, relache: threading.Event, prete: threading.Event) -> threading.Thread:
        """Une requete REST voisine : elle ouvre sa portee et y lit la base.

        C'est la forme EXACTE de la production — `rest_server` enveloppe chaque
        POST dans `portee_de_requete()`, et la portee est PARESSEUSE : elle ne
        tient un handle qu'une fois qu'un repository a lu quelque chose.
        """

        def courir() -> None:
            with portee_de_requete():
                with self.store._managed_conn() as conn:
                    conn.execute("SELECT 1").fetchone()
                prete.set()
                relache.wait(20)

        fil = threading.Thread(target=courir, daemon=True)
        fil.start()
        prete.wait(5)
        return fil


class UneRequeteVOISINENEmpechePlusLeWipeTests(_Base):
    def test_sans_voisin_le_wipe_passe(self) -> None:
        """L'etat de reference : sans lui, le test suivant ne prouverait rien."""
        res = reset_support.reset_database(self.api, dry_run=False)

        self.assertTrue(res.get("ok"), res)
        self.assertFalse(self.db.is_file())

    def test_un_voisin_qui_se_TERMINE_ne_fait_plus_echouer_le_wipe(self) -> None:
        """LE cas normal, et celui qui echouait. Le SPA sonde le dashboard toutes
        les 5 s : une requete voisine est la regle, pas l'exception."""
        relache, prete = threading.Event(), threading.Event()
        fil = self._requete_voisine(relache, prete)
        self.assertEqual(portees_ouvertes(self.db), 1, "la requete voisine ne tient pas de connexion")

        # Elle se termine pendant que le wipe attend — comme une vraie requete.
        threading.Timer(0.3, relache.set).start()
        res = reset_support.reset_database(self.api, dry_run=False)
        relache.set()
        fil.join(5)

        self.assertTrue(res.get("ok"), f"le wipe a echoue alors que le voisin s'est termine : {res}")
        self.assertFalse(self.db.is_file(), "la base n'a pas ete supprimee")

    def test_un_voisin_qui_ne_RELACHE_JAMAIS_echoue_en_le_DISANT(self) -> None:
        """Sur un chemin destructif, l'erreur va dans le sens RESTRICTIF — et
        elle doit dire quoi faire. Un `WinError 32` brut ne le disait pas."""
        relache, prete = threading.Event(), threading.Event()
        fil = self._requete_voisine(relache, prete)
        try:
            res = reset_support.reset_database(self.api, dry_run=False)
        finally:
            relache.set()
            fil.join(5)

        self.assertFalse(res.get("ok"), "le wipe s'est declare reussi alors que la base est verrouillee")
        self.assertTrue(self.db.is_file(), "la base a disparu malgre le verrou")
        message = str(res.get("error") or res.get("message") or "")
        self.assertIn("requete", message.lower(), f"le message ne nomme pas la cause : {message}")
        self.assertIn("reessayez", message.lower(), f"le message ne dit pas quoi faire : {message}")
        self.assertNotIn("WinError", message, "le message Windows brut est remonte tel quel")


class LeCOMPTEDesPorteesEstFideleTests(_Base):
    """Le compte est ce sur quoi la barriere s'appuie : s'il derive, l'attente
    porte sur une grandeur qui ne veut rien dire."""

    def test_une_portee_SANS_lecture_ne_compte_pas(self) -> None:
        """La portee est PARESSEUSE : une requete qui ne touche pas la base ne
        tient aucun handle, et ne doit donc pas retarder un effacement."""
        with portee_de_requete():
            self.assertEqual(portees_ouvertes(self.db), 0)

    def test_le_compte_RETOMBE_a_la_sortie(self) -> None:
        with portee_de_requete():
            with self.store._managed_conn() as conn:
                conn.execute("SELECT 1").fetchone()
            self.assertEqual(portees_ouvertes(self.db), 1)

        self.assertEqual(portees_ouvertes(self.db), 0, "une portee fermee compte encore : l'attente ne finirait jamais")

    def test_deux_requetes_SIMULTANEES_comptent_deux(self) -> None:
        relache, prete1, prete2 = threading.Event(), threading.Event(), threading.Event()
        fils = [self._requete_voisine(relache, p) for p in (prete1, prete2)]
        try:
            self.assertEqual(portees_ouvertes(self.db), 2)
        finally:
            relache.set()
            for f in fils:
                f.join(5)

        self.assertEqual(portees_ouvertes(self.db), 0)


if __name__ == "__main__":
    unittest.main()
