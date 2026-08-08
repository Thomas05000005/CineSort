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


class LaSYMETRIEEntreReserverEtLibererTests(_BaseReelle):
    """Toute table qui RESERVE un run_id doit etre purgee par sa suppression.

    CE BLOC EXISTE PARCE QUE J'AI CREE L'ASYMETRIE. La garde consultait onze
    tables pendant que `delete_run` n'en purgeait que trois : une orpheline dans
    l'une des huit autres survivait a la suppression, et le run_id restait
    occupe POUR TOUJOURS.

    Le premier test de nettoyage ne le voyait pas — il n'utilisait que `errors`,
    qui etait justement l'une des trois purgees. Un test qui n'eprouve qu'un cas
    favorable ne prouve rien de la regle.
    """

    def _semer(self, table: str, run_id: str) -> bool:
        """Insere une ligne minimale dans `table`. Rend False si le schema
        exige des colonnes qu'on ne sait pas fabriquer ici."""
        with self.store._managed_conn() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            colonnes = [(r[1], r[2], r[3]) for r in conn.execute(f"PRAGMA table_info({table})")]
            noms, valeurs = [], []
            for nom, typ, non_nul in colonnes:
                if nom == "run_id":
                    noms.append(nom)
                    valeurs.append(run_id)
                elif non_nul:
                    noms.append(nom)
                    valeurs.append(0 if "INT" in (typ or "").upper() or "REAL" in (typ or "").upper() else "x")
            try:
                conn.execute(
                    f"INSERT INTO {table}({', '.join(noms)}) VALUES({', '.join('?' * len(noms))})",
                    tuple(valeurs),
                )
            except Exception:
                return False
        return True

    #: Tables que `_semer` ne sait pas remplir (schema exigeant des valeurs
    #: qu'on ne peut pas fabriquer generiquement). Elles sont NOMMEES pour que le
    #: saut soit visible : un test qui saute en silence ne prouve rien, et c'est
    #: ainsi que des batteries entieres se vident sans qu'on le sache.
    _NON_SEMABLES = ("film_decisions_v2",)

    def test_chaque_table_qui_RESERVE_est_aussi_PURGEE(self) -> None:
        non_liberees, sautees = [], []
        for table in RunRepository._TABLES_PORTANT_RUN_ID:
            rid = f"SYM-{table}"
            if not self._semer(table, rid):
                sautees.append(table)
                continue
            self.assertTrue(
                self.store.run.run_id_est_utilise(rid),
                f"{table} ne reserve meme pas le run_id — la garde ne la voit pas",
            )
            self.store.run.delete_run(rid)
            if self.store.run.run_id_est_utilise(rid):
                non_liberees.append(table)

        self.assertEqual(
            non_liberees,
            [],
            f"ces tables RESERVENT un run_id que `delete_run` ne libere PAS : {non_liberees}. "
            f"L'identifiant reste occupe pour toujours.",
        )
        # Le saut doit rester BORNE et connu : sans cette assertion, un schema
        # qui rendrait plus de tables non semables viderait ce test en silence.
        self.assertEqual(
            sorted(sautees),
            sorted(self._NON_SEMABLES),
            f"la couverture de ce test a change : sautees={sorted(sautees)}. "
            f"Mettre a jour `_NON_SEMABLES` — ou mieux, apprendre a les semer.",
        )


if __name__ == "__main__":
    unittest.main()
