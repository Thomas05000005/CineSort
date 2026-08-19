r"""#1103 rejoue : une operation comptee UNE qui emportait tout un dossier.

Le critere de reussite de ce chantier est de rattraper les defauts DEJA CONNUS.
Voici le plus destructeur de la semaine, avec son mecanisme exact.

    `quarantine_row` resolvait la video par `folder / row.video`.
    `PlanRow.video` « can be empty » -> `folder / ""` vaut `folder`.
    Les deux `.exists()` qui suivaient repondaient VRAI sur le DOSSIER.
    Pour tout `kind` autre que `single`, ce dossier est PARTAGE.
    -> l'ecran annonce « 1 fichier », des films de la bibliotheque partent.

DEUX INVARIANTS, ET IL EN FAUT DEUX
-----------------------------------
J'avais d'abord ecarte le controle de granularite en affirmant que l'`op_type`
etait honnete (`QUARANTINE_DIR`). C'est FAUX : l'issue #1103 dit
`QUARANTINE_FILE` — le type MENTAIT sur ce qu'il deplacait. Les deux controles
existent donc, et ils voient des choses differentes :

    ampleur      -> le dossier emporte d'AUTRES lignes du plan (geometrie)
    granularite  -> le type dit FICHIER, la destination est un DOSSIER

Le second attrape le cas ou le dossier n'emporte aucune autre ligne mais reste
un dossier deplace sous un type fichier — invisible a la geometrie.
"""

from __future__ import annotations

import unittest

from cinesort.app.verdicts import (
    verifier_granularite_des_operations,
    verifier_operations_qui_emportent_d_autres_lignes,
)


class DefautMilleCentTroisTests(unittest.TestCase):
    """Le scenario reel, par l'ampleur."""

    #: Quatre lignes du plan, un seul dossier — la configuration `kind != single`.
    PLAN_PARTAGE = {
        "row-rocky-1": r"D:\films\Saga Rocky",
        "row-rocky-2": r"D:\films\Saga Rocky",
        "row-rocky-3": r"D:\films\Saga Rocky",
        "row-rocky-4": r"D:\films\Saga Rocky",
    }

    def test_une_quarantaine_de_dossier_partage_est_SIGNALEE(self):
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_FILE", "src_path": r"D:\films\Saga Rocky", "dst_path": r"D:\_review\Saga Rocky"}],
            self.PLAN_PARTAGE,
        )
        self.assertEqual(len(incs), 1, "l'operation qui a emporte plusieurs lignes n'est pas signalee")
        self.assertEqual(incs[0].code, "une_operation_emporte_plusieurs_lignes")

    def test_le_verdict_porte_les_QUATRE_lignes_emportees(self):
        """Aucune conclusion sans sa matiere : « 4 lignes » sans dire LESQUELLES
        obligerait a rejouer l'apply pour savoir quoi recuperer."""
        inc = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Saga Rocky"}],
            self.PLAN_PARTAGE,
        )[0]
        self.assertEqual(inc.journal["lignes_emportees"], sorted(self.PLAN_PARTAGE))
        self.assertEqual(inc.annonce["operations_comptees"], 1)

    def test_une_ligne_NON_APPLIQUEE_compte_aussi(self):
        """Le cœur du defaut : c'est une ligne qu'on n'appliquait PAS qui se
        faisait emporter. Ne regarder que les lignes decidees serait aveugle
        exactement la ou il faut voir."""
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Partage"}],
            {"celle-qu-on-applique": r"D:\films\Partage", "celle-qu-on-touche-pas": r"D:\films\Partage"},
        )
        self.assertEqual(len(incs), 1)


class PasDeFauxPositifTests(unittest.TestCase):
    """Un detecteur qui rougit sur du normal est pire qu'absent."""

    def test_la_quarantaine_d_un_film_SEUL_ne_leve_rien(self):
        """Le cas nominal — `kind == single`, un dossier dedie."""
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Interstellar (2014)"}],
                {"row-1": r"D:\films\Interstellar (2014)", "row-2": r"D:\films\Alien (1979)"},
            ),
            [],
        )

    def test_le_cas_CORRIGE_de_1103_ne_leve_rien(self):
        """Apres correctif, la quarantaine vise le FICHIER et non le dossier
        partage. Les autres lignes restent en place : rien ne doit rougir."""
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "QUARANTINE_FILE", "src_path": r"D:\films\Saga Rocky\rocky1.mkv"}],
                {"r1": r"D:\films\Saga Rocky", "r2": r"D:\films\Saga Rocky"},
            ),
            [],
        )

    def test_un_MOVE_DIR_de_collection_est_HORS_PERIMETRE(self):
        """Limite ECRITE plutot que tue : `move_collection_folder` deplace
        legitimement un dossier racine contenant plusieurs films. L'inclure
        ferait rougir chaque apply de collection."""
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "MOVE_DIR", "src_path": r"D:\films\Collection Marvel"}],
                {"row-1": r"D:\films\Collection Marvel\Iron Man", "row-2": r"D:\films\Collection Marvel\Thor"},
            ),
            [],
        )

    def test_un_MKDIR_ne_leve_rien(self):
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "MKDIR", "src_path": r"D:\films"}],
                {"row-1": r"D:\films\A", "row-2": r"D:\films\B"},
            ),
            [],
        )


