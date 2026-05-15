"""Script one-shot pour issue #86 PR 4 : deduplique `_wait_done` /
`_wait_terminal` en les extrayant vers `tests/_helpers.py`.

Strategie identique a PR 3 :
- AST detecte les def `_wait_done` et `_wait_terminal` (module-level ou methode)
- Supprime la def
- Ajoute import alias depuis tests._helpers
- Remplace `self._wait_done(...)` -> `_wait_done(...)`

Usage :
    python scripts/dedup_wait_helpers_86.py            # dry-run
    python scripts/dedup_wait_helpers_86.py --apply
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


TARGETS = ("_wait_done", "_wait_terminal")


def _find_func_ranges(source: str, target: str) -> list[tuple[int, int, bool]]:
    """Retourne [(start, end, is_method), ...] pour la fonction `target`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    ranges: list[tuple[int, int, bool]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == target:
            ranges.append((node.lineno, node.end_lineno or node.lineno, False))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == target:
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

    # Pour chaque target, collect ranges
    all_ranges: list[tuple[int, int, bool, str]] = []
    for target in TARGETS:
        for start, end, is_method in _find_func_ranges(source, target):
            all_ranges.append((start, end, is_method, target))

    if not all_ranges:
        return False

    lines = source.split("\n")
    targets_found = {t[3] for t in all_ranges}
    any_method = any(t[2] for t in all_ranges)

    # Sort descending by start to delete from bottom to top
    for start, end, _is_method, _target in sorted(all_ranges, key=lambda x: -x[0]):
        del_start = start - 1
        del_end = end
        while del_end < len(lines) and lines[del_end].strip() == "":
            del_end += 1
            if del_end - end >= 2:
                break
        lines = lines[:del_start] + lines[del_end:]

    new_source = "\n".join(lines)

    # Replace self._wait_X( -> _wait_X(
    if any_method:
        for target in targets_found:
            new_source = re.sub(rf"\bself\.{re.escape(target)}\(", f"{target}(", new_source)

    # Import alias depuis _helpers pour chaque target trouvee
    import_lines = []
    if "from tests._helpers import wait_run_done" not in new_source:
        for target in sorted(targets_found):
            import_lines.append(f"from tests._helpers import wait_run_done as {target}")

    if import_lines:
        last_import = _find_last_import_line(new_source)
        if last_import > 0:
            ll = new_source.split("\n")
            for il in reversed(import_lines):
                ll.insert(last_import, il)
            new_source = "\n".join(ll)
        else:
            new_source = "\n".join(import_lines) + "\n" + new_source

    if apply:
        path.write_text(new_source, encoding="utf-8")
    return True


def main() -> int:
    apply = "--apply" in sys.argv

    files = [
        "tests/test_api_bridge_lot3.py",
        "tests/test_apply_preview.py",
        "tests/test_apply_robustness.py",
        "tests/test_backend_flow.py",
        "tests/test_concurrency.py",
        "tests/test_critical_flow_integration.py",
        "tests/test_run_report_export.py",
        "tests/test_tv_detection.py",
        "tests/test_undo_apply.py",
        "tests/test_undo_checksum.py",
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
        else:
            print(f"  SKIP (no func): {fn}")

    print(f"\nTotal : {total} fichier(s) migre(s)")
    if not apply:
        print("(dry-run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
