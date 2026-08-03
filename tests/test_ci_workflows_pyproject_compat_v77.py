"""tests/test_ci_workflows_pyproject_compat_v77.py — Vague M, lot M-08 (ARCH-03).

Audit les workflows .github/workflows/*.yml pour verifier qu'aucun n'utilise
de patterns incompatibles avec la migration progressive vers pyproject.toml :

1. Tout workflow qui installe des paquets Python doit tirer les dependances du
   PROJET depuis une source declaree du depot (`-r requirements*.txt`, ou
   `pip install .` / `-e .[dev]` cote pyproject). Les seuls paquets qu'un
   workflow a le droit de nommer a la main sont des OUTILS de CI, listes
   explicitement dans `ALLOWED_CI_TOOLS` ci-dessous (bandit, mypy, pip-audit,
   nuitka, pytest-playwright...). C'est la garantie anti-drift : la CI ne doit
   jamais installer une dependance de prod avec une version differente de celle
   qui est declaree dans requirements*.txt.

   Le contrat porte sur CE QUI est installe, pas sur le front-end utilise :
   `pip install`, `python -m pip install` et `uv pip install --system`
   (adopte en CI en 2026-06 pour la vitesse de resolution) sont equivalents.
   La version precedente de ce test epinglait la FORME `pip install -r ...`
   avec le `-r` colle a `install` ; elle est passee au rouge le jour de la
   migration vers uv sans qu'aucun contrat reel ne soit viole.

2. Chaque fichier passe a `-r` doit exister dans le depot (attrape un
   requirements renomme/supprime qui casserait l'install en CI).

3. ci.yml doit exister, cibler Python 3.13, installer depuis les requirements
   et executer des tests pytest.

Ces verifications attrapent toute regression qui casserait la CI suite a
des changements pyproject.toml.
"""

from __future__ import annotations

import re
import shlex
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# Outils de CI que les workflows ont le droit de nommer a la main : ils ne font
# pas partie du runtime de l'application, donc ils n'ont rien a faire dans
# requirements.txt. Toute AUTRE nom de paquet installe en dur fait rougir le
# test — c'est le point 2 du docstring (anti-drift CI/local).
ALLOWED_CI_TOOLS = frozenset(
    {
        # gestionnaires / plomberie
        "pip",
        "setuptools",
        "uv",
        "wheel",
        # qualite & securite
        "bandit",
        "coverage",
        "import-linter",
        "mypy",
        "pip-audit",
        "ruff",
        # tests
        "pytest",
        "pytest-cov",
        "pytest-playwright",
        "pytest-timeout",
        # packaging (release.yml, chemin Nuitka)
        "nuitka",
        "ordered-set",
        "zstandard",
    }
)

# `pip install`, `python -m pip install`, `uv pip install --system` : seul le
# segment `pip install` est signifiant, les prefixes sont interchangeables.
# `\bpip\s+install\b` ne matche pas `pip-audit ...` (le tiret casse le \b+\s).
_PIP_INSTALL_RE = re.compile(r"\bpip\s+install\b(?P<args>[^\r\n]*)")

# Debut d'un nom de distribution dans une specification PEP 508 :
# `bandit[sarif,toml]>=1.7,<2` -> `bandit`.
_DIST_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")


def _list_workflows() -> list[Path]:
    if not WORKFLOWS_DIR.is_dir():
        return []
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