class LesFormesDEGRADEESNeFontPasLeverTests(unittest.TestCase):
    def test_un_chemin_vide_est_ignore(self):
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "QUARANTINE_DIR", "src_path": ""}],
                {"row-1": r"D:\films\A", "row-2": r"D:\films\A"},
            ),
            [],
        )

    def test_un_plan_vide_ne_fait_pas_lever(self):
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\A"}], {}
            ),
            [],
        )

    def test_des_entrees_aberrantes_rendent_une_liste_VIDE(self):
        """Pas `assertIsNotNone` : sur une fonction typee `-> List`, l'assertion
        est tautologique. On exige la liste VIDE, ce qui a un contenu."""
        for ops, plan in (([None], {}), ([{}], {"r": None}), ([], {"r": ""})):
            with self.subTest(ops=ops, plan=plan):
                self.assertEqual(verifier_operations_qui_emportent_d_autres_lignes(ops, plan), [])


class LaComparaisonDeCheminsNEstPasMUETTETests(unittest.TestCase):
    """Sans ceci, une sonde inoperante rendrait tout le fichier vert.

    Une premiere version de cette classe eprouvait un helper `_est_sous`. La
    reecriture par ancetres (correctif de performance) l'a rendu MORT sans que
    personne ne s'en apercoive : ses cinq assertions restaient vertes sur du code
    que la production n'appelait plus, et donnaient l'illusion que le chemin reel
    etait couvert. La batterie de mutation, non rejouee apres cette reecriture,
    validait elle aussi du code mort.

    Tout ce qui suit passe donc par la fonction PUBLIQUE. Un helper qui meurt
    fait desormais rougir, parce que plus rien ne le teste isolement.
    """

    def test_le_voisin_au_nom_PREFIXE_n_est_pas_confondu(self):
        r"""`D:\films\Rocky2` commence par `D:\films\Rocky` sans etre dedans.

        Une comparaison par prefixe de CHAINE accuserait un apply sain.
        """
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Rocky"}],
                {
                    "row-1": r"D:\films\Rocky",
                    "row-2": r"D:\films\Rocky2",
                    "row-3": r"D:\films\Rocky Balboa",
                },
            ),
            [],
        )

    def test_une_ligne_IMBRIQUEE_profondement_est_bien_vue(self):
        """La marche par ancetres doit remonter plus d'un cran."""
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Saga"}],
            {"r1": r"D:\films\Saga", "r2": r"D:\films\Saga\Rocky\1976\VF"},
        )
        self.assertEqual(len(incs), 1, "une ligne a trois niveaux sous la source n'est pas vue")

    def test_un_partage_reseau_UNC_est_traite_comme_les_autres(self):
        r"""La marche par ancetres s'arrete-t-elle sur une racine UNC ?

        `os.path.dirname(r'\\nas\films')` se rend LUI-MEME : sans le garde
        `parent == cle`, la boucle tournerait sans fin.
        """
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": r"\\nas\films"}],
            {"r1": r"\\nas\films", "r2": r"\\nas\films\Rocky"},
        )
        self.assertEqual(len(incs), 1)

    def test_la_casse_et_les_separateurs_ne_trompent_pas(self):
        r"""Windows : `D:/Films/A` et `d:\films\a` sont le MEME dossier. Les
        traiter comme distincts ferait manquer le defaut."""
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": "D:/Films/Partage"}],
            {"row-1": r"d:\films\partage", "row-2": r"D:\FILMS\PARTAGE"},
        )
        self.assertEqual(len(incs), 1, "la normalisation de casse/separateurs ne joue pas")


