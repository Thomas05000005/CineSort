# -*- coding: utf-8 -*-
"""Contrat permanent facades (verif totale 2026-07, M2 + reverse M1).

Verifie statiquement (AST + scan JS, ZERO import du code applicatif,
zero reseau/DB) 4 invariants du cablage facades de cinesort/ui/api/ :

1. ORPHELINES (reverse M1) : toute methode publique de facade doit avoir un
   consommateur web (litteral "facade/methode" dans web/dashboard/**/*.js,
   commentaires JS strippes). Les 53 orphelines connues sont figees dans
   KNOWN_ORPHAN_METHODS. Nouvelle methode sans consommateur ET hors liste
   = echec (decision forcee : cabler dans l'UI ou documenter ici).

2. HOMONYMES _X_impl (M2) : les 11 paires god-class/support connues sont
   figees dans KNOWN_HOMONYM_IMPLS. Nouvelle paire (methode CineSortApi
   *_impl homonyme d'une fonction top-level d'un module *_support*.py)
   = echec (source de confusion god vs support, cf m2_facades_impl.json).

3. MULTI-FACADE (M2) : 3 methodes connues exposees sur 2 facades
   (KNOWN_MULTI_FACADE). Toute nouvelle exposition double = echec.

4. FACADES NON INSTANCIEES (M2) : toute classe *Facade de ui/api/ doit etre
   instanciee quelque part dans cinesort/ (hors tests). KNOWN :
   SimilarFilmsFacade (code mort assume, cf m2 facade_instantiations).

REGLE PHASE 5 (PLAN_VERIF_TOTALE.md) : les listes KNOWN_* ne peuvent que
RETRECIR. Si une entree n'est plus violee (methode cablee, supprimee,
homonyme renomme, facade instanciee), le test echoue aussi : retirer
l'entree perimee.

Source des baselines (rejouables) :
  docs/internal/verif_totale_2026_07/matrices/m1_ui_api.json   (reverse)
  docs/internal/verif_totale_2026_07/matrices/m2_facades_impl.json
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "cinesort" / "ui" / "api"
FACADES_DIR = API_DIR / "facades"
GOD_FILE = API_DIR / "cinesort_api.py"
REST_SERVER_FILE = REPO_ROOT / "cinesort" / "infra" / "rest_server.py"
DASHBOARD_DIR = REPO_ROOT / "web" / "dashboard"

# ---------------------------------------------------------------------------
# Baselines figees (etat 2026-07-08, matrices m1/m2). NE PEUT QUE RETRECIR.
# ---------------------------------------------------------------------------

# reverse M1 : 50 ORPHELINE + 3 ORPHELINE_INCERTAINE (get_profiles/save_profile/
# set_active_profile cote quality : nom nu present dans le JS mais jamais
# "quality/<methode>"). Format "facade.methode" (facade = stem du fichier
# facades/<facade>_facade.py = prefixe d'endpoint REST).
KNOWN_ORPHAN_METHODS = frozenset(
    {
        # Phase 5 (purge verif totale) : ces 8 methodes n'etaient consommees QUE par
        # les 6 vues mortes supprimees (status/logs/jellyfin/plex/radarr.js) — la
        # purge a revele qu'elles etaient orphelines de facto. A cabler dans les
        # vues vivantes (integrations dans parametres.js) ou a elaguer = decision produit.
        "integrations.request_radarr_upgrade",
        "library.get_film_history",
        "quality.analyze_perceptual_batch",
        "quality.analyze_quality_batch",
        "quality.apply_quality_preset",
        "quality.compare_perceptual",
        "quality.export_quality_profile",
        "quality.export_shareable_profile",
        "quality.get_calibration_report",
        "quality.get_custom_rules_catalog",
        "quality.get_custom_rules_templates",
        "quality.get_profiles",
        "quality.get_quality_profile",
        "quality.get_quality_report",
        "quality.import_quality_profile",
        "quality.import_shareable_profile",
        "quality.save_profile",
        "quality.save_quality_profile",
        "quality.set_active_profile",
        "quality.validate_custom_rules",
        "run.check_duplicates_fusion",  # B4 : NON cablable — gardee par la variable d'ENVIRONNEMENT serveur CINESORT_FUSION_DOUBLONS, qu'aucune ligne applicative ne positionne
        "run.cleanup_old_runs",  # B4 : NON cablable — doublon : la purge tourne DEJA seule via le cron de retention (24 h)
        "run.export_apply_audit",  # B4 : NON cablable — le parametre `limit` n'est pas transmis ; a traiter avec le defaut, pas par-dessus
        "run.get_cleanup_residual_preview",  # B4 : NON cablable — obstacle majeur signale par la contre-lecture, non tranche
        "run.import_watchlist",  # B4 : NON cablable — aucun domicile UI : la capacite n'a pas d'ecran d'accueil
        "run.list_apply_history",  # B4 : NON cablable — aucune action ne peut cibler un batch affiche : `undo_last_apply` n'accepte pas de batch_id
        "run.list_pending_runs",  # B4 : NON cablable — le bouton « Reprendre » qu'elle appelle refuse 1 des 3 statuts listes (_RESUMABLE_DB_STATES)
        "run.purge_quarantine_bucket",  # B4 : NON cablable — doublon partiel de « Vider maintenant », deja cable sur le meme perimetre
        "run.undo_by_row_preview",  # B4 : NON cablable — la preview par film n'expose ni apply_ts ni expired ; le cabler reactive l'impasse UNDONE_PARTIAL
        "runtime.check_for_updates",  # B3 : NON cablable — doublon d'une capacite deja presente dans l'UI
        "runtime.get_event_ts",
        "runtime.get_probe",
        "runtime.get_tools_status",  # B3 : NON cablable — ALIAS STRICT de get_probe_tools_status, deja cable (app.js) ; le cabler creerait un doublon de requete ET sortirait la reponse de la liste blanche du cache hors-ligne
        "runtime.reset_incremental_cache",  # B3 : NON cablable — impossible de dresser la liste d'elements qu'exige la regle des actions destructives
        "runtime.run_nas_benchmark",  # B3 : NON cablable — aucun parametre de chemin : « tester mon NAS » est irrealisable en l'etat
        "runtime.set_probe_tool_paths",  # B3 : NON cablable — perte de donnees sur payload partiel
        "settings.preview_naming_template",  # B3 : NON cablable — `sample_row_id` est INERTE : #460 documente que la branche chargeant un vrai film « etait morte depuis sa premiere ligne »
        "settings.reset_all_user_data",  # B3 : NON cablable — exige que l'utilisateur TAPE « RESET » (reset_support.py:266) ; dangerConfirmModal n'a aucune affordance de saisie
        "settings.set_locale",
    }
)

# M2 : methodes CineSortApi *_impl AVEC homonyme top-level dans un module
# *_support*.py (2 implementations du meme nom -> confusion, drift possible).
KNOWN_HOMONYM_IMPLS = frozenset(
    {
        "_get_diagnostic_impl",
        "_get_film_full_impl",
        "_get_history_stats_impl",
        "_get_library_filtered_impl",
        "_get_plan_impl",
        "_get_probe_impl",
        "_get_status_impl",
        "_list_apply_history_impl",
        "_mark_alert_ignored_impl",
        "_mark_for_deletion_impl",
        "_start_plan_impl",
    }
)

# M2 : methode publique exposee sur >= 2 classes facade (owners tries).
KNOWN_MULTI_FACADE = {
    "get_profiles": ("QualityFacade", "SettingsFacade"),
    "save_profile": ("QualityFacade", "SettingsFacade"),
    "set_active_profile": ("QualityFacade", "SettingsFacade"),
}

# M2 facade_instantiations : classes *Facade jamais instanciees dans cinesort/.
KNOWN_UNINSTANTIATED_FACADES = frozenset({"SimilarFilmsFacade"})


# ---------------------------------------------------------------------------
# Analyse statique (calculee UNE fois par session pytest)
# ---------------------------------------------------------------------------


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _extract_excluded_methods() -> frozenset[str]:
    """Lit _EXCLUDED_METHODS dans rest_server.py par AST (pas d'import app).

    Ces methodes (log, progress, ...) ne sont jamais exposees en REST : elles
    sont hors perimetre du verdict orpheline (aligne sur m1_ui_api.py).
    """
    tree = _parse(REST_SERVER_FILE)
    for node in tree.body:
        target, value = None, None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == "_EXCLUDED_METHODS" and value is not None:
            return frozenset(ast.literal_eval(value))
    raise AssertionError(
        "_EXCLUDED_METHODS introuvable dans cinesort/infra/rest_server.py — "
        "adapter _extract_excluded_methods() si la constante a ete renommee."
    )


def _strip_js_comments(src: str) -> str:
    """Remplace // et /* */ par des espaces (chaines ' \" ` respectees).

    Portage de m1_ui_api.py : un endpoint mentionne uniquement dans un
    commentaire JS ne compte PAS comme consommateur.
    """
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
        elif state == "/*":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = None
                i += 1
            elif c != "\n":
                out[i] = " "
        i += 1
    return "".join(out)


def _facade_public_methods() -> dict[str, dict[str, int]]:
    """{facade_court: {methode_publique: ligne}} sur facades/*_facade.py.

    Defs propres des classes (AST), _base.py/__init__.py exclus. Le nom court
    (stem sans '_facade') est le prefixe d'endpoint REST (_FACADE_ATTR_NAMES).
    """
    out: dict[str, dict[str, int]] = {}
    for f in sorted(FACADES_DIR.glob("*.py")):
        if f.name in ("__init__.py", "_base.py"):
            continue
        short = f.stem[: -len("_facade")] if f.stem.endswith("_facade") else f.stem
        tree = _parse(f)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                meths = out.setdefault(short, {})
                for m in node.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_"):
                        meths[m.name] = m.lineno
    return out


def _all_facade_classes() -> dict[str, dict[str, object]]:
    """{classe *Facade: {file, methods{nom: ligne}}} sur ui/api/**/*.py."""
    out: dict[str, dict[str, object]] = {}
    for f in sorted(API_DIR.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        tree = _parse(f)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.endswith("Facade") and not node.name.startswith("_"):
                meths = {
                    m.name: m.lineno
                    for m in node.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_")
                }
                rel = str(f.relative_to(REPO_ROOT)).replace("\\", "/")
                out[node.name] = {"file": rel, "methods": meths}
    return out


def _god_impl_methods() -> dict[str, int]:
    """Methodes *_impl de la classe CineSortApi (god-class)."""
    tree = _parse(GOD_FILE)
    out: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CineSortApi":
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.endswith("_impl"):
                    out[m.name] = m.lineno
    return out


def _support_toplevel_funcs() -> dict[str, list[str]]:
    """{nom de fonction top-level: [stems des modules *_support*.py]}."""
    out: dict[str, list[str]] = {}
    for f in sorted(API_DIR.glob("*_support*.py")):
        tree = _parse(f)
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(n.name, []).append(f.stem)
    return out


def _instantiated_class_names(class_names: set[str]) -> set[str]:
    """Sous-ensemble de class_names appele (Call AST) dans cinesort/**/*.py."""
    found: set[str] = set()
    remaining = set(class_names)
    for f in sorted((REPO_ROOT / "cinesort").rglob("*.py")):
        if "__pycache__" in f.parts or not remaining:
            continue
        try:
            tree = _parse(f)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = None
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name in remaining:
                    found.add(name)
                    remaining.discard(name)
    return found


class _Analysis:
    """Resultat d'analyse partage entre les tests (calcule une seule fois)."""

    _instance: "_Analysis | None" = None

    @classmethod
    def get(cls) -> "_Analysis":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.excluded = _extract_excluded_methods()
        self.facade_methods = _facade_public_methods()
        self.facade_classes = _all_facade_classes()
        self.god_impls = _god_impl_methods()
        self.support_funcs = _support_toplevel_funcs()

        js_files = sorted(DASHBOARD_DIR.rglob("*.js"))
        self.js_file_count = len(js_files)
        self.js_corpus = "\n".join(
            _strip_js_comments(p.read_text(encoding="utf-8", errors="replace")) for p in js_files
        )

        # (1) orphelines : methode publique de facade sans litteral
        # "facade/methode" dans le JS strippe (hors _EXCLUDED_METHODS).
        self.orphans: set[str] = set()
        for fac, meths in self.facade_methods.items():
            for meth in meths:
                if meth in self.excluded:
                    continue
                if not re.search(re.escape(f"{fac}/{meth}") + r"\b", self.js_corpus):
                    self.orphans.add(f"{fac}.{meth}")

        # (2) homonymes _X_impl god ET support
        self.homonyms: set[str] = {n for n in self.god_impls if n in self.support_funcs}

        # (3) multi-facade : methode publique sur >= 2 classes facade
        owners: dict[str, set[str]] = {}
        for cls_name, info in self.facade_classes.items():
            for m in info["methods"]:  # type: ignore[union-attr]
                owners.setdefault(m, set()).add(cls_name)
        self.multi_facade: dict[str, tuple[str, ...]] = {
            m: tuple(sorted(cs)) for m, cs in owners.items() if len(cs) > 1
        }

        # (4) classes facade jamais instanciees dans cinesort/
        all_names = set(self.facade_classes)
        self.uninstantiated: set[str] = all_names - _instantiated_class_names(all_names)


class ContractFacadesTests(unittest.TestCase):
    """Contrat M2 + reverse M1 : orphelines, homonymes, multi-facade, ORPHELIN classe."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.a = _Analysis.get()

    # -- sanity : si un chemin casse, echouer clairement, pas silencieusement --

    def test_sanity_corpus_et_facades_scannes(self) -> None:
        self.assertGreaterEqual(
            self.a.js_file_count,
            10,
            msg=f"web/dashboard: seulement {self.a.js_file_count} fichiers .js "
            "scannes — arborescence deplacee ? Adapter DASHBOARD_DIR.",
        )
        self.assertGreaterEqual(
            len(self.a.facade_methods),
            6,
            msg=f"facades/ : {sorted(self.a.facade_methods)} — les 6 facades "
            "attendues (run/settings/quality/integrations/library/runtime) "
            "ne sont plus toutes trouvees. Adapter FACADES_DIR.",
        )
        total = sum(len(m) for m in self.a.facade_methods.values())
        self.assertGreaterEqual(
            total,
            100,
            msg=f"Seulement {total} methodes publiques de facade trouvees "
            "(172 attendues en 2026-07) — l'extraction AST a casse.",
        )

    # -- (1) reverse M1 : orphelines --

    def test_orphan_methods_pas_de_nouvelle(self) -> None:
        new = self.a.orphans - KNOWN_ORPHAN_METHODS
        lines = []
        for key in sorted(new):
            fac, meth = key.split(".", 1)
            lineno = self.a.facade_methods.get(fac, {}).get(meth, "?")
            lines.append(
                f"  - {key} (cinesort/ui/api/facades/{fac}_facade.py:{lineno}) : "
                f"aucun litteral '{fac}/{meth}' dans web/dashboard/**/*.js"
            )
        self.assertFalse(
            new,
            msg=(
                f"{len(new)} NOUVELLE(S) methode(s) publique(s) de facade sans "
                "consommateur web :\n" + "\n".join(lines) + "\n\n"
                "Correction — decision obligatoire, au choix :\n"
                "  a) cabler l'UI : apiPost('<facade>/<methode>', {...}) dans "
                "web/dashboard/ ;\n"
                "  b) assumer l'orpheline : ajouter '<facade>.<methode>' a "
                "KNOWN_ORPHAN_METHODS (tests/test_contract_facades.py) avec "
                "justification en revue ;\n"
                "  c) ne pas exposer : prefixer la methode par '_' ou la "
                "deplacer hors facade.\n"
                "Baseline : matrices/m1_ui_api.json (reverse)."
            ),
        )

    def test_orphan_methods_pas_dentree_perimee(self) -> None:
        stale = KNOWN_ORPHAN_METHODS - self.a.orphans
        self.assertFalse(
            stale,
            msg=(
                f"{len(stale)} entree(s) KNOWN_ORPHAN_METHODS perimee(s) : "
                f"{sorted(stale)}\n"
                "Ces methodes sont desormais consommees par le JS (bravo) ou "
                "ont ete supprimees/renommees. La liste ne peut que RETRECIR "
                "(Phase 5 PLAN_VERIF_TOTALE.md) : retirer ces entrees de "
                "tests/test_contract_facades.py."
            ),
        )

    # -- (2) M2 : homonymes _X_impl god-class / support --

    def test_homonym_impls_pas_de_nouvelle_paire(self) -> None:
        new = self.a.homonyms - KNOWN_HOMONYM_IMPLS
        lines = [
            f"  - {n} : CineSortApi (cinesort_api.py:{self.a.god_impls[n]}) ET {', '.join(self.a.support_funcs[n])}"
            for n in sorted(new)
        ]
        self.assertFalse(
            new,
            msg=(
                f"{len(new)} NOUVELLE(S) paire(s) homonyme(s) _X_impl "
                "god-class/support :\n" + "\n".join(lines) + "\n\n"
                "Deux implementations portant le meme nom divergent avec le "
                "temps (cf m2_facades_impl.json 'homonyms'). Correction : "
                "renommer la fonction support (ou la methode god), OU faire "
                "deleguer la god-class vers le twin support puis supprimer le "
                "corps duplique. NE PAS ajouter a KNOWN_HOMONYM_IMPLS sans "
                "decision de revue."
            ),
        )

    def test_homonym_impls_pas_dentree_perimee(self) -> None:
        stale = KNOWN_HOMONYM_IMPLS - self.a.homonyms
        self.assertFalse(
            stale,
            msg=(
                f"{len(stale)} entree(s) KNOWN_HOMONYM_IMPLS perimee(s) : "
                f"{sorted(stale)}\n"
                "La paire god/support n'existe plus (dedoublonnee ou renommee). "
                "Retirer ces entrees : la liste ne peut que RETRECIR."
            ),
        )

    # -- (3) M2 : exposition multi-facade --

    def test_multi_facade_pas_de_nouvelle_exposition(self) -> None:
        computed = self.a.multi_facade
        new = {m: owners for m, owners in computed.items() if KNOWN_MULTI_FACADE.get(m) != owners}
        lines = [f"  - {m} exposee sur : {', '.join(owners)}" for m, owners in sorted(new.items())]
        self.assertFalse(
            new,
            msg=(
                f"{len(new)} exposition(s) multi-facade nouvelle(s) ou "
                "modifiee(s) :\n" + "\n".join(lines) + "\n\n"
                "Une methode publique ne doit vivre que sur UNE facade "
                "(1 bounded context = 1 endpoint canonique, cf "
                "m2_facades_impl.json 'multi_facade_methods'). Correction : "
                "garder la methode sur sa facade canonique et renommer/retirer "
                "l'autre exposition. Seules les 3 paires historiques "
                "quality/settings (get_profiles, save_profile, "
                "set_active_profile) sont tolerees."
            ),
        )

    def test_multi_facade_pas_dentree_perimee(self) -> None:
        stale = {m: owners for m, owners in KNOWN_MULTI_FACADE.items() if self.a.multi_facade.get(m) != owners}
        self.assertFalse(
            stale,
            msg=(
                f"{len(stale)} entree(s) KNOWN_MULTI_FACADE perimee(s) : "
                f"{sorted(stale)}\n"
                "L'exposition double a ete resorbee (ou les owners ont change). "
                "Mettre a jour/retirer ces entrees : la liste ne peut que "
                "RETRECIR."
            ),
        )

    # -- (4) M2 : classes facade jamais instanciees --

    def test_facades_non_instanciees_pas_de_nouvelle(self) -> None:
        new = self.a.uninstantiated - KNOWN_UNINSTANTIATED_FACADES
        lines = [f"  - {c} ({self.a.facade_classes[c]['file']})" for c in sorted(new)]
        self.assertFalse(
            new,
            msg=(
                f"{len(new)} classe(s) *Facade jamais instanciee(s) dans "
                "cinesort/ :\n" + "\n".join(lines) + "\n\n"
                "Une facade non instanciee est du code mort non expose en REST "
                "(cf m2_facades_impl.json 'facade_instantiations'). Correction : "
                "l'instancier dans CineSortApi.__init__ + l'ajouter a "
                "_FACADE_ATTR_NAMES (rest_server.py), OU la supprimer. Seule "
                "SimilarFilmsFacade est toleree (dette assumee)."
            ),
        )

    def test_facades_non_instanciees_pas_dentree_perimee(self) -> None:
        computed = self.a.uninstantiated
        stale = {c for c in KNOWN_UNINSTANTIATED_FACADES if c not in computed}
        self.assertFalse(
            stale,
            msg=(
                f"{len(stale)} entree(s) KNOWN_UNINSTANTIATED_FACADES "
                f"perimee(s) : {sorted(stale)}\n"
                "La classe est desormais instanciee (cablee) ou supprimee. "
                "Retirer ces entrees : la liste ne peut que RETRECIR."
            ),
        )


if __name__ == "__main__":
    unittest.main()
