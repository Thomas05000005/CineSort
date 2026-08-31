"""Le garde annonce par `gen_endpoints_doc` doit REFUSER d'ecrire une doc fausse.

Constat #38 (CRITIQUE, lot « endpoints ») : le commentaire L33 du generateur
annonce « la generation ECHOUE avec un WARNING si trop d'orphelins ». Mesure :
`grep -niE "warn|echou|fail|orphan|raise|sys.exit|return 1"` sur le fichier
entier ne rendait que ce commentaire, les orphelins ajoutes au markdown, et le
`raise SystemExit(main())` final — `main()` renvoyant `return 0` en dur.

Ce fichier verifie le COMPORTEMENT, pas la presence d'un symbole : on injecte
une donnee curatee perimee (un nom de categorie ou un exemple curl qui ne
correspond a aucune route servie) et on exige que `main()` :
  1. rende un code retour non nul,
  2. explique le probleme sur stderr,
  3. n'ecrive PAS le fichier de doc.

Sans garde, les trois assertions echouent : `main()` rendait 0, n'ecrivait rien
sur stderr, et livrait la doc fausse.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts import gen_endpoints_doc as gen


class GardeDonneesPerimeesTests(unittest.TestCase):
    def _lancer_main_isole(self, racine: Path) -> tuple[int, str, str]:
        """Lance `main()` avec `_PROJECT_ROOT` redirige vers un dossier jetable."""
        err = io.StringIO()
        out = io.StringIO()
        with mock.patch.object(gen, "_PROJECT_ROOT", racine):
            with redirect_stderr(err), redirect_stdout(out):
                code = gen.main()
        return code, out.getvalue(), err.getvalue()

    def test_une_categorie_qui_liste_un_endpoint_disparu_fait_echouer(self) -> None:
        categories_perimees = [*gen._CATEGORIES, ("99. Fantome", ["endpoint_qui_nexiste_pas"])]
        with TemporaryDirectory() as tmp:
            racine = Path(tmp)
            with mock.patch.object(gen, "_CATEGORIES", categories_perimees):
                code, _out, err = self._lancer_main_isole(racine)
            self.assertNotEqual(code, 0, "main() a rendu 0 malgre une categorie perimee")
            self.assertIn("endpoint_qui_nexiste_pas", err)
            self.assertFalse(
                (racine / "docs" / "api" / "ENDPOINTS.md").exists(),
                "la doc fausse a quand meme ete ecrite",
            )

    def test_un_exemple_curl_vers_une_route_absente_fait_echouer(self) -> None:
        exemples_perimes = [
            {
                "title": "1. Route disparue",
                "method": "route_absente_du_dispatcher",
                "body": "{}",
                "response": '{"ok": true}',
            }
        ]
        with TemporaryDirectory() as tmp:
            racine = Path(tmp)
            with mock.patch.object(gen, "_EXAMPLES", exemples_perimes):
                code, _out, err = self._lancer_main_isole(racine)
            self.assertNotEqual(code, 0, "main() a rendu 0 malgre un exemple curl mort")
            self.assertIn("route_absente_du_dispatcher", err)
            self.assertFalse(
                (racine / "docs" / "api" / "ENDPOINTS.md").exists(),
                "la doc fausse a quand meme ete ecrite",
            )

    def test_sans_donnee_perimee_la_generation_reussit_et_ecrit(self) -> None:
        """Cote pile du garde : il ne doit pas mordre l'etat sain du depot."""
        with TemporaryDirectory() as tmp:
            racine = Path(tmp)
            code, out, err = self._lancer_main_isole(racine)
            self.assertEqual(code, 0, f"generation refusee sur un depot sain : {err}")
            cible = racine / "docs" / "api" / "ENDPOINTS.md"
            self.assertTrue(cible.exists())
            self.assertIn("OK", out)


if __name__ == "__main__":
    unittest.main()
