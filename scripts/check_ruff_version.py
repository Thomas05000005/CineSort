"""Le gate local doit lancer LA MEME version de ruff que la CI.

Le defaut
---------
`check_project.bat` resout `.venv313\\Scripts\\python.exe`, sinon
`.venv\\Scripts\\python.exe`, puis appelle `-m ruff`. Il n'epingle donc RIEN : il
prend la version qui se trouve la. Les cinq points epingles du depot
(`requirements-dev.txt`, `pyproject.toml`, `.pre-commit-config.yaml`, `uv.lock`,
`CLAUDE.md`) valent 0.16.3, et `test_ruff_version_is_identical_everywhere` les
garde — mais aucun d'eux n'est ce que le gate execute.

MESURE du 2026-08-31 sur la machine de developpement :

    .venv313  ruff 0.15.6     <- choisi en premier par le .bat
    .venv     ruff 0.15.13
    epingle   ruff 0.16.3     <- ce que la CI lance

    ruff format --check .   ->  1140 fichiers en local, 1192 avec la version
                                epinglee, soit 52 fichiers INVISIBLES au gate.

Un gate qui voit moins de fichiers que la CI ne protege pas de la CI : il rend
un vert que la CI peut contredire, et c'est precisement le motif de l'incident
du 2026-08-02 (hook 0.15.6, lock 0.15.16, CI 0.15.22).

Pourquoi ce script et pas une ligne de plus dans le .bat
--------------------------------------------------------
Le batch n'est pas testable. Ce helper l'est : `tests/test_ancrage_ruff.py`
l'exerce dans les deux sens (version conforme -> 0, version divergente -> 1),
ce qu'aucune assertion lexicale sur le `.bat` ne peut faire. C'est le meme
parti que `scripts/check_python_compile.py`, deja appele par le gate.

Il tourne avec l'interpreteur QUE LE GATE UTILISE : la version qu'il lit est
donc exactement celle que `-m ruff` lancera, pas celle d'un autre environnement.
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

#: `ruff==0.16.3` dans `requirements-dev.txt`. Ce fichier est la SOURCE : les
#: quatre autres points epingles sont deja tenus egaux a lui par
#: `test_ruff_version_is_identical_everywhere`, donc en suivre un seul suffit et
#: evite d'inventer une sixieme verite.
#:
#: MEME FORME que ce garde-la (`\d+\.\d+\.\d+`), et c'est la raison du choix :
#: deux motifs differents pour lire la meme epingle seraient une seconde source
#: de verite en miniature.
#:
#: La premiere version tolerait un nombre libre de composants
#: (`[0-9]+(?:\.[0-9]+)*`). Codacy l'a signalee « expression reguliere
#: inefficace », soit un ReDoS. MESURE : le retour arriere n'a PAS lieu — 0,12 ms
#: a dix composants suivis d'un caractere fautif, ~0 au-dela. C'est structurel :
#: un ReDoS demande deux sous-expressions quantifiees capables de consommer LES
#: MEMES caracteres, et ici le point litteral separe les deux, donc les points de
#: decoupe sont forces. Le signalement porte sur la FORME du motif, pas sur son
#: comportement. Le motif change quand meme, pour la coherence ci-dessus — pas
#: parce que l'alerte etait fondee.
_EPINGLE = re.compile(r"^ruff==(\d+\.\d+\.\d+)\s*$", re.M)


def version_epinglee(racine: Path) -> str | None:
    """La version exigee, lue dans `requirements-dev.txt`. None si introuvable."""
    fichier = racine / "requirements-dev.txt"
    try:
        texte = fichier.read_text(encoding="utf-8")
    except OSError:
        return None
    trouve = _EPINGLE.search(texte)
    return trouve.group(1) if trouve else None


def version_installee() -> str | None:
    """La version de ruff visible par CET interpreteur. None si absente."""
    try:
        return metadata.version("ruff")
    except metadata.PackageNotFoundError:
        return None


def verifier(racine: Path) -> tuple[int, str]:
    """(code de sortie, message). 0 = conforme."""
    attendue = version_epinglee(racine)
    if attendue is None:
        return 1, (
            "[ERREUR] Impossible de lire la version epinglee de ruff dans "
            "requirements-dev.txt. Le gate ne peut pas garantir qu'il lance la "
            "meme version que la CI."
        )

    installee = version_installee()
    if installee is None:
        return 1, (
            f"[ERREUR] ruff n'est pas installe pour cet interpreteur. "
            f"Lance : {sys.executable} -m pip install -r requirements-dev.txt"
        )

    if installee != attendue:
        return 1, (
            f"[ERREUR] ruff {installee} est installe, la CI lance {attendue}.\n"
            f"          Un gate qui lance une AUTRE version rend un vert que la CI "
            f"peut contredire :\n"
            f"          au 2026-08-31, l'ecart valait 52 fichiers de moins vus par "
            f"`ruff format --check`.\n"
            f"          Lance : {sys.executable} -m pip install -r requirements-dev.txt"
        )

    return 0, f"[INFO] ruff {installee} — conforme a la version epinglee."


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--racine", type=Path, default=Path(__file__).resolve().parents[1])
    args = parseur.parse_args(argv)

    code, message = verifier(args.racine)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
