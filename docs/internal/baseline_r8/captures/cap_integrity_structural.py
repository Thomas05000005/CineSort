"""baseline_r8 — captures STRUCTURELLES (grep + line-read, deterministes) des
ruptures d'integrite / d'invariant identifiees.

Read-only TOTAL : ce script n'execute AUCUN code applicatif, n'ouvre aucune DB,
ne touche aucun filesystem hors lecture des sources du repo. Il ouvre chaque
fichier source en lecture, verifie que les lignes attendues contiennent bien le
fragment attendu (sinon il SCANNE et reporte la vraie ligne — anti-drift), et
imprime l'evidence cassee de chaque finding + un bloc RESUME json final.

Replayable depuis la racine repo :
    PYTHONPATH=. .venv313/Scripts/python.exe \
        docs/internal/baseline_r8/captures/cap_integrity_structural.py \
        > docs/internal/baseline_r8/captures/cap_integrity_structural.out.txt 2>&1

Findings couverts :
  F-V10-LOSER-ATOMIC    move losers/marked AVANT la boucle apply et HORS du
                        try/except par-row -> echec partiel non rollback-able.
  F-V10-LOSER-COUNTER   les helpers losers incrementent
                        duplicates_identical_moved_count (lockstep avec
                        _deleted_count) : aucun compteur loser dedie.
  F-V4B-RB1             mark_apply_operation_undo_status jamais appele dans
                        apply_rollback.py (=> undo_status des ops reste PENDING).
  F-V4B-RB2             reconcile_pending_batches scanne WHERE status='PENDING'
                        seulement ; un batch reverti est FAILED -> jamais
                        reconcilie.
  [4]/[5][7]            close_apply_batch(status='DONE') hardcode malgre les
                        erreurs ; statut FAILED fige AVANT rollback_forward.
  [18][19][20]          025 self-heal SELECT NULL->paused_at ;
                        _bootstrap_schema_latest sans insert schema_migrations ;
                        _is_idempotent_error ne couvre que OperationalError.
  F-V6-SCHEMA-IRC /     incremental_row_cache (mig 008) absent de
  F-V8-SCHEMA-REGISTRY  REQUIRED_SCHEMA_TABLES/SCHEMA_GROUPS ; vec_films_hash
                        (mig 032) absent du registry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

# Racine repo : captures/baseline_r8/internal/docs/<racine>
REPO = Path(__file__).resolve().parents[4]

APPLY_CORE = REPO / "cinesort" / "app" / "apply_core.py"
APPLY_ROLLBACK = REPO / "cinesort" / "app" / "apply_rollback.py"
APPLY_RECON = REPO / "cinesort" / "app" / "apply_batches_reconciliation.py"
APPLY_SUPPORT = REPO / "cinesort" / "ui" / "api" / "apply_support.py"
MIG_MANAGER = REPO / "cinesort" / "infra" / "db" / "migration_manager.py"
SQLITE_STORE = REPO / "cinesort" / "infra" / "db" / "sqlite_store.py"
MIG_025 = REPO / "cinesort" / "infra" / "db" / "migrations" / "025_run_pause_status.sql"
SCAN_REPO = REPO / "cinesort" / "infra" / "db" / "repositories" / "scan.py"

RESUME: dict = {}


# --------------------------------------------------------------------------- #
# Helpers deterministes (lecture seule)                                        #
# --------------------------------------------------------------------------- #
def _lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _show(path: Path, lineno: int, label: str = "") -> None:
    """Imprime une ligne 1-based avec son numero (cat -n style)."""
    rel = path.relative_to(REPO)
    try:
        txt = _lines(path)[lineno - 1]
    except IndexError:
        print(f"    {rel}:{lineno}  <hors fichier>")
        return
    tag = f" [{label}]" if label else ""
    print(f"    {rel}:{lineno}{tag}  {txt.rstrip()}")


def _verify(path: Path, expected_line: int, needle: str) -> int:
    """Retourne la VRAIE ligne 1-based contenant `needle`.

    Si la ligne attendue matche -> renvoie expected_line. Sinon scanne tout le
    fichier (anti-drift) et renvoie la 1re occurrence (ou -1). Imprime un avis
    de drift le cas echeant.
    """
    rel = path.relative_to(REPO)
    raw = _lines(path)
    if 1 <= expected_line <= len(raw) and needle in raw[expected_line - 1]:
        return expected_line
    for i, line in enumerate(raw, start=1):
        if needle in line:
            print(f"    [DRIFT] {rel}: attendu '{needle}' L{expected_line}, "
                  f"trouve L{i}")
            return i
    print(f"    [ABSENT] {rel}: '{needle}' introuvable (attendu L{expected_line})")
    return -1


def _count(path: Path, needle: str) -> int:
    return sum(1 for line in _lines(path) if needle in line)


def _grep(path: Path, needle: str) -> List[Tuple[int, str]]:
    return [(i, line) for i, line in enumerate(_lines(path), start=1) if needle in line]


def _enclosing_def(path: Path, lineno: int) -> Optional[Tuple[int, str]]:
    """Remonte vers la def/for/try englobant le plus proche par indentation."""
    raw = _lines(path)
    if not (1 <= lineno <= len(raw)):
        return None
    base_indent = len(raw[lineno - 1]) - len(raw[lineno - 1].lstrip())
    for i in range(lineno - 1, 0, -1):
        line = raw[i - 1]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent < base_indent and line.lstrip().startswith(("def ", "for ", "try:")):
            return (i, line.strip())
    return None


def _hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# --------------------------------------------------------------------------- #
# F-V10-LOSER-ATOMIC                                                           #
# --------------------------------------------------------------------------- #
def cap_loser_atomic() -> None:
    _hr("F-V10-LOSER-ATOMIC : move losers/marked HORS du try/except par-row")
    print("Mecanisme : move_duplicate_losers_to_user_decided + "
          "move_marked_for_deletion_to_bucket sont appeles AVANT la boucle\n"
          "for-row et EN DEHORS du try/except par-row -> si un move loser\n"
          "echoue a mi-parcours, aucune compensation/rollback intra-batch.\n")

    l_loser = _verify(APPLY_CORE, 1303, "move_duplicate_losers_to_user_decided(")
    l_marked = _verify(APPLY_CORE, 1320, "move_marked_for_deletion_to_bucket(")
    l_for = _verify(APPLY_CORE, 1437, "for idx, row in enumerate(rows, start=1):")
    l_try = _verify(APPLY_CORE, 1550, "        try:")
    # 1er handler du try par-row
    handlers = [n for n, _ in _grep(APPLY_CORE, "        except ") if n > l_try]
    l_except = min(handlers) if handlers else -1

    print("\n  Appels losers/marked (AVANT la boucle) :")
    _show(APPLY_CORE, l_loser, "appel loser")
    _show(APPLY_CORE, l_marked, "appel marked")
    print("\n  Boucle par-row + try/except par-row (APRES les appels ci-dessus) :")
    _show(APPLY_CORE, l_for, "for-row")
    _show(APPLY_CORE, l_try, "try par-row")
    _show(APPLY_CORE, l_except, "1er except par-row")

    outside = (l_loser < l_for) and (l_marked < l_for) and (l_loser < l_try) and (l_marked < l_try)
    print(f"\n  appel_loser({l_loser}) et appel_marked({l_marked}) < for-row({l_for}) "
          f"< try-par-row({l_try}) : {outside}")
    print(f"  => les moves losers/marked ne sont JAMAIS dans le try par-row "
          f"[{l_try}..{l_except}] : {outside}")

    RESUME["F-V10-LOSER-ATOMIC"] = {
        "call_move_losers": l_loser,
        "call_move_marked": l_marked,
        "for_row_loop": l_for,
        "per_row_try": l_try,
        "per_row_first_except": l_except,
        "calls_outside_loop_and_try": outside,
        "verdict": "CONFIRME" if outside else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# F-V10-LOSER-COUNTER                                                          #
# --------------------------------------------------------------------------- #
def cap_loser_counter() -> None:
    _hr("F-V10-LOSER-COUNTER : losers incrementent duplicates_identical_moved_count "
        "(lockstep _deleted_count), aucun compteur loser dedie")
    print("Mecanisme : move_duplicate_losers_to_user_decided incremente le\n"
          "MEME compteur (duplicates_identical_moved_count) que la suppression\n"
          "DUPLICATE_IDENTICAL, lequel est increment lockstep avec\n"
          "duplicates_identical_deleted_count -> un loser deplace gonfle le\n"
          "compteur de doublons 'supprimes', il n'existe aucun compteur loser.\n")

    inc_690 = _verify(APPLY_CORE, 690, "res.duplicates_identical_moved_count += 1")
    inc_691 = _verify(APPLY_CORE, 691, "res.duplicates_identical_deleted_count += 1")
    print("  Lockstep moved/deleted dans le chemin DUPLICATE_IDENTICAL :")
    _show(APPLY_CORE, inc_690, "moved++")
    _show(APPLY_CORE, inc_691, "deleted++ (lockstep)")

    print("\n  Increments DANS les helpers losers (reutilisent le compteur doublons) :")
    for ln in (1042, 1056, 1077):
        real = _verify(APPLY_CORE, ln, "res.duplicates_identical_moved_count += 1")
        _show(APPLY_CORE, real, "loser path moved++")

    # Preuve negative : aucun compteur 'loser' dedie dans ApplyResult / apply_core.
    loser_counter_hits = [
        (n, line) for n, line in _grep(APPLY_CORE, "_count")
        if "loser" in line.lower() and "+= 1" in line
    ]
    # Le chemin 'marked' a SON propre compteur (contraste) :
    marked_counter = [n for n, _ in _grep(APPLY_CORE, "res.marked_for_deletion_moved_count += 1")]

    print("\n  Contraste : le chemin 'marked_for_deletion' a SON compteur dedie :")
    for ln in marked_counter[:3]:
        _show(APPLY_CORE, ln, "marked path (compteur dedie)")
    print(f"\n  compteur loser dedie incremente dans apply_core : "
          f"{len(loser_counter_hits)} (attendu 0)")

    RESUME["F-V10-LOSER-COUNTER"] = {
        "lockstep_moved_line": inc_690,
        "lockstep_deleted_line": inc_691,
        "loser_increments_shared_counter": [1042, 1056, 1077],
        "dedicated_loser_counter_increments": len(loser_counter_hits),
        "marked_path_has_dedicated_counter_lines": marked_counter[:3],
        "verdict": "CONFIRME" if len(loser_counter_hits) == 0 else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# F-V4B-RB1                                                                    #
# --------------------------------------------------------------------------- #
def cap_rb1() -> None:
    _hr("F-V4B-RB1 : mark_apply_operation_undo_status JAMAIS appele dans "
        "apply_rollback.py")
    print("Mecanisme : rollback_forward ne met a jour QUE "
          "apply_batch_modes.rollback_status (via mark_rollback_status).\n"
          "Il n'appelle jamais mark_apply_operation_undo_status -> les ops\n"
          "revertees gardent undo_status='PENDING' en base (etat incoherent).\n")

    n_in_rollback = _count(APPLY_ROLLBACK, "mark_apply_operation_undo_status")
    hits_support = _grep(APPLY_SUPPORT, "mark_apply_operation_undo_status(")
    # Ce que rollback_forward appelle reellement a la place :
    mark_rb = _grep(APPLY_ROLLBACK, "mark_rollback_status(")

    print(f"  apply_rollback.py : occurrences de "
          f"mark_apply_operation_undo_status = {n_in_rollback} (attendu 0)")
    print(f"  apply_support.py  : occurrences = {len(hits_support)} "
          f"(prouve que l'API existe et est utilisee ailleurs)")
    for n, _ in hits_support[:3]:
        _show(APPLY_SUPPORT, n, "usage cote support")
    print("\n  Ce que rollback_forward met a jour A LA PLACE "
          "(rollback_status seulement) :")
    for n, _ in mark_rb[:4]:
        _show(APPLY_ROLLBACK, n, "rollback_status only")

    RESUME["F-V4B-RB1"] = {
        "mark_undo_status_in_apply_rollback": n_in_rollback,
        "mark_undo_status_in_apply_support": len(hits_support),
        "mark_rollback_status_calls_in_rollback": [n for n, _ in mark_rb],
        "verdict": "CONFIRME" if n_in_rollback == 0 and len(hits_support) > 0 else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# F-V4B-RB2                                                                    #
# --------------------------------------------------------------------------- #
def cap_rb2() -> None:
    _hr("F-V4B-RB2 : reconcile scanne WHERE status='PENDING' seulement ; "
        "un batch reverti est FAILED -> jamais reconcilie")
    print("Mecanisme : _list_pending_batches filtre status='PENDING'. Or\n"
          "le chemin d'echec apply fige apply_batches.status='FAILED' AVANT\n"
          "rollback_forward, et rollback_forward ne retouche jamais\n"
          "apply_batches.status -> un batch FAILED echappe a la reconciliation.\n")

    l_where = _verify(APPLY_RECON, 77, "WHERE status = 'PENDING'")
    _show(APPLY_RECON, l_where, "filtre PENDING-only")
    # Statut FAILED fige cote apply_support AVANT rollback_forward :
    l_failed = _verify(APPLY_SUPPORT, 2215, 'status="FAILED"')
    l_rbfwd = _verify(APPLY_SUPPORT, 2238, "_atomic_rollback_forward(")
    print("\n  Cote apply (chemin d'echec) : FAILED fige AVANT rollback_forward :")
    _show(APPLY_SUPPORT, l_failed, "close_apply_batch(FAILED)")
    _show(APPLY_SUPPORT, l_rbfwd, "rollback_forward (apres)")
    # rollback_forward ne touche que rollback_status, pas apply_batches.status :
    touches_status = _count(APPLY_ROLLBACK, "apply_batches") + \
        _count(APPLY_ROLLBACK, "close_apply_batch")
    print(f"\n  apply_rollback.py touche apply_batches.status/close_apply_batch : "
          f"{touches_status} fois (attendu 0 -> statut reste FAILED)")

    failed_before_rb = (l_failed != -1 and l_rbfwd != -1 and l_failed < l_rbfwd)
    RESUME["F-V4B-RB2"] = {
        "reconcile_where_pending_line": l_where,
        "close_failed_line": l_failed,
        "rollback_forward_call_line": l_rbfwd,
        "failed_frozen_before_rollback": failed_before_rb,
        "rollback_touches_batch_status": touches_status,
        "verdict": "CONFIRME" if (l_where != -1 and failed_before_rb and touches_status == 0)
                   else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# [4]/[5][7]                                                                   #
# --------------------------------------------------------------------------- #
def cap_close_done_hardcoded() -> None:
    _hr("[4]/[5][7] : close_apply_batch(status='DONE') hardcode malgre erreurs ; "
        "FAILED fige avant rollback_forward")
    print("Mecanisme : le chemin de cloture normal hardcode status='DONE'\n"
          "independamment de result.errors (l'auditeur distingue pourtant\n"
          "DONE/PARTIAL juste au-dessus). Le chemin d'echec fige FAILED avant\n"
          "rollback_forward (cf RB2).\n")

    l_close = _verify(APPLY_SUPPORT, 1565, "store.apply.close_apply_batch(")
    l_status_done = _verify(APPLY_SUPPORT, 1567, 'status="DONE"')
    # L'auditeur SAIT distinguer DONE/PARTIAL (preuve du contraste) :
    audit_end = _grep(APPLY_SUPPORT, 'status="DONE" if getattr(result, "errors"')
    print("  Cloture normale (DONE hardcode) :")
    _show(APPLY_SUPPORT, l_close, "close_apply_batch")
    _show(APPLY_SUPPORT, l_status_done, "status='DONE' hardcode")
    if audit_end:
        print("\n  Contraste : l'auditeur, lui, distingue DONE/PARTIAL sur result.errors :")
        _show(APPLY_SUPPORT, audit_end[0][0], "auditor.end DONE/PARTIAL")

    RESUME["[4]/[5][7]"] = {
        "close_apply_batch_line": l_close,
        "status_done_hardcoded_line": l_status_done,
        "auditor_distinguishes_done_partial_line": audit_end[0][0] if audit_end else -1,
        "verdict": "CONFIRME" if l_status_done != -1 else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# [18] 025 self-heal SELECT NULL -> paused_at                                  #
# --------------------------------------------------------------------------- #
def cap_025_null_paused() -> None:
    _hr("[18] 025 (run_pause_status) : INSERT INTO runs_new ... SELECT ... NULL "
        "pour paused_at")
    print("Mecanisme : la recreation de table 'runs' reinjecte les rows via\n"
          "SELECT, mais hardcode NULL pour la colonne paused_at -> tout\n"
          "paused_at pre-existant est ecrase a NULL au self-heal/migration.\n")

    raw = _lines(MIG_025)
    insert_idx = next((i for i, l in enumerate(raw, start=1)
                       if "INSERT INTO runs_new" in l), -1)
    select_idx = next((i for i, l in enumerate(raw, start=1)
                       if l.strip() == "SELECT"), -1)
    # Derniere ligne de la projection SELECT : termine par 'NULL' avant FROM runs.
    null_idx = next((i for i, l in enumerate(raw, start=1)
                     if l.strip().rstrip(",").endswith("NULL") and i > select_idx), -1)
    from_idx = next((i for i, l in enumerate(raw, start=1)
                     if "FROM runs" in l and i > select_idx), -1)
    print("  Bloc INSERT ... SELECT (paused_at force a NULL) :")
    if insert_idx != -1:
        _show(MIG_025, insert_idx, "INSERT INTO runs_new")
    if select_idx != -1:
        _show(MIG_025, select_idx, "SELECT")
    if null_idx != -1:
        _show(MIG_025, null_idx, "NULL <- ecrase paused_at")
    if from_idx != -1:
        _show(MIG_025, from_idx, "FROM runs")
    # La colonne paused_at est bien la 15e/derniere de la liste INSERT.
    has_paused_col = any("paused_at" in l for l in raw)

    RESUME["[18]_025_null_paused_at"] = {
        "file": str(MIG_025.relative_to(REPO)),
        "insert_line": insert_idx,
        "select_line": select_idx,
        "null_projection_line": null_idx,
        "from_runs_line": from_idx,
        "paused_at_column_present": has_paused_col,
        "verdict": "CONFIRME" if null_idx != -1 and has_paused_col else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# [19] _bootstrap_schema_latest : aucun insert schema_migrations               #
# --------------------------------------------------------------------------- #
def cap_bootstrap_no_schema_migrations() -> None:
    _hr("[19] _bootstrap_schema_latest : aucun insert dans schema_migrations")
    print("Mecanisme : le fallback bootstrap commit user_version mais n'appelle\n"
          "jamais _record_migration / n'INSERT pas dans schema_migrations ->\n"
          "apres un self-heal bootstrap, schema_migrations est incoherent avec\n"
          "l'etat reel du schema.\n")

    raw = _lines(SQLITE_STORE)
    def_idx = next((i for i, l in enumerate(raw, start=1)
                    if "def _bootstrap_schema_latest(self)" in l), -1)
    # Borne de fin : prochaine def au meme indent (4 espaces).
    end_idx = len(raw)
    if def_idx != -1:
        for i in range(def_idx, len(raw)):
            line = raw[i]
            if line.startswith("    def ") and i + 1 != def_idx:
                end_idx = i
                break
    body = raw[def_idx - 1:end_idx] if def_idx != -1 else []
    has_record = any("_record_migration" in l for l in body)
    has_insert_sm = any("schema_migrations" in l for l in body)
    has_uv = next((j for j, l in enumerate(body, start=def_idx)
                   if "PRAGMA user_version" in l), -1)
    print(f"  def _bootstrap_schema_latest -> ligne {def_idx} "
          f"(corps L{def_idx}..{end_idx})")
    if has_uv != -1:
        _show(SQLITE_STORE, has_uv, "commit user_version (mais...)")
    print(f"  '_record_migration' present dans le corps   : {has_record} (attendu False)")
    print(f"  'schema_migrations' present dans le corps    : {has_insert_sm} (attendu False)")
    # Contraste : apply() de MigrationManager, lui, appelle _record_migration.
    rec_in_mgr = _grep(MIG_MANAGER, "self._record_migration(conn")
    print("\n  Contraste : MigrationManager.apply appelle bien _record_migration :")
    for n, _ in rec_in_mgr[:1]:
        _show(MIG_MANAGER, n, "apply() trace schema_migrations")

    RESUME["[19]_bootstrap_no_schema_migrations"] = {
        "bootstrap_def_line": def_idx,
        "bootstrap_body_range": [def_idx, end_idx],
        "record_migration_in_body": has_record,
        "schema_migrations_in_body": has_insert_sm,
        "user_version_commit_line": has_uv,
        "manager_apply_records_line": rec_in_mgr[0][0] if rec_in_mgr else -1,
        "verdict": "CONFIRME" if (not has_record and not has_insert_sm) else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# [20] _is_idempotent_error : OperationalError seulement                       #
# --------------------------------------------------------------------------- #
def cap_idempotent_operational_only() -> None:
    _hr("[20] _is_idempotent_error : ne couvre que sqlite3.OperationalError")
    print("Mecanisme : _is_idempotent_error type son parametre en\n"
          "sqlite3.OperationalError, et il n'est attrape que dans des blocs\n"
          "`except sqlite3.OperationalError` -> une migration partielle qui\n"
          "leve IntegrityError/DatabaseError n'est PAS toleree en idempotence.\n")

    l_def = _verify(MIG_MANAGER, 23,
                    "def _is_idempotent_error(exc: sqlite3.OperationalError)")
    _show(MIG_MANAGER, l_def, "signature OperationalError-only")
    # Sites d'appel : tous gardes par except sqlite3.OperationalError.
    callers = _grep(MIG_MANAGER, "_is_idempotent_error(stmt_exc)")
    print("\n  Sites d'appel (tous sous except sqlite3.OperationalError) :")
    for n, _ in callers:
        _show(MIG_MANAGER, n, "appel")
        enc = _enclosing_def(MIG_MANAGER, n)
        # Cherche le except le plus proche au-dessus.
        above = [m for m, line in _grep(MIG_MANAGER, "except sqlite3.OperationalError")
                 if m < n]
        if above:
            _show(MIG_MANAGER, max(above), "  garde par")
    # Idem dans le bootstrap (sqlite_store).
    boot_callers = _grep(SQLITE_STORE, "_is_idempotent_error(stmt_exc)")
    if boot_callers:
        print("\n  Idem dans _bootstrap_schema_latest (sqlite_store.py) :")
        for n, _ in boot_callers:
            _show(SQLITE_STORE, n, "appel bootstrap")
            above = [m for m, line in _grep(SQLITE_STORE, "except sqlite3.OperationalError")
                     if m < n]
            if above:
                _show(SQLITE_STORE, max(above), "  garde par")
    # Fragments tolERES (preuve : que des messages 'duplicate column'/'already exists').
    frags = _grep(MIG_MANAGER, '"duplicate column name"') + \
        _grep(MIG_MANAGER, '"already exists"')
    print("\n  Fragments tolERES (whitelist statique) :")
    for n, line in frags:
        print(f"    {MIG_MANAGER.relative_to(REPO)}:{n}  {line.strip()}")

    RESUME["[20]_idempotent_operational_only"] = {
        "def_line": l_def,
        "manager_call_lines": [n for n, _ in callers],
        "bootstrap_call_lines": [n for n, _ in boot_callers],
        "tolerated_fragments_lines": [n for n, _ in frags],
        "verdict": "CONFIRME" if l_def != -1 else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# F-V6-SCHEMA-IRC / F-V8-SCHEMA-REGISTRY                                       #
# --------------------------------------------------------------------------- #
def cap_schema_registry() -> None:
    _hr("F-V6-SCHEMA-IRC / F-V8-SCHEMA-REGISTRY : incremental_row_cache (mig 008) "
        "+ vec_films_hash (mig 032) absents du registry")
    print("Mecanisme : REQUIRED_SCHEMA_TABLES + SCHEMA_GROUPS sont la liste de\n"
          "verite du self-heal de schema. La table incremental_row_cache (mig\n"
          "008) et vec_films_hash (mig 032) n'y figurent pas -> le filet\n"
          "self-healing ne se declenche jamais pour ces tables.\n")

    raw = _lines(SQLITE_STORE)
    req_start = next((i for i, l in enumerate(raw, start=1)
                      if "REQUIRED_SCHEMA_TABLES = (" in l), -1)
    grp_start = next((i for i, l in enumerate(raw, start=1)
                      if "SCHEMA_GROUPS:" in l), -1)
    print(f"  REQUIRED_SCHEMA_TABLES debute L{req_start} ; "
          f"SCHEMA_GROUPS debute L{grp_start}")

    def _in_registry(table: str) -> dict:
        in_req = any(f'"{table}"' in l for l in raw)
        # restreint au bloc SCHEMA_GROUPS pour eviter faux positifs ailleurs
        return {"present_anywhere_in_registry_file": in_req}

    # incremental_row_cache : present dans la migration 008 mais pas le registry.
    irc_in_reg = any('"incremental_row_cache"' in l for l in raw)
    # le groupe 'incremental' liste explicitement les 2 AUTRES tables :
    incr_group = _grep(SQLITE_STORE, '"incremental":')
    print("\n  incremental_row_cache (table de migration 008_incr_row_cache.sql) :")
    print(f"    present dans REQUIRED_SCHEMA_TABLES/registry : {irc_in_reg} (attendu False)")
    if incr_group:
        _show(SQLITE_STORE, incr_group[0][0], "groupe 'incremental' (2 autres tables seulement)")
    # Le commentaire du repo scan.py confirme l'omission noir sur blanc :
    scan_comment = _grep(SCAN_REPO, 'pas listee dans SCHEMA_GROUPS["incremental"]')
    if scan_comment:
        print("\n  Aveu explicite dans repositories/scan.py :")
        _show(SCAN_REPO, scan_comment[0][0], "commentaire d'aveu")

    # vec_films_hash : present dans migration 032 mais pas le registry.
    vec_in_reg = any("vec_films_hash" in l for l in raw)
    print("\n  vec_films_hash (table de migration 032-vector-search-tables.sql) :")
    print(f"    present dans REQUIRED_SCHEMA_TABLES/registry : {vec_in_reg} (attendu False)")

    # Note honnete : migration 030 (film_field_locks) EST, elle, dans le registry.
    ffl_in_reg = any('"film_field_locks"' in l for l in raw)
    print(f"\n  NOTE (anti-faux-positif) : film_field_locks (mig 030) present "
          f"dans le registry : {ffl_in_reg} (=> le gap concerne 008 et 032, "
          f"PAS 030)")

    RESUME["F-V6/F-V8-SCHEMA-REGISTRY"] = {
        "required_schema_tables_line": req_start,
        "schema_groups_line": grp_start,
        "incremental_row_cache_in_registry": irc_in_reg,
        "vec_films_hash_in_registry": vec_in_reg,
        "film_field_locks_030_in_registry": ffl_in_reg,
        "scan_repo_admission_line": scan_comment[0][0] if scan_comment else -1,
        "verdict": "CONFIRME" if (not irc_in_reg and not vec_in_reg) else "non-reproduit",
    }


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    print(f"REPO = {REPO}")
    print("Captures STRUCTURELLES (read-only, grep + line-read) — baseline_r8\n")
    cap_loser_atomic()
    cap_loser_counter()
    cap_rb1()
    cap_rb2()
    cap_close_done_hardcoded()
    cap_025_null_paused()
    cap_bootstrap_no_schema_migrations()
    cap_idempotent_operational_only()
    cap_schema_registry()

    _hr("RESUME (json)")
    print(json.dumps(RESUME, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
