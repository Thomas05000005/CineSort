# -*- coding: utf-8 -*-
"""
M5 — Matrice de cablage CSS statique (verif totale 2026-07).

REJOUABLE : python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m5_css.py

Croise :
  - classes CSS DEFINIES dans web/dashboard/*.css + web/shared/*.css
  - classes UTILISEES dans web/dashboard/**/*.js|mjs|html
    (class=, classList.*, className=, cls:, querySelector/closest/matches/$$)
  - couleurs hex en dur hors web/shared/tokens.css (valeurs de declarations CSS
    + litteraux hex dans les JS du dashboard)

Verdicts : OK / UTILISEE_NON_DEFINIE / DEFINIE_NON_UTILISEE / INCERTAIN / HEX_HORS_TOKENS
Les classes construites dynamiquement (prefixe-${var}, arg non litteral de classList)
sont marquees INCERTAIN, jamais ORPHELINE.

Sortie : docs/internal/verif_totale_2026_07/matrices/m5_css.json (UTF-8, sans BOM).
Aucune ecriture hors de matrices/. Aucune execution d'app ni de tests.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # .../CineSort
WEB = REPO / "web"
OUT = REPO / "docs/internal/verif_totale_2026_07/matrices/m5_css.json"

CSS_FILES = sorted((WEB / "dashboard").glob("*.css")) + sorted((WEB / "shared").glob("*.css"))
USAGE_FILES = sorted(
    p for p in (WEB / "dashboard").rglob("*")
    if p.suffix in (".js", ".mjs", ".html") and p.is_file()
)

TOKENS_CSS = (WEB / "shared" / "tokens.css").resolve()
CLASS_TOKEN = re.compile(r"^-?[_a-zA-Z][\w-]*$")
CLASS_IN_SELECTOR = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
DECL_RE = re.compile(r"^\s*(--[\w-]+|[a-zA-Z-]+)\s*:(.*)$", re.S)


def rel(p: Path) -> str:
    return p.resolve().relative_to(REPO).as_posix()


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_block_comments(text: str) -> str:
    """Remplace /* ... */ par des espaces en preservant les sauts de ligne."""
    out = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("/*", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = text.find("*/", j + 2)
        if k < 0:
            k = n - 2
        out.append("".join(c if c == "\n" else " " for c in text[j:k + 2]))
        i = k + 2
    return "".join(out)


# ---------------------------------------------------------------- CSS parsing
def parse_css(path: Path, defined, hex_findings):
    """Extrait classes des selecteurs + hex des valeurs de declarations."""
    raw = strip_block_comments(read(path))
    is_tokens = path.resolve() == TOKENS_CSS
    buf = []
    buf_line = 1
    line = 1
    depth = 0
    prelude_stack = []  # contexte selecteur pour les hex

    def flush_prelude():
        text = "".join(buf).strip()
        if text and not text.startswith("@"):
            clean = re.sub(r"(['\"]).*?\1", "", text)  # vire les chaines ([attr="v"])
            for m in CLASS_IN_SELECTOR.finditer(clean):
                defined[m.group(1)].append(f"{rel(path)}:{buf_line}")
        return text or ("@" if not text else text)

    def flush_decl():
        text = "".join(buf)
        m = DECL_RE.match(text)
        if m and not is_tokens:
            prop, value = m.group(1), m.group(2)
            for hm in HEX_RE.finditer(value):
                hex_findings.append({
                    "file": rel(path), "line": buf_line + text[:m.start(2) + hm.start()].count("\n"),
                    "hex": hm.group(0).lower(), "property": prop.strip(),
                    "selector": " > ".join(s[:80] for s in prelude_stack) or "(top)",
                })

    for ch in raw:
        if ch == "\n":
            line += 1
        if ch == "{":
            prelude_stack.append(flush_prelude())
            depth += 1
            buf, buf_line = [], line
        elif ch == "}":
            if depth > 0:
                flush_decl()
                depth -= 1
                prelude_stack and prelude_stack.pop()
            buf, buf_line = [], line
        elif ch == ";":
            if depth > 0:
                flush_decl()
            buf, buf_line = [], line
        else:
            if not buf and ch.strip():
                buf_line = line
            if buf or ch.strip():
                buf.append(ch)


# ---------------------------------------------------- template value expansion
def split_template(value: str):
    """Decoupe 'a-${x} b' en parts [('t','a-'),('e','x'),('t',' b')]."""
    parts = []
    i, n = 0, len(value)
    while i < n:
        j = value.find("${", i)
        if j < 0:
            parts.append(("t", value[i:]))
            break
        if j > i:
            parts.append(("t", value[i:j]))
        depth, k = 1, j + 2
        while k < n and depth:
            if value[k] == "{":
                depth += 1
            elif value[k] == "}":
                depth -= 1
            k += 1
        parts.append(("e", value[j + 2:k - 1]))
        i = k
    return parts


VALUE_LIT = re.compile(r"(?:\?|:|\|\||&&)\s*(['\"])((?:[^'\"\\]|\\.)*?)\1")


def expand_value(value, sink):
    """Analyse une valeur d'attribut class / arg classList.

    sink.static  : set de classes sures
    sink.prefix  : dict prefixe -> occurrences (classe dynamique prefixe-${var})
    sink.unknown : int (dynamique sans prefixe exploitable)
    """
    parts = split_template(value)
    # reconstruit les tokens (separes par blancs dans les parts texte)
    tokens, cur = [], []
    for kind, txt in parts:
        if kind == "e":
            cur.append(("e", txt))
            continue
        pieces = re.split(r"(\s+)", txt)
        for pc in pieces:
            if not pc:
                continue
            if pc.isspace():
                if cur:
                    tokens.append(cur)
                cur = []
            else:
                cur.append(("t", pc))
    if cur:
        tokens.append(cur)

    for tok in tokens:
        if all(k == "t" for k, _ in tok):
            name = "".join(t for _, t in tok)
            if CLASS_TOKEN.match(name):
                sink["static"].add(name)
            continue
        # token avec expression(s)
        prefix = tok[0][1] if tok[0][0] == "t" else ""
        exprs = [t for k, t in tok if k == "e"]
        trailing = len(tok) > (2 if prefix else 1)  # du contenu apres la 1re expr
        lits = []
        for e in exprs:
            lits += [m.group(2) for m in VALUE_LIT.finditer(e)]
        if len(exprs) == 1 and not trailing and lits:
            for lit in lits:
                if lit == "":
                    if prefix and CLASS_TOKEN.match(prefix):
                        sink["static"].add(prefix)
                elif lit[0].isspace():
                    if prefix and CLASS_TOKEN.match(prefix):
                        sink["static"].add(prefix)
                    for sub in lit.split():
                        if CLASS_TOKEN.match(sub):
                            sink["static"].add(sub)
                else:
                    combined = (prefix + lit).split()
                    for sub in combined:
                        if CLASS_TOKEN.match(sub):
                            sink["static"].add(sub)
        elif prefix:
            sink["prefix"][prefix] += 1
        else:
            sink["unknown"] += 1


# ------------------------------------------------------------ usage extraction
CLASS_ATTR_RES = [
    re.compile(r'class\s*=\s*"([^"]*)"'),
    re.compile(r"class\s*=\s*'([^']*)'"),
    re.compile(r'class=\\"((?:[^"\\]|\\(?!"))*)\\"'),
]
CLASSLIST_RE = re.compile(r"classList\s*\.\s*(add|remove|toggle|contains|replace)\s*\(([^()]*)\)")
CLASSNAME_RE = re.compile(r"\.className\s*\+?=\s*(['\"`])((?:[^\\]|\\.)*?)\1")
CLSPROP_RE = re.compile(r"\bcls\s*[:=]\s*(['\"`])((?:[^'\"`\\]|\\.)*?)\1")
STRLIT_RE = re.compile(r"(['\"`])((?:[^\\]|\\.)*?)\1")
SELECTOR_CALL_RE = re.compile(
    r"(?:querySelectorAll|querySelector|closest|matches|\$\$)\s*\(\s*(['\"`])((?:[^\\]|\\.)*?)\1"
)
SEL_CLASS_RE = re.compile(r"\.(-?[_a-zA-Z][\w-]*(?:\$\{)?)")


def lineno(text, pos):
    return text.count("\n", 0, pos) + 1


def scan_usage(path: Path, used, prefixes, unknown_dyn):
    text = read(path)
    if path.suffix in (".js", ".mjs"):
        text = strip_block_comments(text)
    fp = rel(path)

    def sink_at(pos, ctx):
        ln = lineno(text, pos)
        s = {"static": set(), "prefix": defaultdict(int), "unknown": 0}
        def commit():
            for c in s["static"]:
                used[c].append({"file": fp, "line": ln, "ctx": ctx})
            for p, n in s["prefix"].items():
                prefixes[p].append({"file": fp, "line": ln, "ctx": ctx, "n": n})
            if s["unknown"]:
                unknown_dyn.append({"file": fp, "line": ln, "ctx": ctx})
        return s, commit

    for rx in CLASS_ATTR_RES:
        for m in rx.finditer(text):
            s, commit = sink_at(m.start(), "class-attr")
            expand_value(m.group(1), s)
            commit()

    if path.suffix == ".html":
        return

    for m in CLASSLIST_RE.finditer(text):
        method, args = m.group(1), m.group(2)
        s, commit = sink_at(m.start(), f"classList.{method}")
        arg_lits = list(STRLIT_RE.finditer(args))
        for a in arg_lits:
            expand_value(a.group(2), s)
        # arg non litteral (variable/const) -> dynamique inconnu
        residue = STRLIT_RE.sub("", args)
        if re.search(r"[A-Za-z_$]", residue.replace("true", "").replace("false", "")):
            if method != "toggle" or not arg_lits:
                s["unknown"] += 1
        commit()

    for m in CLASSNAME_RE.finditer(text):
        s, commit = sink_at(m.start(), "className=")
        expand_value(m.group(2), s)
        commit()

    for m in CLSPROP_RE.finditer(text):
        s, commit = sink_at(m.start(), "cls-prop")
        expand_value(m.group(2), s)
        commit()

    for m in SELECTOR_CALL_RE.finditer(text):
        sel = m.group(2)
        s, commit = sink_at(m.start(), "selector")
        for cm in SEL_CLASS_RE.finditer(sel):
            name = cm.group(1)
            if name.endswith("${"):
                s["prefix"][name[:-2]] += 1
            elif CLASS_TOKEN.match(name):
                s["static"].add(name)
        commit()


# ----------------------------------------------------------------------- main
def main():
    defined = defaultdict(list)   # classe -> [file:line]
    hex_findings = []
    for f in CSS_FILES:
        parse_css(f, defined, hex_findings)

    used = defaultdict(list)      # classe -> [{file,line,ctx}]
    prefixes = defaultdict(list)  # prefixe dynamique -> occurrences
    unknown_dyn = []
    for f in USAGE_FILES:
        scan_usage(f, used, prefixes, unknown_dyn)

    # hex en dur dans les JS du dashboard (bonus, meme verdict)
    for f in USAGE_FILES:
        if f.suffix == ".html":
            continue
        text = strip_block_comments(read(f))
        for m in re.finditer(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b", text):
            ctx = text[max(0, m.start() - 60):m.start() + 20].splitlines()[-1].strip()
            hex_findings.append({
                "file": rel(f), "line": lineno(text, m.start()),
                "hex": m.group(0).lower(), "property": "(js)", "selector": ctx[:100],
            })

    prefix_list = sorted(prefixes)
    classes = []
    stats = defaultdict(int)

    for cls in sorted(set(defined) | set(used)):
        d, u = defined.get(cls), used.get(cls)
        if d and u:
            verdict, note = "OK", ""
            if all(e["ctx"] == "selector" for e in u):
                note = "reference uniquement en querySelector (jamais posee statiquement)"
            if all("/tests/" in e["file"] for e in u):
                verdict, note = "INCERTAIN", "utilisee uniquement dans web/dashboard/tests/"
        elif u:
            verdict = "UTILISEE_NON_DEFINIE"
            note = ("hook JS (posee et selectionnee cote JS, jamais stylee)"
                    if {e["ctx"] for e in u} & {"class-attr", "classList.add", "className=", "cls-prop"}
                    and any(e["ctx"] == "selector" for e in u) else "")
        else:
            hits = [p for p in prefix_list if cls.startswith(p)]
            if hits:
                verdict = "INCERTAIN"
                note = "peut etre construite dynamiquement via prefixe(s): " + ", ".join(hits)
            else:
                verdict, note = "DEFINIE_NON_UTILISEE", ""
        stats[verdict] += 1
        entry = {
            "class": cls, "verdict": verdict,
            "defined_in": (d or [])[:8],
            "used_in": [f'{e["file"]}:{e["line"]} ({e["ctx"]})' for e in (u or [])[:8]],
        }
        if note:
            entry["note"] = note
        classes.append(entry)

    stats["HEX_HORS_TOKENS"] = len(hex_findings)

    result = {
        "meta": {
            "matrice": "M5 — CSS statique",
            "date": "2026-07-08",
            "branch": "verif/totale-2026-07",
            "css_files": [rel(f) for f in CSS_FILES],
            "usage_files_count": len(USAGE_FILES),
            "usage_globs": ["web/dashboard/**/*.js", "web/dashboard/**/*.mjs", "web/dashboard/**/*.html"],
            "hex_scope": "valeurs de declarations CSS (hors web/shared/tokens.css) + litteraux hex 6/8 digits dans les JS dashboard",
            "limites": [
                "analyse statique pure, pas de runtime (Phase 3)",
                "classes en variables JS non litterales -> comptees en dynamiques inconnues",
                "web/splash.html hors scope (styles inline autonomes)",
            ],
            "dynamic_unknown_count": len(unknown_dyn),
        },
        "stats": dict(sorted(stats.items())),
        "dynamic_prefixes": {
            p: [f'{e["file"]}:{e["line"]}' for e in v[:5]] for p, v in sorted(prefixes.items())
        },
        "dynamic_unknown": unknown_dyn[:40],
        "classes": classes,
        "hex_hors_tokens": hex_findings,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"defined={len(defined)} used={len(used)} prefixes={len(prefix_list)} "
          f"unknown_dyn={len(unknown_dyn)} hex={len(hex_findings)}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"-> {rel(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
