# -*- coding: utf-8 -*-
"""M6 — Matrice de cablage i18n (verif totale 2026-07).

REJOUABLE : python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m6_i18n.py

Sortie : docs/internal/verif_totale_2026_07/matrices/m6_i18n.json

Ce que fait le script (lecture seule, aucun fichier source modifie) :
  1. Aplatit locales/fr.json et locales/en.json (utf-8-sig, cles dotted).
  2. Scanne web/ (JS + HTML, hors tests/) pour les references i18n reelles :
       - t('cle') / t("cle")            (pattern principal, import { t } de core/i18n.js)
       - t(`cle`) sans ${}              (statique)
       - t(`prefix.${x}...`)            (dynamique -> prefixe)
       - t(identifiant)                 (dynamique inconnu ; indirection labelKey resolue)
       - labelKey: "cle"                (indirection consommee par t(item.labelKey))
     Les commentaires JS sont retires (state machine) pour ne pas compter les
     exemples de docstring de core/i18n.js comme des references.
  3. Croise references <-> locales : OK / MANQUANTE_FR / MANQUANTE_EN.
  4. Divergences fr/en (cle presente d'un seul cote).
  5. Cles definies jamais referencees : ORPHELINE, ou INCERTAIN si la cle
     matche un prefixe dynamique OU n'apparait que dans le backend python.
  6. Echantillon (max 20) de textes UI en dur dans les JS des vues/composants
     qui devraient passer par t() : TEXTE_EN_DUR.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # -> racine du repo CineSort
WEB = ROOT / "web"
LOCALES = ROOT / "locales"
BACKEND = ROOT / "cinesort"
OUT = ROOT / "docs" / "internal" / "verif_totale_2026_07" / "matrices" / "m6_i18n.json"

KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def load_flat(path: Path) -> dict[str, str]:
    """Charge un JSON de locale (utf-8-sig) et l'aplatit en cles dotted."""
    with io.open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    flat: dict[str, str] = {}

    def walk(node, prefix=""):
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, key)
            else:
                flat[key] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

    walk(data)
    return flat


def strip_js_comments(src: str) -> str:
    """Retire // et /* */ en respectant strings et template literals.

    Les commentaires sont remplaces par des espaces (les \n sont conserves
    pour garder des numeros de ligne exacts).
    """
    out = []
    i, n = 0, len(src)
    state = "code"  # code | line | block | sq | dq | tpl
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line"
                out.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                out.append("  ")
                i += 2
                continue
            if c == "'":
                state = "sq"
            elif c == '"':
                state = "dq"
            elif c == "`":
                state = "tpl"
            out.append(c)
            i += 1
        elif state == "line":
            if c == "\n":
                state = "code"
                out.append(c)
            else:
                out.append(" ")
            i += 1
        elif state == "block":
            if c == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append(c if c == "\n" else " ")
            i += 1
        elif state in ("sq", "dq"):
            quote = "'" if state == "sq" else '"'
            if c == "\\":
                out.append(c)
                out.append(nxt)
                i += 2
                continue
            if c == quote or c == "\n":
                state = "code"
            out.append(c)
            i += 1
        else:  # tpl — approximation suffisante (pas de nesting de backticks)
            if c == "\\":
                out.append(c)
                out.append(nxt)
                i += 2
                continue
            if c == "`":
                state = "code"
            out.append(c)
            i += 1
    return "".join(out)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def iter_web_files():
    """JS + HTML de web/, hors dossiers de tests."""
    for ext in ("*.js", "*.html"):
        for p in sorted(WEB.rglob(ext)):
            rel = p.relative_to(ROOT).as_posix()
            if "/tests/" in f"/{rel}/" or "/node_modules/" in f"/{rel}/":
                continue
            yield p, rel


# --------------------------------------------------------------------------- #
# 1. Locales                                                                   #
# --------------------------------------------------------------------------- #

