from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SOURCE_EXCLUDE_DIR_NAMES = {
    ".git",
    "build",
    "dist",
    "packages",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

SOURCE_EXCLUDE_DIR_PATTERNS = [
    ".venv*",
    "venv*",
    ".tmp_test",
    ".ui_backups",
    "archive_ui_next_*",
    "web_next_zero",
]

SOURCE_EXCLUDE_PATH_PATTERNS = [
    "docs/internal",
    "docs/internal/*",
    "archive",
    "archive/*",
    "STATE_DIR",
    "STATE_DIR/*",
    "runs",
    "runs/*",
    "CineSort",
    "CineSort/*",
    "db",
    "db/*",
]

SOURCE_EXCLUDE_FILE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.zip",
    "*.sha256",
    "*.manifest.txt",
    "*.tmp",
    "*.bak",
    "*.sqlite-wal",
    "*.sqlite-shm",
    "~*",
    ".coverage*",
    "_BACKUP_*",
    "_LOCAL_uncommitted_changes_backup.patch",
    "cinesort.sqlite",
    "ui_log.txt",
]

PREVIEW_BASELINE_ROOT = "tests/ui_preview_baselines"
CANONICAL_PREVIEW_BASELINE_DIR = f"{PREVIEW_BASELINE_ROOT}/critical"


def read_version(repo_root: Path) -> str:
    version_file = repo_root / "VERSION"
    if not version_file.exists():
        return "0.0.0-dev"
    v = version_file.read_text(encoding="utf-8").strip()
    return v or "0.0.0-dev"


def build_zip_name(kind: str, version: str) -> str:
    if kind == "source":
        return f"CineSort_{version}_source.zip"
    if kind == "qa":
        return f"CineSort_{version}_qa_win64.zip"
    if kind == "release":
        return f"CineSort_{version}_win64.zip"
    raise ValueError(f"Unknown zip kind: {kind}")


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def is_source_excluded(rel: Path) -> bool:
    parts = tuple(p.lower() for p in rel.parts)
    if any(name.lower() in parts for name in SOURCE_EXCLUDE_DIR_NAMES):
        return True
    if any(_matches_any(part, SOURCE_EXCLUDE_DIR_PATTERNS) for part in parts):
        return True
    rel_posix = rel.as_posix()
    base = rel.name
    if rel_posix.startswith(f"{PREVIEW_BASELINE_ROOT}/"):
        return not rel_posix.startswith(f"{CANONICAL_PREVIEW_BASELINE_DIR}/")
    if _matches_any(rel_posix, SOURCE_EXCLUDE_PATH_PATTERNS):
        return True
    if _matches_any(base, SOURCE_EXCLUDE_FILE_PATTERNS):
        return True
    if _matches_any(rel_posix, SOURCE_EXCLUDE_FILE_PATTERNS):
        return True
    return False


def collect_source_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if is_source_excluded(rel):
            continue
        files.append(path)
    return files


def collect_qa_entries(repo_root: Path) -> list[tuple[Path, Path]]:
    dist_dir = repo_root / "dist"
    qa_root = dist_dir / "CineSort_QA"
    entries: list[tuple[Path, Path]] = []

    if not qa_root.exists():
        return []

    for file_path in sorted(qa_root.rglob("*")):
        if file_path.is_file():
            entries.append((file_path, file_path.relative_to(dist_dir)))

    for extra in ("README_FR.txt", "CHANGELOG.md", "VERSION"):
        p = repo_root / extra
        if p.exists():
            entries.append((p, Path(extra)))
    return entries


