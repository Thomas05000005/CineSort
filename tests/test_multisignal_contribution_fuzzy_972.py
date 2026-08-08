"""La contribution de la Phase B absorbee dans un groupe Phase A doit etre RENDUE.

LE DEFAUT (#972). `augment_groups_with_multi_signal` sautait tous les groupes
`strict_metadata` :

    # Skip Phase A (deja gere par base_groups identique)
    if g.phase == PHASE_STRICT_METADATA:
        continue

Le motif ecrit etait faux a cet endroit — le filtre juste au-dessus vient
d'etablir que le groupe porte au moins un membre ABSENT de `base_groups`.

Il l'etait doublement, et c'est la le vrai defaut : la Pass 1 de la Phase B
ABSORBE des candidats dans les groupes Phase A deja constitues
(`_phase_b_fuzzy_title(remaining, all_groups, ...)`, mutation en place de
`group_match.members`). Le groupe garde alors `phase=strict_metadata` tout en
portant une decouverte FUZZY — celle-la meme que la fonction promet d'ajouter.

MESURE, sur le module reel, avant correctif :

    le groupement TROUVE  : strict_metadata membres=['A','B','C']
    les compteurs disent  : {'strict_metadata': 1, 'fuzzy_title': 1, ...}
    augment(...) RESTITUE : ['A','B']            <- 'C' perdu

La fonction livrait donc ZERO contribution fuzzy la ou son propre resultat en
annoncait UNE. Le module avait deja rencontre ce piege une fois : #724 avait
corrige `phase_counts`, qui ignorait exactement les memes augmentations.

CE QUI N'A PAS CHANGE, ET POURQUOI. Un groupe Phase A *pur* reste ecarte. Le
groupement de base travaille sur les DESTINATIONS planifiees
(`plan_support_dedup.find_duplicate_targets` -> `planned_target_folder`) : deux
lignes de meme cle stricte y sont deja arbitrees, souvent en fusion non
bloquante plutot qu'en conflit. Les re-signaler en advisory reintroduirait un
bruit que la base a supprime volontairement. Le saut est conserve — mais pour
cette raison-la, ecrite, et non pour celle qui figurait dans le code.

INVERSER LES DEUX FILTRES N'AURAIT RIEN CHANGE : dans les deux ordres, tout
groupe Phase A est saute. La sortie est identique, seul le cout change. C'etait
une correction du commentaire, pas du comportement.
"""

from __future__ import annotations

import unittest

from cinesort.domain.duplicate_multi_signal import (
    PHASE_AUDIO_FINGERPRINT,
    PHASE_FUZZY_TITLE,
    PHASE_STRICT_METADATA,
    augment_groups_with_multi_signal,
    candidates_from_rows,
    group_by_multi_signal,
)


def _row(row_id: str, titre: str, annee: int, edition=None):
    """PlanRow duck-type, meme forme que `AugmentIntegrationTests._row`."""

    class _R:
        pass

    r = _R()
    r.row_id = row_id
    r.proposed_title = titre
    r.proposed_year = annee
    r.edition = edition
    return r


# A et B partagent la cle stricte -> groupe Phase A.
# C a un titre proche (token_sort_ratio >= 88) et le MEME premier token trie
# ("inception"), donc le meme bucket d'index, et la meme annee : la Pass 1 de la
# Phase B l'absorbe DANS le groupe Phase A.
_ROWS_AUGMENTE = [
    _row("A", "Inception Origins", 2010),
    _row("B", "Inception Origins", 2010),
    _row("C", "Inception Origin", 2010),
]
_DECISIONS_AUGMENTE = {"A": {"ok": True}, "B": {"ok": True}, "C": {"ok": True}}

# `base_groups` n'a groupe que A et B : C est une ligne que la base a manquee.
_BASE_AB = [
    {
        "title": "Inception Origins",
        "year": 2010,
        "rows": [{"row_id": "A"}, {"row_id": "B"}],
        "existing_paths": [],
        "plan_conflict": True,
    }
]


def _advisories(enrichi):
    return [g for g in enrichi if g.get("advisory")]


def _row_ids(groupe):
    return sorted(str(item.get("row_id")) for item in groupe.get("rows", []) or [])


