"""Script one-shot pour issue #86 PR 2 : deduplique `_find_free_port()`
en l'extrayant vers `tests/_helpers.py`.

Strategie : utiliser AST pour detecter precisement la definition de la
fonction `_find_free_port()` (toutes ses formes possibles), la supprimer
du fichier source, puis ajouter `from tests._helpers import find_free_port
as _find_free_port` apres les imports existants.

Usage :
    python scripts/dedup_find_free_port_86.py            # dry-run
    python scripts/dedup_find_free_port_86.py --apply
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


TARGET_FUNC = "_find_free_port"

IMPORT_LINE = "from tests._helpers import find_free_port as _find_free_port\n"


def _find_func_range(source: str) -> tuple[int, int] | None:
    """Retourne (start_line, end_line) 1-indexed de la def `_find_free_port`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC:
            # ast donne 1-indexed line numbers
            return (node.lineno, node.end_lineno or node.lineno)
    return None


def _find_last_import_line(source: str) -> int:
    """Retourne le numero de ligne (1-indexed) du dernier import au top-level."""
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

    rng = _find_func_range(source)
    if rng is None:
        return False

    start, end = rng  # 1-indexed
    lines = source.split("\n")

    # Supprime les lignes de la fonction (indices 0-based : start-1 a end-1 inclus)
    # Plus 1-2 lignes blanches qui suivent (cleanup esthetique).
    del_start = start - 1
    del_end = end  # exclusive en slice
    # Manger les blanches qui suivent (max 2)
    while del_end < len(lines) and lines[del_end].strip() == "":
        del_end += 1
        if del_end - end >= 2:
            break

    new_lines = lines[:del_start] + lines[del_end:]
    new_source = "\n".join(new_lines)

    # Ajouter l'import si absent
    if "from tests._helpers import find_free_port" not in new_source:
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
        "tests/e2e/conftest.py",
        "tests/e2e/visual_catalog.py",
        "tests/e2e_dashboard/conftest.py",
        "tests/manual/visual_audit_capture.py",
        "tests/test_dashboard_infra.py",
        "tests/test_dashboard_shell.py",
        "tests/test_design_system_v5.py",
        "tests/test_i18n_infrastructure.py",
        "tests/test_i18n_round_trip.py",
        "tests/test_naming_ui.py",
        "tests/test_pyinstaller_smoke.py",
        "tests/test_rest_api.py",
        "tests/test_rest_http_status.py",
        "tests/test_rest_security.py",
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
        print("(dry-run : aucun fichier modifie)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
