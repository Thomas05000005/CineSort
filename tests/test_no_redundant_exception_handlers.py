"""Garde-fou : aucun `except (...)` ne cite une exception deja couverte (#585).

`PermissionError`, `FileNotFoundError`, `FileExistsError`, `TimeoutError`,
`ConnectionError`... heritent toutes d'`OSError`. Les citer a cote d'`OSError`
est du code mort qui trompe le lecteur : il croit qu'`OSError` seul ne suffit
pas. 189 handlers portaient ce bruit avant le lot #585.

Pourquoi ce test et pas la regle ruff `B014` proposee par l'issue : **B014 ne
detecte PAS la redondance par sous-classe**. Verifie sur ruff 0.15.22, la
version epinglee du depot, avec un controle positif pour ecarter le faux vert :

    except (ValueError, ValueError)                   -> B014 (la regle tourne)
    except (OSError, PermissionError, FileNotFoundError) -> AUCUN diagnostic

Le correctif propose par #585 (`ruff check --fix --select B014`) etait donc
inoperant sur les sites qu'il visait.

CE QUE CE TEST NE PROUVE PAS
----------------------------
Il ne verifie que des noms **builtin** resolus via le module `builtins`. Une
redondance passant par une exception du projet ou d'une bibliotheque
(`urllib.error.URLError` herite d'`OSError`, `sqlite3.DatabaseError` herite de
`sqlite3.Error`) n'est pas detectee : la resoudre demanderait d'importer le
module, donc d'executer du code de production a la collecte.

Il ne verifie PAS non plus `tests/` : du bruit dans un test ne trompe pas la
lecture d'un chemin de production.

PIEGE A NE PAS REINTRODUIRE
---------------------------
`sqlite3.Error` n'herite PAS d'`OSError`. Un `except (sqlite3.Error, OSError)`
n'est pas redondant et ce test ne doit jamais le signaler — d'ou le refus
categorique de toucher a un membre non-builtin.
"""

from __future__ import annotations

import ast
import builtins
import os
import unittest
from pathlib import Path

EXCLUDED_DIRS = frozenset({"__pycache__"})


def _builtin_exception(node: ast.expr) -> type | None:
    """Resout un `ast.Name` vers la classe builtin d'exception, sinon None.

    Tout ce qui n'est pas un nom builtin (`sqlite3.Error`, `JellyfinError`,
    `zipfile.BadZipFile`...) renvoie None et est traite comme intouchable.
    """
    if isinstance(node, ast.Name):
        obj = getattr(builtins, node.id, None)
        if isinstance(obj, type) and issubclass(obj, BaseException):
            return obj
    return None


def _redundant_members(elts: list[ast.expr]) -> list[str]:
    """Membres builtin deja couverts par un AUTRE membre du meme tuple."""
    classes = [_builtin_exception(e) for e in elts]
    out: list[str] = []
    for i, ci in enumerate(classes):
        if ci is None:
            continue
        for j, cj in enumerate(classes):
            if i == j or cj is None:
                continue
            # sous-classe stricte, ou doublon exact (le premier cite fait foi)
            if issubclass(ci, cj) and (ci is not cj or j < i):
                out.append(ast.unparse(elts[i]))
                break
    return out


def find_redundant_handlers(root: Path) -> list[str]:
    """Retourne `fichier:ligne  except (...) -> [membres redondants]`."""
    findings: list[str] = []
    for dirpath, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for fname in sorted(fnames):
            if not fname.endswith(".py"):
                continue
            path = Path(dirpath) / fname
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if not isinstance(node.type, ast.Tuple):
                    continue
                redundant = _redundant_members(node.type.elts)
                if redundant:
                    clause = ", ".join(ast.unparse(e) for e in node.type.elts)
                    rel = path.as_posix()
                    findings.append(f"{rel}:{node.lineno}  except ({clause})  -> deja couvert: {redundant}")
    return findings


class TestNoRedundantExceptionHandlers(unittest.TestCase):
    """#585 : plus aucun membre d'`except (...)` couvert par un autre membre."""

    def test_le_detecteur_voit_une_redondance_construite(self) -> None:
        """Anti-test-vacant : le detecteur doit RECONNAITRE les cas connus.

        Sans cette assertion, un detecteur casse (qui ne trouve jamais rien)
        rendrait `test_aucun_handler_redondant` vert pour la mauvaise raison.
        """
        tree = ast.parse("try:\n    pass\nexcept (OSError, PermissionError, FileNotFoundError):\n    pass\n")
        handler = tree.body[0].handlers[0]
        assert isinstance(handler.type, ast.Tuple)
        self.assertEqual(
            _redundant_members(handler.type.elts),
            ["PermissionError", "FileNotFoundError"],
        )

    def test_sqlite3_error_nest_jamais_signale(self) -> None:
        """`sqlite3.Error` n'herite PAS d'`OSError` (regle inviolable du projet)."""
        tree = ast.parse("try:\n    pass\nexcept (sqlite3.Error, OSError):\n    pass\n")
        handler = tree.body[0].handlers[0]
        assert isinstance(handler.type, ast.Tuple)
        self.assertEqual(_redundant_members(handler.type.elts), [])

    def test_aucun_handler_redondant(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        findings = find_redundant_handlers(repo_root / "cinesort")
        self.assertEqual(
            findings,
            [],
            msg=(
                f"{len(findings)} `except` citent une exception deja couverte par un autre\n"
                "membre du meme tuple (#585). Retirer le membre couvert : l'ensemble\n"
                "reellement attrape est IDENTIQUE, mais le lecteur cesse de croire\n"
                "qu'`OSError` seul ne suffisait pas.\n\n" + "\n".join(findings[:40])
            ),
        )


if __name__ == "__main__":
    unittest.main()
