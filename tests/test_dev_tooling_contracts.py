from __future__ import annotations

import unittest
from pathlib import Path


class DevToolingContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.root = root
        cls.requirements_dev = (root / "requirements-dev.txt").read_text(encoding="utf-8")
        cls.pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        cls.pre_commit = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        cls.compile_helper = (root / "scripts" / "check_python_compile.py").read_text(encoding="utf-8")
        cls.check_project = (root / "check_project.bat").read_text(encoding="utf-8")
        cls.dev_readme = (root / "docs" / "README_DEV.md").read_text(encoding="utf-8")
        cls.ci_workflow = (root / ".github" / "workflows" / "windows-ci.yml").read_text(encoding="utf-8")
        cls.sign_script = (root / "scripts" / "sign_windows_release.ps1").read_text(encoding="utf-8")

    def test_requirements_dev_pins_quality_toolchain(self) -> None:
        self.assertIn("-r requirements.txt", self.requirements_dev)
        self.assertIn("-r requirements-preview.txt", self.requirements_dev)
        self.assertIn("ruff>=", self.requirements_dev)
        self.assertIn("coverage>=", self.requirements_dev)
        self.assertIn("pre-commit>=", self.requirements_dev)

    def test_pyproject_declares_ruff_and_coverage_settings(self) -> None:
        self.assertIn("[tool.ruff]", self.pyproject)
        self.assertIn("[tool.ruff.lint]", self.pyproject)
        # Audit B3 : select elargi progressivement. Le contrat minimum est que
        # E et F restent dans select (les fondamentaux du pyflakes + pycodestyle).
        self.assertIn("select = [", self.pyproject)
        self.assertIn('"E"', self.pyproject)
        self.assertIn('"F"', self.pyproject)
        self.assertIn("[tool.coverage.run]", self.pyproject)
        self.assertIn("[tool.coverage.report]", self.pyproject)

    def test_pre_commit_config_keeps_local_ruff_hooks(self) -> None:
        self.assertIn("pre-commit-hooks", self.pre_commit)
        self.assertIn("trailing-whitespace", self.pre_commit)
        self.assertIn("end-of-file-fixer", self.pre_commit)
        self.assertIn("check-yaml", self.pre_commit)
        self.assertIn("check-toml", self.pre_commit)
        self.assertIn("astral-sh/ruff-pre-commit", self.pre_commit)
        self.assertIn("id: ruff", self.pre_commit)
        self.assertIn("id: ruff-format", self.pre_commit)
        # Scope elargi couvre cinesort/, tests/, scripts/
        self.assertIn("cinesort", self.pre_commit)
        self.assertIn("tests", self.pre_commit)
        self.assertIn("scripts", self.pre_commit)

    def test_dev_readme_documents_opt_in_live_verification(self) -> None:
        self.assertIn("python scripts/run_live_verification.py", self.dev_readme)
        self.assertIn("La verification standard reste `check_project.bat`.", self.dev_readme)
        self.assertIn("CINESORT_LIVE_TMDB=1", self.dev_readme)
        self.assertIn("CINESORT_TMDB_API_KEY", self.dev_readme)
        self.assertIn("la preuve live n'a pas ete rejouee", self.dev_readme)
        self.assertIn("CINESORT_LIVE_PROBE=1", self.dev_readme)
        self.assertIn("CINESORT_LIVE_PYWEBVIEW=1", self.dev_readme)
        self.assertIn("CINESORT_MEDIA_SAMPLE_PATH", self.dev_readme)
        self.assertIn("CINESORT_STRESS=1", self.dev_readme)
        self.assertIn("tests.stress.large_volume_flow", self.dev_readme)
        self.assertTrue((self.root / "scripts" / "run_live_verification.py").exists())

    def test_recursive_compile_helper_skips_tooling_artifacts(self) -> None:
        compile(self.compile_helper, str(self.root / "scripts" / "check_python_compile.py"), "exec")
        self.assertIn('root.rglob("*.py")', self.compile_helper)
        self.assertIn('".venv313"', self.compile_helper)
        self.assertIn('"build"', self.compile_helper)
        self.assertIn('"dist"', self.compile_helper)
        self.assertIn('"packages"', self.compile_helper)
        self.assertIn('".tmp"', self.compile_helper)

    def test_check_project_uses_quality_gate_stack(self) -> None:
        # Audit AUDIT_20260422 T2 : check_project.bat a ete simplifie — le scope
        # lint/format est maintenant le projet entier avec `ruff check .` (les
        # exclusions viennent de pyproject.toml). Les tests passent par pytest,
        # pas unittest. La liste explicite de modules a disparu.
        self.assertIn("scripts\\check_python_compile.py", self.check_project)
        self.assertIn("-m ruff check", self.check_project)
        self.assertIn("-m ruff format --check", self.check_project)
        self.assertIn("-m pytest", self.check_project)
        self.assertIn("-m coverage run -m pytest", self.check_project)
        self.assertIn("-m coverage report", self.check_project)
        self.assertIn("--fail-under=80", self.check_project)
        # Les E2E/live/stress sont ignores dans ce gate
        self.assertIn("--ignore=tests/e2e", self.check_project)
        self.assertIn("--ignore=tests/live", self.check_project)

    def test_ci_workflow_documents_windows_quality_build_and_optional_signing(self) -> None:
        self.assertIn("windows-latest", self.ci_workflow)
        self.assertIn('python-version: "3.13"', self.ci_workflow)
        self.assertIn("workflow_dispatch", self.ci_workflow)
        self.assertIn("check_project.bat", self.ci_workflow)
        self.assertIn("build_windows.bat", self.ci_workflow)
        self.assertIn("scripts/capture_ui_preview.py --dev --recommended", self.ci_workflow)
        self.assertIn("scripts/visual_check_ui_preview.py --dev", self.ci_workflow)
        self.assertIn("actions/upload-artifact@v4", self.ci_workflow)
        self.assertIn("WINDOWS_CODESIGN_CERT_BASE64", self.ci_workflow)
        self.assertIn("WINDOWS_CODESIGN_CERT_PASSWORD", self.ci_workflow)
        self.assertIn("scripts/sign_windows_release.ps1", self.ci_workflow)
        self.assertIn("WINDOWS_CODESIGN_CERT_BASE64", self.sign_script)
        self.assertIn("WINDOWS_CODESIGN_CERT_PASSWORD", self.sign_script)
        self.assertIn("signtool", self.sign_script)
        self.assertIn("CI Windows: `.github/workflows/windows-ci.yml`", self.dev_readme)
        self.assertIn("workflow_dispatch", self.dev_readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
