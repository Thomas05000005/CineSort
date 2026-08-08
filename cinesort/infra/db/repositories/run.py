"""RunRepository : runs + errors (issue #85 phase B6).

Migration #85 phase B6 (2026-05-16) : meme pattern que B1-B5 :
- Code metier vit DANS RunRepository
- B8 CLOSE (2026-05, commit 482f3e6) : _RunMixin et l'heritage MRO supprimes
- SQLiteStore expose store.run (heritage MRO supprime en B8)

Note specifique B6 : `insert_run_pending` appelle `initialize()` en fallback
si la table runs n'existe pas. Dans RunRepository (_BaseRepository compose),
on appelle `self._store.initialize()` pour deleguer au SQLiteStore parent.

Methodes exposees :
    insert_run_pending, mark_run_running, update_run_progress,
    mark_cancel_requested, mark_run_done, mark_run_cancelled,
    mark_run_failed, insert_error, get_run, list_errors, get_latest_run,
    list_runs, get_runs_summary, get_error_counts_for_runs
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository
from cinesort.infra.db.repositories._sql import SQL_CHUNK, chunked

# AUDIT 2026-07-13 (HIGH-8) : predicat partage pour EXCLURE les runs utilitaires
# de bulk re-scan (library_actions_support.rescan_rows_bulk pose un marqueur
# config_json {"rescan_run_id": ...}). Ces runs de tracking n'ont ni plan.jsonl
# ni quality reports ; les resoudre comme "dernier run" ecroulait a 0 les KPI
# Accueil + badges sidebar apres un re-scan groupe. Meme exclusion que
# library_support._resolve_run_id (les deux surfaces convergent sur le run de SCAN).
_NOT_RESCAN_TRACKING_SQL = "COALESCE(config_json, '') NOT LIKE '%\"rescan_run_id\"%'"

# Marqueurs SQLite d'une violation de la PRIMARY KEY `runs.run_id`.
_RUN_ID_CONFLICT_MARKERS = ("runs.run_id",)


class RunIdConflictError(sqlite3.IntegrityError):
    """Le `run_id` demande existe deja dans `runs` : AUCUNE ligne n'a ete creee.

    Arbitrage explicite (defense en profondeur) : le repository ECHOUE FORT, il
    ne re-genere PAS d'identifiant a la place de l'appelant.

    Pourquoi ne pas re-generer ici : le run_id n'est pas qu'une cle de
    journalisation, c'est aussi le nom du dossier `runs/tri_films_<run_id>`
    deja cree sur disque, la cle du `RunState` en memoire et la valeur capturee
    par la closure du job. Un identifiant substitue en douce par la couche
    infra desynchroniserait la ligne `runs` du dossier et du worker — c'est
    exactement le defaut de « run fantome » que ce lot corrige. Seul
    l'orchestrateur (`JobRunner.start_job`) connait ces invariants et peut
    decider de retenter ou d'abandonner.

    Pourquoi ne pas non plus absorber l'erreur (`INSERT OR IGNORE` / `OR
    REPLACE`) : ce serait transformer un echec de journalisation en succes
    silencieux. `OR IGNORE` rendrait un run sans ligne `runs`, `OR REPLACE`
    ECRASERAIT le run precedent et, via les trois FK `ON DELETE CASCADE` qui
    pointent sur `runs(run_id)` — `errors`, `quality_reports` et `anomalies`,
    posees par `migrations/021_fk_cascade.sql` — detruirait ses erreurs, ses
    rapports qualite et ses anomalies.

    Ce chiffre est MESURE, pas estime : `PRAGMA foreign_key_list` sur une base
    reellement initialisee, verrouille par `RunsSchemaDocumentationTests`. Il
    disait « six » — le compte des tables PORTANT une colonne `run_id`, qui
    n'est pas la meme chose : `film_marked_for_deletion`, `film_tmdb_overrides`
    et `film_decisions_v2` n'ont AUCUNE FK cascade. Un chiffre faux sur
    l'argument qui porte l'arbitrage sera cite plus tard comme s'il avait ete
    verifie.

    Herite de `sqlite3.IntegrityError` : les appelants existants qui
    l'attrapent (start_job, demo_support via `sqlite3.Error`) restent valides.
    """

    def __init__(self, run_id: str, cause: BaseException) -> None:
        super().__init__(
            f"run_id deja utilise : {run_id!r} — aucune ligne 'runs' creee, "
            f"le run ne doit pas demarrer sous cet identifiant ({cause})"
        )
        self.run_id = run_id


def _is_run_id_conflict(exc: sqlite3.IntegrityError) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RUN_ID_CONFLICT_MARKERS)


class RunRepository(_BaseRepository):
    """Repository pour les tables runs + errors."""

    def _insert_pending_run_row(
        self,
        conn: Any,
        *,
        run_id: str,
        created_ts: float,
        root: str,
        state_dir: str,
        config_json: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO runs (
              run_id, status, created_ts, root, state_dir, config_json,
              stats_json, idx, total, current_folder, cancel_requested, error_message
            )
            VALUES (?, 'PENDING', ?, ?, ?, ?, NULL, 0, 0, '', 0, NULL)
            """,
            (run_id, created_ts, str(root), str(state_dir), config_json),
        )

    def _ensure_runs_table(self) -> None:
        self._ensure_schema_group("runs", min_user_version=1)

    def insert_run_pending(
        self,
        *,
        run_id: str,
        root: str,
        state_dir: str,
        config: Dict[str, Any],
        created_ts: Optional[float] = None,
    ) -> None:
        payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
        now = float(created_ts if created_ts is not None else time.time())
        self._ensure_runs_table()

        try:
            with self._managed_conn() as conn:
                self._insert_pending_run_row(
                    conn,
                    run_id=run_id,
                    created_ts=now,
                    root=str(root),
                    state_dir=str(state_dir),
                    config_json=payload,
                )
        except sqlite3.IntegrityError as exc:
            # Defense en profondeur : la PRIMARY KEY est la seule garde ATOMIQUE
            # cote base. On la traduit en erreur TYPEE et explicite, jamais en
            # succes silencieux (cf. RunIdConflictError pour l'arbitrage).
            if _is_run_id_conflict(exc):
                raise RunIdConflictError(run_id, exc) from exc
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.OperationalError) as exc:
            if not (isinstance(exc, sqlite3.OperationalError) and self._is_missing_table_error(exc, "runs")):
                raise
            # Fallback : table absente, delegue a SQLiteStore.initialize() qui
            # cree tous les schemas depuis migrations. Dans _BaseRepository,
            # self._store est le SQLiteStore.
            self._store.initialize()
            try:
                with self._managed_conn() as conn:
                    self._insert_pending_run_row(
                        conn,
                        run_id=run_id,
                        created_ts=now,
                        root=str(root),
                        state_dir=str(state_dir),
                        config_json=payload,
                    )
            except sqlite3.IntegrityError as exc2:
                if _is_run_id_conflict(exc2):
                    raise RunIdConflictError(run_id, exc2) from exc2
                raise

    def mark_run_running(self, run_id: str, *, started_ts: Optional[float] = None) -> None:
        """Bascule le run en statut RUNNING et enregistre `started_ts`."""
        ts = float(started_ts if started_ts is not None else time.time())
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='RUNNING', started_ts=?, error_message=NULL
                WHERE run_id=?
                """,
                (ts, run_id),
            )

    def update_run_progress(self, run_id: str, *, idx: int, total: int, current_folder: str) -> None:
        """Met a jour la progression du run (indice courant, total, dossier en cours)."""
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET idx=?, total=?, current_folder=?
                WHERE run_id=?
                """,
                (int(idx), int(total), str(current_folder or ""), run_id),
            )

    def mark_cancel_requested(self, run_id: str) -> None:
        """Pose le flag `cancel_requested=1` ; la boucle de scan verifiera ce flag."""
        with self._managed_conn() as conn:
            conn.execute(
                "UPDATE runs SET cancel_requested=1 WHERE run_id=?",
                (run_id,),
            )

    def mark_run_done(
        self, run_id: str, *, stats: Optional[Dict[str, Any]] = None, ended_ts: Optional[float] = None
    ) -> None:
        """Bascule le run en statut DONE avec les stats finales serialisees en JSON."""
        ts = float(ended_ts if ended_ts is not None else time.time())
        stats_json = json.dumps(stats, ensure_ascii=False, sort_keys=True) if stats is not None else None
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='DONE', ended_ts=?, stats_json=?, error_message=NULL
                WHERE run_id=?
                """,
                (ts, stats_json, run_id),
            )

    def mark_run_cancelled(
        self, run_id: str, *, stats: Optional[Dict[str, Any]] = None, ended_ts: Optional[float] = None
    ) -> None:
        """Bascule le run en statut CANCELLED (annule a la demande operateur)."""
        ts = float(ended_ts if ended_ts is not None else time.time())
        stats_json = json.dumps(stats, ensure_ascii=False, sort_keys=True) if stats is not None else None
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='CANCELLED', ended_ts=?, stats_json=?, error_message=NULL
                WHERE run_id=?
                """,
                (ts, stats_json, run_id),
            )

    def mark_run_paused(self, run_id: str, *, saved: bool = False, paused_ts: Optional[float] = None) -> bool:
        """Bascule le run en PAUSED (ou SAVED si `saved=True`) et enregistre `paused_at`.

        V8-01 spec 08 Traitement : un run en cours peut etre suspendu (PAUSED)
        ou sauvegarde pour plus tard (SAVED). La transition est autorisee
        uniquement depuis un etat actif (PENDING, RUNNING, AWAITING_VALIDATION).
        Retourne True si la transition a eu lieu, False sinon.
        """
        ts = float(paused_ts if paused_ts is not None else time.time())
        target = "SAVED" if saved else "PAUSED"
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                UPDATE runs
                SET status=?, paused_at=?
                WHERE run_id=? AND status IN ('PENDING', 'RUNNING', 'AWAITING_VALIDATION')
                """,
                (target, ts, run_id),
            )
            return int(cur.rowcount or 0) > 0

    def mark_run_resumed(self, run_id: str, *, resumed_ts: Optional[float] = None) -> bool:
        """Bascule un run PAUSED ou SAVED vers RUNNING.

        V8-01 spec 08 : le complement de `mark_run_paused`. Efface `paused_at`
        et restaure le statut RUNNING. Autorise uniquement depuis PAUSED ou SAVED.
        Retourne True si la transition a eu lieu, False sinon.
        """
        ts = float(resumed_ts if resumed_ts is not None else time.time())
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                UPDATE runs
                SET status='RUNNING', paused_at=NULL, started_ts=COALESCE(started_ts, ?)
                WHERE run_id=? AND status IN ('PAUSED', 'SAVED')
                """,
                (ts, run_id),
            )
            return int(cur.rowcount or 0) > 0

    def list_pending_runs(self) -> List[Dict[str, Any]]:
        """Retourne tous les runs en attente d'action utilisateur.

        V8-01 spec 08 Traitement §5 : `run/list_pending_runs` doit lister
        les runs PAUSED, SAVED ou AWAITING_VALIDATION pour permettre a l'UI
        d'afficher les runs reprenables dans la sidebar / l'historique.

        Format de chaque row :
            run_id, status, created_at, total_rows, last_activity_at.

        `last_activity_at` = `paused_at` si non null, sinon `started_ts`,
        sinon `created_ts`.
        """
        self._ensure_runs_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, status, created_ts, started_ts, ended_ts, paused_at,
                       idx, total, stats_json
                FROM runs
                WHERE status IN ('PAUSED', 'SAVED', 'AWAITING_VALIDATION')
                ORDER BY COALESCE(paused_at, started_ts, created_ts) DESC,
                         created_ts DESC
                """
            )
            out: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                stats = self._decode_row_json(row, "stats_json", default={}, expected_type=dict)
                total_rows = int(row["total"] or stats.get("planned_rows", 0) or 0)
                created_at = float(row["created_ts"] or 0.0)
                paused_at = float(row["paused_at"]) if row["paused_at"] is not None else None
                started_at = float(row["started_ts"]) if row["started_ts"] is not None else None
                last_activity_at = (
                    paused_at if paused_at is not None else (started_at if started_at is not None else created_at)
                )
                out.append(
                    {
                        "run_id": str(row["run_id"]),
                        "status": str(row["status"] or ""),
                        "created_at": created_at,
                        "total_rows": total_rows,
                        "last_activity_at": last_activity_at,
                    }
                )
            return out

    def mark_run_failed(self, run_id: str, *, error_message: str, ended_ts: Optional[float] = None) -> None:
        """Bascule le run en statut FAILED et enregistre le message d'erreur."""
        ts = float(ended_ts if ended_ts is not None else time.time())
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='FAILED', ended_ts=?, error_message=?
                WHERE run_id=?
                """,
                (ts, str(error_message or ""), run_id),
            )

    def insert_error(
        self,
        *,
        run_id: str,
        step: str,
        code: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Insere une erreur associee au run (step, code, message + contexte JSON optionnel)."""
        now = float(ts if ts is not None else time.time())
        context_json = json.dumps(context, ensure_ascii=False, sort_keys=True) if context is not None else None

        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO errors (run_id, ts, step, code, message, context_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, now, str(step), str(code), str(message), context_json),
            )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retourne la ligne `runs` correspondant a `run_id`, ou None si absente."""

        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

        return self._with_schema_group("runs", op, min_user_version=1)

    def list_errors(self, run_id: str) -> List[Dict[str, Any]]:
        """Retourne la liste chronologique des erreurs enregistrees pour ce run."""
        with self._managed_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM errors WHERE run_id=? ORDER BY id ASC",
                (run_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_latest_run(self) -> Optional[Dict[str, Any]]:
        """Retourne le dernier run de SCAN (par started_ts/created_ts), ou None.

        AUDIT 2026-07-13 (HIGH-8) : exclut les runs utilitaires de bulk re-scan
        (marqueur config_json rescan_run_id) via _NOT_RESCAN_TRACKING_SQL. Sans
        ce filtre, get_dashboard / get_sidebar_counters / quality_simulator
        resolvaient le run de tracking (sans plan ni reports) apres un re-scan
        groupe -> KPI Accueil et badges sidebar a 0, en divergence avec la
        Bibliotheque qui, elle, sautait deja ces runs.
        """
        self._ensure_runs_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT *
                FROM runs
                WHERE {_NOT_RESCAN_TRACKING_SQL}
                ORDER BY COALESCE(started_ts, created_ts) DESC, created_ts DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def list_runs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Retourne les N derniers runs (metadonnees completes), ordre chronologique inverse."""
        self._ensure_runs_table()
        lim = max(1, int(limit))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT *
                FROM runs
                ORDER BY COALESCE(started_ts, created_ts) DESC, created_ts DESC
                LIMIT ?
                """,
                (lim,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_runs_summary(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Return last N runs with basic metadata for timeline display."""
        self._ensure_runs_table()
        lim = max(1, int(limit))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, status, created_ts, started_ts, ended_ts,
                       root, stats_json, total
                FROM runs
                ORDER BY COALESCE(started_ts, created_ts) DESC, created_ts DESC
                LIMIT ?
                """,
                (lim,),
            )
            out: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                started = float(row["started_ts"] or 0)
                ended = float(row["ended_ts"] or 0)
                duration = (ended - started) if started and ended else 0.0
                stats = self._decode_row_json(row, "stats_json", default={}, expected_type=dict)
                health_snap = stats.get("health_snapshot") if isinstance(stats.get("health_snapshot"), dict) else None
                out.append(
                    {
                        "run_id": str(row["run_id"]),
                        "status": str(row["status"] or "PENDING"),
                        "start_ts": started,
                        "duration_s": round(duration, 1),
                        "total_rows": int(row["total"] or stats.get("planned_rows", 0) or 0),
                        "applied": bool(stats.get("applied_count", 0)),
                        "health_snapshot": health_snap,
                    }
                )
            return out

    def get_error_counts_for_runs(self, run_ids: List[str]) -> Dict[str, int]:
        """Retourne {run_id: nb_erreurs} pour la liste de runs donnee (agregation bulk).

        Issue #448 : decoupe en paquets. Le `GROUP BY run_id` rend une ligne par
        run, donc l'union des paquets redonne exactement le meme dictionnaire —
        y compris si l'appelant repete un run_id, puisque la valeur reecrite est
        identique.
        """
        ids = [str(x) for x in (run_ids or []) if str(x).strip()]
        if not ids:
            return {}
        out: Dict[str, int] = {}
        with self._managed_conn() as conn:
            for chunk in chunked(ids, SQL_CHUNK):
                placeholders = ",".join("?" for _ in chunk)
                cur = conn.execute(
                    f"""
                    SELECT run_id, COUNT(*) AS cnt
                    FROM errors
                    WHERE run_id IN ({placeholders})
                    GROUP BY run_id
                    """,
                    tuple(chunk),
                )
                out.update({str(r["run_id"]): int(r["cnt"]) for r in cur.fetchall()})
        return out

    #: Tables portant un `run_id` et pouvant donc devenir ORPHELINES.
    #:
    #: La decision N26 fait deliberement survivre les lignes orphelines a
    #: l'auto-reparation du schema (elle preserve le journal d'erreurs). Leur
    #: `run_id` doit donc rester considere comme PRIS, sans quoi un nouveau run
    #: heriterait du journal d'un run mort.
    #:
    #: MESURE (2026-08-07) : 12 tables portent un `run_id`, mais SEULES TROIS
    #: ont une cle etrangere vers `runs` (`errors`, `quality_reports`,
    #: `anomalies`). La cascade ne couvre donc qu'un quart du probleme.
    #:
    #: `tests/test_run_id_orphelin_984.py` rougit si une table portant un
    #: `run_id` manque a cette liste — elle ne peut pas se perimer en silence.
    _TABLES_PORTANT_RUN_ID: tuple[str, ...] = (
        "anomalies",
        "apply_batches",
        "duplicate_decisions",
        "errors",
        "film_decisions_v2",
        "film_field_locks",
        "film_marked_for_deletion",
        "film_tmdb_overrides",
        "perceptual_reports",
        "quality_reports",
        "user_quality_feedback",
    )

    def run_id_est_utilise(self, run_id: str) -> bool:
        """Vrai si ce `run_id` est pris — y compris par une ligne ORPHELINE.

        `get_run()` ne consulte que `runs`, et rend donc `None` pour un run dont
        seules des lignes enfants subsistent. La garde d'unicite de
        `job_runner.start_job` s'appuyait sur elle : un `run_id` fantome etait
        declare LIBRE, et le run suivant heritait du journal d'erreurs du run
        mort — `list_errors('GHOST')` rendant l'erreur du precedent.

        Ce n'est pas une precaution abstraite : `cinesort/infra/run_id.py`
        documente une collision MESUREE du generateur au passage a l'heure
        d'hiver, et annonce comme defense en profondeur « la PRIMARY KEY de
        `runs` » — laquelle ne voit justement pas les orphelines.
        """
        rid = str(run_id or "").strip()
        if not rid:
            return False
        self._ensure_runs_table()
        with self._managed_conn() as conn:
            cur = conn.execute("SELECT 1 FROM runs WHERE run_id=? LIMIT 1", (rid,))
            if cur.fetchone() is not None:
                return True
            for table in self._TABLES_PORTANT_RUN_ID:
                # Le nom vient d'une constante de classe, jamais d'une entree
                # utilisateur — et l'appartenance est reverifiee ici pour que la
                # surete soit LOCALE, lisible sans remonter a la definition.
                if table not in self._TABLES_PORTANT_RUN_ID:  # pragma: no cover - garde de programmation
                    raise ValueError(f"table hors liste blanche : {table!r}")
                try:
                    cur = conn.execute(f"SELECT 1 FROM {table} WHERE run_id=? LIMIT 1", (rid,))  # noqa: S608
                except sqlite3.OperationalError as exc:
                    # UNIQUEMENT « table absente » (base partiellement migree) :
                    # elle ne peut alors porter aucune orpheline.
                    #
                    # Un `except` large avalerait aussi « database is locked »,
                    # un schema invalide ou une erreur d'E/S — et
                    # `run_id_est_utilise` declarerait le run_id LIBRE sans avoir
                    # regarde toutes les tables. C'est exactement le defaut que
                    # cette methode corrige, reintroduit par sa gestion d'erreur.
                    if not self._is_missing_table_error(exc, table):
                        raise
                    continue
                if cur.fetchone() is not None:
                    return True
        return False

    def delete_run(self, run_id: str) -> int:
        """Supprime un run de la DB.

        Cascade DB (cf migration 021_fk_cascade) :
        - errors           : ON DELETE CASCADE
        - quality_reports  : ON DELETE CASCADE
        - anomalies        : ON DELETE CASCADE

        Cascade manuelle (tables sans FK CASCADE) :
        - perceptual_reports : suppression manuelle par run_id
        - apply_batches      : suppression manuelle (et donc apply_operations
          via FK CASCADE sur batch_id)

        Les fichiers vidéo (root) ne sont JAMAIS touchés. Les fichiers
        d'état (plan.jsonl, validation.json, log.txt) restent eux aussi
        sur disque, le cron de cleanup ou l'utilisateur les supprimera.

        Retourne le nombre d'enregistrements directement liés au run qui
        ont été supprimés (toutes tables confondues, incluant la row
        `runs` elle-même).
        """
        rid = str(run_id or "").strip()
        if not rid:
            return 0
        self._ensure_runs_table()
        with self._managed_conn() as conn:
            # #984 — ON SUPPRIME EXPLICITEMENT, ON NE COMPTE PLUS UNE PROMESSE.
            #
            # La version precedente COMPTAIT ces trois tables avant de supprimer
            # le parent, en pariant sur la CASCADE. Le pari tombe des que la
            # ligne `runs` n'existe pas : la CASCADE ne se declenche pas, les
            # enfants RESTENT, et la methode retournait quand meme leur nombre.
            # Mesure de l'issue : `delete_run('GHOST')` rendait 1 en ayant
            # supprime 0 ligne, et `errors` en portait toujours une apres coup.
            #
            # Ce cas n'est pas theorique : la decision N26 fait deliberement
            # SURVIVRE les lignes orphelines a l'auto-reparation du schema. Un
            # `delete_run` sur un run fantome est donc le seul moyen de les
            # nettoyer — et c'est precisement ce qu'il ne faisait pas.
            #
            # Supprimer d'abord les enfants rend la valeur retournee VRAIE, et
            # marche que le parent existe ou non. La CASCADE devient une
            # ceinture de securite, plus le mecanisme principal.
            # SYMETRIE STRUCTURELLE AVEC `run_id_est_utilise`. On itere la MEME
            # constante : toute table qui RESERVE un run_id doit etre purgee par
            # sa suppression, sinon l'identifiant reste occupe pour toujours.
            #
            # Une premiere version enumerait trois tables a la main pendant que
            # la garde en consultait onze. Une orpheline dans l'une des huit
            # autres survivait donc a `delete_run`, et le run_id n'etait JAMAIS
            # libere. L'asymetrie etait invisible parce que le test de nettoyage
            # n'utilisait que `errors`.
            enfants_supprimes = 0
            for table in self._TABLES_PORTANT_RUN_ID:
                if table == "apply_batches":
                    continue  # purge dediee plus bas, avec ses operations liees
                try:
                    cur = conn.execute(f"DELETE FROM {table} WHERE run_id=?", (rid,))  # noqa: S608
                except sqlite3.OperationalError as exc:
                    if not self._is_missing_table_error(exc, table):
                        raise
                    continue
                enfants_supprimes += int(cur.rowcount or 0)

            # apply_batches n'a PAS de FK CASCADE sur run_id — purge des batches
            # AVANT de supprimer le run pour pouvoir compter les operations
            # rattachees (apply_operations CASCADE sur batch_id).
            #
            # Issue #448 : la version precedente lisait les batch_id en Python
            # puis rejouait la liste ENTIERE en parametres lies, dans un `IN` non
            # borne — au-dela de SQLITE_MAX_VARIABLE_NUMBER la suppression levait
            # « too many SQL variables ». Le sous-requetage garde exactement le
            # meme ensemble de lignes (meme predicat `run_id=?`, meme instant
            # dans la transaction) avec DEUX parametres au total, quel que soit
            # le nombre de batches. Sur ce chemin destructif c'est aussi le sens
            # restrictif : une seule instruction, donc pas d'etat mi-supprime.
            cur = conn.execute(
                "SELECT COUNT(*) AS n FROM apply_operations"
                " WHERE batch_id IN (SELECT batch_id FROM apply_batches WHERE run_id=?)",
                (rid,),
            )
            apply_ops_deleted = int(cur.fetchone()["n"] or 0)
            cur = conn.execute("DELETE FROM apply_batches WHERE run_id=?", (rid,))
            batches_deleted = int(cur.rowcount or 0)

            cur = conn.execute("DELETE FROM runs WHERE run_id=?", (rid,))
            run_deleted = int(cur.rowcount or 0)

        return run_deleted + enfants_supprimes + batches_deleted + apply_ops_deleted

    def list_runs_older_than(self, *, cutoff_ts: float) -> List[str]:
        """Retourne les run_ids dont la date la plus recente (started_ts > created_ts) est < cutoff_ts.

        Utile pour le cron de retention.
        """
        self._ensure_runs_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id
                FROM runs
                WHERE COALESCE(started_ts, created_ts) < ?
                ORDER BY COALESCE(started_ts, created_ts) ASC
                """,
                (float(cutoff_ts),),
            )
            return [str(r["run_id"]) for r in cur.fetchall()]
