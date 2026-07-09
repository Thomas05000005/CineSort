# -*- coding: utf-8 -*-
"""Contrat M6 — cablage i18n (verif totale 2026-07, Phase 5).

Contrats verifies (statiques, sans reseau/app/DB, < 15 s) :
  1. Toute cle i18n referencee statiquement dans web/ (pattern reel :
     t('cle') / t("cle") / t(`cle`) sans ${} / labelKey:'cle') existe dans
     locales/fr.json ET locales/en.json (aplatis en cles dotted, utf-8-sig).
  2. Parite stricte des jeux de cles fr.json / en.json (0 divergence).
  3. Le fallback hardcode _FALLBACK_FR de web/dashboard/core/i18n.js est un
     sous-ensemble des cles de fr.json (sinon le fallback ment sur le contenu
     reel de la locale).

Ce que ce test N'IMPOSE PAS : les 519 cles orphelines (definies mais jamais
referencees) — decision produit en attente, cf matrice
docs/internal/verif_totale_2026_07/matrices/m6_i18n.json.

Source de verite du pattern : docs/internal/verif_totale_2026_07/
scripts_matrices/m6_i18n.py (meme extraction : commentaires JS retires par
state machine, concat "prefix." + x et template `...${x}` ignores car
dynamiques, core/i18n.js exclu du scan de references).

Regle des KNOWN_* (Phase 5 PLAN_VERIF_TOTALE.md) : les listes ne peuvent que
RETRECIR. Le test echoue si une NOUVELLE violation apparait ET si une entree
KNOWN n'est plus violee (entree perimee a retirer).
"""

from __future__ import annotations

import io
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
LOCALES_DIR = REPO_ROOT / "locales"
I18N_JS = REPO_ROOT / "web" / "dashboard" / "core" / "i18n.js"
I18N_JS_REL = "web/dashboard/core/i18n.js"

# --------------------------------------------------------------------------- #
# Violations CONNUES (figees le 2026-07-08, source m6_i18n.json).              #
# Ces listes ne peuvent que RETRECIR : ajouter une entree = regression a       #
# corriger dans les locales/le code, PAS a legitimer ici.                      #
# --------------------------------------------------------------------------- #

# Contrat 1 — cles referencees dans web/ absentes de fr.json ou en.json.
# Etat 2026-07-08 : 157 cles referencees, 0 manquante.
KNOWN_MISSING_LOCALE_KEYS: frozenset[str] = frozenset()

# Contrat 2 — divergences de jeux de cles fr/en (cle presente d'un seul cote).
# Etat 2026-07-08 : 747 cles de chaque cote, 0 divergence.
KNOWN_LOCALE_DIVERGENCES: frozenset[str] = frozenset()

# Contrat 3 — cles de _FALLBACK_FR (core/i18n.js) absentes de fr.json.
# Etat 2026-07-08 : 22 cles de fallback, toutes presentes dans fr.json
# (y compris sidebar.nav.qij, verifiee explicitement).
KNOWN_FALLBACK_ORPHANS: frozenset[str] = frozenset()

# --------------------------------------------------------------------------- #
# Extraction — memes regex que scripts_matrices/m6_i18n.py                     #
# --------------------------------------------------------------------------- #

KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
# t('cle') / t("cle") — lookbehind exclut .t( split( etc. ; groupe 3 = 1er
# char apres la string ("+" => concat dynamique, pas une cle complete).
STATIC_RE = re.compile(
    r"""(?<![\w$.])t\(\s*(['"])((?:\\.|(?!\1).)+?)\1\s*(.)?""", re.S)
TPL_RE = re.compile(r"(?<![\w$.])t\(\s*`([^`]*)`", re.S)
LABELKEY_RE = re.compile(r"""\blabelKey\s*:\s*(['"])([A-Za-z0-9_.\-]+)\1""")
FALLBACK_KEY_RE = re.compile(r'^\s*"([^"]+)"\s*:', re.M)


def _load_flat(path: Path) -> dict[str, str]:
    """Charge un JSON de locale (utf-8-sig) et l'aplatit en cles dotted."""
    with io.open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    flat: dict[str, str] = {}

    def walk(node: dict, prefix: str = "") -> None:
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, key)
            else:
                flat[key] = v if isinstance(v, str) else json.dumps(
                    v, ensure_ascii=False)

    walk(data)
    return flat


