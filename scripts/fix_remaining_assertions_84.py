"""Fix toutes les assertions restantes en bulk pour PR 10.

Patterns traites :
- hasattr(api, "X") -> hasattr(api.facade, "X")
- self.assertIn("def X", py_src) -> self.assertIn("def _X_impl", py_src)
- api.X.return_value -> api.facade.X.return_value (pour les mocks)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

METHOD_TO_FACADE = {
    # Run
    "start_plan": "run", "get_status": "run", "get_plan": "run",
    "export_run_report": "run", "cancel_run": "run",
    "build_apply_preview": "run", "list_apply_history": "run",
    # Settings
    "get_settings": "settings", "save_settings": "settings", "set_locale": "settings",
    "restart_api_server": "settings", "reset_all_user_data": "settings",
    "get_user_data_size": "settings",
    # Quality
    "get_quality_profile": "quality", "save_quality_profile": "quality",
    "reset_quality_profile": "quality", "export_quality_profile": "quality",
    "import_quality_profile": "quality", "get_quality_presets": "quality",
    "apply_quality_preset": "quality", "simulate_quality_preset": "quality",
    "get_quality_report": "quality", "analyze_quality_batch": "quality",
    "save_custom_quality_preset": "quality", "get_custom_rules_templates": "quality",
    "get_custom_rules_catalog": "quality", "validate_custom_rules": "quality",
    "get_perceptual_report": "quality", "get_perceptual_details": "quality",
    "analyze_perceptual_batch": "quality", "compare_perceptual": "quality",
    "submit_score_feedback": "quality", "delete_score_feedback": "quality",
    "get_calibration_report": "quality",
    # Integrations
    "test_tmdb_key": "integrations", "get_tmdb_posters": "integrations",
    "test_jellyfin_connection": "integrations", "get_jellyfin_libraries": "integrations",
    "get_jellyfin_sync_report": "integrations", "test_plex_connection": "integrations",
    "get_plex_libraries": "integrations", "get_plex_sync_report": "integrations",
    "test_radarr_connection": "integrations", "get_radarr_status": "integrations",
    "request_radarr_upgrade": "integrations",
    # Library
    "get_library_filtered": "library", "get_smart_playlists": "library",
    "save_smart_playlist": "library", "delete_smart_playlist": "library",
    "get_scoring_rollup": "library", "get_film_full": "library",
    "get_film_history": "library", "list_films_with_history": "library",
    "export_full_library": "library",
}


def fix_file(path: Path, dry_run: bool = False) -> int:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    total = 0
    new_content = content
    for method, facade in METHOD_TO_FACADE.items():
        # Pattern 1 : hasattr(api, "method") -> hasattr(api.facade, "method")
        pat = re.compile(rf'hasattr\(\s*api\s*,\s*"({re.escape(method)})"\s*\)')
        new_content, c = pat.subn(rf'hasattr(api.{facade}, "{method}")', new_content)
        total += c

        # Pattern 2 : self.assertIn("def method", X) -> self.assertIn("def _method_impl", X)
        pat = re.compile(rf'assertIn\(\s*"def ({re.escape(method)})"')
        new_content, c = pat.subn(rf'assertIn("def _{method}_impl"', new_content)
        total += c

        # Pattern 3 : api.method.return_value -> api.facade.method.return_value
        pat = re.compile(rf'\bapi\.({re.escape(method)})\.return_value')
        new_content, c = pat.subn(rf'api.{facade}.{method}.return_value', new_content)
        total += c

        # Pattern 4 : api.method.side_effect -> api.facade.method.side_effect
        pat = re.compile(rf'\bapi\.({re.escape(method)})\.side_effect')
        new_content, c = pat.subn(rf'api.{facade}.{method}.side_effect', new_content)
        total += c

    if total > 0 and not dry_run:
        path.write_text(new_content, encoding="utf-8")
    return total


def main(apply: bool) -> int:
    total = 0
    changed = 0
    for path in sorted(Path("tests").rglob("*.py")):
        n = fix_file(path, dry_run=not apply)
        if n > 0:
            changed += 1
            total += n
            print(f"  [{n}x] {path}")
    print(f"\nTotal : {total} remplacements dans {changed} fichier(s)")
    return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    sys.exit(main(apply))
