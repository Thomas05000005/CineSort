# -*- coding: utf-8 -*-
"""M8 — Matrice pollers/timers/cleanup du dashboard SPA.

Rejouable :
    python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m8_timers.py

Scanne web/dashboard/**/*.js pour TOUS les setInterval / setTimeout /
requestAnimationFrame / addEventListener sur window|document(.body|.documentElement)
et evalue le cablage cleanup selon la convention lifecycle du router :

  - core/router.js L31-34 + L143-152 : init() de vue retourne un cleanup stocke
    dans _currentCleanup, appele avant chaque navigation. Fallback legacy
    route.unmount (L239-242).
  - core/router.js L159 : stopAllPolling() (core/state.js L286) arrete les
    polls nommes startPolling() a chaque navigation.
  - core/nav-abort.js : abortCurrentNav() coupe les fetchs de la nav precedente.
  - app.js L859-872 : intervals globaux cleares au logout via onClearToken.
  - Modules ESM = singletons : un listener pose au top-level d'un module ne
    s'empile jamais (execute une seule fois au chargement) -> page-lifetime.

Verdicts :
  PROPRE     : clear/remove cable au unmount, ou boot-once page-lifetime,
               ou {once:true}/AbortController/garde idempotente.
  FUITE      : jamais cleare alors que le code re-execute, ou clear existant
               mais jamais appele (ex: unmount non cable au router).
  EMPILEMENT : re-cree a chaque mount de vue/composant sans clear ni garde.
  RACE       : timer qui peut ecrire (DOM/etat) apres unmount de la vue.

Flags complementaires :
  code_mort  : fichier non atteignable depuis app.js / index.html (import graph).
  boot_once  : pose une seule fois au boot (top-level module ou fonction
               appelee uniquement depuis le boot d'app.js).

Sortie : docs/internal/verif_totale_2026_07/matrices/m8_timers.json
Ne modifie AUCUN fichier source.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DASH = ROOT / "web" / "dashboard"
OUT = ROOT / "docs" / "internal" / "verif_totale_2026_07" / "matrices" / "m8_timers.json"

# --- Regex ------------------------------------------------------------------

RE_TIMER = re.compile(r"\b(setInterval|setTimeout|requestAnimationFrame)\s*\(")
RE_LISTENER = re.compile(
    r"\b(window|document\.body|document\.documentElement|document)\s*\.\s*addEventListener\s*\("
    r"\s*[\"']([\w:.-]+)[\"']\s*,\s*([A-Za-z_$][\w$.]*|\(|function|async)"
)
RE_ASSIGN = re.compile(
    r"([A-Za-z_$][\w$.]*(?:\[[^\]]+\])?)\s*=\s*(?:window\.)?"
    r"(?:setInterval|setTimeout|requestAnimationFrame)\s*\("
)
RE_REGISTRY = re.compile(r"\.(set|push)\s*\(.*\b(?:setInterval|setTimeout)\s*\(")
RE_CLEAR = re.compile(r"\b(clearInterval|clearTimeout|cancelAnimationFrame)\s*\(\s*([^);]+?)\s*\)")
RE_REMOVE = re.compile(
    r"\b(window|document\.body|document\.documentElement|document)\s*\.\s*removeEventListener\s*\("
    r"\s*[\"']([\w:.-]+)[\"']\s*,\s*([A-Za-z_$][\w$.]*)"
)
RE_FUNC_DEFS = [
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s+)?function\b"),
    re.compile(r"^\s*(?:async\s+)?([\w$]+)\s*\([^)]*\)\s*\{\s*$"),  # methode objet/classe
]
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "else", "try", "do"}
RE_DELAY = re.compile(r",\s*(\d+)\s*(?:\)|,)")
RE_TIMEOUT_FIRSTARG = re.compile(r"(?:setTimeout|requestAnimationFrame)\s*\(\s*([A-Za-z_$][\w$]*)\s*[,)]")
RE_STRINGS = re.compile(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)')
RE_IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*|import\s+)["'](\.{1,2}/[^"']+\.js)["']""")

