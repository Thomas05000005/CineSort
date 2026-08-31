"""LOT 3 — INTEGRITE BASE : trois defauts mesures dans `cinesort/infra/db/`.

A. `apply_batch_modes` n'est purgee par RIEN (repositories/run.py, delete_run).
   La table est creee par la migration 029 SANS cle etrangere vers
   `apply_batches` — choix documente et delibere (029:15-19). Mais `delete_run`
   ne la cite dans AUCUNE de ses deux listes : ni `_TABLES_PORTANT_RUN_ID`
   (elle n'a pas de colonne `run_id`, donc l'invariant de symetrie du #984 ne
   la voit pas), ni la purge dediee `apply_batches`. Ses lignes survivent donc
   POUR TOUJOURS a la suppression de leur run.

   Ce n'est pas qu'une fuite d'espace : `_list_inprogress_rollbacks`
   (app/apply_batches_reconciliation.py:132) lit cette table A CHAQUE BOOT et
   relance `rollback_forward` sur tout batch `IN_PROGRESS`. Une ligne orpheline
   y reste eligible a vie, alors que son batch et ses operations n'existent
   plus — le boot repart en reconciliation sur du vide, indefiniment.

C. `clear_all_incremental_caches` (repositories/scan.py:56) avale TOUTE
   `sqlite3.OperationalError`, pas seulement le « no such table » que son
   commentaire invoque. Un « database is locked » fait donc rendre 0 la ligne
   concernee, et le rapport de purge annonce un succes partiel MENSONGER.

D. Migration 021, filtre `WHERE EXISTS` des sections 2 et 3 : le constat
   « non idempotent au rejeu » est REFUTE par la mesure. Rejouer le SQL
   ENTIER sur une base deja migree est un no-op strict (voir la classe dediee).
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from cinesort.app.apply_batches_reconciliation import _list_inprogress_rollbacks
from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.sqlite_store import SQLiteStore
from tests._helpers import cleanup_test_tree

# Resolu depuis `__file__` et NON depuis le repertoire courant : un chemin
# relatif ferait dependre la lecture de la migration de l'endroit d'ou pytest
# est lance, et le fichier introuvable rendrait un echec qui accuse la migration.
_MIG_DIR = Path(__file__).resolve().parents[1] / "cinesort" / "infra" / "db" / "migrations"


class _BaseReelle(unittest.TestCase):
    """Base SQLite reelle, migree jusqu'a la derniere version."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_lot3_"))
        self.store = SQLiteStore(db_path=self._tmp / "cinesort.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self.store.close()
        # `shutil.rmtree(..., ignore_errors=True)` AVALE l'echec : sous Windows,
        # un handle SQLite encore ouvert empeche la suppression, et le dossier
        # reste dans %TEMP% sans qu'aucune erreur ne le dise. Mesure en CI :
        # 4 dossiers `cinesort_lot3_*` laisses, portant la session de 9 a 13
        # pour une borne de 12 — c'est `tests/_temp_leak_guard.py` qui l'a dit.
        # `cleanup_test_tree` joint les threads de fond puis reessaie.
        cleanup_test_tree(self._tmp)

    def _run_avec_batch(self, run_id: str, batch_id: str, *, rollback_status: str = "NONE") -> None:
        """Cree un run, un batch qui lui appartient, et son mode atomique."""
        self.store.run.insert_run_pending(
            run_id=run_id,
            root="D:/Films",
            state_dir=str(self._tmp),
            config={},
        )
        self.store.apply.insert_apply_batch(
            run_id=run_id,
            dry_run=False,
            quarantine_unapproved=False,
            status="DONE",
            batch_id=batch_id,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)
        if rollback_status != "NONE":
            self.store.apply.mark_rollback_status(batch_id, rollback_status)


class ApplyBatchModesEstPurgeeAvecSonRunTests(_BaseReelle):
    """DEFAUT A. Le mode atomique d'un batch ne survit pas a son run."""

    def test_la_ligne_de_mode_NE_SURVIT_PAS_a_delete_run(self) -> None:
        self._run_avec_batch("R-MODE", "B-MODE")
        self.assertIsNotNone(self.store.apply.get_atomic_mode("B-MODE"))

        self.store.run.delete_run("R-MODE")

        self.assertIsNone(
            self.store.apply.get_atomic_mode("B-MODE"),
            "la ligne `apply_batch_modes` survit a la suppression de son run : "
            "son batch n'existe plus, rien ne la purgera jamais",
        )

    def test_elle_est_COMPTEE_dans_le_retour_de_delete_run(self) -> None:
        """Le #984 a impose que `delete_run` ne rende plus une promesse mais un
        compte reel. Purger sans compter reintroduirait l'ecart inverse."""
        self._run_avec_batch("R-CPT", "B-CPT")

        # run + apply_batches + apply_batch_modes = 3
        self.assertEqual(
            self.store.run.delete_run("R-CPT"),
            3,
            "le compte rendu ne reflete pas la ligne `apply_batch_modes` supprimee",
        )

    def test_le_boot_NE_RELANCE_PLUS_un_rollback_sur_un_batch_disparu(self) -> None:
        """La consequence reelle, pas seulement la ligne restante.

        `_list_inprogress_rollbacks` est lu a CHAQUE boot et declenche
        `rollback_forward` sur chaque batch rendu. Une orpheline y reste
        eligible a vie.
        """
        self._run_avec_batch("R-BOOT", "B-BOOT", rollback_status="IN_PROGRESS")
        self.assertEqual(_list_inprogress_rollbacks(self.store), ["B-BOOT"])

        self.store.run.delete_run("R-BOOT")

        self.assertEqual(
            _list_inprogress_rollbacks(self.store),
            [],
            "le boot repartira en reconciliation sur un batch qui n'existe plus, a chaque demarrage",
        )

    def test_le_mode_d_un_AUTRE_run_est_INTACT(self) -> None:
        """Contre-epreuve : une purge qui viderait la table entiere passerait
        les trois tests ci-dessus."""
        self._run_avec_batch("R-A", "B-A")
        self._run_avec_batch("R-B", "B-B")

        self.store.run.delete_run("R-A")

        self.assertIsNone(self.store.apply.get_atomic_mode("B-A"))
        self.assertIsNotNone(
            self.store.apply.get_atomic_mode("B-B"),
            "la purge a emporte le mode atomique d'un run qui n'etait pas vise",
        )

    def test_le_JOURNAL_WRITE_AHEAD_n_est_PAS_purge(self) -> None:
        """Garde anti-sur-correction, meme taxonomie que 021 sections 1 et 4.

        `apply_pending_moves` porte aussi un `batch_id` sans cle etrangere, mais
        ce n'est pas une metadonnee de batch : c'est le journal write-ahead des
        deplacements DEJA FAITS SUR DISQUE (019:1-7), relu au boot par
        `move_reconciliation`. Le purger avec le run detruirait la trace d'une
        action irreversible.
        """
        self._run_avec_batch("R-WAL", "B-WAL")
        pending_id = self.store.apply.insert_pending_move(
            batch_id="B-WAL",
            op_type="MOVE_FILE",
            src_path="D:/Films/a.mkv",
            dst_path="D:/Films/Trie/a.mkv",
        )
        self.assertIsNotNone(pending_id)

        self.store.run.delete_run("R-WAL")

        with self.store._managed_conn() as conn:
            restantes = conn.execute(
                "SELECT COUNT(*) FROM apply_pending_moves WHERE batch_id=?", ("B-WAL",)
            ).fetchone()[0]
        self.assertEqual(
            restantes,
            1,
            "le journal write-ahead a ete ampute : ces lignes tracent des deplacements deja faits sur disque",
        )


class CountV2TierSinceNeScanNePlusToutTests(_BaseReelle):
    """DEFAUT B — CONFIRME sur le fond, REFUTE sur la cause, et le remede
    « evident » est une REGRESSION MESUREE.

    LE FAIT. `count_v2_tier_since` filtre `global_tier_v2` et `ts`, deux
    colonnes sans index : `EXPLAIN QUERY PLAN` rend `SCAN perceptual_reports`.
    Trois appels par chargement du tableau de bord (dashboard_support.py:1900,
    quality_audit_support.py:266-267).

    LA CAUSE ANNONCEE EST FAUSSE. L'index supprime par
    `022_drop_redundant_indexes.sql:29` etait `idx_perceptual_reports_run ON
    perceptual_reports(run_id)` — une seule colonne, `run_id`, redondante avec
    le prefixe gauche de la PK `(run_id, row_id)`. Il n'aurait JAMAIS servi ce
    filtre. Mieux : `global_tier_v2` n'existait meme pas quand cet index a ete
    cree (009) — la colonne est ajoutee par l'`ALTER` de la 018. La 022 n'a donc
    rien retire qui aurait aide ici ; il n'y a jamais eu d'index a remplacer.

    LE REMEDE EVIDENT EST NUISIBLE. MESURE, 200 000 lignes, distribution
    desequilibree realiste, ms/appel :

        tier (lignes rendues)   aucun index   (tier, ts)   (tier, ts, row_id)
        platinum   (  2 006)       26,6          10,5            1,1
        gold       ( 40 159)       58,2         241,3           37,5
        silver     ( 38 037)       57,1         234,3           44,5
        bronze     ( 15 108)       36,4          79,1           16,6
        reject     (  4 940)       28,3          24,6            4,9

    L'index a DEUX colonnes rend la requete 4x PLUS LENTE sur les tiers
    frequents : le compte porte sur `COUNT(DISTINCT row_id)`, absent de l'index,
    donc SQLite paie une remontee de ligne par entree trouvee — 40 000 acces
    aleatoires valent plus cher qu'un parcours sequentiel de 200 000. Il ne
    gagne que sur le tier RARE. Un index calibre sur le seul appel qu'on a en
    tete aurait donc degrade les deux appels les plus lourds.

    Seul l'index COUVRANT (`row_id` en 3e position) gagne PARTOUT : x25 sur
    platinum, x5,8 sur reject, x1,3 a x2,2 sur les tiers de masse. Cout : le
    fichier passe de 17,6 a 24,2 Mo (+37 %) sur ces 200 000 lignes.
    """

    def _sql_de_production(self) -> str:
        """Rend le SQL REELLEMENT execute par `count_v2_tier_since`.

        On ne recopie pas la requete dans le test : une copie derive, et le
        test finirait par mesurer un plan qui n'est plus celui du produit.
        """
        captures: list[str] = []
        vrai_managed_conn = self.store.perceptual._managed_conn

        class _ConnQuiEcoute:
            def __init__(self, conn: Any) -> None:
                self._conn = conn

            def execute(self, sql: Any, *args: Any, **kwargs: Any) -> Any:
                if isinstance(sql, str) and "global_tier_v2" in sql:
                    captures.append(sql)
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, nom: str) -> Any:
                return getattr(self._conn, nom)

        @contextmanager
        def faux_managed_conn() -> Any:
            with vrai_managed_conn() as conn:
                yield _ConnQuiEcoute(conn)

        with mock.patch.object(self.store.perceptual, "_managed_conn", faux_managed_conn):
            self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=0.0)
        self.assertEqual(len(captures), 1, f"SQL non capture : {captures}")
        return captures[0]

    def _plan(self, sql: str, params: tuple) -> str:
        with self.store._managed_conn() as conn:
            return " | ".join(str(r[3]) for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))

    def _semer(self, n: int = 200) -> None:
        tiers = ("platinum", "gold", "silver", "bronze", "reject")
        with self.store._managed_conn() as conn:
            conn.executemany(
                "INSERT INTO perceptual_reports(run_id,row_id,visual_score,audio_score,global_score,"
                "global_tier,metrics_json,settings_json,ts,global_score_v2,global_tier_v2)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (f"R{i % 7}", f"row{i}", 50, 50, 50, "gold", "{}", "{}", 1000.0 + i, 50.0, tiers[i % 5])
                    for i in range(n)
                ],
            )

    def test_le_plan_n_est_plus_un_SCAN_de_toute_la_table(self) -> None:
        self._semer()

        plan = self._plan(self._sql_de_production(), ("reject", 0.0))

        self.assertNotIn(
            "SCAN perceptual_reports",
            plan,
            f"la requete parcourt encore toute la table : {plan}",
        )

    def test_l_index_est_COUVRANT_car_un_index_a_deux_colonnes_est_une_REGRESSION(self) -> None:
        """L'assertion qui compte. Un index `(global_tier_v2, ts)` ferait aussi
        disparaitre le `SCAN` du test precedent — tout en rendant la requete 4x
        plus lente sur les tiers de masse (mesure dans la docstring de classe).
        Seul le mot `COVERING` separe le remede de la regression."""
        self._semer()

        plan = self._plan(self._sql_de_production(), ("reject", 0.0))

        self.assertIn(
            "COVERING INDEX",
            plan,
            f"l'index ne couvre pas `row_id` : chaque entree trouvee coutera une remontee de ligne. Plan : {plan}",
        )

    def test_l_EGALITE_sur_le_tier_est_un_terme_de_RECHERCHE(self) -> None:
        """AJOUTE APRES QU'UN MUTANT A SURVECU, et c'est tout son interet.

        L'assertion `COVERING INDEX` ci-dessus ne voit PAS l'ordre des colonnes.
        Un index `(ts, global_tier_v2, row_id)` reste couvrant — SQLite parcourt
        l'intervalle de `ts` dans l'index et filtre le tier au passage — et le
        plan porte toujours le mot `COVERING`. Le mutant passait donc.

        Il est pourtant une regression MESUREE (200 000 lignes, ms/appel) :

            tier       (tier, ts, row_id)   (ts, tier, row_id)
            platinum          1,2                 13,8
            gold             46,3                 63,4
            silver           43,4                 56,6
            bronze           16,0                 27,8
            reject            4,8                 15,7

        Un predicat d'EGALITE place apres un predicat d'INTERVALLE cesse d'etre
        un terme de recherche : SQLite ne peut plus sauter directement au groupe
        du tier. Le plan le dit, et c'est la seule chose qui les separe —
        `(global_tier_v2=? AND ts>?)` contre `(ts>?)` tout court.
        """
        self._semer()

        plan = self._plan(self._sql_de_production(), ("reject", 0.0))

        self.assertIn(
            "global_tier_v2=?",
            plan,
            f"l'egalite sur le tier n'est pas un terme de recherche de l'index — elle est "
            f"probablement placee APRES l'intervalle sur `ts`. Plan : {plan}",
        )

    def test_la_variante_avec_until_ts_est_couverte_AUSSI(self) -> None:
        """Le second appelant (`quality_audit_support`) ajoute `AND ts < ?`."""
        self._semer()
        captures: list[str] = []
        vrai_managed_conn = self.store.perceptual._managed_conn

        class _ConnQuiEcoute:
            def __init__(self, conn: Any) -> None:
                self._conn = conn

            def execute(self, sql: Any, *args: Any, **kwargs: Any) -> Any:
                if isinstance(sql, str) and "global_tier_v2" in sql:
                    captures.append(sql)
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, nom: str) -> Any:
                return getattr(self._conn, nom)

        @contextmanager
        def faux_managed_conn() -> Any:
            with vrai_managed_conn() as conn:
                yield _ConnQuiEcoute(conn)

        with mock.patch.object(self.store.perceptual, "_managed_conn", faux_managed_conn):
            self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=0.0, until_ts=9e9)

        plan = self._plan(captures[0], ("reject", 0.0, 9e9))
        self.assertIn("COVERING INDEX", plan, f"variante bornee non couverte : {plan}")

    def test_le_RESULTAT_est_inchange(self) -> None:
        """Contre-epreuve : un index qui accelererait en changeant le compte
        serait la pire des corrections."""
        self._semer(n=200)

        # 200 lignes, 5 tiers alternes -> 40 par tier, `row_id` tous distincts
        self.assertEqual(self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=0.0), 40)
        self.assertEqual(self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=1100.0), 20)
        self.assertEqual(
            self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=0.0, until_ts=1100.0),
            20,
        )
        self.assertEqual(self.store.perceptual.count_v2_tier_since(tier="inexistant", since_ts=0.0), 0)

    def test_le_COUNT_DISTINCT_dedoublonne_toujours(self) -> None:
        """Un meme film re-scane (2 runs, meme `row_id`) compte pour UN."""
        with self.store._managed_conn() as conn:
            for run in ("RA", "RB"):
                conn.execute(
                    "INSERT INTO perceptual_reports(run_id,row_id,visual_score,audio_score,global_score,"
                    "global_tier,metrics_json,settings_json,ts,global_tier_v2)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (run, "MEME-FILM", 50, 50, 50, "gold", "{}", "{}", 5000.0, "reject"),
                )

        self.assertEqual(self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=0.0), 1)


