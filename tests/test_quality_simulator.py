"""Tests backend pour G5 — simulateur de preset qualite."""

from __future__ import annotations

import tempfile
import unittest

from cinesort.domain.tiers_helpers import DEFAULT_TIER_THRESHOLDS
from cinesort.ui.api.quality_simulator_support import (
    _apply_weights,
    _count_tiers,
    _get_active_profile,
    _group_avg_delta,
    _load_reports_for_scope,
    _recompute_in_memory,
    _resolve_latest_run_id,
    _resolve_target_profile,
    _slugify,
    _tier_for,
    clear_cache,
    run_simulation,
)

_DEFAULT_ACTIVE_PROFILE = {
    "id": "active",
    "label": "Actuel",
    "weights": {"video": 60, "audio": 30, "extras": 10},
    "tiers": {"premium": 85, "bon": 68, "moyen": 54},
}


class _FakeQualityRepo:
    def __init__(self, reports):
        self._reports = reports

    def list_quality_reports(self, run_id=None):
        return [dict(rep) for rep in self._reports]


class _FakeRunRepo:
    def __init__(self, runs):
        self._runs = runs

    def list_runs(self, limit=20):
        return [dict(run) for run in self._runs][: int(limit)]


class _FakeStore:
    """Store minimal, SANS `__getattr__` magique : tout acces a un attribut
    non declare leve AttributeError, comme le vrai SQLiteStore."""

    def __init__(self, reports, runs):
        self.quality = _FakeQualityRepo(reports)
        self.run = _FakeRunRepo(runs)
        self.writes = []

    def save_quality_profile(self, *args, **kwargs):
        self.writes.append(("save_quality_profile", args, kwargs))


class _FakeSettingsFacade:
    def __init__(self, state_dir):
        self._state_dir = state_dir

    def get_settings(self):
        return {"state_dir": self._state_dir}


class _FakeApi:
    """Surface REELLE de CineSortApi vue par le simulateur de preset.

    Aucun attribut `_store` : c'est le point du correctif #441/#729. Le
    module doit obtenir le store par la seule voie de production,
    `settings.get_settings()` -> `_get_or_create_infra(state_dir)`.
    """

    def __init__(self, reports, active_profile=None, runs=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = _FakeSettingsFacade(self._tmp.name)
        self.store = _FakeStore(reports, runs if runs is not None else [{"run_id": "RUN123"}])
        self.infra_calls = []
        self.profile_writes = []
        self._profile = active_profile or _DEFAULT_ACTIVE_PROFILE

    def _get_or_create_infra(self, state_dir):
        self.infra_calls.append(state_dir)
        return (self.store, None)

    def _active_quality_profile_payload(self):
        return {"profile_json": self._profile}

    def _save_active_quality_profile(self, *args, **kwargs):
        self.profile_writes.append((args, kwargs))


class ApplyWeightsTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_apply_weights(80, 60, 40, {"video": 60, "audio": 30, "extras": 10}), 70)

    def test_all_zero_weights_fallback(self):
        """Poids 0/0/0 -> divise par 1 mais numerator=0 donc score=0 (comportement attendu)."""
        self.assertEqual(_apply_weights(80, 60, 40, {"video": 0, "audio": 0, "extras": 0}), 0)

    def test_clamp_upper(self):
        self.assertEqual(_apply_weights(120, 120, 120, {"video": 1, "audio": 0, "extras": 0}), 100)

    def test_clamp_lower(self):
        self.assertEqual(_apply_weights(-10, -10, -10, {"video": 1, "audio": 1, "extras": 1}), 0)