MOUNT_FN = re.compile(r"^_?(init|mount|render|open|show|install|bind|attach|create|start|ensure|hook)", re.IGNORECASE)
BOOT_EVENTS = {"DOMContentLoaded", "load", "beforeunload", "pagehide", "unload"}
GUARD_RES = [
    re.compile(r"if\s*\(\s*document\.getElementById\([^)]*\)\s*\)\s*return"),
    re.compile(r"if\s*\(\s*!?_?[\w$.]*([Bb]ound|[Ss]tarted|[Ii]nstalled|[Ii]nitialized|[Mm]ounted)[\w$]*\s*\)"),
    re.compile(r"window\.__\w+__"),
    re.compile(r"!==?\s*null\s*\)\s*return"),
    re.compile(r"==\s*null\s*\)\s*\{?\s*return|== null\) return"),
    re.compile(r"if\s*\(\s*_started\s*\)\s*return"),
]


def strip_line_comment(line):
    idx = 0
    while True:
        idx = line.find("//", idx)
        if idx == -1:
            return line
        before = line[:idx]
        if before.count('"') % 2 == 0 and before.count("'") % 2 == 0 and before.count("`") % 2 == 0:
            return before
        idx += 2


class JsFile:
    def __init__(self, path):
        self.path = path
        self.rel = str(path.relative_to(DASH)).replace("\\", "/")
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        self.lines = text.split("\n")
        self.text = text
        self.comment = self._comment_map()
        self.code = []  # ligne sans commentaires ni contenu de strings
        for i, ln in enumerate(self.lines):
            if self.comment[i]:
                self.code.append("")
            else:
                self.code.append(RE_STRINGS.sub('""', strip_line_comment(ln)))
        # profondeur d'accolades au DEBUT de chaque ligne
        self.depth0 = []
        d = 0
        for c in self.code:
            self.depth0.append(d)
            d += c.count("{") - c.count("}")

    def _comment_map(self):
        flags = [False] * len(self.lines)
        inside = False
        for i, ln in enumerate(self.lines):
            s = ln.strip()
            if inside:
                flags[i] = True
                if "*/" in s:
                    inside = False
                continue
            if s.startswith("/*"):
                flags[i] = True
                if "*/" not in s:
                    inside = True
            elif s.startswith("*") and not s.startswith("*/"):
                # heuristique JSdoc : ligne commencant par * consideree commentaire
                flags[i] = True
            elif s.startswith("*/"):
                flags[i] = True
        return flags

    def enclosing_chain(self, idx):
        """Chaine des fonctions nommees englobantes (proche -> lointaine),
        via suivi de profondeur d'accolades en remontant."""
        chain = []
        depth = 0
        for i in range(idx - 1, -1, -1):
            c = self.code[i]
            depth += c.count("}") - c.count("{")
            if depth < 0:
                for rex in RE_FUNC_DEFS:
                    m = rex.match(self.lines[i])
                    if m and m.group(1) not in KEYWORDS:
                        chain.append((m.group(1), i + 1))
                        break
                depth = 0
        return chain


def context_kind(rel):
    if rel.startswith("tests/"):
        return "tests"
    if rel.startswith("views/"):
        return "vue"
    if rel.startswith("components/"):
        return "composant"
    if rel.startswith("core/"):
        return "core"
    return "app"


RE_DELAY_CLOSE = re.compile(r"^\s*\}\s*,\s*(\d+)\s*\)")


def find_delay(jsf, lineno):
    m = RE_DELAY.search(jsf.code[lineno - 1])
    if m:
        return int(m.group(1))
    # callback multi-lignes : chercher la fermeture "}, NNN)" dans les 12 lignes
    for i in range(lineno, min(lineno + 12, len(jsf.lines))):
        m = RE_DELAY_CLOSE.search(jsf.code[i])
        if m:
            return int(m.group(1))
    return None


