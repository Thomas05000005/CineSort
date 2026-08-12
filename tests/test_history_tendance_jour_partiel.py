"""Une activite CONSTANTE doit afficher une tendance NULLE, quelle que soit l'heure.

`get_history` compare deux moities de la fenetre, et `delta_films` est une
SOMME. Tout seau structurellement PARTIEL present dans une moitie et pas dans
l'autre devient donc une tendance qui ne mesure que la troncature.

Il y a DEUX seaux partiels, et il a fallu deux passes pour les voir tous les
deux :

  - le plus ancien : la fenetre demarrait a l'heure courante. Traite en amont
    par `_minuit_local` ;
  - AUJOURD'HUI : `until_ts=now`, donc le seau du jour ne contient que ce qui a
    ete classe depuis minuit. C'est celui que ce fichier verrouille.

MESURE, bibliotheque a activite strictement constante (10 films/jour), `t` =
films deja classes aujourd'hui. Une tendance honnete rend 0 pour tout `t` :

    coupe                  t=0    t=2    t=5   t=10
    [:half] / [half:]      +0     +2     +5    +10    <- defaut d'origine
    [:half] / [-half:]    -10     -8     -5     +0    <- signe INVERSE
    [:half] / [half:-1]    +0     +0     +0     +0    <- retenue

POURQUOI CE FICHIER EXISTE. La coupe `[-half:]` egalise bien les longueurs, et
son test passait — mais uniquement parce que sa fixture donnait a AUJOURD'HUI un
compte de journee COMPLETE (`count: 10`), configuration impossible en
production et seule valeur de `t` ou cette coupe parait juste. Un test dont la
fixture choisit le seul cas favorable ne mesure pas la propriete qu'il annonce.

Ces tests balaient donc PLUSIEURS valeurs de `t`, dont `t=0` (aucun film classe
aujourd'hui) qui est le cas le plus courant en debut de journee.
"""

from __future__ import annotations

import time
import unittest

from cinesort.ui.api.quality_audit_support import get_history
from tests.test_phase4_qualite_endpoints import _build_mock_api

#: Rythme constant de la bibliotheque simulee.
_PAR_JOUR = 10


def _serie(films_aujourdhui: int, jours: int = 31) -> list:
    """Activite strictement constante, sauf AUJOURD'HUI qui est partiel."""
    maintenant = time.time()
    out = []
    for jour in range(jours):
        compte = films_aujourdhui if jour == 0 else _PAR_JOUR
        out.append(
            {
                "date": time.strftime("%Y-%m-%d", time.localtime(maintenant - jour * 86400.0)),
                "avg_score": 60.0,
                "count": compte,
            }
        )
    return out


def _delta(films_aujourdhui: int, periode: int = 30) -> int:
    api, _ = _build_mock_api(perceptual_trend=_serie(films_aujourdhui))
    return int(get_history(api, period_days=periode)["delta_films"])


class UneActiviteCONSTANTENAffichePasDeTendanceTests(unittest.TestCase):
    def test_quel_que_soit_le_remplissage_du_jour_en_cours(self) -> None:
        """LE test. Sans le correctif, la valeur suit `t` — dans un sens ou l'autre."""
        for t in (0, 1, 2, 5, 9, 10):
            with self.subTest(films_aujourdhui=t):
                self.assertEqual(
                    _delta(t),
                    0,
                    f"activite constante mais tendance non nulle avec {t} film(s) classes "
                    f"aujourd'hui : la coupe compare un seau PARTIEL a des journees pleines.",
                )

    def test_le_cas_le_plus_courant_est_couvert(self) -> None:
        """`t=0` — debut de journee, rien de classe encore. C'est l'etat de la
        bibliotheque a chaque premiere ouverture du jour, et celui ou l'ancienne
        coupe `[-half:]` se trompait le plus (-10)."""
        self.assertEqual(_delta(0), 0)

    def test_la_precondition_du_test_est_reelle(self) -> None:
        """Un vert vide ne prouve rien : verifier que la fenetre a bien 31 seaux,
        donc que la coupe est effectivement asymetrique sans correctif."""
        api, _ = _build_mock_api(perceptual_trend=_serie(3))

        res = get_history(api, period_days=30)

        self.assertEqual(len(res["points"]), 31, "le contrat de l'endpoint a change")

    def test_le_score_moyen_reste_insensible(self) -> None:
        """`delta_score` est une MOYENNE : il ne porte pas ce biais, et ne doit
        pas se mettre a en porter un."""
        for t in (0, 5, 10):
            with self.subTest(films_aujourdhui=t):
                api, _ = _build_mock_api(perceptual_trend=_serie(t))
                self.assertEqual(get_history(api, period_days=30)["delta_score"], 0.0)


class LesAutresPeriodesDeLUISontCouvertesTests(unittest.TestCase):
    """7 / 90 / 365 : les autres boutons de la page Qualite."""

    def test_sept_jours(self) -> None:
        api, _ = _build_mock_api(perceptual_trend=_serie(0, jours=8))
        self.assertEqual(int(get_history(api, period_days=7)["delta_films"]), 0)

    def test_quatre_vingt_dix_jours(self) -> None:
        api, _ = _build_mock_api(perceptual_trend=_serie(0, jours=91))
        self.assertEqual(int(get_history(api, period_days=90)["delta_films"]), 0)

    def test_une_annee(self) -> None:
        api, _ = _build_mock_api(perceptual_trend=_serie(0, jours=366))
        self.assertEqual(int(get_history(api, period_days=365)["delta_films"]), 0)


if __name__ == "__main__":
    unittest.main()
