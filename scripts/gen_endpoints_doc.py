"""Genere docs/api/ENDPOINTS.md via introspection de CineSortApi.

V3-06 (Polish Total v7.7.0, mai 2026) — resout R4-DOC-2.

Audit 2026-08-31, lot « endpoints » (constats #22, #23, #24, #30, #32, #38) :
ce script reimplementait la seule « Pass 1 » de `rest_server._get_api_methods`
(methodes directes sur `CineSortApi`), desactivee par defaut depuis P0 #233. Il
voyait donc **0** route la ou le dispatcher en servait **172**, et la doc
committee annoncait « Total endpoints publics : 1 ». La surface REST etait
encodee deux fois ; elle ne l'est plus.

Lance ce script apres tout changement d'API publique pour regenerer la doc :

    .venv313/Scripts/python.exe scripts/gen_endpoints_doc.py

Le script :
- demande ses routes a `rest_server._get_api_methods` — la MEME fonction que le
  dispatcher et que le log de demarrage du serveur, pour qu'un seul nombre
  d'endpoints existe
- regroupe les endpoints en 9 categories metier ; ce qui n'y figure pas est
  regroupe par facade, jamais laisse de cote
- genere `docs/api/ENDPOINTS.md` avec signatures, docstrings, exemples curl
- ECHOUE (message sur stderr, code retour 1, aucun fichier ecrit) si une donnee
  curatee de ce fichier — `_CATEGORIES` ou `_EXAMPLES` — designe un endpoint que
  le dispatcher ne sert pas
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# Ajout du root projet au sys.path pour permettre l'import "cinesort.*"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from cinesort.infra.rest_server import (  # noqa: E402
    _EXCLUDED_METHODS,
    _FACADE_SEPARATOR,
    _get_api_methods,
)
from cinesort.ui.api.cinesort_api import CineSortApi  # noqa: E402

# --- Categorisation metier des endpoints ---------------------------------
# Chaque route est associee a une categorie via son NOM DE METHODE, cote droit
# du chemin "{facade}/{methode}". Une route dont le nom n'est liste nulle part
# ici n'est pas perdue : elle atterrit dans "Autres endpoints — facade `X`".
#
# GARDE (implemente par `_verifier_donnees_curatees`, appele par `main`) : un
# nom liste ici, ou un exemple curl de `_EXAMPLES`, qui ne correspond a AUCUNE
# route servie fait ECHOUER la generation — message sur stderr, code retour 1,
# et le fichier de doc n'est pas ecrit. C'est ce garde que le commentaire
# precedent annoncait sans l'avoir jamais implemente (constat d'audit #38) :
# il mordait deja au moment de son ajout, sur `test_reset` (retire du REST par
# #483) et sur les 10 exemples curl, tous perimes.
_CATEGORIES: List[Tuple[str, List[str]]] = [
    (
        "1. Configuration & Settings",
        [
            "get_settings",
            "save_settings",
            "get_server_info",
            "get_log_paths",
            "restart_api_server",
        ],
    ),
    (
        "2. Scan & Plan",
        [
            "start_plan",
            "get_status",
            "cancel_run",
            "get_plan",
            "load_validation",
            "save_validation",
            "validate_dropped_path",
            "get_sidebar_counters",
        ],
    ),
    (
        "3. Apply & Undo",
        [
            "apply",
            "build_apply_preview",
            "list_apply_history",
            "export_apply_audit",
            "undo_last_apply",
            "get_cleanup_residual_preview",
        ],
    ),
    (
        "4. Quality & Scoring",
        [
            "analyze_quality_batch",
            "get_quality_report",
            "get_quality_profile",
            "save_quality_profile",
            "reset_quality_profile",
            "get_quality_presets",
            "apply_quality_preset",
            "save_custom_quality_preset",
            "simulate_quality_preset",
            "export_quality_profile",
            "import_quality_profile",
            "get_calibration_report",
            "get_scoring_rollup",
            "submit_score_feedback",
            "delete_score_feedback",
            "get_custom_rules_catalog",
            "get_custom_rules_templates",
            "validate_custom_rules",
        ],
    ),
    (
        "5. Perceptual analysis",
        [
            "analyze_perceptual_batch",
            "get_perceptual_report",
            "compare_perceptual",
        ],
    ),
    (
        "6. Probe tools",
        [
            "get_probe_tools_status",
            "auto_install_probe_tools",
        ],
    ),
    (
        "7. Integrations (TMDb / Jellyfin / Plex / Radarr)",
        [
            "test_tmdb_key",
            "get_tmdb_posters",
            "test_jellyfin_connection",
            "get_jellyfin_libraries",
            "get_jellyfin_sync_report",
            "test_plex_connection",
            "get_plex_libraries",
            "get_plex_sync_report",
            "test_radarr_connection",
            "get_radarr_status",
            "request_radarr_upgrade",
            "import_watchlist",
        ],
    ),
    (
        "8. Library, Films & UI",
        [
            "get_library_filtered",
            "get_film_full",
            "get_film_history",
            "list_films_with_history",
            "get_dashboard",
            "get_dashboard_qr",
            "get_global_stats",
            "get_smart_playlists",
            "save_smart_playlist",
            "delete_smart_playlist",
            "export_run_report",
            "export_run_nfo",
            "check_duplicates",
        ],
    ),
    (
        "9. Notifications & System",
        [
            "get_notifications",
            "get_notifications_unread_count",
            "mark_notification_read",
            "mark_all_notifications_read",
            "dismiss_notification",
            "clear_notifications",
            "check_for_updates",
            "get_update_info",
            "open_logs_folder",
            "reset_all_user_data",
            "get_user_data_size",
            # `test_reset` a ete retiree ici le 2026-08-31 : #483 l'a ajoutee a
            # `_EXCLUDED_METHODS`, donc le dispatcher ne la sert plus. C'etait
            # pourtant le SEUL endpoint que la doc committee documentait encore.
            "is_demo_mode_active",
            "start_demo_mode",
            "stop_demo_mode",
        ],
    ),
]

# Documentation des exclusions (raison metier).
_EXCLUSION_REASONS: Dict[str, str] = {
    "open_path": "Prend un chemin arbitraire — vector path-traversal en supervision distante.",
    "log_api_exception": "Helper interne logging, pas un endpoint metier.",
    "log": "Helper interne logging (frontend → backend).",
    "progress": "Helper interne progress reporting (frontend → backend).",
    "test_reset": (
        "Remet l'application dans un etat propre (efface les runs en memoire) — #483."
        " Reste appelable par les E2E via l'objet Python et le pont pywebview,"
        " qui ne passent pas par ce dispatcher."
    ),
}

# Exemples curl populaires (10 endpoints critiques).
#
# `method` porte la ROUTE COMPLETE, "{facade}/{methode}", telle que le
# dispatcher l'expose. Constat d'audit #24 : les 10 exemples visaient les
# chemins directs ("/api/start_plan"), morts depuis que Pass 1 est desactivee
# — le serveur y repond 410 Gone. `_verifier_donnees_curatees` refuse desormais
# de generer la doc si l'une de ces routes n'est pas servie.
_EXAMPLES: List[Dict[str, str]] = [
    {
        "title": "1. Lancer un scan",
        "method": "run/start_plan",
        "body": '{"settings": {"sources": ["D:/Films"], "destination": "D:/Library", "tmdb_key": "***"}}',
        "response": '{"ok": true, "run_id": "20260504_120000_001"}',
    },
    {
        "title": "2. Recuperer les settings actuels",
        "method": "settings/get_settings",
        "body": "{}",
        "response": '{"ok": true, "data": {"sources": [...], "destination": "...", ...}}',
    },
    {
        "title": "3. Sauvegarder de nouveaux settings",
        "method": "settings/save_settings",
        "body": '{"settings": {"destination": "D:/NewLibrary", "auto_apply_threshold": 90}}',
        "response": '{"ok": true}',
    },
    {
        "title": "4. Suivre la progression d'un run",
        "method": "run/get_status",
        "body": '{"run_id": "20260504_120000_001", "last_log_index": 0}',
        "response": '{"ok": true, "status": "running", "progress": 42, "logs": [...]}',
    },
    {
        "title": "5. Recuperer le plan complet d'un run",
        "method": "run/get_plan",
        "body": '{"run_id": "20260504_120000_001"}',
        "response": '{"ok": true, "rows": [...], "stats": {...}}',
    },
    {
        "title": "6. Appliquer les decisions de validation",
        "method": "run/apply",
        "body": '{"run_id": "20260504_120000_001", "decisions": {"row_id_1": {"approved": true}}, "dry_run": false, "quarantine_unapproved": true}',
        "response": '{"ok": true, "applied_count": 42, "errors": []}',
    },
    {
        "title": "7. Annuler la derniere operation apply",
        "method": "run/undo_last_apply",
        "body": "{}",
        "response": '{"ok": true, "undone_count": 42}',
    },
    {
        "title": "8. Tester la cle TMDb",
        "method": "integrations/test_tmdb_key",
        "body": '{"api_key": "abcd1234"}',
        "response": '{"ok": true, "valid": true}',
    },
    {
        "title": "9. Tester une connexion Jellyfin",
        "method": "integrations/test_jellyfin_connection",
        "body": '{"url": "http://jellyfin.local:8096", "api_key": "***"}',
        "response": '{"ok": true, "version": "10.9.6"}',
    },
    {
        "title": "10. Recuperer le dashboard d'un run",
        "method": "run/get_dashboard",
        "body": '{"run_id": "latest"}',
        "response": '{"ok": true, "kpis": {...}, "distribution": [...], "anomalies": [...]}',
    },
]


def _format_signature(method: Callable[..., Any]) -> str:
    """Formate la signature d'une methode pour affichage Markdown.

    Retire `self`, simplifie les annotations typing.* en formes lisibles.
    """
    sig = inspect.signature(method)
    parts: List[str] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        annotation = ""
        if param.annotation is not inspect.Parameter.empty:
            ann = str(param.annotation).strip("'\"")
            # Normalisation : "typing.Dict[str, Any]" → "Dict[str, Any]"
            ann = ann.replace("typing.", "")
            annotation = f": {ann}"
        default = ""
        if param.default is not inspect.Parameter.empty:
            default = f" = {param.default!r}"
        parts.append(f"{name}{annotation}{default}")
    args = ", ".join(parts)
    ret = ""
    if sig.return_annotation is not inspect.Parameter.empty:
        ret_ann = str(sig.return_annotation).strip("'\"").replace("typing.", "")
        ret = f" -> {ret_ann}"
    return f"({args}){ret}"


def _collect_methods(api: Any) -> Dict[str, Callable[..., Any]]:
    """Retourne les routes REST servies — SOURCE UNIQUE.

    Delegue a `rest_server._get_api_methods`, c'est-a-dire exactement la table
    que le dispatcher utilise pour router et que le serveur compte dans son log
    de demarrage (`REST API started on ... (%d endpoints)`).

    Ce corps reimplementait auparavant la seule Pass 1 de cette fonction. Comme
    Pass 1 est desactivee par defaut (P0 #233), il rendait 0 route quand
    `_get_api_methods` en rendait 172 : deux encodages de la meme surface, et
    deux nombres livres a l'utilisateur (constats #22 et #32).
    """
    return _get_api_methods(api)


def _method_name(route: str) -> str:
    """Nom de methode d'une route : "run/start_plan" -> "start_plan"."""
    return route.rsplit(_FACADE_SEPARATOR, 1)[-1]


def _facade_name(route: str) -> str:
    """Facade d'une route, ou "" pour une route directe (Pass 1 re-activee)."""
    if _FACADE_SEPARATOR not in route:
        return ""
    return route.split(_FACADE_SEPARATOR, 1)[0]


def _verifier_donnees_curatees(methods: Dict[str, Callable[..., Any]]) -> List[str]:
    """Confronte les donnees ECRITES ICI aux routes REELLEMENT servies.

    Retourne la liste des problemes (vide = tout est a jour). C'est le garde que
    l'en-tete de ce fichier annonce ; `main` l'applique avant d'ecrire quoi que
    ce soit. Deux sources sont verifiees :

    - `_CATEGORIES` : un nom de methode categorise qui n'est plus servi signale
      une doc qui promet un endpoint disparu (cas mesure : `test_reset`, sortie
      du REST par #483) ;
    - `_EXAMPLES` : un exemple curl vers une route absente donne au lecteur une
      commande qui repondra 404 ou 410 (cas mesure : 10 sur 10).
    """
    servis = {_method_name(route) for route in methods}
    problemes: List[str] = []
    for cat_name, cat_methods in _CATEGORIES:
        for name in cat_methods:
            if name not in servis:
                problemes.append(f"categorie « {cat_name} » : « {name} » n'est servi par aucune route REST")
    for example in _EXAMPLES:
        route = example["method"]
        if route not in methods:
            problemes.append(f"exemple curl « {example['title']} » : la route « {route} » n'est pas servie")
    return problemes


def _categorize(methods: Dict[str, Callable[..., Any]]) -> List[Tuple[str, List[str]]]:
    """Retourne (categorie, [routes]).

    Les routes dont le nom de methode figure dans `_CATEGORIES` gardent leur
    categorie metier ; les autres sont regroupees par facade. Aucune route n'est
    laissee de cote : la somme des sections egale toujours `len(methods)`.
    """
    par_nom: Dict[str, List[str]] = {}
    for route in sorted(methods):
        par_nom.setdefault(_method_name(route), []).append(route)

    seen: set[str] = set()
    grouped: List[Tuple[str, List[str]]] = []
    for cat_name, cat_methods in _CATEGORIES:
        present: List[str] = []
        for name in cat_methods:
            for route in par_nom.get(name, []):
                if route in seen:
                    # Un meme nom liste dans deux categories ne doit pas produire
                    # deux blocs pour la meme route : la premiere categorie gagne.
                    continue
                present.append(route)
                seen.add(route)
        if present:
            grouped.append((cat_name, present))

    grouped.extend(_group_by_facade([r for r in sorted(methods) if r not in seen]))
    return grouped


def _group_by_facade(routes: List[str]) -> List[Tuple[str, List[str]]]:
    """Sections de repli pour les routes sans categorie metier."""
    par_facade: Dict[str, List[str]] = {}
    for route in routes:
        par_facade.setdefault(_facade_name(route), []).append(route)

    sections: List[Tuple[str, List[str]]] = []
    index = len(_CATEGORIES)
    for facade in sorted(par_facade):
        index += 1
        libelle = f"facade `{facade}`" if facade else "routes directes (hors facade)"
        sections.append((f"{index}. Autres endpoints — {libelle}", par_facade[facade]))
    return sections


def _render_method(route: str, method: Callable[..., Any]) -> str:
    """Genere le bloc Markdown d'un endpoint (`route` = "{facade}/{methode}")."""
    sig = _format_signature(method)
    doc = (method.__doc__ or "").strip()
    if doc:
        first_line = doc.splitlines()[0].strip()
    else:
        first_line = "_(pas de docstring)_"
    name = _method_name(route)
    return f"#### `POST /api/{route}`\n\n**Signature** : `{name}{sig}`\n\n**Description** : {first_line}\n"


def _render_examples() -> str:
    blocks: List[str] = []
    for ex in _EXAMPLES:
        blocks.append(
            f"### {ex['title']}\n\n"
            "```bash\n"
            f"curl -X POST http://localhost:8642/api/{ex['method']} \\\n"
            '  -H "Authorization: Bearer YOUR_TOKEN" \\\n'
            '  -H "Content-Type: application/json" \\\n'
            f"  -d '{ex['body']}'\n"
            "```\n\n"
            f"**Reponse** : `{ex['response']}`\n"
        )
    return "\n".join(blocks)


def _render_exclusions() -> str:
    lines: List[str] = []
    for name in sorted(_EXCLUDED_METHODS):
        reason = _EXCLUSION_REASONS.get(name, "(raison non documentee)")
        lines.append(f"- `{name}` — {reason}")
    return "\n".join(lines)


def generate_markdown(api: Any, methods: Dict[str, Callable[..., Any]] | None = None) -> str:
    """Construit le contenu Markdown complet de docs/api/ENDPOINTS.md.

    `methods` permet a `main` de ne MESURER QU'UNE FOIS : le nombre imprime sur
    la console, celui ecrit dans la doc et la liste des blocs rendus viennent
    alors du meme dictionnaire.
    """
    if methods is None:
        methods = _collect_methods(api)
    grouped = _categorize(methods)

    out: List[str] = []
    out.append("# CineSort REST API — Endpoints\n")
    out.append(
        "> Auto-genere depuis l'introspection de `CineSortApi` (V3-06, mai 2026).\n"
        "> Regenerer apres changement d'API : `python scripts/gen_endpoints_doc.py`\n"
    )

    out.append("## Vue d'ensemble\n")
    out.append(f"- **Total endpoints publics** : {len(methods)}")
    out.append("- **Methode HTTP** : `POST /api/{facade}/{method_name}` avec body JSON")
    out.append(
        "- **Chemins directs `POST /api/{method_name}`** : desactives par defaut"
        " (P0 #233) — le serveur repond `410 Gone` avec"
        " `Use /api/<facade>/<method> instead`"
    )
    out.append("- **Auth** : `Authorization: Bearer <token>` (token configure dans les Reglages)")
    out.append('- **Format reponse** : `{"ok": true, ...}` ou `{"ok": false, "message": "..."}`')
    # Lot 2 (2026-08-31) : `GET /api/spec` n'est PLUS public. Elle rendait
    # 80 182 octets — la carte complete des endpoints ci-dessous — a un
    # appelant sans jeton. Seule `/api/health` reste ouverte : le boot du
    # dashboard et les sondes e2e l'interrogent avant d'avoir un jeton.
    out.append("- **Endpoint public** : `GET /api/health` (sans auth)")
    out.append("- **`GET /api/spec`** (OpenAPI 3.0.3) : exige `Authorization: Bearer <token>`, comme les POST")
    out.append("- **Body max** : 16 MB ; **Rate limit auth** : 5 echecs / 60s par IP\n")

    out.append("## Endpoints groupes par categorie\n")
    for cat_name, names in grouped:
        out.append(f"### {cat_name}\n")
        for name in names:
            out.append(_render_method(name, methods[name]))
        out.append("")

    out.append("## Endpoints exclus du REST\n")
    out.append(
        "Les methodes suivantes existent sur `CineSortApi` mais sont volontairement"
        " filtrees par `_EXCLUDED_METHODS` (`cinesort/infra/rest_server.py`) :\n"
    )
    out.append(_render_exclusions())
    out.append("")

    out.append("## Exemples requete / reponse\n")
    out.append("Tous les exemples supposent que le serveur ecoute sur `localhost:8642`")
    out.append("et qu'un token Bearer valide est configure cote serveur.\n")
    out.append(_render_examples())

    out.append("---\n")
    out.append("_Genere par `scripts/gen_endpoints_doc.py` — ne pas editer manuellement._")
    out.append("_Pour regenerer : `.venv313/Scripts/python.exe scripts/gen_endpoints_doc.py`_\n")

    return "\n".join(out)


def main() -> int:
    api = CineSortApi()
    # UNE seule interrogation du dispatcher : le garde, le rendu et le compte
    # imprime partagent ce dictionnaire, donc ne peuvent pas diverger.
    methods = _collect_methods(api)

    problemes = _verifier_donnees_curatees(methods)
    if problemes:
        sys.stderr.write(
            f"[gen_endpoints_doc] WARNING : {len(problemes)} donnee(s) curatee(s) perimee(s)"
            " — generation ABANDONNEE, la doc n'a PAS ete ecrite.\n"
        )
        for probleme in problemes:
            sys.stderr.write(f"  - {probleme}\n")
        sys.stderr.write("Corrige `_CATEGORIES` / `_EXAMPLES` dans scripts/gen_endpoints_doc.py, puis relance.\n")
        return 1

    content = generate_markdown(api, methods)
    output = _PROJECT_ROOT / "docs" / "api" / "ENDPOINTS.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    line_count = content.count("\n") + 1
    print(f"OK : {output.relative_to(_PROJECT_ROOT)} ecrit ({len(methods)} endpoints, {line_count} lignes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
