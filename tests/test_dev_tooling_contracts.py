from __future__ import annotations

import re
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
        cls.uv_lock = (root / "uv.lock").read_text(encoding="utf-8")
        cls.claude_md = (root / "CLAUDE.md").read_text(encoding="utf-8")
        cls.compile_helper = (root / "scripts" / "check_python_compile.py").read_text(encoding="utf-8")
        cls.check_project = (root / "check_project.bat").read_text(encoding="utf-8")
        cls.dev_readme = (root / "docs" / "README_DEV.md").read_text(encoding="utf-8")
        cls.ci_workflow = (root / ".github" / "workflows" / "windows-ci.yml").read_text(encoding="utf-8")
        cls.sign_script = (root / "scripts" / "sign_windows_release.ps1").read_text(encoding="utf-8")

    def test_requirements_dev_pins_quality_toolchain(self) -> None:
        self.assertIn("-r requirements.txt", self.requirements_dev)
        # ruff est EPINGLE EXACTEMENT depuis le 2026-08-02 (plus fort qu'un
        # plancher `>=`) : une borne flottante avait mis la CI au rouge sur main,
        # trois versions differentes cohabitant entre le hook pre-commit,
        # uv.lock et la resolution fraiche de la CI.
        self.assertRegex(
            self.requirements_dev,
            r"ruff==\d+\.\d+\.\d+",
            "ruff doit rester epingle exactement, pas ramene a une borne flottante",
        )
        self.assertIn("coverage>=", self.requirements_dev)
        self.assertIn("pre-commit>=", self.requirements_dev)

    def test_le_plugin_pytest_playwright_accompagne_la_bibliotheque(self) -> None:
        """La fixture `page` vient du PLUGIN, pas de la bibliotheque `playwright`.

        Ce sont deux paquets distincts, et n'installer que le second ne produit
        pas un echec lisible : les tests marques `runtime` partent en
        `ERROR at setup` avec « fixture 'page' not found ». Or le CLAUDE.md du
        depot le rappelle — un `ERROR at setup` n'apparait dans AUCUN grep
        `FAILED`.

        MESURE qui motive ce garde (2026-08-05) : le quality gate `verify`
        (`windows-ci`, qui installe depuis `requirements-dev.txt`) etait rouge
        sur les **29 derniers runs de `main`**, et sur les 5 PR de la journee,
        pour cette seule raison :

            8417 passed, 18 skipped, 2 xfailed, 52 errors

        Zero echec, 52 erreurs. `ci.yml` installait le plugin a la main de son
        cote (`uv pip install --system pytest-playwright`), donc son propre
        `Lint, Tests, Build` restait vert : le manque etait invisible la ou on
        regardait, et fatal la ou on ne regardait plus.

        Le test porte sur l'ENVIRONNEMENT, pas sur le texte d'un fichier : la ou
        `playwright` est installe, le plugin doit l'etre aussi. Il aurait donc
        nomme la cause en une ligne au lieu de 52 erreurs opaques.
        """
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            self.skipTest("playwright absent : environnement sans les extras dev")
        self.assertIsNotNone(
            importlib.util.find_spec("pytest_playwright"),
            "`playwright` est installe mais pas `pytest-playwright` : la fixture "
            "`page` sera introuvable et tous les tests `runtime` partiront en "
            "ERROR at setup, sans apparaitre dans un grep FAILED. "
            "Declarer `pytest-playwright` dans requirements-dev.txt ET dans "
            "pyproject.toml [project.optional-dependencies].dev.",
        )

    def test_ruff_version_is_identical_everywhere(self) -> None:
        """Les CINQ endroits ou ruff est epingle doivent viser LA MEME version.

        Sans cette garde, un developpeur formate avec une version et la CI
        rejette avec une autre — situation trouvee le 2026-08-02 (hook 0.15.6,
        lock 0.15.16, CI 0.15.22).

        Ce test n'en couvrait que DEUX — `requirements-dev.txt` et le hook
        pre-commit — alors que `CLAUDE.md` le nommait comme le gardien de
        quatre. Un document qui designe un test faisant MOINS que ce qu'il
        annonce est pire que pas de document : il donne une garantie qui
        n'existe pas.

        `CLAUDE.md` compte lui-meme parmi les cinq, et c'est le plus cher a
        laisser deriver : il se charge AUTOMATIQUEMENT dans le contexte de
        chaque session et porte la commande que tout le monde copie. MESURE du
        2026-08-06 : le depot etait a `0.16.1`, les quatre autres endroits
        synchronises et ce test vert, pendant que `CLAUDE.md` annoncait
        `uvx ruff@0.15.22`. Les deux versions ne voient meme pas le meme
        perimetre — 1018 fichiers contre 1068 — donc une session qui suivait le
        fichier verifiait autre chose que la CI, et un `format` sans `--check`
        aurait reformate le depot avec la mauvaise version.
        """
        attendue = re.search(r"ruff==(\d+\.\d+\.\d+)", self.requirements_dev)
        self.assertIsNotNone(attendue, "ruff doit etre epingle dans requirements-dev.txt")
        reference = attendue.group(1)

        hook = re.search(r"ruff-pre-commit\s*\n(?:\s*#.*\n)*\s*rev:\s*v(\d+\.\d+\.\d+)", self.pre_commit)
        self.assertIsNotNone(hook, "le hook ruff-pre-commit doit declarer une rev versionnee")
        pyproject = re.search(r'"ruff==(\d+\.\d+\.\d+)"', self.pyproject)
        self.assertIsNotNone(pyproject, "ruff doit etre epingle dans pyproject.toml [dev]")
        lock = re.search(r'name = "ruff"\s*\nversion = "(\d+\.\d+\.\d+)"', self.uv_lock)
        self.assertIsNotNone(lock, "uv.lock doit contenir le paquet ruff avec sa version")
        citees = sorted(set(re.findall(r"ruff[@=]{1,2}(\d+\.\d+\.\d+)", self.claude_md)))
        self.assertTrue(citees, "CLAUDE.md doit citer la version de ruff (commandes + section Pieges)")

        trouvees = {
            ".pre-commit-config.yaml": [hook.group(1)],
            "pyproject.toml": [pyproject.group(1)],
            "uv.lock": [lock.group(1)],
            "CLAUDE.md": citees,
        }
        divergents = {ou: v for ou, v in trouvees.items() if v != [reference]}
        self.assertEqual(
            divergents,
            {},
            f"ruff doit etre epingle a {reference} (requirements-dev.txt) PARTOUT. "
            f"Divergences : {divergents}. CLAUDE.md compte parmi les cinq : il se "
            "charge dans chaque session, donc une version perimee y est heritee a "
            "chaque demarrage, avec l'autorite du fichier de reference.",
        )

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
        self.assertIn("--fail-under=75", self.check_project)
        # Les E2E/live/stress sont ignores dans ce gate
        self.assertIn("--ignore=tests/e2e", self.check_project)
        self.assertIn("--ignore=tests/live", self.check_project)

    def test_ci_workflow_documents_windows_quality_build_and_optional_signing(self) -> None:
        self.assertIn("windows-latest", self.ci_workflow)
        self.assertIn('python-version: "3.13"', self.ci_workflow)
        self.assertIn("workflow_dispatch", self.ci_workflow)
        self.assertIn("check_project.bat", self.ci_workflow)
        self.assertIn("build_windows.bat", self.ci_workflow)
        # v1.0.0-beta : tolere n'importe quelle version >= v4 (Dependabot
        # bumps periodiques) ET SHA-pinning (OpenSSF Scorecard). On verifie
        # juste que l'action est utilisee.
        self.assertRegex(
            self.ci_workflow,
            r"actions/upload-artifact@(v\d+|[a-f0-9]{40}( # v\d+)?)",
        )
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
