"""Mesure objective de la santé de la codebase CineSort.

Produit un rapport markdown chiffré utilisé pour synchroniser CLAUDE.md avec
la réalité du dépôt. Reproduible cross-machine, sans dépendance externe (stdlib
+ ruff via subprocess).

Usage :
    python scripts/measure_codebase_health.py [--output PATH]

Si --output n'est pas fourni, le rapport est imprimé sur stdout.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".venv313",
    "__pycache__",
    "build",
    "dist",
    "packages",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "archive",
}


def iter_files(root: Path, extensions: Iterable[str]) -> Iterable[Path]:
    exts = {f".{e.lstrip('.')}" for e in extensions}
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in EXCLUDED_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in exts:
            yield p


# ---------------------------------------------------------------------------
# Métriques Python via AST
# ---------------------------------------------------------------------------


def analyze_python_file(path: Path) -> Dict[str, object]:
    """Retourne métriques par fichier : LOC, fonctions, except Exception."""
    text = path.read_text(encoding="utf-8", errors="replace")
    loc = text.count("\n") + 1
    out: Dict[str, object] = {
        "path": str(path.relative_to(REPO_ROOT).as_posix()),
        "loc": loc,
        "long_functions": [],
        "except_exception_sites": [],
        "param_heavy_functions": [],
    }
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        out["parse_error"] = str(exc)
        return out

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            length = end_line - node.lineno + 1
            if length > 100:
                out["long_functions"].append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "length": length,
                    }
                )
            args = node.args
            total_params = (
                len(args.args)
                + len(args.posonlyargs)
                + len(args.kwonlyargs)
                + (1 if args.vararg else 0)
                + (1 if args.kwarg else 0)
            )
            # Skip self/cls
            if node.args.args and node.args.args[0].arg in ("self", "cls"):
                total_params -= 1
            if total_params >= 10:
                out["param_heavy_functions"].append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "params": total_params,
                    }
                )
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                out["except_exception_sites"].append(
                    {
                        "line": node.lineno,
                        "form": "bare except",
                    }
                )
            elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                out["except_exception_sites"].append(
                    {
                        "line": node.lineno,
                        "form": "except Exception",
                    }
                )
    return out


# ---------------------------------------------------------------------------
# Métriques Ruff
# ---------------------------------------------------------------------------


def run_ruff_select(select: str, paths: Iterable[Path]) -> int:
    """Compte les violations Ruff pour une règle donnée. Retourne -1 si erreur.

    « Erreur » doit couvrir la panne la plus probable : **ruff absent de
    l'interpréteur**. Elle ne passait par aucune des gardes précédentes.
    `sys.executable` existe toujours, donc `except FileNotFoundError` ne pouvait
    pas se déclencher ; et `python -m <module absent>` rend **rc=1 avec un
    stdout vide** (mesuré le 2026-08-31), or rc=1 est aussi le code d'un ruff
    qui a trouvé des violations. Le `json.loads(proc.stdout or "[]")` d'origine
    transformait donc ce stdout vide en **0 violation** : le rapport annonçait
    une codebase propre sans avoir rien mesuré.

    Seule la sortie sépare les deux cas. En `--output-format json`, ruff écrit
    toujours un tableau JSON — `[]` compris (vérifié le 2026-08-31, rc=0). Un
    stdout vide signifie donc que ruff n'a pas tourné, jamais qu'il n'a rien
    trouvé.
    """
    args = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        select,
        "--no-cache",
        "--output-format",
        "json",
    ]
    args.extend(str(p) for p in paths)
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO_ROOT),
        )
    except OSError:
        # FileNotFoundError seule ne suffit pas : PermissionError, OSError
        # « executable trop long », etc. sont aussi des non-mesures.
        return -1
    if proc.returncode not in (0, 1):
        return -1
    if not (proc.stdout or "").strip():
        # Ruff n'a pas produit de JSON : il n'a pas tourné.
        return -1
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return -1
    if not isinstance(data, list):
        return -1
    return len(data)


# ---------------------------------------------------------------------------
# Métriques duplications + tests
# ---------------------------------------------------------------------------


#: Suffixes de décorateur reconnus comme « ce test est désactivé ».
#: `skipif`/`skipunless` sont conditionnels mais désactivent bel et bien le test
#: sur la machine où la condition est vraie — ils comptent.
_SKIP_LEAF_NAMES = {"skip", "skipif", "skipunless"}

#: Préfixes admis devant le nom de feuille. `""` couvre l'import direct
#: (`from unittest import skipUnless` → `@skipUnless(...)`).
_SKIP_PREFIXES = {"", "unittest", "pytest.mark"}


def _repo_relative(path: Path) -> str:
    """Chemin POSIX relatif au dépôt, ou chemin absolu si le fichier est hors dépôt.

    Sans ce repli, le compteur lève `ValueError` dès qu'on le pointe ailleurs
    que sur l'arbre du dépôt — c'est-à-dire qu'on ne peut pas le mesurer sur un
    jeu d'essai.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _decorator_dotted_name(node: ast.expr) -> str:
    """Nom pointé d'un décorateur, appelé ou non : `pytest.mark.skipif`, `skip`…"""
    if isinstance(node, ast.Call):
        node = node.func
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _skip_reason(node: ast.expr, leaf: str) -> str:
    """Raison littérale d'un décorateur de skip, chaîne vide si non littérale.

    `reason=` prime ; à défaut on prend l'argument positionnel qui porte la
    raison — le 1er pour `skip`, le 2e pour `skipif`/`skipunless` dont le 1er
    est la condition.
    """
    if not isinstance(node, ast.Call):
        return ""
    for kw in node.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value.strip()
    index = 0 if leaf == "skip" else 1
    if len(node.args) > index:
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value.strip()
    return ""