class TierForTests(unittest.TestCase):
    def test_tiers_modern(self):
        # U1 audit : 5 tiers Platinum/Gold/Silver/Bronze/Reject (migration 011)
        t = {"platinum": 85, "gold": 68, "silver": 54, "bronze": 30}
        self.assertEqual(_tier_for(95, t), "Platinum")
        self.assertEqual(_tier_for(85, t), "Platinum")
        self.assertEqual(_tier_for(70, t), "Gold")
        self.assertEqual(_tier_for(55, t), "Silver")
        self.assertEqual(_tier_for(40, t), "Bronze")
        self.assertEqual(_tier_for(10, t), "Reject")

    def test_tiers_legacy_keys_still_read(self):
        # Retro-compat : les profils sauvegardes avec les anciennes clefs doivent
        # continuer a produire les nouveaux noms.
        t = {"premium": 85, "bon": 68, "moyen": 54}
        self.assertEqual(_tier_for(95, t), "Platinum")
        self.assertEqual(_tier_for(70, t), "Gold")
        self.assertEqual(_tier_for(55, t), "Silver")
        self.assertEqual(_tier_for(40, t), "Bronze")
        self.assertEqual(_tier_for(10, t), "Reject")

    def test_seuil_bronze_a_zero_est_une_valeur_metier(self):
        """ROUGE avant le correctif : `int(tiers.get("bronze") or 30)` rendait 30.

        `normalize_tiers` clamp sur [0, 100] et `validate_quality_profile`
        n'exige que `platinum >= gold >= silver >= bronze` : un bronze a 0 est
        donc un profil VALIDE, et il dit « aucun film n'est Reject ». Le
        simulateur le relisait comme 30 et annoncait « Reject » a l'utilisateur
        pour des films que le scoring reel classe Bronze.
        """
        t = {"platinum": 70, "gold": 66, "silver": 55, "bronze": 0}
        self.assertEqual(_tier_for(10, t), "Bronze")
        self.assertEqual(_tier_for(0, t), "Bronze")

    def test_seuils_adjacents_egaux_ne_declenchent_pas_de_repli(self):
        """ROUGE avant le correctif : rendait "Gold" (repli sur 85/68/54/30).

        L'ancien controle exigeait un ordre STRICTEMENT decroissant
        (`p > g > s > br`) la ou la production admet l'egalite (`>=`, cf.
        `validate_quality_profile`). Un profil 70/70/55/40 est donc valide et
        classe 70 en Platinum ; le simulateur basculait EN SILENCE sur une
        grille qui n'etait pas celle de l'utilisateur (log warning, payload muet).
        """
        t = {"platinum": 70, "gold": 70, "silver": 55, "bronze": 40}
        self.assertEqual(_tier_for(70, t), "Platinum")

    def test_tiers_absents_retombent_sur_la_grille_canonique(self):
        """ROUGE avant le correctif : rendait "Gold" (grille pre-v1.5.5 85/68/54/30).

        Le defaut canonique est 70/66/55/40 (`DEFAULT_TIER_THRESHOLDS`, egal a
        `default_quality_profile()["tiers"]`). C'est exactement le cas « un film
        a 72 » deja documente par `test_vue_statistiques` et deja corrige cote
        frontend par `test_audit_ultra_wave4b_frontend_constants`.
        """
        self.assertEqual(DEFAULT_TIER_THRESHOLDS["platinum"], 70)
        self.assertEqual(_tier_for(72, {}), "Platinum")
        self.assertEqual(_tier_for(35, {}), "Reject")

    def test_profil_actif_illisible_retombe_sur_la_grille_canonique(self):
        """ROUGE avant le correctif : rendait {premium: 85, bon: 68, moyen: 54}.

        Ce troisieme site etait le plus trompeur des trois : son dict est
        TRUTHY, donc le defaut de `_recompute_in_memory` ne le rattrapait pas.
        C'est bien cette grille-la qui servait de baseline des que la lecture du
        profil actif echouait.
        """

        class _ApiQuiEchoue:
            def _active_quality_profile_payload(self):
                raise OSError("profil illisible")

        tiers = _get_active_profile(_ApiQuiEchoue())["tiers"]
        self.assertEqual(tiers, dict(DEFAULT_TIER_THRESHOLDS))
        self.assertNotIn("premium", tiers)


class CountTiersTests(unittest.TestCase):
    def test_count(self):
        got = _count_tiers(["Platinum", "Gold", "Gold", "Silver", "Reject", "Platinum"])
        self.assertEqual(got["Platinum"], 2)
        self.assertEqual(got["Gold"], 2)
        self.assertEqual(got["Silver"], 1)
        self.assertEqual(got["Reject"], 1)
        self.assertEqual(got["Bronze"], 0)


class GroupAvgDeltaTests(unittest.TestCase):
    def test_group(self):
        rows = [
            {"codec": "hevc", "delta": 5},
            {"codec": "hevc", "delta": 15},
            {"codec": "h264", "delta": -2},
        ]
        out = _group_avg_delta(rows, "codec")
        self.assertEqual(out["hevc"]["avg_delta"], 10.0)
        self.assertEqual(out["hevc"]["count"], 2)
        self.assertEqual(out["h264"]["avg_delta"], -2.0)


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_slugify("Mon Preset Tres Cool"), "mon_preset_tres_cool")
        self.assertEqual(_slugify("Test!@#$123"), "test_123")
        self.assertEqual(_slugify(""), "custom")