class LaContributionFuzzyAbsorbeeEstRENDUETests(unittest.TestCase):
    """LE test. Sans le correctif, `C` disparait sans un mot."""

    def test_la_ligne_absorbee_par_le_fuzzy_est_visible(self) -> None:
        enrichi = augment_groups_with_multi_signal(_BASE_AB, _ROWS_AUGMENTE, _DECISIONS_AUGMENTE)

        vues = {str(item.get("row_id")) for g in enrichi for item in g.get("rows", []) or []}
        self.assertIn(
            "C",
            vues,
            "la ligne absorbee par la Pass 1 de la Phase B est perdue : le groupe "
            "Phase A qui la portait a ete saute en bloc.",
        )

    def test_le_groupe_augmente_est_annonce_en_fuzzy_title(self) -> None:
        """La phase annoncee doit etre celle qui a fait la DECOUVERTE.

        Annoncer `strict_metadata` designerait la phase qui a cree le groupe, pas
        celle qui a trouve le lien avec `C` — et laisserait croire que la base
        aurait du le voir.
        """
        avis = _advisories(augment_groups_with_multi_signal(_BASE_AB, _ROWS_AUGMENTE, _DECISIONS_AUGMENTE))

        self.assertEqual(len(avis), 1, f"attendu 1 advisory, obtenu {len(avis)}")
        self.assertEqual(avis[0]["detection_phase"], PHASE_FUZZY_TITLE)
        self.assertEqual(_row_ids(avis[0]), ["A", "B", "C"], "l'advisory doit porter le groupe COMPLET")

    def test_ce_que_le_compteur_ANNONCE_la_fonction_le_LIVRE(self) -> None:
        """L'invariant qui aurait attrape le defaut d'emblee.

        `phase_counts[fuzzy_title]` comptait 1 (le groupe Phase A augmente) alors
        que la fonction d'integration rendait 0 advisory. Cette contradiction
        entre deux sorties du meme module est le coeur de #972.
        """
        resultat = group_by_multi_signal(candidates_from_rows(_ROWS_AUGMENTE, _DECISIONS_AUGMENTE))
        annonce = resultat.phase_counts.get(PHASE_FUZZY_TITLE, 0)
        self.assertEqual(annonce, 1, "precondition : le groupement doit annoncer une contribution fuzzy")

        avis = _advisories(augment_groups_with_multi_signal(_BASE_AB, _ROWS_AUGMENTE, _DECISIONS_AUGMENTE))

        self.assertEqual(
            len(avis),
            annonce,
            f"le groupement annonce {annonce} contribution(s) fuzzy et l'integration en livre {len(avis)}.",
        )

    def test_le_groupe_de_base_n_est_jamais_supprime(self) -> None:
        """Backward compat : l'advisory s'AJOUTE, il ne remplace pas."""
        enrichi = augment_groups_with_multi_signal(_BASE_AB, _ROWS_AUGMENTE, _DECISIONS_AUGMENTE)

        bases = [g for g in enrichi if not g.get("advisory")]
        self.assertEqual(len(bases), 1)
        self.assertEqual(_row_ids(bases[0]), ["A", "B"])
        self.assertTrue(bases[0]["plan_conflict"], "le groupe de base garde ses attributs d'origine")


class UnGroupePhaseAPURResteECARTETests(unittest.TestCase):
    """La contre-epreuve : le correctif ne doit PAS tout ouvrir.

    Sans ces tests, retirer purement le skip passerait aussi — et elargirait la
    detection a des cas que le groupement de base a deliberement arbitres.
    """

    _ROWS_PUR = [_row("P1", "Solaris", 1972), _row("P2", "Solaris", 1972)]
    _DECISIONS_PUR = {"P1": {"ok": True}, "P2": {"ok": True}}

    def test_aucun_advisory_pour_un_groupe_strict_pur(self) -> None:
        # `base_groups` vide : les DEUX membres sont « nouveaux », le premier
        # filtre laisse donc passer. Seul le saut Phase A les ecarte.
        enrichi = augment_groups_with_multi_signal([], self._ROWS_PUR, self._DECISIONS_PUR)

        self.assertEqual(
            _advisories(enrichi),
            [],
            "un groupe de metadonnee stricte PURE ne doit pas etre re-signale : "
            "le groupement de base l'a deja arbitre.",
        )

    def test_la_precondition_du_test_precedent_est_reelle(self) -> None:
        """Un vert vide ne prouve rien : verifier que le groupe existe vraiment.

        Si la Phase A cessait de grouper P1/P2, le test ci-dessus resterait vert
        sans rien eprouver.
        """
        resultat = group_by_multi_signal(candidates_from_rows(self._ROWS_PUR, self._DECISIONS_PUR))

        stricts = [g for g in resultat.groups if g.phase == PHASE_STRICT_METADATA]
        self.assertEqual(len(stricts), 1, "precondition : la Phase A doit avoir forme un groupe")
        self.assertEqual(sorted(stricts[0].members), ["P1", "P2"])
        self.assertEqual(stricts[0].augmented_members, [], "ce groupe ne doit PAS avoir ete augmente")


