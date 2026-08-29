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
from pathlib import Path

from cinesort.app import verdicts
from cinesort.app.verdicts import (
    OPS_DE_DEPLACEMENT,
    OPS_DE_QUARANTAINE,
    comparer_annonce_et_journal,
)

#: Tous les `op_type` que l'application ECRIT reellement dans son journal,
#: releves dans `apply_core.py`. C'est l'univers sur lequel le contrat ci-dessous
#: interroge l'undo : sans lui, on ne saurait tester que ce qu'on a deja pense.
OP_TYPES_ECRITS_PAR_L_APP: tuple[str, ...] = (
    "MKDIR",
    "MOVE_DIR",
    "MOVE_FILE",
    "QUARANTINE_DIR",
    "QUARANTINE_FILE",
    "ROLLBACK_COLLECTION_MOVE",
    "ROLLBACK_TV_MOVE",
    "UNDO_QUARANTINE",
    "UNDO_RESTORE",
)


class LaSourceDesOpTypeNAPasDivergeTests(unittest.TestCase):
    """`OPS_DE_DEPLACEMENT` doit etre EXACTEMENT ce que l'undo sait defaire.

    Ce contrat se lit dans les DEUX sens, et le second est le plus dangereux :

    - un `op_type` EN TROP fait compter comme « deplacement » quelque chose que
      l'undo ne rejouera pas ;
    - un `op_type` MANQUANT rend l'invariant MUET sur ce type. Retirer
      `MOVE_DIR` suffirait a ce qu'un run ayant deplace des dossiers — #1103
      exactement — compte zero deplacement et ne leve rien.

    Une premiere version de ce test cherchait les chaines dans le source de
    `apply_rollback.py`. Elle etait unidirectionnelle : un mutant qui RETIRAIT
    `MOVE_DIR` de la liste a SURVECU, la boucle se contentant de verifier moins
    de choses. Elle etait aussi de la forme que `CLAUDE.md` proscrit — comparer
    du texte de code plutot qu'un comportement.

    On interroge donc l'undo lui-meme : `_revert_one_op` refuse explicitement
    tout type hors de sa liste. Aucun fichier n'est touche — les chemins sont
    vides, donc un type ACCEPTE tombe simplement sur le garde suivant.
    """

    @staticmethod
    def _l_undo_accepte(op_type: str) -> bool:
        from cinesort.app.apply_rollback import _revert_one_op

        r = _revert_one_op({"op_type": op_type, "reversible": 1, "undo_status": "PENDING"})
        return "non revert-able" not in str(r.get("reason") or "")

    def test_le_garde_de_l_undo_repond_bien(self):
        """Sans ceci, une sonde muette rendrait le contrat vide : si
        `_l_undo_accepte` renvoyait toujours la meme chose, le test suivant
        serait vert quoi qu'il arrive."""
        self.assertTrue(self._l_undo_accepte("MOVE_FILE"))
        self.assertFalse(self._l_undo_accepte("MKDIR"))
        self.assertFalse(self._l_undo_accepte("CE_TYPE_N_EXISTE_PAS"))

    def test_ops_de_deplacement_est_EXACTEMENT_ce_que_l_undo_defait(self):
        acceptes = {t for t in OP_TYPES_ECRITS_PAR_L_APP if self._l_undo_accepte(t)}
        self.assertEqual(
            acceptes,
            set(OPS_DE_DEPLACEMENT),
            "les deux listes ont diverge : en trop = compte des deplacements que "
            "l'undo ne rejoue pas ; manquant = invariant MUET sur ce type",
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
            "le comptage ne peut pas voir #1103 ; c'est l'invariant d'AMPLEUR qui le voit",
        )


