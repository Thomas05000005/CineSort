"""Un run entier partage UNE connexion — et cela compose avec les gardes du wipe.

OU VIVENT LES 60 003 CONNEXIONS. Un scan a froid de 10 000 films les ouvre, et
23 % de son temps y passe. Le job ne traverse PAS le dispatch REST : la portee
posee la ne le couvrait donc pas.

MESURE, A/B A BRAS ALTERNES, TROIS TOURS CHACUN, sur un job de 400 acces base :

    SANS portee : mediane 508,8 ms | 407 connexions
    AVEC portee : mediane  18,2 ms |   8 connexions

Le job est SYNTHETIQUE (400 lectures pures) : le x28 est donc un MAJORANT. Un
vrai scan fait aussi des I/O fichier, du ffprobe et du TMDb, et son gain sera
plus faible — la reference honnete reste le x8,2 mesure sur un scan reel. La
grandeur robuste, elle, est le compte : 407 -> 8.

LE POINT DELICAT N'EST PAS LA VITESSE, C'EST LA DUREE DE VIE. La connexion d'un
run vit des MINUTES, la ou celle d'une requete vit des millisecondes. Elle ne
tient AUCUNE transaction entre deux appels — chaque `_managed_conn` garde son
`with conn:` — donc elle ne bloque ni lecteur ni ecrivain. Ce qu'elle tient, c'est
un HANDLE : sous Windows, cela empeche de SUPPRIMER le fichier.

Ce fichier eprouve donc la COMPOSITION avec les gardes du wipe, pas seulement le
partage : c'est le refus « un run est actif » qui rend cette portee sure, et non
une propriete de SQLite.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.app.job_runner import JobRunner
from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir, portees_ouvertes
from cinesort.ui.api import reset_support


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cinesort_portee_run_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state_dir = self.tmp / "state"
        self.root = self.tmp / "root"
        self.state_dir.mkdir()
        self.root.mkdir()
        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()
        self.db = db_path_for_state_dir(self.state_dir)

    def _lancer(self, job_fn) -> tuple:
        runner = JobRunner(self.store)
        rid = runner.start_job(job_fn=job_fn, root=str(self.root), state_dir=str(self.state_dir), config={})
        return runner, rid

    def _attendre(self, runner, rid, secondes: float = 20.0) -> None:
        fin = time.monotonic() + secondes
        while time.monotonic() < fin:
            snap = runner.get_status(rid)
            if snap and snap.done:
                return
            time.sleep(0.01)
        self.fail("le run n'a pas termine dans le delai")


class UnRunPARTAGEUneConnexionTests(_Base):
    def test_N_acces_base_n_ouvrent_plus_N_connexions(self) -> None:
        """LE gain de cette etape. On compte les ouvertures REELLES, pas le temps
        — le temps depend de la charge, le compte ne depend que du code."""
        ouvertures = []
        vrai = type(self.store)._connect

        def compter(store_self):
            conn = vrai(store_self)
            ouvertures.append(1)
            return conn

        def job(_should_cancel, **_kwargs):
            for _ in range(50):
                with self.store._managed_conn() as conn:
                    conn.execute("SELECT 1").fetchone()
            return {}

        type(self.store)._connect = compter
        try:
            runner, rid = self._lancer(job)
            self._attendre(runner, rid)
        finally:
            type(self.store)._connect = vrai

        self.assertLessEqual(
            len(ouvertures),
            10,
            f"50 acces base ont ouvert {len(ouvertures)} connexions : la portee du run ne s'applique pas",
        )

    def test_la_portee_est_RELACHEE_a_la_fin_du_run(self) -> None:
        """Sinon un handle survivrait au run et bloquerait toute suppression
        ulterieure — sans qu'aucun garde ne le voie, le run n'etant plus actif."""

        def job(_should_cancel, **_kwargs):
            with self.store._managed_conn() as conn:
                conn.execute("SELECT 1").fetchone()
            return {}

        runner, rid = self._lancer(job)
        self._attendre(runner, rid)

        self.assertEqual(
            portees_ouvertes(self.db),
            0,
            "la connexion du run survit a son run : plus rien ne pourra supprimer la base",
        )

    def test_un_run_qui_ECHOUE_relache_aussi(self) -> None:
        """Le `finally` de la portee doit tenir meme quand le job leve."""

        def job(_should_cancel, **_kwargs):
            with self.store._managed_conn() as conn:
                conn.execute("SELECT 1").fetchone()
            raise RuntimeError("boum")

        runner, rid = self._lancer(job)
        self._attendre(runner, rid)

        self.assertEqual(portees_ouvertes(self.db), 0, "un run en echec laisse sa connexion ouverte")


class LaPorteeDuRunCOMPOSEAvecLesGardesDuWipeTests(_Base):
    """C'EST CE QUI REND CETTE ETAPE SURE, ET IL FALLAIT LE VERIFIER.

    Une connexion qui vit des minutes empeche `unlink` sous Windows. Ce n'est
    acceptable QUE parce que les deux routes destructives refusent tant qu'un run
    tourne. Si ce garde disparaissait, cette portee transformerait un refus
    explicite en `WinError 32` illisible.
    """

    def test_pendant_un_run_le_reset_est_REFUSE_et_la_base_INTACTE(self) -> None:
        demarre, relache = threading.Event(), threading.Event()

        def job(_should_cancel, **_kwargs):
            with self.store._managed_conn() as conn:
                conn.execute("SELECT 1").fetchone()
            demarre.set()
            relache.wait(20)
            return {}

        api = backend.CineSortApi()
        api.settings.save_settings({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        store_api, runner = api._get_or_create_infra(self.state_dir)
        rid = runner.start_job(job_fn=job, root=str(self.root), state_dir=str(self.state_dir), config={})
        api._runs[rid] = type("R", (), {"running": True})()
        demarre.wait(10)
        try:
            res = reset_support.reset_database(api, dry_run=False)
        finally:
            relache.set()
            api._runs.pop(rid, None)

        self.assertFalse(res.get("ok"), "la base a ete supprimee pendant un run")
        self.assertTrue(db_path_for_state_dir(self.state_dir).is_file(), "la base a disparu")
        message = str(res.get("error") or res.get("message") or "")
        self.assertNotIn("WinError", message, "un verrou de fichier est remonte au lieu du refus explicite")
        # ASSERTER CE QUE SEUL LE REFUS PRODUIT. Les deux messages possibles
        # contiennent « en cours » — celui du refus (« un traitement est en
        # cours ») et celui du repli sur le verrou de fichier (« utilisee par N
        # requete(s) en cours »). Chercher « cours » ne distinguait donc PAS quel
        # garde a joue, et la mutation l'a montre : retirer le refus laissait le
        # test vert, l'echec venant alors du verrou.
        self.assertIn(
            "arretez-le",
            message.lower().replace("ê", "e").replace("é", "e"),
            f"ce n'est pas le refus « run actif » qui a joue, mais le verrou de fichier : {message}",
        )
        self.assertIn(rid, message, "le refus ne nomme pas le run qui bloque")


if __name__ == "__main__":
    unittest.main()
