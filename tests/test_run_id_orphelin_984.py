"""Un `run_id` dont il reste des lignes enfants ne doit pas etre declare LIBRE.

LE DEFAUT (#984). La decision N26 fait DELIBEREMENT survivre les lignes
orphelines a l'auto-reparation du schema : elles preservent le journal
d'erreurs. Ce choix est bon et n'est pas remis en cause ici.

Mais trois lecteurs ne l'avaient pas integre :

1. `job_runner.start_job` verifiait l'unicite du `run_id` avec `get_run()`, qui
   ne consulte QUE `runs`. Un `run_id` fantome etait donc declare libre, et le
   run suivant HERITAIT du journal d'erreurs du run mort.
2. `delete_run` COMPTAIT les enfants avant de supprimer le parent, en pariant
   sur la CASCADE — laquelle ne se declenche pas s'il n'y a pas de parent. Il
   rendait 1 en ayant supprime 0 ligne.
3. Le KPI « Erreurs » attribuait au nouveau run les erreurs du run mort. Ce
   troisieme point disparait des que le premier est corrige : un `run_id` qui
   n'est plus jamais reutilise ne peut plus rien faire heriter.

CE QUE LA MESURE A APPRIS. **12 tables portent un `run_id`, mais SEULES TROIS
ont une cle etrangere vers `runs`** (`errors`, `quality_reports`, `anomalies`).
La cascade ne couvre donc qu'un quart du probleme, et n'importe laquelle des
autres peut orpheliner un `run_id` sans qu'aucune contrainte ne s'en apercoive.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.repositories.run import RunRepository
from cinesort.infra.db.sqlite_store import SQLiteStore


class _BaseReelle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_984_"))
        self.store = SQLiteStore(db_path=self._tmp / "cinesort.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self.store.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _orpheline(self, run_id: str = "GHOST") -> None:
        """Reproduit l'etat d'apres self-heal : une ligne `errors` SANS parent.

        On insere sous `foreign_keys = OFF`, exactement comme le fait
        l'auto-reparation du schema — c'est ce chemin qui produit l'orpheline.
        """
        with self.store._managed_conn() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES(?,?,?,?,?)",
                (run_id, 1.0, "probe", "TIMEOUT", "probe timeout"),
            )


class UnRunIdOrphelinEstPRISTests(_BaseReelle):
    def test_get_run_ne_voit_PAS_l_orpheline(self) -> None:
        """Le fait de depart, et il est normal : `get_run` interroge `runs`."""
        self._orpheline()

        self.assertIsNone(self.store.run.get_run("GHOST"))

    def test_run_id_est_utilise_LA_voit(self) -> None:
        """Le coeur du correctif."""
        self._orpheline()

        self.assertTrue(
            self.store.run.run_id_est_utilise("GHOST"),
            "un run_id dont il reste un journal d'erreurs est declare LIBRE : le prochain run heritera de ce journal",
        )

    def test_un_run_id_JAMAIS_utilise_reste_libre(self) -> None:
        """Contre-epreuve : sans elle, une methode qui rendrait toujours True
        passerait — et bloquerait tout demarrage de run."""
        self.assertFalse(self.store.run.run_id_est_utilise("JAMAIS-VU"))

    def test_un_run_id_vide_n_est_pas_considere_pris(self) -> None:
        self.assertFalse(self.store.run.run_id_est_utilise(""))
        self.assertFalse(self.store.run.run_id_est_utilise("   "))

    def test_une_orpheline_dans_une_table_SANS_cle_etrangere_compte_aussi(self) -> None:
        """9 des 12 tables porteuses n'ont AUCUNE cle etrangere vers `runs` :
        elles orphelinent sans que rien ne s'en apercoive."""
        with self.store._managed_conn() as conn:
            conn.execute(
                "INSERT INTO perceptual_reports(run_id, row_id, visual_score, audio_score,"
                " global_score, global_tier, metrics_json, settings_json, ts)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                ("FANTOME2", "r1", 1.0, 1.0, 1.0, "gold", "{}", "{}", 1.0),
            )

        self.assertTrue(self.store.run.run_id_est_utilise("FANTOME2"))


