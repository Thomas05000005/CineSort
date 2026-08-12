# -*- coding: utf-8 -*-
"""Contrat M1 (permanent) : cablage UI apiPost() -> facades API REST.

Source de verite initiale : docs/internal/verif_totale_2026_07/matrices/
m1_ui_api.json (genere par scripts_matrices/m1_ui_api.py, 2026-07-08).
Ce test fige le contrat, statiquement (aucun reseau / app / DB) :

 1. chaque ``apiPost("facade/methode", {...})`` de ``web/dashboard/**/*.js``
    doit viser une methode existante de la facade visee (introspection
    ``inspect.signature`` des 6 facades ``cinesort.ui.api.facades.*``) ;
 2. si le payload est un objet litteral, ses cles doivent etre incluses dans
    les parametres de la signature (sauf ``**kwargs``) — le dispatch serveur
    fait ``method(**params)`` : cle inconnue => TypeError => 400 ;
 3. les endpoints dynamiques (1er argument non litteral) sont limites a la
    liste blanche DYNAMIC_ALLOWED_SITES / DYNAMIC_RESOLVED_ENDPOINTS
    (2 sites physiques dans parametres.js -> 7 endpoints resolus) ;
    tout NOUVEAU site dynamique non liste = echec ;
 4. les violations CONNUES sont figees dans KNOWN_BROKEN : le test echoue si
    une NOUVELLE violation apparait ET si une entree KNOWN n'est plus violee
    (entree perimee a retirer -> la liste ne peut que RETRECIR, cf Phase 5
    de PLAN_VERIF_TOTALE.md).

Les cles de violation sont volontairement SANS numero de ligne (robustes aux
editions) : (fichier relatif, endpoint, sorte_de_violation).
"""

from __future__ import annotations

import importlib
import inspect
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "web" / "dashboard"

# ---------------------------------------------------------------------------
# Violations CONNUES. Cle = (fichier relatif posix, endpoint, sorte). La liste
# ne peut que RETRECIR : corriger le JS (ou la facade) PUIS retirer l'entree.
# Les 5 violations de la matrice m1_ui_api.json (2026-07-08) ont toutes ete
# corrigees en Lot E (E2/E3/E4/E5/E8) : la liste est VIDE — toute violation
# UI->API est desormais bloquante.
# ---------------------------------------------------------------------------
KNOWN_BROKEN: dict[tuple[str, str, str], str] = {}

# ---------------------------------------------------------------------------
# Endpoints dynamiques toleres (matrice m1_ui_api.json, champ forward :
# 2 sites physiques -> 7 endpoints resolus, tous verdict OK).
# Cle = (fichier relatif posix, expression du 1er argument) -> nb de sites.
# Tout NOUVEAU site dynamique (fichier/expression hors liste, ou site en trop)
# = echec. Si un site disparait, retirer/decrementer l'entree.
# ---------------------------------------------------------------------------
DYNAMIC_ALLOWED_SITES: dict[tuple[str, str], int] = {
    # L1030 : const method = force ? "runtime/recheck_probe_tools"
    #                              : "runtime/get_probe_tools_status"
    # L2207 : boutons "Tester" -> dataset.testMethod (5 integrations)
    ("web/dashboard/views/parametres.js", "method"): 2,
    # Vague B1 : le cadenas de verrouillage d'un champ. La route depend de
    # l'etat du verrou -- `clear_field_lock` s'il est pose, `set_field_lock`
    # sinon -- et les DEUX branches sont couvertes par
    # `tests/test_cadenas_verrous_fiche_film.py`, qui verifie la route ET le
    # nom de champ transmis.
    ("web/dashboard/components/film-detail.js", "route"): 1,
    # Vague B2 : les cinq actions d'integration (rapports de coherence,
    # rafraichissements, email de test). La route est portee par le bouton, donc
    # UN seul site physique pour cinq endpoints — c'est la meme discipline
    # declarative que le reste de la page, et
    # `tests/test_actions_integration_parametres.py` verrouille la liste exacte.
    ("web/dashboard/views/parametres.js", "route"): 1,
}

# Les endpoints resolus derriere les sites dynamiques ci-dessus. Chacun doit
# rester une methode valide de sa facade (garde contre un rename backend).
DYNAMIC_RESOLVED_ENDPOINTS: tuple[str, ...] = (
    "integrations/get_jellyfin_sync_report",
    "integrations/get_plex_sync_report",
    "integrations/refresh_jellyfin_library_now",
    "integrations/refresh_plex_library_now",
    "integrations/test_email_report",
    "library/clear_field_lock",
    "library/set_field_lock",
    "runtime/get_probe_tools_status",
    "runtime/recheck_probe_tools",
    "integrations/test_jellyfin_connection",
    "integrations/test_omdb_connection",
    "integrations/test_plex_connection",
    "integrations/test_radarr_connection",
    "integrations/test_tmdb_key",
)

