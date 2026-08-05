"""Un cache OMDb surdimensionne ne doit pas s'installer a demeure.

Remarque de revue sur la PR #546. `read_text_bounded` REFUSE de lire au-dela de
`_CACHE_MAX_BYTES` (CWE-400 : `read_text()` alloue tout en RAM avant le parse).
Le client repartait alors sur un cache vide — correct — mais laissait le fichier
en place. Deux couts qui ne s'arretent jamais :

  * l'avertissement se repete a CHAQUE demarrage ;
  * l'espace disque n'est jamais recupere, puisque la sauvegarde suivante ecrit
    un fichier NEUF a cote.

Le fichier est desormais ecarte vers un emplacement UNIQUE : au plus une copie
perimee a la fois, donc croissance bornee, et il en reste une a inspecter.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cinesort.infra import omdb_client
from cinesort.infra.omdb_client import OmdbClient


class CacheSurdimensionneTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cs_omdb_546_")
        self.dossier = Path(self._tmp.name)
        self.cache = self.dossier / "omdb_cache.json"
        self.addCleanup(self._tmp.cleanup)

    def _client(self) -> OmdbClient:
        return OmdbClient(api_key="k", cache_path=self.cache)

    def _ecrire_trop_gros(self) -> int:
        """Ecrit un JSON VALIDE mais au-dela de la borne."""
        bourrage = "x" * (omdb_client._CACHE_MAX_BYTES + 1024)
        self.cache.write_text(json.dumps({"tt1": {"title": bourrage}}), encoding="utf-8")
        return self.cache.stat().st_size

    def test_le_fichier_trop_gros_est_ECARTE_du_chemin_de_cache(self) -> None:
        taille = self._ecrire_trop_gros()
        self.assertGreater(taille, omdb_client._CACHE_MAX_BYTES)

        client = self._client()

        self.assertEqual(client._cache, {}, "le cache doit repartir a vide")
        self.assertFalse(self.cache.exists(), "le fichier surdimensionne occupe encore le chemin du cache")
        ecarte = self.cache.with_suffix(self.cache.suffix + ".oversized")
        self.assertTrue(ecarte.exists(), "ecarte sans laisser de copie : plus rien a inspecter")
        self.assertEqual(ecarte.stat().st_size, taille, "la copie ecartee doit etre INTACTE")

    def test_la_croissance_reste_BORNEE_sur_plusieurs_occurrences(self) -> None:
        """Le point de la remarque : sans emplacement unique, ca s'empile."""
        for _ in range(3):
            self._ecrire_trop_gros()
            self._client()

        ecartes = sorted(p.name for p in self.dossier.iterdir() if ".oversized" in p.name)
        self.assertEqual(len(ecartes), 1, f"une copie ecartee par occurrence : {ecartes}")

    def test_un_cache_de_taille_NORMALE_n_est_pas_touche(self) -> None:
        """La garde ne doit pas se declencher sur le cas nominal."""
        self.cache.write_text(json.dumps({"tt1": {"title": "Heat"}}), encoding="utf-8")

        client = self._client()

        self.assertIn("tt1", client._cache)
        self.assertTrue(self.cache.exists(), "un cache valide a ete ecarte a tort")
        self.assertFalse(self.cache.with_suffix(self.cache.suffix + ".oversized").exists())

    def test_un_cache_ILLISIBLE_n_est_PAS_ecarte(self) -> None:
        """Seule la taille declenche la mise a l'ecart, pas n'importe quel echec.

        Un JSON corrompu de taille normale reste en place : l'ecarter
        elargirait une action sur fichier a des causes qu'elle n'adresse pas.
        """
        self.cache.write_text("{ pas du json", encoding="utf-8")

        client = self._client()

        self.assertEqual(client._cache, {})
        self.assertTrue(self.cache.exists(), "un cache corrompu mais PETIT ne doit pas etre deplace")
        self.assertFalse(self.cache.with_suffix(self.cache.suffix + ".oversized").exists())


if __name__ == "__main__":
    unittest.main()
