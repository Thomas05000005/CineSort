"""Un reset qui n'a rien supprime ne doit pas rapporter qu'il a tout supprime.

LE DEFAUT. `reset_all_user_data` supprime les dossiers du `state_dir` avec
`shutil.rmtree(item, ignore_errors=True)`. Ce drapeau ne leve RIEN : un echec
est strictement indiscernable d'un succes du point de vue de l'appelant. Le code
ajoutait pourtant `item.name` a `removed` juste apres, sans jamais regarder si
l'element avait disparu — et retournait `ok: True`.

Consequence pour l'utilisateur : il tape « RESET », voit « reinitialisation
effectuee » avec la liste de ce qui a ete efface, et sa base, ses runs et ses
reglages sont toujours la.

POURQUOI CE N'EST PAS THEORIQUE. Ce reset s'execute pendant que l'application
TOURNE. Les threads de fond ecrivent dans ce meme `state_dir` — le cron de
retention (`retention_cleanup`), le cron TTL de quarantaine (`quarantine_ttl`),
le watcher, le serveur REST, le job runner. Sous Windows, un seul fichier ouvert
par l'un d'eux fait echouer la suppression de son dossier parent. C'est le meme
mecanisme que celui deja documente dans `CLAUDE.md` a propos des tests : « Les
threads de fond de l'app survivent au test. Ils continuent d'ecrire dans le
`state_dir` du test, au point de le RECREER juste apres le `rmtree`. »

L'INJECTION EST FAITE A LA COUCHE DE PRODUCTION. La regle du depot (piege n1,
mesure du 2026-08-06) : une panne injectee ailleurs qu'a l'endroit ou le defaut
VIT saute par-dessus lui. Le defaut vit dans le couple
`rmtree(ignore_errors=True)` + `removed.append`, donc c'est `shutil.rmtree` TEL
QUE LE MODULE L'APPELLE qui est remplace, par une doublure qui ne supprime rien
— exactement ce que fait le vrai `rmtree` face a un verrou. Le reste du chemin
(porte de confirmation, backup ZIP, boucle, rapport) s'execute sans retouche.

ET LES ASSERTIONS PORTENT SUR LA SORTIE UTILISATEUR (piege n3) : le payload rendu
a l'appelant, pas une variable interne.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, ".")

from cinesort.ui.api import reset_support


class _FakeApi:
    """Stub minimal : `reset_all_user_data` n'a besoin que du state_dir."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def _get_state_dir(self) -> str:
        return str(self._state_dir)


class ResetPartielTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name)
        self.state_dir = self.parent / "CineSort"
        self.state_dir.mkdir(parents=True)
        self.api = _FakeApi(self.state_dir)

        (self.state_dir / "logs").mkdir()
        (self.state_dir / "logs" / "app.log").write_text("trace", encoding="utf-8")
        (self.state_dir / "db").mkdir()
        (self.state_dir / "db" / "cinesort.sqlite").write_bytes(b"SQLite format 3\x00DONNEES")
        (self.state_dir / "runs").mkdir()
        (self.state_dir / "runs" / "r1.json").write_text('{"run": 1}', encoding="utf-8")
        (self.state_dir / "settings.json").write_text('{"root": "D:/Films"}', encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- 1) le cas du defaut : rmtree n'efface rien -------------------------

    def _reset_avec_rmtree_inoperant(self) -> dict:
        """`rmtree` ne supprime rien et ne dit rien — comportement exact de
        `ignore_errors=True` face a un fichier verrouille."""

        def _rmtree_qui_echoue_en_silence(*_args, **_kwargs):
            return None

        with mock.patch.object(reset_support.shutil, "rmtree", _rmtree_qui_echoue_en_silence):
            return reset_support.reset_all_user_data(self.api, "RESET")

    def test_les_dossiers_QUI_RESTENT_ne_sont_pas_annonces_supprimes(self) -> None:
        """Le coeur du correctif : `removed` decrit le disque, pas l'intention."""
        out = self._reset_avec_rmtree_inoperant()

        # Contre-epreuve de la doublure : si elle n'agissait pas, ce test ne
        # prouverait rien.
        self.assertTrue((self.state_dir / "db" / "cinesort.sqlite").exists())
        self.assertTrue((self.state_dir / "runs" / "r1.json").exists())

        removed = set(out.get("removed") or [])
        self.assertNotIn("db", removed, "la base est toujours la, et le rapport la declare supprimee")
        self.assertNotIn("runs", removed, "les runs sont toujours la, et le rapport les declare supprimes")

    def test_ce_qui_a_RESISTE_est_expose_a_l_appelant(self) -> None:
        """Sans champ dedie, l'UI ne peut rien dire a l'utilisateur."""
        out = self._reset_avec_rmtree_inoperant()

        self.assertEqual(set(out.get("failed") or []), {"db", "runs"})

    def test_un_reset_partiel_porte_un_message_actionnable(self) -> None:
        out = self._reset_avec_rmtree_inoperant()

        message = str(out.get("message") or "")
        self.assertTrue(message, "un reset partiel ne dit rien a l'utilisateur")
        self.assertIn("PARTIELLE", message)
        # Le chemin du backup doit rester joignable : c'est le seul recours.
        self.assertIn(str(out.get("backup_path") or ""), message)

    def test_les_FICHIERS_reellement_effaces_restent_comptes(self) -> None:
        """La doublure ne porte que sur les dossiers : le reste doit marcher."""
        out = self._reset_avec_rmtree_inoperant()

        self.assertIn("settings.json", set(out.get("removed") or []))
        self.assertFalse((self.state_dir / "settings.json").exists())

    # -- 2) non-regression : le cas nominal ne change pas -------------------

    def test_un_reset_COMPLET_rapporte_exactement_comme_avant(self) -> None:
        out = reset_support.reset_all_user_data(self.api, "RESET")

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(set(out.get("removed") or []), {"db", "runs", "settings.json"})
        self.assertEqual(out.get("failed"), [], "aucun echec ne doit etre invente")
        self.assertNotIn("message", out, "un reset complet n'a pas d'avertissement a porter")
        self.assertFalse((self.state_dir / "db").exists())
        self.assertFalse((self.state_dir / "runs").exists())

    def test_logs_reste_preserve_et_hors_des_deux_listes(self) -> None:
        out = reset_support.reset_all_user_data(self.api, "RESET")

        self.assertTrue((self.state_dir / "logs" / "app.log").exists())
        self.assertNotIn("logs", set(out.get("removed") or []))
        self.assertNotIn("logs", set(out.get("failed") or []))

    def test_la_porte_de_confirmation_reste_souveraine(self) -> None:
        """Contre-epreuve : le nouveau champ ne doit pas ouvrir une voie de
        contournement de la confirmation."""
        out = reset_support.reset_all_user_data(self.api, "reset")

        self.assertFalse(out.get("ok"), out)
        self.assertNotIn("failed", out)
        self.assertTrue((self.state_dir / "db" / "cinesort.sqlite").exists())


class HelperDisparitionTests(unittest.TestCase):
    """`_a_disparu` decide du contenu des deux listes : il doit etre restrictif."""

    def test_un_chemin_absent_a_bien_disparu(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(reset_support._a_disparu(Path(td) / "jamais-cree"))

    def test_un_chemin_present_n_a_pas_disparu(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cible = Path(td) / "f.txt"
            cible.write_text("x", encoding="utf-8")
            self.assertFalse(reset_support._a_disparu(cible))

    def test_une_existence_ILLISIBLE_ne_vaut_PAS_disparition(self) -> None:
        """Sens restrictif : ne pas pouvoir prouver la suppression, ce n'est pas
        l'avoir prouvee."""

        class _CheminIllisible:
            def exists(self):
                raise OSError("volume debranche")

        self.assertFalse(reset_support._a_disparu(_CheminIllisible()))


class RmtreeResteAppeleTests(unittest.TestCase):
    """Le correctif ne doit pas avoir transforme la suppression en no-op."""

    def test_rmtree_est_bien_invoque_sur_chaque_dossier(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "CineSort"
            state_dir.mkdir(parents=True)
            (state_dir / "db").mkdir()
            (state_dir / "runs").mkdir()
            api = _FakeApi(state_dir)

            appels: list = []
            vrai_rmtree = shutil.rmtree

            def _tracant(path, ignore_errors=False, **kwargs):
                appels.append(Path(path).name)
                return vrai_rmtree(path, ignore_errors=ignore_errors, **kwargs)

            with mock.patch.object(reset_support.shutil, "rmtree", _tracant):
                out = reset_support.reset_all_user_data(api, "RESET")

            self.assertEqual(sorted(appels), ["db", "runs"])
            self.assertEqual(out.get("failed"), [])


if __name__ == "__main__":
    unittest.main()
