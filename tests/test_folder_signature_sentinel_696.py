"""Un dossier INACCESSIBLE ne doit pas se confondre avec un dossier VIDE.

Issue #696. `folder_signature` rendait `sha1(b"")` sur echec de `os.scandir`
— exactement la signature d'un dossier vide. Le cache incremental dossier
decide d'un HIT sur la seule egalite des signatures :

    if cache_entry.get("folder_sig") == folder_sig:   # -> reutilise les rows

Consequence : un dossier PEUPLE momentanement illisible (blip NAS/SMB,
permission, disparition transitoire) prenait la signature « vide ». Si le
cache portait deja cette signature pour ce chemin, le scan concluait a un HIT
et les films du dossier n'etaient PAS replanifies — une perte de resultat
SILENCIEUSE, sans aucun log distinguant les deux cas.

Le sens de l'erreur compte : sur un scan qui alimente un apply capable de
DEPLACER des dossiers, une entree manquante est plus grave qu'un recalcul.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.app.plan_support_core import _try_apply_folder_cache, folder_signature
from cinesort.domain.core import Config


class _ScanIndexAvecCache:
    """Index de scan minimal qui rend UNE entree de cache preenregistree."""

    def __init__(self, entree: Optional[Dict[str, Any]]) -> None:
        self._entree = entree
        self.lectures = 0

    def get_incremental_folder_cache(self, **_kw: Any) -> Optional[Dict[str, Any]]:
        self.lectures += 1
        return self._entree


class _Stats:
    def __init__(self) -> None:
        self.incremental_cache_hits = 0
        self.incremental_cache_misses = 0
        self.incremental_cache_rows_reused = 0


class _Ctx:
    """Contexte reduit a ce que `_try_apply_folder_cache` lit reellement."""

    def __init__(self, cfg: Config, scan_index: Any) -> None:
        self.cfg = cfg
        self.scan_index = scan_index
        self.incremental_enabled = True
        self.run_hash_cache: Dict[Any, Any] = {}
        self.root_key = str(cfg.root)
        self.cfg_sig = "CFGSIG"
        self.rows: List[Any] = []
        self.video_paths_seen: List[str] = []
        self.stats = _Stats()


class FolderSignatureSentinelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name)
        self.cfg = Config(root=self.racine)
        self.addCleanup(self._tmp.cleanup)

    def _dossier(self, nom: str, fichiers: List[str]) -> Path:
        d = self.racine / nom
        d.mkdir()
        for f in fichiers:
            (d / f).write_bytes(b"x" * 1024)
        return d

    def test_inaccessible_ne_partage_plus_la_signature_du_vide(self) -> None:
        """La confusion elle-meme : deux etats distincts, deux signatures."""
        vide = self._dossier("vide", [])
        absent = self.racine / "jamais_cree"  # scandir leve

        sig_vide = folder_signature(self.cfg, vide, scan_index=None)
        sig_absent = folder_signature(self.cfg, absent, scan_index=None)

        self.assertIsInstance(sig_vide, str, "un dossier vide a bien une signature")
        self.assertIsNone(sig_absent, "un dossier inaccessible n'a AUCUNE signature")
        self.assertNotEqual(sig_vide, sig_absent)

    def test_le_dossier_peuple_illisible_ne_recoit_pas_le_cache_du_vide(self) -> None:
        """LE SCENARIO COMPLET : les films ne doivent pas disparaitre du plan.

        Le cache porte une entree « dossier vide » (0 row) pour ce chemin. Le
        dossier est ensuite peuple, puis devient illisible. Avant #696, la
        signature retombait sur celle du vide -> HIT -> 0 row replanifiee.
        """
        entree_vide = {
            "folder_sig": folder_signature(self.cfg, self._dossier("temoin_vide", []), scan_index=None),
            "rows_json": [],
            "stats_json": {},
        }
        index = _ScanIndexAvecCache(entree_vide)
        ctx = _Ctx(self.cfg, index)

        illisible = self.racine / "peuple_mais_illisible"  # n'existe pas -> scandir leve

        folder_sig, hit = _try_apply_folder_cache(ctx, illisible)

        self.assertFalse(hit, "un dossier illisible ne doit JAMAIS etre servi depuis le cache")
        self.assertIsNone(folder_sig)
        self.assertEqual(ctx.stats.incremental_cache_hits, 0)
        self.assertEqual(ctx.stats.incremental_cache_misses, 1, "le miss doit etre COMPTE, pas silencieux")
        self.assertEqual(index.lectures, 0, "inutile d'interroger le cache : on ne peut rien en faire")

    def test_le_cache_reste_fonctionnel_quand_le_dossier_est_lisible(self) -> None:
        """Contre-epreuve : le correctif ne doit pas tuer le cache legitime."""
        dossier = self._dossier("lisible", ["A (2001).mkv", "B (2002).mkv"])
        sig = folder_signature(self.cfg, dossier, scan_index=None)
        self.assertIsNotNone(sig)

        index = _ScanIndexAvecCache({"folder_sig": sig, "rows_json": [], "stats_json": {}})
        ctx = _Ctx(self.cfg, index)

        folder_sig, hit = _try_apply_folder_cache(ctx, dossier)

        self.assertTrue(hit, "signature identique et dossier lisible => le HIT doit rester")
        self.assertEqual(folder_sig, sig)
        self.assertEqual(ctx.stats.incremental_cache_hits, 1)


if __name__ == "__main__":
    unittest.main()