class ComptesTests(unittest.TestCase):
    def test_le_compte_de_quarantaine_n_est_PLUS_compare(self):
        """L'invariant qui comparait `quarantined` aux ops `QUARANTINE_*` a ete
        RETIRE, et ce test fige la raison pour qu'on ne le reintroduise pas.

        Les deux grandeurs ne sont pas comparables. `apply_core.move_to_review_bucket`
        journalise un `QUARANTINE_*` pour TOUT passage sous `_review` — conflits,
        sidecars, leftovers, doublons — via une dizaine de sites d'appel qui
        incrementent SEPT compteurs differents, dont aucun n'est `quarantined`.

        Consequence mesuree : tout apply deplacant un seul leftover levait une
        incoherence. Un faux positif SYSTEMATIQUE, sur un apply parfaitement
        sain — exactement ce que ce module existe pour eviter.

        L'appariement 1:1 n'etant pas demontrable sur les dix sites, l'invariant
        n'est pas « repare » : il est retire. Sa part saine — « le journal bouge
        alors que le payload n'annonce RIEN » — est deja couverte par
        `deplacements_journalises_non_annonces`.
        """
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 1, "renames": 0, "moves": 0},
            [{"op_type": "QUARANTINE_FILE"}, {"op_type": "QUARANTINE_DIR"}],
        )
        self.assertTrue(v.coherent, f"un compte de quarantaine ne doit plus rien lever : {v.as_dict()}")

    def test_un_leftover_vers_review_ne_leve_RIEN(self):
        """Le faux positif qui a fait retirer l'invariant, fige comme contre-test.

        Un apply qui range UN leftover : le journal porte un `QUARANTINE_FILE`,
        le payload annonce `leftovers_moved_count: 1` et `quarantined: 0`.
        """
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 0, "leftovers_moved_count": 1},
            [{"op_type": "QUARANTINE_FILE", "src_path": "D:/films/x.srt"}],
        )
        self.assertTrue(v.coherent, f"faux positif sur un rangement de leftover : {v.as_dict()}")

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
        """En apercu rien n'est journalise. Sans ce garde, un dry-run leverait
        une incoherence — le faux positif qui tue l'outil.

        Le journal est NON VIDE ici, et c'est indispensable. Une premiere version
        passait `[]` : le garde ne changeait alors rien, et le mutant qui le
        SUPPRIMAIT survivait. Un test qui n'expose pas la garde ne la garde pas.
        """
        operations = [{"op_type": "MOVE_FILE"}, {"op_type": "QUARANTINE_FILE"}]
        self.assertFalse(
            comparer_annonce_et_journal({"errors": 0}, operations).coherent,
            "premisse du test : hors dry-run, ce cas DOIT lever — sinon on ne mesure rien",
        )
        self.assertTrue(comparer_annonce_et_journal({"errors": 0}, operations, dry_run=True).coherent)

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
        """Les formes RELEVEES, et le rappel de celle qui etait imaginee.

        Mesurees dans le code qui les ecrit : `undo_status='FAILED'` et
        `error_message` sur `apply_operations` (ecrits par l'UNDO, cf.
        `apply_rollback.py:467`), et `event="error"` sur `apply_audit.jsonl`.

        La cle `error` NUE, elle, n'est produite par AUCUN de ces deux
        producteurs — c'est la forme que j'avais imaginee, et le detecteur ne
        voyait rien. Elle reste acceptee pour les payloads internes, mais ne doit
        plus jamais etre citee comme une forme du journal.
        """
        self.assertTrue(verdicts._en_echec({"undo_status": "FAILED"}))
        self.assertTrue(verdicts._en_echec({"error": "boom"}))
        self.assertFalse(verdicts._en_echec({"undo_status": "DONE"}))
        self.assertFalse(verdicts._en_echec({}))


