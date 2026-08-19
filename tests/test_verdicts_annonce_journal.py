"""Phase 2 du plan — le triangle « annonce / journal / disque », premier cote.

Le critere de reussite de ce chantier est deliberement dur, et il est applique
ici : **rejouer les defauts DEJA CONNUS** et exiger que le verdict les signale.
Un systeme d'observabilite qui ne rattrape pas ce qu'on connait ne rattrapera
pas l'inconnu.

Les scenarios de la classe `DefautsDeLaSemaineTests` reproduisent donc, avec
leurs grandeurs reelles, les payloads et journaux des defauts corriges entre le
2026-08-13 et le 2026-08-19.

Ces tests portent sur une fonction PURE : aucun fichier ne bouge, aucune base
n'est ouverte. C'est voulu — la decision doit etre eprouvable exhaustivement,
et le cablage se mute separement.
"""

from __future__ import annotations

import unittest

from cinesort.app import verdicts
from cinesort.app.verdicts import (
    OPS_DE_DEPLACEMENT,
    OPS_DE_QUARANTAINE,
    comparer_annonce_et_journal,
)


class LaSourceDesOpTypeNAPasDivergeTests(unittest.TestCase):
    """La liste locale doit rester alignee sur celle de l'undo.

    `apply_rollback.py` refuse tout `op_type` hors de sa propre liste. Si les
    deux divergent, ce module comptera comme « deplacement » quelque chose que
    l'undo ne sait pas defaire — ou l'inverse, plus grave encore.
    """

    def test_ops_de_deplacement_est_celle_de_apply_rollback(self):
        from pathlib import Path

        source = Path("cinesort/app/apply_rollback.py").read_text(encoding="utf-8")
        for op in OPS_DE_DEPLACEMENT:
            self.assertIn(
                f'"{op}"',
                source,
                f"`{op}` n'apparait plus dans apply_rollback : les deux listes ont diverge",
            )

    def test_la_quarantaine_est_un_sous_ensemble_strict(self):
        self.assertTrue(set(OPS_DE_QUARANTAINE) < set(OPS_DE_DEPLACEMENT))


class DefautsDeLaSemaineTests(unittest.TestCase):
    """Rejouer les defauts connus. C'est le seul critere honnete."""

    def test_1062_un_succes_vert_alors_que_tout_a_resiste(self):
        """« 0 fichier(s) supprime(s) » en VERT, apres avoir fait TAPER un mot.

        Le payload posait son succes a la construction et ne le rediscutait
        jamais ; les 300 echecs vivaient dans une cle que l'ecran ne lisait pas.
        """
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 0, "renames": 0, "moves": 0},
            [{"op_type": "MOVE_FILE", "error": "PermissionError"} for _ in range(300)],
        )
        self.assertFalse(v.coherent, "un succes annonce sur 300 echecs doit etre signale")
        codes = {i.code for i in v.incoherences}
        self.assertIn("succes_annonce_malgre_des_echecs", codes)

    def test_1062_le_verdict_porte_LES_DEUX_TERMES(self):
        """Aucune conclusion sans sa matiere : le lecteur doit pouvoir refaire
        le calcul sans faire confiance au message."""
        v = comparer_annonce_et_journal(
            {"errors": 0},
            [{"op_type": "MOVE_FILE", "error": "boom"} for _ in range(300)],
        )
        inc = next(i for i in v.incoherences if i.code == "succes_annonce_malgre_des_echecs")
        self.assertEqual(inc.annonce, {"errors": 0})
        self.assertEqual(inc.journal, {"operations_en_echec": 300})

    def test_un_apply_qui_annonce_rien_alors_qu_il_a_deplace(self):
        """La forme la plus dangereuse : l'utilisateur n'a aucune raison
        d'annuler quelque chose qu'on ne lui a pas dit."""
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 0, "renames": 0, "moves": 0, "collection_moves": 0},
            [{"op_type": "MOVE_DIR"}, {"op_type": "MOVE_FILE"}],
        )
        codes = {i.code for i in v.incoherences}
        self.assertIn("deplacements_journalises_non_annonces", codes)

    def test_1103_N_EST_PAS_attrape_par_ce_cote_du_triangle(self):
        """La limite, eprouvee plutot que tue.

        #1103 deplacait un DOSSIER entier en UNE operation : le payload annonce
        1, le journal porte 1. Les comptes concordent, et pourtant trois films
        de la bibliotheque ont bouge. Seule la photo du disque tranche.

        Ce test existe pour que personne ne croie ce module plus couvrant qu'il
        n'est — et pour rougir le jour ou le cote « disque » sera pose.
        """
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 1, "renames": 0, "moves": 0},
            [{"op_type": "QUARANTINE_FILE", "src_path": "D:/biblio/Saga Rocky"}],
        )
        self.assertTrue(
            v.coherent,
            "tant que le cote DISQUE n'existe pas, ce cas passe — et la reserve du module doit le dire",
        )


