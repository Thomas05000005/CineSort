"""Script one-shot pour PR 10 du #84 : migration Python callers vers facade paths.

Remplace tous les `<obj>.X(...)` ou X est une methode appartenant a une facade
par sa version prefixee `<obj>.facade.X(...)`. Cible : tests/ + app.py +
cinesort/ sous-modules qui appellent directement les methodes legacy.

Patterns matches :
- api.start_plan(...) -> api.run.start_plan(...)
- self.api.get_settings() -> self.api.settings.get_settings()
- cls.api.X() -> cls.api.facade.X()
- backend_api.X() -> backend_api.facade.X()
- bridge.X() -> bridge.facade.X()
- target.X(...) -> patterns plus generaux si voulu

Usage :
    python scripts/migrate_py_to_facades_84.py --dry-run
    python scripts/migrate_py_to_facades_84.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Memes 54 methodes que migrate_js_to_facades_84.py.
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


# Noms d'objets connus qui sont des instances de CineSortApi (ou similaires).
# Pour eviter de matcher des objets aleatoires, on liste les patterns "safe".
# Exemples : api, self.api, cls.api, backend_api, bridge, _api, etc.
SAFE_ROOTS: List[str] = [
    r"\bapi",
    r"\bself\.api",
    r"\bcls\.api",
    r"\bself\._api",
    r"\bbackend_api",
    r"\bbridge",
    r"\b_api",
    r"\bself\.cs_api",
    r"\bcs_api",
]


def _build_pattern_for_method(method: str) -> re.Pattern[str]:
    """Construit un regex qui match <safe_root>.method( avec un identifier safe.

    Le regex match aussi le contexte autour pour eviter de toucher des chaines
    de caracteres ou des nom de tests (assertEqual etc.).
    """
    # Forme : (api|self.api|cls.api|...).method(
    # On capture le root pour pouvoir le reutiliser dans le remplacement.
    roots_alt = "|".join(SAFE_ROOTS)
    # Pattern : (root).method(
    # On utilise non-capture pour roots_alt, puis on rebuild le replacement
    # via la chaine matchee complete.
    pattern = re.compile(
        rf"(?P<root>(?:{roots_alt}))\.{re.escape(method)}\("
    )
    return pattern


def _migrate_file(path: Path, methods: Dict[str, str], dry_run: bool) -> int:
    """Migre un fichier. Retourne le nombre de remplacements."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0

    total = 0
    new_content = content
    for method, facade in methods.items():
        pattern = _build_pattern_for_method(method)

        def replace(match: re.Match[str]) -> str:
            root = match.group("root")
            return f"{root}.{facade}.{method}("

        new_content, count = pattern.subn(replace, new_content)
        total += count

    if total > 0 and not dry_run:
        path.write_text(new_content, encoding="utf-8")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Python callers to facade paths (#84 PR 10)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="Optional target file/dir (default: tests/, app.py, cinesort/)",
    )
    args = parser.parse_args()

    if args.target:
        targets = [Path(t) for t in args.target]
    else:
        targets = [Path("tests"), Path("app.py"), Path("cinesort")]

    # Fichiers a EXCLURE de la migration :
    # - facades/ : ces fichiers CONTIENNENT self._api.X(...) qui est intentionnel
    #   (sinon recursion infinie : facade.X -> self._api.run.X -> facade.X)
    # - cinesort_api.py : c'est la classe CineSortApi elle-meme, les self.X()
    #   internes sont des appels prives, pas un caller a migrer
    # - quality_simulator_support.py + similar : peuvent appeler api en interne
    EXCLUDE_RELATIVE = {
        Path("cinesort") / "ui" / "api" / "facades",
        Path("cinesort") / "ui" / "api" / "cinesort_api.py",
    }

    def _is_excluded(p: Path) -> bool:
        try:
            rp = p.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            rp = p
        for ex in EXCLUDE_RELATIVE:
            try:
                rp.relative_to(ex)
                return True
            except ValueError:
                pass
            if rp == ex:
                return True
        return False

    files: List[Path] = []
    for t in targets:
        if t.is_file() and t.suffix == ".py":
            if not _is_excluded(t):
                files.append(t)
        elif t.is_dir():
            for p in sorted(t.rglob("*.py")):
                if not _is_excluded(p):
                    files.append(p)

    if not files:
        print("ERREUR : aucun .py trouve", file=sys.stderr)
        return 1

    print(f"Mode : {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Fichiers Python scannes : {len(files)}")
    print()

    total_files_changed = 0
    total_replacements = 0
    file_counts: List[Tuple[Path, int]] = []
    for path in files:
        count = _migrate_file(path, METHOD_TO_FACADE, dry_run=not args.apply)
        if count > 0:
            total_files_changed += 1
            total_replacements += count
            file_counts.append((path, count))

    # Tri par nombre de remplacements descendant
    file_counts.sort(key=lambda x: -x[1])
    for path, count in file_counts:
        rel = path
        print(f"  [{count}x]  {rel}")

    print()
    print(f"Total : {total_replacements} remplacements dans {total_files_changed} fichier(s)")
    if not args.apply:
        print("(dry-run : aucun fichier modifie. Relancer avec --apply pour appliquer.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
