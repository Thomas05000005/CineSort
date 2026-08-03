"""M2 — Matrice de cablage facade -> support -> impl (verif totale 2026-07).

REJOUABLE : python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m2_facades_impl.py

Analyse AST (module ast, zero import du code applicatif) de :
    - cinesort/ui/api/cinesort_api.py           (god-class CineSortApi, _X_impl)
    - cinesort/ui/api/facades/*.py              (6 facades cablees)
    - cinesort/ui/api/similar_films_facade.py   (facade hors dossier facades/)
    - cinesort/ui/api/*_support*.py             (modules support)

Pour chaque methode de facade : cible de delegation (self._api._X_impl god-class
OU appel direct module support), profondeur de chaine, verdict.

Verdicts (facade methods) :
    PROPRE        : 1 cible unique, chaine resolue, pas d'ambiguite
    DOUBLE_CHEMIN : methode exposee sur >= 2 facades OU >= 2 cibles god distinctes
    DUPLIQUE      : la cible _X_impl god-class a un homonyme defini dans un support
    ORPHELIN      : classe facade jamais instanciee OU cible de delegation inexistante

Verdicts (god _X_impl) :
    PROPRE        : reference par >= 1 facade, pas d'homonyme support
    DUPLIQUE      : homonyme _X_impl defini aussi dans un module support
    ORPHELIN      : reference par AUCUNE facade ni AUCUN autre fichier du repo
    DOUBLE_CHEMIN : reference a la fois par facade(s) ET par d'autres call sites hors facades

Sortie : docs/internal/verif_totale_2026_07/matrices/m2_facades_impl.json
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO = Path(__file__).resolve().parents[3]
if REPO.name != "CineSort" and not (REPO / "cinesort").is_dir():
    # fallback si la profondeur change : remonter jusqu'a trouver cinesort/
    p = Path(__file__).resolve()
    while p != p.parent and not (p / "cinesort").is_dir():
        p = p.parent
    REPO = p

API_DIR = REPO / "cinesort" / "ui" / "api"
FACADES_DIR = API_DIR / "facades"
GOD_FILE = API_DIR / "cinesort_api.py"
SIMILAR_FILE = API_DIR / "similar_films_facade.py"
OUT_FILE = REPO / "docs" / "internal" / "verif_totale_2026_07" / "matrices" / "m2_facades_impl.json"

REL = lambda p: str(Path(p).resolve().relative_to(REPO)).replace("\\", "/")


def read_src(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def parse(path: Path) -> ast.Module:
    return ast.parse(read_src(path), filename=str(path))


# ---------------------------------------------------------------------------
# 1. Modules support : nom module -> {fonctions top-level: ligne}
# ---------------------------------------------------------------------------
def collect_support_modules() -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for f in sorted(API_DIR.glob("*_support*.py")):
        tree = parse(f)
        funcs = {n.name: n.lineno for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        out[f.stem] = funcs
    return out


# ---------------------------------------------------------------------------
# 2. Imports d'un module : alias -> module support, et nom -> (module, orig)
# ---------------------------------------------------------------------------
def collect_imports(tree: ast.Module, support_names: Set[str]) -> Tuple[Dict[str, str], Dict[str, Tuple[str, str]]]:
    mod_alias: Dict[str, str] = {}  # alias local -> nom module support
    from_funcs: Dict[str, Tuple[str, str]] = {}  # nom local -> (module, nom origine)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                base = a.name.split(".")[-1]
                if base in support_names:
                    mod_alias[a.asname or base] = base
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            tail = mod.split(".")[-1]
            if tail in support_names:
                for a in node.names:
                    from_funcs[a.asname or a.name] = (tail, a.name)
            elif mod.endswith("ui.api") or mod == "cinesort.ui.api":
                for a in node.names:
                    if a.name in support_names:
                        mod_alias[a.asname or a.name] = a.name
    return mod_alias, from_funcs


# ---------------------------------------------------------------------------
# 3. Extraction des cibles de delegation dans le corps d'une fonction
# ---------------------------------------------------------------------------
def extract_calls(
    fn: ast.FunctionDef, mod_alias: Dict[str, str], from_funcs: Dict[str, Tuple[str, str]], self_attr_api: bool
) -> List[Dict[str, Any]]:
    """Retourne la liste des cibles appelees : god (via self._api.X ou self.X),
    support (module.fn ou fn importee)."""
    targets: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()

    def add(kind: str, module: str, name: str, line: int) -> None:
        key = (kind, module, name)
        if key not in seen:
            seen.add(key)
            targets.append({"kind": kind, "module": module, "name": name, "line": line})

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            v = f.value
            # self._api.X(...)  (facade -> god)
            if (
                self_attr_api
                and isinstance(v, ast.Attribute)
                and v.attr == "_api"
                and isinstance(v.value, ast.Name)
                and v.value.id == "self"
            ):
                add("god", "cinesort_api.CineSortApi", f.attr, node.lineno)
            # self.X(...) (god -> god interne)
            elif isinstance(v, ast.Name) and v.id == "self" and not self_attr_api:
                add("self", "cinesort_api.CineSortApi", f.attr, node.lineno)
            # module_support.fn(...)
            elif isinstance(v, ast.Name) and v.id in mod_alias:
                add("support", mod_alias[v.id], f.attr, node.lineno)
        elif isinstance(f, ast.Name) and f.id in from_funcs:
            mod, orig = from_funcs[f.id]
            add("support", mod, orig, node.lineno)
    return targets


# ---------------------------------------------------------------------------
# 4. God-class : methodes + leurs cibles support
# ---------------------------------------------------------------------------
def collect_god() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, Tuple[str, str]]]:
    tree = parse(GOD_FILE)
    support_names = set(SUPPORT.keys())
    mod_alias, from_funcs = collect_imports(tree, support_names)
    methods: Dict[str, Dict[str, Any]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CineSortApi":
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    calls = extract_calls(m, mod_alias, from_funcs, self_attr_api=False)
                    methods[m.name] = {"lineno": m.lineno, "calls": calls}
    return methods, mod_alias, from_funcs


# ---------------------------------------------------------------------------
# 5. Facades : classes + methodes publiques + cibles
# ---------------------------------------------------------------------------
def collect_facades() -> List[Dict[str, Any]]:
    support_names = set(SUPPORT.keys())
    files = sorted(FACADES_DIR.glob("*.py")) + [SIMILAR_FILE]
    out: List[Dict[str, Any]] = []
    for f in files:
        if f.name in ("__init__.py", "_base.py"):
            continue
        tree = parse(f)
        mod_alias, from_funcs = collect_imports(tree, support_names)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            methods = []
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_"):
                    calls = extract_calls(m, mod_alias, from_funcs, self_attr_api=True)
                    methods.append({"name": m.name, "lineno": m.lineno, "calls": calls})
            out.append({"file": REL(f), "class": node.name, "methods": methods})
    return out


# ---------------------------------------------------------------------------
# 6. References AST reelles dans cinesort/ (Attribute/Name, JAMAIS les
#    commentaires ni docstrings — un scan regex donnait des faux positifs :
#    ex reset_support.py:290 mentionne _get_settings_impl en docstring)
# ---------------------------------------------------------------------------
def build_reference_index(names: Set[str]) -> Dict[str, List[str]]:
    """name -> ['fichier:ligne', ...] pour toute reference AST (acces attribut
    `x._X_impl` ou nom nu) hors ligne de definition, dans cinesort/ (runtime).
    tests/ exclus volontairement (la mission porte sur le cablage runtime)."""
    idx: Dict[str, List[str]] = {n: [] for n in names}
    for f in sorted((REPO / "cinesort").rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            tree = parse(f)
        except Exception:
            continue
        rel = REL(f)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in idx:
                idx[node.attr].append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Name) and node.id in idx:
                idx[node.id].append(f"{rel}:{node.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in idx:
                pass  # definition, pas une reference
    return idx


# ---------------------------------------------------------------------------
# 7. Instanciation des classes facade dans cinesort/
# ---------------------------------------------------------------------------
def find_instantiations(class_names: Set[str]) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {c: [] for c in class_names}
    for f in sorted((REPO / "cinesort").rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            tree = parse(f)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = None
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name in class_names:
                    # exclure l'auto-reference dans le fichier qui definit la classe
                    found[name].append(f"{REL(f)}:{node.lineno}")
    return found


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
SUPPORT = collect_support_modules()


def main() -> None:
    god_methods, god_alias, god_from = collect_god()
    god_impls = {n: v for n, v in god_methods.items() if n.endswith("_impl")}
    facades = collect_facades()

    # --- homonymes _X_impl god ET support ---
    support_func_index: Dict[str, List[str]] = {}
    for mod, funcs in SUPPORT.items():
        for fn, line in funcs.items():
            support_func_index.setdefault(fn, []).append(f"{mod}.py:{line}")
    # Corps des fonctions support (pour tracer wrapper -> twin dans le meme module)
    support_internal_calls: Dict[str, Dict[str, Set[str]]] = {}  # mod -> fn -> {noms appeles}
    for mod in SUPPORT:
        tree = parse(API_DIR / f"{mod}.py")
        calls_map: Dict[str, Set[str]] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                called = {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
                calls_map[node.name] = called
        support_internal_calls[mod] = calls_map

    homonyms = []
    for name in sorted(god_impls):
        if name in support_func_index:
            god_calls_twin = any(c["kind"] == "support" and c["name"] == name for c in god_impls[name]["calls"])
            # le god impl appelle-t-il un wrapper support qui appelle le twin ?
            twin_via_wrapper = None
            for c in god_impls[name]["calls"]:
                if c["kind"] != "support":
                    continue
                mod_calls = support_internal_calls.get(c["module"], {})
                if name in mod_calls.get(c["name"], set()):
                    twin_via_wrapper = f"{c['module']}.{c['name']} -> {c['module']}.{name}"
                    break
            homonyms.append(
                {
                    "name": name,
                    "god_line": f"{REL(GOD_FILE)}:{god_impls[name]['lineno']}",
                    "support_defs": support_func_index[name],
                    "god_delegates_to_support_twin": god_calls_twin,
                    "twin_reachable_via_wrapper": twin_via_wrapper,
                }
            )
    homonym_names = {h["name"] for h in homonyms}

    # _X_impl definis UNIQUEMENT dans un support (pas de twin god-class)
    support_only_impls = []
    for fn, defs in sorted(support_func_index.items()):
        if fn.endswith("_impl") and fn not in god_impls:
            callers = []
            for mod, calls_map in support_internal_calls.items():
                for wrapper, called in calls_map.items():
                    if fn in called and wrapper != fn:
                        callers.append(f"{mod}.{wrapper}")
            support_only_impls.append({"name": fn, "defs": defs, "internal_callers": sorted(callers)})

    # --- exposition multi-facades ---
    method_owners: Dict[str, List[str]] = {}
    for fc in facades:
        for m in fc["methods"]:
            method_owners.setdefault(m["name"], []).append(fc["class"])
    multi_facade = {n: owners for n, owners in sorted(method_owners.items()) if len(owners) > 1}

    # --- instanciation des facades ---
    class_names = {fc["class"] for fc in facades}
    instantiations = find_instantiations(class_names)
    orphan_classes = sorted(c for c, sites in instantiations.items() if not sites)

    # --- resolution chaine + verdict par methode de facade ---
    def resolve_god_chain(attr: str) -> Tuple[List[str], int, str]:
        """Suit attr sur CineSortApi -> support. Retourne (chaine, profondeur, statut)."""
        chain: List[str] = []
        depth = 1  # hop facade -> god
        cur = attr
        visited: Set[str] = set()
        while True:
            if cur in visited:
                return chain, depth, "cycle"
            visited.add(cur)
            info = god_methods.get(cur)
            if info is None:
                chain.append(f"CineSortApi.{cur} [INEXISTANT]")
                return chain, depth, "missing"
            chain.append(f"CineSortApi.{cur} (L{info['lineno']})")
            sup = [c for c in info["calls"] if c["kind"] == "support"]
            if sup:
                for c in sup:
                    chain.append(f"{c['module']}.{c['name']}")
                return chain, depth + 1, "support"
            nxt = [c for c in info["calls"] if c["kind"] == "self" and c["name"] in god_methods and c["name"] != cur]
            if len(nxt) == 1 and len(info["calls"]) <= 2:
                cur = nxt[0]["name"]
                depth += 1
                continue
            return chain, depth, "inline_god"

    matrix: List[Dict[str, Any]] = []
    for fc in facades:
        is_orphan_class = fc["class"] in orphan_classes
        for m in fc["methods"]:
            god_targets = sorted({c["name"] for c in m["calls"] if c["kind"] == "god"})
            support_targets = sorted({f"{c['module']}.{c['name']}" for c in m["calls"] if c["kind"] == "support"})
            reasons: List[str] = []
            chain: List[str] = [f"{fc['class']}.{m['name']} ({REL(FACADES_DIR / '')}...L{m['lineno']})"]
            chain = [f"{fc['class']}.{m['name']} (L{m['lineno']})"]
            depth = 0
            status = "inline_facade"
            if support_targets and not god_targets:
                chain += support_targets
                depth, status = 1, "support_direct"
            elif god_targets:
                sub, d, st = resolve_god_chain(god_targets[0])
                chain += sub
                depth, status = d, st
                if support_targets:
                    chain += [f"(+direct) {t}" for t in support_targets]
                    reasons.append("mixe delegation god + appel support direct")

            # verdict
            if is_orphan_class:
                verdict = "ORPHELIN"
                reasons.append(f"classe {fc['class']} jamais instanciee dans cinesort/")
            elif god_targets and status == "missing":
                verdict = "ORPHELIN"
                reasons.append(f"cible self._api.{god_targets[0]} inexistante sur CineSortApi")
            elif m["name"] in multi_facade:
                verdict = "DOUBLE_CHEMIN"
                reasons.append(
                    f"methode exposee sur {len(multi_facade[m['name']])} facades: {', '.join(multi_facade[m['name']])}"
                )
            elif len(god_targets) > 1:
                verdict = "DOUBLE_CHEMIN"
                reasons.append(f"{len(god_targets)} cibles god distinctes: {', '.join(god_targets)}")
            elif any(t in homonym_names for t in god_targets):
                verdict = "DUPLIQUE"
                t = next(t for t in god_targets if t in homonym_names)
                reasons.append(f"cible {t} homonyme god-class ET support ({', '.join(support_func_index[t])})")
            else:
                verdict = "PROPRE"

            matrix.append(
                {
                    "facade": fc["class"],
                    "file": fc["file"],
                    "method": m["name"],
                    "line": m["lineno"],
                    "delegation_kind": status,
                    "god_targets": god_targets,
                    "support_targets": support_targets,
                    "chain": chain,
                    "depth": depth,
                    "verdict": verdict,
                    "reasons": reasons,
                }
            )

    # --- references des _X_impl god : facades vs reste du repo ---
    facade_refs: Dict[str, Set[str]] = {}
    for row in matrix:
        for t in row["god_targets"]:
            facade_refs.setdefault(t, set()).add(f"{row['facade']}.{row['method']}")
    ref_idx = build_reference_index(set(god_impls.keys()))
    god_report: List[Dict[str, Any]] = []
    god_verdict_count: Dict[str, int] = {}
    for name in sorted(god_impls):
        info = god_impls[name]
        by_facades = sorted(facade_refs.get(name, set()))
        all_refs = ref_idx.get(name, [])
        facade_files = {REL(f) for f in list(FACADES_DIR.glob("*.py")) + [SIMILAR_FILE]}
        god_file_rel = REL(GOD_FILE)
        external_refs = [
            r for r in all_refs if r.rsplit(":", 1)[0] not in facade_files and r.rsplit(":", 1)[0] != god_file_rel
        ]
        internal_god_refs = [r for r in all_refs if r.rsplit(":", 1)[0] == god_file_rel]
        if name in homonym_names:
            verdict = "DUPLIQUE"
        elif not by_facades and not external_refs and not internal_god_refs:
            verdict = "ORPHELIN"
        elif by_facades and external_refs:
            verdict = "DOUBLE_CHEMIN"
        else:
            verdict = "PROPRE"
        god_verdict_count[verdict] = god_verdict_count.get(verdict, 0) + 1
        god_report.append(
            {
                "name": name,
                "line": info["lineno"],
                "delegates_to": sorted({f"{c['module']}.{c['name']}" for c in info["calls"] if c["kind"] == "support"}),
                "referenced_by_facades": by_facades,
                "external_refs_outside_facades": external_refs[:8],
                "internal_god_refs": internal_god_refs[:5],
                "verdict": verdict,
            }
        )

    # --- stats ---
    verdict_count: Dict[str, int] = {}
    for row in matrix:
        verdict_count[row["verdict"]] = verdict_count.get(row["verdict"], 0) + 1
    depth_count: Dict[str, int] = {}
    for row in matrix:
        depth_count[str(row["depth"])] = depth_count.get(str(row["depth"]), 0) + 1

    result = {
        "meta": {
            "mission": "M2 chaine facade->support->impl",
            "generated_by": REL(Path(__file__)),
            "repo": str(REPO),
            "files_analyzed": {
                "god": REL(GOD_FILE),
                "facades": [fc["file"] for fc in facades],
                "support_modules": sorted(SUPPORT.keys()),
            },
        },
        "stats": {
            "facade_methods_total": len(matrix),
            "facade_verdicts": verdict_count,
            "facade_depths": depth_count,
            "god_impl_total": len(god_impls),
            "god_impl_verdicts": god_verdict_count,
            "homonyms_god_and_support": len(homonyms),
            "support_only_impls": len(support_only_impls),
            "multi_facade_methods": len(multi_facade),
            "orphan_facade_classes": orphan_classes,
        },
        "facade_matrix": matrix,
        "god_impls": god_report,
        "homonyms": homonyms,
        "support_only_impls": support_only_impls,
        "multi_facade_methods": multi_facade,
        "facade_instantiations": {c: v for c, v in sorted(instantiations.items())},
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"OK -> {OUT_FILE}")
    print(json.dumps(result["stats"], indent=1, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
