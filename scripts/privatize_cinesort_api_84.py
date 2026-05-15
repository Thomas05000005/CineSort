"""Script one-shot pour PR 10 etape 2 du #84 : privatize les 54 methodes
publiques de CineSortApi qui appartiennent a une facade.

Rationale : apres PR 9, tous les call sites JS et Python passent par les
facades (api.run.X, api.settings.X, ...). Les methodes directes sur
CineSortApi sont desormais dead code public (facades delegent encore vers
elles, mais aucun caller externe ne les appelle directement).

Action : renommer les 54 methodes en `_X_impl` (private) pour :
1. Reduire l'API publique de CineSortApi (104 -> ~50 methodes publiques)
2. Faire echouer le dispatch REST `/api/start_plan` (intentionnel : seule
   la voie facade /api/run/start_plan survit)
3. Forcer toute regression future (caller direct) a etre detectee par le
   snapshot test

Modifications :
- cinesort/ui/api/cinesort_api.py : `def X(self,` -> `def _X_impl(self,`
- cinesort/ui/api/facades/*.py : `self._api.X(` -> `self._api._X_impl(`

Usage :
    python scripts/privatize_cinesort_api_84.py --dry-run
    python scripts/privatize_cinesort_api_84.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Memes 54 methodes que migrate_py_to_facades_84.py.
FACADE_METHODS = [
    # RunFacade (7)
    "start_plan",
    "get_status",
    "get_plan",
    "export_run_report",
    "cancel_run",
    "build_apply_preview",
    "list_apply_history",
    # SettingsFacade (6)
    "get_settings",
    "save_settings",
    "set_locale",
    "restart_api_server",
    "reset_all_user_data",
    "get_user_data_size",
    # QualityFacade (21)
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
    # IntegrationsFacade (11)
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
    # LibraryFacade (9)
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


CINESORT_API_PATH = Path("cinesort/ui/api/cinesort_api.py")
FACADES_DIR = Path("cinesort/ui/api/facades")


def _rename_method_in_cinesort_api(content: str, method: str) -> Tuple[str, int]:
    """Renomme la definition `def method(self,` en `def _method_impl(self,`."""
    private_name = f"_{method}_impl"
    pattern = re.compile(rf"^(\s+)def {re.escape(method)}\(", flags=re.MULTILINE)
    new_def = lambda m: f"{m.group(1)}def {private_name}("
    new_content, count = pattern.subn(new_def, content)
    return new_content, count


def _update_facade_delegations(content: str, method: str) -> Tuple[str, int]:
    """Dans une facade, remplace `self._api.X(` par `self._api._X_impl(`."""
    private_name = f"_{method}_impl"
    pattern = re.compile(rf"\bself\._api\.{re.escape(method)}\(")
    new_content, count = pattern.subn(f"self._api.{private_name}(", content)
    return new_content, count


def main() -> int:
    parser = argparse.ArgumentParser(description="Privatize 54 CineSortApi methods (#84 PR 10 step 2)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    args = parser.parse_args()

    if not CINESORT_API_PATH.is_file():
        print(f"ERREUR : {CINESORT_API_PATH} introuvable", file=sys.stderr)
        return 1
    if not FACADES_DIR.is_dir():
        print(f"ERREUR : {FACADES_DIR} introuvable", file=sys.stderr)
        return 1

    print(f"Mode : {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    # === Step 2a : Rename methods in cinesort_api.py ===
    api_content = CINESORT_API_PATH.read_text(encoding="utf-8")
    new_api_content = api_content
    api_renames: List[Tuple[str, int]] = []
    for method in FACADE_METHODS:
        new_api_content, count = _rename_method_in_cinesort_api(new_api_content, method)
        if count > 0:
            api_renames.append((method, count))
        elif count == 0:
            print(f"  WARN : {method} NOT found in cinesort_api.py")

    print(f"cinesort_api.py : {sum(c for _, c in api_renames)} methodes renommees")
    for method, count in api_renames:
        if count > 1:
            print(f"  WARN : {method} matched {count} times (expected 1)")

    if args.apply:
        CINESORT_API_PATH.write_text(new_api_content, encoding="utf-8")

    # === Step 2b : Update facade delegations ===
    print()
    facade_files = sorted(FACADES_DIR.glob("*.py"))
    total_facade_updates = 0
    for facade_path in facade_files:
        if facade_path.name in ("__init__.py", "_base.py"):
            continue  # ces fichiers ne contiennent pas de delegation
        content = facade_path.read_text(encoding="utf-8")
        new_content = content
        per_facade = 0
        for method in FACADE_METHODS:
            new_content, count = _update_facade_delegations(new_content, method)
            per_facade += count
        if per_facade > 0:
            total_facade_updates += per_facade
            print(f"  {facade_path.name} : {per_facade} delegations updated")
            if args.apply:
                facade_path.write_text(new_content, encoding="utf-8")

    print()
    print(f"Total : {sum(c for _, c in api_renames)} methodes renommees + {total_facade_updates} delegations updated")
    if not args.apply:
        print("(dry-run : aucun fichier modifie. Relancer avec --apply pour appliquer.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
