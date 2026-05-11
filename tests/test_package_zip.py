from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts import package_zip


class PackageZipTests(unittest.TestCase):
    def _write_text(self, path: Path, content: str = "x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_bytes(self, path: Path, content: bytes = b"x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _create_source_tree(self, root: Path) -> None:
        essential_files = {
            "README_FR.txt": "doc",
            "CHANGELOG.md": "changelog",
            "VERSION": "7.2.0-dev",
            "docs/README_DEV.md": "dev",
            "docs/product/VISION_V7_FR.md": "vision",
            "docs/releases/V7_1_NOTES_FR.md": "notes",
            "docs/design/UNDO_7_2_0_A_DESIGN_FR.md": "undo design",
            "docs/design/APPLY_ROWS_7E_DESIGN_FR.md": "apply design",
            "web/index.html": "<!doctype html>",
            "web/app.js": "console.log('app');",
            "web/styles.css": "body {}",
            "cinesort/__init__.py": "__all__ = []",
            "scripts/package_zip.py": "print('zip')",
            "tests/test_keep.py": "print('keep')",
            "tests/ui_preview_baselines/critical/manifest.json": "{}",
        }
        for rel, content in essential_files.items():
            self._write_text(root / rel, content)

        critical_binary_files = {
            "tests/ui_preview_baselines/critical/accueil.png": b"png",
        }
        for rel, content in critical_binary_files.items():
            self._write_bytes(root / rel, content)

        noise_files = {
            ".venv313/Scripts/python.exe": b"x",
            "venv_local/Scripts/python.exe": b"x",
            "dist/CineSort.exe": b"x",
            "dist/CineSort_QA/CineSort.exe": b"x",
            "build/tmp.obj": b"x",
            "packages/CineSort_7.2.0-dev_source.zip": b"x",
            "__pycache__/module.pyc": b"x",
            ".tmp_test/manual_dir/normal.txt": "tmp",
            ".ui_backups/index.before_ui_redesign.html": "backup",
            "archive_ui_next_20260308/web_next_current/app_next.js": "next",
            "web_next_zero/index.html": "next zero",
            "tests/ui_preview_baselines/premium_sober/manifest.json": "{}",
            "tests/ui_preview_baselines/synthese_quality/02-dashboard.png": b"png",
            "docs/internal/worklogs/CODEX_WORKLOG.md": "internal",
            "docs/internal/audits/AUDIT_CORRECTIFS_PROJET_FR.txt": "internal",
            "STATE_DIR/runs/tri_films_20260308_113501_172/ui_log.txt": "runtime",
            "CineSort/db/cinesort.sqlite": b"sqlite",
            "db/cinesort.sqlite": b"sqlite",
            "cinesort.sqlite-wal": b"wal",
            "cinesort.sqlite-shm": b"shm",
            "_BACKUP_before.txt": "backup",
            "_LOCAL_uncommitted_changes_backup.patch": "patch",
            "debug.log": "log",
            "ui_log.txt": "log",
        }
        for rel, content in noise_files.items():
            path = root / rel
            if isinstance(content, bytes):
                self._write_bytes(path, content)
            else:
                self._write_text(path, content)

    def test_build_zip_name_contains_version(self) -> None:
        self.assertEqual(
            package_zip.build_zip_name("source", "7.1.6-dev"),
            "CineSort_7.1.6-dev_source.zip",
        )
        self.assertEqual(
            package_zip.build_zip_name("qa", "7.1.6-dev"),
            "CineSort_7.1.6-dev_qa_win64.zip",
        )
        self.assertEqual(
            package_zip.build_zip_name("release", "7.1.6-dev"),
            "CineSort_7.1.6-dev_win64.zip",
        )

    def test_collect_qa_entries_uses_onedir_payload_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_zip_qa_") as tmp:
            root = Path(tmp)
            self._create_source_tree(root)

            entries = package_zip.collect_qa_entries(root)
            names = {arc.as_posix() for _src, arc in entries}

            self.assertIn("CineSort_QA/CineSort.exe", names)
            self.assertIn("README_FR.txt", names)
            self.assertIn("CHANGELOG.md", names)
            self.assertIn("VERSION", names)
            self.assertNotIn("CineSort.exe", names)

    def test_collect_release_entries_uses_onefile_payload_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_zip_release_") as tmp:
            root = Path(tmp)
            self._create_source_tree(root)

            entries = package_zip.collect_release_entries(root)
            names = {arc.as_posix() for _src, arc in entries}

            self.assertIn("CineSort.exe", names)
            self.assertIn("README_FR.txt", names)
            self.assertIn("CHANGELOG.md", names)
            self.assertIn("VERSION", names)
            self.assertNotIn("CineSort_QA/CineSort.exe", names)

    def test_source_exclusions_filter_noise_and_keep_essentials(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_zip_") as tmp:
            root = Path(tmp)
            self._create_source_tree(root)

            files = package_zip.collect_source_files(root)
            rels = {str(p.relative_to(root)).replace("\\", "/") for p in files}

            self.assertIn("README_FR.txt", rels)
            self.assertIn("CHANGELOG.md", rels)
            self.assertIn("VERSION", rels)
            self.assertIn("docs/README_DEV.md", rels)
            self.assertIn("docs/product/VISION_V7_FR.md", rels)
            self.assertIn("docs/releases/V7_1_NOTES_FR.md", rels)
            self.assertIn("docs/design/UNDO_7_2_0_A_DESIGN_FR.md", rels)
            self.assertIn("docs/design/APPLY_ROWS_7E_DESIGN_FR.md", rels)
            self.assertIn("web/index.html", rels)
            self.assertIn("web/app.js", rels)
            self.assertIn("web/styles.css", rels)
            self.assertIn("cinesort/__init__.py", rels)
            self.assertIn("scripts/package_zip.py", rels)
            self.assertIn("tests/test_keep.py", rels)
            self.assertIn("tests/ui_preview_baselines/critical/manifest.json", rels)
            self.assertIn("tests/ui_preview_baselines/critical/accueil.png", rels)

            excluded = {
                ".venv313/Scripts/python.exe",
                "venv_local/Scripts/python.exe",
                "dist/CineSort.exe",
                "build/tmp.obj",
                "packages/CineSort_7.2.0-dev_source.zip",
                "__pycache__/module.pyc",
                ".tmp_test/manual_dir/normal.txt",
                ".ui_backups/index.before_ui_redesign.html",
                "archive_ui_next_20260308/web_next_current/app_next.js",
                "web_next_zero/index.html",
                "tests/ui_preview_baselines/premium_sober/manifest.json",
                "tests/ui_preview_baselines/synthese_quality/02-dashboard.png",
                "docs/internal/worklogs/CODEX_WORKLOG.md",
                "docs/internal/audits/AUDIT_CORRECTIFS_PROJET_FR.txt",
                "STATE_DIR/runs/tri_films_20260308_113501_172/ui_log.txt",
                "CineSort/db/cinesort.sqlite",
                "db/cinesort.sqlite",
                "cinesort.sqlite-wal",
                "cinesort.sqlite-shm",
                "_BACKUP_before.txt",
                "_LOCAL_uncommitted_changes_backup.patch",
                "debug.log",
                "ui_log.txt",
            }
            self.assertTrue(excluded.isdisjoint(rels))

    def test_make_source_zip_excludes_noise_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_zip_make_") as tmp:
            root = Path(tmp)
            self._create_source_tree(root)
            output_dir = root / "out"

            output_zip = package_zip.make_source_zip(root, output_dir, "7.2.0-dev")

            self.assertTrue(output_zip.exists())
            manifest_path = output_zip.with_suffix(output_zip.suffix + ".manifest.txt")
            self.assertTrue(manifest_path.exists())

            with ZipFile(output_zip) as zf:
                names = {name.replace("\\", "/") for name in zf.namelist()}

            self.assertIn("web/index.html", names)
            self.assertIn("web/app.js", names)
            self.assertIn("web/styles.css", names)
            self.assertIn("cinesort/__init__.py", names)
            self.assertIn("scripts/package_zip.py", names)
            self.assertIn("README_FR.txt", names)
            self.assertIn("CHANGELOG.md", names)
            self.assertIn("VERSION", names)
            self.assertIn("docs/README_DEV.md", names)
            self.assertIn("docs/product/VISION_V7_FR.md", names)
            self.assertIn("docs/releases/V7_1_NOTES_FR.md", names)
            self.assertIn("docs/design/UNDO_7_2_0_A_DESIGN_FR.md", names)
            self.assertIn("docs/design/APPLY_ROWS_7E_DESIGN_FR.md", names)
            self.assertIn("tests/ui_preview_baselines/critical/manifest.json", names)
            self.assertIn("tests/ui_preview_baselines/critical/accueil.png", names)

            for prefix in (
                ".venv",
                "venv",
                ".tmp_test/",
                ".ui_backups/",
                "archive_ui_next_",
                "web_next_zero/",
                "docs/internal/",
                "STATE_DIR/",
                "CineSort/",
                "db/",
            ):
                self.assertFalse(any(name.startswith(prefix) for name in names), prefix)
            self.assertFalse(
                any(
                    name.startswith("tests/ui_preview_baselines/")
                    and not name.startswith("tests/ui_preview_baselines/critical/")
                    for name in names
                )
            )

            manifest = manifest_path.read_text(encoding="utf-8")
            self.assertIn("web/index.html <- web/index.html", manifest)
            self.assertIn(
                "docs/design/UNDO_7_2_0_A_DESIGN_FR.md <- docs/design/UNDO_7_2_0_A_DESIGN_FR.md",
                manifest,
            )
            self.assertIn(
                "tests/ui_preview_baselines/critical/manifest.json <- tests/ui_preview_baselines/critical/manifest.json",
                manifest,
            )
            self.assertNotIn(".venv313/", manifest)
            self.assertNotIn(".tmp_test/", manifest)
            self.assertNotIn("tests/ui_preview_baselines/premium_sober/", manifest)
            self.assertNotIn("tests/ui_preview_baselines/synthese_quality/", manifest)
            self.assertNotIn("docs/internal/", manifest)
            self.assertNotIn("STATE_DIR/", manifest)
            self.assertNotIn("CineSort/", manifest)
            self.assertNotIn("db/cinesort.sqlite", manifest)

    def test_manifest_uses_repo_relative_paths_when_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_zip_manifest_") as tmp:
            root = Path(tmp)
            readme = root / "README_FR.txt"
            readme.write_text("doc", encoding="utf-8")
            out_zip = root / "packages" / "CineSort_test_source.zip"
            entries = [(readme, Path("README_FR.txt"))]

            package_zip.write_zip(out_zip, entries)
            package_zip.write_sidecars(out_zip, entries, repo_root=root)

            manifest = out_zip.with_suffix(out_zip.suffix + ".manifest.txt").read_text(encoding="utf-8")
            self.assertIn("README_FR.txt <- README_FR.txt", manifest)
            self.assertNotIn(str(root), manifest)

    def test_make_qa_zip_keeps_onedir_structure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_zip_make_qa_") as tmp:
            root = Path(tmp)
            self._create_source_tree(root)
            output_dir = root / "out"

            output_zip = package_zip.make_qa_zip(root, output_dir, "7.2.0-dev")

            with ZipFile(output_zip) as zf:
                names = {name.replace("\\", "/") for name in zf.namelist()}

            self.assertIn("CineSort_QA/CineSort.exe", names)
            self.assertIn("README_FR.txt", names)
            self.assertNotIn("CineSort.exe", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
