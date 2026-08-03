# -*- coding: utf-8 -*-
"""M1 — Matrice de cablage UI (apiPost) -> API (6 facades).

REJOUABLE :
    python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m1_ui_api.py

Ce script NE MODIFIE aucun fichier source. Il :
 1. scanne web/dashboard/**/*.js, extrait chaque site d'appel apiPost(
    (commentaires JS strippes, numeros de ligne preserves) : endpoint +
    cles du payload (heuristique regex sur l'objet litteral) ;
 2. introspection Python des 6 facades (cinesort.ui.api.facades.*) via
    inspect.signature (params requis / optionnels / **kwargs) ;
 3. croise les deux sens :
    - AVANT  (UI -> API) : verdicts OK / ENDPOINT_INEXISTANT / MAUVAISE_FACADE /
      PAYLOAD_DESACCORDE / EXCLU (_EXCLUDED_METHODS de rest_server.py) /
      NON_RESOLU (endpoint dynamique non resolvable statiquement) ;
    - ARRIERE (API -> UI) : chaque methode de facade est-elle consommee par le
      JS du dashboard ? verdicts CONSOMMEE / ORPHELINE / ORPHELINE_INCERTAINE
      (nom nu present mais jamais "facade/methode") / EXCLU.
 4. ecrit docs/internal/verif_totale_2026_07/matrices/m1_ui_api.json.

Contexte serveur (cinesort/infra/rest_server.py) :
 - dispatch : result = method(**params)  -> TypeError => 400
   => cle inattendue sans **kwargs, ou param requis manquant = PAYLOAD_DESACCORDE
 - Pass 1 legacy ("/api/<methode>" sans facade) DESACTIVEE par defaut => 410 Gone
 - _EXCLUDED_METHODS filtre les methodes en Pass 1 ET en Pass 2 (facades).
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[4]  # .../CineSort
sys.path.insert(0, str(ROOT))

OUT_JSON = ROOT / "docs/internal/verif_totale_2026_07/matrices/m1_ui_api.json"
DASH = ROOT / "web" / "dashboard"

# ---------------------------------------------------------------------------
# 0. Constantes serveur (importees, pas dupliquees -> rejouable apres refactor)
# ---------------------------------------------------------------------------
from cinesort.infra.rest_server import _EXCLUDED_METHODS, _FACADE_ATTR_NAMES  # noqa: E402

FACADE_CLASS = {
    "run": "RunFacade",
    "settings": "SettingsFacade",
    "quality": "QualityFacade",
    "integrations": "IntegrationsFacade",
    "library": "LibraryFacade",
    "runtime": "RuntimeFacade",
}


# ---------------------------------------------------------------------------
# 1. Introspection des facades
# ---------------------------------------------------------------------------
def introspect_facades():
    """{facade: {method: {required, optional, has_kwargs, signature}}}"""
    out = {}
    for fname in _FACADE_ATTR_NAMES:
        mod = importlib.import_module(f"cinesort.ui.api.facades.{fname}_facade")
        cls = getattr(mod, FACADE_CLASS[fname])
        methods = {}
        for name in dir(cls):
            if name.startswith("_"):
                continue
            attr = getattr(cls, name)
            if not callable(attr):
                continue
            try:
                sig = inspect.signature(attr)
            except (TypeError, ValueError):
                methods[name] = {"required": [], "optional": [], "has_kwargs": True, "signature": "<introuvable>"}
                continue
            required, optional, has_kwargs = [], [], False
            for pname, p in sig.parameters.items():
                if pname == "self":
                    continue
                if p.kind == inspect.Parameter.VAR_KEYWORD:
                    has_kwargs = True
                    continue
                if p.kind == inspect.Parameter.VAR_POSITIONAL:
                    continue
                (required if p.default is inspect.Parameter.empty else optional).append(pname)
            methods[name] = {
                "required": required,
                "optional": optional,
                "has_kwargs": has_kwargs,
                "signature": str(sig),
            }
        out[fname] = methods
    return out


# ---------------------------------------------------------------------------
# 2. Scan JS : strip commentaires (lignes preservees) + extraction call sites
# ---------------------------------------------------------------------------
def strip_js_comments(src: str) -> str:
    """Remplace les commentaires // et /* */ par des espaces (newlines gardes).
    Machine a etats simple : suit les chaines ' " ` (avec echappements)."""
    out = list(src)
    i, n = 0, len(src)
    state = None  # None | "'" | '"' | '`' | '//' | '/*'
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c in ("'", '"', "`"):
                state = c
            elif c == "/" and nxt == "/":
                state = "//"
                out[i] = out[i + 1] = " "
                i += 1
            elif c == "/" and nxt == "*":
                state = "/*"
                out[i] = out[i + 1] = " "
                i += 1
        elif state in ("'", '"', "`"):
            if c == "\\":
                i += 1  # saute le char echappe
            elif c == state:
                state = None
            elif c == "\n" and state in ("'", '"'):
                state = None  # chaine non terminee : on se resynchronise
        elif state == "//":
            if c == "\n":
                state = None
            else:
                out[i] = " "
        elif state == "/*":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = None
                i += 1
            elif c != "\n":
                out[i] = " "
        i += 1
    return "".join(out)


