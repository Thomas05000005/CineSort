"""Script one-shot pour PR 9 du #84 : migration JS frontend vers facade paths.

Remplace tous les `apiPost("X", ...)` et `testMethod: "X"` ou X est une methode
appartenant a une facade par sa version prefixee `facade/X`.

Usage :
    python scripts/migrate_js_to_facades_84.py --dry-run
    python scripts/migrate_js_to_facades_84.py --apply

Le mode --dry-run affiche les remplacements prevus sans modifier les fichiers.
Le mode --apply modifie effectivement les fichiers et affiche un resume.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Mapping methode_directe -> facade. Construit a partir des 5 facades du #84
# (cf cinesort/ui/api/facades/*.py).
METHOD_TO_FACADE: Dict[str, str] = {
    # RunFacade (7)
    "start_plan": "run",
    "get_status": "run",
    "get_plan": "run",
    "export_run_report": "run",
    "cancel_run": "run",
    "build_apply_preview": "run",
    "list_apply_history": "run",
    # SettingsFacade (6)
    "get_settings": "settings",
    "save_settings": "settings",
    "set_locale": "settings",
    "restart_api_server": "settings",
    "reset_all_user_data": "settings",
    "get_user_data_size": "settings",
    # QualityFacade (21)
    "get_quality_profile": "quality",
    "save_quality_profile": "quality",
    "reset_quality_profile": "quality",
    "export_quality_profile": "quality",
    "import_quality_profile": "quality",
    "get_quality_presets": "quality",
    "apply_quality_preset": "quality",
    "simulate_quality_preset": "quality",
    "get_quality_report": "quality",
    "analyze_quality_batch": "quality",
    "save_custom_quality_preset": "quality",
    "get_custom_rules_templates": "quality",
    "get_custom_rules_catalog": "quality",
    "validate_custom_rules": "quality",
    "get_perceptual_report": "quality",
    "get_perceptual_details": "quality",
    "analyze_perceptual_batch": "quality",
    "compare_perceptual": "quality",
    "submit_score_feedback": "quality",
    "delete_score_feedback": "quality",
    "get_calibration_report": "quality",
    # IntegrationsFacade (11)
    "test_tmdb_key": "integrations",
    "get_tmdb_posters": "integrations",
    "test_jellyfin_connection": "integrations",
    "get_jellyfin_libraries": "integrations",
    "get_jellyfin_sync_report": "integrations",
    "test_plex_connection": "integrations",
    "get_plex_libraries": "integrations",
    "get_plex_sync_report": "integrations",
    "test_radarr_connection": "integrations",
    "get_radarr_status": "integrations",
    "request_radarr_upgrade": "integrations",
    # LibraryFacade (9)
    "get_library_filtered": "library",
    "get_smart_playlists": "library",
    "save_smart_playlist": "library",
    "delete_smart_playlist": "library",
    "get_scoring_rollup": "library",
    "get_film_full": "library",
    "get_film_history": "library",
    "list_films_with_history": "library",
    "export_full_library": "library",
}


def _build_replacements_for_file(content: str) -> List[Tuple[str, str, int]]:
    """Retourne une liste de (old, new, count) representant les remplacements.

    Pour chaque methode, on cherche deux patterns :
    1. apiPost("method"...) ou apiPost('method'...)
       -> apiPost("facade/method"...) ou apiPost('facade/method'...)
    2. testMethod: "method" ou testMethod: 'method'
       -> testMethod: "facade/method" ou testMethod: 'facade/method'

    Retourne la liste des modifications a faire (sans appliquer).
    """
    replacements: List[Tuple[str, str, int]] = []
    for method, facade in METHOD_TO_FACADE.items():
        prefixed = f"{facade}/{method}"

        # Pattern 1 : apiPost("method"...) - double quotes
        old1 = f'apiPost("{method}"'
        new1 = f'apiPost("{prefixed}"'
        if old1 in content:
            count = content.count(old1)
            replacements.append((old1, new1, count))

        # Pattern 1bis : apiPost('method'...) - single quotes
        old1q = f"apiPost('{method}'"
        new1q = f"apiPost('{prefixed}'"
        if old1q in content:
            count = content.count(old1q)
            replacements.append((old1q, new1q, count))

        # Pattern 2 : testMethod: "method"
        old2 = f'testMethod: "{method}"'
        new2 = f'testMethod: "{prefixed}"'
        if old2 in content:
            count = content.count(old2)
            replacements.append((old2, new2, count))

        # Pattern 2bis : testMethod: 'method'
        old2q = f"testMethod: '{method}'"
        new2q = f"testMethod: '{prefixed}'"
        if old2q in content:
            count = content.count(old2q)
            replacements.append((old2q, new2q, count))

        # Pattern 3 : _call("method"...) - wrapper qij-v5.js + qij.js
        old3 = f'_call("{method}"'
        new3 = f'_call("{prefixed}"'
        if old3 in content:
            count = content.count(old3)
            replacements.append((old3, new3, count))

        # Pattern 3bis : _call('method'...)
        old3q = f"_call('{method}'"
        new3q = f"_call('{prefixed}'"
        if old3q in content:
            count = content.count(old3q)
            replacements.append((old3q, new3q, count))

    return replacements


def _apply_replacements(content: str, replacements: List[Tuple[str, str, int]]) -> str:
    """Applique tous les remplacements au contenu."""
    for old, new, _count in replacements:
        content = content.replace(old, new)
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate JS frontend to facade paths (#84 PR 9)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--web-dir", default="web", help="Path to web/ directory")
    args = parser.parse_args()

    web_dir = Path(args.web_dir)
    if not web_dir.is_dir():
        print(f"ERREUR : {web_dir} introuvable", file=sys.stderr)
        return 1

    # Glob tous les .js (recursive)
    js_files = sorted(web_dir.rglob("*.js"))
    if not js_files:
        print(f"ERREUR : aucun .js trouve dans {web_dir}", file=sys.stderr)
        return 1

    print(f"Mode : {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Fichiers .js scannes : {len(js_files)}")
    print()

    total_files_changed = 0
    total_replacements = 0
    for path in js_files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"SKIP {path}: {exc}", file=sys.stderr)
            continue

        replacements = _build_replacements_for_file(content)
        if not replacements:
            continue

        total_files_changed += 1
        file_total = sum(c for _, _, c in replacements)
        total_replacements += file_total

        rel_path = path.relative_to(web_dir.parent) if path.is_absolute() else path
        print(f"{rel_path} : {file_total} remplacement(s)")
        for old, new, count in replacements:
            print(f"  [{count}x]  {old}  ->  {new}")

        if args.apply:
            new_content = _apply_replacements(content, replacements)
            path.write_text(new_content, encoding="utf-8")

    print()
    print(f"Total : {total_replacements} remplacements dans {total_files_changed} fichier(s)")
    if not args.apply:
        print("(dry-run : aucun fichier modifie. Relancer avec --apply pour appliquer.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