def _iter_skip_decorators(tree: ast.AST) -> Iterable[str]:
    """Rend la raison (possiblement vide) de chaque décorateur de skip de l'arbre."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for deco in node.decorator_list:
            dotted = _decorator_dotted_name(deco)
            prefix, _, leaf = dotted.rpartition(".")
            if leaf.lower() in _SKIP_LEAF_NAMES and prefix in _SKIP_PREFIXES:
                yield _skip_reason(deco, leaf.lower())


def count_test_skips(tests_dir: Path) -> Dict[str, object]:
    """Compte les décorateurs de skip et leurs raisons.

    Familles reconnues : `@skip` / `@skipIf` / `@skipUnless` (import direct),
    `@unittest.skip*` et `@pytest.mark.skip*`.

    La lecture passe par l'**AST**, pas par un motif de texte. L'ancien motif
    `@(unittest\\.)?skip(...)` exigeait que `skip` suive immédiatement `@` ou
    `@unittest.` : il ne pouvait structurellement pas voir `@pytest.mark.skip`,
    alors que la docstring l'annonçait déjà. Mesure du 2026-08-31 sur `tests/` :
    il rendait **27** là où **39** décorateurs existent — les 13 `@pytest.mark.*`
    étaient invisibles — et l'un de ces 27 n'était pas un décorateur mais une
    **mention en commentaire** (`tests/test_naming_properties.py:24`), le motif
    n'étant ancré nulle part.

    `unparsed_files` expose les fichiers que l'AST n'a pas pu lire : un fichier
    ignoré en silence est une nouvelle cécité.
    """
    skips: Counter = Counter()
    reasons: Dict[str, int] = defaultdict(int)
    unparsed: List[str] = []
    for path in iter_files(tests_dir, ["py"]):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except (OSError, SyntaxError, ValueError):
            unparsed.append(_repo_relative(path))
            continue
        for reason in _iter_skip_decorators(tree):
            skips[_repo_relative(path)] += 1
            if reason:
                # Tronquer pour grouper
                reasons[reason[:60]] += 1
    return {
        "total": sum(skips.values()),
        "by_file": dict(skips),
        "by_reason_short": dict(reasons),
        "unparsed_files": unparsed,
    }


def count_test_functions(tests_dir: Path) -> int:
    """Compte les fonctions test_*."""
    pattern = re.compile(r"^\s*def\s+test_\w+", re.MULTILINE)
    total = 0
    for path in iter_files(tests_dir, ["py"]):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(pattern.findall(text))
    return total


def count_console_logs(web_dir: Path) -> int:
    """Compte les console.log dans le frontend (hors commentaires évidents)."""
    total = 0
    pattern = re.compile(r"console\.log\s*\(")
    for path in iter_files(web_dir, ["js"]):
        if "preview" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            total += len(pattern.findall(line))
    return total


def count_lazy_imports(cinesort_dir: Path) -> int:
    """Compte les imports `from cinesort.X` indentés (lazy imports)."""
    pattern = re.compile(r"^\s+(?:from\s+cinesort\.[\w.]+\s+import|import\s+cinesort\.[\w.]+)")
    total = 0
    for path in iter_files(cinesort_dir, ["py"]):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if pattern.match(line):
                total += 1
    return total


# ---------------------------------------------------------------------------
# Métriques globales
# ---------------------------------------------------------------------------


def gather_python_metrics(cinesort_dir: Path) -> Dict[str, object]:
    files = list(iter_files(cinesort_dir, ["py"]))
    total_loc = 0
    long_funcs: List[Tuple[str, str, int, int]] = []  # path, name, line, length
    very_long: List[Tuple[str, str, int, int]] = []
    except_sites: List[Tuple[str, int, str]] = []
    param_heavy: List[Tuple[str, str, int, int]] = []
    large_files: List[Tuple[str, int]] = []

    for path in files:
        result = analyze_python_file(path)
        loc = int(result["loc"])
        total_loc += loc
        if loc > 500:
            large_files.append((str(result["path"]), loc))
        for f in result["long_functions"]:
            entry = (str(result["path"]), f["name"], f["line"], f["length"])
            long_funcs.append(entry)
            if f["length"] > 150:
                very_long.append(entry)
        for s in result["except_exception_sites"]:
            except_sites.append((str(result["path"]), s["line"], s["form"]))
        for p in result["param_heavy_functions"]:
            param_heavy.append((str(result["path"]), p["name"], p["line"], p["params"]))

    long_funcs.sort(key=lambda x: -x[3])
    very_long.sort(key=lambda x: -x[3])
    param_heavy.sort(key=lambda x: -x[3])
    large_files.sort(key=lambda x: -x[1])

    return {
        "file_count": len(files),
        "total_loc": total_loc,
        "long_functions_100": long_funcs,
        "very_long_functions_150": very_long,
        "except_exception_sites": except_sites,
        "param_heavy_functions": param_heavy,
        "large_files_500": large_files,
    }


def gather_js_metrics(web_dir: Path) -> Dict[str, object]:
    files = list(iter_files(web_dir, ["js"]))
    total_loc = 0
    for path in files:
        with contextlib.suppress(OSError):
            total_loc += path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    return {"file_count": len(files), "total_loc": total_loc}


def gather_duplicate_components(web_dir: Path) -> Dict[str, object]:
    """Composants présents à la fois dans web/components/ et web/dashboard/components/.

    Rend un **verdict**, pas une liste : « aucun doublon » et « le dossier
    desktop n'existe pas » ne sont pas le même fait. `web/components/` a disparu
    de l'arbre (mesure 2026-08-31 : `web/` ne contient plus que `dashboard/` et
    `shared/`), donc la version d'origine sortait toujours par le `return []` de
    tête et le rapport imprimait « 0 » — un compte, pour une mesure qui n'avait
    pas eu lieu. Un détecteur qui ne peut rendre qu'UNE valeur ne mesure rien.
    """
    desktop_dir = web_dir / "components"
    dashboard_dir = web_dir / "dashboard" / "components"
    missing = [
        rel
        for d, rel in ((desktop_dir, "web/components"), (dashboard_dir, "web/dashboard/components"))
        if not d.is_dir()
    ]
    if missing:
        return {"measurable": False, "duplicates": [], "missing_dirs": missing}
    desktop_names = {p.name for p in desktop_dir.glob("*.js")}
    dashboard_names = {p.name for p in dashboard_dir.glob("*.js")}
    return {
        "measurable": True,
        "duplicates": sorted(desktop_names & dashboard_names),
        "missing_dirs": [],
    }


def gather_migrations(infra_db_dir: Path) -> List[str]:
    migrations_dir = infra_db_dir / "migrations"
    if not migrations_dir.is_dir():
        return []
    return sorted(p.name for p in migrations_dir.glob("*.sql"))


# ---------------------------------------------------------------------------
# Format markdown
# ---------------------------------------------------------------------------


def _duplicate_cell(dup: Dict[str, object]) -> str:
    """Cellule du rapport pour les composants dupliqués : un compte, ou l'aveu."""
    if dup.get("measurable"):
        return str(len(dup.get("duplicates") or []))
    absents = ", ".join(str(d) for d in (dup.get("missing_dirs") or [])) or "?"
    return f"non mesuré ({absents} absent)"