def handle_token(h):
    return h.split(".")[-1].split("[")[0].strip()


def build_reachability(files):
    """BFS sur le graphe d'imports depuis les points d'entree reels."""
    entries = set()
    index_html = DASH / "index.html"
    if index_html.exists():
        html = index_html.read_text(encoding="utf-8-sig", errors="replace")
        for m in re.finditer(r'src="\./([^"]+\.js)"', html):
            entries.add(m.group(1))
    entries.add("app.js")
    graph = {}
    for f in files.values():
        deps = set()
        for m in RE_IMPORT.finditer(f.text):
            target = m.group(1)
            base = Path(f.rel).parent
            resolved = (base / target).as_posix()
            parts = []
            for p in resolved.split("/"):
                if p == "..":
                    if parts:
                        parts.pop()
                elif p != ".":
                    parts.append(p)
            deps.add("/".join(parts))
        graph[f.rel] = deps
    reachable = set()
    stack = [e for e in entries if e in graph]
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for d in graph.get(cur, ()):
            if d in graph and d not in reachable:
                stack.append(d)
    return reachable


def build_callsites(files):
    """name -> [(rel, ligne, depth0, texte)] hors definitions et hors tests."""
    defs = {}
    for f in files.values():
        if f.rel.startswith("tests/"):
            continue
        for i, ln in enumerate(f.lines):
            for rex in RE_FUNC_DEFS:
                m = rex.match(ln)
                if m and m.group(1) not in KEYWORDS:
                    defs.setdefault(m.group(1), []).append((f.rel, i + 1))
                    break
    sites = {}
    for f in files.values():
        if f.rel.startswith("tests/"):
            continue
        for i, c in enumerate(f.code):
            for m in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", c):
                name = m.group(1)
                if name in KEYWORDS or name not in defs:
                    continue
                if any(d[0] == f.rel and d[1] == i + 1 for d in defs[name]):
                    continue  # ligne de definition
                sites.setdefault(name, []).append((f.rel, i + 1, f.depth0[i], f.lines[i]))
    return defs, sites


def is_boot_once(name, defs, sites):
    """True si la fonction n'est appelee que depuis le boot d'app.js ou depuis
    le top-level d'un module (ESM = execute une fois)."""
    if name not in defs or len(defs[name]) != 1:
        return False  # nom ambigu -> pas de conclusion
    slist = sites.get(name, [])
    if not slist:
        return False
    for rel, _ln, depth, text in slist:
        if "registerRoute" in text or "init:" in text:
            return False  # cable comme init de route = per-mount
        if rel == "app.js":
            continue  # app.js = module boot (DOMContentLoaded / top-level)
        if depth == 0:
            continue  # top-level d'un module ESM = une seule execution
        return False
    return True


def has_guard(jsf, chain, idx):
    """Garde idempotente entre le debut de la fonction englobante et le match."""
    if not chain:
        return False
    start = chain[0][1] - 1
    for i in range(start, idx + 1):
        for rex in GUARD_RES:
            if rex.search(jsf.code[i]) or rex.search(jsf.lines[i]):
                return True
    return False


def callback_zone(jsf, idx, span=4):
    return "\n".join(jsf.lines[idx : min(idx + span, len(jsf.lines))])


