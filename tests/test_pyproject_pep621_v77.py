"""tests/test_pyproject_pep621_v77.py — Vague M, lot M-08 (ARCH-03).

Verifie que pyproject.toml expose un bloc [project] PEP 621 complet :
- name, version, description, readme, license, authors
- requires-python = "==3.13.*"
- dependencies alignees sur requirements.txt
- [project.optional-dependencies] dev + build presentes
- Plus de placeholder <PROJECT_AUTHOR>

Ce test garantit la metadata minimale pour pip / build / publish, et
attrape toute regression qui supprimerait des champs PEP 621.
"""

from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)


class PyprojectPep621Tests(unittest.TestCase):
    """Section [project] conforme PEP 621."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_pyproject()
        cls.project = cls.data.get("project", {})

    def test_pyproject_exists(self) -> None:
        self.assertTrue(PYPROJECT.exists(), f"pyproject.toml introuvable a {PYPROJECT}")

    def test_project_table_present(self) -> None:
        self.assertIn("project", self.data, "Bloc [project] absent de pyproject.toml")

    def test_project_name(self) -> None:
        self.assertEqual(self.project.get("name"), "cinesort")

    def test_project_version_aligned_on_version_file(self) -> None:
        """version doit etre alignee sur le fichier VERSION."""
        version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(
            self.project.get("version"),
            version_file,
            f"Mismatch pyproject.version={self.project.get('version')!r} vs VERSION={version_file!r}",
        )

    def test_project_description_non_empty(self) -> None:
        desc = self.project.get("description", "")
        self.assertIsInstance(desc, str)
        self.assertGreater(len(desc), 20, "description trop courte")

    def test_project_readme(self) -> None:
        self.assertEqual(self.project.get("readme"), "README.md")

    def test_project_license_mit(self) -> None:
        lic = self.project.get("license", {})
        self.assertIsInstance(lic, dict)
        self.assertEqual(lic.get("text"), "MIT")

    def test_project_authors_no_placeholder(self) -> None:
        """Le placeholder <PROJECT_AUTHOR> doit etre remplace."""
        authors = self.project.get("authors", [])
        self.assertGreater(len(authors), 0, "authors vide")
        for author in authors:
            name = author.get("name", "")
            self.assertFalse(
                re.search(r"<\s*PROJECT_AUTHOR\s*>", name),
                f"Placeholder author trouve : {name!r}",
            )
            self.assertTrue(name, "author.name vide")

    def test_requires_python_313(self) -> None:
        rp = self.project.get("requires-python", "")
        self.assertEqual(rp, "==3.13.*", f"requires-python attendu '==3.13.*', recu {rp!r}")

    def test_dependencies_non_empty(self) -> None:
        deps = self.project.get("dependencies", [])
        self.assertIsInstance(deps, list)
        self.assertGreater(len(deps), 0, "dependencies vide")

    def test_dependencies_aligned_on_requirements_txt(self) -> None:
        """Chaque package nomme dans requirements.txt doit apparaitre dans dependencies."""
        req_path = ROOT / "requirements.txt"
        self.assertTrue(req_path.exists())
        req_pkgs = set()
        for raw in req_path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            # nom de package = lettres/chiffres/_-. avant >=, <, ==, !=, ~=
            m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
            if m:
                req_pkgs.add(m.group(1).lower())
        deps_pkgs = set()
        for dep in self.project.get("dependencies", []):
            m = re.match(r"^([A-Za-z0-9_.\-]+)", dep)
            if m:
                deps_pkgs.add(m.group(1).lower())
        missing = req_pkgs - deps_pkgs
        self.assertEqual(
            missing,
            set(),
            f"Packages dans requirements.txt absents de [project.dependencies] : {missing}",
        )

    def test_optional_dependencies_dev_present(self) -> None:
        opt = self.project.get("optional-dependencies", {})
        self.assertIn("dev", opt, "optional-dependencies.dev manquant")
        dev = opt["dev"]
        self.assertIsInstance(dev, list)
        # Doit au moins contenir pytest, ruff, coverage.
        names = {re.match(r"^([A-Za-z0-9_.\-]+)", d).group(1).lower() for d in dev}
        for required in {"pytest", "ruff", "coverage"}:
            self.assertIn(required, names, f"{required} absent de optional-dependencies.dev")

    def test_optional_dependencies_build_present(self) -> None:
        opt = self.project.get("optional-dependencies", {})
        self.assertIn("build", opt, "optional-dependencies.build manquant")
        build = opt["build"]
        names = {re.match(r"^([A-Za-z0-9_.\-]+)", d).group(1).lower() for d in build}
        self.assertIn("pyinstaller", names, "pyinstaller absent de optional-dependencies.build")

    def test_build_system_present(self) -> None:
        bs = self.data.get("build-system", {})
        self.assertIn("requires", bs)
        self.assertIn("build-backend", bs)


if __name__ == "__main__":
    sys.exit(unittest.main())
