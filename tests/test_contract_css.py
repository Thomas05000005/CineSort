# -*- coding: utf-8 -*-
"""Contrat M5 — cablage CSS statique (verif totale 2026-07, Phase 5).

Deux invariants permanents, verifies par extraction statique pure
(aucun reseau, aucune app, aucune DB, <15s) :

1. INVARIANTES TIER : les hex de la charte tier
   Platinum #E5E4E2 / Gold #FFD700 / Silver #C0C0C0 / Bronze #CD7F32
   ne doivent apparaitre QUE dans web/shared/tokens.css (source unique).
   Les exceptions historiques CONNUES sont figees nominativement dans
   KNOWN_TIER_HEX ((fichier, hex) -> nombre d'occurrences). Toute
   NOUVELLE occurrence = echec. Toute entree KNOWN qui n'est plus violee
   = echec "perimee" (la retirer : la liste ne peut que RETRECIR,
   cf docs/internal/verif_totale_2026_07/PLAN_VERIF_TOTALE.md Phase 5).

2. CLASSES UTILISEES JAMAIS DEFINIES : les classes referencees dans les
   JS/HTML du dashboard (class=, classList.*, className=, cls:,
   querySelector/closest/matches/$$ — extraction statique identique a
   docs/internal/verif_totale_2026_07/scripts_matrices/m5_css.py, les
   constructions dynamiques prefixe-${var} sont ignorees) mais definies
   dans AUCUN CSS de web/dashboard/ + web/shared/. Baseline figee de
   212 entrees : tests/contract_baselines/css_used_undefined.json
   (generee depuis matrices/m5_css.json). NOUVELLE entree = echec ;
   entree disparue = echec "perimee" avec instruction de mise a jour.

L'extraction ci-dessous est un port fidele de m5_css.py (copie volontaire :
le test permanent ne doit pas dependre d'un script sous docs/internal/).
"""

from __future__ import annotations

import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
TOKENS_CSS = (WEB / "shared" / "tokens.css").resolve()
BASELINE_PATH = REPO / "tests" / "contract_baselines" / "css_used_undefined.json"

# ------------------------------------------------------------------ contrat 1
# Charte tier (memoire user INVIOLABLE #2) : hex en minuscules.
TIER_HEXES = ("#e5e4e2", "#ffd700", "#c0c0c0", "#cd7f32")

# Exceptions CONNUES au 2026-07-08 (source : matrices/m5_css.json,
# hex_hors_tokens filtre sur les 4 hex tier — 16 occurrences).
# Cle = (chemin repo-relatif posix, hex minuscule) ; valeur = occurrences.
# Cette liste ne peut que RETRECIR (corriger = remplacer le hex en dur par
# var(--tier-<x>-solid) de web/shared/tokens.css, puis retirer l'entree).
KNOWN_TIER_HEX: dict[tuple[str, str], int] = {
    # @layer legacy .tier-label.tier-bronze / .quality-fill.tier-bronze (L399/400/428)
    ("web/dashboard/depth-effects.css", "#cd7f32"): 3,
    # :root secondaire ~L2044-2047 : fallbacks var(--tier-X-solid, #hex)
    # (cf memoire project_cinesort_tier_duplication_historique)
    ("web/dashboard/styles.css", "#e5e4e2"): 1,
    ("web/dashboard/styles.css", "#ffd700"): 1,
    ("web/dashboard/styles.css", "#c0c0c0"): 1,
    ("web/dashboard/styles.css", "#cd7f32"): 1,
    # @layer v5 .film-detail-tier-* (L7924-7927) + .historique-films-history-tier--* (L10037/10038)
    ("web/shared/components.css", "#e5e4e2"): 1,
    ("web/shared/components.css", "#ffd700"): 1,
    ("web/shared/components.css", "#c0c0c0"): 2,
    ("web/shared/components.css", "#cd7f32"): 2,
    # themes : --focus-ring [data-theme="luxe"] L139 ; --text-muted/--text-3 [data-theme="aaa"] L252/259
    ("web/shared/themes.css", "#ffd700"): 1,
    ("web/shared/themes.css", "#c0c0c0"): 2,
}

