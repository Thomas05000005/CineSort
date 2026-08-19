"""#1103 rejoue : une operation comptee UNE qui emportait QUATRE films.

Le critere de reussite de tout ce chantier est de rattraper les defauts DEJA
CONNUS. Voici le plus destructeur de la semaine, remonte avec son mecanisme
exact.

    `quarantine_row` resolvait la video par `folder / row.video`.
    `PlanRow.video` « can be empty » -> `folder / ""` vaut `folder`.
    Les deux `.exists()` qui suivaient repondaient VRAI sur le DOSSIER.
    Pour tout `kind` autre que `single`, ce dossier est PARTAGE.
    -> l'ecran annonce « 1 fichier », trois films de la bibliotheque partent.

L'`op_type` etait HONNETE : `QUARANTINE_DIR`, un dossier. Un controle « le type
dit FILE mais c'est un DIR » n'aurait rien vu. Ce qui mentait, c'etait
l'AMPLEUR.
"""

from __future__ import annotations

import unittest

from cinesort.app.verdicts import (
    _est_sous,
    verifier_operations_qui_emportent_d_autres_lignes,
)


class DefautMilleCentTroisTests(unittest.TestCase):
    """Le scenario reel."""

    #: Quatre lignes du plan, un seul dossier — la configuration `kind != single`.
    PLAN_PARTAGE = {
        "row-rocky-1": r"D:\films\Saga Rocky",
        "row-rocky-2": r"D:\films\Saga Rocky",
        "row-rocky-3": r"D:\films\Saga Rocky",
        "row-rocky-4": r"D:\films\Saga Rocky",
    }

    def test_une_quarantaine_de_dossier_partage_est_SIGNALEE(self):
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Saga Rocky", "dst_path": r"D:\_review\Saga Rocky"}],
            self.PLAN_PARTAGE,
        )
        self.assertEqual(len(incs), 1, "l'operation qui a emporte 4 films n'est pas signalee")
        self.assertEqual(incs[0].code, "une_operation_emporte_plusieurs_lignes")

    def test_le_verdict_porte_les_QUATRE_lignes_emportees(self):
        """Aucune conclusion sans sa matiere : « 4 films » sans dire LESQUELS
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

    def test_un_dossier_VOISIN_au_nom_prefixe_n_est_pas_emporte(self):
        """`D:\films\\Rocky2` commence par `D:\films\\Rocky` sans etre dedans.

        Une comparaison par prefixe de CHAINE accuserait un apply sain. La
        comparaison se fait donc par SEGMENTS.
        """
        self.assertEqual(
            verifier_operations_qui_emportent_d_autres_lignes(
                [{"op_type": "QUARANTINE_DIR", "src_path": r"D:\films\Rocky"}],
                {"row-1": r"D:\films\Rocky", "row-2": r"D:\films\Rocky2"},
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

    def test_des_entrees_aberrantes_ne_font_pas_lever(self):
        for ops, plan in (([None], {}), ([{}], {"r": None}), ([], {"r": ""})):
            with self.subTest(ops=ops, plan=plan):
                self.assertIsNotNone(verifier_operations_qui_emportent_d_autres_lignes(ops, plan))


class LaComparaisonDeCheminsNEstPasMUETTETests(unittest.TestCase):
    """Sans ceci, une sonde inoperante rendrait tout le fichier vert."""

    def test_est_sous_repond_vraiment(self):
        self.assertTrue(_est_sous(r"d:\films\a", r"d:\films"))
        self.assertTrue(_est_sous(r"d:\films", r"d:\films"))
        self.assertFalse(_est_sous(r"d:\films2", r"d:\films"))
        self.assertFalse(_est_sous(r"d:\films", r"d:\films\a"))
        self.assertFalse(_est_sous("", r"d:\films"))

    def test_la_casse_et_les_separateurs_ne_trompent_pas(self):
        """Windows : `D:/Films/A` et `d:\films\a` sont le MEME dossier. Les
        traiter comme distincts ferait manquer le defaut."""
        incs = verifier_operations_qui_emportent_d_autres_lignes(
            [{"op_type": "QUARANTINE_DIR", "src_path": "D:/Films/Partage"}],
            {"row-1": r"d:\films\partage", "row-2": r"D:\FILMS\PARTAGE"},
        )
        self.assertEqual(len(incs), 1, "la normalisation de casse/separateurs ne joue pas")


if __name__ == "__main__":
    unittest.main()


class LeCoutNeRedevientPasQUADRATIQUETests(unittest.TestCase):
    """Un verdict qui fige l'application est un verdict qu'on debranche.

    La premiere version comparait chaque ligne du plan a chaque operation.
    MESURE sur ce poste :

        1 000 lignes x   100 operations ->      10 ms
        5 000 lignes x   500 operations ->     274 ms
       20 000 lignes x 2 000 operations ->   4 675 ms   <-- inacceptable

    Un apply termine qui se fige cinq secondes pour calculer un verdict finit
    debranche, et l'instrument avec. La version par ANCETRES rend 48 ms sur le
    meme cas — la profondeur d'un chemin est bornee (~10), le nombre
    d'operations ne l'est pas.

    Le seuil est volontairement LARGE (1 s contre 48 ms mesures) : ce test ne
    mesure pas une performance, il refuse un CHANGEMENT D'ORDRE DE GRANDEUR. La
    version quadratique met 4,7 s ici — meme sur un runner trois fois plus lent,
    les deux restent separes sans ambiguite.
    """

    def test_vingt_mille_lignes_et_deux_mille_operations_restent_sous_la_seconde(self):
        import time

        plan = {f"r{i}": f"D:/films/Film {i}" for i in range(20_000)}
        ops = [{"op_type": "QUARANTINE_DIR", "src_path": f"D:/films/Film {i}"} for i in range(2_000)]

        debut = time.perf_counter()
        verifier_operations_qui_emportent_d_autres_lignes(ops, plan)
        ecoule = time.perf_counter() - debut

        self.assertLess(
            ecoule,
            1.0,
            f"{ecoule:.2f} s — le cout a change d'ordre de grandeur (quadratique ?). "
            "Mesure de reference : 0,05 s par ancetres, 4,7 s paire a paire.",
        )

    def test_et_la_detection_reste_VIVANTE_a_cette_echelle(self):
        """Sans ceci, rendre `[]` tout de suite passerait le test de cout."""
        plan = {f"r{i}": f"D:/films/Film {i}" for i in range(20_000)}
        plan["intrus-1"] = "D:/films/Film 7"
        ops = [{"op_type": "QUARANTINE_DIR", "src_path": f"D:/films/Film {i}"} for i in range(2_000)]
        incs = verifier_operations_qui_emportent_d_autres_lignes(ops, plan)
        self.assertEqual(len(incs), 1, "l'optimisation a rendu le detecteur muet")
        self.assertEqual(incs[0].journal["lignes_emportees"], ["intrus-1", "r7"])
