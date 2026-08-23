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
export const __consequence = _CONSEQUENCE_SUPPRESSION_RUN;
"""

# Sortie explicite apres l'emission, comme `test_historique_doublons_affirmation`
# sur ce meme module : si une minuterie restait armee, Node survivrait a
# `__emit` et le harnais attendrait son timeout au lieu de conclure.
_EXIT = "\nprocess.exit(0);\n"

# Un evenement de clic reduit au contrat que `_onActionClick` consomme
# reellement : `ev.target.closest(sel)`, d'abord pour l'onglet d'inspecteur
# (aucun ici), puis pour l'action.
_DRIVER = """
const evenement = (action, runId) => ({
  target: {
    closest: (sel) =>
      sel === "[data-historique-action]" ? { dataset: { historiqueAction: action, runId } } : null,
  },
});
M.__onActionClick(evenement("delete-run", "run-42"));
const m = globalThis.__modales[0] || null;
__emit({
  nb_modales: globalThis.__modales.length,
  consequence: m ? String(m.consequence || "") : null,
  titre: m ? String(m.title || "") : null,
  constante: String(M.__consequence || ""),
  cablee: !!(m && m.consequence === M.__consequence),
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
            1,
            "aucune confirmation demandee avant une suppression definitive (regle n3)",
        )
        self.assertIn("run-42", self.modale["titre"])

    def test_la_consequence_nomme_la_perte_de_l_annulation(self) -> None:
        """Le fond du correctif : dire ce qui est REELLEMENT detruit."""
        consequence = self.modale["consequence"]

        self.assertIn(
            "Annuler l'apply",
            consequence,
            "la modale ne nomme pas la capacite qu'elle detruit : le journal "
            "d'undo (apply_batches + apply_operations en CASCADE) part avec le run",
        )

    def test_elle_ne_se_contente_plus_de_rassurer(self) -> None:
        """Contre-epreuve de la phrase d'origine.

        « Aucune modification sur les fichiers vidéo du disque » etait vraie au
        pied de la lettre et lue comme « rien a craindre ». Ce test refuse le
        retour a une formulation qui s'arrete a la partie rassurante.
        """
        consequence = self.modale["consequence"]

        self.assertNotIn("Aucune modification sur les fichiers vidéo", consequence)
        self.assertIn("détruit", consequence)

    def test_le_handler_passe_BIEN_cette_constante(self) -> None:
        """Le SITE D'APPEL, pas seulement la valeur.

        Un mutant qui remet une chaine en dur dans `dangerConfirmModal({...})`
        laisserait les trois tests precedents verts si l'on n'assertait que sur
        la constante. On exige l'identite entre ce que la modale recoit et ce
        que le module declare.
        """
        self.assertTrue(
            self.modale["cablee"],
            "le handler `delete-run` n'utilise plus `_CONSEQUENCE_SUPPRESSION_RUN` : "
            f"recu {self.modale['consequence']!r}, attendu {self.modale['constante']!r}",
        )


if __name__ == "__main__":
    unittest.main()
