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


def strip_imports(src: str, *, autorise_zero_import: bool = False) -> str:
    """Retire les declarations d'import (remplacees par des stubs injectes).

    Remplace chaque import par une ligne vide pour PRESERVER la numerotation
    des lignes (les traces d'erreur Node restent exploitables).

    `autorise_zero_import` : quelques modules du front sont AUTONOMES et n'ont
    aucun import — `core/cache.js` par exemple. Sans ce drapeau, l'assertion
    ci-dessous les refuse, et c'est VOULU : elle attrape le cas ou l'on croit
    stubber un module alors que le harnais ne s'y applique pas. Le drapeau ne
    l'affaiblit pas, il oblige l'appelant a DECLARER que le module est autonome
    — un silence ne suffit pas.
    """

    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    out, n = _IMPORT_RE.subn(_blank, src)
    if n == 0 and not autorise_zero_import:
        raise AssertionError(
            "aucun import trouve : le harnais ne s'applique pas a ce fichier. "
            "Si le module est REELLEMENT autonome, passer `autorise_zero_import=True`."
        )
    return out


_PRELUDE = r"""
// --- prelude harnais (injecte) ---
globalThis.__emit = (obj) => { process.stdout.write("<<<JSON>>>" + JSON.stringify(obj) + "<<<END>>>"); };
globalThis.__sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// `process.exit()` NE VIDE PAS le pipe. Quatorze fichiers de test terminent
// leur driver par `process.exit(0)` juste apres `__emit` — un motif recopie de
// proche en proche — pour couper court a une minuterie restee armee. Quand
// stdout est un PIPE (ce qui est le cas sous `subprocess.run`), l'ecriture est
// asynchrone : sortir immediatement peut tronquer le JSON deja ecrit. Le
// harnais rapporte alors « driver node n'a rien emis », un echec qui n'a rien a
// voir avec le test.
//
// On rend donc `process.exit` sur-mesure ici plutot que dans les quatorze
// fichiers : le drainage est une propriete du HARNAIS, pas de chaque driver.
// `write("")` rappelle son callback une fois le tampon vide.
//
// Le `setTimeout` de secours couvre le cas ou le callback ne viendrait jamais
// (pipe ferme en face) : sans lui, le driver resterait pendu jusqu'au timeout
// du subprocess. `unref()` l'empeche a son tour de retenir la boucle
// d'evenements, donc il ne change rien a une sortie naturelle.
(() => {
  const sortieReelle = process.reallyExit ? process.reallyExit.bind(process) : null;
  const exitOriginal = process.exit.bind(process);
  let enCours = false;
  process.exit = (code) => {
    if (enCours) { return (sortieReelle || exitOriginal)(code); }
    enCours = true;
    const filet = setTimeout(() => (sortieReelle || exitOriginal)(code), 2000);
    if (filet.unref) { filet.unref(); }
    process.stdout.write("", () => { clearTimeout(filet); exitOriginal(code); });
  };
})();
"""


def build_module(js_path: Path, stubs: str, extra: str, out_dir: Path, *, autorise_zero_import: bool = False) -> Path:
    src = strip_imports(js_path.read_text(encoding="utf-8"), autorise_zero_import=autorise_zero_import)
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
    autorise_zero_import: bool = False,
) -> dict:
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        build_module(js_path, stubs, extra, out_dir, autorise_zero_import=autorise_zero_import)
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


#: Verificateur de syntaxe reel (cf. son en-tete pour la mesure du faux vert).
JS_SYNTAX_CHECKER = ROOT / "scripts" / "check_js_syntax.mjs"


def node_check(test: unittest.TestCase, js_path: Path) -> None:
    """Verifie la syntaxe d'un fichier de `web/` — pour de vrai.

    Cette fonction faisait `node --check <chemin>` et asseyait `returncode == 0`.
    Mesure du 2026-08-03 (Node v24.14.1) : sur 47 des 48 `.js` de
    `web/dashboard/`, cette commande sort en **0 meme avec une erreur de syntaxe
    averee**. Les fichiers sont des modules ESM ; sans `package.json` declarant
    `"type": "module"`, la detection de syntaxe de module de Node s'interpose et
    le processus sort en 0 sans jamais reverifier la source en goal module.
    Toutes les assertions basees sur cette commande etaient donc vides : elles
    n'auraient pas pu echouer.

    Le controle passe desormais par `scripts/check_js_syntax.mjs`, qui impose le
    goal d'analyse explicitement (`--input-type`) et s'auto-teste par canaris
    avant de conclure.
    """
    require_node(test)
    try:
        rel = js_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:  # pragma: no cover - garde de programmation
        raise AssertionError(f"{js_path} est hors du depot : le verificateur ne peut pas le situer") from None
    proc = subprocess.run(
        ["node", str(JS_SYNTAX_CHECKER), "--only", rel],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    test.assertEqual(
        proc.returncode,
        0,
        f"syntaxe invalide dans {rel} :\n{proc.stdout}\n{proc.stderr}",
    )
