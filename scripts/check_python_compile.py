from __future__ import annotations

import argparse
import py_compile
import sys
from pathlib import Path

EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pre-commit-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv313",
    "__pycache__",
    "build",
    "dist",
    "packages",
    "venv",
}

EXCLUDED_DIR_PREFIXES = (
    ".tmp",
    "archive_ui_next_",
)

EXCLUDED_DIR_PATHS = {
    ".ui_backups",
    "web_next_zero",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def should_skip_dir(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    rel_posix = rel.as_posix().lower()
    if rel_posix in EXCLUDED_DIR_PATHS:
        return True
    for part in rel.parts:
        lowered = part.lower()
        if lowered in EXCLUDED_DIR_NAMES:
            return True
        if any(lowered.startswith(prefix) for prefix in EXCLUDED_DIR_PREFIXES):
            return True
    return False


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if should_skip_dir(path.parent, root):
            continue
        files.append(path)
    return files


def compile_files(root: Path) -> tuple[int, list[tuple[Path, Exception]]]:
    failures: list[tuple[Path, Exception]] = []
    files = iter_python_files(root)
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:  # pragma: no cover - surfaced via exit code
            failures.append((path, exc))
    return len(files), failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recursively compile Python files for CineSort.")
    parser.add_argument("--root", default="", help="Repository root override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else repo_root()
    total, failures = compile_files(root)
    print(f"[INFO] Python files compiled: {total}")
    if not failures:
        print("[OK] Recursive compile check passed.")
        return 0
    print("[ERROR] Recursive compile check failed:")
    for path, exc in failures:
        print(f" - {path.relative_to(root)} :: {exc}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
