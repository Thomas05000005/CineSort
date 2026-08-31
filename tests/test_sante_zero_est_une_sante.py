# -*- coding: utf-8 -*-
"""Une sante de 0 est la PIRE sante, pas une absence de mesure.

LE DEFAUT
---------
`dashboard_support._compute_active_insights` lisait la sante de la bibliotheque
par ``int(librarian_data.get("health_score") or 100)``. Python evalue le falsy,
pas l'absence : un score de **0** — la pire bibliotheque possible — devenait
**100**, et l'insight `health_low` (qui se declenche sous 60) ne pouvait donc
PAS se declencher sur le seul cas ou il compte le plus.

Le comportement n'etait pas seulement faux, il etait NON MONOTONE : une sante
de 59 alertait, une sante de 0 ne disait rien.

POURQUOI 0 EST ATTEIGNABLE, ET PAS QU'EN THEORIE
------------------------------------------------
`domain/librarian.generate_suggestions` rend
``round(100 * healthy / total_rows)``. Le bloc C (sous-titres manquants) marque
comme « a probleme » toute ligne a laquelle il manque une langue attendue —
`fr` par defaut. Une bibliotheque anglophone, ou simplement une bibliotheque
dont l'utilisateur ne telecharge pas de sous-titres, met donc TOUTES ses lignes
dans `problem_ids` : `healthy = 0`, donc `health_score = 0`.

Ce n'est pas une deduction : `tests/test_lot_librarian_rules_617_662_723.py`
asserte deja `generate_suggestions(...)["health_score"] == 0`. Le domaine
produisait bien 0 ; c'est la couche `ui` qui le relevait a 100.

OU CA ATTERRIT
--------------
`get_global_stats` passe le resultat a `_compute_active_insights`, dont la
sortie part dans `notifications_support.emit_from_insights` — le CENTRE DE
NOTIFICATIONS, seul canal qui survit a la fermeture de l'ecran. Un insight
supprime ici n'est donc pas seulement absent d'un encart : il n'est emis nulle
part.

CE QUE CHAQUE TEST PROUVE
-------------------------
- `test_sante_zero_declenche_l_insight` : le cas du defaut. ROUGE sans le
  correctif (`0 or 100` -> 100 -> `health < 60` faux -> aucun insight).
- `test_sante_zero_est_une_alerte_et_non_une_info` : la severite se calcule sur
  la vraie valeur (`health < 40` -> "warning"). Un correctif qui rendrait bien
  l'insight mais avec `severity="info"` resterait faux.
- `test_cle_absente_vaut_toujours_cent` : le CONTRE-TEST. Il interdit le
  correctif trop large qui traiterait « pas de mesure » comme « sante nulle » —
  c'est-a-dire qui alerterait sur toute bibliotheque dont le bibliothecaire n'a
  pas tourne.
- `test_sante_intermediaire_inchangee` : verrouille l'absence d'effet de bord
  sur le chemin qui marchait deja.

Le libelle est asserte sur la chaine EXACTE `0/100` : « Sante bibliotheque :
100/100 » contient « 100 », donc un `assertIn("100", label)` passerait sur le
comportement fautif.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock

from cinesort.ui.api import dashboard_support


def _store_neutre() -> MagicMock:
    """Store dont AUCUNE autre section d'insight ne produit quoi que ce soit.

    Chaque section est neutralisee separement pour que la liste rendue ne
    contienne que ce que la section 3c a decide — sans quoi une assertion sur
    « il y a un insight » serait satisfaite par un voisin.
    """
    store = MagicMock()
    store.run.list_runs.return_value = []
    store.perceptual.list_perceptual_reports.return_value = []
    store.perceptual.count_v2_warnings_flag.return_value = 0
    store.perceptual.count_v2_tier_since.return_value = 0
    return store


def _insights(librarian_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return dashboard_support._compute_active_insights(
        MagicMock(),
        _store_neutre(),
        ["r1"],
        {},
        librarian_data,
        latest_scan_rid="r1",
    )


def _health_low(insights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [i for i in insights if i.get("type") == "health_low"]


class SanteZeroEstUneSanteTests(unittest.TestCase):
    def test_sante_zero_declenche_l_insight(self) -> None:
        trouves = _health_low(_insights({"health_score": 0}))
        self.assertEqual(
            len(trouves),
            1,
            "une sante de 0 doit produire l'insight health_low ; `or 100` la relevait a 100",
        )
        self.assertEqual(trouves[0]["count"], 0)
        self.assertEqual(trouves[0]["label"], "Sante bibliotheque : 0/100")

    def test_sante_zero_est_une_alerte_et_non_une_info(self) -> None:
        """La severite se derive de la VRAIE valeur (`health < 40`)."""
        trouves = _health_low(_insights({"health_score": 0}))
        self.assertEqual(trouves[0]["severity"], "warning")

    def test_cle_absente_vaut_toujours_cent(self) -> None:
        """Contre-test : pas de mesure n'est pas une sante nulle."""
        self.assertEqual(_health_low(_insights({})), [])
        self.assertEqual(_health_low(_insights({"health_score": None})), [])
        self.assertEqual(_health_low(_insights({"health_score": ""})), [])

    def test_sante_intermediaire_inchangee(self) -> None:
        """Le chemin qui marchait deja ne bouge pas, dans les deux sens du seuil."""
        trouves = _health_low(_insights({"health_score": 42}))
        self.assertEqual(len(trouves), 1)
        self.assertEqual(trouves[0]["severity"], "info")
        self.assertEqual(trouves[0]["label"], "Sante bibliotheque : 42/100")
        self.assertEqual(_health_low(_insights({"health_score": 60})), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