class ComptesTests(unittest.TestCase):
    def test_un_compte_de_quarantaine_qui_diverge_est_signale(self):
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 1},
            [{"op_type": "QUARANTINE_FILE"}, {"op_type": "QUARANTINE_DIR"}],
        )
        inc = next(i for i in v.incoherences if i.code == "compte_de_quarantaine_diverge")
        self.assertEqual(inc.annonce, {"quarantined": 1})
        self.assertEqual(inc.journal, {"QUARANTINE_FILE": 1, "QUARANTINE_DIR": 1})
        self.assertIn("#1103", inc.reserve, "la limite connue doit accompagner le verdict")

    def test_un_apply_coherent_ne_leve_RIEN(self):
        """Contre-test central : un verdict qui rougit sur du normal serait pire
        qu'absent — on apprendrait a l'ignorer, et les vrais avec."""
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 2, "renames": 3, "moves": 0, "collection_moves": 0},
            [
                {"op_type": "QUARANTINE_FILE"},
                {"op_type": "QUARANTINE_DIR"},
                {"op_type": "MOVE_DIR"},
                {"op_type": "MOVE_DIR"},
                {"op_type": "MOVE_DIR"},
                {"op_type": "MKDIR"},
            ],
        )
        self.assertTrue(v.coherent, f"faux positif sur un apply sain : {v.as_dict()}")

    def test_le_dry_run_ne_compare_pas_les_comptes(self):
        """En apercu rien n'est journalise. Sans ce garde, CHAQUE dry-run
        leverait une incoherence — le faux positif qui tue l'outil."""
        v = comparer_annonce_et_journal({"errors": 0, "quarantined": 4, "renames": 9}, [], dry_run=True)
        self.assertTrue(v.coherent)

    def test_mais_le_dry_run_signale_QUAND_MEME_un_succes_menteur(self):
        """Le garde du dry-run ne doit pas devenir un trou : un echec journalise
        reste un echec, meme en apercu."""
        v = comparer_annonce_et_journal({"errors": 0}, [{"op_type": "MOVE_FILE", "error": "boom"}], dry_run=True)
        self.assertFalse(v.coherent)

    def test_une_operation_illisible_est_COMPTEE_pas_jetee(self):
        """La jeter ferait mentir le total — exactement le silence que ce module
        existe pour attraper."""
        v = comparer_annonce_et_journal({"errors": 0, "quarantined": 0}, [{"pas_d_op_type": 1}])
        self.assertEqual(v.comptes_journal.get(""), 1)

    def test_un_payload_aux_valeurs_ABERRANTES_ne_fait_pas_lever(self):
        """Robustesse : `None`, chaine, absence. Un verdict qui plante sur une
        entree bizarre ne protege plus rien."""
        for aberrant in ({}, {"errors": None}, {"errors": "trois"}, {"quarantined": []}):
            with self.subTest(aberrant=aberrant):
                self.assertIsNotNone(comparer_annonce_et_journal(aberrant, []))


class LeDetecteurNEstPasMuetTests(unittest.TestCase):
    """Les tests d'etat ci-dessus resteraient VERTS si la detection devenait
    inoperante. Ceux-ci l'eprouvent sur des entrees controlees."""

    def test_le_comptage_par_type_compte_vraiment(self):
        comptes = verdicts._compter_par_type([{"op_type": "MOVE_FILE"}, {"op_type": "MOVE_FILE"}, {"op_type": "MKDIR"}])
        self.assertEqual(comptes, {"MOVE_FILE": 2, "MKDIR": 1})

    def test_les_deux_formes_d_echec_sont_reconnues(self):
        """`undo_status=FAILED` sur les lignes de base, cle `error` sur les
        evenements d'audit. Les deux coexistent dans ce depot."""
        self.assertTrue(verdicts._en_echec({"undo_status": "FAILED"}))
        self.assertTrue(verdicts._en_echec({"error": "boom"}))
        self.assertFalse(verdicts._en_echec({"undo_status": "DONE"}))
        self.assertFalse(verdicts._en_echec({}))


if __name__ == "__main__":
    unittest.main()