def analyze():
    files = {}
    for path in sorted(DASH.rglob("*.js")):
        f = JsFile(path)
        files[f.rel] = f

    reachable = build_reachability(files)
    defs, sites = build_callsites(files)

    app_text = files["app.js"].text if "app.js" in files else ""
    unmounts_wired = set(re.findall(r"\b(unmount[A-Z]\w*)\b", app_text))

    entries = []
    for rel in sorted(files):
        jsf = files[rel]
        ckind = context_kind(rel)
        dead = (ckind != "tests") and (rel not in reachable)

        clears = []
        removes = []
        for i, c in enumerate(jsf.code):
            for m in RE_CLEAR.finditer(strip_line_comment(jsf.lines[i]) if not jsf.comment[i] else ""):
                clears.append((m.group(1), m.group(2).strip(), i + 1))
            for m in RE_REMOVE.finditer(strip_line_comment(jsf.lines[i]) if not jsf.comment[i] else ""):
                removes.append((m.group(1), m.group(2), m.group(3), i + 1))

        exported_unmounts = set(re.findall(r"export\s+(?:async\s+)?function\s+(unmount\w+)", jsf.text))
        unwired = {u for u in exported_unmounts if u not in unmounts_wired}
        unmount_spans = {}
        for m in re.finditer(r"export\s+(?:async\s+)?function\s+(unmount\w+)", jsf.text):
            unmount_spans[m.group(1)] = jsf.text[: m.start()].count("\n") + 1

        for i, raw in enumerate(jsf.lines):
            if jsf.comment[i]:
                continue
            ln = strip_line_comment(raw)
            lineno = i + 1
            chain = None

            # ---------- addEventListener window/document ----------
            for m in RE_LISTENER.finditer(ln):
                target, event, handler = m.group(1), m.group(2), m.group(3)
                chain = jsf.enclosing_chain(i)
                top_fn = chain[-1][0] if chain else None
                ctx_fn = chain[0][0] if chain else "(module top-level)"
                anon = handler in ("(", "function", "async")
                zone = callback_zone(jsf, i)
                once = re.search(r"\bonce\s*:\s*true", zone) is not None
                signal = re.search(r"\bsignal\s*[:,]", zone) is not None
                removed = [
                    r for r in removes
                    if r[1] == event and (anon or r[2].split(".")[-1] == handler.split(".")[-1])
                ]
                boot = (not chain) or (top_fn and is_boot_once(top_fn, defs, sites))
                guarded = has_guard(jsf, chain, i)
                verdict, note = None, []
                if ckind == "tests":
                    verdict, note = "PROPRE", ["fichier de test, hors bundle runtime"]
                elif event in BOOT_EVENTS:
                    verdict, note = "PROPRE", ["evenement de boot '%s' (tire une seule fois)" % event]
                elif once:
                    verdict, note = "PROPRE", ["{once:true}"]
                elif signal:
                    verdict, note = "PROPRE", ["AbortController signal"]
                elif removed and not anon:
                    verdict = "PROPRE"
                    note = ["removeEventListener '%s' @ L%s" % (event, ",".join(str(r[3]) for r in removed))]
                elif not chain:
                    verdict = "PROPRE"
                    note = ["top-level module ESM = boot-once, page-lifetime"]
                elif boot:
                    verdict = "PROPRE"
                    note = ["boot-once : %s() appelee uniquement au boot (app.js) -> page-lifetime" % top_fn]
                elif guarded:
                    verdict = "PROPRE"
                    note = ["garde idempotente detectee dans %s() (flag/singleton)" % ctx_fn]
                elif removed and anon:
                    verdict = "PROPRE"
                    note = ["removeEventListener '%s' @ L%s (handler stocke)" % (event, ",".join(str(r[3]) for r in removed))]
                elif ckind in ("vue", "composant") and any(MOUNT_FN.match(c[0]) for c in chain):
                    verdict = "EMPILEMENT"
                    note = ["ajoute via %s() a chaque mount, aucun removeEventListener '%s' ni garde" % (ctx_fn, event)]
                else:
                    verdict = "FUITE"
                    note = ["pose dans %s(), jamais retire (handler %s)" % (ctx_fn, "anonyme" if anon else handler)]
                if dead:
                    note.append("CODE MORT : fichier non importe (jamais charge en runtime)")
                entries.append({
                    "fichier": "web/dashboard/" + rel, "ligne": lineno,
                    "type": "addEventListener", "cible": target, "evenement": event,
                    "contexte": ckind, "fonction": ctx_fn,
                    "handle": None if anon else handler,
                    "boot_once": bool(boot), "code_mort": dead,
                    "cleanup": "; ".join(note), "verdict": verdict,
                    "code": ln.strip()[:160],
                })

            # ---------- timers ----------
            for m in RE_TIMER.finditer(ln):
                kind = m.group(1)
                am = RE_ASSIGN.search(ln)
                handle = am.group(1).strip() if am else None
                registry = RE_REGISTRY.search(ln) is not None
                if chain is None:
                    chain = jsf.enclosing_chain(i)
                top_fn = chain[-1][0] if chain else None
                ctx_fn = chain[0][0] if chain else "(module top-level)"
                chain_names = {c[0] for c in chain}
                delay = find_delay(jsf, lineno) if kind != "requestAnimationFrame" else None
                fa = RE_TIMEOUT_FIRSTARG.search(ln)
                recursive = bool(fa and fa.group(1) in chain_names)
                zone = callback_zone(jsf, i, 5)
                zone8 = callback_zone(jsf, i, 9)
                sleep_pattern = bool(fa and fa.group(1) == "resolve")
                cleared = []
                if handle:
                    tok = handle_token(handle)
                    cleared = [c for c in clears if handle_token(c[1]) == tok]
                cleared_in_unmount = any(
                    any(span <= c[2] <= span + 40 for span in unmount_spans.values()) for c in cleared
                )
                boot = (not chain) or (top_fn and is_boot_once(top_fn, defs, sites))
                guarded = has_guard(jsf, chain, i)
                self_guard = bool(re.search(r"==\s*null\s*\)\s*return|\.isConnected", zone))
                raf_self_clear = kind == "requestAnimationFrame" and handle and re.search(
                    re.escape(handle_token(handle)) + r"\s*=\s*null", zone)
                revoke_only = "revokeObjectURL" in zone and kind == "setTimeout"

                verdict, note = None, []
                if ckind == "tests":
                    verdict, note = "PROPRE", ["fichier de test, hors bundle runtime"]
                elif registry:
                    verdict = "PROPRE"
                    note = ["handle stocke dans un registre central + clear via le registre (stopPolling/stopAllPolling)"]
                elif kind == "setInterval":
                    if handle and cleared:
                        verdict = "PROPRE"
                        note = ["clear @ L%s" % ",".join(str(c[2]) for c in cleared)]
                    elif boot:
                        verdict = "PROPRE"
                        note = ["boot-once, page-lifetime"]
                    elif guarded:
                        verdict = "PROPRE"
                        note = ["garde idempotente (singleton)"]
                    elif ckind in ("vue", "composant") and any(MOUNT_FN.match(c[0]) for c in chain):
                        verdict = "EMPILEMENT"
                        note = ["recree via %s() a chaque mount, jamais cleare" % ctx_fn]
                    else:
                        verdict = "FUITE"
                        note = ["jamais cleare (handle %s)" % (handle or "non stocke")]
                elif kind == "requestAnimationFrame":
                    if handle and cleared:
                        verdict = "PROPRE"
                        note = ["cancelAnimationFrame @ L%s" % ",".join(str(c[2]) for c in cleared)]
                    elif raf_self_clear:
                        verdict = "PROPRE"
                        note = ["throttle rAF auto-nettoyant (handle remis a null dans le callback)"]
                    elif not handle:
                        verdict = "PROPRE"
                        note = ["rAF one-shot non stocke (frame unique)"]
                    else:
                        verdict = "FUITE"
                        note = ["rAF stocke mais jamais cancel"]
                else:  # setTimeout
                    if recursive:
                        if handle and cleared:
                            verdict = "PROPRE"
                            note = ["poll auto-rearme, clear @ L%s" % ",".join(str(c[2]) for c in cleared)]
                        elif self_guard:
                            verdict = "PROPRE"
                            note = ["poll auto-rearme avec garde d'arret dans le callback"]
                        else:
                            verdict = "FUITE"
                            note = ["poll auto-rearme (setTimeout recursif) jamais cleare"]
                    elif revoke_only:
                        verdict = "PROPRE"
                        note = ["revokeObjectURL differe (aucun acces DOM)"]
                    elif sleep_pattern:
                        verdict = "PROPRE"
                        note = ["sleep async (setTimeout(resolve, ...)) : la boucle appelante porte ses propres gardes"]
                    elif self_guard:
                        verdict = "PROPRE"
                        note = ["garde dans le callback (== null return / isConnected)"]
                    elif handle and cleared:
                        debounce = any(abs(c[2] - lineno) <= 3 for c in cleared)
                        others = [c for c in cleared if abs(c[2] - lineno) > 3]
                        touches_state = bool(re.search(r"_state\.|_refresh|[Rr]ender\(", zone8))
                        if not debounce or others:
                            verdict = "PROPRE"
                            note = ["clear @ L%s" % ",".join(str(c[2]) for c in cleared)]
                        elif "localStorage.setItem" in zone8 and not touches_state:
                            verdict = "PROPRE"
                            note = ["debounce cleare avant re-set (L%s) ; le callback persiste en localStorage "
                                    "(ecriture voulue meme apres unmount), aucun acces DOM"
                                    % ",".join(str(c[2]) for c in cleared)]
                        elif ckind in ("vue", "composant") and not touches_state and delay is not None and delay <= 500:
                            verdict = "PROPRE"
                            note = ["debounce court (%dms) idempotent, sans acces a l'etat de vue" % delay]
                        elif ckind in ("vue", "composant"):
                            verdict = "RACE"
                            note = ["debounce cleare avant re-set (L%s) mais pas au unmount -> le callback peut ecrire apres unmount"
                                    % ",".join(str(c[2]) for c in cleared)]
                        else:
                            verdict = "PROPRE"
                            note = ["debounce module page-lifetime (contexte %s)" % ckind]
                    elif boot:
                        verdict = "PROPRE"
                        note = ["boot-once / top-level, page-lifetime"]
                    elif delay is not None and delay <= 1500:
                        verdict = "PROPRE"
                        note = ["one-shot court (%dms), transitoire UI" % delay]
                    elif ckind in ("vue", "composant"):
                        if delay is None:
                            verdict = "PROPRE"
                            note = ["one-shot, delai non detecte (probablement court)"]
                        else:
                            verdict = "RACE"
                            note = ["one-shot %dms non stocke/cleare : le callback peut toucher DOM/etat apres unmount" % delay]
                    else:
                        verdict = "PROPRE"
                        note = ["one-shot contexte %s (page-lifetime)" % ckind]

                gravite = None
                if verdict == "RACE":
                    zone10 = callback_zone(jsf, i, 11)
                    if re.search(r"_state\.|_refresh|initParametres|initAccueil|_render", zone10):
                        gravite = "moyenne"
                        note.append("gravite moyenne : le callback touche l'etat module/rendu de la vue")
                    else:
                        gravite = "faible"
                        note.append("gravite faible : ecrit seulement du texte/classe sur un noeud (detache apres unmount, sans crash)")

                # Escalade : le seul vrai teardown vit dans un unmount jamais cable au router
                if verdict == "PROPRE" and cleared and unwired and (recursive or kind == "setInterval"):
                    in_unwired = [
                        c for c in cleared
                        if any(unmount_spans.get(u, -10 ** 9) <= c[2] <= unmount_spans.get(u, -10 ** 9) + 40 for u in unwired)
                    ]
                    resets = [c for c in cleared if c not in in_unwired]
                    resets_are_local = all(
                        (jsf.enclosing_chain(c[2] - 1) and top_fn in {x[0] for x in jsf.enclosing_chain(c[2] - 1)})
                        for c in resets
                    ) if resets else True
                    if in_unwired and resets_are_local:
                        verdict = "FUITE"
                        note.append(
                            "MAIS le seul teardown hors relance est dans %s, jamais appele : "
                            "app.js ne cable pas cet unmount au router" % "/".join(sorted(unwired))
                        )
                if dead:
                    note.append("CODE MORT : fichier non importe (jamais charge en runtime)")

                entries.append({
                    "fichier": "web/dashboard/" + rel, "ligne": lineno,
                    "type": kind, "cible": None, "evenement": None,
                    "contexte": ckind, "fonction": ctx_fn,
                    "handle": handle, "delai_ms": delay, "recursif": recursive,
                    "boot_once": bool(boot), "code_mort": dead, "gravite": gravite,
                    "cleanup": "; ".join(note), "verdict": verdict,
                    "code": ln.strip()[:160],
                })

    all_dead = sorted(
        "web/dashboard/" + rel for rel in files
        if not rel.startswith("tests/") and rel not in reachable
    )
    return entries, all_dead, unmounts_wired


