"""La fenetre de `get_history` doit demarrer a MINUIT, pas a l'heure courante.

LE DEFAUT. `since = now - period * 86400.0` fait demarrer la fenetre a l'heure
courante. Or les points sont regroupes par DATE LOCALE : le bucket le plus
ancien ne couvre qu'une fraction de journee, tout en formant un point a part
entiere.

Deux consequences, la seconde etant un biais permanent :

1. la premiere barre du graphique est un moignon, sans que rien ne le dise ;
2. ce point tombe toujours du cote `older` de la coupe en deux moities, et
   `delta_films` est une SOMME -- sur une bibliotheque a activite constante,
   l'indicateur affiche une hausse qui ne mesure que la troncature.

MESURE, 31 jours d'activite strictement constante (10 films/jour), la coupe
symetrique de #1008 etant deja appliquee :

    jour ancien COMPLET (10 films)  -> delta_films = +0
    jour ancien PARTIEL (4 films)   -> delta_films = +6
    jour ancien PARTIEL (1 film)    -> delta_films = +9

L'asymetrie corrigee par #1008 valait +10. Le residu etait donc du meme ordre
et de meme signe : la tendance 📈 permanente retrecissait sans disparaitre.

POURQUOI CES TESTS ASSERTENT SUR L'ARGUMENT, ET NON SUR `delta_films`.
`_build_mock_api` cable `get_global_score_v2_trend.return_value` : le double
IGNORE `since_ts` et rend toujours la meme liste. Un test qui verifierait
`delta_films` sur ce double mesurerait donc la mise en forme des points, jamais
le calcul de la fenetre -- il resterait vert avec le defaut intact. La seule
grandeur qui porte le correctif est la BORNE transmise au repository.
"""

from __future__ import annotations

import time
import unittest

from cinesort.ui.api.quality_audit_support import _minuit_local, get_history
from tests.test_phase4_qualite_endpoints import _build_mock_api


def _since_transmis(period_days: int) -> float:
    """Borne basse effectivement passee au repository perceptual."""
    api, _ = _build_mock_api(perceptual_trend=[])
    get_history(api, period_days=period_days)
    appel = api._get_or_create_infra.return_value[0].perceptual.get_global_score_v2_trend.call_args
    return float(appel.kwargs["since_ts"])


class LaFenetreDemarreAMinuitTests(unittest.TestCase):
    def test_la_borne_transmise_est_a_minuit_pile(self) -> None:
        borne = time.localtime(_since_transmis(30))

        self.assertEqual(
            (borne.tm_hour, borne.tm_min, borne.tm_sec),
            (0, 0, 0),
            "la fenetre demarre a l'heure courante : le jour le plus ancien est TRONQUE, "
            "et son point compte quand meme dans la moitie `older`.",
        )

    def test_elle_ne_decale_pas_le_jour(self) -> None:
        """Minuit du BON jour : reculer d'un jour de trop fausserait la periode."""
        attendu = time.localtime(time.time() - 30 * 86400.0)
        obtenu = time.localtime(_since_transmis(30))

        self.assertEqual(
            (obtenu.tm_year, obtenu.tm_mon, obtenu.tm_mday),
            (attendu.tm_year, attendu.tm_mon, attendu.tm_mday),
        )

    def test_toutes_les_periodes_de_l_UI_sont_couvertes(self) -> None:
        """7 / 30 / 90 / 365 : les quatre boutons de la page Qualite."""
        for periode in (7, 30, 90, 365):
            with self.subTest(periode=periode):
                borne = time.localtime(_since_transmis(periode))
                self.assertEqual((borne.tm_hour, borne.tm_min, borne.tm_sec), (0, 0, 0))

    def test_la_borne_est_ANTERIEURE_au_calcul_naif(self) -> None:
        """Contre-epreuve d'efficacite du test lui-meme.

        Si l'heure d'execution etait justement minuit, les deux calculs
        coincideraient et les assertions ci-dessus passeraient sans rien
        eprouver. On exige donc un ecart strict -- sauf dans la seule minute ou
        la coincidence est legitime, cas alors declare.
        """
        maintenant = time.time()
        naif = maintenant - 30 * 86400.0
        borne = _since_transmis(30)

        heure = time.localtime(maintenant)
        if (heure.tm_hour, heure.tm_min) == (0, 0):
            self.skipTest("execute a minuit pile : les deux calculs coincident legitimement")

        self.assertLess(borne, naif, "la borne devrait reculer jusqu'a minuit du meme jour")
        self.assertLess(naif - borne, 86400.0, "elle ne doit jamais reculer de plus d'une journee")


class LeHelperEstCorrectEnLuiMemeTests(unittest.TestCase):
    def test_minuit_local_est_idempotent(self) -> None:
        """Minuit d'un minuit reste ce minuit -- sinon la borne deriverait."""
        une_fois = _minuit_local(time.time())

        self.assertEqual(_minuit_local(une_fois), une_fois)

    def test_deux_instants_du_MEME_jour_donnent_le_meme_minuit(self) -> None:
        jour = time.localtime()
        matin = time.mktime((jour.tm_year, jour.tm_mon, jour.tm_mday, 9, 15, 0, 0, 0, -1))
        soir = time.mktime((jour.tm_year, jour.tm_mon, jour.tm_mday, 22, 45, 0, 0, 0, -1))

        self.assertEqual(_minuit_local(matin), _minuit_local(soir))

    def test_il_ne_devance_JAMAIS_son_argument(self) -> None:
        """Minuit est toujours <= l'instant donne : une borne future viderait la fenetre."""
        for decalage_h in (0, 1, 6, 13, 23):
            with self.subTest(heure=decalage_h):
                jour = time.localtime()
                ts = time.mktime((jour.tm_year, jour.tm_mon, jour.tm_mday, decalage_h, 30, 0, 0, 0, -1))
                self.assertLessEqual(_minuit_local(ts), ts)


if __name__ == "__main__":
    unittest.main()