class ClearAllIncrementalCachesNeMENT_PasTests(_BaseReelle):
    """DEFAUT C. Une base verrouillee ne doit pas passer pour une purge reussie."""

    def _forcer_erreur(self, message: str) -> Any:
        """Fait echouer le seul DELETE de `incremental_row_cache` avec `message`.

        `sqlite3.Connection` est un type immuable : on ne peut pas patcher son
        `execute`. On interpose donc un proxy entre le repository et la vraie
        connexion — les autres tables sont purgees pour de bon, ce qui rend le
        rapport comparable au cas nominal.
        """
        vrai_managed_conn = self.store.scan._managed_conn

        class _ConnQuiEchoue:
            def __init__(self, conn: Any) -> None:
                self._conn = conn

            def execute(self, sql: Any, *args: Any, **kwargs: Any) -> Any:
                if isinstance(sql, str) and sql.strip().upper().startswith("DELETE FROM INCREMENTAL_ROW_CACHE"):
                    raise sqlite3.OperationalError(message)
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, nom: str) -> Any:
                return getattr(self._conn, nom)

        @contextmanager
        def faux_managed_conn() -> Any:
            with vrai_managed_conn() as conn:
                yield _ConnQuiEchoue(conn)

        return mock.patch.object(self.store.scan, "_managed_conn", faux_managed_conn)

    def test_un_verrou_de_base_REMONTE_au_lieu_de_rendre_zero(self) -> None:
        with self._forcer_erreur("database is locked"), self.assertRaises(sqlite3.OperationalError) as ctx:
            self.store.scan.clear_all_incremental_caches()

        self.assertIn("database is locked", str(ctx.exception))

    def test_une_table_ABSENTE_reste_toleree(self) -> None:
        """Contre-epreuve : la tolerance annoncee par le commentaire doit vivre."""
        with self._forcer_erreur("no such table: incremental_row_cache"):
            rapport = self.store.scan.clear_all_incremental_caches()

        self.assertEqual(rapport["row_cache"], 0)
        self.assertIn("folder_cache", rapport)
        self.assertIn("file_hashes", rapport)

    def test_le_cas_NOMINAL_purge_et_compte(self) -> None:
        """Sans lui, une methode qui leverait toujours passerait le premier test."""
        self.store.scan.upsert_incremental_row_cache(
            root_path="D:/Films",
            video_path="D:/Films/Un Film (2020)/film.mkv",
            video_size=1,
            video_mtime_ns=1,
            video_hash="h",
            folder_path="D:/Films/Un Film (2020)",
            nfo_sig=None,
            cfg_sig="c",
            kind="movie",
            row_json={"row_id": "r1"},
            run_id="R-CACHE",
        )

        rapport = self.store.scan.clear_all_incremental_caches()

        self.assertEqual(rapport["row_cache"], 1, f"purge incomplete : {rapport}")