class LaFormeVientDuCODEDEPRODUCTIONTests(unittest.TestCase):
    """Le test qui aurait attrape l'erreur que les 15 autres ont laissee passer.

    Une premiere version de `_en_echec` cherchait une cle `error`. Elle passait
    tous les tests et tuait tous ses mutants — parce que MOI qui ecrivais les
    tests fournissais la forme que MOI j'avais imaginee. Confrontee aux deux
    sources reelles, elle etait muette sur les deux :

        apply_operations   -> `error_message`, pas `error`
        apply_audit.jsonl  -> `event="error"`, un TYPE, pas une cle

    Un detecteur muet est pire qu'absent : il fait croire que le controle a eu
    lieu. La seule parade est de ne jamais fabriquer la forme soi-meme. Ici les
    evenements sont ecrits par `ApplyAuditLogger` et relus par
    `read_apply_audit` — les deux fonctions de production. Si leur format
    change, ce test rougit ; un dict ecrit a la main, lui, resterait vert pour
    toujours.
    """

    def setUp(self) -> None:
        import shutil
        import tempfile

        self._td = tempfile.mkdtemp(prefix="cinesort_verdict_")
        self.run_dir = Path(self._td)
        self.addCleanup(shutil.rmtree, self._td, ignore_errors=True)

    def _relire(self, ecrire) -> list:
        """Ecrit via le logger de production, relit via le lecteur de production."""
        from cinesort.app.apply_audit import ApplyAuditLogger, audit_path_for_run, read_apply_audit

        with ApplyAuditLogger(audit_path_for_run(self.run_dir), batch_id="b1", run_id="r1") as journal:
            ecrire(journal)
        return read_apply_audit(self.run_dir, batch_id="b1")

    def test_l_alller_retour_produit_bien_des_evenements(self):
        """Sans ce garde, un journal casse rendrait [] et TOUT le reste de cette
        classe serait vert sans rien avoir mesure."""
        evs = self._relire(lambda j: j.error(context="move", message="PermissionError"))
        self.assertTrue(evs, "le journal de production n'a rien rendu : la mesure serait vide")
        self.assertEqual([e.get("event") for e in evs], ["error"])

    def test_un_echec_REEL_est_reconnu(self):
        """C'est le cas exact qui echouait : `event="error"`, aucune cle `error`."""
        evs = self._relire(lambda j: j.error(context="move", message="PermissionError"))
        self.assertNotIn("error", evs[0], "la forme reelle n'a PAS de cle `error` — c'est tout le piege")
        self.assertTrue(verdicts._en_echec(evs[0]))

    def test_1062_de_bout_en_bout_sur_la_forme_REELLE(self):
        """300 echecs ecrits par le code de production, un payload `errors: 0`."""

        def _ecrire(j):
            for i in range(300):
                j.error(context="move", message="PermissionError", row_id=f"r{i}")

        evs = self._relire(_ecrire)
        v = comparer_annonce_et_journal({"errors": 0, "quarantined": 0}, [], evenements_audit=evs)
        self.assertFalse(v.coherent, "300 erreurs REELLES et le verdict ne dit rien")
        inc = next(i for i in v.incoherences if i.code == "succes_annonce_malgre_des_echecs")
        self.assertEqual(inc.journal, {"operations_en_echec": 300})

    def test_un_deplacement_REUSSI_n_est_pas_pris_pour_un_echec(self):
        """Contre-test : `op_move_file` porte `reversible`, `sha1`, `size`. Si
        l'une de ces cles etait prise pour une marque d'echec, chaque apply sain
        leverait — le faux positif qui tue l'outil."""
        evs = self._relire(lambda j: j.op_move_file(row_id="r1", src="a.mkv", dst="b.mkv", sha1="deadbeef", size=42))
        self.assertFalse(verdicts._en_echec(evs[0]), f"faux positif sur un move reussi : {evs[0]}")

    def test_les_conflits_et_skips_ne_sont_pas_des_echecs(self):
        """`op_skip` et `conflict` sont des issues NORMALES : les compter comme
        echecs ferait rougir des apply parfaitement sains."""

        def _ecrire(j):
            j.skip(row_id="r1", reason="user_rejected")
            j.conflict(row_id="r2", src="a", dst="b", conflict_type="dst_exists", resolution="quarantine")

        for ev in self._relire(_ecrire):
            self.assertFalse(verdicts._en_echec(ev), f"pris a tort pour un echec : {ev}")


