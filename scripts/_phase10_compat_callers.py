"""Phase 10 v7.8.0 - count external callers via core.X for compat re-exports."""

from pathlib import Path

symbols = [
    "core_apply_support",
    "core_duplicate_support",
    "_collect_non_video_extensions",
    "_stream_scan_targets",
    "iter_videos",
    "_apply_rows_support",
    "_move_empty_top_level_dirs",
    "_move_residual_top_level_dirs",
    "preview_cleanup_residual_folders",
    "_find_duplicate_targets_support",
    "core_plan_support",
]
for sym in symbols:
    n = 0
    for f in Path("cinesort").rglob("*.py"):
        fn = str(f).replace("\\", "/")
        if "domain/core.py" in fn:
            continue
        try:
            txt = f.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        # Match `core.X` or `core_mod.X`
        if (f"core.{sym}" in txt) or (f"core_mod.{sym}" in txt):
            n += 1
    print(f"  {sym}: {n} ext callers")
