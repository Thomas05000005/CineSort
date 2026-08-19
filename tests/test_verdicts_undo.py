"""Le triangle sur l'UNDO : ce qu'on annonce restaure contre ce qu'on inscrit.

L'undo est la seconde route la plus destructive de l'application — elle redeplace
des dossiers de films. Son payload annonce `counts: {done, skipped, failed}` et
chaque operation est marquee dans `apply_operations.undo_status`.

DEUX CHOSES MESUREES AVANT D'ECRIRE CET INVARIANT, et pas supposees :

1. **L'appariement est sain.** Chaque `done += 1` est suivi d'un
   `_mark_undo_status(DONE)`, chaque `failed += 1` d'un `FAILED`. Ce sont deux
   vues de la MEME population — contrairement au compte de quarantaine, retire
   parce qu'il comparait des populations disjointes.
2. **La divergence est atteignable.** `_mark_undo_status` avale `sqlite3.Error`
   et `OSError` DELIBEREMENT (« le statut en base est un artefact de rapport »).
   Une base verrouillee fait annoncer N restaurations la ou le journal en garde
   moins — et l'undo complet ne filtrant pas sur `undo_status`, ces operations
   seront REJOUEES au prochain essai.
"""

from __future__ import annotations

import unittest

from cinesort.app.verdicts import STATUTS_UNDO, comparer_undo_annonce_et_journal


class LeCompteRestaureTests(unittest.TestCase):
    def test_un_undo_NOMINAL_ne_leve_rien(self):
        """500 annonces, 500 inscrites."""
        self.assertEqual(
            comparer_undo_annonce_et_journal(
                {"done": 500, "skipped": 0, "failed": 0},
                {"PENDING": 500, "DONE": 0, "FAILED": 0, "SKIPPED": 0},
                {"PENDING": 0, "DONE": 500, "FAILED": 0, "SKIPPED": 0},
            ),
            [],
        )

    def test_un_statut_NON_PERSISTE_est_signale(self):
        """Le mode de panne reel : base verrouillee, `_mark_undo_status` avale
        l'erreur, le compteur monte quand meme."""
        incs = comparer_undo_annonce_et_journal(
            {"done": 500, "failed": 0},
            {"PENDING": 500, "DONE": 0},
            {"PENDING": 3, "DONE": 497},
        )
        self.assertEqual([i.code for i in incs], ["undo_compte_restaure_diverge"])
        self.assertEqual(incs[0].annonce, {"done": 500})
        self.assertEqual(incs[0].journal, {"delta_DONE": 497})

    def test_la_reserve_dit_ce_que_le_verdict_ne_prouve_PAS(self):
        """Un statut non persiste ne signifie pas que le fichier n'a pas bouge :
        le marquage vient APRES la restauration. Le risque est le REJEU."""
        inc = comparer_undo_annonce_et_journal({"done": 5}, {"DONE": 0}, {"DONE": 3})[0]
        self.assertIn("REJEU", inc.reserve)

    def test_un_SECOND_undo_du_meme_batch_ne_leve_rien(self):
        """LE FAUX POSITIF QUE LE DELTA EVITE.

        `_build_undo_preview_payload` ne filtre pas sur `undo_status` : un batch
        peut etre annule plusieurs fois. Apres un premier passage, le journal
        porte deja 3 DONE. Le second en ajoute 2, et annonce 2 — pas 5.
        Comparer des etats ABSOLUS ferait rougir chaque reprise.
        """
        self.assertEqual(
            comparer_undo_annonce_et_journal(
                {"done": 2, "failed": 0},
                {"PENDING": 2, "DONE": 3},
                {"PENDING": 0, "DONE": 5},
            ),
            [],
        )