def main():
    entries, dead_files, unmounts_wired = analyze()
    effectif = [e for e in entries if e["contexte"] != "tests" and not e["code_mort"]]
    stats_all = Counter(e["verdict"] for e in entries)
    stats_eff = Counter(e["verdict"] for e in effectif)
    stats_mort = Counter(e["verdict"] for e in entries if e["code_mort"])

    convention = {
        "source": "core/router.js L31-34, L143-159, L224-245 ; core/state.js L250-288 ; app.js L859-872",
        "resume": (
            "init() de vue retourne un cleanup stocke dans _currentCleanup, appele avant chaque "
            "navigation (router.js:148-152) ; fallback legacy route.unmount (router.js:239-242). "
            "stopAllPolling() (state.js:286) arrete les polls nommes a chaque nav (router.js:159). "
            "abortCurrentNav() coupe les fetchs. Intervals globaux d'app.js cleares au logout via "
            "onClearToken (app.js:859-872). Modules ESM top-level = singletons page-lifetime."
        ),
        "unmounts_cables_dans_app_js": sorted(unmounts_wired),
    }

    connus = {
        "R8-083_poll_processing": {
            "statut": "CONFIRME (toujours present)",
            "detail": "app.js:287 registre la route /processing avec init: initProcessing (async, ne "
                      "retourne pas de cleanup) et sans opts.unmount. unmountProcessing "
                      "(processing.js:878, clear du pollTimer L879) n'est importe nulle part : le poll "
                      "recursif get_status 2s (processing.js:487) survit a la navigation.",
        },
        "R8-084_saveTimer_parametres": {
            "statut": "CORRIGE pour saveTimer (clear au unmount parametres.js:3430 + debounce reset "
                      "L1797) ; reste le debounce de recherche L2111 (timer local jamais cleare au "
                      "unmount) et les timers de messages L1775/L2276.",
        },
    }

    out = {
        "matrice": "M8 — pollers/timers/cleanup",
        "genere_par": "docs/internal/verif_totale_2026_07/scripts_matrices/m8_timers.py",
        "commande": "python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m8_timers.py",
        "perimetre": "web/dashboard/**/*.js (tests/ et code mort inclus mais flagges)",
        "convention_lifecycle": convention,
        "fichiers_code_mort": dead_files,
        "findings_connus": connus,
        "stats_effectif_runtime": dict(stats_eff),
        "stats_tous": dict(stats_all),
        "stats_code_mort": dict(stats_mort),
        "total": len(entries),
        "entrees": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK -> %s" % OUT)
    print("STATS effectif runtime (hors tests + hors code mort):", dict(stats_eff))
    print("STATS tous:", dict(stats_all))
    print("Fichiers code mort:", len(dead_files))
    for e in entries:
        if e["verdict"] != "PROPRE" and e["contexte"] != "tests":
            flag = " [CODE MORT]" if e["code_mort"] else ""
            print("%-11s %s:%s [%s]%s %s" % (e["verdict"], e["fichier"], e["ligne"], e["fonction"], flag, e["cleanup"]))


if __name__ == "__main__":
    sys.exit(main())