class LaFormeSQLiteEstCELLEDuDEPOTTests(unittest.TestCase):
    """L'autre source : `apply_operations`, dont la regle d'echec fait autorite.

    `apply_batches_reconciliation.py` classe un batch `ROLLED_BACK` sur
    *`error_message` non vide OU `undo_status='FAILED'`*. C'est la meme regle qui
    doit valoir ici — deux definitions de « echec » dans un meme depot, et l'une
    des deux se tait forcement au mauvais moment.
    """

    #: Les cles EXACTES que `list_apply_operations` construit (apply.py:463).
    LIGNE_TYPE = {
        "id": 1,
        "batch_id": "b1",
        "op_index": 0,
        "op_type": "MOVE_FILE",
        "src_path": "a",
        "dst_path": "b",
        "reversible": 1,
        "undo_status": "PENDING",
        "error_message": "",
    }

    def test_une_ligne_NOMINALE_n_est_pas_un_echec(self):
        self.assertFalse(verdicts._en_echec(dict(self.LIGNE_TYPE)))

    def test_error_message_non_vide_est_un_echec(self):
        """C'est la cle que la premiere version ignorait."""
        self.assertTrue(verdicts._en_echec({**self.LIGNE_TYPE, "error_message": "PermissionError"}))

    def test_undo_status_FAILED_est_un_echec(self):
        self.assertTrue(verdicts._en_echec({**self.LIGNE_TYPE, "undo_status": "FAILED"}))

    def test_les_comptes_se_lisent_bien_sur_CETTE_source(self):
        """`op_type` en MAJUSCULES ici, `event` en minuscules dans le JSONL :
        seule cette source-ci porte de quoi compter."""
        v = comparer_annonce_et_journal(
            {"errors": 0, "quarantined": 0},
            [{**self.LIGNE_TYPE, "op_type": "QUARANTINE_FILE"}],
        )
        self.assertEqual(v.comptes_journal, {"QUARANTINE_FILE": 1})
        self.assertIn("deplacements_journalises_non_annonces", {i.code for i in v.incoherences})


class LesCompteursNONTPasDeriveTests(unittest.TestCase):
    """`COMPTEURS_D_ACTION_DISQUE` doit suivre `ApplyResult`.

    La liste a d'abord ete DEVINEE — quatre compteurs sur dix-huit — et le
    premier apply reel l'a mise en defaut : un nettoyage de buckets incremente
    `applied_count` et `leftovers_moved_count` sans toucher aux quatre, donc le
    verdict criait a l'incoherence sur un apply sain.

    Le probleme n'etait pas la liste, c'etait qu'elle ne pouvait pas se tromper
    BRUYAMMENT. Ce test le lui apprend : ajouter un compteur de deplacement a
    `ApplyResult` sans passer par la liste rougit ici, au lieu de refabriquer le
    faux positif quelques versions plus tard.
    """

    #: Les champs d'`ApplyResult` dont on a VERIFIE qu'ils ne signifient aucune
    #: action sur le disque. Tout le reste doit etre dans la liste.
    SANS_ACTION_DISQUE = frozenset(
        {
            "cleanup_residual_diagnostic",  # detail de diagnostic, pas un compte
            "considered_rows",  # combien de lignes examinees
            "error_messages",  # les libelles d'erreur
            "errors",  # les echecs — couverts par l'invariant n1
            "journal_failures",  # deplacement FAIT mais non journalise
            "skip_reasons",  # pourquoi on n'a rien fait
            "skipped",  # rien n'a bouge, par definition
            "total_rows",  # taille du plan
        }
    )

    def _champs(self) -> set:
        import dataclasses

        from cinesort.domain.core import ApplyResult

        return {f.name for f in dataclasses.fields(ApplyResult)}

    def test_le_dataclass_est_bien_lu(self):
        """Sans ce garde, un import casse rendrait un ensemble vide et les deux
        tests suivants seraient verts sans rien avoir compare."""
        champs = self._champs()
        self.assertGreater(len(champs), 20, "ApplyResult n'a pas ete lu correctement")
        self.assertIn("applied_count", champs)

    def test_aucun_compteur_d_ApplyResult_n_est_OUBLIE(self):
        """Le sens qui produit le faux positif."""
        from cinesort.app.verdicts import COMPTEURS_D_ACTION_DISQUE

        oublies = self._champs() - set(COMPTEURS_D_ACTION_DISQUE) - self.SANS_ACTION_DISQUE
        self.assertEqual(
            oublies,
            set(),
            "ces champs d'ApplyResult ne sont ni classes « action disque » ni "
            "declares sans action : un apply qui ne les incremente qu'eux "
            "rougira a tort. Les trancher explicitement.",
        )

    def test_la_liste_n_INVENTE_pas_de_compteur(self):
        """Le sens inverse : un compteur disparu d'ApplyResult resterait lu a 0
        pour toujours, elargissant silencieusement l'invariant."""
        from cinesort.app.verdicts import COMPTEURS_D_ACTION_DISQUE

        fantomes = set(COMPTEURS_D_ACTION_DISQUE) - self._champs()
        self.assertEqual(fantomes, set(), "ces compteurs n'existent plus dans ApplyResult")