class LesEchecsTests(unittest.TestCase):
    def test_un_succes_annonce_sur_des_echecs_inscrits_est_signale(self):
        incs = comparer_undo_annonce_et_journal(
            {"done": 10, "failed": 0},
            {"DONE": 0, "FAILED": 0},
            {"DONE": 10, "FAILED": 4},
        )
        self.assertIn("undo_succes_annonce_malgre_des_echecs", [i.code for i in incs])

    def test_des_echecs_ANNONCES_ne_levent_rien(self):
        """Contre-test : un undo partiel HONNETE est un undo sain."""
        self.assertEqual(
            comparer_undo_annonce_et_journal(
                {"done": 6, "failed": 4},
                {"DONE": 0, "FAILED": 0},
                {"DONE": 6, "FAILED": 4},
            ),
            [],
        )

    def test_les_echecs_d_un_undo_PRECEDENT_ne_comptent_pas(self):
        """Meme piege que pour les restaurations : sans delta, les 4 echecs d'un
        premier passage feraient rougir un second passage parfaitement sain."""
        self.assertEqual(
            comparer_undo_annonce_et_journal(
                {"done": 2, "failed": 0},
                {"DONE": 6, "FAILED": 4},
                {"DONE": 8, "FAILED": 4},
            ),
            [],
        )


class LesFormesDEGRADEESTests(unittest.TestCase):
    def test_des_comptes_absents_valent_zero(self):
        self.assertEqual(comparer_undo_annonce_et_journal({}, {}, {}), [])

    def test_des_valeurs_ABERRANTES_ne_font_pas_lever_d_exception(self):
        for annonce in ({"done": None}, {"done": "trois"}, {"failed": []}):
            with self.subTest(annonce=annonce):
                self.assertIsInstance(comparer_undo_annonce_et_journal(annonce, {}, {}), list)

    def test_un_annonce_None_est_tolere(self):
        self.assertEqual(comparer_undo_annonce_et_journal(None, {"DONE": 0}, {"DONE": 0}), [])


class LeDetecteurNEstPasMuetTests(unittest.TestCase):
    """Sans ceci, une comparaison inoperante rendrait tout le fichier vert."""

    def test_le_delta_compte_vraiment(self):
        self.assertEqual(
            len(comparer_undo_annonce_et_journal({"done": 1}, {"DONE": 0}, {"DONE": 0})),
            1,
            "annoncer 1 restauration sans aucune inscription doit lever",
        )

    def test_les_statuts_couvrent_ce_que_la_base_peut_porter(self):
        self.assertEqual(set(STATUTS_UNDO), {"PENDING", "DONE", "FAILED", "SKIPPED"})


class LesStatutsNONTPasDeriveTests(unittest.TestCase):
    """`STATUTS_UNDO` doit rester ce que le code de production ECRIT.

    Meme parade que pour `COMPTEURS_D_ACTION_DISQUE` : une liste recopiee derive,
    et une derive silencieuse rend l'invariant muet sur le statut oublie.
    """

    def test_chaque_statut_ecrit_par_l_undo_est_liste(self):
        import re
        from pathlib import Path

        source = Path("cinesort/ui/api/apply_support.py").read_text(encoding="utf-8")
        ecrits = set(re.findall(r'undo_status="([A-Z]+)"', source))
        self.assertTrue(ecrits, "aucun statut releve : la sonde ne mesure plus rien")
        oublies = ecrits - set(STATUTS_UNDO)
        self.assertEqual(oublies, set(), f"statuts ecrits mais absents de STATUTS_UNDO : {sorted(oublies)}")


