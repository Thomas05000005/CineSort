"""« Supprimer ce run » detruit le journal d'undo, et la modale disait l'inverse.

LE DEFAUT. Dans l'inspecteur de l'ecran Historique, deux boutons sont rendus
COTE A COTE pour le meme run (`historique.js`, section « Actions ») :

    ↺ Annuler l'apply     rendu si `isApply && status !== "UNDONE"`
    🗑 Supprimer ce run    rendu SANS AUCUNE CONDITION

Le second annoncait :

    « Le run + son plan + son log seront supprimés définitivement.
      Aucune modification sur les fichiers vidéo du disque. Action NON réversible. »

La deuxieme phrase est litteralement vraie — et c'est ce qui la rend trompeuse.
`run/delete_run` ne deplace aucun fichier, mais il supprime `apply_batches` et,
par CASCADE, `apply_operations` : le journal grace auquel le premier bouton
remet les dossiers a leur place. Apres la suppression,
`build_undo_preview_payload` echoue DEUX fois — `_find_run_row` ne trouve plus
la ligne `runs`, et `get_last_reversible_apply_batch` plus le batch.

La modale rassurait donc exactement la ou la perte a lieu. La regle n3 du depot
(`/CLAUDE.md`) exige d'une action destructive qu'elle annonce LA CONSEQUENCE ;
celle-ci annoncait une absence de consequence.

PORTEE HONNETE. L'undo reel est de toute facon refuse au-dela de
`UNDO_DEADLINE_SECONDS` (24 h, `domain/run_models.py`). La fenetre de perte est
donc celle des 24 h qui suivent l'apply — mais c'est precisement la fenetre
pendant laquelle l'ecran AFFICHE « ↺ Annuler l'apply », donc pendant laquelle il
promet la capacite qu'un clic voisin detruit.

POURQUOI CE TEST EXECUTE LE JS AU LIEU DE LIRE LA SOURCE. Une assertion
`assertIn("...", source)` passerait au vert des qu'on ecrit la bonne chaine
n'importe ou dans le fichier — y compris dans un commentaire, y compris sans que
le handler s'en serve. Ce fichier charge donc la VRAIE source sous Node
(harnais `tests/_jsexec.py`, deja utilise sur ce meme module et sur ce meme
`_onActionClick` par `tests/test_undo_compensate_ui.py`, dont les doublures sont
reprises telles quelles), declenche le VRAI `_onActionClick` avec une action
`delete-run`, et observe l'objet REELLEMENT passe a `dangerConfirmModal`.

C'est ce qui fait la difference avec le mutant que le depot a vu survivre trois
fois (`/CLAUDE.md`, « tester la decision ne dit RIEN du site d'appel ») : si
quelqu'un cesse de cabler la constante dans le handler, `test_le_handler_passe_
BIEN_cette_constante` rougit, alors qu'un test de contenu resterait vert.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"

# Doublures des imports de `historique.js`, reprises TELLES QUELLES de
# `tests/test_undo_compensate_ui.py` — le test qui exerce deja `_onActionClick`
# sur ce meme module et qui passe en CI. On ne reinvente pas un harnais quand un
# harnais eprouve existe, et un stub de plus est un risque de collision de plus.
#
# `dangerConfirmModal` est la seule doublure qui compte ici : elle CAPTURE
# l'objet d'options, c'est-a-dire ce que l'utilisateur lira.
_STUBS = r"""
globalThis.__modales = [];

const apiPost = async () => ({ data: { ok: true, runs: [], items: [] } });
const cachedGetSettings = async () => ({});
const escapeHtml = (s) => String(s == null ? "" : s);
const getNavSignal = () => ({ aborted: false });
const navigateTo = () => {};
const deriveRunStatus = () => "done";
const rightPanel = { open: () => {}, close: () => {} };
const dangerConfirmModal = (opts) => { __modales.push(opts); };
const showModal = () => {};
const closeModal = () => {};
const showToast = () => {};
const buildEmptyState = () => "";
"""

_EXTRA = """
export const __onActionClick = _onActionClick;
export const __consequence = _consequenceSuppressionRun;