if __name__ == "__main__":
    unittest.main()


class LeJournalJAMAISOUVERTTests(unittest.TestCase):
    """T-PROD-6 : le sens qui manquait, et c'est celui qui ment a l'utilisateur.

    `_verifier_deplacements_tus` couvre un sens : le journal porte des
    deplacements, le payload n'en annonce aucun — l'utilisateur n'a alors aucune
    raison d'annuler. Le sens INVERSE n'etait couvert par rien : le payload
    annonce douze rangements, le journal est vide. L'utilisateur voit « 12 films
    ranges » et un bouton *Annuler* qui ne fera rien.

    Ce n'est pas un cas theorique : quand `insert_apply_batch` echoue,
    `apply_batch_id` reste `None`, `record_apply_op` sort immediatement, et
    l'apply s'execute quand meme. Le mode degrade est documente dans
    `apply_support.py` ; ce qui ne l'etait pas, c'est qu'il rendait un verdict
    VERT.

    Le critere est le journal JAMAIS OUVERT, pas le journal vide. La difference
    est essentielle : si le batch existe et qu'aucune ligne n'y figure, la cause
    peut etre un compteur qui n'ecrit legitimement pas d'operation, et le
    signaler serait un faux positif. Un batch qui n'a jamais ete cree, lui, ne
    laisse aucune place au doute.
    """

    def test_journal_jamais_ouvert_avec_des_actions_annoncees(self) -> None:
        verdict = comparer_annonce_et_journal(
            {"applied_count": 12, "errors": 0},
            [],
            evenements_audit=[],
            dry_run=False,
            journal_ouvert=False,
        )
        self.assertFalse(
            verdict.coherent,
            "12 rangements annonces, aucun journal ouvert : l'apply n'est PAS "
            "annulable et l'utilisateur ne l'apprend nulle part.",
        )
        self.assertIn(
            "journal_absent_malgre_des_actions_annoncees",
            [inc.code for inc in verdict.incoherences],
        )

    def test_journal_jamais_ouvert_mais_RIEN_annonce_reste_coherent(self) -> None:
        """Un apply qui n'a rien fait n'a rien a journaliser."""
        verdict = comparer_annonce_et_journal(
            {"applied_count": 0, "errors": 0},
            [],
            evenements_audit=[],
            dry_run=False,
            journal_ouvert=False,
        )
        self.assertTrue(verdict.coherent, f"faux positif : {[i.code for i in verdict.incoherences]}")

    def test_apercu_ne_declenche_jamais_ce_verdict(self) -> None:
        """En dry_run rien n'est journalise : le batch n'existe pas, c'est normal."""
        verdict = comparer_annonce_et_journal(
            {"applied_count": 12, "errors": 0},
            [],
            evenements_audit=[],
            dry_run=True,
            journal_ouvert=False,
        )
        self.assertTrue(verdict.coherent, f"faux positif en apercu : {[i.code for i in verdict.incoherences]}")

    def test_le_defaut_par_defaut_est_le_comportement_ACTUEL(self) -> None:
        """Sans le parametre, rien ne change pour les appelants existants.

        Le contraire ferait rougir tous les appels deja en place, et un garde
        qui mord tout le monde des sa pose se fait desarmer dans l'heure.
        """
        verdict = comparer_annonce_et_journal(
            {"applied_count": 12, "errors": 0}, [], evenements_audit=[], dry_run=False
        )
        self.assertTrue(verdict.coherent)