def _strip_js_comments(src: str) -> str:
    """Retire // et /* */ en respectant strings et template literals.

    Copie de m6_i18n.py : sans ce strip, les exemples de docstring
    (ex. t("missing.key")) compteraient comme des references de vue.
    Les \\n sont conserves pour garder des numeros de ligne exacts.
    """
    out: list[str] = []
    i, n = 0, len(src)
    state = "code"          # code | line | block | sq | dq | tpl
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line"; out.append("  "); i += 2; continue
            if c == "/" and nxt == "*":
                state = "block"; out.append("  "); i += 2; continue
            if c == "'":
                state = "sq"
            elif c == '"':
                state = "dq"
            elif c == "`":
                state = "tpl"
            out.append(c); i += 1
        elif state == "line":
            if c == "\n":
                state = "code"; out.append(c)
            else:
                out.append(" ")
            i += 1
        elif state == "block":
            if c == "*" and nxt == "/":
                state = "code"; out.append("  "); i += 2; continue
            out.append(c if c == "\n" else " "); i += 1
        elif state in ("sq", "dq"):
            quote = "'" if state == "sq" else '"'
            if c == "\\":
                out.append(c); out.append(nxt); i += 2; continue
            if c == quote or c == "\n":
                state = "code"
            out.append(c); i += 1
        else:  # tpl — approximation suffisante (pas de nesting de backticks)
            if c == "\\":
                out.append(c); out.append(nxt); i += 2; continue
            if c == "`":
                state = "code"
            out.append(c); i += 1
    return "".join(out)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _iter_web_files():
    """JS + HTML de web/, hors dossiers de tests et node_modules."""
    for ext in ("*.js", "*.html"):
        for p in sorted(WEB_DIR.rglob(ext)):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in f"/{rel}/" or "/node_modules/" in f"/{rel}/":
                continue
            yield p, rel


def _collect_static_refs() -> dict[str, list[str]]:
    """Cle statique referencee -> emplacements 'fichier:ligne'.

    Ignore les appels dynamiques (concat "a.b." + x, template `...${x}`,
    t(variable)) : ils ne designent pas une cle complete verifiable.
    """
    refs: dict[str, list[str]] = {}
    for path, rel in _iter_web_files():
        raw = io.open(path, encoding="utf-8-sig", errors="replace").read()
        src = _strip_js_comments(raw) if rel.endswith(".js") else raw
        if rel == I18N_JS_REL:
            continue  # module infra : ses t()/fallbacks ne sont pas des refs de vue

        for m in STATIC_RE.finditer(src):
            key, after = m.group(2), m.group(3) or ""
            if after == "+":
                continue  # concat dynamique
            if KEY_RE.match(key):
                refs.setdefault(key, []).append(f"{rel}:{_line_of(src, m.start())}")

        for m in TPL_RE.finditer(src):
            body = m.group(1)
            if "${" in body:
                continue  # template dynamique
            if KEY_RE.match(body):
                refs.setdefault(body, []).append(f"{rel}:{_line_of(src, m.start())}")

        for m in LABELKEY_RE.finditer(src):
            refs.setdefault(m.group(2), []).append(
                f"{rel}:{_line_of(src, m.start())} (labelKey)")
    return refs


def _collect_fallback_keys() -> list[str]:
    """Cles du dict _FALLBACK_FR de core/i18n.js (bloc Object.freeze)."""
    src = io.open(I18N_JS, encoding="utf-8-sig").read()
    start = src.index("_FALLBACK_FR = Object.freeze({")
    end = src.index("});", start)
    return FALLBACK_KEY_RE.findall(src[start:end])