def _skip_section(tests: Dict[str, object]) -> List[str]:
    """Section « Raisons de skip » + avertissement sur les fichiers illisibles."""
    skips = tests["skips"]
    out: List[str] = []
    unparsed = skips.get("unparsed_files") or []
    if unparsed:
        out.append(f"> ⚠ {len(unparsed)} fichier(s) de test non analysables (AST) — non comptés : {unparsed[:5]}")
        out.append("")
    if not skips["by_reason_short"]:
        return out
    out.append("### Raisons de skip les plus fréquentes")
    out.append("")
    out.append("| Raison (extrait) | Occurrences |")
    out.append("|------------------|-------------|")
    for reason, count in sorted(skips["by_reason_short"].items(), key=lambda kv: -kv[1])[:15]:
        out.append(f"| `{reason}` | {count} |")
    out.append("")
    return out


#: Règles Ruff mesurées, dans l'ordre du rapport, avec leur libellé.
RUFF_RULES: Tuple[Tuple[str, str], ...] = (
    ("BLE001", "blind except (`except Exception`)"),
    ("PLR2004", "magic value comparison"),
    ("PLR0913", "too many arguments (>5)"),
    ("C901", "complexity > 10"),
    ("SIM105", "try/except/pass → suppress"),
    ("ARG001", "argument inutilisé"),
    ("B007", "variable de boucle inutilisée"),
    ("RUF100", "`# noqa` inutile"),
)