# ----------------------------------------------------- extraction (port m5_css)
CLASS_TOKEN = re.compile(r"^-?[_a-zA-Z][\w-]*$")
CLASS_IN_SELECTOR = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
DECL_RE = re.compile(r"^\s*(--[\w-]+|[a-zA-Z-]+)\s*:(.*)$", re.S)
JS_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _rel(p: Path) -> str:
    return p.resolve().relative_to(REPO).as_posix()


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig", errors="replace")


def _css_files() -> list[Path]:
    return sorted((WEB / "dashboard").glob("*.css")) + sorted((WEB / "shared").glob("*.css"))


def _usage_files() -> list[Path]:
    return sorted(
        p for p in (WEB / "dashboard").rglob("*")
        if p.suffix in (".js", ".mjs", ".html") and p.is_file()
    )


def _strip_block_comments(text: str) -> str:
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


def _parse_css(path: Path, defined: dict, hex_findings: list) -> None:
    """Extrait classes des selecteurs + hex des valeurs de declarations."""
    raw = _strip_block_comments(_read(path))
    is_tokens = path.resolve() == TOKENS_CSS
    buf: list[str] = []
    buf_line = 1
    line = 1
    depth = 0
    prelude_stack: list[str] = []

    def flush_prelude():
        text = "".join(buf).strip()
        if text and not text.startswith("@"):
            clean = re.sub(r"(['\"]).*?\1", "", text)
            for m in CLASS_IN_SELECTOR.finditer(clean):
                defined[m.group(1)].append(f"{_rel(path)}:{buf_line}")
        return text or "@"

    def flush_decl():
        text = "".join(buf)
        m = DECL_RE.match(text)
        if m and not is_tokens:
            prop, value = m.group(1), m.group(2)
            for hm in HEX_RE.finditer(value):
                hex_findings.append({
                    "file": _rel(path),
                    "line": buf_line + text[:m.start(2) + hm.start()].count("\n"),
                    "hex": hm.group(0).lower(),
                    "property": prop.strip(),
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
                if prelude_stack:
                    prelude_stack.pop()
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


def _split_template(value: str):
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


def _expand_value(value: str, sink: dict) -> None:
    """Analyse une valeur d'attribut class / arg classList (cf m5_css.py)."""
    parts = _split_template(value)
    tokens, cur = [], []
    for kind, txt in parts:
        if kind == "e":
            cur.append(("e", txt))
            continue
        for pc in re.split(r"(\s+)", txt):
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
        prefix = tok[0][1] if tok[0][0] == "t" else ""
        exprs = [t for k, t in tok if k == "e"]
        trailing = len(tok) > (2 if prefix else 1)
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
                    for sub in (prefix + lit).split():
                        if CLASS_TOKEN.match(sub):
                            sink["static"].add(sub)
        elif prefix:
            sink["prefix"][prefix] += 1
        else:
            sink["unknown"] += 1


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


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _scan_usage(path: Path, used: dict) -> None:
    """Extrait les classes UTILISEES statiquement (dynamiques ignorees)."""
    text = _read(path)
    if path.suffix in (".js", ".mjs"):
        text = _strip_block_comments(text)
    fp = _rel(path)

    def sink_at(pos: int, ctx: str):
        ln = _lineno(text, pos)
        s = {"static": set(), "prefix": defaultdict(int), "unknown": 0}

        def commit():
            for c in s["static"]:
                used[c].append(f"{fp}:{ln} ({ctx})")

        return s, commit

    for rx in CLASS_ATTR_RES:
        for m in rx.finditer(text):
            s, commit = sink_at(m.start(), "class-attr")
            _expand_value(m.group(1), s)
            commit()

    if path.suffix == ".html":
        return

    for m in CLASSLIST_RE.finditer(text):
        method, args = m.group(1), m.group(2)
        s, commit = sink_at(m.start(), f"classList.{method}")
        for a in STRLIT_RE.finditer(args):
            _expand_value(a.group(2), s)
        commit()

    for m in CLASSNAME_RE.finditer(text):
        s, commit = sink_at(m.start(), "className=")
        _expand_value(m.group(2), s)
        commit()

    for m in CLSPROP_RE.finditer(text):
        s, commit = sink_at(m.start(), "cls-prop")
        _expand_value(m.group(2), s)
        commit()

    for m in SELECTOR_CALL_RE.finditer(text):
        s, commit = sink_at(m.start(), "selector")
        for cm in SEL_CLASS_RE.finditer(m.group(2)):
            name = cm.group(1)
            if name.endswith("${"):
                s["prefix"][name[:-2]] += 1
            elif CLASS_TOKEN.match(name):
                s["static"].add(name)
        commit()


# --------------------------------------------------------------- etat partage
class _State:
    """Extraction unique partagee entre les tests (setUpClass)."""

    defined: dict[str, list[str]]
    used: dict[str, list[str]]
    tier_hex_hits: list[dict]


def _extract() -> _State:
    st = _State()
    st.defined = defaultdict(list)
    st.used = defaultdict(list)
    hex_findings: list[dict] = []

    css_files = _css_files()
    usage_files = _usage_files()
    # Garde-fou : si l'arbo web/ bouge, echouer explicitement plutot que
    # de passer VERT sur un scan vide.
    if not css_files or not usage_files:
        raise AssertionError(
            "Scan CSS vide : web/dashboard ou web/shared introuvable/vide. "
            "Mettre a jour tests/test_contract_css.py si l'arborescence web/ a change."
        )

    for f in css_files:
        _parse_css(f, st.defined, hex_findings)
    for f in usage_files:
        _scan_usage(f, st.used)

    # hex tier dans les JS du dashboard (comme le bonus m5_css.py)
    for f in usage_files:
        if f.suffix == ".html":
            # bonus contrat : hex tier dans le HTML (styles inline), commentaires exclus
            text = HTML_COMMENT_RE.sub(" ", _read(f))
        else:
            text = _strip_block_comments(_read(f))
        for m in JS_HEX_RE.finditer(text):
            hx = m.group(0).lower()
            if hx in TIER_HEXES:
                hex_findings.append({
                    "file": _rel(f), "line": _lineno(text, m.start()),
                    "hex": hx, "property": "(js/html)", "selector": "",
                })

    st.tier_hex_hits = [h for h in hex_findings if h["hex"] in TIER_HEXES]
    return st


class CssContractTests(unittest.TestCase):
    """Contrat M5 : invariantes tier hex + classes utilisees non definies."""

    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = _extract()

    # ------------------------------------------------------------ contrat 1
    def test_tier_hex_only_in_tokens_css(self) -> None:
        observed = Counter(
            (h["file"], h["hex"]) for h in self.state.tier_hex_hits
        )
        # tokens.css est exclu par construction (_parse_css is_tokens +
        # usage_files ne couvre pas web/shared) ; ceinture-bretelles :
        for (fp, _hx) in observed:
            self.assertNotEqual(
                fp, "web/shared/tokens.css",
                "tokens.css ne doit jamais figurer dans les violations (bug du scan)",
            )

        problems: list[str] = []

        # NOUVELLES violations (fichier/hex inconnu OU count en hausse)
        for key, count in sorted(observed.items()):
            known = KNOWN_TIER_HEX.get(key, 0)
            if count > known:
                fp, hx = key
                locs = [
                    f"  {h['file']}:{h['line']} [{h['property']}] {h['selector']}"
                    for h in self.state.tier_hex_hits
                    if (h["file"], h["hex"]) == key
                ]
                problems.append(
                    f"NOUVELLE violation tier hex : {hx} present {count}x dans {fp} "
                    f"(KNOWN_TIER_HEX en autorise {known}).\n"
                    + "\n".join(locs)
                    + "\n  -> Correction : remplacer le hex en dur par "
                    f"var(--tier-<x>-solid) defini dans web/shared/tokens.css "
                    "(charte tier INVARIANTE, memoire user #2). "
                    "Ne PAS ajouter d'entree a KNOWN_TIER_HEX."
                )

        # Entrees KNOWN perimees (plus violees, ou count en baisse)
        for key, known in sorted(KNOWN_TIER_HEX.items()):
            count = observed.get(key, 0)
            if count < known:
                fp, hx = key
                problems.append(
                    f"Entree KNOWN_TIER_HEX PERIMEE : ({fp}, {hx}) attend {known} "
                    f"occurrence(s), n'en trouve plus que {count}.\n"
                    "  -> Bravo, une dette a ete corrigee : mettre a jour "
                    "KNOWN_TIER_HEX dans tests/test_contract_css.py "
                    f"({'retirer l entree' if count == 0 else f'abaisser a {count}'}). "
                    "La liste ne peut que RETRECIR (Phase 5 PLAN_VERIF_TOTALE.md)."
                )

        if problems:
            self.fail(
                "Contrat INVARIANTES TIER viole "
                f"({len(problems)} probleme(s)) :\n\n" + "\n\n".join(problems)
            )

    # ------------------------------------------------------------ contrat 2
    def test_used_classes_are_defined_or_baselined(self) -> None:
        self.assertTrue(
            BASELINE_PATH.is_file(),
            f"Baseline manquante : {BASELINE_PATH}. "
            "La regenerer depuis docs/internal/verif_totale_2026_07/matrices/m5_css.json "
            "(classes verdict UTILISEE_NON_DEFINIE).",
        )
        baseline_doc = json.loads(BASELINE_PATH.read_text(encoding="utf-8-sig"))
        baseline = set(baseline_doc["classes"])

        current = set(self.state.used) - set(self.state.defined)

        problems: list[str] = []

        new = sorted(current - baseline)
        if new:
            details = []
            for cls in new[:20]:
                locs = self.state.used[cls][:4]
                details.append(f"  .{cls}\n    " + "\n    ".join(locs))
            details_txt = "\n".join(details)
            more = f"\n  ... et {len(new) - 20} autres" if len(new) > 20 else ""
            problems.append(
                f"{len(new)} NOUVELLE(S) classe(s) UTILISEE(s) (JS/HTML dashboard) "
                "mais DEFINIE(s) dans aucun CSS (web/dashboard + web/shared) :\n"
                f"{details_txt}{more}\n"
                "  -> Correction : definir la classe dans le CSS approprie, OU "
                "corriger/retirer l'usage (typo, classe renommee, code mort). "
                "N'ajoute PAS d'entree a la baseline "
                "tests/contract_baselines/css_used_undefined.json : "
                "elle ne peut que RETRECIR (Phase 5 PLAN_VERIF_TOTALE.md)."
            )

        stale = sorted(baseline - current)
        if stale:
            listing = "\n".join(f"  .{c}" for c in stale[:20])
            more = f"\n  ... et {len(stale) - 20} autres" if len(stale) > 20 else ""
            problems.append(
                f"{len(stale)} entree(s) PERIMEE(s) dans la baseline "
                "(classe desormais definie dans un CSS, ou usage disparu) :\n"
                f"{listing}{more}\n"
                "  -> Bravo, une dette a ete corrigee : retirer ces entrees de "
                "tests/contract_baselines/css_used_undefined.json "
                "(champ 'classes', garder le tri alphabetique)."
            )

        if problems:
            self.fail(
                "Contrat CLASSES UTILISEES/DEFINIES viole "
                f"({len(problems)} famille(s)) :\n\n" + "\n\n".join(problems)
            )


if __name__ == "__main__":
    unittest.main()
