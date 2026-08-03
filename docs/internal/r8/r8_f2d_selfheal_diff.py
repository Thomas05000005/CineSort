"""R8 F2-d — DIFFERENTIEL self-heal de migration (cluster R8-019/020/021/022). DB jetable.

S-019 (paused_at) : un self-heal bootstrap (rejoue 025) sur une DB avec paused_at PRESERVE la valeur
                    (AVANT : ecrasee a NULL = perte). LE plus critique.
S-022 (incremental_row_cache) : la table est dans REQUIRED_SCHEMA_TABLES -> recreee par le self-heal.
S-020 (schema_migrations) : backfille apres le bootstrap (historique non desync).
S-021 RETRACTE (filet F2-d) : _is_idempotent_error NE swallow PLUS aucun IntegrityError (UNIQUE/PK
                    inclus) -> sur rebuild a source corrompue, re-leve (boot bloque, recuperable)
                    plutot que wipe silencieux. Seuls OperationalError duplicate-column/already-exists
                    restent idempotents. Voir r8_f2d_filet_survivors_diff.py pour le differentiel wipe.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2d_selfheal_diff.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from cinesort.infra.db.migration_manager import _is_idempotent_error
from cinesort.infra.db.sqlite_store import REQUIRED_SCHEMA_TABLES, SCHEMA_GROUPS, SQLiteStore


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

    s019 = paused_after == PAUSED_AT
    s022_reg = (
        "incremental_row_cache" in REQUIRED_SCHEMA_TABLES and "incremental_row_cache" in SCHEMA_GROUPS["incremental"]
    )
    s022_recreated = irc_before is None and irc_after is not None
    s020 = sm_count > 0
    results["S019_paused_at_preserve_au_selfheal"] = s019
    results["S022_incremental_row_cache_dans_registre"] = s022_reg
    results["S022_recreee_par_selfheal"] = s022_recreated
    results["S020_schema_migrations_backfille"] = s020

    print("=== S-019 (paused_at preserve au self-heal bootstrap) ===")
    print(f"  paused_at AVANT self-heal : {PAUSED_AT}")
    print(f"  paused_at APRES self-heal : {paused_after} (AVANT le fix = None/perte ; attendu {PAUSED_AT})")
    print("\n=== S-022 (incremental_row_cache filet self-heal) ===")
    print(f"  dans REQUIRED_SCHEMA_TABLES + SCHEMA_GROUPS : {s022_reg}")
    print(
        f"  droppee puis RECREEE par le self-heal       : {s022_recreated} (before={irc_before}, after={bool(irc_after)})"
    )
    print("\n=== S-020 (schema_migrations backfille apres bootstrap) ===")
    print(f"  rows schema_migrations apres self-heal : {sm_count} (attendu > 0)")

    # S-021 RETRACTE (filet F2-d) : _is_idempotent_error NE swallow PLUS aucun
    # IntegrityError (UNIQUE/PK inclus) -> sur un rebuild a source corrompue, l'erreur
    # est re-levee (boot bloque, recuperable) plutot que de wiper la table. SEULS les
    # OperationalError "duplicate column"/"already exists" restent idempotents.
    skip_unique = _is_idempotent_error(sqlite3.OperationalError("UNIQUE constraint failed: t.col"))
    skip_pk = _is_idempotent_error(sqlite3.OperationalError("PRIMARY KEY must be unique"))
    skip_notnull = _is_idempotent_error(sqlite3.OperationalError("NOT NULL constraint failed: t.col"))
    skip_dupcol = _is_idempotent_error(sqlite3.OperationalError("duplicate column name: x"))
    skip_exists = _is_idempotent_error(sqlite3.OperationalError("table x already exists"))
    # SUR = aucun IntegrityError-like swallow, seuls duplicate column / already exists.
    s021 = (not skip_unique) and (not skip_pk) and (not skip_notnull) and skip_dupcol and skip_exists
    results["S021_integrityerror_NON_swallow_retracte"] = s021
    print("\n=== S-021 RETRACTE (IntegrityError NON swallow = sur) ===")
    print(
        f"  UNIQUE/PK/NOTNULL -> NON idempotent (re-leve) : {not skip_unique}/{not skip_pk}/{not skip_notnull} (attendu True/True/True)"
    )
    print(f"  duplicate column / already exists -> idempotent : {skip_dupcol}/{skip_exists} (attendu True/True)")

    shutil.rmtree(tmp, ignore_errors=True)
    allok = all(results.values())
    print(
        f"\nVERDICT : {'CORRIGE (self-heal coherent : paused_at preserve, cache au filet, backfill, taxonomie)' if allok else 'INCOMPLET'}"
    )
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