fr = load_flat(LOCALES / "fr.json")
en = load_flat(LOCALES / "en.json")
fr_keys, en_keys = set(fr), set(en)
all_defined = fr_keys | en_keys

# --------------------------------------------------------------------------- #
# 2. References dans web/                                                      #
# --------------------------------------------------------------------------- #

# t('cle') / t("cle") — lookbehind pour exclure .t( split( etc. ; groupe 3 =
# 1er char apres la string ("+" => concat dynamique, pas une cle complete).
STATIC_RE = re.compile(r"""(?<![\w$.])t\(\s*(['"])((?:\\.|(?!\1).)+?)\1\s*(.)?""", re.S)
TPL_RE = re.compile(r"(?<![\w$.])t\(\s*`([^`]*)`", re.S)
IDENT_RE = re.compile(r"(?<![\w$.])t\(\s*(?!['\"`])([A-Za-z_$][\w$.\[\]]*)")
LABELKEY_RE = re.compile(r"""\blabelKey\s*:\s*(['"])([A-Za-z0-9_.\-]+)\1""")
# Prefixes de concat probables : string finissant par un point ("a.b." + x)
CONCAT_PREFIX_RE = re.compile(r"""(['"])([a-z0-9_]+(?:\.[a-z0-9_]+)+\.)\1\s*\+""")

static_refs: dict[str, list[str]] = {}  # cle -> ["fichier:ligne", ...]
dynamic_prefixes: dict[str, list[str]] = {}  # prefixe -> emplacements
ident_calls: list[str] = []  # t(variable) — emplacements

web_corpus: dict[str, str] = {}  # rel -> contenu sans commentaires

for path, rel in iter_web_files():
    raw = io.open(path, encoding="utf-8-sig", errors="replace").read()
    src = strip_js_comments(raw) if rel.endswith(".js") else raw
    web_corpus[rel] = src
    if rel == "web/dashboard/core/i18n.js":
        continue  # module infra : ses propres t()/fallbacks ne sont pas des refs de vue

    for m in STATIC_RE.finditer(src):
        key, after = m.group(2), m.group(3) or ""
        loc = f"{rel}:{line_of(src, m.start())}"
        if after == "+":
            dynamic_prefixes.setdefault(key, []).append(loc)
        elif KEY_RE.match(key):
            static_refs.setdefault(key, []).append(loc)

    for m in TPL_RE.finditer(src):
        body = m.group(1)
        loc = f"{rel}:{line_of(src, m.start())}"
        if "${" in body:
            prefix = body.split("${", 1)[0]
            if prefix:
                dynamic_prefixes.setdefault(prefix, []).append(loc)
            else:
                ident_calls.append(loc)
        elif KEY_RE.match(body):
            static_refs.setdefault(body, []).append(loc)

    for m in IDENT_RE.finditer(src):
        ident_calls.append(f"{rel}:{line_of(src, m.start())} (t({m.group(1)}))")

    for m in LABELKEY_RE.finditer(src):
        static_refs.setdefault(m.group(2), []).append(f"{rel}:{line_of(src, m.start())} (labelKey)")

    for m in CONCAT_PREFIX_RE.finditer(src):
        dynamic_prefixes.setdefault(m.group(2), []).append(f"{rel}:{line_of(src, m.start())} (concat)")

# --------------------------------------------------------------------------- #
# 3-4. Croisement references <-> locales + divergences fr/en                  #
# --------------------------------------------------------------------------- #

findings: list[dict] = []

