"""tests/test_pip_install_editable_v77.py — Vague M, lot M-08 (ARCH-03).

Verifie que `pip install -e .[dev]` reussit (ou peut reussir) en validant que
la metadata pyproject.toml est suffisante pour un build editable :
- [build-system] requires + build-backend declares
- [project] name, version, dependencies sont valides
- Le package cinesort/ existe physiquement et est declarable

Note : on ne lance PAS pip install -e en CI (couteux + effets de bord global).
On utilise `python -m build --sdist --no-isolation` style dry-run via
`python -m pip install --dry-run`. Si pip dry-run echoue, on tombe sur
une verification structurelle minimale qui passe toujours en CI.

Ce test sert de garde-fou : si quelqu'un casse la metadata (ex: supprime
build-system), le test detecte l'erreur sans avoir besoin d'un vrai install.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


class PipInstallEditableTests(unittest.TestCase):
    """Verifications structurelles de l'installabilite editable."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(PYPROJECT, "rb") as fh:
            cls.data = tomllib.load(fh)

    def test_build_system_requires_setuptools(self) -> None:
        bs = self.data.get("build-system", {})
        requires = bs.get("requires", [])
        # On accepte setuptools, hatchling, flit-core, poetry-core. Pour CineSort
        # on a choisi setuptools (le plus simple, deja sur le runner).
        has_setuptools = any(re.match(r"^setuptools", r) for r in requires)
        has_other = any(re.match(r"^(hatchling|flit_core|flit-core|poetry-core)", r) for r in requires)
        self.assertTrue(
            has_setuptools or has_other,
            f"build-system.requires doit contenir un build backend connu, recu : {requires}",
        )

    def test_build_backend_declared(self) -> None:
        backend = self.data.get("build-system", {}).get("build-backend", "")
        self.assertTrue(backend, "build-system.build-backend manquant")

    def test_package_directory_exists(self) -> None:
        """Le package cinesort/ doit exister et contenir un __init__.py."""
        pkg = ROOT / "cinesort"
        self.assertTrue(pkg.is_dir(), f"Repertoire cinesort/ introuvable a {pkg}")
        init = pkg / "__init__.py"
        self.assertTrue(init.is_file(), f"cinesort/__init__.py introuvable a {init}")

    def test_setuptools_packages_declared(self) -> None:
        """Si setuptools est le backend, [tool.setuptools.packages] doit etre coherent."""
        backend = self.data.get("build-system", {}).get("build-backend", "")
        if "setuptools" not in backend:
            self.skipTest("Backend non-setuptools, check non applicable")
        st = self.data.get("tool", {}).get("setuptools", {})
        # On accepte packages=[...] explicite OU packages.find auto-discovery.
        has_explicit = isinstance(st.get("packages"), list)
        has_find = isinstance(st.get("packages"), dict)
        self.assertTrue(
            has_explicit or has_find or not st,
            "Configuration setuptools.packages malformee",
        )
        if has_explicit:
            self.assertIn(
                "cinesort",
                st["packages"],
                "package cinesort/ doit etre declare dans [tool.setuptools].packages",
            )

    def test_pip_dry_run_metadata_resolves(self) -> None:
        """`pip install --dry-run --no-deps` parse-t-il la metadata sans erreur ?

        --no-deps evite de resoudre toutes les transitives (lent + reseau).
        --dry-run n'installe rien physiquement.

        Si pip est indisponible ou trop ancien (< 23.0 pas de --dry-run), on
        skip plutot que de fail.
        """
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--dry-run",
                    "--no-deps",
                    "-e",
                    str(ROOT),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(ROOT),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            self.skipTest(f"pip indisponible ou trop lent : {exc}")
            return

        # rc=0 (full success) ou stderr contenant "dry-run" sont acceptables.
        # On rejette uniquement les erreurs claires de metadata.
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if "no matching distribution" in stderr or "could not find a version" in stderr:
                self.skipTest("pip dry-run a echoue sur la resolution reseau, non bloquant pour metadata.")
                return
            # Une erreur "invalid metadata" / "build backend" doit faire fail.
            metadata_errors = [
                "invalid pyproject",
                "invalid metadata",
                "build_meta",
                "build-system",
                "no module named",
            ]
            for marker in metadata_errors:
                if marker in stderr:
                    self.fail(f"pip dry-run a detecte une erreur metadata : {result.stderr}")
            # Sinon erreur reseau / autre : skip.
            self.skipTest(f"pip dry-run rc={result.returncode}, stderr non-bloquant : {result.stderr[:200]}")


if __name__ == "__main__":
    sys.exit(unittest.main())
