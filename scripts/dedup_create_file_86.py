"""Script one-shot pour issue #86 PR 3 : deduplique `_create_file()`
en l'extrayant vers `tests/_helpers.py`.

Strategie AST :
- Detecte la fonction `_create_file` (module-level OU methode de classe)
- Supprime la def
- Ajoute `from tests._helpers import create_file as _create_file`
- Pour les methodes : remplace `self._create_file(...)` par `_create_file(...)`

Usage :
    python scripts/dedup_create_file_86.py            # dry-run
    python scripts/dedup_create_file_86.py --apply
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


TARGET_FUNC = "_create_file"

IMPORT_LINE = "from tests._helpers import create_file as _create_file\n"


def _find_func_ranges(source: str) -> list[tuple[int, int, bool]]:
    """Retourne [(start, end, is_method), ...] 1-indexed pour `_create_file`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    ranges = []
    # Top-level
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC:
            ranges.append((node.lineno, node.end_lineno or node.lineno, False))

    # Methods
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_FUNC:
                    ranges.append((item.lineno, item.end_lineno or item.lineno, True))

    return ranges


def _find_last_import_line(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    last = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno or node.lineno
    return last


def migrate(path: Path, apply: bool) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    ranges = _find_func_ranges(source)
    if not ranges:
        return False

    lines = source.split("\n")
    has_method = any(is_method for _, _, is_method in ranges)

    # Supprimer les fonctions de la fin vers le debut (pour ne pas decaler les indices)
    for start, end, _is_method in sorted(ranges, reverse=True):
        del_start = start - 1
        del_end = end
        # Eat trailing blank lines (max 2)
        while del_end < len(lines) and lines[del_end].strip() == "":
            del_end += 1
            if del_end - end >= 2:
                break
        lines = lines[:del_start] + lines[del_end:]

    new_source = "\n".join(lines)

    # Remplacer les usages : `self._create_file(` -> `_create_file(`
    if has_method:
        new_source = re.sub(r"\bself\._create_file\(", "_create_file(", new_source)

    # Ajouter l'import
    if "from tests._helpers import create_file" not in new_source:
        last_import = _find_last_import_line(new_source)
        if last_import > 0:
            ll = new_source.split("\n")
            ll.insert(last_import, IMPORT_LINE.rstrip())
            new_source = "\n".join(ll)
        else:
            new_source = IMPORT_LINE + new_source

    if apply:
        path.write_text(new_source, encoding="utf-8")
    return True


def main() -> int:
    apply = "--apply" in sys.argv

    files = [
        "tests/test_api_bridge_lot3.py",
        "tests/test_apply_robustness.py",
        "tests/test_backend_flow.py",
        "tests/test_concurrency.py",
        "tests/test_critical_flow_integration.py",
        "tests/test_run_report_export.py",
        "tests/test_tv_detection.py",
        "tests/test_undo_apply.py",
    ]

    print(f"Mode : {'APPLY' if apply else 'DRY-RUN'}")
    total = 0
    for fn in files:
        p = Path(fn)
        if not p.is_file():
            print(f"  SKIP (missing): {fn}")
            continue
        if migrate(p, apply):
            total += 1
            print(f"  OK : {fn}")

    print(f"\nTotal : {total} fichier(s) migre(s)")
    if not apply:
        print("(dry-run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
