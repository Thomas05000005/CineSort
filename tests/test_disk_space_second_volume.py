"""Le pre-check d'espace ne regardait qu'UN volume sur les deux.

MESURE (`build_apply_context`, 2026-08-06) : sur les SEPT bacs de l'apply, SIX
vivent sous `<run_dir>/_review`, donc sous le `state_dir` — en pratique
`%LOCALAPPDATA%`, souvent le disque systeme. Seul `review_root` (quarantaine des
non approuves) reste sous `cfg.root`.

    review_root                      cfg.root
    conflicts_root                   run_dir (state_dir)
    conflicts_sidecars_root          run_dir (state_dir)
    duplicates_identical_root        run_dir (state_dir)
    duplicates_user_decided_root     run_dir (state_dir)
    marked_for_deletion_root         run_dir (state_dir)
    leftovers_root                   run_dir (state_dir)

`check_disk_space_for_apply` ne mesurait que le volume de `cfg.root`. Un apply
pouvait donc remplir C: apres avoir verifie D:.

CE QUE LA COUVERTURE N'EST PAS : exhaustive. Seuls les doublons ecartes et les
marques pour suppression sont resolubles au moment du pre-check. Les CONFLITS
dependent de collisions de destination connues seulement a l'execution. Majorer
au total complet ressusciterait le faux « espace insuffisant » qui a deja bloque
des apply legitimes deux fois (#698, Fix R6-04) — c'est un arbitrage, pas un
oubli.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cinesort.app import disk_space_check
from cinesort.app.disk_space_check import check_disk_space_for_apply, estimate_bucket_size


def _row(row_id: str, folder: str = "/x", video: str = "f.mkv"):
    return SimpleNamespace(row_id=row_id, folder=folder, video=video, kind="single")


_GO = 1024 * 1024 * 1024


class _Usage:
    def __init__(self, free_go: float) -> None:
        self.free = int(free_go * _GO)
        self.total = 4000 * _GO
        self.used = self.total - self.free


class SecondVolumeTests(unittest.TestCase):
    """Bibliotheque spacieuse, disque systeme sature."""

    def setUp(self) -> None:
        self.cfg = SimpleNamespace(root=Path("D:/Films"))
        self.rows = [_row("r1"), _row("r2"), _row("r3")]
        self.approuves = {"r1", "r2", "r3"}

    def _appel(self, *, bucket_keys, meme_volume: bool, libre_state_go: float = 0.05):
        def _usage(chemin: str):
            return _Usage(500.0) if str(chemin).startswith("D:") else _Usage(libre_state_go)

        with (
            mock.patch.object(disk_space_check, "_row_estimated_size", return_value=8 * _GO),
            mock.patch.object(disk_space_check.shutil, "disk_usage", side_effect=_usage),
            mock.patch.object(disk_space_check, "_meme_volume", return_value=meme_volume),
        ):
            return check_disk_space_for_apply(
                self.cfg,
                self.rows,
                self.approuves,
                state_dir=Path("C:/Users/x/AppData/Local/CineSort/runs/r1"),
                bucket_keys=bucket_keys,
            )

    def test_le_disque_systeme_sature_BLOQUE_l_apply(self) -> None:
        """Deux films de 8 Go partent en bac sur C:, ou il reste 50 Mo."""
        ok, info = self._appel(bucket_keys={"r1", "r2"}, meme_volume=False)

        self.assertFalse(ok, f"l'apply demarre alors que le volume des bacs est plein : {info}")
        self.assertIn("C:", info.get("message", ""))
        self.assertEqual(info.get("bucket_estimated_bytes"), 16 * _GO)

    def test_le_message_NOMME_les_deux_disques(self) -> None:
        """Sans les deux chemins, l'utilisateur ne peut pas comprendre : sa
        bibliotheque a 500 Go libres, et on lui refuse l'apply."""
        _ok, info = self._appel(bucket_keys={"r1"}, meme_volume=False)
        message = info.get("message", "")

        self.assertIn("C:", message)
        self.assertIn("Films", message, f"le disque de la bibliotheque n'est pas nomme : {message}")

    def test_MEME_volume_ne_facture_pas_deux_fois(self) -> None:
        """Bibliotheque et state_dir sur le meme disque : deplacer un film d'un
        dossier a l'autre ne consomme rien de plus."""
        ok, info = self._appel(bucket_keys={"r1", "r2"}, meme_volume=True)

        self.assertTrue(ok)
        self.assertNotIn("bucket_needed_bytes", info)

    def test_aucun_film_en_bac_ne_declenche_RIEN(self) -> None:
        """Contre-epreuve : le cas courant ne doit pas payer un disk_usage de plus."""
        ok, info = self._appel(bucket_keys=set(), meme_volume=False)

        self.assertTrue(ok)
        self.assertNotIn("bucket_root", info)

    def test_le_volume_de_la_bibliotheque_reste_verifie(self) -> None:
        """Non-regression : le controle historique n'est pas remplace."""

        def _usage(_chemin: str):
            return _Usage(0.01)

        with (
            mock.patch.object(disk_space_check, "_row_estimated_size", return_value=8 * _GO),
            mock.patch.object(disk_space_check.shutil, "disk_usage", side_effect=_usage),
        ):
            ok, info = check_disk_space_for_apply(self.cfg, self.rows, self.approuves)

        self.assertFalse(ok)
        self.assertIn("Films", info.get("message", ""))


class EstimateBucketSizeTests(unittest.TestCase):
    def test_ne_somme_QUE_les_row_ids_donnes(self) -> None:
        rows = [_row("a"), _row("b"), _row("c")]
        with mock.patch.object(disk_space_check, "_row_estimated_size", return_value=100):
            self.assertEqual(estimate_bucket_size(rows, {"a", "c"}), 200)

    def test_un_ensemble_vide_rend_zero(self) -> None:
        with mock.patch.object(disk_space_check, "_row_estimated_size", return_value=100):
            self.assertEqual(estimate_bucket_size([_row("a")], set()), 0)

    def test_un_row_id_vide_n_est_jamais_compte(self) -> None:
        """Regle « sentinelle falsy » du depot : une chaine vide ne doit pas
        matcher un ensemble qui contiendrait accidentellement une chaine vide."""
        with mock.patch.object(disk_space_check, "_row_estimated_size", return_value=100):
            self.assertEqual(estimate_bucket_size([_row("")], {""}), 0)


class MemeVolumeTests(unittest.TestCase):
    def test_deux_chemins_du_meme_arbre_sont_sur_le_meme_volume(self) -> None:
        ici = Path(__file__).resolve()
        self.assertTrue(disk_space_check._meme_volume(ici.parent, ici.parent.parent))

    def test_un_chemin_INEXISTANT_remonte_a_son_parent(self) -> None:
        """`run_dir` peut ne pas exister au moment du pre-check."""
        ici = Path(__file__).resolve().parent
        self.assertTrue(disk_space_check._meme_volume(ici, ici / "pas" / "encore" / "cree"))


if __name__ == "__main__":
    unittest.main()
