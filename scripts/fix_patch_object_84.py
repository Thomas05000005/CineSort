"""Script complementaire pour PR 10 du #84 : update patch.object refs.

Apres la privatisation des 54 methodes (X -> _X_impl), tous les
`patch.object(api, "X", ...)` doivent etre mis a jour.

Le script de migration py callers etait limite aux `<root>.X(...)` patterns.
Les patch.object strings sont des chaines (pas des attribute access), donc
manques.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

METHODS = [
    "start_plan",
    "get_status",
    "get_plan",
    "export_run_report",
    "cancel_run",
    "build_apply_preview",
    "list_apply_history",
    "get_settings",
    "save_settings",
    "set_locale",
    "restart_api_server",
    "reset_all_user_data",
    "get_user_data_size",
    "get_quality_profile",
    "save_quality_profile",
    "reset_quality_profile",
    "export_quality_profile",
    "import_quality_profile",
    "get_quality_presets",
    "apply_quality_preset",
    "simulate_quality_preset",
    "get_quality_report",
    "analyze_quality_batch",
    "save_custom_quality_preset",
    "get_custom_rules_templates",
    "get_custom_rules_catalog",
    "validate_custom_rules",
    "get_perceptual_report",
    "get_perceptual_details",
    "analyze_perceptual_batch",
    "compare_perceptual",
    "submit_score_feedback",
    "delete_score_feedback",
    "get_calibration_report",
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
    "get_library_filtered",
    "get_smart_playlists",
    "save_smart_playlist",
    "delete_smart_playlist",
    "get_scoring_rollup",
    "get_film_full",
    "get_film_history",
    "list_films_with_history",
    "export_full_library",
]


def main(apply: bool) -> int:
    total = 0
    for path in sorted(Path("tests").rglob("*.py")):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_content = content
        for m in METHODS:
            # patch.object(X, "method", ...) -> patch.object(X, "_method_impl", ...)
            pat = re.compile(rf'(patch\.object\([^,]+,\s*)"({re.escape(m)})"')
            new_content, count = pat.subn(rf'\1"_{m}_impl"', new_content)
            # patch.object(X, 'method', ...) - single quotes
            pat2 = re.compile(rf"(patch\.object\([^,]+,\s*)'({re.escape(m)})'")
            new_content, count2 = pat2.subn(rf"\1'_{m}_impl'", new_content)
            total += count + count2
        if new_content != content and apply:
            path.write_text(new_content, encoding="utf-8")
    print(f"Total : {total} patch.object refs migres")
    return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    sys.exit(main(apply))
