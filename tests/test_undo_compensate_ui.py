"""Un fichier modifie ne doit plus empecher de restaurer les autres.

MESURE du defaut : l'undo est atomique par defaut. Si UN SEUL fichier a ete
modifie depuis l'apply, il refuse TOUT — 1 fichier touche a la main sur 5, et
c'est 0 sur 5 qui sont restaures.

Le backend sait pourtant faire autrement : `atomic=false` restaure les fichiers
intacts et ignore les autres (`_execute_undo_ops`). Ce mode n'etait atteignable
qu'en REST BRUT — `historique.js` forcait `atomic: true`, et `traitement.js`
l'omet (le defaut vaut True). L'utilisateur n'avait donc aucun moyen, depuis
l'application, de recuperer ses quatre films intacts.

Arbitrage Thomas (2026-08-06) : restaurer les N intacts, laisser les autres,
derriere la modale destructive — liste, consequence, delai derive du nombre.

Ces tests lisent le source JS. C'est assume et borne : ils n'assertent que sur la
PRESENCE des elements de la politique, pas sur une mise en forme.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_HISTORIQUE = Path("web/dashboard/views/historique.js")


def _source() -> str:
    return _HISTORIQUE.read_text(encoding="utf-8")


class ReplPartielProposeTests(unittest.TestCase):
    def test_le_refus_atomique_est_INTERCEPTE(self) -> None:
        """Sans cette branche, la reponse `ABORTED_HASH_MISMATCH` tombait dans
        le `else` generique et l'utilisateur ne voyait qu'un message d'echec.

        Ce test exigeait d'abord la seule PRESENCE de la chaine — il restait donc
        vert avec la branche desactivee (`if (false && _payload.status === ...)`),
        ce que la mutation a montre. Il exige maintenant que la garde soit
        ATTEIGNABLE : le premier terme doit etre `atomic`, pas une constante.
        """
        source = _source()

        self.assertIn("_proposerUndoPartiel", source)
        self.assertRegex(
            source,
            r"if\s*\(\s*atomic\s*&&\s*_payload\.status\s*===\s*\"ABORTED_HASH_MISMATCH\"\s*\)",
            "la garde du repli n'est pas conditionnee au mode atomique : branche morte ou toujours prise",
        )
        self.assertNotRegex(
            source,
            r"if\s*\(\s*(?:false|0)\s*&&",
            "une garde neutralisee par une constante subsiste dans ce fichier",
        )

    def test_le_repli_appelle_bien_atomic_FALSE(self) -> None:
        source = _source()

        self.assertRegex(
            source,
            r"_doUndoApply\(runId,\s*\{\s*atomic:\s*false\s*\}\)",
            "le repli ne demande pas le mode best-effort : il refuserait a nouveau tout",
        )

    def test_le_repli_passe_par_la_MODALE_DESTRUCTIVE(self) -> None:
        """Regle projet n3 : liste des elements, consequence, delai."""
        source = _source()
        debut = source.index("function _proposerUndoPartiel")
        bloc = source[debut : debut + 2200]

        self.assertIn("dangerConfirmModal", bloc)
        self.assertIn("items:", bloc)
        self.assertIn("itemCount:", bloc)
        self.assertIn("consequence:", bloc)

    def test_la_consequence_dit_ce_qui_est_LAISSE_en_place(self) -> None:
        """« Restaurer N films » sans dire ce qui ne le sera pas serait la meme
        demi-verite que le message d'origine."""
        source = _source()
        debut = source.index("function _proposerUndoPartiel")
        bloc = source[debut : debut + 2200]

        self.assertIn("LAISSÉS EN PLACE", bloc)

    def test_zero_restaurable_ne_propose_RIEN(self) -> None:
        """Contre-epreuve : ouvrir une modale destructive dont la seule issue est
        « 0 restaure » userait la confirmation exactement quand elle doit porter."""
        source = _source()
        debut = source.index("function _proposerUndoPartiel")
        bloc = source[debut : debut + 2200]

        self.assertIn("restaurables <= 0", bloc)
        self.assertLess(
            bloc.index("restaurables <= 0"),
            bloc.index("dangerConfirmModal"),
            "le garde doit precederer l'ouverture de la modale",
        )


class MessagesHonnetesTests(unittest.TestCase):
    def test_le_toast_de_succes_DIT_le_nombre(self) -> None:
        """« Apply annule. Fichiers restaures. » se lisait comme un succes
        complet, y compris quand 1 film sur 5 avait ete laisse en place."""
        source = _source()

        self.assertNotIn('text: "Apply annulé. Fichiers restaurés."', source)
        self.assertIn("laissé(s) en place", source)

    def test_UNDONE_NONE_n_est_pas_annonce_comme_un_succes(self) -> None:
        """Le backend distingue desormais « rien restaure » de « tout restaure » ;
        l'UI doit suivre, sinon la distinction meurt au dernier metre."""
        source = _source()

        self.assertIn('_payload.status === "UNDONE_NONE"', source)
        bloc = source[source.index('_payload.status === "UNDONE_NONE"') :][:400]
        self.assertIn('type: "warn"', bloc)


class NonRegressionTests(unittest.TestCase):
    def test_le_chemin_NOMINAL_reste_atomique(self) -> None:
        """Le premier essai doit rester atomique : on ne bascule en best-effort
        qu'apres un refus EXPLICITE et une confirmation de l'utilisateur."""
        source = _source()
        appels = re.findall(r"apiPost\(\"run/undo_last_apply\",\s*\{([^}]*)\}", source)

        self.assertTrue(appels, "l'appel d'undo a disparu ou change de forme")
        for args in appels:
            self.assertIn("atomic", args, f"undo sans mode atomique explicite : {args}")


if __name__ == "__main__":
    unittest.main()