IDENT_CHARS = re.compile(r"[A-Za-z0-9_$.]")
ENDPOINT_SHAPE = re.compile(r"^[a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)?$")


def split_top_level_args(text: str):
    """Split une liste d'arguments sur les virgules de profondeur 0."""
    args, depth, cur, i, n = [], 0, [], 0, len(text)
    in_str = None
    while i < n:
        c = text[i]
        if in_str:
            cur.append(c)
            if c == "\\":
                if i + 1 < n:
                    cur.append(text[i + 1])
                    i += 1
            elif c == in_str:
                in_str = None
        elif c in ("'", '"', "`"):
            in_str = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        args.append(tail)
    return args


def extract_call(stripped: str, pos: int):
    """A partir de l'index de '(' apres apiPost, retourne (args_text, end_index)."""
    depth, i, n = 0, pos, len(stripped)
    in_str = None
    start = pos + 1
    while i < n:
        c = stripped[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == in_str:
                in_str = None
        elif c in ("'", '"', "`"):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return stripped[start:i], i
        i += 1
    return stripped[start:], n - 1


KEY_RE = re.compile(r'^(?:(["\'])(?P<qkey>[^"\']+)\1|(?P<key>[A-Za-z_$][\w$]*))\s*:')
SHORTHAND_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def parse_payload_keys(arg: str):
    """Extrait les cles top-level d'un objet litteral JS. Retourne
    (kind, keys, flags) — kind: 'object' | 'empty' | 'expression' | 'absent'."""
    if arg is None or arg == "":
        return "absent", [], []
    a = arg.strip()
    if not a.startswith("{"):
        return "expression", [], []
    inner = a[1 : a.rfind("}")] if a.rfind("}") > 0 else a[1:]
    parts = split_top_level_args(inner)
    keys, flags = [], []
    for part in parts:
        p = part.strip()
        if not p:
            continue
        if p.startswith("..."):
            flags.append("spread")
            continue
        if p.startswith("["):
            flags.append("computed_key")
            continue
        m = KEY_RE.match(p)
        if m:
            keys.append(m.group("qkey") or m.group("key"))
        elif ":" not in p and SHORTHAND_RE.match(p.split("=")[0].strip()):
            keys.append(p.split("=")[0].strip())  # shorthand {foo} / {foo = def}
        else:
            flags.append("non_parse")
    if not keys and not flags:
        return "empty", [], []
    return "object", keys, sorted(set(flags))


ASSIGN_STR_RE = re.compile(r'["\']([a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)?)["\']')


def resolve_dynamic(expr: str, lines, call_line_idx: int, whole_stripped: str):
    """Heuristiques de resolution d'un 1er argument non litteral.
    Retourne (candidats, methode_de_resolution)."""
    expr = expr.strip()
    # Cas dataset.xxx : les valeurs viennent d'attributs data-* / champs testMethod
    m = re.search(r"dataset\.([A-Za-z_$][\w$]*)", expr)
    ident = None
    if not m:
        im = re.match(r"^[A-Za-z_$][\w$]*$", expr)
        if im:
            ident = expr
            # remonter jusqu'a 60 lignes : affectation de l'identifiant
            lo = max(0, call_line_idx - 60)
            for j in range(call_line_idx, lo - 1, -1):
                line = lines[j]
                if re.search(rf"(?:const|let|var)?\s*\b{re.escape(ident)}\b\s*=(?!=)", line):
                    seg = line + " " + (lines[j + 1] if j + 1 < len(lines) else "")
                    cands = [s for s in ASSIGN_STR_RE.findall(seg) if ENDPOINT_SHAPE.match(s)]
                    if cands:
                        return sorted(set(cands)), f"affectation ligne {j + 1}"
                    dm = re.search(r"dataset\.([A-Za-z_$][\w$]*)", seg)
                    if dm:
                        m = dm
                        break
    if m:
        attr = m.group(1)
        kebab = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", attr).lower()
        pat = re.compile(
            rf'(?:\b{re.escape(attr)}\s*:\s*|data-{re.escape(kebab)}\s*=\s*)["\']'
            rf"([a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)?)[\"']"
        )
        cands = [s for s in pat.findall(whole_stripped) if ENDPOINT_SHAPE.match(s)]
        if cands:
            return sorted(set(cands)), f"valeurs de dataset.{attr} dans le fichier"
    return [], f"expression dynamique non resolue: {expr[:80]}"


def scan_js():
    """Retourne (sites, corpus_stripped_par_fichier)."""
    sites = []
    corpus = {}
    for path in sorted(DASH.rglob("*.js")):
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8", errors="replace")
        stripped = strip_js_comments(src)
        corpus[rel] = stripped
        lines = stripped.split("\n")
        for mo in re.finditer(r"apiPost\s*\(", stripped):
            s = mo.start()
            prev = stripped[s - 1] if s > 0 else ""
            if prev and IDENT_CHARS.match(prev):
                continue  # _spaApiPost, monApiPost, etc.
            head = stripped[max(0, s - 40) : s]
            if re.search(r"function\s+$", head):
                continue  # definition du wrapper, pas un appel
            line_no = stripped.count("\n", 0, s) + 1
            args_text, _end = extract_call(stripped, s + mo.group(0).__len__() - 1)
            args = split_top_level_args(args_text)
            first = args[0] if args else ""
            second = args[1] if len(args) > 1 else None
            entry = {
                "file": rel,
                "line": line_no,
                "arg_raw": first.replace("\n", " ")[:120],
            }
            fs = first.strip()
            if fs[:1] in ("'", '"') and fs[-1:] == fs[:1]:
                entry["endpoints"] = [fs[1:-1]]
                entry["resolution"] = "litteral"
            elif fs[:1] == "`" and "${" not in fs:
                entry["endpoints"] = [fs[1:-1]]
                entry["resolution"] = "litteral (template)"
            else:
                cands, how = resolve_dynamic(fs, lines, line_no - 1, stripped)
                entry["endpoints"] = cands
                entry["resolution"] = f"dynamique — {how}"
            kind, keys, flags = parse_payload_keys(second)
            entry["payload_kind"] = kind
            entry["payload_keys"] = keys
            entry["payload_flags"] = flags
            sites.append(entry)
    return sites, corpus


# ---------------------------------------------------------------------------
# 3. Verdicts sens AVANT (UI -> API)
# ---------------------------------------------------------------------------
def find_method_elsewhere(facades, method):
    return sorted(f for f, ms in facades.items() if method in ms)


def check_payload(spec, kind, keys, flags):
    """Retourne (verdict_payload_ok, details[]). Regles alignees sur
    method(**params) : requis manquant OU cle inconnue sans **kwargs => 400."""
    details = []
    if kind in ("expression", "absent"):
        # params construit dynamiquement ({} par defaut cote wrapper si absent)
        if kind == "absent" and spec["required"]:
            details.append("payload absent mais params requis: " + ", ".join(spec["required"]))
            return False, details
        return True, (["payload non analysable (expression)"] if kind == "expression" else [])
    known = set(spec["required"]) | set(spec["optional"])
    partial = bool(set(flags) & {"spread", "computed_key", "non_parse"})
    missing = [r for r in spec["required"] if r not in keys]
    if missing and not partial:
        details.append("params requis manquants: " + ", ".join(missing))
    unexpected = [k for k in keys if k not in known]
    if unexpected and not spec["has_kwargs"]:
        details.append("cles inconnues de la signature (TypeError => 400): " + ", ".join(unexpected))
    if partial:
        details.append("payload partiellement analyse (" + ",".join(flags) + ")")
    ok = not ((missing and not partial) or (unexpected and not spec["has_kwargs"]))
    return ok, details


def verdict_forward(site, facades):
    results = []
    if not site["endpoints"]:
        results.append({**site, "endpoint": None, "verdict": "NON_RESOLU", "detail": site["resolution"]})
        return results
    for ep in site["endpoints"]:
        row = {**site, "endpoint": ep}
        row.pop("endpoints", None)
        if "/" in ep:
            fac, meth = ep.split("/", 1)
        else:
            fac, meth = None, ep
        if meth in _EXCLUDED_METHODS:
            row["verdict"] = "EXCLU"
            row["detail"] = (
                f"methode '{meth}' dans _EXCLUDED_METHODS (rest_server.py) => "
                "jamais exposee en REST (404), appel UI mort"
            )
        elif fac is None:
            elsewhere = find_method_elsewhere(facades, meth)
            row["verdict"] = "ENDPOINT_INEXISTANT"
            row["detail"] = "appel legacy sans facade => 410 Gone (Pass 1 desactivee par defaut)" + (
                f" ; methode presente sur: {', '.join(elsewhere)}" if elsewhere else ""
            )
        elif fac not in facades:
            elsewhere = find_method_elsewhere(facades, meth)
            row["verdict"] = "MAUVAISE_FACADE" if elsewhere else "ENDPOINT_INEXISTANT"
            row["detail"] = f"facade '{fac}' inconnue" + (
                f" ; methode presente sur: {', '.join(elsewhere)}" if elsewhere else ""
            )
        elif meth not in facades[fac]:
            elsewhere = find_method_elsewhere(facades, meth)
            if elsewhere:
                row["verdict"] = "MAUVAISE_FACADE"
                row["detail"] = f"'{meth}' absent de la facade '{fac}' mais present sur: " + ", ".join(elsewhere)
            else:
                row["verdict"] = "ENDPOINT_INEXISTANT"
                row["detail"] = f"'{meth}' absent des 6 facades => 404"
        else:
            spec = facades[fac][meth]
            ok, details = check_payload(spec, site["payload_kind"], site["payload_keys"], site["payload_flags"])
            row["verdict"] = "OK" if ok else "PAYLOAD_DESACCORDE"
            row["detail"] = "; ".join(details) if details else f"signature {spec['signature']}"
        results.append(row)
    return results


# ---------------------------------------------------------------------------
# 4. Sens ARRIERE (API -> UI)
# ---------------------------------------------------------------------------
def reverse_matrix(facades, corpus, forward_rows):
    used_endpoints = {r["endpoint"] for r in forward_rows if r.get("endpoint")}
    big = "\n".join(corpus.values())
    rows = []
    for fac, methods in facades.items():
        for meth, spec in sorted(methods.items()):
            ep = f"{fac}/{meth}"
            literal = len(re.findall(re.escape(ep) + r"\b", big))
            bare = len(re.findall(rf"\b{re.escape(meth)}\b", big))
            if meth in _EXCLUDED_METHODS:
                verdict = "EXCLU"
            elif literal > 0 or ep in used_endpoints:
                verdict = "CONSOMMEE"
            elif bare > 0:
                verdict = "ORPHELINE_INCERTAINE"
            else:
                verdict = "ORPHELINE"
            rows.append(
                {
                    "facade": fac,
                    "method": meth,
                    "endpoint": ep,
                    "verdict": verdict,
                    "literal_refs": literal,
                    "bare_name_refs": bare,
                    "signature": spec["signature"],
                }
            )
    return rows


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------
def main():
    facades = introspect_facades()
    sites, corpus = scan_js()
    forward = []
    for site in sites:
        forward.extend(verdict_forward(site, facades))
    reverse = reverse_matrix(facades, corpus, forward)

    fstats, rstats = {}, {}
    for r in forward:
        fstats[r["verdict"]] = fstats.get(r["verdict"], 0) + 1
    for r in reverse:
        rstats[r["verdict"]] = rstats.get(r["verdict"], 0) + 1

    n_methods = sum(len(m) for m in facades.values())
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": str(SCRIPT.relative_to(ROOT).as_posix()),
            "root": str(ROOT),
            "js_files_scanned": len(corpus),
            "apipost_call_sites": len(sites),
            "forward_rows": len(forward),
            "facade_methods_total": n_methods,
            "excluded_methods": sorted(_EXCLUDED_METHODS),
            "regles": {
                "dispatch": "rest_server.py L1197 result = method(**params); TypeError => 400",
                "legacy": "Pass 1 desactivee par defaut => /api/<methode> sans facade = 410 Gone",
                "exclusion": "_EXCLUDED_METHODS filtre Pass 1 ET Pass 2 (L215+L232)",
            },
        },
        "facades": {f: {m: {k: v for k, v in spec.items()} for m, spec in ms.items()} for f, ms in facades.items()},
        "forward": sorted(forward, key=lambda r: (r["file"], r["line"])),
        "reverse": reverse,
        "stats": {"forward": fstats, "reverse": rstats},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"JS scannes: {len(corpus)} fichiers, {len(sites)} sites apiPost, {len(forward)} lignes forward")
    print(f"Facades: {n_methods} methodes")
    print("STATS forward:", json.dumps(fstats, ensure_ascii=False, sort_keys=True))
    print("STATS reverse:", json.dumps(rstats, ensure_ascii=False, sort_keys=True))
    print("--- findings non-OK (forward) ---")
    for r in payload["forward"]:
        if r["verdict"] not in ("OK",):
            print(f"{r['verdict']} | {r.get('endpoint') or r['arg_raw']} | {r['file']}:{r['line']} | {r['detail']}")
    print("--- orphelines (reverse) ---")
    for r in reverse:
        if r["verdict"].startswith("ORPHELINE"):
            print(f"{r['verdict']} | {r['endpoint']} | bare_refs={r['bare_name_refs']}")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()
