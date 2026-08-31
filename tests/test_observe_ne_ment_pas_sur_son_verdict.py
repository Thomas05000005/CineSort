# -*- coding: utf-8 -*-
"""`observe.py` rendait un verdict propre sans avoir rien observe.

Trois mensonges cumulables, mesures le 2026-08-31
-------------------------------------------------
1. **`main()` retournait 0 inconditionnellement.** Si playwright est absent,
   `observe_dashboard` rend `{"ok": False, "views": []}` et le processus sortait
   quand meme en 0 : un appelant qui lit le code de sortie concluait
   « observation reussie » alors que RIEN n'avait ete observe.

2. **`summary["ok"] = True` etait pose apres la boucle**, sans regarder les
   `view_summary["nav_error"]` accumules. Toutes les vues pouvaient avoir echoue
   a naviguer, le rapport annoncait `ok: True`.

3. **`POSTERS_ABSENTS` ne remontait pas au sommaire.** Une vue qui n'a rien rendu
   donne `posters_expected == 0`, donc ce verdict — et `broken_posters_detected`
   reste False, puisqu'il ne vaut True que sur `POSTERS_KO`. Ce flag est marque
   `[FIGE]` pour compatibilite et n'est pas touche ; ce qui manquait, c'est que
   l'absence remonte, la ou `POSTERS_KO` remonte deja.

C'est la famille des trois mesureurs de #1175 : un outil de diagnostic qui rend
un chiffre propre sans mesurer. Un outil qui ne peut pas echouer ne diagnostique
rien.

Ce que ce test N'EST PAS
------------------------
Il ne lance ni playwright ni l'application. Il eprouve la DECISION — le passage
du verdict au code de sortie — en substituant `observe_dashboard`. Le reste du
pipeline est couvert ailleurs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_RACINE = Path(__file__).resolve().parents[1]
_OBSERVE = _RACINE / "scripts" / "observe.py"


def _charger_observe():
    """Charge `scripts/observe.py` comme module (il n'est pas un paquet)."""
    spec = importlib.util.spec_from_file_location("_observe_sous_test", _OBSERVE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_observe_sous_test"] = module
    spec.loader.exec_module(module)
    return module


class LeCodeDeSortieDitLaVeriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observe = _charger_observe()
        self._tmp = tempfile.mkdtemp(prefix="cinesort_observe_verdict_")
        self.out = Path(self._tmp) / "out"

    def _lancer(self, faux_dashboard: dict) -> int:
        """Execute `main()` en substituant la seule observation reelle."""
        with mock.patch.object(self.observe, "observe_dashboard", return_value=faux_dashboard):
            return int(self.observe.main(["--modes", "dashboard", "--out", str(self.out), "--use-local-state"]))

    def test_une_observation_qui_a_ECHOUE_ne_sort_pas_en_zero(self) -> None:
        """Le cas playwright absent : `ok: False`, `views: []`, et pourtant 0."""
        code = self._lancer({"ok": False, "views": [], "error": "playwright indisponible"})

        self.assertEqual(
            code,
            1,
            "un rapport `ok: False` sortait en 0 : l'appelant concluait "
            "« observation reussie » alors que rien n'avait ete observe",
        )

    def test_une_observation_REUSSIE_sort_bien_en_zero(self) -> None:
        """Contre-epreuve, sans laquelle « toujours 1 » passerait le test
        precedent — et rendrait l'outil inutilisable dans une chaine."""
        code = self._lancer({"ok": True, "views": [{"route": "/accueil"}], "views_with_broken_posters": []})

        self.assertEqual(code, 0)

    def test_le_motif_de_l_echec_est_ECRIT(self) -> None:
        """Un code de sortie sans motif oblige a relire le JSON. Le message doit
        nommer la cause sur stderr, la ou l'appelant la lit."""
        flux = io.StringIO()
        with mock.patch.object(sys, "stderr", flux):
            self._lancer({"ok": False, "views": [], "error": "playwright indisponible"})

        sortie = flux.getvalue()
        self.assertIn("ECHEC", sortie)
        self.assertIn("playwright indisponible", sortie)


class LeRapportNeSeDECLAREPasSainSansRaisonTests(unittest.TestCase):
    """Ces deux invariants portent sur la CONSTRUCTION du sommaire.

    On ne peut pas les exercer sans navigateur ; on verifie donc que le code
    qui les porte existe et lie bien les deux grandeurs. C'est un controle de
    SOURCE, assume comme tel : le sommaire n'est pas atteignable autrement, et
    un test qui ne mesure rien serait pire que celui-ci.
    """

    def setUp(self) -> None:
        self.source = io.open(_OBSERVE, encoding="utf-8").read()

    def test_ok_depend_des_erreurs_de_navigation(self) -> None:
        """`summary["ok"] = True` inconditionnel ignorait `nav_error`."""
        self.assertIn('summary["ok"] = not vues_en_erreur', self.source)
        self.assertNotIn('summary["ok"] = True', self.source)

    def test_l_absence_totale_de_jaquettes_REMONTE_au_sommaire(self) -> None:
        """`POSTERS_ABSENTS` etait un verdict de vue sans echo au sommaire,
        alors que `POSTERS_KO` y remonte. « Rien observe » n'est pas « rien de
        casse »."""
        self.assertIn('"views_with_posters_absents": []', self.source)
        self.assertIn('summary["views_with_posters_absents"].append(label)', self.source)

    def test_le_sommaire_reste_SERIALISABLE(self) -> None:
        """Garde anti-silence : les deux cles ajoutees doivent etre des listes
        de chaines, sinon `json.dumps` du rapport casserait en production —
        panne qu'aucun des controles de source ci-dessus ne verrait."""
        json.dumps({"views_with_posters_absents": ["/accueil"], "views_with_nav_error": []})


if __name__ == "__main__":
    unittest.main()