class Migration021LeFiltreEstIdempotentTests(unittest.TestCase):
    """DEFAUT D — REFUTE PAR LA MESURE.

    Le constat annoncait que le filtre `WHERE EXISTS` des sections 2 et 3 de
    `021_fk_cascade.sql` ne serait pas idempotent au rejeu. On rejoue ici le
    fichier SQL ENTIER — pas via `MigrationManager.apply`, qui le sauterait sur
    `user_version >= 21` — sur une base deja migree et peuplee. C'est le chemin
    reel de `SQLiteStore._bootstrap_schema_latest`, qui concatene TOUTES les
    migrations a chaque auto-reparation.

    MESURE : les quatre tables reconstruites gardent exactement leurs lignes.
    `f(f(x)) == f(x)`, le filtre EST idempotent.

    Ce qu'il fait — et que le constat confondait avec une non-idempotence —
    c'est supprimer les orphelines APPARUES ENTRE deux rejeux. Ce n'est pas un
    defaut : c'est le comportement documente en 021:133-135 et justifie en
    021:226-228 (les sorties recalculables sont filtrees, le journal d'undo et
    le journal d'erreurs ne le sont pas). Le test le pin egalement, pour que
    « corriger » cette section rougisse.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_lot3_021_"))
        self.db_path = self._tmp / "t.db"
        store = SQLiteStore(db_path=self.db_path)
        store.initialize()
        store.close()
        self._peupler()

    def tearDown(self) -> None:
        # Meme raison que la classe ci-dessus : `_peupler` ouvre la base par
        # `sqlite3.connect`, et le fichier peut rester verrouille un instant
        # apres la fermeture du `with`.
        cleanup_test_tree(self._tmp)

    def _peupler(self) -> None:
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json)"
                " VALUES('R1','DONE',1.0,'D:/f','s','{}')"
            )
            for i in range(3):
                conn.execute(
                    "INSERT INTO errors(run_id, ts, step, code, message) VALUES('R1',1.0,'p','C',?)",
                    (f"m{i}",),
                )
                conn.execute(
                    "INSERT INTO quality_reports(run_id,row_id,score,tier,reasons_json,metrics_json,"
                    "profile_id,profile_version,ts) VALUES('R1',?,1,'gold','[]','{}','p',1,1.0)",
                    (f"row{i}",),
                )
                conn.execute(
                    "INSERT INTO anomalies(run_id,row_id,severity,code,message,ts) VALUES('R1',?,'warn','C','m',1.0)",
                    (f"row{i}",),
                )
            conn.execute(
                "INSERT INTO apply_batches(batch_id,run_id,started_ts,status,dry_run,"
                "quarantine_unapproved,summary_json,app_version) VALUES('B1','R1',1.0,'DONE',0,0,'{}','x')"
            )
            conn.execute(
                "INSERT INTO apply_operations(batch_id,op_index,op_type,src_path,dst_path,reversible,ts)"
                " VALUES('B1',0,'MOVE','a','b',1,1.0)"
            )

    def _rejouer_021(self) -> None:
        sql = (_MIG_DIR / "021_fk_cascade.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN")
            for stmt in _split_sql_statements(sql):
                conn.execute(stmt)
            conn.commit()

    def _compter(self) -> dict[str, int]:
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
                for table in ("runs", "errors", "quality_reports", "anomalies", "apply_batches", "apply_operations")
            }

    def test_rejouer_le_SQL_entier_ne_change_AUCUNE_ligne(self) -> None:
        avant = self._compter()
        self.assertEqual(avant["quality_reports"], 3)

        self._rejouer_021()
        apres_1 = self._compter()
        self._rejouer_021()
        apres_2 = self._compter()

        self.assertEqual(apres_1, avant, f"le 1er rejeu a change les lignes : {avant} -> {apres_1}")
        self.assertEqual(apres_2, apres_1, f"le 2e rejeu a change les lignes : {apres_1} -> {apres_2}")

    def test_une_orpheline_APPARUE_entre_deux_rejeux_est_bien_filtree(self) -> None:
        """Le comportement voulu, pas le defaut annonce — et il doit rester vrai."""
        self._rejouer_021()
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO quality_reports(run_id,row_id,score,tier,reasons_json,metrics_json,"
                "profile_id,profile_version,ts) VALUES('GHOST','g1',1,'gold','[]','{}','p',1,1.0)"
            )
        self.assertEqual(self._compter()["quality_reports"], 4)

        self._rejouer_021()

        self.assertEqual(
            self._compter()["quality_reports"],
            3,
            "l'orpheline recalculable a survecu : plus aucun chemin de nettoyage ne l'atteindra",
        )

    def test_le_journal_d_UNDO_orphelin_survit_au_rejeu(self) -> None:
        """L'autre moitie de la regle : ce qui trace une action irreversible reste."""
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO apply_operations(batch_id,op_index,op_type,src_path,dst_path,reversible,ts)"
                " VALUES('B-DISPARU',0,'MOVE','c','d',1,1.0)"
            )

        self._rejouer_021()

        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            restantes = int(
                conn.execute("SELECT COUNT(*) FROM apply_operations WHERE batch_id='B-DISPARU'").fetchone()[0]
            )
        self.assertEqual(restantes, 1, "le journal d'undo a ete ampute au rejeu")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
