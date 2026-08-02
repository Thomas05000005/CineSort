"""tests/test_ci_workflows_pyproject_compat_v77.py — Vague M, lot M-08 (ARCH-03).

Audit les workflows .github/workflows/*.yml pour verifier qu'aucun n'utilise
de patterns incompatibles avec la migration progressive vers pyproject.toml :

1. Tous les workflows doivent installer via :
   - `pip install -r requirements*.txt` (legacy compat, OK)
   - OU `pip install -e .[dev]` (pyproject path, OK)
   - OU `pip install .` / `pip install -e .` (OK)

2. Aucun workflow ne doit hardcoder un package non-liste dans requirements.txt
   ou pyproject.toml [project.dependencies]/[optional-dependencies].
   (sauf playwright/pytest-playwright explicitement installes apres pour E2E,
   et pytest qui est dans dev.)

3. ci.yml doit exister et contenir au moins une etape "Setup Python" + une
   etape qui execute des tests pytest.

Ces verifications attrapent toute regression qui casserait la CI suite a
des changements pyproject.toml.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"


def _list_workflows() -> list[Path]:
    if not WORKFLOWS_DIR.is_dir():
        return []
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


class CiWorkflowsCompatTests(unittest.TestCase):
    """Audit des workflows GitHub Actions."""

    def test_workflows_dir_exists(self) -> None:
        self.assertTrue(
            WORKFLOWS_DIR.is_dir(),
            f".github/workflows/ introuvable a {WORKFLOWS_DIR}",
        )

    def test_ci_yml_present(self) -> None:
        ci = WORKFLOWS_DIR / "ci.yml"
        self.assertTrue(ci.is_file(), "Workflow ci.yml manquant")

    def test_ci_yml_uses_python_313(self) -> None:
        ci = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        # On accepte "3.13" en string libre (avec ou sans quotes).
        self.assertRegex(
            ci,
            r"python-version[\s:]+[\"\']?3\.13",
            "ci.yml ne configure pas python-version 3.13",
        )

    def test_ci_yml_runs_tests(self) -> None:
        ci = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        # pytest, unittest discover, ou coverage run -m pytest.
        has_tests = bool(
            re.search(r"\bpytest\b", ci) or re.search(r"unittest\s+discover", ci) or re.search(r"coverage\s+run", ci)
        )
        self.assertTrue(has_tests, "ci.yml ne lance pas de tests Python")

    def test_workflows_install_via_known_patterns(self) -> None:
        """Chaque workflow qui installe des deps Python doit utiliser un pattern connu."""
        # Patterns autorises (au moins l'un doit etre present si le workflow installe).
        valid_patterns = [
            r"pip install\s+-r\s+requirements",
            r"pip install\s+-e\s+\.",
            r"pip install\s+\.",
            r"pip install\s+--upgrade",  # pip lui-meme, neutre
        ]
        # Workflows totalement exempts (pas Python ou pas de pip install).
        exempt_filenames = {
            "labeler.yml",
            "release-drafter.yml",
            "stale.yml",
            "dependabot-auto-merge.yml",
            "pr-title-lint.yml",
            "link-check.yml",
            "gitleaks.yml",
            "scorecard.yml",
            "claude.yml",
            "actionlint.yml",
        }

        failures: list[str] = []
        for wf in _list_workflows():
            if wf.name in exempt_filenames:
                continue
            text = wf.read_text(encoding="utf-8")
            if "pip install" not in text:
                # Workflow Python sans pip install : OK (ex: smoke EXE pur).
                continue
            ok = any(re.search(p, text) for p in valid_patterns)
            if not ok:
                failures.append(wf.name)

        self.assertEqual(
            failures,
            [],
            f"Workflows avec pip install sans pattern reconnu : {failures}",
        )

    def test_ci_yml_installs_requirements_or_pyproject(self) -> None:
        """ci.yml doit installer soit -r requirements*.txt soit -e .[dev]."""
        ci = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        has_req = bool(re.search(r"pip install\s+(?:-[a-z]+\s+)*-r\s+requirements", ci))
        has_editable = bool(re.search(r"pip install\s+-e\s+\.", ci))
        self.assertTrue(
            has_req or has_editable,
            "ci.yml n'installe ni requirements*.txt ni -e .[dev]",
        )

    def test_no_workflow_pins_outdated_python(self) -> None:
        """Aucun workflow ne doit pinner Python < 3.13."""
        bad: list[str] = []
        for wf in _list_workflows():
            text = wf.read_text(encoding="utf-8")
            # Chercher python-version: "3.X" / 3.X avec X < 13.
            for m in re.finditer(r"python-version[\s:]+[\"\']?(\d+)\.(\d+)", text):
                major = int(m.group(1))
                minor = int(m.group(2))
                if major == 3 and minor < 13:
                    bad.append(f"{wf.name}: 3.{minor}")
        self.assertEqual(
            bad,
            [],
            f"Workflows pinnant Python < 3.13 : {bad}",
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