def collect_release_entries(repo_root: Path) -> list[tuple[Path, Path]]:
    dist_dir = repo_root / "dist"
    onefile = dist_dir / "CineSort.exe"
    entries: list[tuple[Path, Path]] = []

    if onefile.exists():
        entries.append((onefile, Path("CineSort.exe")))
    else:
        return []

    for extra in ("README_FR.txt", "CHANGELOG.md", "VERSION"):
        p = repo_root / extra
        if p.exists():
            entries.append((p, Path(extra)))
    return entries


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_zip(output_zip: Path, entries: list[tuple[Path, Path]]) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_zip, "w", compression=ZIP_DEFLATED, compresslevel=9) as zf:
        for src, arc in entries:
            zf.write(src, arcname=str(arc.as_posix()))


def _manifest_source_label(src: Path, repo_root: Path | None) -> str:
    if repo_root is not None:
        try:
            return src.resolve().relative_to(repo_root.resolve()).as_posix()
        except Exception:
            pass
    return src.as_posix()


def write_sidecars(output_zip: Path, entries: list[tuple[Path, Path]], repo_root: Path | None = None) -> None:
    sha_path = output_zip.with_suffix(output_zip.suffix + ".sha256")
    manifest_path = output_zip.with_suffix(output_zip.suffix + ".manifest.txt")
    sha_path.write_text(f"{sha256_file(output_zip)}  {output_zip.name}\n", encoding="utf-8")
    lines = [f"{arc.as_posix()} <- {_manifest_source_label(src, repo_root)}" for src, arc in entries]
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_source_zip(repo_root: Path, output_dir: Path, version: str) -> Path:
    files = collect_source_files(repo_root)
    if not files:
        raise RuntimeError("Aucun fichier source a compresser.")
    entries = [(f, f.relative_to(repo_root)) for f in files]
    output_zip = output_dir / build_zip_name("source", version)
    write_zip(output_zip, entries)
    write_sidecars(output_zip, entries, repo_root=repo_root)
    print(f"[OK] Source ZIP: {output_zip} ({len(entries)} fichiers)")
    return output_zip


def make_qa_zip(repo_root: Path, output_dir: Path, version: str) -> Path:
    entries = collect_qa_entries(repo_root)
    if not entries:
        raise RuntimeError("Aucun artefact QA trouve dans dist/CineSort_QA/.")
    output_zip = output_dir / build_zip_name("qa", version)
    write_zip(output_zip, entries)
    write_sidecars(output_zip, entries, repo_root=repo_root)
    print(f"[OK] QA ZIP: {output_zip} ({len(entries)} fichiers)")
    return output_zip


def make_release_zip(repo_root: Path, output_dir: Path, version: str) -> Path:
    entries = collect_release_entries(repo_root)
    if not entries:
        raise RuntimeError("Aucun artefact release trouve dans dist/ (attendu dist/CineSort.exe).")
    output_zip = output_dir / build_zip_name("release", version)
    write_zip(output_zip, entries)
    write_sidecars(output_zip, entries, repo_root=repo_root)
    print(f"[OK] Release ZIP: {output_zip} ({len(entries)} fichiers)")
    return output_zip


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Packaging ZIP CineSort (source/qa/release).")
    parser.add_argument("--source", action="store_true", help="Genere le ZIP source.")
    parser.add_argument("--qa", action="store_true", help="Genere le ZIP QA onedir.")
    parser.add_argument("--release", action="store_true", help="Genere le ZIP release (binaire).")
    parser.add_argument("--all", action="store_true", help="Genere source + QA + release.")
    parser.add_argument("--output-dir", default="packages", help="Dossier de sortie des ZIP (defaut: packages).")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    version = read_version(repo_root)
    output_dir = (repo_root / args.output_dir).resolve()

    run_source = bool(args.source)
    run_qa = bool(args.qa)
    run_release = bool(args.release)
    if args.all or (not run_source and not run_qa and not run_release):
        run_source = True
        run_qa = True
        run_release = True

    try:
        if run_source:
            make_source_zip(repo_root, output_dir, version)
        if run_qa:
            make_qa_zip(repo_root, output_dir, version)
        if run_release:
            make_release_zip(repo_root, output_dir, version)
    except Exception as exc:
        print(f"[ERREUR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
