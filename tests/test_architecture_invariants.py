"""Invariants d'architecture verrouilles par la CI (issues #485, #779).

Deux cliquets, tous deux poses A ZERO MARGE sur la mesure reelle : toute
regression les fait rougir, et toute amelioration exige de resserrer la borne
dans ce fichier. C'est volontaire — une marge dormante laisse passer une
recidive gratuite.

1. `CineSortApiPublicSurfaceTests` (#485) — le pattern Strangler Fig de #84 a
   deplace ~166 methodes publiques de `CineSortApi` vers 6 facades. Rien
   n'empechait un contributeur d'en rajouter une DIRECTEMENT sur la god class :
   la regression n'etait visible qu'au prochain audit transverse manuel.

2. `UiApiPatchableImportTests` (#779) — verrouille la convention module-style
   documentee dans `docs/internal/REFACTOR_PLAN_84.md` §11.2. La vague 2 de
   #779 avait explicitement laisse ce garde-fou manquant : la convention
   n'etait tenue que par la relecture, et sa violation produit un test VERT
   QUI NE TESTE PLUS RIEN.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi

_REPO_ROOT = Path(__file__).resolve().parent.parent
_UI_API_DIR = _REPO_ROOT / "cinesort" / "ui" / "api"
_TESTS_DIR = _REPO_ROOT / "tests"


# ---------------------------------------------------------------------------
# 1. Surface publique de CineSortApi (#485)
# ---------------------------------------------------------------------------

# Les SEULES methodes publiques encore tolerees sur `CineSortApi`. Chacune a une
# raison mesuree de ne PAS etre facade-isee — cf. l'analyse de #483, qui
# proposait de les deplacer sur `RuntimeFacade` et dont c'est la refutation :
#
#   open_path        Volontairement hors facade. `rest_server._EXCLUDED_METHODS`
#                    l'exclut du dispatcher (il prend un chemin ARBITRAIRE en
#                    parametre : vecteur path-traversal), et c'est le SEUL appel
#                    `window.pywebview.api.*` restant du front
#                    (web/dashboard/components/film-detail.js:1312) — tout le
#                    reste passe par REST. La note d'en-tete de
#                    `facades/runtime_facade.py` documente deja ce choix.
#
#   test_reset       Helper E2E, garde par `CINESORT_E2E=1`. Il n'est PAS dans
#                    `_EXCLUDED_METHODS` : aujourd'hui il reste inatteignable
#                    seulement parce qu'aucune facade ne le porte et que la
#                    passe legacy `/api/<methode>` est desactivee. Le poser sur
#                    une facade l'exposerait en `POST /api/runtime/test_reset`.
#
#   log_api_exception  Utilitaire d'instrumentation appele par les modules
#                    `*_support` via `api.log_api_exception(...)`, jamais par le
#                    front. Egalement dans `_EXCLUDED_METHODS`. L'issue #483
#                    concluait elle-meme « rester ».
#
# Ajouter une entree ici doit etre une DECISION, pas une derive : toute nouvelle
# methode publique va sur une facade (api.run, api.settings, api.quality,
# api.integrations, api.library, api.runtime).
_ALLOWED_PUBLIC_METHODS = frozenset(
    {
        "log_api_exception",
        "open_path",
        "test_reset",
    }
)

# Les 6 facades instanciees dans `CineSortApi.__init__`.
_FACADE_ATTRS = ("run", "settings", "quality", "integrations", "library", "runtime")


class CineSortApiPublicSurfaceTests(unittest.TestCase):
    """#485 : garde-fou anti-regression de la facade-isation (#84)."""

    @staticmethod
    def _public_methods() -> set[str]:
        """Methodes publiques definies sur la CLASSE (pas les facades d'instance)."""
        return {name for name, _ in inspect.getmembers(CineSortApi, inspect.isfunction) if not name.startswith("_")}

    def test_no_new_public_method_on_cinesort_api(self) -> None:
        unexpected = self._public_methods() - _ALLOWED_PUBLIC_METHODS
        self.assertEqual(
            unexpected,
            set(),
            msg=(
                f"Nouvelle(s) methode(s) publique(s) directement sur CineSortApi : {sorted(unexpected)}.\n"
                "Le pattern Strangler Fig (#84) exige qu'une nouvelle methode publique soit posee sur "
                "une facade : api.run, api.settings, api.quality, api.integrations, api.library, "
                "api.runtime.\n"
                "Si l'ajout est DELIBERE et ne peut pas vivre sur une facade, ajouter le nom a "
                "_ALLOWED_PUBLIC_METHODS dans ce fichier AVEC sa raison."
            ),
        )

    def test_allowlist_has_no_dead_entry(self) -> None:
        """L'inverse : une entree de l'allowlist qui ne correspond plus a rien.

        Sans ce sens-la, supprimer `open_path` laisserait une autorisation
        fantome qui re-couvrirait silencieusement une methode homonyme future.
        """
        stale = _ALLOWED_PUBLIC_METHODS - self._public_methods()
        self.assertEqual(
            stale,
            set(),
            msg=(
                f"_ALLOWED_PUBLIC_METHODS autorise des methodes qui n'existent plus : {sorted(stale)}. "
                "Retirer l'entree."
            ),
        )

    def test_six_facades_are_instantiated(self) -> None:
        """La facade-isation n'a de sens que si les 6 facades existent vraiment."""
        api = CineSortApi()
        for attr in _FACADE_ATTRS:
            facade = getattr(api, attr, None)
            self.assertIsNotNone(facade, msg=f"Facade `api.{attr}` absente de CineSortApi.__init__")
            public = [n for n in dir(facade) if not n.startswith("_") and callable(getattr(facade, n, None))]
            self.assertTrue(public, msg=f"Facade `api.{attr}` n'expose aucune methode publique")