missing_fr = missing_en = ok_count = 0
for key in sorted(static_refs):
    locs = static_refs[key][:3]
    in_fr, in_en = key in fr_keys, key in en_keys
    if in_fr and in_en:
        ok_count += 1
        continue
    if not in_fr:
        missing_fr += 1
        findings.append(
            {
                "verdict": "MANQUANTE_FR",
                "categorie": "ref_sans_locale",
                "element": key,
                "preuve": locs,
                "detail": "cle referencee dans web/ mais absente de locales/fr.json"
                + ("" if in_en else " (absente aussi de en.json)"),
            }
        )
    if not in_en:
        missing_en += 1
        findings.append(
            {
                "verdict": "MANQUANTE_EN",
                "categorie": "ref_sans_locale",
                "element": key,
                "preuve": locs,
                "detail": "cle referencee dans web/ mais absente de locales/en.json"
                + ("" if in_fr else " (absente aussi de fr.json)"),
            }
        )

div_fr_only = sorted(fr_keys - en_keys)
div_en_only = sorted(en_keys - fr_keys)
for key in div_fr_only:
    findings.append(
        {
            "verdict": "MANQUANTE_EN",
            "categorie": "divergence_locales",
            "element": key,
            "preuve": ["locales/fr.json (presente) / locales/en.json (absente)"],
            "detail": f"fr='{fr[key][:80]}'",
        }
    )
for key in div_en_only:
    findings.append(
        {
            "verdict": "MANQUANTE_FR",
            "categorie": "divergence_locales",
            "element": key,
            "preuve": ["locales/en.json (presente) / locales/fr.json (absente)"],
            "detail": f"en='{en[key][:80]}'",
        }
    )

# --------------------------------------------------------------------------- #
# 5. Cles definies jamais referencees (ORPHELINE / INCERTAIN)                 #
# --------------------------------------------------------------------------- #

# Corpus backend (python) : une cle qui n'apparait QUE la est INCERTAIN.
backend_corpus = ""
for p in sorted(BACKEND.rglob("*.py")):
    rel = p.relative_to(ROOT).as_posix()
    if "/tests/" in f"/{rel}/":
        continue
    backend_corpus += io.open(p, encoding="utf-8", errors="replace").read()

web_all = "\n".join(web_corpus.values())
prefixes = sorted(dynamic_prefixes)

orphan = incert_dyn = incert_backend = 0
orphan_rows: list[dict] = []
for key in sorted(all_defined):
    if key in static_refs:
        continue
    quoted = (f'"{key}"' in web_all) or (f"'{key}'" in web_all) or (f"`{key}`" in web_all)
    if quoted:
        continue  # referencee comme literal ailleurs (data-*, mapping, etc.)
    dyn = [p for p in prefixes if key.startswith(p)]
    if dyn:
        incert_dyn += 1
        orphan_rows.append(
            {
                "verdict": "INCERTAIN",
                "categorie": "cle_dynamique_possible",
                "element": key,
                "preuve": dynamic_prefixes[dyn[0]][:2],
                "detail": f"matche le prefixe dynamique '{dyn[0]}'",
            }
        )
        continue
    in_backend = (f'"{key}"' in backend_corpus) or (f"'{key}'" in backend_corpus)
    if in_backend:
        incert_backend += 1
        orphan_rows.append(
            {
                "verdict": "INCERTAIN",
                "categorie": "referencee_backend_seulement",
                "element": key,
                "preuve": ["cinesort/ (grep literal)"],
                "detail": "cle absente de web/ mais literal present dans le backend python",
            }
        )
        continue
    orphan += 1
    orphan_rows.append(
        {
            "verdict": "ORPHELINE",
            "categorie": "definie_jamais_referencee",
            "element": key,
            "preuve": ["locales/fr.json" if key in fr_keys else "locales/en.json"],
            "detail": f"valeur fr='{fr.get(key, en.get(key, ''))[:60]}'",
        }
    )
findings.extend(orphan_rows)

# --------------------------------------------------------------------------- #
# 6. Textes UI en dur dans les vues/composants (echantillon, max 20)          #
# --------------------------------------------------------------------------- #

TEXT_NODE_RE = re.compile(r">([^<>{}`\n]{2,90})<")
ATTR_RE = re.compile(r"""(?:placeholder|title|aria-label|alt|data-tooltip)\s*=\s*"([^"<>{}]{3,90})\"""")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}")


