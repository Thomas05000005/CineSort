"""Harnais d'execution Node pour les modules ESM du dashboard.

Motivation (memoire projet « verifier en RUNTIME, pas par grep ») : les
findings frontend de la revue post-merge 2026-07-18 (F04/F05/F21/F23/F25) sont
des bugs de SEQUENCE (debounce annule, reponse tardive, onglet ecrase, cache de
signature, boucle bulk). Une assertion `assertIn("...", source)` ne prouverait
rien : elle passe au vert des qu'on ecrit la bonne chaine, meme si la logique
est fausse.

Ce module charge donc la VRAIE source `web/dashboard/**/*.js`, neutralise
uniquement ses `import ... from "..."` (remplaces par des stubs injectes) et
execute le module sous Node. Le corps des fonctions testees n'est jamais
reecrit : c'est bien le code de production qui tourne.

Usage :
    res = run_module_test(JS_PATH, stubs=STUBS_JS, extra=EXTRA_EXPORTS_JS,
                          driver=DRIVER_JS)
    assert res["...

`run_module_test` retourne le JSON imprime par le driver via
`__emit(obj)` (helper injecte).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "web" / "dashboard"

# `import ... ;` — les specificateurs ESM ne contiennent jamais de ';' donc un
# match non-greedy jusqu'au premier ';' est sur, y compris sur import multi-ligne.
_IMPORT_RE = re.compile(r"(?m)^import\b[^;]*;")


# `export const|let|var|function|async|class` en debut de ligne. On ne retire QUE
# le mot-cle `export` : le corps declare reste strictement identique.
_EXPORT_RE = re.compile(r"(?m)^export\s+(?=(?:const|let|var|function|async|class)\b)")


def node_available() -> bool:
    return shutil.which("node") is not None


def inline_module(rel_path: str) -> str:
    """Injecte la VRAIE source d'un module `web/dashboard/**` dans les stubs.

    Quand le module sous test IMPORTE un helper partage, `strip_imports` efface
    l'import : sans rien de plus, le driver leve un ReferenceError. Le reflexe
    « j'ecris un stub qui fait la meme chose » produirait un FAUX VERT — le test
    verifierait alors la copie du testeur, pas le code livre. On injecte donc le
    fichier de production tel quel, `export` retire (le corps n'est jamais
    reecrit), pour que ce soit bien lui qui s'execute.

    Refuse un module a dependances : il faudrait les inliner recursivement, et
    un echec silencieux redonnerait un faux vert.
    """
    src = (DASHBOARD / rel_path).read_text(encoding="utf-8")
    out, n = _EXPORT_RE.subn("", src)
    if n == 0:
        raise AssertionError(f"{rel_path} : aucun `export ` retire, rien ne serait visible du module")
    if _IMPORT_RE.search(out):
        raise AssertionError(f"{rel_path} : le module a des imports, inlining non supporte")
    return out


def require_node(test: unittest.TestCase) -> None:
    if not node_available():
        test.skipTest("node introuvable dans le PATH")


def strip_imports(src: str) -> str:
    """Retire les declarations d'import (remplacees par des stubs injectes).

    Remplace chaque import par une ligne vide pour PRESERVER la numerotation
    des lignes (les traces d'erreur Node restent exploitables).
    """

    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    out, n = _IMPORT_RE.subn(_blank, src)
    if n == 0:
        raise AssertionError("aucun import trouve : le harnais ne s'applique pas a ce fichier")
    return out


_PRELUDE = r"""
// --- prelude harnais (injecte) ---
globalThis.__emit = (obj) => { process.stdout.write("<<<JSON>>>" + JSON.stringify(obj) + "<<<END>>>"); };
globalThis.__sleep = (ms) => new Promise((r) => setTimeout(r, ms));
"""


def build_module(js_path: Path, stubs: str, extra: str, out_dir: Path) -> Path:
    src = strip_imports(js_path.read_text(encoding="utf-8"))
    mod = out_dir / "mod.mjs"
    mod.write_text(_PRELUDE + stubs + "\n" + src + "\n" + extra + "\n", encoding="utf-8")
    return mod


def run_module_test(
    js_path: Path,
    *,
    stubs: str,
    extra: str,
    driver: str,
    timeout: int = 60,
) -> dict:
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        build_module(js_path, stubs, extra, out_dir)
        drv = out_dir / "driver.mjs"
        drv.write_text('import * as M from "./mod.mjs";\n' + driver, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(drv)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    if proc.returncode != 0:
        raise AssertionError(
            f"driver node en echec (rc={proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    m = re.search(r"<<<JSON>>>(.*?)<<<END>>>", proc.stdout, re.S)
    if not m:
        raise AssertionError(f"driver node n'a rien emis\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(m.group(1))


def node_check(test: unittest.TestCase, js_path: Path) -> None:
    require_node(test)
    proc = subprocess.run(
        ["node", "--check", str(js_path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    test.assertEqual(proc.returncode, 0, f"node --check {js_path.name} : {proc.stderr}")


def esm_syntax_error(js_path: Path) -> str:
    """Parse le fichier en tant que MODULE ES et retourne l'erreur, ou "".

    `node --check fichier.js` parse en mode SCRIPT (CommonJS) et laisse passer
    des fichiers que le navigateur refuse : mesure faite le 2026-08-03 sur
    historique.js ou une backquote glissee dans un commentaire HTML *a
    l'interieur d'un template literal* fermait la chaine prematurement —
    `node --check x.js` -> rc=0, `node --check x.mjs` -> rc=1 (SyntaxError).
    Le dashboard etant 100 % ESM, c'est la seconde qui fait foi.
    """
    src = js_path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        mjs = Path(td) / (js_path.stem + ".mjs")
        mjs.write_text(src, encoding="utf-8")
        proc = subprocess.run(
            ["node", "--check", str(mjs)], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    return "" if proc.returncode == 0 else (proc.stderr or "").strip()