def _ruff_section(ruff: Dict[str, int]) -> List[str]:
    """Tableau Ruff. Une valeur < 0 signifie « ruff n'a pas tourné », pas « 0 »."""
    out: List[str] = []
    out.append("## Qualité (Ruff)")
    out.append("")
    out.append("Comptés en activant **uniquement** la règle (config actuelle ignore probablement) :")
    out.append("")
    out.append("| Règle Ruff | Description | Violations |")
    out.append("|------------|-------------|------------|")
    for rule, label in RUFF_RULES:
        value = ruff.get(rule, -1)
        out.append(f"| `{rule}` | {label} | {value if value >= 0 else 'erreur ruff'} |")
    out.append("")
    return out


def format_report(data: Dict[str, object]) -> str:
    py = data["python"]
    js = data["js"]
    tests = data["tests"]
    ruff = data["ruff"]
    out: List[str] = []
    out.append("# CineSort — Mesures objectives codebase")
    out.append("")
    out.append(f"**Date** : {data['timestamp']}")
    out.append(f"**Branche** : {data['git_branch']}")
    out.append(f"**Commit** : `{data['git_commit']}`")
    out.append(f"**Python** : {sys.version.split()[0]}")
    out.append("")
    out.append("Script : `scripts/measure_codebase_health.py` — reproductible cross-machine.")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## Taille codebase")
    out.append("")
    out.append("| Métrique | Valeur |")
    out.append("|----------|--------|")
    out.append(f"| Fichiers Python (cinesort/) | {py['file_count']} |")
    out.append(f"| LOC Python total | {py['total_loc']:,} |")
    out.append(f"| Fichiers JS (web/) | {js['file_count']} |")
    out.append(f"| LOC JS total | {js['total_loc']:,} |")
    out.append(f"| Fichiers Python > 500L | {len(py['large_files_500'])} |")
    out.append(f"| Migrations SQL | {len(data['migrations'])} |")
    out.append(f"| Composants JS dupliqués (desktop ↔ dashboard) | {_duplicate_cell(data['duplicate_components'])} |")
    out.append("")
    out.append("## Tests")
    out.append("")
    out.append("| Métrique | Valeur |")
    out.append("|----------|--------|")
    out.append(f"| Fonctions test_* totales | {tests['test_function_count']} |")
    out.append(f"| Tests skip cumulés (@unittest.skip* / @pytest.mark.skip*) | {tests['skips']['total']} |")
    out.append("")

    out.extend(_skip_section(tests))
    out.extend(_ruff_section(ruff))

    out.append("## Anti-patterns mesurés par AST")
    out.append("")
    out.append("| Métrique | Valeur |")
    out.append("|----------|--------|")
    out.append(f"| `except Exception` / bare except | **{len(py['except_exception_sites'])}** |")
    out.append(f"| Fonctions > 100L | **{len(py['long_functions_100'])}** |")
    out.append(f"| Fonctions > 150L | **{len(py['very_long_functions_150'])}** |")
    out.append(f"| Fonctions avec ≥ 10 paramètres | **{len(py['param_heavy_functions'])}** |")
    out.append(f"| Imports lazy (`import cinesort.X` indenté) | **{data['lazy_imports']}** |")
    out.append(f"| `console.log` actifs (web/, hors preview) | **{data['console_logs']}** |")
    out.append("")

    if py["very_long_functions_150"]:
        out.append("### Top 15 fonctions > 150L")
        out.append("")
        out.append("| Fichier | Fonction | Ligne | Longueur |")
        out.append("|---------|----------|-------|----------|")
        for path, name, line, length in py["very_long_functions_150"][:15]:
            out.append(f"| `{path}` | `{name}` | {line} | **{length}L** |")
        out.append("")

    if py["long_functions_100"]:
        out.append("### Top 20 fonctions > 100L")
        out.append("")
        out.append("| Fichier | Fonction | Ligne | Longueur |")
        out.append("|---------|----------|-------|----------|")
        for path, name, line, length in py["long_functions_100"][:20]:
            out.append(f"| `{path}` | `{name}` | {line} | {length}L |")
        out.append("")

    if py["param_heavy_functions"]:
        out.append("### Top 15 fonctions à paramètres nombreux (≥ 10)")
        out.append("")
        out.append("| Fichier | Fonction | Ligne | Params |")
        out.append("|---------|----------|-------|--------|")
        for path, name, line, params in py["param_heavy_functions"][:15]:
            out.append(f"| `{path}` | `{name}` | {line} | {params} |")
        out.append("")

    if py["except_exception_sites"]:
        out.append("### Sites `except Exception` (top 20 par fichier)")
        out.append("")
        by_file: Counter = Counter(item[0] for item in py["except_exception_sites"])
        out.append("| Fichier | Occurrences |")
        out.append("|---------|-------------|")
        for fpath, count in by_file.most_common(20):
            out.append(f"| `{fpath}` | {count} |")
        out.append("")

    if py["large_files_500"]:
        out.append("### Fichiers Python > 500L (top 25)")
        out.append("")
        out.append("| Fichier | LOC |")
        out.append("|---------|-----|")
        for path, loc in py["large_files_500"][:25]:
            out.append(f"| `{path}` | {loc} |")
        out.append("")

    if data["duplicate_components"].get("duplicates"):
        out.append("### Composants JS dupliqués (présents desktop ET dashboard)")
        out.append("")
        for name in data["duplicate_components"]["duplicates"]:
            out.append(f"- `{name}`")
        out.append("")

    out.append("## Reproduction")
    out.append("")
    out.append("```bash")
    out.append("python scripts/measure_codebase_health.py --output audit/results/v7_X_Y_real_metrics.md")
    out.append("```")
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Git context
# ---------------------------------------------------------------------------


