# -*- coding: utf-8 -*-
"""Le SIXIEME ancrage de ruff : celui que le gate EXECUTE.

Le defaut
---------
`CLAUDE.md` dit que ruff est epingle en CINQ endroits, et
`test_ruff_version_is_identical_everywhere` les tient egaux :
`requirements-dev.txt`, `pyproject.toml`, `.pre-commit-config.yaml`, `uv.lock`,
`CLAUDE.md`.

Aucun des cinq n'est ce que le gate LANCE. `check_project.bat` resout
`.venv313\\Scripts\\python.exe`, sinon `.venv\\Scripts\\python.exe`, puis appelle
`-m ruff` : il prend la version qui se trouve la, quelle qu'elle soit.

MESURE du 2026-08-31 sur la machine de developpement :

    .venv313  ruff 0.15.6      <- choisi EN PREMIER par le .bat
    .venv     ruff 0.15.13
    CI        ruff 0.16.3

    `ruff format --check .`  ->  1140 fichiers en local
                                 1192 avec la version epinglee
                                 soit 52 fichiers INVISIBLES au gate.

Un gate plus permissif que la CI ne protege pas de la CI : il rend un vert que
la CI peut contredire. C'est exactement l'incident du 2026-08-02 (hook 0.15.6,
lock 0.15.16, CI 0.15.22), qui avait motive le garde des cinq — et que le garde
des cinq ne pouvait pas voir, parce qu'il regarde des FICHIERS DE CONFIGURATION
et jamais l'outil execute.

Pourquoi un helper Python plutot qu'une ligne de plus dans le .bat
------------------------------------------------------------------
Un `.bat` n'est pas testable : on ne peut en asserter que des SOUS-CHAINES, et
`assertIn("-m ruff check", ...)` reste vert quand la ligne est commentee. Le
helper, lui, s'exerce dans les DEUX SENS. C'est le meme parti que
`scripts/check_python_compile.py`, deja appele par le gate.

Et il tourne avec l'interpreteur QUE LE GATE UTILISE : la version qu'il lit est
celle que `-m ruff` lancera, pas celle d'un autre environnement.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_ruff_version import verifier, version_epinglee, version_installee

_RACINE = Path(__file__).resolve().parents[1]


class LAncrageExecuteEstGardeTests(unittest.TestCase):
    def test_la_version_epinglee_est_LUE(self) -> None:
        """Contre-epreuve du lecteur : s'il rendait toujours None, `verifier`
        echouerait toujours et le message ne dirait rien d'utile.
        """
        version = version_epinglee(_RACINE)

        self.assertIsNotNone(version, "requirements-dev.txt n'epingle plus ruff de facon lisible")
        self.assertRegex(str(version), r"^\d+\.\d+\.\d+$")

    def test_une_version_DIVERGENTE_fait_echouer(self) -> None:
        """Le sens qui compte. Sans lui, le helper pourrait rendre 0 quoi qu'il
        arrive et le gate resterait aussi permissif qu'avant.
        """
        faux = _RACINE / "tests" / "fixtures_ancrage_ruff"
        with self.subTest("version impossible"):
            racine = self._racine_factice("ruff==0.0.1")
            code, message = verifier(racine)
            self.assertEqual(code, 1)
            self.assertIn("0.0.1", message)
        self.assertFalse(faux.exists(), "aucune fixture ne doit rester sur disque")

    def test_la_version_REELLE_est_acceptee(self) -> None:
        """L'autre sens : le helper ne doit pas refuser un environnement sain.

        On construit la racine factice a partir de la version REELLEMENT
        installee pour cet interpreteur : le test reste vrai quel que soit
        l'environnement, et il echoue si `verifier` refusait tout.
        """
        installee = version_installee()
        if installee is None:
            self.skipTest("ruff n'est pas installe pour cet interpreteur")

        code, message = verifier(self._racine_factice(f"ruff=={installee}"))

        self.assertEqual(code, 0, message)
        self.assertIn("conforme", message)

    def test_le_gate_APPELLE_le_helper(self) -> None:
        """L'assertion lexicale, assumee comme faible : elle dit que le gate
        cite le helper, pas qu'il l'honore. C'est `if errorlevel 1 exit /b 1`
        qui le rend bloquant, donc on exige les deux, ADJACENTS — un
        `exit /b 1` situe cent lignes plus bas n'aurait aucun rapport.
        """
        gate = (_RACINE / "check_project.bat").read_text(encoding="utf-8")
        lignes = [ligne.strip() for ligne in gate.splitlines()]

        try:
            index = next(i for i, ligne in enumerate(lignes) if "check_ruff_version.py" in ligne)
        except StopIteration:
            self.fail("check_project.bat n'appelle pas scripts/check_ruff_version.py")

        suivante = lignes[index + 1] if index + 1 < len(lignes) else ""
        self.assertIn("errorlevel 1", suivante, f"l'appel n'est pas rendu bloquant : {suivante!r}")
        self.assertIn("exit /b 1", suivante)

    def test_le_gate_reste_en_ASCII(self) -> None:
        """Un `.bat` est lu par `cmd` dans la codepage OEM. Un caractere UTF-8
        dans un commentaire y est au mieux illisible, au pire un piege pour la
        prochaine edition. Le fichier n'en portait aucun avant ce lot.
        """
        brut = (_RACINE / "check_project.bat").read_bytes()

        non_ascii = [octet for octet in brut if octet > 127]
        self.assertEqual(non_ascii, [], f"{len(non_ascii)} octet(s) non-ASCII dans check_project.bat")

    @staticmethod
    def _racine_factice(ligne_ruff: str) -> Path:
        """Une racine jetable ne portant qu'un `requirements-dev.txt`."""
        import tempfile

        from tests._helpers import cleanup_test_tree

        dossier = Path(tempfile.mkdtemp(prefix="cinesort_ancrage_ruff_"))
        unittest.addModuleCleanup(cleanup_test_tree, dossier)
        (dossier / "requirements-dev.txt").write_text(f"{ligne_ruff}\n", encoding="utf-8")
        return dossier


if __name__ == "__main__":
    unittest.main()
