"""Genere docs/api/ENDPOINTS.md via introspection de CineSortApi.

V3-06 (Polish Total v7.7.0, mai 2026) — resout R4-DOC-2.

Lance ce script apres tout changement d'API publique pour regenerer la doc :

    .venv313/Scripts/python.exe scripts/gen_endpoints_doc.py

Le script :
- introspect `cinesort.ui.api.cinesort_api.CineSortApi`
- filtre les `_EXCLUDED_METHODS` definis dans `cinesort.infra.rest_server`
- regroupe les endpoints en 8 categories metier
- genere `docs/api/ENDPOINTS.md` avec signatures, docstrings, exemples curl
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

from cinesort.infra.rest_server import _EXCLUDED_METHODS  # noqa: E402
from cinesort.ui.api.cinesort_api import CineSortApi  # noqa: E402

# --- Categorisation metier des endpoints ---------------------------------
# Chaque endpoint est associe a une categorie. Tout endpoint non liste
# tombe dans "Divers" (la generation echoue avec un warning si trop d'orphelins).
_CATEGORIES: List[Tuple[str, List[str]]] = [
    (
        "1. Configuration & Settings",
        [
            "get_settings",
            "save_settings",
            "get_server_info",
            "get_log_paths",
            "restart_api_server",
            "get_event_ts",
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
            "undo_last_apply_preview",
            "undo_by_row_preview",
            "undo_selected_rows",
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
            "export_shareable_profile",
            "import_shareable_profile",
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
            "get_probe",
            "get_probe_tools_status",
            "auto_install_probe_tools",
            "install_probe_tools",
            "update_probe_tools",
            "recheck_probe_tools",
            "set_probe_tool_paths",
            "get_tools_status",
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
            "test_email_report",
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
            "get_naming_presets",
            "preview_naming_template",
            "export_run_report",
            "export_run_nfo",
            "get_auto_approved_summary",
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
            "reset_incremental_cache",
            "reset_all_user_data",
            "get_user_data_size",
            "test_reset",
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
}

# Exemples curl populaires (10 endpoints critiques).
_EXAMPLES: List[Dict[str, str]] = [
    {
        "title": "1. Lancer un scan",
        "method": "start_plan",
        "body": '{"settings": {"sources": ["D:/Films"], "destination": "D:/Library", "tmdb_key": "***"}}',
        "response": '{"ok": true, "run_id": "20260504_120000_001"}',
    },
    {
        "title": "2. Recuperer les settings actuels",
        "method": "get_settings",
        "body": "{}",
        "response": '{"ok": true, "data": {"sources": [...], "destination": "...", ...}}',
    },
    {
        "title": "3. Sauvegarder de nouveaux settings",
        "method": "save_settings",
        "body": '{"settings": {"destination": "D:/NewLibrary", "auto_apply_threshold": 90}}',
        "response": '{"ok": true}',
    },
    {
        "title": "4. Suivre la progression d'un run",
        "method": "get_status",
        "body": '{"run_id": "20260504_120000_001", "last_log_index": 0}',
        "response": '{"ok": true, "status": "running", "progress": 42, "logs": [...]}',
    },
    {
        "title": "5. Recuperer le plan complet d'un run",
        "method": "get_plan",
        "body": '{"run_id": "20260504_120000_001"}',
        "response": '{"ok": true, "rows": [...], "stats": {...}}',
    },
    {
        "title": "6. Appliquer les decisions de validation",
        "method": "apply",
        "body": '{"run_id": "20260504_120000_001", "decisions": {"row_id_1": {"approved": true}}, "dry_run": false, "quarantine_unapproved": true}',
        "response": '{"ok": true, "applied_count": 42, "errors": []}',
    },
    {
        "title": "7. Annuler la derniere operation apply",
        "method": "undo_last_apply",
        "body": "{}",
        "response": '{"ok": true, "undone_count": 42}',
    },
    {
        "title": "8. Tester la cle TMDb",
        "method": "test_tmdb_key",
        "body": '{"api_key": "abcd1234"}',
        "response": '{"ok": true, "valid": true}',
    },
    {
        "title": "9. Tester une connexion Jellyfin",
        "method": "test_jellyfin_connection",
        "body": '{"url": "http://jellyfin.local:8096", "api_key": "***"}',
        "response": '{"ok": true, "version": "10.9.6"}',
    },
    {
        "title": "10. Recuperer le dashboard d'un run",
        "method": "get_dashboard",
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
    """Retourne les methodes publiques exposees au REST."""
    methods: Dict[str, Callable[..., Any]] = {}
    for name in dir(api):
        if name.startswith("_"):
            continue
        if name in _EXCLUDED_METHODS:
            continue
        attr = getattr(api, name, None)
        if callable(attr):
            methods[name] = attr
    return methods


def _categorize(methods: Dict[str, Callable[..., Any]]) -> List[Tuple[str, List[str]]]:
    """Retourne (categorie, [methods]) ; ajoute 'Divers' pour les orphelins."""
    seen: set[str] = set()
    grouped: List[Tuple[str, List[str]]] = []
    for cat_name, cat_methods in _CATEGORIES:
        present = [m for m in cat_methods if m in methods]
        for m in present:
            seen.add(m)
        if present:
            grouped.append((cat_name, present))
    orphans = sorted(name for name in methods if name not in seen)
    if orphans:
        grouped.append((f"{len(_CATEGORIES) + 1}. Divers (a categoriser)", orphans))
    return grouped


def _render_method(name: str, method: Callable[..., Any]) -> str:
    """Genere le bloc Markdown d'un endpoint."""
    sig = _format_signature(method)
    doc = (method.__doc__ or "").strip()
    if doc:
        first_line = doc.splitlines()[0].strip()
    else:
        first_line = "_(pas de docstring)_"
    return f"#### `POST /api/{name}`\n\n**Signature** : `{name}{sig}`\n\n**Description** : {first_line}\n"


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


def generate_markdown(api: Any) -> str:
    """Construit le contenu Markdown complet de docs/api/ENDPOINTS.md."""
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
    out.append("- **Methode HTTP** : `POST /api/{method_name}` avec body JSON")
    out.append("- **Auth** : `Authorization: Bearer <token>` (token configure dans les Reglages)")
    out.append('- **Format reponse** : `{"ok": true, ...}` ou `{"ok": false, "message": "..."}`')
    out.append("- **Endpoints publics** : `GET /api/health` (sans auth) et `GET /api/spec` (OpenAPI)")
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
    content = generate_markdown(api)
    output = _PROJECT_ROOT / "docs" / "api" / "ENDPOINTS.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    line_count = content.count("\n") + 1
    methods_count = len(_collect_methods(api))
    print(f"OK : {output.relative_to(_PROJECT_ROOT)} ecrit ({methods_count} endpoints, {line_count} lignes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