def has_accent(s: str) -> bool:
    return any(unicodedata.combining(c) or ord(c) > 127 for c in unicodedata.normalize("NFD", s))


def looks_like_ui_text(s: str) -> bool:
    s = s.strip()
    if not s or "${" in s or "&#" in s or s.startswith("&"):
        return False
    if not WORD_RE.search(s):
        return False
    # exige une phrase probable : espace entre mots OU caractere accentue
    if " " not in s and not has_accent(s):
        return False
    low = s.lower()
    junk = ("http", "svg", "px", "rgba", "var(--", "cinesort v", "…")
    if any(j in low for j in junk):
        return False
    # fragments de code JS captures entre > et < (comparaisons, ternaires...)
    if "&&" in s or "||" in s or s.startswith(("=", "?", ":", ".")):
        return False
    if re.fullmatch(r"[\d\s%.,:/+\-]+", s):
        return False
    return True


hard_rows: list[dict] = []
seen_texts: set[str] = set()
scan_dirs = ("web/dashboard/views/", "web/dashboard/components/")
locale_values = {v.strip() for v in list(fr.values()) + list(en.values())}
MAX_PER_FILE = 3  # diversifier l'echantillon (max 20 au total)

for rel in sorted(web_corpus):
    if not rel.startswith(scan_dirs) or not rel.endswith(".js"):
        continue
    src = web_corpus[rel]
    per_file = 0
    for regex, kind in ((TEXT_NODE_RE, "text_node"), (ATTR_RE, "attribut")):
        for m in regex.finditer(src):
            txt = m.group(1).strip()
            if not looks_like_ui_text(txt) or txt in seen_texts:
                continue
            seen_texts.add(txt)
            hard_rows.append(
                {
                    "verdict": "TEXTE_EN_DUR",
                    "categorie": f"texte_dur_{kind}",
                    "element": txt[:80],
                    "preuve": [f"{rel}:{line_of(src, m.start())}"],
                    "detail": "existe dans les locales (valeur identique)"
                    if txt in locale_values
                    else "texte visible non passe par t()",
                }
            )
            per_file += 1
            if len(hard_rows) >= 20 or per_file >= MAX_PER_FILE:
                break
        if len(hard_rows) >= 20 or per_file >= MAX_PER_FILE:
            break
    if len(hard_rows) >= 20:
        break
findings.extend(hard_rows)

# --------------------------------------------------------------------------- #
# Sortie                                                                       #
# --------------------------------------------------------------------------- #

stats = {
    "OK": ok_count,
    "MANQUANTE_FR": missing_fr + len(div_en_only),
    "MANQUANTE_EN": missing_en + len(div_fr_only),
    "ORPHELINE": orphan,
    "INCERTAIN": incert_dyn + incert_backend,
    "TEXTE_EN_DUR": len(hard_rows),
}
result = {
    "matrice": "M6_i18n",
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "script": "docs/internal/verif_totale_2026_07/scripts_matrices/m6_i18n.py",
    "pattern_reel": "import { t } from core/i18n.js ; t('cle'), t(`...${x}`), "
    "t(item.labelKey) + labelKey:'cle' ; fetch /locales/<locale>.json ; "
    "fallback _FALLBACK_FR hardcode dans i18n.js ; pas de data-i18n",
    "stats": stats,
    "resume": {
        "cles_fr": len(fr_keys),
        "cles_en": len(en_keys),
        "cles_referencees_statiques": len(static_refs),
        "prefixes_dynamiques": {p: dynamic_prefixes[p][:2] for p in prefixes},
        "appels_t_identifiant": ident_calls,
        "fichiers_web_scannes": len(web_corpus),
    },
    "findings": findings,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)

print(f"[m6_i18n] {OUT}")
print(f"[m6_i18n] stats: {json.dumps(stats, ensure_ascii=False)}")
