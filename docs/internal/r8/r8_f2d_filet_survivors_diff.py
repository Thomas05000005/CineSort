"""R8 F2-d — DIFFERENTIELS des 2 survivants du filet F2-d.

(1) R8-021 RETRACTE : swallow IntegrityError sur un rebuild INSERT...SELECT a source
    corrompue (PK dupliquee) = wipe silencieux de la table. La politique COURANTE
    (migration_manager._is_idempotent_error : OperationalError uniquement) re-leve ->
    pas de wipe (boot bloque, recuperable).
(2) R8-091 : candidate_from_json perdait tmdb_collection_id / tmdb_collection_name
    (le jumeau plan_row_from_jsonable les preservait deja).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2d_filet_survivors_diff.py
"""
from __future__ import annotations
import dataclasses
import json
import sqlite3

from cinesort.domain import core
from cinesort.infra.db.migration_manager import _is_idempotent_error
from cinesort.ui.api.run_data_support import candidate_from_json


# Sequence d'une migration de RECONSTRUCTION (cf 021/025) : rebuild via table _new.
_REBUILD_STMTS = [
    "CREATE TABLE x_new (id INTEGER PRIMARY KEY, val TEXT)",
    "INSERT INTO x_new (id, val) SELECT id, val FROM x",  # leve PK IntegrityError si x corrompue
    "DROP TABLE x",
    "ALTER TABLE x_new RENAME TO x",
]


def _seed_corrupt_db():
    """Table x SANS PK declaree -> peut contenir des id dupliques (source corrompue)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE x (id INTEGER, val TEXT)")
    conn.execute("INSERT INTO x (id, val) VALUES (1, 'PRECIEUX-A')")
    conn.execute("INSERT INTO x (id, val) VALUES (1, 'PRECIEUX-B')")  # id duplique
    conn.execute("INSERT INTO x (id, val) VALUES (2, 'PRECIEUX-C')")
    conn.commit()
    return conn


def _replay(conn, *, swallow_integrity: bool):
    """Rejoue le rebuild avec savepoint/stmt, politique skip/raise parametree.

    swallow_integrity=True  -> AVANT (R8-021 : allowlist UNIQUE/PK + except IntegrityError)
    swallow_integrity=False -> COURANT (retracte : OperationalError uniquement via _is_idempotent_error)
    """
    for i, stmt in enumerate(_REBUILD_STMTS):
        sp = f"sp_{i}"
        conn.execute(f"SAVEPOINT {sp}")
        try:
            conn.execute(stmt)
            conn.execute(f"RELEASE SAVEPOINT {sp}")
        except sqlite3.OperationalError as exc:
            if _is_idempotent_error(exc):
                conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                conn.execute(f"RELEASE SAVEPOINT {sp}")
                continue
            raise
        except sqlite3.IntegrityError as exc:
            if swallow_integrity and any(
                f in str(exc).lower() for f in ("unique constraint failed", "primary key")
            ):
                # AVANT : la politique R8-021 skippait -> x_new reste VIDE.
                conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                conn.execute(f"RELEASE SAVEPOINT {sp}")
                continue
            raise


def _count_x(conn) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM x").fetchone()[0]
    except sqlite3.Error:
        return -1


def diff_r8021():
    print("=== (1) R8-021 RETRACTE : rebuild a source corrompue ===")

    # AVANT (swallow IntegrityError) : x_new vide -> DROP+RENAME = wipe.
    conn_av = _seed_corrupt_db()
    before = _count_x(conn_av)
    wiped = False
    try:
        _replay(conn_av, swallow_integrity=True)
    except sqlite3.Error as exc:  # ne devrait PAS arriver cote AVANT
        print(f"  AVANT a leve (inattendu) : {exc}")
    after_av = _count_x(conn_av)
    wiped = after_av == 0 and before > 0
    print(f"  AVANT (swallow)  : x {before} lignes -> {after_av} lignes  | WIPE silencieux = {wiped}")
    conn_av.close()

    # COURANT (retracte) : IntegrityError re-levee -> rollback, x intacte.
    conn_now = _seed_corrupt_db()
    before2 = _count_x(conn_now)
    raised = False
    try:
        _replay(conn_now, swallow_integrity=False)
    except sqlite3.IntegrityError as exc:
        raised = True
        conn_now.rollback()  # le manager fait rollback global puis re-leve (boot bloque)
        reason = str(exc)
    after_now = _count_x(conn_now)
    preserved = raised and after_now == before2 and before2 > 0
    print(f"  COURANT (raise)  : x {before2} lignes -> {after_now} lignes  | IntegrityError re-levee = {raised}")
    if raised:
        print(f"                     raison : {reason}")
    print(f"  -> donnees PRESERVEES (boot bloque, recuperable) = {preserved}")
    conn_now.close()

    ok = wiped and preserved
    print(f"  VERDICT R8-021 : {'CORRIGE (AVANT wipe ; COURANT preserve+re-leve)' if ok else 'NON PROUVE'}")
    return ok


def diff_r8091():
    print("\n=== (2) R8-091 : round-trip candidate collection TMDb ===")
    cand = core.Candidate(
        title="Iron Man",
        year=2008,
        source="tmdb",
        tmdb_id=1726,
        score=0.95,
        note="n",
        tmdb_collection_id=131292,
        tmdb_collection_name="The Avengers Collection",
    )
    serialized = dataclasses.asdict(cand)
    reloaded = candidate_from_json(serialized)

    a = dataclasses.asdict(cand)
    b = dataclasses.asdict(reloaded)
    lost = [k for k in a if a[k] != b[k]]
    id_ok = reloaded.tmdb_collection_id == 131292
    name_ok = reloaded.tmdb_collection_name == "The Avengers Collection"
    print(f"  champs perdus au reload : {lost} (AVANT : ['tmdb_collection_id','tmdb_collection_name'])")
    print(f"  tmdb_collection_id   reload : {reloaded.tmdb_collection_id} (attendu 131292)")
    print(f"  tmdb_collection_name reload : {reloaded.tmdb_collection_name!r} (attendu 'The Avengers Collection')")
    ok = id_ok and name_ok and not lost
    print(f"  VERDICT R8-091 : {'CORRIGE (collection preservee)' if ok else 'NON PROUVE'}")
    return ok


if __name__ == "__main__":
    r1 = diff_r8021()
    r2 = diff_r8091()
    print("\nRESUME:", json.dumps({"R8021_retract": r1, "R8091_collection": r2}, ensure_ascii=False))