def _strip_comments(text: str) -> str:
    """Retire les commentaires YAML/shell et recolle les continuations de ligne.

    Indispensable : ci.yml documente `uv pip install --system` DANS un
    commentaire ; sans ce nettoyage la phrase francaise qui suit serait lue
    comme une liste de paquets.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        # Commentaire de fin de ligne (` # ...`), jamais colle a un argument.
        cut = raw.find(" #")
        lines.append(raw[:cut] if cut != -1 else raw)
    joined = "\n".join(lines)
    # Continuations pwsh (`) et bash (\) : la commande d'install peut deborder.
    return re.sub(r"[`\\][ \t]*\r?\n[ \t]*", " ", joined)


def _dist_name(spec: str) -> str:
    match = _DIST_NAME_RE.match(spec.strip().strip("\"'"))
    name = match.group(0) if match else spec
    return name.lower().replace("_", "-")


def _parse_install(args: str) -> tuple[list[str], bool, list[str]]:
    """Decompose les arguments d'un `pip install`.

    Retourne (fichiers requirements references, installe-t-il le projet local,
    paquets nommes a la main).
    """
    try:
        tokens = shlex.split(args)
    except ValueError:  # guillemet non ferme (ligne tronquee) : on degrade
        tokens = args.split()

    req_files: list[str] = []
    local_project = False
    packages: list[str] = []

    iterator = iter(tokens)
    for token in iterator:
        if token in {"-r", "--requirement"}:
            req_files.append(next(iterator, ""))
        elif token.startswith("-r") and len(token) > 2:
            req_files.append(token[2:])
        elif token in {"-e", "--editable"}:
            next(iterator, "")  # le chemin qui suit est le projet lui-meme
            local_project = True
        elif token.startswith("-"):
            continue  # flag neutre : --system, --upgrade, --no-deps...
        elif token == "." or token.startswith("./") or token.startswith(".["):
            local_project = True
        else:
            packages.append(token)
    return req_files, local_project, packages


def _installs_in(text: str) -> list[tuple[list[str], bool, list[str]]]:
    clean = _strip_comments(text)
    return [_parse_install(m.group("args")) for m in _PIP_INSTALL_RE.finditer(clean)]


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
        """Aucun workflow ne doit installer un paquet hors manifeste declare.

        Le contrat verifie CE QUI est installe (le nom des distributions), pas
        la forme de la ligne de commande : le front-end peut etre `pip`,
        `python -m pip` ou `uv pip` sans que le contrat change. Chaque paquet
        nomme en dur doit etre un outil de CI allowliste ; tout le reste doit
        venir d'un `-r requirements*.txt` ou d'une install du projet local.

        Plus aucune exemption par nom de fichier : un workflow sans
        `pip install` ne produit simplement aucune invocation a verifier, ce
        qui evite qu'un workflow exempte cache un vrai drift.
        """
        failures: list[str] = []
        for wf in _list_workflows():
            text = wf.read_text(encoding="utf-8")
            for req_files, local_project, packages in _installs_in(text):
                for spec in packages:
                    if _dist_name(spec) not in ALLOWED_CI_TOOLS:
                        failures.append(
                            f"{wf.name}: paquet installe en dur hors manifeste : {spec!r} "
                            f"(ajouter a requirements*.txt, ou a ALLOWED_CI_TOOLS si c'est un outil de CI)"
                        )
                for req in req_files:
                    if not (ROOT / req).is_file():
                        failures.append(f"{wf.name}: `-r {req}` reference un fichier absent du depot")
                if not req_files and not local_project and not packages:
                    failures.append(f"{wf.name}: `pip install` sans aucune cible exploitable")

        self.assertEqual(
            failures,
            [],
            "Installs de workflow non conformes :\n" + "\n".join(failures),
        )

    def test_ci_yml_installs_requirements_or_pyproject(self) -> None:
        """ci.yml doit installer les deps du projet depuis un manifeste declare.

        Accepte indifferemment `-r requirements*.txt`, `pip install .` et
        `-e .[dev]`, avec n'importe quels flags intercales (`--system` de uv,
        `--upgrade`, ...). Ce qui est refuse, c'est une CI qui ne lit AUCUN
        manifeste et re-declare les dependances a la main.
        """
        ci = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        installs = _installs_in(ci)
        from_manifest = [(req_files, local) for req_files, local, _pkgs in installs if req_files or local]
        self.assertTrue(
            from_manifest,
            "ci.yml n'installe ni requirements*.txt ni le projet local (-e .[dev] / .) ; "
            f"invocations `pip install` vues : {installs}",
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
