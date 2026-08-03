"""C3-F — Repro LIVE migrations sur COPIE d'une vraie DB peuplee (data.db).

Teste, sur COPIE JETABLE uniquement (jamais data.db reelle) :
  T1  apply() sur la copie -> atteint la derniere version, AUCUNE exception,
      row-counts des tables preserves (pas de perte de donnees).
  T2  idempotence : 2e apply() -> no-op, meme version, pas d'erreur.
  T3  vieux schema simule : user_version=0 sur DB DEJA peuplee -> apply() rejoue
      TOUTES les migrations (self-healing). Doit etre IDEMPOTENT (IF NOT EXISTS)
      et ne perdre AUCUNE donnee. Si une migration n'est pas idempotente ->
      OperationalError -> ROUGE (falsifiable).
  T4  ordre : list_migrations() renvoie bien un tri ASCENDANT (refute leurre).
  T5  migration 032 (nom en tirets) : confirme qu'elle est ABSENTE de la liste.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/c3_migrations_old_db.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from cinesort.infra.db.migration_manager import MigrationManager

REPO = Path(__file__).resolve().parents[4]  # proofs/audit_horizons/internal/docs/<racine>
MIG_DIR = REPO / "cinesort" / "infra" / "db" / "migrations"
_STATE_DB = Path("C:/Users/blanc/AppData/Local/CineSort/db")
# DB peuplee courante (1027 films) + un backup VIEUX SCHEMA reel (v1.6.2, 30 mai).
REAL_DB = _STATE_DB / "cinesort.sqlite"
OLD_DB = _STATE_DB / "cinesort.sqlite.bak_avant_v162_20260530_172150"


def _table_counts(db: Path) -> dict:
    out = {}
    with sqlite3.connect(str(db)) as conn:
        tbls = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        for t in tbls:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
            except sqlite3.Error as e:
                out[t] = f"ERR:{e}"
    return out


def _user_version(db: Path) -> int:
    with sqlite3.connect(str(db)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def run():
    out = {"real_db_exists": REAL_DB.is_file()}
    if not REAL_DB.is_file():
        print(json.dumps(out, indent=2))
        return

    tmp = Path(tempfile.mkdtemp(prefix="cs_mig_"))
    copy = tmp / "data_copy.db"
    shutil.copy2(REAL_DB, copy)

    before = _table_counts(copy)
    v0 = _user_version(copy)
    out["version_initiale"] = v0
    out["tables_avant"] = len(before)

    mm = MigrationManager(copy, MIG_DIR)

    # T4 + T5 : ordre + 032
    migs = mm.list_migrations()
    versions = [v for v, _ in migs]
    out["T4_ordre_ascendant"] = {
        "versions": versions,
        "VERDICT": "ASCENDANT OK" if versions == sorted(versions) else "DESORDRE",
    }
    names = [p.name for _, p in migs]
    out["T5_032_dash_absente"] = {
        "032_dans_liste": any("032" in n for n in names),
        "VERDICT": "032 tirets IGNOREE (confirme latent)"
        if not any(n.startswith("032") for n in names)
        else "032 presente",
    }

    # T1 : apply sur copie
    try:
        vfinal = mm.apply()
        after = _table_counts(copy)
        lost = {
            t: (before[t], after.get(t))
            for t in before
            if isinstance(before[t], int) and isinstance(after.get(t), int) and after[t] < before[t]
        }
        out["T1_apply"] = {
            "version_finale": vfinal,
            "tables_apres": len(after),
            "tables_perdues_ou_reduites": lost,
            "VERDICT": "OK (aucune perte)" if not lost else "PERTE DETECTEE",
        }
    except Exception as e:  # noqa: BLE001
        out["T1_apply"] = {"EXCEPTION": f"{type(e).__name__}: {e}", "VERDICT": "ROUGE"}

    # T2 : idempotence
    try:
        v2 = mm.apply()
        out["T2_idempotence"] = {
            "version_2e_run": v2,
            "VERDICT": "no-op OK" if v2 == out["T1_apply"].get("version_finale") else "DIVERGE",
        }
    except Exception as e:  # noqa: BLE001
        out["T2_idempotence"] = {"EXCEPTION": f"{type(e).__name__}: {e}", "VERDICT": "NON-IDEMPOTENT (ROUGE)"}

    # T3 : vieux schema simule (user_version=0) sur DB peuplee
    copy3 = tmp / "data_oldschema.db"
    shutil.copy2(REAL_DB, copy3)
    with sqlite3.connect(str(copy3)) as conn:
        conn.execute("PRAGMA user_version=0")
        conn.commit()
    before3 = _table_counts(copy3)
    mm3 = MigrationManager(copy3, MIG_DIR)
    try:
        v3 = mm3.apply()
        after3 = _table_counts(copy3)
        lost3 = {
            t: (before3[t], after3.get(t))
            for t in before3
            if isinstance(before3[t], int) and isinstance(after3.get(t), int) and after3[t] < before3[t]
        }
        out["T3_vieux_schema_replay"] = {
            "version_finale": v3,
            "tables_perdues_ou_reduites": lost3,
            "VERDICT": "self-healing IDEMPOTENT OK (aucune perte)" if not lost3 else "PERTE/ROUGE",
        }
    except Exception as e:  # noqa: BLE001
        out["T3_vieux_schema_replay"] = {
            "EXCEPTION": f"{type(e).__name__}: {e}",
            "VERDICT": "REPLAY NON-IDEMPOTENT (ROUGE)",
        }

    # T6 : vrai backup VIEUX SCHEMA peuple (v1.6.2) -> upgrade lossless + idempotent
    if OLD_DB.is_file():
        copy6 = tmp / "old_schema_v162.db"
        shutil.copy2(OLD_DB, copy6)
        before6 = _table_counts(copy6)
        v6_0 = _user_version(copy6)
        mm6 = MigrationManager(copy6, MIG_DIR)
        try:
            v6 = mm6.apply()
            v6b = mm6.apply()  # idempotence
            after6 = _table_counts(copy6)
            lost6 = {
                t: (before6[t], after6.get(t))
                for t in before6
                if isinstance(before6[t], int) and isinstance(after6.get(t), int) and after6[t] < before6[t]
            }
            out["T6_vrai_vieux_schema_v162"] = {
                "version_avant": v6_0,
                "version_apres": v6,
                "idempotent_run2": v6b == v6,
                "tables_avant": len(before6),
                "tables_apres": len(after6),
                "tables_perdues_ou_reduites": lost6,
                "VERDICT": "UPGRADE vieux schema OK (lossless + idempotent)"
                if not lost6 and v6b == v6
                else "PERTE/NON-IDEMPOTENT (ROUGE)",
            }
        except Exception as e:  # noqa: BLE001
            out["T6_vrai_vieux_schema_v162"] = {"EXCEPTION": f"{type(e).__name__}: {e}", "VERDICT": "ROUGE"}
    else:
        out["T6_vrai_vieux_schema_v162"] = {"SKIP": "backup v162 absent"}

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