class LaGRANULARITEQueJAvaisEcarteeATortTests(unittest.TestCase):
    """Le controle « le type dit FICHIER mais c'est un DOSSIER ».

    Je l'avais ecarte en affirmant que l'`op_type` de #1103 etait honnete
    (`QUARANTINE_DIR`). L'issue dit `QUARANTINE_FILE` : le controle aurait donc
    attrape le defaut, et il est desormais pose.

    Il est COMPLEMENTAIRE de l'ampleur, pas redondant : il voit un dossier
    deplace sous un type FICHIER meme quand il n'emporte AUCUNE autre ligne du
    plan — cas que la geometrie ne peut pas voir.
    """

    def test_1103_dans_sa_forme_EXACTE_est_signale(self):
        incs = verifier_granularite_des_operations(
            [{"op_type": "QUARANTINE_FILE", "dst_path": r"D:\_review\Saga Rocky", "dst_est_dossier": True}]
        )
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0].code, "op_type_fichier_sur_un_dossier")

    def test_le_verdict_porte_ses_DEUX_termes(self):
        inc = verifier_granularite_des_operations(
            [{"op_type": "QUARANTINE_FILE", "dst_path": r"D:\_review\X", "dst_est_dossier": True}]
        )[0]
        self.assertEqual(inc.annonce["granularite_declaree"], "FICHIER")
        self.assertIs(inc.journal["dst_est_dossier"], True)
        self.assertIn("_review", inc.journal["dst_path"])

    def test_un_vrai_FICHIER_ne_leve_rien(self):
        self.assertEqual(
            verifier_granularite_des_operations(
                [{"op_type": "QUARANTINE_FILE", "dst_path": r"D:\_review\a.mkv", "dst_est_dossier": False}]
            ),
            [],
        )

    def test_un_op_type_DIR_sur_un_dossier_ne_leve_rien(self):
        """Le cas NOMINAL apres correctif : `_quarantine_single_folder` journalise
        bien `QUARANTINE_DIR` pour un dossier."""
        self.assertEqual(
            verifier_granularite_des_operations(
                [{"op_type": "QUARANTINE_DIR", "dst_path": r"D:\_review\Film", "dst_est_dossier": True}]
            ),
            [],
        )

    def test_un_MOVE_FILE_sur_un_dossier_est_signale_AUSSI(self):
        """Le defaut n'est pas propre a la quarantaine : tout type `*_FILE`
        pose sur un dossier ment de la meme facon."""
        self.assertEqual(
            len(
                verifier_granularite_des_operations(
                    [{"op_type": "MOVE_FILE", "dst_path": r"D:\films\Trie\Rocky", "dst_est_dossier": True}]
                )
            ),
            1,
        )

    def test_une_destination_ILLISIBLE_ne_conclut_PAS(self):
        """L'absence de mesure n'est pas une mesure negative — mais elle n'est pas
        non plus une accusation. Sans `dst_est_dossier`, on se tait."""
        self.assertEqual(
            verifier_granularite_des_operations([{"op_type": "QUARANTINE_FILE", "dst_path": r"D:\_review\X"}]),
            [],
        )

    def test_des_entrees_aberrantes_ne_font_pas_lever(self):
        for obs in ([None], [{}], [{"op_type": None}], []):
            with self.subTest(obs=obs):
                self.assertEqual(verifier_granularite_des_operations(obs), [])


class LeCoutNeRedevientPasQUADRATIQUETests(unittest.TestCase):
    """Un verdict qui fige l'application est un verdict qu'on debranche.

    La premiere version comparait chaque ligne du plan a chaque operation.
    MESURE sur ce poste, avec ce jeu de donnees exact (20 000 lignes de la forme
    `D:/films/Film {i}`, 2 000 operations de quarantaine sur les 2 000
    premieres) : **4,7 s**. La version par ancetres rend **48 ms** sur le meme
    jeu — la profondeur d'un chemin est bornee (~3 ici), le nombre d'operations
    ne l'est pas.

    Le seuil est volontairement LARGE : ce test ne mesure pas une performance, il
    refuse un CHANGEMENT D'ORDRE DE GRANDEUR. Meme sur un runner trois fois plus
    lent, 0,15 s et 14 s restent separes sans ambiguite.
    """

    N_LIGNES = 20_000
    N_OPS = 2_000

    def _jeu(self) -> tuple[list, dict]:
        plan = {f"r{i}": f"D:/films/Film {i}" for i in range(self.N_LIGNES)}
        ops = [{"op_type": "QUARANTINE_DIR", "src_path": f"D:/films/Film {i}"} for i in range(self.N_OPS)]
        return ops, plan

    def test_le_cout_reste_sous_la_seconde(self):
        import time

        ops, plan = self._jeu()
        debut = time.perf_counter()
        verifier_operations_qui_emportent_d_autres_lignes(ops, plan)
        ecoule = time.perf_counter() - debut
        self.assertLess(
            ecoule,
            1.0,
            f"{ecoule:.2f} s — le cout a change d'ordre de grandeur (quadratique ?). "
            "Reference sur ce jeu : 0,05 s par ancetres, 4,7 s paire a paire.",
        )

    def test_et_la_detection_reste_VIVANTE_a_cette_echelle(self):
        """Sans ceci, rendre `[]` tout de suite passerait le test de cout."""
        ops, plan = self._jeu()
        plan["intrus-1"] = "D:/films/Film 7"
        incs = verifier_operations_qui_emportent_d_autres_lignes(ops, plan)
        self.assertEqual(len(incs), 1, "l'optimisation a rendu le detecteur muet")
        self.assertEqual(incs[0].journal["lignes_emportees"], ["intrus-1", "r7"])


if __name__ == "__main__":
    unittest.main()