class LE_CABLAGE_DE_L_UNDO_Tests(unittest.TestCase):
    """Le SITE D'APPEL, mute a part de la decision.

    Quatre fois dans cette campagne un mutant qui supprimait un appel — ou qui
    lui passait un mauvais argument — a survecu parce que seuls les tests de la
    DECISION existaient. Ces tests-ci portent sur `_verdict_undo` et sur la
    photo `avant`, dont l'exactitude conditionne tout le delta.
    """

    def setUp(self) -> None:
        self.journal: list = []
        self.notifications: list = []

    def _api(self):
        from types import SimpleNamespace

        notify = SimpleNamespace(
            notify=lambda *a, **k: self.notifications.append((a, k)),
        )
        return SimpleNamespace(_notify=notify)

    def _store(self, apres_rows, *, leve=None):
        from types import SimpleNamespace

        def _list(*, batch_id):
            if leve is not None:
                raise leve
            return list(apres_rows)

        return SimpleNamespace(apply=SimpleNamespace(list_apply_operations=_list))

    def _appeler(self, counts, avant, apres_rows, *, leve=None):
        from cinesort.ui.api import apply_support

        return apply_support._verdict_undo(
            {"ok": True, "counts": counts},
            self._api(),
            store=self._store(apres_rows, leve=leve),
            batch_id="b1",
            avant=avant,
            log_fn=lambda n, m: self.journal.append((n, m)),
        )

    def test_la_photo_AVANT_compte_les_statuts_reels(self):
        from cinesort.ui.api import apply_support

        comptes = apply_support._comptes_undo_par_statut(
            [{"undo_status": "PENDING"}, {"undo_status": "DONE"}, {"undo_status": "PENDING"}, {}]
        )
        self.assertEqual(comptes["PENDING"], 3, "une ligne sans statut vaut PENDING, elle ne se jette pas")
        self.assertEqual(comptes["DONE"], 1)
        self.assertEqual(comptes["FAILED"], 0, "les statuts connus doivent apparaitre a zero")

    def test_un_statut_NON_PERSISTE_remonte_jusqu_au_payload(self):
        payload = self._appeler(
            {"done": 3, "failed": 0},
            {"PENDING": 3, "DONE": 0},
            [{"undo_status": "DONE"}, {"undo_status": "PENDING"}, {"undo_status": "PENDING"}],
        )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertIn("undo_compte_restaure_diverge", codes)

    def test_l_incoherence_est_PUBLIEE_et_JOURNALISEE(self):
        self._appeler({"done": 3, "failed": 0}, {"DONE": 0}, [{"undo_status": "DONE"}])
        self.assertEqual(len(self.notifications), 1, "l'incoherence n'atteint aucun humain")
        warns = [m for n, m in self.journal if n == "WARN" and "INCOHERENCE undo" in m]
        self.assertEqual(len(warns), 1)
        self.assertIn("delta_DONE", warns[0], "le WARN doit porter les TERMES, pas la seule conclusion")

    def test_un_undo_SAIN_n_ajoute_rien_et_ne_publie_rien(self):
        payload = self._appeler(
            {"done": 2, "failed": 0},
            {"PENDING": 2, "DONE": 0},
            [{"undo_status": "DONE"}, {"undo_status": "DONE"}],
        )
        self.assertNotIn("verdict", payload)
        self.assertEqual(self.notifications, [])

    def test_un_journal_ILLISIBLE_ne_passe_pas_pour_un_undo_verifie(self):
        import sqlite3

        payload = self._appeler({"done": 2}, {"DONE": 0}, [], leve=sqlite3.OperationalError("database is locked"))
        self.assertNotIn("verdict", payload, "aucun verdict ne doit etre invente")
        self.assertTrue(payload.get("ok"), "un undo disque reussi doit rester reussi")
        warns = [m for n, m in self.journal if "NON CALCULE" in m]
        self.assertEqual(len(warns), 1, f"le non-calcul doit etre DIT : {self.journal}")
        self.assertIn("database is locked", warns[0])


