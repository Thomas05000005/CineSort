"""R8 F2-d — DIFFERENTIEL self-heal de migration (cluster R8-019/020/021/022). DB jetable.

S-019 (paused_at) : un self-heal bootstrap (rejoue 025) sur une DB avec paused_at PRESERVE la valeur
                    (AVANT : ecrasee a NULL = perte). LE plus critique.
S-022 (incremental_row_cache) : la table est dans REQUIRED_SCHEMA_TABLES -> recreee par le self-heal.
S-020 (schema_migrations) : backfille apres le bootstrap (historique non desync).
S-021 (IntegrityError idempotent) : _is_idempotent_error accepte unique/pk (re-INSERT au replay) mais
                    PAS NOT NULL/CHECK -> un rebuild idempotent ne bloque plus le boot.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2d_selfheal_diff.py
"""
from __future__ import annotations
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore, REQUIRED_SCHEMA_TABLES, SCHEMA_GROUPS
from cinesort.infra.db.migration_manager import _is_idempotent_error


def run():
    results = {}
    tmp = Path(tempfile.mkdtemp(prefix="cs_f2d_sh_"))
    st = SQLiteStore(tmp / "t.sqlite", busy_timeout_ms=5000)
    st.initialize()

    # Inserer un run avec paused_at non-NULL
    PAUSED_AT = 1234567.89
    with st._managed_conn() as c:
        c.execute(
            "INSERT INTO runs (run_id, status, created_ts, root, state_dir, config_json, paused_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("run1", "PAUSED", 1.0, "root", "sdir", "{}", PAUSED_AT),
        )
        c.commit()

    # Declencher le self-heal : dropper une table REQUISE (incremental_row_cache) puis re-init.
    with st._managed_conn() as c:
        c.execute("DROP TABLE IF EXISTS incremental_row_cache")
        c.commit()
        irc_before = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='incremental_row_cache'"
        ).fetchone()

    # Re-initialiser -> _ensure_required_schema voit incremental_row_cache manquante ->
    # _bootstrap_schema_latest rejoue tout le script (dont 025).
    st.initialize()

    with st._managed_conn() as c:
        row = c.execute("SELECT paused_at FROM runs WHERE run_id='run1'").fetchone()
        paused_after = row[0] if row else None
        irc_after = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='incremental_row_cache'"
        ).fetchone()
        try:
            sm_count = c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        except sqlite3.Error:
            sm_count = -1

    s019 = (paused_after == PAUSED_AT)
    s022_reg = ("incremental_row_cache" in REQUIRED_SCHEMA_TABLES
                and "incremental_row_cache" in SCHEMA_GROUPS["incremental"])
    s022_recreated = (irc_before is None and irc_after is not None)
    s020 = (sm_count > 0)
    results["S019_paused_at_preserve_au_selfheal"] = s019
    results["S022_incremental_row_cache_dans_registre"] = s022_reg
    results["S022_recreee_par_selfheal"] = s022_recreated
    results["S020_schema_migrations_backfille"] = s020

    print("=== S-019 (paused_at preserve au self-heal bootstrap) ===")
    print(f"  paused_at AVANT self-heal : {PAUSED_AT}")
    print(f"  paused_at APRES self-heal : {paused_after} (AVANT le fix = None/perte ; attendu {PAUSED_AT})")
    print("\n=== S-022 (incremental_row_cache filet self-heal) ===")
    print(f"  dans REQUIRED_SCHEMA_TABLES + SCHEMA_GROUPS : {s022_reg}")
    print(f"  droppee puis RECREEE par le self-heal       : {s022_recreated} (before={irc_before}, after={bool(irc_after)})")
    print("\n=== S-020 (schema_migrations backfille apres bootstrap) ===")
    print(f"  rows schema_migrations apres self-heal : {sm_count} (attendu > 0)")

    # S-021 : taxonomie idempotente (pure fonction)
    ok_unique = _is_idempotent_error(sqlite3.IntegrityError("UNIQUE constraint failed: t.col"))
    ok_pk = _is_idempotent_error(sqlite3.IntegrityError("PRIMARY KEY must be unique"))
    not_notnull = _is_idempotent_error(sqlite3.IntegrityError("NOT NULL constraint failed: t.col"))
    not_check = _is_idempotent_error(sqlite3.IntegrityError("CHECK constraint failed: t"))
    s021 = ok_unique and ok_pk and (not not_notnull) and (not not_check)
    results["S021_integrityerror_idempotent_narrow"] = s021
    print("\n=== S-021 (IntegrityError idempotent, allowlist etroite) ===")
    print(f"  UNIQUE/PK -> idempotent (skip)     : {ok_unique}/{ok_pk} (attendu True/True)")
    print(f"  NOT NULL/CHECK -> NON idempotent   : {not not_notnull}/{not not_check} (attendu re-leve)")

    shutil.rmtree(tmp, ignore_errors=True)
    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (self-heal coherent : paused_at preserve, cache au filet, backfill, taxonomie)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