def git_info() -> Tuple[str, str]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        ).stdout.strip()
        return branch, commit
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "n/a", "n/a"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="Chemin du fichier markdown de sortie (sinon stdout)")
    args = parser.parse_args(argv)

    cinesort_dir = REPO_ROOT / "cinesort"
    web_dir = REPO_ROOT / "web"
    tests_dir = REPO_ROOT / "tests"
    infra_db_dir = REPO_ROOT / "cinesort" / "infra" / "db"

    branch, commit = git_info()

    sys.stderr.write("Mesure Python via AST...\n")
    py_metrics = gather_python_metrics(cinesort_dir)
    sys.stderr.write(f"  {py_metrics['file_count']} fichiers, {py_metrics['total_loc']:,} LOC\n")

    sys.stderr.write("Mesure JS...\n")
    js_metrics = gather_js_metrics(web_dir)

    sys.stderr.write("Comptage tests + skips...\n")
    tests_metrics = {
        "test_function_count": count_test_functions(tests_dir),
        "skips": count_test_skips(tests_dir),
    }

    sys.stderr.write("Imports lazy + console.log...\n")
    lazy_imports = count_lazy_imports(cinesort_dir)
    console_logs = count_console_logs(web_dir)

    sys.stderr.write("Composants frontend dupliqués...\n")
    duplicate_components = gather_duplicate_components(web_dir)

    sys.stderr.write("Migrations SQL...\n")
    migrations = gather_migrations(infra_db_dir)

    sys.stderr.write(f"Ruff ({len(RUFF_RULES)} règles)...\n")
    ruff_results: Dict[str, int] = {}
    for rule, _label in RUFF_RULES:
        ruff_results[rule] = run_ruff_select(rule, [cinesort_dir])
        value = ruff_results[rule]
        sys.stderr.write(f"  {rule}: {value if value >= 0 else 'ERREUR (ruff n a pas tourne)'}\n")
    if all(v < 0 for v in ruff_results.values()):
        sys.stderr.write("  ⚠ Aucune règle Ruff mesurée — ruff est-il installé dans cet interpréteur ?\n")

    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "git_branch": branch,
        "git_commit": commit,
        "python": py_metrics,
        "js": js_metrics,
        "tests": tests_metrics,
        "ruff": ruff_results,
        "lazy_imports": lazy_imports,
        "console_logs": console_logs,
        "duplicate_components": duplicate_components,
        "migrations": migrations,
    }

    report = format_report(data)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        sys.stderr.write(f"\nRapport écrit dans {args.output}\n")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