FACADE_CLASS = {
    "run": "RunFacade",
    "settings": "SettingsFacade",
    "quality": "QualityFacade",
    "integrations": "IntegrationsFacade",
    "library": "LibraryFacade",
    "runtime": "RuntimeFacade",
}


# ---------------------------------------------------------------------------
# Introspection des facades (meme logique que scripts_matrices/m1_ui_api.py)
# ---------------------------------------------------------------------------
def _introspect_facades():
    """{facade: {method: {"known": set(params), "has_kwargs": bool, "sig": str}}}"""
    from cinesort.infra.rest_server import _FACADE_ATTR_NAMES

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
                methods[name] = {"known": set(), "has_kwargs": True, "sig": "<introuvable>"}
                continue
            known, has_kwargs = set(), False
            for pname, p in sig.parameters.items():
                if pname == "self":
                    continue
                if p.kind == inspect.Parameter.VAR_KEYWORD:
                    has_kwargs = True
                elif p.kind != inspect.Parameter.VAR_POSITIONAL:
                    known.add(pname)
            methods[name] = {"known": known, "has_kwargs": has_kwargs, "sig": str(sig)}
        out[fname] = methods
    return out


# ---------------------------------------------------------------------------
# Mini-parseur JS (copie compacte de scripts_matrices/m1_ui_api.py, qui a
# produit la matrice de reference : 74 fichiers / 193 sites apiPost)
# ---------------------------------------------------------------------------
_IDENT_CHARS = re.compile(r"[A-Za-z0-9_$.]")
_ENDPOINT_SHAPE = re.compile(r"^[a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)?$")
_KEY_RE = re.compile(r'^(?:(["\'])(?P<qkey>[^"\']+)\1|(?P<key>[A-Za-z_$][\w$]*))\s*:')
_SHORTHAND_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def _strip_js_comments(src: str) -> str:
    """Remplace // et /* */ par des espaces, newlines et chaines preserves."""
    out = list(src)
    i, n, state = 0, len(src), None
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c in ("'", '"', "`"):
                state = c
            elif c == "/" and nxt in ("/", "*"):
                state = "//" if nxt == "/" else "/*"
                out[i] = out[i + 1] = " "
                i += 1
        elif state in ("'", '"', "`"):
            if c == "\\":
                i += 1
            elif c == state:
                state = None
            elif c == "\n" and state in ("'", '"'):
                state = None  # chaine non terminee : resynchronisation
        elif state == "//":
            if c == "\n":
                state = None
            else:
                out[i] = " "
        else:  # "/*"
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = None
                i += 1
            elif c != "\n":
                out[i] = " "
        i += 1
    return "".join(out)