class LaProvenanceDesMembresEstTRACEETests(unittest.TestCase):
    """`augmented_members` est le mecanisme qui rend les deux cas distinguables."""

    def test_la_pass_1_enregistre_le_membre_qu_elle_absorbe(self) -> None:
        resultat = group_by_multi_signal(candidates_from_rows(_ROWS_AUGMENTE, _DECISIONS_AUGMENTE))

        stricts = [g for g in resultat.groups if g.phase == PHASE_STRICT_METADATA]
        self.assertEqual(len(stricts), 1)
        self.assertEqual(sorted(stricts[0].members), ["A", "B", "C"])
        self.assertEqual(
            stricts[0].augmented_members,
            ["C"],
            "seul C a ete absorbe par le fuzzy ; A et B viennent de la Phase A.",
        )

    def test_un_groupe_CREE_par_la_phase_B_n_est_pas_dit_augmente(self) -> None:
        """Creer un groupe et en augmenter un ne sont pas la meme chose.

        Confondre les deux ferait passer un groupe fuzzy pour un groupe Phase A
        augmente, et brouillerait la phase annoncee.
        """
        rows = [_row("L1", "The Lord of the Rings", 2001), _row("L2", "Lord of the Rings The", 2002)]
        decisions = {"L1": {"ok": True}, "L2": {"ok": True}}

        resultat = group_by_multi_signal(candidates_from_rows(rows, decisions))

        fuzzy = [g for g in resultat.groups if g.phase == PHASE_FUZZY_TITLE]
        self.assertEqual(len(fuzzy), 1, "precondition : la Pass 2 doit avoir cree un groupe")
        self.assertEqual(fuzzy[0].augmented_members, [])

    def test_le_defaut_est_bien_le_champ_par_defaut(self) -> None:
        """Un groupe non touche par la Phase B porte une liste VIDE, pas None.

        `None` ferait passer le `not g.augmented_members` du correctif, mais
        casserait tout appelant qui itere la provenance.
        """
        resultat = group_by_multi_signal(candidates_from_rows(_ROWS_AUGMENTE, _DECISIONS_AUGMENTE))

        for g in resultat.groups:
            self.assertIsInstance(g.augmented_members, list)
            for membre in g.augmented_members:
                self.assertIn(membre, g.members, "un membre trace doit etre dans le groupe")


class LesAvisFuzzyEtFingerprintNeRegressentPasTests(unittest.TestCase):
    """Non-regression : le chemin nominal des Phases B et C est inchange."""

    def test_un_groupe_fuzzy_reste_annonce_en_fuzzy_title(self) -> None:
        rows = [_row("r1", "The Lord of the Rings", 2001), _row("r2", "Lord of the Rings The", 2002)]
        decisions = {"r1": {"ok": True}, "r2": {"ok": True}}

        avis = _advisories(augment_groups_with_multi_signal([], rows, decisions))

        self.assertEqual(len(avis), 1)
        self.assertEqual(avis[0]["detection_phase"], PHASE_FUZZY_TITLE)
        self.assertEqual(_row_ids(avis[0]), ["r1", "r2"])

    def test_un_advisory_n_est_jamais_un_conflit_de_destination(self) -> None:
        """Le signal reste informatif : il ne doit declencher aucune action."""
        avis = _advisories(augment_groups_with_multi_signal(_BASE_AB, _ROWS_AUGMENTE, _DECISIONS_AUGMENTE))

        self.assertEqual(len(avis), 1)
        self.assertFalse(avis[0]["plan_conflict"])
        self.assertEqual(avis[0]["existing_paths"], [])
        self.assertTrue(all(item.get("kind") == "advisory" for item in avis[0]["rows"]))

    def test_les_phases_connues_restent_les_trois_attendues(self) -> None:
        """Garde de nommage : la phase annoncee sort d'un jeu ferme."""
        connues = {PHASE_STRICT_METADATA, PHASE_FUZZY_TITLE, PHASE_AUDIO_FINGERPRINT}
        avis = _advisories(augment_groups_with_multi_signal(_BASE_AB, _ROWS_AUGMENTE, _DECISIONS_AUGMENTE))

        for g in avis:
            self.assertIn(g["detection_phase"], connues)


if __name__ == "__main__":
    unittest.main()
