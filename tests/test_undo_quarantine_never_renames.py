"""Regle inviolable n1 sur le chemin de l'UNDO : le fichier video n'est pas renomme.

4e site de renommage du depot, trouve en corrigeant les trois premiers (#903).
Celui-ci est sur le **filet de secours** : quand l'undo veut restaurer un fichier
et que sa cible est deja occupee, il met le fichier courant en quarantaine sous
`_review/_undo_conflicts/`. L'ancien code y resolvait une collision de nom en
renommant le FICHIER :

    Rocky.1976.1080p.mkv  ->  Rocky.1976.1080p_2.mkv

Le nom de fichier doit rester synchrone avec les torrents : le renommer casse le
seeding, y compris dans un bac de quarantaine ou l'utilisateur peut aller le
rechercher.

Ces tests regardent le DISQUE apres un undo REEL, pas un dictionnaire de
previsualisation : `Path.exists()` est insensible a la casse sur NTFS et ne
distinguerait pas non plus un `_2` d'un fichier voisin.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from cinesort.app.apply_core import unique_bucket_path
from cinesort.ui.api import apply_support
from cinesort.ui.api.apply_support import _execute_undo_ops
from tests.test_apply_robustness import _FakeApi, _FakeRunPaths, _FakeStore, _log_noop


class UndoQuarantineNeverRenamesTests(unittest.TestCase):
    """Contrat de `unique_bucket_path` tel que le chemin d'undo l'utilise."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="undo_quarantine_")
        self.addCleanup(self._tmp.cleanup)
        self.bucket = Path(self._tmp.name) / "_review" / "_undo_conflicts"
        self.bucket.mkdir(parents=True, exist_ok=True)

    def _poser(self, chemin: Path, contenu: bytes = b"x") -> Path:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(contenu)
        return chemin

    def test_cible_libre_le_nom_est_rendu_intact(self) -> None:
        vise = self.bucket / "Rocky.1976.1080p.mkv"
        obtenu = unique_bucket_path(vise, bucket_root=self.bucket, use_dup_suffix=False)
        self.assertEqual(obtenu, vise)

    def test_collision_a_la_racine_du_bac_insere_un_DOSSIER(self) -> None:
        """Le cas exact du chemin d'undo : le fichier est pose a la racine du bac."""
        nom = "Rocky.1976.1080p.mkv"
        self._poser(self.bucket / nom)

        obtenu = unique_bucket_path(self.bucket / nom, bucket_root=self.bucket, use_dup_suffix=False)

        self.assertIsNotNone(obtenu, "aucune desambiguisation proposee")
        assert obtenu is not None  # pour mypy
        self.assertEqual(obtenu.name, nom, f"le FICHIER a ete renomme : {obtenu.name}")
        self.assertNotEqual(obtenu, self.bucket / nom, "la cible occupee a ete rendue telle quelle")
        self.assertEqual(
            obtenu.parent.parent,
            self.bucket,
            "un dossier d'index doit etre INSERE sous le bac",
        )

    def test_collisions_multiples_ne_touchent_jamais_au_nom(self) -> None:
        nom = "Rocky.1976.1080p.mkv"
        self._poser(self.bucket / nom)
        obtenus: list[Path] = []
        for _ in range(4):
            p = unique_bucket_path(self.bucket / nom, bucket_root=self.bucket, use_dup_suffix=False)
            self.assertIsNotNone(p)
            assert p is not None
            self.assertEqual(p.name, nom, f"le FICHIER a ete renomme : {p.name}")
            self._poser(p)  # on occupe la place pour forcer la collision suivante
            obtenus.append(p)
        self.assertEqual(len(set(obtenus)), 4, "deux appels ont rendu le meme chemin")

    def test_hors_du_bac_refuse_plutot_que_renommer(self) -> None:
        """Sens RESTRICTIF : sans desambiguisation possible, on rend None.

        L'appelant doit alors abandonner le deplacement et laisser le fichier en
        place, plutot que d'ecraser la cible ou de renommer le fichier.
        """
        ailleurs = Path(self._tmp.name) / "ailleurs" / "Rocky.1976.1080p.mkv"
        self._poser(ailleurs)
        self.assertIsNone(unique_bucket_path(ailleurs, bucket_root=self.bucket, use_dup_suffix=False))

    def test_le_contenu_est_preserve_apres_deplacement_reel(self) -> None:
        """Bout en bout : on deplace vraiment, et on relit le disque."""
        nom = "Rocky.1976.1080p.mkv"
        self._poser(self.bucket / nom, b"premier occupant")
        source = Path(self._tmp.name) / "source" / nom
        self._poser(source, b"celui que l'undo quarantine")

        cible = unique_bucket_path(self.bucket / nom, bucket_root=self.bucket, use_dup_suffix=False)
        self.assertIsNotNone(cible)
        assert cible is not None
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(cible))

        noms_sur_disque = {p.name for p in self.bucket.rglob("*") if p.is_file()}
        self.assertEqual(
            noms_sur_disque,
            {nom},
            f"un nom de fichier a change sur le disque : {sorted(noms_sur_disque)}",
        )
        self.assertEqual(cible.read_bytes(), b"celui que l'undo quarantine")