def _split_top_level_args(text: str) -> list[str]:
    args, depth, cur, i, n, in_str = [], 0, [], 0, len(text), None
    while i < n:
        c = text[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < n:
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


def _extract_call_args(stripped: str, open_paren: int) -> str:
    """Texte des arguments entre la parenthese ouvrante et sa fermante."""
    depth, i, n, in_str = 0, open_paren, len(stripped), None
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
                return stripped[open_paren + 1 : i]
        i += 1
    return stripped[open_paren + 1 :]


def _parse_payload_keys(arg: str | None):
    """(kind, keys) — kind: 'object' | 'empty' | 'expression' | 'absent'.
    Seules les cles top-level explicites sont retournees (spread/computed
    ignores : la presence d'une cle inconnue EXPLICITE suffit au TypeError)."""
    if not arg:
        return "absent", []
    a = arg.strip()
    if not a.startswith("{"):
        return "expression", []
    inner = a[1 : a.rfind("}")] if a.rfind("}") > 0 else a[1:]
    keys, has_content = [], False
    for part in _split_top_level_args(inner):
        p = part.strip()
        if not p:
            continue
        has_content = True
        if p.startswith("...") or p.startswith("["):
            continue  # spread / computed key : non statique, ignore
        m = _KEY_RE.match(p)
        if m:
            keys.append(m.group("qkey") or m.group("key"))
        elif ":" not in p and _SHORTHAND_RE.match(p.split("=")[0].strip()):
            keys.append(p.split("=")[0].strip())  # shorthand {foo} / {foo = def}
    return ("object" if has_content else "empty"), keys


def _scan_apipost_sites():
    """[{file, line, first, endpoint|None, payload_kind, payload_keys}]"""
    sites = []
    js_files = sorted(DASHBOARD_DIR.rglob("*.js"))
    for path in js_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        stripped = _strip_js_comments(path.read_text(encoding="utf-8", errors="replace"))
        for mo in re.finditer(r"apiPost\s*\(", stripped):
            s = mo.start()
            prev = stripped[s - 1] if s > 0 else ""
            if prev and _IDENT_CHARS.match(prev):
                continue  # _spaApiPost, monApiPost, ...
            if re.search(r"function\s+$", stripped[max(0, s - 40) : s]):
                continue  # definition du wrapper, pas un appel
            args = _split_top_level_args(_extract_call_args(stripped, mo.end() - 1))
            first = (args[0] if args else "").strip()
            second = args[1] if len(args) > 1 else None
            if (first[:1] in ("'", '"') and first[-1:] == first[:1]) or (
                first[:1] == "`" and first[-1:] == "`" and "${" not in first
            ):
                endpoint = first[1:-1]
            else:
                endpoint = None  # site dynamique
            kind, keys = _parse_payload_keys(second)
            sites.append(
                {
                    "file": rel,
                    "line": stripped.count("\n", 0, s) + 1,
                    "first": re.sub(r"\s+", " ", first)[:80],
                    "endpoint": endpoint,
                    "payload_kind": kind,
                    "payload_keys": keys,
                }
            )
    return sites, len(js_files)


# ---------------------------------------------------------------------------
# Calcul des violations : cle robuste (file, endpoint, sorte), sans ligne
# ---------------------------------------------------------------------------
def _violation_for_site(site, facades, excluded):
    """(sorte, message_correctif) ou None si le site est conforme."""
    ep = site["endpoint"]
    if "/" not in ep:
        extra = " (methode aussi dans _EXCLUDED_METHODS => 404)" if ep in excluded else ""
        return (
            "sans_facade",
            f"endpoint legacy '{ep}' sans facade => 410 Gone (Pass 1 desactivee){extra}. "
            "Correction : appeler 'facade/methode' d'une des 6 facades.",
        )
    fac, meth = ep.split("/", 1)
    if meth in excluded:
        return (
            "methode_exclue",
            f"'{meth}' est dans _EXCLUDED_METHODS (rest_server.py) => jamais exposee (404). "
            "Correction : retirer l'appel UI ou exposer une vraie methode de facade.",
        )
    if fac not in facades:
        elsewhere = sorted(f for f, ms in facades.items() if meth in ms)
        hint = f" ; methode presente sur: {', '.join(elsewhere)}" if elsewhere else ""
        return (
            f"facade_inconnue:{fac}",
            f"facade '{fac}' inconnue (6 facades: {', '.join(sorted(facades))}){hint}. "
            "Correction : corriger le prefixe de l'endpoint dans le JS.",
        )
    if meth not in facades[fac]:
        elsewhere = sorted(f for f, ms in facades.items() if meth in ms)
        if elsewhere:
            return (
                "mauvaise_facade",
                f"'{meth}' absent de la facade '{fac}' mais present sur: "
                f"{', '.join(elsewhere)} => 404. Correction : corriger le prefixe "
                "dans le JS (ou deplacer la methode de facade).",
            )
        return (
            "methode_inexistante",
            f"'{meth}' absent des 6 facades => 404. Correction : corriger le nom "
            "dans le JS ou implementer la methode sur la facade visee.",
        )
    spec = facades[fac][meth]
    if site["payload_kind"] == "object" and not spec["has_kwargs"]:
        unexpected = sorted(k for k in site["payload_keys"] if k not in spec["known"])
        if unexpected:
            return (
                "cles_inconnues:" + ",".join(unexpected),
                f"cles payload inconnues de la signature {spec['sig']} "
                f"(dispatch method(**params) => TypeError => 400): {', '.join(unexpected)}. "
                "Correction : renommer/retirer ces cles dans le JS, ou ajouter le "
                "parametre cote facade.",
            )
    return None


_CACHE: dict = {}


def _analyse():
    """Scan + verdicts, calcule une seule fois pour toute la classe."""
    if _CACHE:
        return _CACHE
    sites, js_file_count = _scan_apipost_sites()
    facades = _introspect_facades()
    from cinesort.infra.rest_server import _EXCLUDED_METHODS

    violations: dict[tuple[str, str, str], str] = {}
    dynamic_sites: dict[tuple[str, str], int] = {}
    for site in sites:
        if site["endpoint"] is None:
            key = (site["file"], site["first"])
            dynamic_sites[key] = dynamic_sites.get(key, 0) + 1
            continue
        res = _violation_for_site(site, facades, _EXCLUDED_METHODS)
        if res is not None:
            sorte, msg = res
            violations[(site["file"], site["endpoint"], sorte)] = (
                f"{site['file']}:{site['line']} — apiPost('{site['endpoint']}') : {msg}"
            )
    _CACHE.update(
        {
            "sites": sites,
            "js_file_count": js_file_count,
            "facades": facades,
            "excluded": set(_EXCLUDED_METHODS),
            "violations": violations,
            "dynamic_sites": dynamic_sites,
        }
    )
    return _CACHE


class ContractUiApiTests(unittest.TestCase):
    """Contrat M1 : chaque apiPost du dashboard vise une methode de facade
    existante avec un payload compatible ; violations connues figees."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _analyse()

    def test_sanity_scan_volume(self) -> None:
        """Garde anti-faux-vert : le scan doit retrouver l'ordre de grandeur de
        la matrice M1. Etat 2026-07-09 apres purge Phase 5 (6 vues + 20 modules
        morts supprimes) : 48 fichiers JS, 160 sites apiPost (etait 74/193)."""
        self.assertGreaterEqual(
            self.data["js_file_count"],
            40,
            "Trop peu de fichiers JS scannes : web/dashboard a-t-il bouge ?",
        )
        self.assertGreaterEqual(
            len(self.data["sites"]),
            150,
            "Trop peu de sites apiPost trouves : parseur ou arborescence casses ?",
        )
        total_methods = sum(len(m) for m in self.data["facades"].values())
        self.assertGreaterEqual(
            total_methods,
            150,
            "Introspection facades anormalement pauvre (172 methodes attendues).",
        )

    def test_no_new_broken_apipost_endpoint(self) -> None:
        """Toute NOUVELLE violation UI->API (endpoint inexistant, mauvaise
        facade, cle payload inconnue...) fait echouer ce test."""
        current = self.data["violations"]
        new = {k: v for k, v in current.items() if k not in KNOWN_BROKEN}
        self.assertEqual(
            new,
            {},
            msg=(
                f"\n{len(new)} NOUVELLE(S) violation(s) du contrat UI->API "
                "(non presentes dans KNOWN_BROKEN) :\n"
                + "\n".join(f"  - {msg}" for msg in sorted(new.values()))
                + "\nCorriger le JS/la facade, ou (exceptionnellement, avec "
                "justification) ajouter l'entree a KNOWN_BROKEN."
            ),
        )

    def test_known_broken_list_only_shrinks(self) -> None:
        """Une entree KNOWN_BROKEN qui n'est plus violee est PERIMEE : la
        retirer (la liste ne peut que retrecir, Phase 5 PLAN_VERIF_TOTALE)."""
        current = self.data["violations"]
        stale = [k for k in KNOWN_BROKEN if k not in current]
        self.assertEqual(
            stale,
            [],
            msg=(
                f"\n{len(stale)} entree(s) KNOWN_BROKEN perimee(s) (plus violees) :\n"
                + "\n".join(f"  - {k}" for k in stale)
                + "\nBravo pour la correction : retirer ces entrees de "
                "KNOWN_BROKEN dans tests/test_contract_ui_api.py."
            ),
        )

    def test_dynamic_apipost_sites_whitelisted(self) -> None:
        """Les sites apiPost a endpoint dynamique doivent correspondre
        EXACTEMENT a la liste blanche (2 sites parametres.js)."""
        observed = self.data["dynamic_sites"]
        self.assertEqual(
            observed,
            DYNAMIC_ALLOWED_SITES,
            msg=(
                f"\nSites apiPost dynamiques observes {observed} != liste blanche "
                f"{DYNAMIC_ALLOWED_SITES}.\nUn NOUVEAU site dynamique doit etre "
                "resolu statiquement (cf scripts_matrices/m1_ui_api.py), verifie "
                "contre les facades, puis ajoute a DYNAMIC_ALLOWED_SITES + "
                "DYNAMIC_RESOLVED_ENDPOINTS. Un site disparu doit etre retire."
            ),
        )

    def test_dynamic_resolved_endpoints_still_exist(self) -> None:
        """Les 7 endpoints resolus derriere les sites dynamiques restent des
        methodes valides et non exclues de leurs facades (garde anti-rename)."""
        facades, excluded = self.data["facades"], self.data["excluded"]
        problems = []
        for ep in DYNAMIC_RESOLVED_ENDPOINTS:
            fac, meth = ep.split("/", 1)
            if fac not in facades or meth not in facades.get(fac, {}):
                problems.append(f"{ep} : methode absente de la facade '{fac}'")
            elif meth in excluded:
                problems.append(f"{ep} : methode dans _EXCLUDED_METHODS")
        self.assertEqual(
            problems,
            [],
            msg=(
                "\nEndpoints dynamiques resolus devenus invalides :\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\nCorriger le backend/l'UI puis mettre a jour "
                "DYNAMIC_RESOLVED_ENDPOINTS."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
