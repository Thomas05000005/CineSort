"""`scripts/generate_api_schema.py` ne doit ni mentir sur la version, ni annoncer OK a vide.

Constats d'audit couverts (lot « endpoints », 2026-08-31) :

- #37 (MINEUR) — la version applicative etait codee en dur (`"version":
  "v1.5.2-beta"`, L84) a cote du fichier `VERSION` et de `pyproject.toml:9`,
  eux verrouilles l'un a l'autre par `tests/test_pyproject_pep621_v77.py`.
  Troisieme copie, non gardee : au prochain bump, `docs/api/schema.json`
  annoncerait silencieusement l'ancienne version.
- #40 (MAJEUR) — la branche `except ImportError` retournait un schema VIDE
  (`"endpoints": {}, "reports": {}`) que `main()` ECRIVAIT quand meme sur
  `--out`, avant d'annoncer `[generate_api_schema] OK -> ...` et de rendre 0.
  MESURE du 2026-08-31 dans `.venv` (qui n'a pas pydantic) : rc=0, fichier de
  167 octets ecrit, message « OK » — la ou le fichier committe fait 20 915
  octets. Un schema vide ecrasait donc le vrai, sans aucun signal d'echec.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts import generate_api_schema as gen

_REPO_ROOT = Path(__file__).resolve().parent.parent


class VersionUniqueTests(unittest.TestCase):
    """#37 : la version du schema doit etre LUE, pas recopiee."""

    def test_la_version_du_schema_suit_le_fichier_version(self) -> None:
        attendu = "v" + (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(gen._schema_version(), attendu)

    def test_la_version_suit_un_bump_du_fichier_version(self) -> None:
        """Preuve que la valeur n'est pas figee : on bouge la source, la sortie suit.

        Sans la lecture du fichier `VERSION`, `_schema_version()` rend toujours
        la constante codee en dur et ce test echoue.
        """
        with TemporaryDirectory() as tmp:
            faux_root = Path(tmp)
            (faux_root / "VERSION").write_text("9.9.9-testbump\n", encoding="utf-8")
            with mock.patch.object(gen, "ROOT", faux_root):
                self.assertEqual(gen._schema_version(), "v9.9.9-testbump")


class SchemaVideTests(unittest.TestCase):
    """#40 : pydantic absent = echec bruyant, pas un fichier vide annonce OK."""

    def _lancer_sans_pydantic(self, sortie: Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        # `sys.modules[nom] = None` fait lever ImportError a l'import : c'est la
        # simulation exacte du venv minimal decrit par la docstring du script.
        with mock.patch.dict(sys.modules, {"pydantic": None}):
            with redirect_stdout(out), redirect_stderr(err):
                code = gen.main(["--out", str(sortie)])
        return code, out.getvalue(), err.getvalue()

    def test_pydantic_absent_rend_un_code_non_nul(self) -> None:
        with TemporaryDirectory() as tmp:
            sortie = Path(tmp) / "schema.json"
            code, out, err = self._lancer_sans_pydantic(sortie)
            self.assertNotEqual(code, 0, "rc=0 alors que le schema n'a pas pu etre construit")
            self.assertIn("pydantic", err)
            self.assertNotIn("OK", out)

    def test_pydantic_absent_n_ecrase_pas_le_schema_existant(self) -> None:
        with TemporaryDirectory() as tmp:
            sortie = Path(tmp) / "schema.json"
            temoin = '{"endpoints": {"start_plan": "schema reel"}}'
            sortie.write_text(temoin, encoding="utf-8")
            self._lancer_sans_pydantic(sortie)
            self.assertEqual(
                sortie.read_text(encoding="utf-8"),
                temoin,
                "un schema vide a ecrase le schema existant",
            )

    def test_chemin_nominal_ecrit_le_schema_et_rend_zero(self) -> None:
        """Cote pile : quand `build_schema` aboutit, `main()` ecrit et annonce OK.

        `build_schema` est double parce qu'aucun des deux venvs du poste n'a
        pydantic (mesure 2026-08-31) ; ce test garde le cablage de `main()`,
        pas le contenu des schemas Pydantic.
        """
        faux_schema = {"title": "faux", "endpoints": {"start_plan": {}}, "reports": {}}
        with TemporaryDirectory() as tmp:
            sortie = Path(tmp) / "sous_dossier" / "schema.json"
            out = io.StringIO()
            with mock.patch.object(gen, "build_schema", return_value=faux_schema):
                with redirect_stdout(out):
                    code = gen.main(["--out", str(sortie)])
            self.assertEqual(code, 0)
            self.assertIn("OK", out.getvalue())
            self.assertEqual(json.loads(sortie.read_text(encoding="utf-8")), faux_schema)


if __name__ == "__main__":
    unittest.main()
