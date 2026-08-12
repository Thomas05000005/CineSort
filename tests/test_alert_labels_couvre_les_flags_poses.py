"""Tout flag pose sur `PlanRow.warning_flags` doit avoir une etiquette humaine.

`web/dashboard/core/alert-labels.js` ecrit lui-meme sa source de verite en tete
de fichier :

    * Source des flags : grep ALL warning_flags.append() dans cinesort/{app,domain}.

Ce test formalise cette phrase. Il ne compare AUCUN fragment de code source : il
derive DEUX ENSEMBLES — les flags poses cote Python, les cles de `FLAG_MAP` cote
JS — et verifie l'inclusion. Il reste donc vrai quand le code s'ameliore, et
rougit quand un flag est ajoute d'un cote sans l'autre.

CE QUE LA CONVENTION `grep .append()` LAISSAIT PASSER. Un flag pose par
AFFECTATION et non par `.append()` echappait au grep :

    result_row.warning_flags = [runtime_hard_excluded_flag]   # plan_support_replan

`runtime_hard_filter_excluded_candidate` etait donc absent de `FLAG_MAP`, et
`labelForFlag` (alert-labels.js) retombait sur son cas « flag inconnu » :

    ⚠  runtime_hard_filter_excluded_candidate
       Alerte « runtime_hard_filter_excluded_candidate » (non documentee).
       Signalez-la si elle est frequente.

Or ce flag existe precisement pour repondre a une question d'utilisateur, et son
propre commentaire le dit (`domain/runtime_hard_filter.py`) :

    # Warning pose sur la PlanRow quand au moins un candidat a ete exclu par le
    # filtre HARD (utile pour debug user en UI : "Pourquoi mon film n'a pas matche ?").

L'application demandait donc a l'utilisateur de lui signaler son propre code
interne, a l'endroit meme ou elle etait censee expliquer un non-match.

Meme cas pour `bonus_video`, alors que `_SCAN_ONLY_WARNING_FLAGS`
(`library_actions_support.py`) le traite explicitement comme un BADGE d'interface
— le commentaire du report-arriere dit qu'un rescan les effacait et que cela
faisait perdre des « badges UI ». Son voisin immediat dans ce meme tuple,
`root_level_source`, a bien son etiquette. L'asymetrie portait sur deux flags
manipules par la meme ligne de code.

SENS UNIQUE, DELIBERE. Le test verifie « tout flag pose est etiquete », pas la
reciproque. Une etiquette sans flag correspondant est inerte (elle n'apparait
jamais), alors qu'un flag sans etiquette est vu par l'utilisateur. Exiger la
reciproque ferait rougir le test sur des etiquettes defensives legitimes
(`duplicate_same_root`, `low_bitrate`, `low_confidence_tmdb`) et sur celles que
les vues Bibliotheque/Qualite alimentent par d'autres chemins.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]
_JS = _RACINE / "web" / "dashboard" / "core" / "alert-labels.js"
_SOURCES = (_RACINE / "cinesort" / "app", _RACINE / "cinesort" / "domain")

#: Prefixes que `labelForFlag` fabrique DYNAMIQUEMENT (alert-labels.js) au lieu
#: de les lister dans `FLAG_MAP` : `subtitle_missing_<lang>` et
#: `subtitle_forced_only_<lang>`. Un flag qui commence par l'un d'eux est donc
#: couvert meme sans cle explicite.
_PREFIXES_DYNAMIQUES = ("subtitle_missing_", "subtitle_forced_only_")


def _cles_flag_map() -> set[str]:
    """Cles de premier niveau du litteral `FLAG_MAP` de alert-labels.js.

    LA REGEX EST LARGE, ET LE PARSEUR SE SURVEILLE. Une premiere version exigeait
    exactement DEUX espaces d'indentation et des cles strictement en minuscules.
    Signale par sourcery-ai sur la PR #1029, et la consequence est precise : si
    l'extraction RATE une cle pourtant presente, le test l'annonce comme
    « absente de FLAG_MAP » — un faux positif qui casse la CI sans qu'aucun
    defaut n'existe, et qui envoie corriger le mauvais fichier.

    Deux mesures plutot qu'une :

    1. l'indentation est libre (`^\\s+`) et le jeu de caracteres elargi, donc un
       reformatage ne casse plus rien ;
    2. le nombre de cles extraites est confronte au nombre d'ouvertures d'objet
       du bloc. Si le parseur cesse de voir la carte, il le DIT au lieu de rendre
       un ensemble ampute — c'est la difference entre un outil qui echoue et un
       outil qui ment.
    """
    texte = _JS.read_text(encoding="utf-8")
    debut = texte.index("const FLAG_MAP")
    fin = texte.index("\n};", debut)
    corps = texte[debut:fin]

    cles = set(re.findall(r"^\s+([A-Za-z_$][\w$]*)\s*:\s*\{", corps, re.M))
    # Chaque entree de premier niveau ouvre un objet ; le compte doit concorder.
    ouvertures = len(re.findall(r"^\s+[\"'A-Za-z_$][^\n:]*:\s*\{", corps, re.M))
    if not cles or len(cles) != ouvertures:
        raise AssertionError(
            f"l'extraction des cles de FLAG_MAP ne suit plus le fichier : "
            f"{len(cles)} cle(s) reconnue(s) pour {ouvertures} entree(s) ouvrant un objet. "
            f"Corriger CE parseur, pas `alert-labels.js` — sans quoi les cles manquees "
            f"seraient signalees comme absentes de FLAG_MAP."
        )
    return cles


def _est_cible_warning_flags(noeud: ast.AST) -> bool:
    """Vrai si `noeud` designe un `warning_flags` (attribut ou variable locale)."""
    if isinstance(noeud, ast.Attribute):
        return noeud.attr == "warning_flags"
    if isinstance(noeud, ast.Name):
        return noeud.id == "warning_flags"
    return False


def _est_alias_warning_flags(noeud: ast.AST) -> bool:
    """Vrai pour `getattr(X, "warning_flags", ...)`.

    Forme reellement utilisee par `plan_support_core` pour poser `bonus_video` :
    la liste est d'abord recuperee dans une variable locale, puis `.append()` est
    appele sur elle. Sans cette resolution l'extracteur passait a cote.
    """
    return (
        isinstance(noeud, ast.Call)
        and isinstance(noeud.func, ast.Name)
        and noeud.func.id == "getattr"
        and len(noeud.args) >= 2
        and isinstance(noeud.args[1], ast.Constant)
        and noeud.args[1].value == "warning_flags"
    )


def _code_de_flag(valeur: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{3,}", valeur))


def _litteraux_directs(noeuds: list[ast.expr]) -> set[str]:
    """Codes de flag parmi des expressions PRISES AU PREMIER NIVEAU.

    Volontairement SANS `ast.walk` : un parcours recursif ramassait les cles de
    dictionnaire d'un appel imbrique (`nfo_state["nfo_ok"]`) et inventait des
    flags `nfo_ok` / `year_delta_reject` qui n'existent pas.
    """
    out: set[str] = set()
    for noeud in noeuds:
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and _code_de_flag(noeud.value):
            out.add(noeud.value)
    return out


def _elements_de_collection(valeur: ast.expr) -> list[ast.expr]:
    """Elements d'un litteral `[...]` / `(...)` / `{...}`, sinon rien.

    Une valeur qui n'est PAS une collection litterale (appel de fonction,
    comprehension) ne dit rien de lisible statiquement : on ne devine pas.
    """
    if isinstance(valeur, (ast.List, ast.Tuple, ast.Set)):
        return list(valeur.elts)
    return []


def _constantes_warn(chemin: Path) -> dict[str, str]:
    """`WARN_X = "code"` du module : les flags passent souvent par ces constantes."""
    out: dict[str, str] = {}
    for m in re.finditer(
        r'^(WARN_[A-Z0-9_]+)\s*=\s*["\']([a-z][a-z0-9_]+)["\']',
        chemin.read_text(encoding="utf-8"),
        re.M,
    ):
        out[m.group(1)] = m.group(2)
    return out


def _constantes_warn_globales() -> dict[str, str]:
    out: dict[str, str] = {}
    for base in _SOURCES + (_RACINE / "cinesort" / "domain",):
        for chemin in base.rglob("*.py"):
            if "__pycache__" in chemin.parts:
                continue
            out.update(_constantes_warn(chemin))
    return out


def flags_poses() -> dict[str, set[str]]:
    """Flags ecrits dans un `warning_flags`, avec leurs sites.

    Couvre les QUATRE formes rencontrees dans le depot :
      - `row.warning_flags.append("x")` — la seule que la convention grep voyait ;
      - `row.warning_flags = ["x"]` / `= [CONSTANTE]` — la forme OUBLIEE, celle qui
        a laisse passer `runtime_hard_filter_excluded_candidate` ;
      - `flags = getattr(row, "warning_flags", None)` puis `flags.append("x")` —
        celle de `bonus_video` ;
      - `warning_flags=[...]` passe en mot-cle a un constructeur de PlanRow.

    C'est une BORNE INFERIEURE assumee : un flag construit dynamiquement
    (`f"subtitle_missing_{lang}"`) n'est pas lisible statiquement, d'ou les
    prefixes dynamiques traites a part. `test_la_mesure_trouve_bien_quelque_chose`
    empeche l'extracteur de devenir aveugle en silence.
    """
    warn = _constantes_warn_globales()
    out: dict[str, set[str]] = {}

    for base in _SOURCES:
        for chemin in sorted(base.rglob("*.py")):
            if "__pycache__" in chemin.parts:
                continue
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - le depot compile
                continue
            rel = chemin.relative_to(_RACINE).as_posix()

            # Noms locaux qui DESIGNENT une liste warning_flags, et noms locaux
            # qui PORTENT un code de flag venu d'une constante WARN_*.
            alias_listes: set[str] = set()
            alias_codes: dict[str, str] = {}
            for noeud in ast.walk(arbre):
                if not (isinstance(noeud, ast.Assign) and len(noeud.targets) == 1):
                    continue
                cible = noeud.targets[0]
                if not isinstance(cible, ast.Name):
                    continue
                if _est_alias_warning_flags(noeud.value):
                    alias_listes.add(cible.id)
                elif isinstance(noeud.value, ast.Name) and noeud.value.id in warn:
                    alias_codes[cible.id] = warn[noeud.value.id]

            def _resolus(noeuds: list[ast.expr], _ac: dict[str, str] = alias_codes) -> set[str]:
                codes = _litteraux_directs(noeuds)
                for n in noeuds:
                    if isinstance(n, ast.Name):
                        if n.id in warn:
                            codes.add(warn[n.id])
                        elif n.id in _ac:
                            codes.add(_ac[n.id])
                return codes

            def _enregistre(codes: set[str], ligne: int, _rel: str = rel) -> None:
                for code in codes:
                    out.setdefault(code, set()).add(f"{_rel}:{ligne}")

            for noeud in ast.walk(arbre):
                # a) `X.warning_flags = [...]` (ou variable locale `warning_flags`)
                if isinstance(noeud, ast.Assign) and any(_est_cible_warning_flags(t) for t in noeud.targets):
                    _enregistre(_resolus(_elements_de_collection(noeud.value)), noeud.lineno)
                # b) `.append(...)` sur un warning_flags direct ou aliase
                if (
                    isinstance(noeud, ast.Call)
                    and isinstance(noeud.func, ast.Attribute)
                    and noeud.func.attr == "append"
                ):
                    recepteur = noeud.func.value
                    aliase = isinstance(recepteur, ast.Name) and recepteur.id in alias_listes
                    if _est_cible_warning_flags(recepteur) or aliase:
                        _enregistre(_resolus(list(noeud.args)), noeud.lineno)
                # c) `warning_flags=[...]` en mot-cle d'un constructeur
                if isinstance(noeud, ast.Call):
                    for kw in noeud.keywords:
                        if kw.arg == "warning_flags":
                            _enregistre(_resolus(_elements_de_collection(kw.value)), noeud.lineno)
    return out


def _couvert(flag: str, cles: set[str]) -> bool:
    return flag in cles or flag.startswith(_PREFIXES_DYNAMIQUES)


class AlertLabelsCouvreLesFlagsPosesTests(unittest.TestCase):
    def test_la_mesure_trouve_bien_quelque_chose(self) -> None:
        """Sans ce garde-fou, un extracteur casse rendrait le test complaisant :
        zero flag trouve et zero cle trouvee font passer n'importe quoi."""
        self.assertGreaterEqual(len(flags_poses()), 10, "extracteur de flags casse")
        self.assertGreaterEqual(len(_cles_flag_map()), 20, "extracteur de FLAG_MAP casse")

    def test_tout_flag_pose_a_une_etiquette(self) -> None:
        cles = _cles_flag_map()
        poses = flags_poses()

        orphelins = {f: sorted(sites) for f, sites in poses.items() if not _couvert(f, cles)}

        self.assertEqual(
            orphelins,
            {},
            "flag(s) pose(s) sur PlanRow.warning_flags sans etiquette dans "
            "web/dashboard/core/alert-labels.js : l'utilisateur voit le code interne "
            "et le message « non documentee ». Ajouter une entree a FLAG_MAP. Detail : "
            + ", ".join(f"{f} ({', '.join(s)})" for f, s in sorted(orphelins.items())),
        )

    def test_les_deux_flags_du_correctif_sont_bien_etiquetes(self) -> None:
        """Garde nomme : ces deux-la sont ceux qui manquaient. Si une refonte de
        FLAG_MAP les reperd, ce test le dit sans dependre de l'extracteur."""
        cles = _cles_flag_map()

        for flag in ("runtime_hard_filter_excluded_candidate", "bonus_video"):
            with self.subTest(flag=flag):
                self.assertIn(flag, cles)

    def test_un_flag_INVENTE_nest_PAS_couvert(self) -> None:
        """Contre-epreuve : sans elle, un `_couvert` qui rendrait toujours True
        ferait passer les tests ci-dessus."""
        self.assertFalse(_couvert("flag_qui_nexiste_pas", _cles_flag_map()))


if __name__ == "__main__":
    unittest.main()
