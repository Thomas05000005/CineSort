from __future__ import annotations

import re
from pathlib import Path
import unittest


class ReleaseHygieneTests(unittest.TestCase):
    def test_no_personal_strings_in_repo(self) -> None:
        """Detecte les fuites PII : chemins Windows perso, NAS, base d'etat
        precedente. On evite de chercher le bare "blanc" qui matche aussi
        "bruit blanc" (audio FR), "carte blanche", etc. — on traque les
        vrais marqueurs de leak (chemin Users\\..., adresse mail, NAS path).
        """
        repo_root = Path(__file__).resolve().parents[1]
        allowed_exts = {".py", ".md", ".txt", ".spec", ".html", ".js", ".css"}
        # 'audit' = dossier de prompts d'orchestration parallele qui contient
        # legitimement des chemins de worktrees (.claude/worktrees/...). Pas du code prod.
        skip_dirs = {".git", ".venv", ".venv313", "build", "dist", "packages", "__pycache__", "manual", "audit"}
        skip_files = {"_BACKUP_patch_before.txt", "_BACKUP_patch_after.txt", "test_release_hygiene.py"}

        # Les fragments sont assembles a runtime pour que le fichier de test
        # lui-meme ne matche pas (sinon ce serait recursif).
        user_login = "".join(["bl", "anc"])
        forbidden_tokens = [
            # Chemin Windows perso: c:\users\blanc, /users/blanc/, users\blanc
            "users\\" + user_login,
            "users/" + user_login,
            "users\\\\" + user_login,
            # Email perso
            user_login + ".thomas@",
            # NAS UNC perso
            "".join(["\\\\", "omv", "\\", "media", "\\", "films"]),
            # Ancien nom du dossier d'etat (leak base v1)
            "".join(["tri_", "films_", "state"]),
        ]

        offenders = []
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed_exts:
                continue
            if path.name in skip_files:
                continue
            parts_lower = {part.lower() for part in path.parts}
            if parts_lower.intersection(skip_dirs):
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(encoding="latin-1", errors="ignore")

            content_l = content.lower()
            for token in forbidden_tokens:
                if token in content_l:
                    offenders.append(f"{path}: {token}")
                    break

        if offenders:
            details = "\n".join(offenders[:40])
            self.fail(f"Forbidden strings found:\n{details}")

    def test_docs_use_stable_ui_terminology(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        critical_docs = [
            repo_root / "README_FR.txt",
            repo_root / "CHANGELOG.md",
            repo_root / "docs" / "releases" / "V7_1_NOTES_FR.md",
        ]
        offenders: list[str] = []
        forbidden_patterns = [
            re.compile(r"\bDashboard\b"),
            re.compile(r"\bdashboard\b"),
            re.compile(r"Workflow clair en 4 etapes"),
        ]

        for path in critical_docs:
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                for match in pattern.finditer(content):
                    line_no = content.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.name}:{line_no}: {pattern.pattern}")

        if offenders:
            self.fail("Legacy UI/doc terms found:\n" + "\n".join(offenders))

    def test_readme_contains_official_guided_workflow(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README_FR.txt").read_text(encoding="utf-8")
        expected_workflow = (
            "Workflow guide reel:\n"
            "- Reglages\n"
            "- Analyse\n"
            "- Vue du run\n"
            "- Qualite\n"
            "- Cas a revoir\n"
            "- Decisions\n"
            "- Conflits\n"
            "- Execution (dry-run puis reel)\n"
            "- Historique"
        )
        self.assertIn(expected_workflow, readme)
        self.assertIn("Vue du run:", readme)
        self.assertIn("accessible apres Analyse", readme)

    def test_release_docs_keep_official_synthese_wording(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
        release_notes = (repo_root / "docs" / "releases" / "V7_1_NOTES_FR.md").read_text(encoding="utf-8")

        self.assertIn("Synthese qualite", changelog)
        self.assertIn("nouvel onglet **Synthese**", changelog)
        self.assertIn("Ajout onglet UI Synthese", release_notes)

    def test_check_project_covers_preview_scripts_and_new_modules(self) -> None:
        # Audit AUDIT_20260422 T2 : migration vers pytest + ruff sur le projet
        # entier (les excludes sont declares dans pyproject.toml). On garde ici
        # juste les invariants du gate qualite.
        repo_root = Path(__file__).resolve().parents[1]
        check_project = (repo_root / "check_project.bat").read_text(encoding="utf-8")
        compile_helper = repo_root / "scripts" / "check_python_compile.py"
        self.assertTrue(compile_helper.exists())
        self.assertIn("scripts\\check_python_compile.py", check_project)
        self.assertIn("-m ruff check", check_project)
        self.assertIn("-m ruff format --check", check_project)
        self.assertIn("-m pytest", check_project)
        self.assertIn("-m coverage run -m pytest", check_project)
        self.assertIn("-m coverage report", check_project)

    def test_internal_and_design_docs_are_reorganized_out_of_repo_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        moved_docs = {
            "VISION_V7_FR.md": "docs/product/VISION_V7_FR.md",
            "V7_1_NOTES_FR.md": "docs/releases/V7_1_NOTES_FR.md",
            "UNDO_7_2_0_A_DESIGN_FR.md": "docs/design/UNDO_7_2_0_A_DESIGN_FR.md",
            "APPLY_ROWS_7E_DESIGN_FR.md": "docs/design/APPLY_ROWS_7E_DESIGN_FR.md",
            "AUDIT_CORRECTIFS_PROJET_FR.txt": "docs/internal/audits/AUDIT_CORRECTIFS_PROJET_FR.txt",
            "CODEX_WORKLOG.md": "docs/internal/worklogs/CODEX_WORKLOG.md",
            "PHASE1_CADRAGE_APP_20260309.txt": "docs/internal/plans/PHASE1_CADRAGE_APP_20260309.txt",
        }

        for old_rel, new_rel in moved_docs.items():
            self.assertFalse((repo_root / old_rel).exists(), old_rel)
            self.assertTrue((repo_root / new_rel).exists(), new_rel)

        self.assertTrue((repo_root / "docs" / "README_DEV.md").exists())

    def test_readme_stays_operator_focused_and_avoids_internal_root_doc_links(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README_FR.txt").read_text(encoding="utf-8")
        forbidden_internal_root_refs = [
            "AUDIT_CORRECTIFS_PROJET_FR.txt",
            "CODEX_WORKLOG.md",
            "PHASE1_CADRAGE_APP_20260309.txt",
            "UI_NEXT_REFONTE_WORKLOG.txt",
            "UI_NEXT_ZERO_WORKLOG.txt",
        ]

        for token in forbidden_internal_root_refs:
            self.assertNotIn(token, readme)

        self.assertIn("docs/releases/V7_1_NOTES_FR.md", readme)
        self.assertIn("docs/design/UNDO_7_2_0_A_DESIGN_FR.md", readme)
        self.assertIn("docs/README_DEV.md", readme)

    def test_operator_docs_no_longer_advertise_archived_next_ui(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README_FR.txt").read_text(encoding="utf-8")
        dev_readme = (repo_root / "docs" / "README_DEV.md").read_text(encoding="utf-8")

        self.assertNotIn("UI Next = dev only", readme)
        self.assertNotIn("python app.py --ui next", readme)
        self.assertNotIn("CINESORT_UI=next", readme)
        self.assertIn("prototype UI Next est archive", readme)
        self.assertIn("archive dans `docs/internal/archive/ui_next_20260319/`", dev_readme)

    def test_build_docs_scripts_and_spec_agree_on_packaging_strategy(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        dev_readme = (repo_root / "docs" / "README_DEV.md").read_text(encoding="utf-8")
        vision = (repo_root / "docs" / "product" / "VISION_V7_FR.md").read_text(encoding="utf-8")
        build_script = (repo_root / "build_windows.bat").read_text(encoding="utf-8")
        spec = (repo_root / "CineSort.spec").read_text(encoding="utf-8")
        package_zip = (repo_root / "scripts" / "package_zip.py").read_text(encoding="utf-8")

        self.assertIn("dist/CineSort_QA/CineSort.exe", dev_readme)
        self.assertIn("dist/CineSort.exe", dev_readme)
        self.assertIn("QA interne = `onedir`", vision)
        self.assertIn("release utilisateur = `onefile`", vision)
        self.assertIn("dist\\CineSort_QA\\CineSort.exe", build_script)
        self.assertIn("dist\\CineSort.exe", build_script)
        self.assertIn('name="CineSort_QA"', spec)
        self.assertIn('name="CineSort"', spec)
        self.assertIn('parser.add_argument("--qa"', package_zip)
        self.assertIn('build_zip_name("qa"', package_zip)


class SmtplibAvailabilityTests(unittest.TestCase):
    """Verifie que les modules requis par email_report.py ne sont pas exclus du bundle."""

    def test_smtplib_importable(self) -> None:
        import smtplib

        self.assertTrue(hasattr(smtplib, "SMTP"))

    def test_email_mime_importable(self) -> None:
        from email.mime.text import MIMEText

        self.assertTrue(callable(MIMEText))

    def test_ssl_importable(self) -> None:
        import ssl

        self.assertTrue(hasattr(ssl, "create_default_context"))


class RecordApplyOpTests(unittest.TestCase):
    """Tests pour record_apply_op (logging echec + retour boolean)."""

    def test_returns_true_on_success(self) -> None:
        from cinesort.app.apply_core import record_apply_op

        ops = []
        ok = record_apply_op(ops.append, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertTrue(ok)
        self.assertEqual(len(ops), 1)

    def test_returns_true_when_record_op_is_none(self) -> None:
        from cinesort.app.apply_core import record_apply_op

        ok = record_apply_op(None, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertTrue(ok)

    def test_returns_false_on_failure_and_logs(self) -> None:
        import logging
        from cinesort.app.apply_core import record_apply_op

        def _broken_recorder(_data: dict) -> None:
            raise OSError("DB verrouille")

        with self.assertLogs("cinesort.app.apply_core", level=logging.ERROR) as cm:
            ok = record_apply_op(_broken_recorder, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertFalse(ok)
        self.assertTrue(any("echec journalisation" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main(verbosity=2)