# ---------------------------------------------------------------------------
# 2. Imports module-style pour les cibles patchees (#779, cf. §11.2)
# ---------------------------------------------------------------------------

# Cibles `patch("cinesort.ui.api.<module>.<symbole>")` reperees dans tests/.
_PATCH_TARGET_RE = re.compile(r"""["'](cinesort\.ui\.api\.[A-Za-z0-9_.]+)["']""")

# Violations PRE-EXISTANTES, gelees. Les corriger n'est pas neutre : les tests de
# ces modules patchent aujourd'hui la cible LOCALE
# (`library_podiums_support._build_library_rows`), qui disparait si l'import
# passe en module-style. Le risque reste reel et c'est pourquoi ils sont
# nommes ici : quiconque patche `library_support._build_library_rows` en
# croyant affecter le podium ou la timeline obtiendra un test vert qui
# n'observe rien.
_KNOWN_SYMBOL_IMPORTS = frozenset(
    {
        ("cinesort/ui/api/library_actions_support.py", "cinesort.ui.api.library_support", "_build_library_rows"),
        ("cinesort/ui/api/library_podiums_support.py", "cinesort.ui.api.library_support", "_build_library_rows"),
        ("cinesort/ui/api/library_timeline_support.py", "cinesort.ui.api.library_support", "_build_library_rows"),
        ("cinesort/ui/api/quality_simulator_support.py", "cinesort.ui.api.library_support", "_get_store"),
    }
)


def _iter_python_files(root: Path):
    for dirpath, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in sorted(fnames):
            if fname.endswith(".py"):
                yield Path(dirpath) / fname


def _collect_patched_symbols() -> dict[str, set[str]]:
    """`{module_ui_api: {symboles patches par les tests}}`."""
    patched: dict[str, set[str]] = {}
    for path in _iter_python_files(_TESTS_DIR):
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _PATCH_TARGET_RE.finditer(src):
            parts = match.group(1).split(".")
            # cinesort.ui.api.<module>.<symbole>[...] -> 5 segments minimum
            if len(parts) < 5:
                continue
            if parts[3] == "facades":
                if len(parts) < 6:
                    continue
                module, symbol = ".".join(parts[:5]), parts[5]
            else:
                module, symbol = ".".join(parts[:4]), parts[4]
            patched.setdefault(module, set()).add(symbol)
    return patched


def _collect_top_level_symbol_imports() -> list[tuple[str, int, str, str]]:
    """Imports `from cinesort.ui.api.X import f` situes en TETE de module."""
    found: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files(_UI_API_DIR):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in tree.body:  # corps du module uniquement = import de tete
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if not module.startswith("cinesort.ui.api."):
                continue
            for alias in node.names:
                found.append((rel, node.lineno, module, alias.name))
    return found


class UiApiPatchableImportTests(unittest.TestCase):
    """#779 §11.2 : un import de SYMBOLE en tete fige le binding et tue les patchs.

    `from cinesort.ui.api.library_support import _get_store` ecrit en tete lie
    l'objet AU CHARGEMENT du module. Un test qui fait ensuite
    `patch("cinesort.ui.api.library_support._get_store")` remplace l'attribut du
    module SOURCE, mais le consommateur garde sa reference d'origine : le patch
    ne l'atteint plus. Quand le test assertait sur le resultat, il vire au rouge
    et on le voit ; quand il n'observe que l'absence d'effet, il reste VERT et
    ne teste plus rien. Ce defaut a ete trouve par mutation, pas par relecture.

    Regle : cible dans `ui/api` => importer le MODULE
    (`from cinesort.ui.api import library_support`) et appeler
    `library_support._get_store(...)`, ce qui garde la resolution tardive.
    """

    def test_patched_symbols_are_not_bound_at_import_time(self) -> None:
        patched = _collect_patched_symbols()
        violations = []
        for rel, lineno, module, symbol in _collect_top_level_symbol_imports():
            if symbol not in patched.get(module, ()):
                continue
            if (rel, module, symbol) in _KNOWN_SYMBOL_IMPORTS:
                continue
            violations.append(f"{rel}:{lineno}  from {module} import {symbol}")
        self.assertEqual(
            violations,
            [],
            msg=(
                "Import de symbole en tete d'une cible que les tests patchent "
                "(cf. REFACTOR_PLAN_84.md §11.2) :\n  " + "\n  ".join(violations) + "\n"
                "Le patch pose par le test n'atteindra pas ce consommateur. "
                "Passer en module-style : `from cinesort.ui.api import <module>` puis "
                "`<module>.<symbole>(...)`."
            ),
        )

    def test_known_symbol_imports_still_exist(self) -> None:
        """Cliquet : une entree gelee qui a ete corrigee doit sortir de la liste."""
        actual = {(rel, module, symbol) for rel, _lineno, module, symbol in _collect_top_level_symbol_imports()}
        stale = sorted(_KNOWN_SYMBOL_IMPORTS - actual)
        self.assertEqual(
            stale,
            [],
            msg=(
                f"_KNOWN_SYMBOL_IMPORTS gele des imports qui n'existent plus : {stale}. "
                "Retirer l'entree pour que le cliquet reste a zero marge."
            ),
        )


if __name__ == "__main__":
    unittest.main()