// INSTRUMENTATION DU SITE D'APPEL.
//
// Comparer `modale.consequence === __consequence(true)` compare deux CHAINES :
// un mutant qui recopie le texte en dur dans `dangerConfirmModal({...})` rend
// la meme valeur et passe l'assertion. C'est une egalite de valeur, pas
// d'identite, et JS n'offre pas la seconde sur des primitives.
//
// On remplace donc la fonction par une doublure qui rend une SENTINELLE
// impossible a produire autrement. Une declaration `function f(){}` cree une
// liaison REASSIGNABLE dans son scope, et ce bloc est concatene dans le meme
// module que la source : la reaffectation atteint donc le site d'appel reel.
const __vraieConsequence = _consequenceSuppressionRun;
export const __instrumenter = () => {
  _consequenceSuppressionRun = (undoEncorePossible) =>
    "SENTINELLE#" + String(undoEncorePossible);
};
export const __restaurer = () => { _consequenceSuppressionRun = __vraieConsequence; };
"""

# Sortie explicite apres l'emission, comme `test_historique_doublons_affirmation`
# sur ce meme module : si une minuterie restait armee, Node survivrait a
# `__emit` et le harnais attendrait son timeout au lieu de conclure.
_EXIT = "\nprocess.exit(0);\n"

# Un evenement de clic reduit au contrat que `_onActionClick` consomme
# reellement : `ev.target.closest(sel)`, d'abord pour l'onglet d'inspecteur
# (aucun ici), puis pour l'action.
_DRIVER = """
const evenement = (action, runId, undoPossible) => ({
  target: {
    closest: (sel) =>
      sel === "[data-historique-action]"
        ? { dataset: { historiqueAction: action, runId, undoPossible } }
        : null,
  },
});
// LES DEUX CAS. Le texte est CONDITIONNEL : n'en exercer qu'un laisserait
// passer une fonction qui ignore son argument et rend toujours la meme chose.
M.__onActionClick(evenement("delete-run", "run-42", "1"));
M.__onActionClick(evenement("delete-run", "run-43", "0"));
// Troisieme et quatrieme clics, fonction INSTRUMENTEE : ce que la modale
// recoit doit etre ce que la fonction PRODUIT, pas un texte identique.
M.__instrumenter();
M.__onActionClick(evenement("delete-run", "run-44", "1"));
M.__onActionClick(evenement("delete-run", "run-45", "0"));
M.__restaurer();
const avec = globalThis.__modales[0] || null;
const sans = globalThis.__modales[1] || null;
const sentinelle_avec = globalThis.__modales[2] || null;
const sentinelle_sans = globalThis.__modales[3] || null;
__emit({
  nb_modales: globalThis.__modales.length,
  consequence: avec ? String(avec.consequence || "") : null,
  consequence_sans_undo: sans ? String(sans.consequence || "") : null,
  titre: avec ? String(avec.title || "") : null,
  cablee: !!(avec && avec.consequence === M.__consequence(true)),
  cablee_sans_undo: !!(sans && sans.consequence === M.__consequence(false)),
  sentinelle_avec: sentinelle_avec ? String(sentinelle_avec.consequence || "") : null,
  sentinelle_sans: sentinelle_sans ? String(sentinelle_sans.consequence || "") : null,
});
"""


class LaModaleDeSuppressionAnnonceLaPerteDeLUndoTests(unittest.TestCase):
    """L'objet observe est celui que `dangerConfirmModal` recoit en production."""

    def setUp(self) -> None:
        require_node(self)
        self.modale = run_module_test(
            HISTORIQUE_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_DRIVER + _EXIT,
            timeout=90,
        )

    def test_une_confirmation_est_bien_demandee(self) -> None:
        """Garde anti-silence : sans modale, toutes les assertions suivantes
        porteraient sur `None` et passeraient pour de mauvaises raisons."""
        self.assertEqual(
            self.modale["nb_modales"],
            4,
            "aucune confirmation demandee avant une suppression definitive (regle n3)",
        )
        self.assertIn("run-42", self.modale["titre"])

    def test_la_consequence_nomme_la_perte_de_l_annulation(self) -> None:
        """Le fond du correctif : dire ce qui est REELLEMENT detruit."""
        consequence = self.modale["consequence"]

        self.assertIn(
            "annulation de cet apply",
            consequence,
            "la modale ne nomme pas la capacite qu'elle detruit : le journal "
            "d'undo (apply_batches + apply_operations en CASCADE) part avec le run",
        )

    def test_l_avertissement_n_apparait_QUE_si_l_undo_est_possible(self) -> None:
        """C'est ce test qui rend la CONDITION mesurable.

        Sans lui, une fonction qui ignore son argument et rend toujours
        l'avertissement passerait les autres — et alarmerait sur un run sans
        apply, ou il n'y a rien a perdre. Alarmer a tort et rassurer a tort sont
        le meme defaut."""
        avec = self.modale["consequence"]
        sans = self.modale["consequence_sans_undo"]

        self.assertIn("DÉFINITIVEMENT impossible", avec)
        self.assertNotIn(
            "DÉFINITIVEMENT impossible",
            sans,
            "un run sans apply reversible n'a pas de journal a perdre",
        )
        self.assertNotEqual(avec, sans, "le texte ne depend pas de la condition")

    def test_les_DECISIONS_perdues_sont_nommees(self) -> None:
        """Mesure sur `_TABLES_PORTANT_RUN_ID` : `duplicate_decisions`,
        `film_marked_for_deletion`, `film_tmdb_overrides` et
        `user_quality_feedback` portent toutes `run_id` DANS leur cle
        d'identite. Leur purge est correcte — mais l'utilisateur perd des heures
        d'arbitrage manuel sans en etre averti.

        Present dans les DEUX cas : ces pertes n'ont rien a voir avec l'undo."""
        for cle in ("consequence", "consequence_sans_undo"):
            with self.subTest(cas=cle):
                texte = self.modale[cle]
                for attendu in ("doublons", "marqués", "TMDb", "qualité"):
                    self.assertIn(attendu, texte)

    def test_elle_ne_ment_PAS_sur_ce_qui_survit(self) -> None:
        """Contre-epreuve, dans les deux sens.

        « Aucune modification sur les fichiers vidéo du disque » est VRAIE et
        doit rester : une version anterieure de ce test l'interdisait, ce qui
        revenait a mesurer la formulation plutot que le fond.

        Ce qui etait faux, c'est « le run + son plan + son log seront supprimés
        définitivement » : la docstring de `delete_run` dit que le plan, le log
        et le fichier de validation RESTENT sur disque jusqu'a la rotation de
        retention."""
        for cle in ("consequence", "consequence_sans_undo"):
            with self.subTest(cas=cle):
                texte = self.modale[cle]
                self.assertIn("Aucune modification sur les fichiers vidéo", texte)
                self.assertIn("NE sont PAS supprimés", texte)
                self.assertNotIn("son plan + son log seront supprimés", texte)

    def test_le_handler_passe_BIEN_cette_fonction(self) -> None:
        """Le SITE D'APPEL, pas seulement la valeur.

        Un mutant qui remet une chaine en dur dans `dangerConfirmModal({...})`
        laisserait les tests precedents verts si l'on n'assertait que sur la
        fonction. On exige l'identite entre ce que la modale recoit et ce que le
        module produit POUR LE MEME ARGUMENT — les deux cas, sinon un handler
        qui passe toujours `true` resterait invisible.
        """
        self.assertTrue(
            self.modale["cablee"],
            "le handler `delete-run` n'appelle pas `_consequenceSuppressionRun(true)` : "
            f"recu {self.modale['consequence']!r}",
        )
        self.assertTrue(
            self.modale["cablee_sans_undo"],
            f"le handler ne transmet pas `undoEncorePossible` : recu {self.modale['consequence_sans_undo']!r}",
        )

    def test_le_handler_APPELLE_la_fonction_et_ne_recopie_pas_son_texte(self) -> None:
        """L'egalite de CHAINES ne prouve pas le cablage.

        `modale.consequence === __consequence(true)` compare deux valeurs
        primitives : un mutant qui recopie le texte en dur dans
        `dangerConfirmModal({...})` rend la meme chaine et passe l'assertion.
        JS n'offre pas d'identite sur des primitives.

        Le driver remplace donc la fonction par une doublure qui rend une
        SENTINELLE, impossible a produire autrement, et refait les deux clics.
        Ce que la modale recoit alors ne peut venir que de l'appel."""
        self.assertEqual(self.modale["sentinelle_avec"], "SENTINELLE#true")
        self.assertEqual(
            self.modale["sentinelle_sans"],
            "SENTINELLE#false",
            "le handler ne transmet pas `undoEncorePossible` a la fonction",
        )


if __name__ == "__main__":
    unittest.main()
