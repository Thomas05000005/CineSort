"""Un fichier modifie a la main ne doit plus bloquer la restauration des autres.

MESURE du defaut : l'undo est atomique par defaut. Si UN SEUL fichier a ete
modifie depuis l'apply, il refuse TOUT — 1 fichier touche sur 5, et c'est 0 sur 5
qui sont restaures.

Le backend sait pourtant faire autrement (`_execute_undo_ops` avec
`atomic=False`). Ce mode n'etait atteignable qu'en REST BRUT : `historique.js`
forcait `atomic: true` et `traitement.js` l'omet. L'utilisateur n'avait aucun
moyen, depuis l'application, de recuperer ses quatre films intacts.

CES TESTS EXECUTENT LA VRAIE SOURCE. Une premiere version comparait des chaines
du fichier JavaScript — ce que la regle du depot proscrit, et pour une raison
que ce meme fichier a demontree : la mutation `if (false && condition)` laissait
le test VERT, puisque `condition` etait toujours presente dans la source. Le
harnais `_jsexec` charge `historique.js`, neutralise ses seuls imports (remplaces
par des doublures) et fait tourner le code de production sous Node.
"""

from __future__ import annotations

import unittest

from tests._jsexec import DASHBOARD, require_node, run_module_test

_JS = DASHBOARD / "views" / "historique.js"

# Doublures des imports de `historique.js`. Seules `apiPost`,
# `dangerConfirmModal` et `showToast` comptent ici ; les autres existent pour
# que le module se charge.
_STUBS = r"""
globalThis.__appels = [];
globalThis.__modales = [];
globalThis.__toasts = [];
globalThis.__reponses = [];

// `__appels` ne retient QUE les appels d'undo. Le chemin de succes enchaine sur
// `_refreshRuns`, qui fait ses propres `apiPost` : les compter aurait rendu les
// assertions dependantes d'un rafraichissement sans rapport avec le sujet.
const apiPost = async (route, params) => {
  if (route === "run/undo_last_apply") {
    __appels.push({ route, params });
    return __reponses.shift() || { data: { ok: true, counts: { done: 0, skipped: 0 } } };
  }
  return { data: { ok: true, runs: [], items: [] } };
};
const cachedGetSettings = async () => ({});
const escapeHtml = (s) => String(s == null ? "" : s);
const getNavSignal = () => ({ aborted: false });
const navigateTo = () => {};
const deriveRunStatus = () => "done";
const rightPanel = { open: () => {}, close: () => {} };
const dangerConfirmModal = (opts) => { __modales.push(opts); };
const showModal = () => {};
const closeModal = () => {};
const showToast = (o) => { __toasts.push(o); };
const buildEmptyState = () => "";
"""

# `_doUndoApply` et `_proposerUndoPartiel` sont des fonctions de module, non
# exportees : on les expose au driver sans toucher a leur corps.
_EXTRA = r"""
export const __doUndoApply = _doUndoApply;
export const __refreshRunsStub = () => {};
"""


def _executer(driver: str) -> dict:
    return run_module_test(_JS, stubs=_STUBS, extra=_EXTRA, driver=driver)


class ReplPartielTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def test_un_refus_atomique_PROPOSE_le_repli(self) -> None:
        """Le coeur du defaut : sans cette branche, l'utilisateur ne voyait
        qu'un message d'echec et repartait avec zero film restaure."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: {
              ok: false, status: "ABORTED_HASH_MISMATCH",
              preverify: { safe_count: 4, hash_mismatch_count: 1,
                           mismatch_details: [{ dst_path: "D:/Films/Alien (1979)/alien.mkv" }] },
            }});
            await M.__doUndoApply("r1");
            __emit({ appels: __appels, modales: __modales.map(m => ({
              titre: m.title, items: m.items, itemCount: m.itemCount,
              countdown: m.countdownSeconds, consequence: m.consequence })) });
            """
        )
        self.assertEqual(len(res["appels"]), 1, "le premier essai doit etre unique")
        self.assertIs(res["appels"][0]["params"]["atomic"], True, "le premier essai doit etre ATOMIQUE")
        self.assertEqual(len(res["modales"]), 1, f"aucun repli propose : {res}")
        self.assertIn("4", res["modales"][0]["titre"])

    def test_la_confirmation_relance_en_atomic_FALSE(self) -> None:
        """C'est ce second appel qui restaure reellement les fichiers intacts."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: {
              ok: false, status: "ABORTED_HASH_MISMATCH",
              preverify: { safe_count: 4, hash_mismatch_count: 1, mismatch_details: [] },
            }});
            __reponses.push({ data: { ok: true, status: "UNDONE_PARTIAL",
                                      counts: { done: 4, skipped: 1 } }});
            await M.__doUndoApply("r1");
            await __modales[0].onConfirm();
            __emit({ appels: __appels, toasts: __toasts });
            """
        )
        self.assertEqual(len(res["appels"]), 2, f"le repli n'a pas relance l'undo : {res['appels']}")
        self.assertIs(res["appels"][1]["params"]["atomic"], False, "le repli doit demander le mode best-effort")

    def test_le_delai_de_3s_s_applique_au_dela_de_50_RESTAURES(self) -> None:
        """Regle projet n3. Le compte a rebours se calibre sur ce qui est
        REELLEMENT DEPLACE (`restaurables`), pas sur les fichiers laisses en
        place — c'est l'erreur de la premiere version."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: {
              ok: false, status: "ABORTED_HASH_MISMATCH",
              preverify: { safe_count: 200, hash_mismatch_count: 2, mismatch_details: [] },
            }});
            await M.__doUndoApply("r1");
            __emit({ countdown: __modales[0].countdownSeconds, itemCount: __modales[0].itemCount });
            """
        )
        self.assertEqual(res["countdown"], 3, "200 films deplaces sans delai de confirmation")
        self.assertEqual(res["itemCount"], 200, "le compte est calibre sur les fichiers NON deplaces")

    def test_sous_le_seuil_aucun_delai_n_est_impose(self) -> None:
        """Contre-epreuve : un delai systematique userait la confirmation."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: {
              ok: false, status: "ABORTED_HASH_MISMATCH",
              preverify: { safe_count: 3, hash_mismatch_count: 1, mismatch_details: [] },
            }});
            await M.__doUndoApply("r1");
            __emit({ countdown: __modales[0].countdownSeconds });
            """
        )
        self.assertEqual(res["countdown"], 0)

    def test_ZERO_restaurable_ne_propose_RIEN(self) -> None:
        """Ouvrir une modale destructive dont la seule issue est « 0 restaure »
        userait la confirmation exactement quand elle doit porter."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: {
              ok: false, status: "ABORTED_HASH_MISMATCH",
              preverify: { safe_count: 0, hash_mismatch_count: 3, mismatch_details: [] },
            }});
            await M.__doUndoApply("r1");
            __emit({ modales: __modales.length, toasts: __toasts });
            """
        )
        self.assertEqual(res["modales"], 0, "une modale destructive s'ouvre pour ne rien restaurer")
        self.assertEqual(res["toasts"][0]["type"], "error")


class MessagesHonnetesTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def test_le_toast_DIT_combien_ont_ete_laisses(self) -> None:
        """« Apply annule. Fichiers restaures. » se lisait comme un succes
        COMPLET, y compris quand un film sur cinq etait reste en place."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: { ok: true, status: "UNDONE_PARTIAL",
                                      counts: { done: 4, skipped: 1 } }});
            await M.__doUndoApply("r1", { atomic: false });
            __emit({ toasts: __toasts });
            """
        )
        texte = res["toasts"][0]["text"]
        self.assertIn("4", texte)
        self.assertIn("1", texte)
        self.assertIn("laissé", texte.lower())

    def test_UNDONE_NONE_n_est_PAS_annonce_comme_un_succes(self) -> None:
        """Le backend distingue desormais « rien restaure » de « tout restaure » ;
        sans cette branche la distinction mourait au dernier metre."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: { ok: true, status: "UNDONE_NONE",
                                      message: "Aucun film n'a été restauré.",
                                      counts: { done: 0, skipped: 2 } }});
            await M.__doUndoApply("r1");
            __emit({ toasts: __toasts });
            """
        )
        self.assertEqual(res["toasts"][0]["type"], "warn", f"annonce comme un succes : {res['toasts']}")


class CheminNominalTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def test_un_undo_qui_REUSSIT_ne_propose_aucun_repli(self) -> None:
        """Non-regression : le cas courant ne doit rien declencher de neuf."""
        res = _executer(
            """
            globalThis._refreshRuns = async () => {};
            __reponses.push({ data: { ok: true, status: "UNDONE_DONE",
                                      counts: { done: 5, skipped: 0 } }});
            await M.__doUndoApply("r1");
            __emit({ appels: __appels.length, modales: __modales.length,
                     toast: __toasts[0] });
            """
        )
        self.assertEqual(res["appels"], 1)
        self.assertEqual(res["modales"], 0)
        self.assertEqual(res["toast"]["type"], "success")


if __name__ == "__main__":
    unittest.main()
