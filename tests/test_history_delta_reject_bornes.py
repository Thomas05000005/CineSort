"""`delta_reject` doit employer les MEMES bornes que `delta_score` et `delta_films`.

LE DEFAUT. Les deux premiers deltas comparent deux fenetres de journees
COMPLETES. `delta_reject`, lui, interrogeait le depot avec :

    reject_recent = count_v2_tier_since(since_ts=now - (period // 2) * 86400)
    reject_older  = count_v2_tier_since(since_ts=since) - reject_recent

`since` etant minuit, la fenetre ancienne couvre `period/2` jours PLUS les
heures ecoulees depuis minuit, tandis que la recente en couvre exactement
`period/2`. Sur une activite constante, l'ancienne compte donc davantage et
l'indicateur affiche une baisse qui ne mesure que l'heure qu'il est.

MESURE, depot factice a debit STRICTEMENT constant, 10 rejects/jour :

    bornes demandees (jours avant maintenant) : [15.0, 30.34]
    delta_reject = -3          <- attendu 0

    apres correctif :
    bornes demandees : [0.341, 15.341, 30.341]   <- trois minuits, 15 j d'ecart
    delta_reject = +0

Signale par CodeRabbit sur la PR #1018.

POURQUOI UN FAUX DEPOT PLUTOT QUE `_build_mock_api`. Ce dernier cable
`count_v2_tier_since.return_value` : le double rend la MEME valeur quelle que
soit la borne, donc il ne peut rien dire d'un defaut qui porte precisement sur
les bornes. Un test bati dessus resterait vert avec le defaut intact — il
mesurerait la mise en forme du payload, pas le calcul. Le faux depot ci-dessous
respecte `since_ts` ; c'est la seule facon d'observer la grandeur en cause.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from cinesort.ui.api import quality_audit_support as Q

#: Debit constant de la bibliotheque simulee.
_REJECTS_PAR_JOUR = 10.0


def _api_avec_depot_a_debit_constant(maintenant: float):
    """Depot factice ou les Reject arrivent a debit rigoureusement constant.

    `count_v2_tier_since(since_ts=X)` rend le nombre de Reject dans `[X, now]`,
    soit exactement `(now - X) * debit`. Toute asymetrie de bornes se lit alors
    directement dans `delta_reject`.
    """
    appels: list[float] = []

    def _compter(*, tier: str, since_ts: float) -> int:
        appels.append(since_ts)
        return int(max(0.0, maintenant - since_ts) / 86400.0 * _REJECTS_PAR_JOUR)

    store = mock.MagicMock()
    store.perceptual.count_v2_tier_since.side_effect = _compter
    store.perceptual.get_global_score_v2_trend.return_value = []

    api = mock.MagicMock()
    api.settings.get_settings.return_value = {"state_dir": "X"}
    api._get_or_create_infra.return_value = (store, mock.MagicMock())
    return api, appels


class UneActiviteCONSTANTENAffichePasDeTendanceRejectTests(unittest.TestCase):
    def test_delta_reject_est_nul_a_debit_constant(self) -> None:
        maintenant = time.time()
        api, _ = _api_avec_depot_a_debit_constant(maintenant)

        with mock.patch.object(Q.time, "time", lambda: maintenant):
            res = Q.get_history(api, period_days=30)

        self.assertEqual(
            int(res["delta_reject"]),
            0,
            "activite Reject constante mais tendance non nulle : les deux fenetres comparees n'ont pas la meme duree.",
        )

    def test_pour_toutes_les_periodes_de_l_UI(self) -> None:
        for periode in (7, 30, 90, 365):
            with self.subTest(periode=periode):
                maintenant = time.time()
                api, _ = _api_avec_depot_a_debit_constant(maintenant)

                with mock.patch.object(Q.time, "time", lambda: maintenant):
                    res = Q.get_history(api, period_days=periode)

                self.assertEqual(int(res["delta_reject"]), 0)


class LesBornesTRANSMISESAuDepotSontSymetriquesTests(unittest.TestCase):
    """L'assertion qui porte le correctif : ce sont les BORNES qui comptent."""

    def test_trois_bornes_a_minuit_local(self) -> None:
        maintenant = time.time()
        api, appels = _api_avec_depot_a_debit_constant(maintenant)

        with mock.patch.object(Q.time, "time", lambda: maintenant):
            Q.get_history(api, period_days=30)

        self.assertEqual(len(appels), 3, f"attendu 3 bornes, obtenu {len(appels)} : {appels}")
        for borne in appels:
            heure = time.localtime(borne)
            self.assertEqual(
                (heure.tm_hour, heure.tm_min, heure.tm_sec),
                (0, 0, 0),
                "une borne ne tombe pas a minuit : la fenetre demarre a l'heure courante",
            )

    def test_les_deux_tranches_ont_la_meme_duree(self) -> None:
        maintenant = time.time()
        api, appels = _api_avec_depot_a_debit_constant(maintenant)

        with mock.patch.object(Q.time, "time", lambda: maintenant):
            Q.get_history(api, period_days=30)

        bornes = sorted(appels)
        ancienne = bornes[1] - bornes[0]
        recente = bornes[2] - bornes[1]
        self.assertAlmostEqual(
            ancienne,
            recente,
            delta=3600.0,  # tolerance : un changement d'heure d'ete decale d'une heure
            msg=f"tranches inegales : ancienne={ancienne / 86400:.3f} j, recente={recente / 86400:.3f} j",
        )

    def test_aujourd_hui_est_exclu_des_deux(self) -> None:
        """La borne haute de la fenetre recente est minuit, pas `now`."""
        maintenant = time.time()
        api, appels = _api_avec_depot_a_debit_constant(maintenant)

        with mock.patch.object(Q.time, "time", lambda: maintenant):
            Q.get_history(api, period_days=30)

        self.assertEqual(max(appels), Q._minuit_local(maintenant))


if __name__ == "__main__":
    unittest.main()
