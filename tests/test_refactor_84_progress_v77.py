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

Si tu ajoutes un lazy import legitime, augmente la borne de SA couche dans
`MAX_LAZY_IMPORTS_BY_LAYER` et documente la raison dans
`docs/internal/REFACTOR_PLAN_84.md` section "Lazy imports residuels".

Si tu convertis des lazy imports en top-level, DIMINUE la borne correspondante
pour empecher la regression.

--- Reetalonnage 2026-08-03 (dette pre-existante, pas une regression) ---

La borne globale valait encore 69 alors que le paquet mesure en comptait 170 :
le cliquet n'avait pas ete re-etalonne apres l'eclatement de `cinesort/ui/api`
en facades (`*_support.py`), qui a deplace la majorite des imports differes
sans en supprimer. L'historique du depot ayant ete ecrase (squash public), il
est impossible d'attribuer commit par commit ; la borne etait donc morte : elle
rougissait en permanence et ne signalait plus rien.

Deux changements pour que le cliquet redevienne utile plutot que juste vert :

1. Le perimetre exclut `cinesort/tests/`. Le docstring parle du "code source" ;
   du code de test qui importe dans une methode de test n'est pas la dette que
   #84 traque, et son bruit polluait le compte (7 imports).
2. La borne globale unique est remplacee par une borne PAR COUCHE. Une borne
   globale laissait passer un echange silencieux (ajouter un import differe
   dans `domain` en en supprimant un dans `ui` gardait le total identique) ;
   or c'est justement dans les couches basses qu'un import differe trahit un
   cycle. Les bornes sont posees a la valeur EXACTE mesuree : tout ajout,
   dans n'importe quelle couche, fait rougir.

Ces bornes constatent une dette, elles ne l'absolvent pas : 116 des 170 imports
differes visent `cinesort.*` (donc des cycles internes, la cible reelle de #84).
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

# Sous-arbres de `cinesort/` hors perimetre "code source".
EXCLUDED_DIRS = frozenset({"tests", "__pycache__"})

# Cliquet par couche — valeurs EXACTES mesurees le 2026-08-03 (zero marge).
# A diminuer des qu'on convertit ; a augmenter UNIQUEMENT avec doc dans
# REFACTOR_PLAN_84.md. `__root__` = modules a la racine du paquet.
MAX_LAZY_IMPORTS_BY_LAYER: dict[str, int] = {
    "__root__": 3,
    # 23 -> 25 (PR#852, +2). Les DEUX imports differes ont ete verifies un par
    # un, et ils ne sont pas du meme genre :
    #   - `cleanup` -> `apply_core._append_error_message` : VRAI CYCLE.
    #     `apply_core.py:15` importe deja `cinesort.app.cleanup`. Un import de
    #     tete casserait l'import du paquet.
    #   - `apply_batches_reconciliation` -> `apply_audit.read_apply_audit` : PAS
    #     de cycle (`apply_audit` n'importe que la stdlib). Le commentaire du
    #     code dit « eviter de charger au boot », mais la vraie raison est le
    #     `except ImportError` juste en dessous : sur un build EXE AMPUTE, un
    #     import de tete tuerait tout le module de reconciliation, la ou l'import
    #     local ne degrade que la lecture du marqueur. Conserve pour cette
    #     raison-la, pas pour la raison affichee.
    "app": 25,
    "data": 0,
    "domain": 16,
    "infra": 17,
    # 110 -> 111 : +1 pour `history_support.get_plan_row`, importe tardivement
    # dans `film_support` (PR#853). Ce n'est pas un choix de confort : les deux
    # modules se referencent mutuellement, un import de tete cree un cycle a
    # l'import du paquet. Justification detaillee dans REFACTOR_PLAN_84.md.
    # Le TOTAL reste a 170 : la couche `app` rend le point que `ui` prend.
    "ui": 111,
}

# Borne globale = somme des bornes par couche (170). Gardee pour que le
# message d'erreur donne l'ordre de grandeur, jamais saisie a la main.
MAX_LAZY_IMPORTS = sum(MAX_LAZY_IMPORTS_BY_LAYER.values())


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


def _count_lazy_imports(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Compte les imports differes de `root`, par couche et par fichier."""
    by_layer: dict[str, int] = dict.fromkeys(MAX_LAZY_IMPORTS_BY_LAYER, 0)
    by_file: dict[str, int] = {}
    for dirpath, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
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
            if visitor.count <= 0:
                continue
            rel_in_pkg = path.relative_to(root).as_posix()
            layer = rel_in_pkg.split("/")[0] if "/" in rel_in_pkg else "__root__"
            by_layer[layer] = by_layer.get(layer, 0) + visitor.count
            by_file[str(path.relative_to(root.parent)).replace("\\", "/")] = visitor.count
    return by_layer, by_file


class TestRefactor84LazyImportProgress(unittest.TestCase):
    """Borne le nombre de lazy imports residuels apres M-03 / refactor #84."""

    def test_lazy_imports_bounded(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        cinesort_dir = repo_root / "cinesort"
        by_layer, by_file = _count_lazy_imports(cinesort_dir)

        top_files = "\n".join(f"  {c:3d}  {p}" for p, c in sorted(by_file.items(), key=lambda x: -x[1])[:15])
        over = {
            layer: (count, MAX_LAZY_IMPORTS_BY_LAYER.get(layer, 0))
            for layer, count in by_layer.items()
            if count > MAX_LAZY_IMPORTS_BY_LAYER.get(layer, 0)
        }
        self.assertEqual(
            over,
            {},
            msg=(
                "Imports differes en hausse (couche: mesure > borne) : "
                + ", ".join(f"{k}: {c} > {b}" for k, (c, b) in sorted(over.items()))
                + f"\nTotal mesure = {sum(by_layer.values())} (borne globale {MAX_LAZY_IMPORTS}).\n"
                "Soit on a regresse (ajout d'un import differe), soit on a converti et il "
                "faut BAISSER la borne de la couche dans MAX_LAZY_IMPORTS_BY_LAYER.\n\n"
                f"Top fichiers :\n{top_files}"
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