class UndoConflictCallSiteTests(unittest.TestCase):
    """Le SITE D'APPEL, pas seulement le contrat du helper.

    Un premier jet de ces tests n'exercait que `unique_bucket_path`. En remettant
    l'ancien `api._unique_path` dans `apply_support`, ils restaient VERTS : ils
    prouvaient le helper, pas que le chemin d'undo s'en sert. Piege classique du
    correctif hors du chemin d'appel — d'ou cette classe, qui passe par
    `_execute_undo_ops`.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_quarantine_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir()
        self.run_dir = Path(self._tmp) / "run_dir"
        self.run_dir.mkdir()
        self.store = _FakeStore()
        self.api = _FakeApi()
        self.run_paths = _FakeRunPaths(self.run_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _op(self, idx: int, src: Path, dst: Path) -> dict:
        return {"id": idx, "op_type": "MOVE", "src_path": str(src), "dst_path": str(dst)}

    def test_deux_conflits_homonymes_gardent_leur_nom_de_fichier(self) -> None:
        """Deux fichiers de MEME nom quarantines : aucun ne recoit de suffixe.

        C'est le cas qui produisait `Rocky.1976.1080p_2.mkv`. Il suffit de deux
        dossiers sources homonymes — situation banale quand une bibliotheque est
        repartie sur deux disques.
        """
        nom = "Rocky.1976.1080p.mkv"
        ops = []
        for idx, disque in enumerate(("Disque A", "Disque B"), start=1):
            courant = self.root / disque / nom
            courant.parent.mkdir(parents=True, exist_ok=True)
            courant.write_bytes(f"contenu {disque}".encode())
            # La cible de restauration est OCCUPEE -> l'undo doit quarantiner.
            cible = self.root / disque / "occupee.mkv"
            cible.write_bytes(b"deja la")
            ops.append(self._op(idx, cible, courant))

        result = _execute_undo_ops(
            self.api, ops, self.store, _log_noop, self.run_paths, empty_bucket=None, residual_bucket=None
        )

        self.assertEqual(result["conflict_moves"], 2, result)
        quarantines = [p for p in self.run_dir.rglob("*") if p.is_file()]
        self.assertEqual(len(quarantines), 2, [str(p) for p in quarantines])
        noms = sorted(p.name for p in quarantines)
        self.assertEqual(
            noms,
            [nom, nom],
            f"un fichier video a ete renomme dans la quarantaine d'undo : {noms}",
        )
        # Et les deux contenus distincts survivent : rien n'a ete ecrase.
        self.assertEqual(
            sorted(p.read_bytes() for p in quarantines),
            [b"contenu Disque A", b"contenu Disque B"],
        )

    def test_si_aucune_desambiguisation_nest_possible_on_refuse(self) -> None:
        """Sens RESTRICTIF au site d'appel : refuser, pas ecraser ni renommer.

        On simule le refus DOCUMENTE du helper (`None` = aucune desambiguisation
        de dossier possible) pour observer la reaction de l'APPELANT. Le mock ne
        fabrique pas la condition testee — il fournit la reponse que le helper
        rend deja dans son contrat ; ce qu'on verifie, c'est ce que le chemin
        d'undo en fait.

        Sans cette garde, `shutil.move` vers `None` leverait, ou pire une
        version anterieure ecrasait la cible.
        """
        nom = "Rocky.1976.1080p.mkv"
        courant = self.root / nom
        courant.write_bytes(b"a preserver")
        cible = self.root / "occupee.mkv"
        cible.write_bytes(b"deja la")

        with mock.patch.object(apply_support, "unique_bucket_path", return_value=None):
            result = _execute_undo_ops(
                self.api,
                [self._op(1, cible, courant)],
                self.store,
                _log_noop,
                self.run_paths,
                empty_bucket=None,
                residual_bucket=None,
            )

        self.assertEqual(result["conflict_moves"], 0, result)
        self.assertEqual(result["failed"], 1, result)
        self.assertTrue(courant.exists(), "le fichier source a bouge malgre le refus")
        self.assertEqual(courant.read_bytes(), b"a preserver")
        self.assertEqual(cible.read_bytes(), b"deja la", "la cible occupee a ete ecrasee")
        # Le refus doit etre TRACE, pas silencieux.
        self.assertEqual(self.store.marks[0]["status"], "FAILED")
        # `_FakeApplyRepo` range le message sous la cle "error" (pas
        # "error_message") : lire la mauvaise cle rendait "" et l'assertion
        # aurait pu etre "assouplie" au lieu d'etre corrigee.
        self.assertIn("renommer", str(self.store.marks[0].get("error", "")).lower())

    def test_un_seul_conflit_garde_son_nom(self) -> None:
        """Non-regression du cas simple, deja couvert ailleurs mais bon marche."""
        nom = "Inception.2010.1080p.mkv"
        courant = self.root / nom
        courant.write_bytes(b"a quarantiner")
        cible = self.root / "occupee.mkv"
        cible.write_bytes(b"deja la")

        result = _execute_undo_ops(
            self.api,
            [self._op(1, cible, courant)],
            self.store,
            _log_noop,
            self.run_paths,
            empty_bucket=None,
            residual_bucket=None,
        )

        self.assertEqual(result["conflict_moves"], 1, result)
        quarantines = [p for p in self.run_dir.rglob("*") if p.is_file()]
        self.assertEqual([p.name for p in quarantines], [nom])
        self.assertTrue(cible.exists(), "la cible occupee a ete ecrasee")


if __name__ == "__main__":
    unittest.main()
