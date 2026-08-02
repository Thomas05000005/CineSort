"""Garde-fou regression : compte de lazy imports residuels du refactor #84.

Ce test, ajoute en M-03 (Vague M, refactor #84 etapes 2-4), borne le nombre
de lazy imports (import a l'interieur d'une fonction) qui subsistent dans le
code source `cinesort/`. Objectif : empecher qu'un dev re-introduise des
imports lazy sans documentation/justification.

Strategie :
- Issue #83 (mai 2026) avait converti 150 lazy imports sur ~165 au depart.
- M-03 (Vague M, juin 2026) a converti 4 lazy imports stdlib safes
  (settings_support.re/secrets, quality_simulator_support.re, migration_manager.Path).
- Reste 69 lazy imports volontaires, majoritairement :
  * dependances optionnelles (segno, onnxruntime, rapidfuzz, requests)
  * platform-specific (msvcrt vs fcntl dans single_instance)
  * cycles intentionnels documentes (apply_core <-> cleanup, runtime_support
    pour eviter d'importer settings_support au load module)

Si tu ajoutes un lazy import legitime, augmente `MAX_LAZY_IMPORTS` et
documente la raison dans `docs/internal/REFACTOR_PLAN_84.md` section
"Lazy imports residuels".

Si tu convertis des lazy imports en top-level, DIMINUE `MAX_LAZY_IMPORTS`
pour empecher la regression.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

# Bound de regression : 69 = etat M-03 (post-conversion de 4 imports).
# A diminuer si on converte d'autres lazy imports en top-level.
# A augmenter UNIQUEMENT avec doc dans REFACTOR_PLAN_84.md.
MAX_LAZY_IMPORTS = 69


class _LazyImportCounter(ast.NodeVisitor):
    """Compte les `import` ou `from ... import` a l'interieur de fonctions."""

    def __init__(self) -> None:
        self.depth = 0
        self.count = 0
        self.locations: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        if self.depth > 0:
            self.count += 1
            names = ",".join(a.name for a in node.names)
            self.locations.append((node.lineno, f"import {names}"))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.depth > 0:
            self.count += 1
            mod = node.module or ""
            names = ",".join(a.name for a in node.names)
            self.locations.append((node.lineno, f"from {mod} import {names}"))


def _count_lazy_imports(root: Path) -> tuple[int, dict[str, int]]:
    total = 0
    by_file: dict[str, int] = {}
    for dirpath, _dirs, fnames in os.walk(root):
        for fname in fnames:
            if not fname.endswith(".py"):
                continue
            path = Path(dirpath) / fname
            try:
                src = path.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            visitor = _LazyImportCounter()
            visitor.visit(tree)
            if visitor.count > 0:
                rel = str(path.relative_to(root.parent)).replace("\\", "/")
                by_file[rel] = visitor.count
                total += visitor.count
    return total, by_file


class TestRefactor84LazyImportProgress(unittest.TestCase):
    """Borne le nombre de lazy imports residuels apres M-03 / refactor #84."""

    def test_lazy_imports_bounded(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        cinesort_dir = repo_root / "cinesort"
        total, by_file = _count_lazy_imports(cinesort_dir)
        self.assertLessEqual(
            total,
            MAX_LAZY_IMPORTS,
            msg=(
                f"Lazy imports residuels = {total} > borne {MAX_LAZY_IMPORTS}.\n"
                f"Soit on a regresse (ajout d'un lazy import), soit on a converti "
                f"et on doit BAISSER la borne MAX_LAZY_IMPORTS.\n\n"
                f"Top fichiers :\n"
                + "\n".join(f"  {c:3d}  {p}" for p, c in sorted(by_file.items(), key=lambda x: -x[1])[:15])
            ),
        )

    def test_known_converted_in_m03_stay_top_level(self) -> None:
        """Verifie que les 4 conversions M-03 ne sont pas regressees.

        Si quelqu'un re-introduit `import secrets as _secrets` localement
        dans settings_support.apply_settings_defaults, ce test catch.
        """
        repo_root = Path(__file__).resolve().parent.parent
        # Les 4 fichiers convertis en M-03
        files_and_imports_top = [
            ("cinesort/ui/api/settings_support.py", ["import secrets", "import re"]),
            ("cinesort/ui/api/quality_simulator_support.py", ["import re"]),
        ]
        for relpath, expected_top in files_and_imports_top:
            path = repo_root / relpath
            src = path.read_text(encoding="utf-8")
            for imp in expected_top:
                self.assertIn(
                    imp,
                    src.split("\n\ndef ")[0],  # header avant le 1er def
                    msg=f"{relpath}: {imp!r} doit etre top-level (M-03 conversion)",
                )


if __name__ == "__main__":
    unittest.main()