class LE_CORPS_D_UNDO_APPELLE_VRAIMENT_LE_VERDICT_Tests(unittest.TestCase):
    """Les deux mutants qui ont SURVECU, et le test qui les tue.

    `LE_CABLAGE_DE_L_UNDO_Tests` appelle `_verdict_undo` EN DIRECT. Mesure :
    supprimer son appel depuis `_execute_and_finalize_undo`, ou y passer une
    photo `avant` VIDE, laissait toute la batterie verte. Cinquieme occurrence
    de la meme lecon dans cette campagne — tester la decision ne dit rien du
    site d'appel, ni de ses arguments.

    On execute donc le VRAI corps jusqu'a son retour.
    """

    def _payload_d_un_undo_reel(self, ops_avant, comptes_apres, ops_apres):
        from types import SimpleNamespace
        from unittest import mock

        from cinesort.ui.api import apply_support

        self.journal: list = []
        self.notifications: list = []
        store = SimpleNamespace(apply=SimpleNamespace(list_apply_operations=lambda *, batch_id: list(ops_apres)))
        api = SimpleNamespace(
            _file_logger=lambda _rp: lambda n, m: self.journal.append((str(n), str(m))),
            _notify=SimpleNamespace(notify=lambda *a, **k: self.notifications.append((a, k))),
            _dispatch_plugin_hook=lambda *a, **k: None,
        )
        uctx = {
            "batch_id": "b1",
            "irreversible_count": 0,
            "preview_categories": {},
            "empty_bucket": None,
            "residual_bucket": None,
        }
        with (
            mock.patch.object(apply_support, "_execute_undo_ops", return_value=dict(comptes_apres)),
            mock.patch.object(apply_support, "_undo_mkdir_ops", return_value=0),
            mock.patch.object(apply_support, "_write_undo_summary", return_value=None),
            mock.patch.object(apply_support, "_finalize_batch_undo_status", return_value=True),
        ):
            return apply_support._execute_and_finalize_undo(
                api, "run-1", uctx, list(ops_avant), store, run_paths=SimpleNamespace()
            )

    #: Ce que `_execute_undo_ops` rend, forme minimale acceptee par le corps.
    COMPTES = {
        "done": 3,
        "skipped": 0,
        "failed": 0,
        "conflict_moves": 0,
        "empty_folder_dirs_reversed": 0,
        "cleanup_residual_dirs_reversed": 0,
        "conflicts_details": [],
        "undo_conflicts_root": "",
    }

    def test_le_harnais_produit_bien_un_undo_NOMINAL(self):
        """Sans ce garde, un harnais casse rendrait un payload d'erreur et les
        deux tests suivants seraient verts sans avoir atteint le verdict."""
        payload = self._payload_d_un_undo_reel(
            [{"undo_status": "PENDING"}] * 3,
            self.COMPTES,
            [{"undo_status": "DONE"}] * 3,
        )
        self.assertTrue(payload.get("ok"), f"le harnais n'atteint pas l'undo nominal : {payload}")
        self.assertEqual(payload["counts"]["done"], 3)

    def test_un_undo_REEL_incoherent_porte_son_verdict(self):
        """ROUGE si l'appel disparait de `_execute_and_finalize_undo`."""
        payload = self._payload_d_un_undo_reel(
            [{"undo_status": "PENDING"}] * 3,
            self.COMPTES,
            [{"undo_status": "DONE"}, {"undo_status": "PENDING"}, {"undo_status": "PENDING"}],
        )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertIn(
            "undo_compte_restaure_diverge",
            codes,
            "le corps d'undo n'appelle plus le verdict",
        )

    def test_la_photo_AVANT_vient_bien_des_operations_du_batch(self):
        """ROUGE si la photo `avant` est vidée au site d'appel.

        Trois operations DEJA restaurees par un undo precedent, plus deux
        nouvelles. Le journal final porte 5 DONE, l'undo en annonce 2 : c'est
        COHERENT — mais seulement si la photo `avant` a bien vu les 3.
        """
        payload = self._payload_d_un_undo_reel(
            [{"undo_status": "DONE"}] * 3 + [{"undo_status": "PENDING"}] * 2,
            {**self.COMPTES, "done": 2},
            [{"undo_status": "DONE"}] * 5,
        )
        self.assertNotIn(
            "verdict",
            payload,
            "la photo AVANT ne voit pas les restaurations anterieures : chaque reprise d'undo rougirait a tort",
        )


if __name__ == "__main__":
    unittest.main()