class LaListeDeTablesNePeutPasSePERIMERTests(_BaseReelle):
    """Contrat : la liste codee en dur doit rester alignee sur le schema reel.

    Sans ce test, une migration future ajoutant une table porteuse de `run_id`
    rouvrirait le defaut en silence — exactement la facon dont il est ne.
    """

    def test_toutes_les_tables_portant_un_run_id_sont_INSCRITES(self) -> None:
        with self.store._managed_conn() as conn:
            noms = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            porteuses = set()
            for nom in noms:
                colonnes = [r[1] for r in conn.execute(f"PRAGMA table_info({nom})")]  # noqa: S608
                if "run_id" in colonnes:
                    porteuses.add(nom)
        porteuses.discard("runs")  # le parent lui-meme, interroge separement

        manquantes = sorted(porteuses - set(RunRepository._TABLES_PORTANT_RUN_ID))
        self.assertEqual(
            manquantes,
            [],
            f"ces tables portent un run_id sans etre inscrites dans "
            f"`_TABLES_PORTANT_RUN_ID` : {manquantes}. Une orpheline y rendrait "
            f"le run_id LIBRE, et le prochain run heriterait de ses lignes.",
        )

    def test_aucune_table_INSCRITE_n_a_disparu(self) -> None:
        """L'autre sens : une entree perimee ferait echouer une requete a chaque
        demarrage de run (elle est toleree, mais autant le savoir)."""
        with self.store._managed_conn() as conn:
            existantes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        fantomes = sorted(set(RunRepository._TABLES_PORTANT_RUN_ID) - existantes)
        self.assertEqual(fantomes, [], f"entrees perimees : {fantomes}")


class DeleteRunDitLaVERITETests(_BaseReelle):
    def test_sur_un_run_FANTOME_il_supprime_vraiment_et_compte_juste(self) -> None:
        """Avant : rendait 1 en ayant supprime 0 ligne, et l'orpheline restait."""
        self._orpheline()

        supprimes = self.store.run.delete_run("GHOST")

        with self.store._managed_conn() as conn:
            restantes = conn.execute("SELECT COUNT(*) FROM errors WHERE run_id=?", ("GHOST",)).fetchone()[0]
        self.assertEqual(restantes, 0, "l'orpheline SURVIT a sa suppression explicite")
        self.assertEqual(supprimes, 1, f"le compte est faux : {supprimes}")

    def test_apres_suppression_le_run_id_redevient_LIBRE(self) -> None:
        """La boucle se ferme : nettoyer doit reellement liberer l'identifiant."""
        self._orpheline()
        self.assertTrue(self.store.run.run_id_est_utilise("GHOST"))

        self.store.run.delete_run("GHOST")

        self.assertFalse(self.store.run.run_id_est_utilise("GHOST"))

    def test_un_run_INEXISTANT_et_sans_enfant_rend_zero(self) -> None:
        """Contre-epreuve : le compte ne doit pas devenir optimiste."""
        self.assertEqual(self.store.run.delete_run("RIEN-DU-TOUT"), 0)

    def test_un_run_REEL_avec_ses_enfants_est_compte_correctement(self) -> None:
        """Non-regression du cas nominal : parent + 2 enfants = 3."""
        self.store.run.insert_run_pending(run_id="VRAI", root="D:/Films", state_dir=str(self._tmp), config={})
        with self.store._managed_conn() as conn:
            for i in range(2):
                conn.execute(
                    "INSERT INTO errors(run_id, ts, step, code, message) VALUES(?,?,?,?,?)",
                    ("VRAI", 1.0, "probe", "BOOM", f"boom {i}"),
                )

        self.assertEqual(self.store.run.delete_run("VRAI"), 3)


if __name__ == "__main__":
    unittest.main()
