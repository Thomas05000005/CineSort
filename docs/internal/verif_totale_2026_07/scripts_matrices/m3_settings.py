# -*- coding: utf-8 -*-
"""M3 — Matrice de cablage Settings write->read->effet (verif totale 2026-07).

REJOUABLE : python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m3_settings.py

Pipeline :
  1. Extrait les cles canoniques du GET settings depuis
     cinesort/ui/api/settings_support.py (AST, zero execution du code app) :
       - table _LITERAL_DEFAULTS (~100 defaults litteraux)
       - setdefault()/payload[...] dans apply_settings_defaults (derives)
       - data[...] + cles *_protection/*_warning dans read_settings (meta GET)
       - _has_<secret> generes par _mask_secrets (via _SECRET_FIELDS)
       - cles persistees par les _save_section_* (probe_timeout_s, retention_days,
         excluded_patterns, video_exts, ... reinjectees dans le GET via echo)
       - endpoints dedies (scan_max_workers, PRAGMA avances)
  2. Pour CHAQUE cle :
       - UI : occurrences mot-entier dans web/dashboard (js/html, hors tests/)
       - Backend : occurrences QUOTEES dans cinesort/**/*.py + app.py, classees
         lecture / ecriture / cle-de-dict / persistance (settings_support.py :
         classement par fonction englobante via ranges AST)
  3. Verdict : CABLEE / WRITE_ONLY / READ_ONLY / FANTOME / ALIAS_MORT.
     - lecture backend "consommatrice" = contexte read hors couche persistance
     - cas speciaux documentes (preuve fichier:ligne) dans SPECIAL_CASES

Sortie : docs/internal/verif_totale_2026_07/matrices/m3_settings.json (UTF-8).
Aucun fichier source n'est modifie. Aucune app/pytest lancee.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]  # .../CineSort/docs/internal/verif_totale_2026_07/scripts_matrices/m3.py
assert (REPO / "cinesort").is_dir(), f"repo root introuvable depuis {HERE} -> {REPO}"

SUPPORT = REPO / "cinesort" / "ui" / "api" / "settings_support.py"
OUT = REPO / "docs" / "internal" / "verif_totale_2026_07" / "matrices" / "m3_settings.json"

# ---------------------------------------------------------------------------
# Classement des fonctions de settings_support.py
# ---------------------------------------------------------------------------
# PERSISTANCE = read/write/defaults/mask/sections de save : une occurrence de la
# cle ici ne prouve PAS un effet runtime (c'est le tuyau, pas le robinet).
PERSISTENCE_FUNCS = {
    "read_settings", "write_settings", "apply_settings_defaults",
    "get_settings_payload", "save_settings_payload", "_save_settings_payload_locked",
    "_apply_naming_preset", "_apply_tmdb_key_persistence", "_apply_jellyfin_key_persistence",
    "_normalize_scopes", "_mask_secrets", "_unmask_secrets_for_save",
    "_migrate_root_to_roots", "_extract_protected_secret", "_persist_protected_secret",
    "extract_tmdb_key_from_settings_payload", "extract_jellyfin_key_from_settings_payload",
    "_backup_settings_before_write", "_rotate_settings_backups", "_build_save_result",
    "list_settings_backups", "restore_settings_backup", "settings_path",
    "_get_settings_write_lock", "validate_roots",
    "read_saved_root_candidates", "read_saved_roots_candidates",
    "set_scan_max_workers_payload", "set_advanced_pragma_settings_payload",
}
# CONSOMMATEURS dans settings_support.py : lecture qui branche un comportement
# (Config du scan/apply, resolution workers effectifs, etat PRAGMA actif...).
CONSUMER_FUNCS = {
    "build_cfg_from_settings", "build_cfg_from_run_row",
    "resolve_effective_scan_max_workers", "get_scan_max_workers_payload",
    "get_advanced_pragma_settings_payload",
    "resolve_payload_state_dir", "resolve_root_from_payload", "resolve_roots_from_payload",
    "test_tmdb_key", "test_jellyfin_connection",
}

# Cas speciaux documentes : verdict force + preuve. Utilise UNIQUEMENT quand le
# verdict mecanique serait factuellement trompeur.
SPECIAL_CASES: Dict[str, Tuple[str, str]] = {
    "remember_key": (
        "CABLEE",
        "lu par write_settings (settings_support.py:608,614) : gate la persistance "
        "DPAPI de tmdb_api_key -> effet reel bien que dans la couche persistance",
    ),
    "file_extensions": (
        "CABLEE",
        "jamais lu tel quel, mais miroir vers video_exts au save "
        "(_save_section_sources settings_support.py:1671) ; video_exts est lu par "
        "build_cfg_from_settings (settings_support.py:1009) -> effet scan reel",
    ),
    # Cles pilotees par des ENDPOINTS DEDIES : l'UI ne manipule pas le nom de la
    # cle settings mais des params renommes (mode/value/profile_name/...), donc le
    # scan mecanique la voit READ_ONLY a tort.
    "scan_max_workers_mode": (
        "CABLEE",
        "UI via endpoint dedie settings/set_scan_max_workers param 'mode' "
        "(parametres.js:2775) ; persiste settings_support.py:2362 ; lu par "
        "resolve_effective_scan_max_workers (settings_support.py:2257) + build_cfg (1024)",
    ),
    "scan_max_workers_value": (
        "CABLEE",
        "UI via endpoint dedie settings/set_scan_max_workers param 'value' "
        "(parametres.js:2775) ; persiste settings_support.py:2363 ; lu settings_support.py:2259/1025",
    ),
    "storage_profile_override": (
        "CABLEE",
        "UI via endpoint dedie settings/set_advanced_pragma_settings param 'profile_name' "
        "(parametres.js:2625) ; persiste settings_support.py:2457 ; lu get_advanced_pragma_settings_payload:2404",
    ),
    "sqlite_locking_mode_exclusive": (
        "CABLEE",
        "UI via endpoint dedie settings/set_advanced_pragma_settings param 'locking_mode_exclusive' "
        "(parametres.js:2627) ; persiste settings_support.py:2458 ; lu settings_support.py:2407",
    ),
}
# Alias declares dans le code (commentaire L944 : auto_check_updates = alias de
# update_check_enabled). Si l'alias n'a AUCUNE lecture consommatrice -> ALIAS_MORT.
# (verifie 2026-07-08 : app.py:165 lit l'alias -> vivant, la regle reste en garde-fou)
ALIAS_OF = {
    "auto_check_updates": "update_check_enabled",
}

# Lectures INDIRECTES prouvees manuellement : la cle est resolue via une table
# (pas de .get("cle") littral au site de lecture), invisible au scan mecanique.
# notify_service._SETTING_KEYS (L25-31) mappe event -> cle settings, lue en
# self._settings.get(key, True) (notify_service.py:84).
INDIRECT_READS: Dict[str, List[Dict[str, Any]]] = {
    k: [{
        "site": "cinesort/app/notify_service.py:84",
        "context": "read_get_indirect",
        "layer": "backend",
        "code": f"via _SETTING_KEYS (notify_service.py:25-31) -> self._settings.get('{k}', True)",
    }]
    for k in (
        "notifications_scan_triggered", "notifications_scan_done",
        "notifications_apply_done", "notifications_undo_done", "notifications_errors",
    )
}

# Notes factuelles ajoutees au verdict mecanique (sans le changer).
EXTRA_NOTES: Dict[str, str] = {
    "dry_run_apply": "effet client-side : status.js:248 pre-coche le toggle dry-run du "
                     "prochain run (le backend lit le flag dry_run du payload run, pas ce setting)",
    "expert_mode": "effet client-side : parametres.js:3337 classList 'is-expert' (masque les sections avancees)",
    "theme": "effet client-side : app.js:899 document.body.dataset.theme",
    "animation_level": "effet client-side (app.js applique le niveau d'animation)",
    "effect_speed": "effet client-side (variables CSS d'animation)",
    "glow_intensity": "effet client-side (variables CSS)",
    "light_intensity": "effet client-side (variables CSS)",
    "onboarding_completed": "expose en toggle parametres.js:328 mais AUCUN lecteur (ni wizard ni backend)",
    "notifications_enabled": "R8-069 : le gate desktop lit desormais desktop_notifications_enabled "
                             "(notify_service.py:75) et le miroir centre est inconditionnel -> ce "
                             "toggle 'notifications applicatives' n'a plus aucun lecteur",
    "notifications_scan_triggered": "lu via mapping notify_service mais AUCUN champ UI (toggle #108 jamais expose)",
    "auto_approve_enabled": "toggle 'Approbation automatique' parametres.js:105 : aucune logique "
                            "d'auto-approbation ne lit la cle dans cinesort/",
    "auto_approve_threshold": "seuil parametres.js:106 : jamais lu (get_auto_approved_summary compte "
                              "des decisions existantes, n'applique rien)",
    "auto_quarantine_corrupted": "default + save section + reset list + test de presence, mais aucun "
                                 "consommateur ni champ UI (feature M-2 jamais cablee)",
}

WORD_RE_TMpl = r"(?<![A-Za-z0-9_$-]){k}(?![A-Za-z0-9_$-])"


# ---------------------------------------------------------------------------
# 1. Extraction AST des cles canoniques
# ---------------------------------------------------------------------------

def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_canonical_keys(src: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Tuple[int, int]]]:
    tree = ast.parse(src)
    keys: Dict[str, Dict[str, Any]] = {}
    func_ranges: Dict[str, Tuple[int, int]] = {}

    def add(key: str, provenance: str, line: int, default: Any = None) -> None:
        if not key or key.startswith("_orig_"):
            return
        entry = keys.setdefault(key, {"provenances": [], "default": None})
        tag = f"{provenance}@settings_support.py:{line}"
        if tag not in entry["provenances"]:
            entry["provenances"].append(tag)
        if default is not None and entry["default"] is None:
            entry["default"] = default

    funcs: Dict[str, ast.FunctionDef] = {}
    secret_fields: List[str] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
            func_ranges[node.name] = (node.lineno, node.end_lineno or node.lineno)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_LITERAL_DEFAULTS":
                    for elt in node.value.elts:  # type: ignore[attr-defined]
                        if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                            k = _const_str(elt.elts[0])
                            if k:
                                try:
                                    dv = ast.literal_eval(elt.elts[1])
                                except Exception:
                                    dv = "<expr>"
                                add(k, "literal_default", elt.lineno, dv)
                elif isinstance(tgt, ast.Name) and tgt.id == "_SECRET_FIELDS":
                    for elt in node.value.elts:  # type: ignore[attr-defined]
                        s = _const_str(elt)
                        if s:
                            secret_fields.append(s)

    def scan_func(name: str, provenance: str, receivers: Tuple[str, ...],
                  take_setdefault: bool = False, take_return_dict: bool = False,
                  take_meta_strings: bool = False) -> None:
        fn = funcs.get(name)
        if fn is None:
            return
        for node in ast.walk(fn):
            # payload.setdefault("k", ...)
            if take_setdefault and isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr == "setdefault" and node.args:
                    k = _const_str(node.args[0])
                    if k:
                        add(k, provenance, node.lineno)
            # receiver["k"] = ...
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                            and tgt.value.id in receivers):
                        k = _const_str(tgt.slice)
                        if k:
                            add(k, provenance, node.lineno)
            # return { "k": ... }
            if take_return_dict and isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for kn in node.value.keys:
                    k = _const_str(kn) if kn is not None else None
                    if k:
                        add(k, provenance, kn.lineno)  # type: ignore[union-attr]
            # cles meta *_protection / *_warning (tuples de read_settings)
            if take_meta_strings and isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[a-z0-9_]+(_protection|_warning)", node.value):
                    add(node.value, provenance, node.lineno)

    scan_func("apply_settings_defaults", "apply_settings_defaults",
              ("payload",), take_setdefault=True)
    scan_func("read_settings", "read_settings_meta", ("data",), take_meta_strings=True)
    for fname in sorted(funcs):
        if fname.startswith("_save_section_"):
            scan_func(fname, fname, ("out",), take_return_dict=True)
    scan_func("_apply_naming_preset", "_apply_naming_preset", ("to_save",))
    scan_func("_apply_tmdb_key_persistence", "_apply_tmdb_key_persistence", ("to_save",))
    scan_func("_apply_jellyfin_key_persistence", "_apply_jellyfin_key_persistence", ("to_save",))
    scan_func("_save_settings_payload_locked", "save_dispatcher", ("to_save",))
    scan_func("set_scan_max_workers_payload", "endpoint_scan_max_workers", ("data",))
    scan_func("set_advanced_pragma_settings_payload", "endpoint_pragma", ("data",))

    # _mask_secrets : _has_<field> pour chaque secret + le champ lui-meme
    mask_fn = funcs.get("_mask_secrets")
    mask_line = mask_fn.lineno if mask_fn else 0
    for f in secret_fields:
        add(f, "secret_field", mask_line)
        add(f"_has_{f}", "mask_secrets_meta", mask_line)

    return keys, func_ranges


# ---------------------------------------------------------------------------
# 2. Scan des occurrences (backend python + UI js/html)
# ---------------------------------------------------------------------------

def _strip_line_comment(line: str, comment_start: str) -> str:
    """Coupe le commentaire de fin de ligne en respectant les quotes simples/doubles."""
    quote = None
    i = 0
    n = len(line)
    cs0 = comment_start[0]
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in ("'", '"', "`"):
                quote = c
            elif c == cs0 and line.startswith(comment_start, i):
                return line[:i]
        i += 1
    return line


def classify_py_context(line: str, m: re.Match) -> str:
    """Classifie l'occurrence quotee d'une cle dans une ligne python."""
    before = line[: m.start()]
    after = line[m.end():]
    if re.search(r"\.get\(\s*$", before):
        return "read_get"
    if re.search(r"\.pop\(\s*$", before):
        return "write_pop"
    if re.search(r"\.setdefault\(\s*$", before):
        return "write_setdefault"
    if re.search(r"\[\s*$", before):
        # subscript : lecture ou ecriture selon ce qui suit "]"
        m2 = re.match(r"\s*\]\s*(=[^=])?", after)
        if m2 and m2.group(1):
            return "write_subscript"
        return "read_subscript"
    if re.match(r"\s*:", after):
        return "dict_key"
    if re.match(r"\s+in\s", after) or after.startswith(" in "):
        return "read_membership"
    if re.search(r"\bin\s+$", before):
        return "read_membership"
    return "mention"


def classify_js_context(line: str, m: re.Match) -> str:
    before = line[: m.start()]
    after = line[m.end():]
    if re.search(r"key\s*:\s*[\"'`]$", before):
        return "field_registry"  # parametres.js { key: "..." }
    if re.match(r"\s*[\"'`]?\s*:", after):
        return "object_key"
    if re.search(r"\.\s*$", before):
        return "property_access"
    if re.search(r"\[\s*[\"'`]$", before):
        return "bracket_access"
    return "mention"


READ_CONTEXTS_PY = {"read_get", "read_subscript", "read_membership"}


def scan_backend(repo: Path, all_keys: List[str],
                 support_ranges: Dict[str, Tuple[int, int]]) -> Dict[str, List[Dict[str, Any]]]:
    quoted_re = re.compile(r"[\"'](" + "|".join(re.escape(k) for k in all_keys) + r")[\"']")
    hits: Dict[str, List[Dict[str, Any]]] = {k: [] for k in all_keys}

    def support_func_for(line_no: int) -> Optional[str]:
        for name, (a, b) in support_ranges.items():
            if a <= line_no <= b:
                return name
        return None

    files = sorted(repo.glob("cinesort/**/*.py")) + [repo / "app.py"]
    for path in files:
        if "__pycache__" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(repo).as_posix()
        is_support = path.resolve() == SUPPORT.resolve()
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        for ln, raw in enumerate(text.splitlines(), 1):
            if raw.lstrip().startswith("#"):
                continue
            line = _strip_line_comment(raw, "#")
            for m in quoted_re.finditer(line):
                key = m.group(1)
                ctx = classify_py_context(line, m)
                layer = "backend"
                if is_support:
                    fn = support_func_for(ln)
                    if fn in CONSUMER_FUNCS:
                        layer = "support_consumer"
                    elif fn is None or fn in PERSISTENCE_FUNCS or fn.startswith("_save_section_"):
                        layer = "persistence"
                    else:
                        layer = "persistence"  # defaut prudent dans settings_support.py
                hits[key].append({
                    "site": f"{rel}:{ln}",
                    "context": ctx,
                    "layer": layer,
                    "code": raw.strip()[:140],
                })
    return hits


def scan_ui(repo: Path, all_keys: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    word_re = re.compile(r"(?<![A-Za-z0-9_$-])(" + "|".join(re.escape(k) for k in all_keys) + r")(?![A-Za-z0-9_$-])")
    hits: Dict[str, List[Dict[str, Any]]] = {k: [] for k in all_keys}
    base = repo / "web" / "dashboard"
    files = [p for p in sorted(base.rglob("*"))
             if p.suffix in {".js", ".html"} and p.is_file()
             and "tests" not in p.relative_to(base).parts]
    for path in files:
        rel = path.relative_to(repo).as_posix()
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        in_block_comment = False
        for ln, raw in enumerate(text.splitlines(), 1):
            stripped = raw.lstrip()
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if stripped.startswith("/*"):
                if "*/" not in stripped:
                    in_block_comment = True
                continue
            line = _strip_line_comment(raw, "//")
            for m in word_re.finditer(line):
                key = m.group(1)
                hits[key].append({
                    "site": f"{rel}:{ln}",
                    "context": classify_js_context(line, m),
                    "code": raw.strip()[:140],
                })
    return hits


# ---------------------------------------------------------------------------
# 3. Verdicts
# ---------------------------------------------------------------------------

def main() -> int:
    src = SUPPORT.read_text(encoding="utf-8-sig")
    keys_meta, func_ranges = extract_canonical_keys(src)
    all_keys = sorted(keys_meta)

    backend_hits = scan_backend(REPO, all_keys, func_ranges)
    ui_hits = scan_ui(REPO, all_keys)

    matrix: Dict[str, Any] = {}
    stats: Dict[str, int] = {}
    meta_re = re.compile(r"^_has_|(_protection|_warning)$")
    for key in all_keys:
        bh = backend_hits[key]
        uh = ui_hits[key]
        consumer_reads = [h for h in bh
                          if h["layer"] in ("backend", "support_consumer")
                          and h["context"] in READ_CONTEXTS_PY]
        consumer_reads += INDIRECT_READS.get(key, [])
        backend_other = [h for h in bh if h not in consumer_reads and h["layer"] != "persistence"]
        persistence_count = sum(1 for h in bh if h["layer"] == "persistence")

        ui_exposed = len(uh) > 0
        backend_reads = len(consumer_reads) > 0

        if key in SPECIAL_CASES:
            verdict, note = SPECIAL_CASES[key]
        elif meta_re.search(key):
            # Meta GET (backend -> UI) : le backend la GENERE, le seul cablage
            # utile est son affichage UI. WRITE_ONLY/READ_ONLY n'ont pas de sens ici.
            if ui_exposed:
                verdict, note = "CABLEE", "meta GET (derivee backend) consommee par l'UI"
            else:
                verdict, note = "FANTOME", "meta GET (derivee backend) jamais affichee par l'UI"
        elif key in ALIAS_OF and not backend_reads:
            verdict = "ALIAS_MORT"
            note = (f"alias de {ALIAS_OF[key]} (settings_support.py:945) ; aucune lecture "
                    f"consommatrice de l'alias, et le save le persiste sans remap vers la canonique "
                    f"(settings_support.py:1689-1692)")
        elif ui_exposed and backend_reads:
            verdict, note = "CABLEE", ""
        elif ui_exposed:
            verdict, note = "WRITE_ONLY", ""
        elif backend_reads:
            verdict, note = "READ_ONLY", ""
        else:
            verdict, note = "FANTOME", ""

        extra = EXTRA_NOTES.get(key, "")
        if extra:
            note = f"{note} | {extra}" if note else extra

        stats[verdict] = stats.get(verdict, 0) + 1
        matrix[key] = {
            "verdict": verdict,
            "default": keys_meta[key]["default"],
            "provenances": keys_meta[key]["provenances"],
            "ui_exposed": ui_exposed,
            "ui_in_parametres": any("parametres.js" in h["site"] for h in uh),
            "ui_hits": uh[:8],
            "ui_hits_total": len(uh),
            "backend_consumer_reads": consumer_reads[:8],
            "backend_consumer_reads_total": len(consumer_reads),
            "backend_other_mentions": backend_other[:4],
            "persistence_hits": persistence_count,
            "note": note,
        }

    out = {
        "meta": {
            "matrix": "M3 settings write->read->effet",
            "source_canonique": "cinesort/ui/api/settings_support.py (GET = read_settings + apply_settings_defaults + _mask_secrets)",
            "scopes": {
                "ui": "web/dashboard/**/*.{js,html} hors tests/",
                "backend": "cinesort/**/*.py + app.py, hors commentaires, occurrences quotees",
            },
            "regles": {
                "CABLEE": "UI expose la cle ET lecture backend hors persistance",
                "WRITE_ONLY": "UI ecrit/affiche, aucune lecture backend hors persistance",
                "READ_ONLY": "backend lit, UI n'expose pas la cle",
                "FANTOME": "ni UI ni lecture backend",
                "ALIAS_MORT": "alias declare sans lecture consommatrice ni remap vers la canonique",
            },
            "limites": [
                "lecture backend detectee sur cle QUOTEE uniquement (les attributs Config renommes sont couverts via build_cfg_from_settings)",
                "WRITE_ONLY peut avoir un effet purement client-side (theme, animation_level...) : voir ui_hits hors parametres.js",
                "persistence_hits = occurrences dans la couche read/write/defaults/save de settings_support.py (non comptees comme effet)",
            ],
            "total_cles": len(all_keys),
        },
        "stats": stats,
        "keys": matrix,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK {OUT.relative_to(REPO)}")
    print("STATS:", json.dumps(stats, ensure_ascii=False))
    for v in ("FANTOME", "ALIAS_MORT", "WRITE_ONLY", "READ_ONLY"):
        ks = [k for k in all_keys if matrix[k]["verdict"] == v]
        if ks:
            print(f"{v} ({len(ks)}):", ", ".join(ks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