class ResolveTargetProfileTests(unittest.TestCase):
    def test_known_preset(self):
        prof = _resolve_target_profile("equilibre", None)
        self.assertIsNotNone(prof)
        self.assertIn("weights", prof)
        self.assertIn("tiers", prof)

    def test_unknown_preset(self):
        self.assertIsNone(_resolve_target_profile("no_such_preset_id", None))

    def test_overrides_merge(self):
        prof = _resolve_target_profile("equilibre", {"weights": {"video": 80, "audio": 15, "extras": 5}})
        self.assertEqual(prof["weights"]["video"], 80)
        self.assertEqual(prof["weights"]["audio"], 15)


class RecomputeInMemoryTests(unittest.TestCase):
    def test_simple(self):
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 80, "audio": 60, "extras": 40},
                    "detected": {"video_codec": "hevc", "resolution": "1080p", "title": "Dune"},
                },
            },
            {
                "row_id": "2",
                "score": 50,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 40, "audio": 60, "extras": 60},
                    "detected": {"video_codec": "h264", "resolution": "720p", "title": "Old"},
                },
            },
        ]
        baseline = {
            "weights": {"video": 60, "audio": 30, "extras": 10},
            "tiers": {"premium": 85, "bon": 68, "moyen": 54},
        }
        target = {
            "weights": {"video": 80, "audio": 15, "extras": 5},
            "tiers": {"premium": 85, "bon": 68, "moyen": 54},
            "label": "Video-first",
        }

        out = _recompute_in_memory(reports, baseline, target)
        self.assertEqual(len(out), 2)
        self.assertIn("score_after", out[0])
        self.assertIn("delta", out[0])
        # video dominant => row 1 (video=80) score_after > score_before
        self.assertGreater(out[0]["score_after"], 70)

    def test_legacy_tier_before_normalized(self):
        """Audit 2026-07-09 : un rapport stocke avec un ancien nom FR (Premium/Bon/
        Moyen/...) doit voir son tier_before normalise vers le nom canonique
        anglais, sinon la distribution before/after et la matrice de shift
        produisent des cles fantomes ("Premium>Platinum")."""
        reports = [
            {
                "row_id": "1",
                "score": 90,
                "tier": "Premium",
                "metrics": {"subscores": {"video": 90, "audio": 90, "extras": 90}, "detected": {}},
            },
            {
                "row_id": "2",
                "score": 60,
                "tier": "Moyen",
                "metrics": {"subscores": {"video": 60, "audio": 60, "extras": 60}, "detected": {}},
            },
        ]
        baseline = {
            "weights": {"video": 60, "audio": 30, "extras": 10},
            "tiers": {"premium": 85, "bon": 68, "moyen": 54},
        }
        target = dict(baseline)
        out = _recompute_in_memory(reports, baseline, target)
        tiers_before = {r["tier_before"] for r in out}
        self.assertNotIn("Premium", tiers_before)
        self.assertNotIn("Moyen", tiers_before)
        self.assertIn("Platinum", tiers_before)
        self.assertIn("Silver", tiers_before)


class RunSimulationIntegrationTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def _make_api(self, reports, active_profile=None, runs=None):
        # AUDIT 2026-08-03 (#441 / #729) : l'ancien fake faisait
        # `api._store = MagicMock()`. C'est CE mock qui a maintenu le
        # simulateur vert pendant des mois alors qu'il etait mort en prod :
        # CineSortApi n'a aucun attribut `_store`, mais un MagicMock CREE
        # l'attribut absent. Le fake ci-dessous reproduit la surface REELLE
        # (facade `settings` + `_get_or_create_infra`) et n'expose
        # deliberement PAS `_store` — cf test_api_has_no_store_attribute.
        return _FakeApi(reports, active_profile=active_profile, runs=runs)

    def test_empty_scope(self):
        api = self._make_api([])
        res = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertFalse(res.get("ok"))

    def test_api_has_no_store_attribute(self):
        """Garde-fou : le fake ne doit JAMAIS ressusciter `api._store`.

        Si quelqu'un le reintroduit dans le fake, les tests ci-dessous
        redeviendraient verts sur un module casse (c'est exactement ce qui
        s'est produit : issues #441/#729, fermees a tort comme doublons).
        """
        api = self._make_api([])
        self.assertFalse(hasattr(api, "_store"))
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertNotIn("_store", dir(CineSortApi))

    def test_reports_loaded_via_get_or_create_infra(self):
        """#441/#729 : le store s'obtient par la facade settings + _get_or_create_infra.

        ROUGE avec `getattr(api, "_store", None)` : store=None -> [] ->
        run_simulation repond « Aucun rapport qualite disponible ».
        """
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 70, "audio": 70, "extras": 50},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
        ]
        api = self._make_api(reports)
        got = _load_reports_for_scope(api, "RUN123", "run")
        self.assertEqual([r["row_id"] for r in got], ["1"])
        # Le store a bien ete obtenu via _get_or_create_infra(state_dir).
        self.assertEqual(len(api.infra_calls), 1)
        self.assertEqual(str(api.infra_calls[0]), api.settings.get_settings()["state_dir"])

    def test_latest_run_id_uses_shared_resolver(self):
        """#441/#729 : `latest` doit passer par library_support._resolve_run_id.

        Le run utilitaire de bulk re-scan (config_json.rescan_run_id) doit
        etre saute au profit du run qui porte reellement le plan — c'est le
        comportement que `store.run.get_latest_run()` n'avait pas.
        """
        api = self._make_api(
            [],
            runs=[
                {"run_id": "RESCAN1", "config_json": '{"rescan_run_id": "RUN123"}'},
                {"run_id": "RUN123"},
            ],
        )
        self.assertEqual(_resolve_latest_run_id(api), "RUN123")

    def test_scope_run_resolves_latest_when_run_id_is_latest(self):
        """Bout en bout : scope="run" + run_id="latest" doit trouver des rapports."""
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 70, "audio": 70, "extras": 50},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
        ]
        api = self._make_api(reports)
        res = run_simulation(api, run_id="latest", preset_id="equilibre", scope="run")
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res["films_count"], 1)

    def test_full_simulation(self):
        reports = [
            {
                "row_id": str(i),
                "score": 50 + i * 3,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 50 + i * 3, "audio": 60, "extras": 40},
                    "detected": {"video_codec": "hevc", "resolution": "1080p", "title": f"Film {i}"},
                },
            }
            for i in range(10)
        ]
        api = self._make_api(reports)
        res = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res["films_count"], 10)
        self.assertIn("before", res)
        self.assertIn("after", res)
        self.assertIn("delta", res)
        self.assertIn("top_winners", res)
        self.assertIn("top_losers", res)
        self.assertIn("distribution_shift", res)
        self.assertIn("by_codec", res)
        self.assertIn("by_resolution", res)

    def test_cache_hit(self):
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 70, "audio": 70, "extras": 50},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
        ]
        api = self._make_api(reports)
        r1 = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertFalse(r1.get("cache_hit"))
        r2 = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertTrue(r2.get("cache_hit"))

    def test_is_dry_run(self):
        """Verifie qu'aucune methode de store d'ecriture n'est appelee."""
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 70, "audio": 70, "extras": 50},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
        ]
        api = self._make_api(reports)
        run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertEqual(api.store.writes, [])
        self.assertEqual(api.profile_writes, [])

    def test_concurrent_simulations_thread_safe(self):
        """Audit 2026-05-13 : _SIM_CACHE est mute par plusieurs threads
        REST (ThreadingHTTPServer). Sans lock, l'eviction FIFO
        `_SIM_CACHE.pop(next(iter(...)))` peut crasher avec
        RuntimeError si un autre thread mute le dict pendant l'iteration.
        Ce test simule N threads qui appellent run_simulation +
        clear_cache en parallele et exige zero exception."""
        import threading

        reports = [
            {
                "row_id": str(i),
                "score": 60 + i,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 60 + i, "audio": 60, "extras": 60},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
            for i in range(5)
        ]
        api = self._make_api(reports)
        errors: list[BaseException] = []
        clear_cache()

        def worker(idx: int) -> None:
            try:
                # Vary run_id pour forcer beaucoup de cache misses + evictions.
                run_simulation(api, run_id=f"RUN{idx}", preset_id="equilibre", scope="run")
                if idx % 7 == 0:
                    clear_cache()
            except BaseException as exc:  # noqa: BLE001 - on capture tout
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        clear_cache()
        self.assertEqual(errors, [], f"thread errors: {errors}")

    def test_distribution_shift_sums_to_total(self):
        reports = [
            {
                "row_id": str(i),
                "score": 60,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 60, "audio": 60, "extras": 60},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
            for i in range(5)
        ]
        api = self._make_api(reports)
        res = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        total_in_shift = sum(res["distribution_shift"].values())
        self.assertEqual(total_in_shift, 5)


if __name__ == "__main__":
    unittest.main()
