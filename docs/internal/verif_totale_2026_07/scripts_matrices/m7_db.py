# -*- coding: utf-8 -*-
"""M7 - Matrice de cablage DB : table -> repository -> UI.

REJOUABLE : python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m7_db.py

Entrees (lecture seule) :
  - cinesort/infra/db/migrations/*.sql  (CREATE TABLE + ALTER ... RENAME TO)
  - cinesort/**/*.py                    (sites SQL lecture/ecriture)
  - cinesort/infra/db/repositories/*.py (methodes par table, via ast)
  - cinesort/infra/db/sqlite_store.py   (mapping attribut store -> Repository)
  - cinesort/ui/api/**                  (remontee UI : *_support.py -> facades)

Sortie : docs/internal/verif_totale_2026_07/matrices/m7_db.json

Verdicts (sites .py hors migrations, DDL exclue) :
  - CABLEE     : >=1 site d'ecriture ET >=1 site de lecture
  - WRITE_ONLY : ecrite mais jamais lue
  - READ_NEVER : lue mais jamais ecrite (table toujours vide)
  - MORTE      : ni lue ni ecrite

Note a part (PAS un finding) : 032-vector-search-tables.sql est nommee avec
des TIRETS -> ne matche pas _MIGRATION_FILE_RE (^\\d+_.*\\.sql$) du
migration_manager, donc jamais appliquee = decision produit D3 (differee).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(r"C:/Users/blanc/projects/CineSort")
MIG_DIR = REPO_ROOT / "cinesort" / "infra" / "db" / "migrations"
REPOS_DIR = REPO_ROOT / "cinesort" / "infra" / "db" / "repositories"
STORE_PY = REPO_ROOT / "cinesort" / "infra" / "db" / "sqlite_store.py"
UI_API_DIR = REPO_ROOT / "cinesort" / "ui" / "api"
OUT_JSON = REPO_ROOT / "docs" / "internal" / "verif_totale_2026_07" / "matrices" / "m7_db.json"

MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d+)_.*\.sql$")  # copie de migration_manager.py:15
CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\w+)", re.I)
RENAME_RE = re.compile(r"ALTER\s+TABLE\s+(?P<old>\w+)\s+RENAME\s+TO\s+(?P<new>\w+)", re.I)

# Methodes de repo trop generiques -> exclues du scan d'appels (faux positifs)
GENERIC_METHOD_BLOCKLIST = {"get", "set", "list", "all", "run", "add", "close", "open", "count"}

# Annotations verifiees manuellement (2026-07-08) — contexte pour les verdicts
ANNOTATIONS = {
    "anomalies": (
        "READ_NEVER confirme : AnomalyRepository (anomaly.py) = 4 SELECT purs, "
        "AUCUN INSERT dans tout cinesort/ (verifie : 0 executemany, pas de nom de "
        "table dynamique). Le dashboard lit une table structurellement vide "
        "(dashboard_support.py:511 list_anomalies_for_run avec fallback "
        "anomalies_light, dashboard_cache_support.py:40 get_anomaly_stats, "
        "dashboard_support.py:1703 get_top_anomaly_codes). Les rows ne peuvent "
        "sortir que par FK CASCADE (delete_run) mais n'entrent jamais."
    ),
    "schema_migrations": (
        "WRITE_ONLY by design : journal d'audit DB3 (INSERT OR IGNORE, "
        "migration_manager.py:321 + backfill sqlite_store.py:333). Jamais lu par "
        "le code — trace pour lecture humaine/diagnostic. Pas un bug."
    ),
    "vec_films_hash": (
        "Decision produit D3 (voir note_a_part_032) : migration jamais appliquee "
        "(nom en tirets) ET SqliteVecAdapter.add_embedding non implemente "
        "(sqlite_vec_adapter.py:166 'a implementer en V3.3 runtime'). Scaffold "
        "V3.3 differe, feature flag similar_films OFF. PAS un finding."
    ),
    "apply_pending_moves": (
        "Pas de remontee UI directe by design : journal crash-recovery consomme "
        "par cinesort/app/move_journal.py et cinesort/app/move_reconciliation.py."
    ),
    "pragma_history": (
        "Table interne infra (pragma_profile.py:230 INSERT / :249 SELECT / :253 "
        "DELETE), pas de repository ni de remontee UI attendus."
    ),
    "incremental_file_hashes": "Cache interne du scan incremental (scan.py), pas d'UI attendue.",
    "incremental_scan_cache": "Cache interne du scan incremental (scan.py), pas d'UI attendue.",
    "incremental_row_cache": "Cache interne du scan incremental (scan.py), pas d'UI attendue.",
}


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_sql_comments(sql: str) -> str:
    out_lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        if idx >= 0:
            line = line[:idx]
        out_lines.append(line)
    return "\n".join(out_lines)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------- migrations
def extract_tables():
    """Retourne (tables, notes). tables[name] = {origin, migrations, rebuilds, applied}."""
    tables: dict[str, dict] = {}
    notes = []
    mig_files = sorted(
        MIG_DIR.glob("*.sql"),
        key=lambda p: int(re.match(r"^(\d+)", p.name).group(1)),
    )
    for mig in mig_files:
        applied = bool(MIGRATION_FILE_RE.match(mig.name))
        sql = strip_sql_comments(read_text(mig))
        created = [m.group("name") for m in CREATE_TABLE_RE.finditer(sql)]
        renames = {m.group("old"): m.group("new") for m in RENAME_RE.finditer(sql)}
        for name in created:
            if name in renames:  # table temporaire de rebuild (xxx_new -> xxx)
                target = renames[name]
                tbl = tables.setdefault(target, {
                    "origin_migration": mig.name, "migrations": [], "rebuilds": [], "applied_by_manager": applied,
                })
                tbl["rebuilds"].append(mig.name)
                if mig.name not in tbl["migrations"]:
                    tbl["migrations"].append(mig.name)
                continue
            tbl = tables.setdefault(name, {
                "origin_migration": mig.name, "migrations": [], "rebuilds": [], "applied_by_manager": applied,
            })
            if mig.name not in tbl["migrations"]:
                tbl["migrations"].append(mig.name)
        if not applied:
            notes.append(
                f"{mig.name}: nom en TIRETS -> ne matche pas _MIGRATION_FILE_RE "
                f"(migration_manager.py:15), JAMAIS appliquee par le manager. "
                f"Decision produit D3 (vector search V3.3 differee, feature flag "
                f"similar_films OFF). PAS un bug."
            )
    return tables, notes


# ---------------------------------------------------------- sites SQL en .py
def iter_py_files():
    for p in sorted(REPO_ROOT.joinpath("cinesort").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def sql_site_patterns(table: str):
    b = r"(?![A-Za-z0-9_])"
    kw = (
        r"(?P<kw>INSERT\s+OR\s+REPLACE\s+INTO|INSERT\s+OR\s+IGNORE\s+INTO|"
        r"INSERT\s+INTO|REPLACE\s+INTO|DELETE\s+FROM|UPDATE|FROM|JOIN)"
    )
    return re.compile(kw + r"\s+" + re.escape(table) + b, re.I)


WRITE_KW = {"INSERT INTO", "INSERT OR REPLACE INTO", "INSERT OR IGNORE INTO",
            "REPLACE INTO", "DELETE FROM", "UPDATE"}


def scan_sites(tables: dict):
    """Remplit write_sites / read_sites (fichier:ligne) pour chaque table."""
    sites = {t: {"write": [], "read": []} for t in tables}
    pats = {t: sql_site_patterns(t) for t in tables}
    for py in iter_py_files():
        text = read_text(py)
        rel = py.relative_to(REPO_ROOT).as_posix()
        for t, pat in pats.items():
            if t not in text:
                continue
            for m in pat.finditer(text):
                kw = re.sub(r"\s+", " ", m.group("kw").upper())
                ln = line_of(text, m.start())
                entry = f"{rel}:{ln} [{kw}]"
                if kw in WRITE_KW:
                    sites[t]["write"].append(entry)
                else:
                    sites[t]["read"].append(entry)
    return sites


# ------------------------------------------------------------- repositories
def store_attr_map():
    """sqlite_store.py : self.<attr> = <Class>(self) -> {class: attr}."""
    text = read_text(STORE_PY)
    return {m.group(2): m.group(1)
            for m in re.finditer(r"self\.(\w+)\s*=\s*(\w+Repository)\(self\)", text)}


def repo_methods_by_table(tables: dict):
    """Pour chaque repo .py : methodes publiques dont le corps mentionne la table.

    Retour: table -> {"files": {rel: attr}, "methods": {"read": [...], "write": [...]}}
    """
    cls2attr = store_attr_map()
    result = {t: {"files": {}, "methods": {"read": set(), "write": set()}} for t in tables}
    for repo_py in sorted(REPOS_DIR.glob("*.py")):
        if repo_py.name.startswith("_"):
            continue
        text = read_text(repo_py)
        rel = repo_py.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            attr = cls2attr.get(node.name, "?")
            for fn in node.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                seg = ast.get_source_segment(text, fn) or ""
                for t in tables:
                    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])", seg):
                        result[t]["files"][rel] = attr
                        pat = sql_site_patterns(t)
                        has_w = has_r = False
                        for m in pat.finditer(seg):
                            kw = re.sub(r"\s+", " ", m.group("kw").upper())
                            if kw in WRITE_KW:
                                has_w = True
                            else:
                                has_r = True
                        if not fn.name.startswith("_"):
                            if has_w:
                                result[t]["methods"]["write"].add(fn.name)
                            if has_r:
                                result[t]["methods"]["read"].add(fn.name)
    for t in result:
        result[t]["methods"]["read"] = sorted(result[t]["methods"]["read"])
        result[t]["methods"]["write"] = sorted(result[t]["methods"]["write"])
    return result


# ----------------------------------------------------------------- UI chain
def facade_map_for_support():
    """support module -> [facades qui le referencent] (facades/*.py + cinesort_api.py)."""
    refs = {}
    facade_files = sorted((UI_API_DIR / "facades").glob("*.py")) + [UI_API_DIR / "cinesort_api.py"]
    for f in facade_files:
        text = read_text(f)
        for mod in set(re.findall(r"[a-z_]+_support", text)):
            refs.setdefault(mod, set()).add(f.name)
    return {k: sorted(v) for k, v in refs.items()}


def ui_chain(tables: dict, sites: dict, repo_info: dict):
    """Remontee UI : fichiers ui/api avec SQL direct ou appel de methode repo."""
    support_to_facades = facade_map_for_support()
    method_callers: dict[str, list[str]] = {}
    all_methods = set()
    for t in tables:
        for kind in ("read", "write"):
            all_methods.update(repo_info[t]["methods"][kind])
    all_methods = {m for m in all_methods if len(m) >= 4 and m not in GENERIC_METHOD_BLOCKLIST}
    call_pats = {m: re.compile(r"\." + re.escape(m) + r"\s*\(") for m in all_methods}
    for py in iter_py_files():
        rel = py.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("cinesort/infra/db/"):
            continue  # repo lui-meme + wrappers store = pas des consommateurs
        text = read_text(py)
        for m, pat in call_pats.items():
            if pat.search(text):
                method_callers.setdefault(m, []).append(rel)

    out = {}
    for t in tables:
        ui_files = {}
        # 1) SQL direct dans cinesort/ui/
        for entry in sites[t]["read"] + sites[t]["write"]:
            rel = entry.split(":")[0].replace("\\", "/")
            if rel.startswith("cinesort/ui/"):
                ui_files.setdefault(rel, set()).add("sql_direct")
        # 2) appels de methodes repo depuis cinesort/ui/
        app_callers = set()
        for kind in ("read", "write"):
            for m in repo_info[t]["methods"][kind]:
                for rel in method_callers.get(m, []):
                    if rel.startswith("cinesort/ui/"):
                        ui_files.setdefault(rel, set()).add(f"repo:{m}")
                    elif rel.startswith(("cinesort/app/", "cinesort/domain/", "cinesort/infra/")):
                        app_callers.add(f"{rel} -> .{m}()")
        chain = {}
        for rel, hows in sorted(ui_files.items()):
            mod = Path(rel).stem
            if mod == "cinesort_api" or "/facades/" in rel:
                facades = ["(est lui-meme l'API/facade)"]
            else:
                facades = support_to_facades.get(mod, [])
            chain[rel] = {
                "via": sorted(hows),
                "facades": facades,
            }
        out[t] = {"ui_files": chain, "non_ui_callers": sorted(app_callers)}
    return out


# -------------------------------------------------------------------- main
def main():
    tables, mig_notes = extract_tables()
    sites = scan_sites(tables)
    repo_info = repo_methods_by_table(tables)
    ui = ui_chain(tables, sites, repo_info)

    matrix = {}
    for t in sorted(tables):
        w, r = sites[t]["write"], sites[t]["read"]
        if w and r:
            verdict = "CABLEE"
        elif w:
            verdict = "WRITE_ONLY"
        elif r:
            verdict = "READ_NEVER"
        else:
            verdict = "MORTE"
        matrix[t] = {
            "origin_migration": tables[t]["origin_migration"],
            "migrations": tables[t]["migrations"],
            "rebuilds": tables[t]["rebuilds"],
            "applied_by_manager": tables[t]["applied_by_manager"],
            "repositories": repo_info[t]["files"],
            "repo_methods": repo_info[t]["methods"],
            "write_sites_count": len(w),
            "read_sites_count": len(r),
            "write_sites": w[:60],
            "read_sites": r[:60],
            "ui": ui[t]["ui_files"],
            "ui_reachable": bool(ui[t]["ui_files"]),
            "non_ui_callers": ui[t]["non_ui_callers"][:40],
            "verdict": verdict,
            "annotation": ANNOTATIONS.get(t, ""),
        }

    # Check dedie : perceptual_reports vs quality_reports restent distinctes
    def repo_set(t):
        return set(matrix[t]["repositories"]) if t in matrix else set()
    pr, qr = repo_set("perceptual_reports"), repo_set("quality_reports")
    distinct_check = {
        "both_tables_exist": "perceptual_reports" in matrix and "quality_reports" in matrix,
        "perceptual_reports_repos": sorted(pr),
        "quality_reports_repos": sorted(qr),
        "repos_overlap": sorted(pr & qr),
        "distinct": ("perceptual_reports" in matrix and "quality_reports" in matrix
                     and matrix["perceptual_reports"]["origin_migration"]
                     != matrix["quality_reports"]["origin_migration"]),
    }

    stats = {}
    for t in matrix:
        stats[matrix[t]["verdict"]] = stats.get(matrix[t]["verdict"], 0) + 1

    out = {
        "matrice": "M7 - DB table -> repo -> UI",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "script": "docs/internal/verif_totale_2026_07/scripts_matrices/m7_db.py",
        "regles": {
            "sites": "scan cinesort/**/*.py (hors __pycache__), regex SQL ancree "
                     "(INSERT [OR ...] INTO | REPLACE INTO | UPDATE | DELETE FROM = write ; "
                     "FROM | JOIN = read), frontiere de mot sur le nom de table",
            "ddl_exclue": "les .sql de migrations ne comptent ni en read ni en write",
            "verdicts": "CABLEE=write+read ; WRITE_ONLY=write sans read ; "
                        "READ_NEVER=read sans write ; MORTE=aucun site",
            "ui": "fichier cinesort/ui/** avec SQL direct OU appel .methode_repo( ; "
                  "facade = facades/*.py ou cinesort_api.py referencant le module _support",
        },
        "table_count": len(matrix),
        "stats_verdicts": stats,
        "note_a_part_032": mig_notes,
        "check_perceptual_vs_quality_reports": distinct_check,
        "tables": matrix,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(matrix)} tables -> {OUT_JSON}")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    sys.exit(main())
