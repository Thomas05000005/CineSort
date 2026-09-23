"""Un dossier ILLISIBLE ne doit pas entrer au cache incremental comme « vide ».

Issue #696, SECOND VOLET — et le dépôt avait déjà formulé l'invariant lui-même.

CE QUI EXISTAIT DEJA
--------------------
1. `folder_signature` rend `None` sur echec de `os.scandir` (#696) : « un dossier
   inaccessible ne peut ni etre servi depuis le cache, ni y entrer ».
2. `_scan_saw_unreadable_folder` (F26) saute le prune du cache row des que
   `ignore_scandir_error > 0`, avec la raison ecrite sur place : « on ne saute
   desormais le prune que dans le seul cas ou "0 video" n'est pas une
   observation fiable : un dossier illisible pendant ce scan ».

LE SITE QUI Y ECHAPPAIT
-----------------------
L'ECRITURE du cache dossier. `_filter_dossiers_phase` persistait l'entree
`0 ligne` meme quand la lecture du dossier avait echoue, parce que les deux
lectures sont faites par DEUX `os.scandir` distincts :

    _try_apply_folder_cache -> folder_signature -> os.scandir  (#1)
    iter_videos                                 -> os.scandir  (#2)

Le premier peut reussir quand le second echoue — blip NAS/SMB, verrou antivirus,
la famille `WinError 5/32` que le CLAUDE.md mesure a 33 % de reproduction dans
une fenetre de quelques microsecondes. La garde de #696 ne voit que le premier.

POURQUOI L'OUBLI EST PERMANENT
------------------------------
La signature du dossier, elle, n'a PAS change : le dossier n'a pas bouge, c'est
sa lecture qui a echoue. Le scan suivant trouve donc une signature identique,
conclut au HIT, et reutilise une entree a ZERO ligne. Les films du dossier
restent invisibles jusqu'a ce que son contenu change ou qu'un « Forcer le rescan
complet » soit lance — alors meme qu'ils sont sur le disque et lisibles.

PORTEE HONNETE : `incremental_scan_enabled` vaut `False` par defaut. Le chemin
demande donc que l'utilisateur ait active le scan incremental — ce qu'on fait
precisement sur une GROSSE bibliotheque, donc souvent sur un NAS, donc la ou les
lectures transitoires echouent.
"""

from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir


class CacheIncrementalDossierIllisibleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_blip_scandir_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        patch_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patch_min.start()
        self.addCleanup(patch_min.stop)

        # Les noms portent une annee entre parentheses : `discover_candidate_folders`
        # les retient alors sans faire de scandir dessus (optimisation « BUG 5 »).
        # C'est ce qui rend l'ordre des scandir sur ce chemin DETERMINISTE pendant
        # la passe : #1 = folder_signature, #2 = iter_videos.
        self.dossier_blip = self.root / "Inception (2010)"
        self.dossier_sain = self.root / "Interstellar (2014)"
        self.dossier_bruit = self.root / "Notes (2001)"
        (self.dossier_blip).mkdir()
        (self.dossier_sain).mkdir()
        (self.dossier_bruit).mkdir()
        (self.dossier_blip / "Inception.2010.1080p.mkv").write_bytes(b"a" * 4096)
        (self.dossier_sain / "Interstellar.2014.2160p.mkv").write_bytes(b"b" * 4096)
        (self.dossier_bruit / "lisez-moi.txt").write_bytes(b"c" * 64)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, run_id: str) -> Tuple[List[Any], Any, List[Tuple[str, str]]]:
        cfg = core.Config(root=self.root, enable_tmdb=False, incremental_scan_enabled=True)
        logs: List[Tuple[str, str]] = []
        rows, stats = plan_support.plan_library(
            cfg,
            tmdb=None,
            log=lambda level, msg: logs.append((str(level), str(msg))),
            progress=lambda _idx, _total, _cur: None,
            scan_index=self.store.scan,
            run_id=run_id,
        )
        return rows, stats, logs

    def _blip_sur(self, cible: Path):
        """Sur `cible`, seul le `os.scandir` d'`iter_videos` echoue.

        La panne est injectee a l'appel SYSTEME, la ou la production la subit —
        pas en remplacant `iter_videos`, ce qui sauterait par-dessus le code
        teste. Le discriminant est la fonction APPELANTE, et non un rang d'appel :
        trois fonctions de production font un scandir sur ce meme chemin
        (`_yyyy_folder_shape` a la decouverte, `folder_signature`, puis
        `iter_videos`), et compter les appels rendrait le test dependant d'un
        ordre qui n'est pas un contrat.

        C'est exactement le scenario que #696 ne couvre pas : la SIGNATURE est
        calculee normalement, seule la LECTURE du contenu echoue.
        """
        vrai_scandir = os.scandir
        appelants: Dict[str, int] = {}

        def _scandir(chemin: Any = "."):
            if str(chemin) == str(cible):
                appelant = sys._getframe(1).f_code.co_name
                appelants[appelant] = appelants.get(appelant, 0) + 1
                if appelant == "iter_videos":
                    raise OSError(errno.EIO, "blip NAS simule")
            return vrai_scandir(chemin)

        return mock.patch("os.scandir", _scandir), appelants

    def _dossiers_des_rows(self, rows: List[Any]) -> set:
        return {str(getattr(row, "folder", "")) for row in rows}

    def test_le_film_revient_au_scan_suivant(self) -> None:
        """LA CONSEQUENCE UTILISATEUR, de bout en bout.

        Sans le correctif : la passe 1 ecrit « 0 ligne » pour le dossier, la
        passe 2 fait un HIT sur cette entree et le film reste absent.
        """
        patch, appelants = self._blip_sur(self.dossier_blip)
        with patch:
            rows1, stats1, logs1 = self._scan("passe-1-blip")

        # LE SCENARIO A BIEN EU LIEU, et c'est la verification qui empeche le
        # faux vert : la signature a ete calculee (donc `folder_sig` n'est PAS
        # None, donc `persist_folder_cache` n'est PAS neutralise par la garde de
        # #696), et c'est la lecture du contenu qui a echoue.
        self.assertGreaterEqual(appelants.get("folder_signature", 0), 1, appelants)
        self.assertGreaterEqual(appelants.get("iter_videos", 0), 1, appelants)
        self.assertNotIn(str(self.dossier_blip), self._dossiers_des_rows(rows1))
        self.assertGreater(
            int(getattr(stats1, "folders_rejected_scandir_error", 0) or 0),
            0,
            "la lecture echouee doit etre COMPTEE",
        )
        self.assertTrue(
            any("Cache incremental NON ecrit" in msg for _lvl, msg in logs1),
            "le refus d'ecrire doit etre DIT dans le journal du run",
        )

        # Passe 2, disque parfaitement lisible : le film doit reapparaitre.
        rows2, _stats2, _logs2 = self._scan("passe-2-saine")

        self.assertIn(
            str(self.dossier_blip),
            self._dossiers_des_rows(rows2),
            "le film a ete oublie DEFINITIVEMENT : le cache a fige « aucune video »",
        )

    def test_un_dossier_vraiment_sans_video_reste_mis_en_cache(self) -> None:
        """Contre-test : la garde ne doit pas desarmer le cache legitime.

        Un dossier de bruit (.txt) n'a aucune entree illisible : son entree doit
        continuer d'etre ecrite, sinon le correctif remplacerait un defaut par
        une perte de performance sur toute bibliotheque.
        """
        rows1, _stats1, logs1 = self._scan("passe-1-saine")
        self.assertFalse(
            any("Cache incremental NON ecrit" in msg for _lvl, msg in logs1),
            "aucune lecture n'a echoue : rien ne justifie de refuser le cache",
        )
        self.assertEqual(len(rows1), 2, self._dossiers_des_rows(rows1))

        rows2, stats2, _logs2 = self._scan("passe-2-cache")

        self.assertEqual(self._dossiers_des_rows(rows1), self._dossiers_des_rows(rows2))
        self.assertGreater(
            int(getattr(stats2, "incremental_cache_hits", 0) or 0),
            0,
            "le cache incremental doit toujours servir les dossiers lisibles",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