class I18nContractTests(unittest.TestCase):
    """Contrat M6 : references web <-> locales fr/en <-> fallback i18n.js."""

    fr: dict[str, str]
    en: dict[str, str]
    static_refs: dict[str, list[str]]
    fallback_keys: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fr = _load_flat(LOCALES_DIR / "fr.json")
        cls.en = _load_flat(LOCALES_DIR / "en.json")
        cls.static_refs = _collect_static_refs()
        cls.fallback_keys = _collect_fallback_keys()

    # ------------------------------------------------------------------ #
    # Sanity : le scanner voit bien le corpus (protege contre un scan     #
    # silencieusement vide qui rendrait les 3 contrats verts par vacuite) #
    # ------------------------------------------------------------------ #

    def test_scanner_finds_corpus(self) -> None:
        self.assertGreaterEqual(
            len(self.static_refs), 20,
            msg=(
                f"Seulement {len(self.static_refs)} cles i18n statiques trouvees "
                f"dans web/ (attendu >= 20). Le scanner est probablement casse "
                f"(web/ deplace ? pattern t() change ?) : realigner ce test sur "
                f"scripts_matrices/m6_i18n.py."
            ),
        )
        # Note : le corpus de refs est passe de 157 (2026-07-08) a ~34 apres la
        # purge des 6 vues mortes (Phase 5) qui portaient l'essentiel des t().
        # Seuil abaisse a 20 (anti-vacuite) ; les 9 vues vivantes restent
        # majoritairement FR-only (i18n a cabler = decision produit, hors purge).
        self.assertGreaterEqual(
            len(self.fr), 500,
            msg=f"locales/fr.json aplati = {len(self.fr)} cles (attendu >= 500) : "
                f"fichier tronque ou aplatissement casse.",
        )
        self.assertGreaterEqual(
            len(self.fallback_keys), 10,
            msg=(
                f"_FALLBACK_FR de {I18N_JS_REL} = {len(self.fallback_keys)} cles "
                f"(attendu >= 10, etat 2026-07-08 = 22) : extraction cassee ou "
                f"fallback vide — realigner FALLBACK_KEY_RE sur le fichier."
            ),
        )

    # ------------------------------------------------------------------ #
    # Contrat 1 : toute cle referencee existe dans fr.json ET en.json     #
    # ------------------------------------------------------------------ #

    def test_referenced_keys_exist_in_both_locales(self) -> None:
        missing: dict[str, tuple[str, list[str]]] = {}
        for key in sorted(self.static_refs):
            in_fr, in_en = key in self.fr, key in self.en
            if in_fr and in_en:
                continue
            side = ("fr.json ET en.json" if not in_fr and not in_en
                    else ("fr.json" if not in_fr else "en.json"))
            missing[key] = (side, self.static_refs[key][:3])

        new = {k: v for k, v in missing.items()
               if k not in KNOWN_MISSING_LOCALE_KEYS}
        self.assertFalse(
            new,
            msg=(
                "NOUVELLES cles i18n referencees dans web/ mais absentes des "
                "locales :\n"
                + "\n".join(
                    f"  - '{k}' absente de {side} — referencee a : {', '.join(locs)}"
                    for k, (side, locs) in sorted(new.items())
                )
                + "\nCorriger : ajouter la cle (fr ET en) dans locales/*.json, "
                  "ou corriger la faute de frappe dans l'appel t()/labelKey. "
                  "NE PAS l'ajouter a KNOWN_MISSING_LOCALE_KEYS (liste gelee, "
                  "elle ne peut que retrecir)."
            ),
        )

        stale = sorted(KNOWN_MISSING_LOCALE_KEYS - set(missing))
        self.assertFalse(
            stale,
            msg=(
                f"Entrees KNOWN_MISSING_LOCALE_KEYS perimees (plus violees) : "
                f"{stale}.\nCorriger : les retirer de la constante dans "
                f"tests/test_contract_i18n.py — la liste ne peut que retrecir "
                f"(Phase 5 PLAN_VERIF_TOTALE.md)."
            ),
        )

    # ------------------------------------------------------------------ #
    # Contrat 2 : parite stricte des jeux de cles fr/en                   #
    # ------------------------------------------------------------------ #

    def test_locales_fr_en_key_parity(self) -> None:
        fr_only = set(self.fr) - set(self.en)
        en_only = set(self.en) - set(self.fr)
        diverging = fr_only | en_only

        new = sorted(diverging - KNOWN_LOCALE_DIVERGENCES)
        self.assertFalse(
            new,
            msg=(
                "NOUVELLES divergences de cles entre locales/fr.json et "
                "locales/en.json :\n"
                + "\n".join(
                    f"  - '{k}' presente uniquement dans "
                    f"{'fr.json' if k in fr_only else 'en.json'}"
                    for k in new
                )
                + "\nCorriger : ajouter la traduction manquante dans l'autre "
                  "locale (meme arborescence de cles), ou retirer la cle des "
                  "deux si elle est morte. NE PAS l'ajouter a "
                  "KNOWN_LOCALE_DIVERGENCES (liste gelee)."
            ),
        )

        stale = sorted(KNOWN_LOCALE_DIVERGENCES - diverging)
        self.assertFalse(
            stale,
            msg=(
                f"Entrees KNOWN_LOCALE_DIVERGENCES perimees (plus violees) : "
                f"{stale}.\nCorriger : les retirer de la constante dans "
                f"tests/test_contract_i18n.py."
            ),
        )

    # ------------------------------------------------------------------ #
    # Contrat 3 : _FALLBACK_FR (core/i18n.js) sous-ensemble de fr.json    #
    # ------------------------------------------------------------------ #

    def test_fallback_fr_is_subset_of_fr_locale(self) -> None:
        orphans = {k for k in self.fallback_keys if k not in self.fr}

        new = sorted(orphans - KNOWN_FALLBACK_ORPHANS)
        self.assertFalse(
            new,
            msg=(
                f"NOUVELLES cles de _FALLBACK_FR ({I18N_JS_REL}) absentes de "
                f"locales/fr.json :\n"
                + "\n".join(f"  - '{k}'" for k in new)
                + "\nLe fallback hardcode doit rester un sous-ensemble de "
                  "fr.json (sinon il masque une cle morte ou une faute de "
                  "frappe). Corriger : ajouter la cle dans locales/fr.json ET "
                  "en.json, ou corriger/retirer l'entree du fallback."
            ),
        )

        stale = sorted(KNOWN_FALLBACK_ORPHANS - orphans)
        self.assertFalse(
            stale,
            msg=(
                f"Entrees KNOWN_FALLBACK_ORPHANS perimees (plus violees) : "
                f"{stale}.\nCorriger : les retirer de la constante dans "
                f"tests/test_contract_i18n.py."
            ),
        )


if __name__ == "__main__":
    unittest.main()
