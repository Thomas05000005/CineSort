"""Tests Vague G (v1.5.3) - durcissement de 11 endpoints additionnels.

Verifie que chaque endpoint vise par la Vague G est correctement durci par un
wrap `try / except Exception` global qui retourne le contrat standardise
`{ok: False, error: "<endpoint>_failed", message: ..., user_message: ...}`
au lieu de laisser remonter une exception non geree (qui se traduirait par
un HTTP 500 cote UI).

Chaque test :
1. Patche l'implementation interne (`_<endpoint>_impl`) ou la dependance
   directe pour qu'elle leve une exception non listee dans le `except`
   interne.
2. Appelle la fonction publique de l'endpoint.
3. Verifie que la reponse est un dict avec `ok=False`, un `error` precis,
   un `user_message` non vide, et un `message` qui contient le texte
   technique du raise initial (pour le debug serveur).

Fix audit 2026-05-25 (v1.5.3) Vague G.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _make_api() -> MagicMock:
    """Mock API minimal commun a tous les tests Vague G."""
    api = MagicMock()
    api._is_valid_run_id.return_value = True
    return api


class GetProbeHardeningTests(unittest.TestCase):
    """Vague G #1 : probe_support.get_probe."""

    def test_get_probe_handles_exception(self) -> None:
        from cinesort.ui.api import probe_support

        api = _make_api()
        api._find_run_row.side_effect = RuntimeError("probe boom")

        # detect_probe_tools_fn obligatoire en kwarg-only mais jamais appele
        # ici car la raise survient avant.
        res = probe_support.get_probe(
            api,
            "run_xyz",
            "row_1",
            detect_probe_tools_fn=lambda *a, **kw: {},
        )

        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "probe_unavailable")
        self.assertIn("user_message", res)
        self.assertTrue(res["user_message"])
        self.assertIn("probe boom", res.get("message", ""))


class GetFilmsByTierHardeningTests(unittest.TestCase):
    """Vague G #2 : quality_audit_support.get_films_by_tier."""

    def test_get_films_by_tier_handles_exception(self) -> None:
        from cinesort.ui.api import quality_audit_support

        api = _make_api()

        with patch.object(
            quality_audit_support,
            "_get_films_by_tier_impl",
            side_effect=RuntimeError("tier boom"),
        ):
            res = quality_audit_support.get_films_by_tier(api, "gold", 8)

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "films_by_tier_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("tier boom", res.get("message", ""))


class RecomputeAllScoresHardeningTests(unittest.TestCase):
    """Vague G #3 : quality_audit_support.recompute_all_scores."""

    def test_recompute_all_scores_handles_exception(self) -> None:
        from cinesort.ui.api import quality_audit_support

        api = _make_api()

        with patch.object(
            quality_audit_support,
            "_recompute_all_scores_impl",
            side_effect=RuntimeError("recompute boom"),
        ):
            res = quality_audit_support.recompute_all_scores(api)

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "recompute_scores_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("recompute boom", res.get("message", ""))


class GetLibraryTimelineHardeningTests(unittest.TestCase):
    """Vague G #4 : library_timeline_support.get_library_timeline."""

    def test_get_library_timeline_handles_exception(self) -> None:
        from cinesort.ui.api import library_timeline_support

        api = _make_api()

        with patch.object(
            library_timeline_support,
            "_get_library_timeline_impl",
            side_effect=RuntimeError("timeline boom"),
        ):
            res = library_timeline_support.get_library_timeline(api, 12, None)

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "timeline_load_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("timeline boom", res.get("message", ""))


class GetLibraryPodiumsHardeningTests(unittest.TestCase):
    """Vague G #5 : library_podiums_support.get_library_podiums."""

    def test_get_library_podiums_handles_exception(self) -> None:
        from cinesort.ui.api import library_podiums_support

        api = _make_api()

        with patch.object(
            library_podiums_support,
            "_get_library_podiums_impl",
            side_effect=RuntimeError("podiums boom"),
        ):
            res = library_podiums_support.get_library_podiums(api, run_id=None, limit=10)

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "podiums_load_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("podiums boom", res.get("message", ""))


class GetFilmsByDecadeHardeningTests(unittest.TestCase):
    """Vague G #6 : library_audit_support.get_films_by_decade."""

    def test_get_films_by_decade_handles_exception(self) -> None:
        from cinesort.ui.api import library_audit_support

        api = _make_api()

        with patch.object(
            library_audit_support,
            "_get_films_by_decade_impl",
            side_effect=RuntimeError("decade boom"),
        ):
            res = library_audit_support.get_films_by_decade(api, filters=None)

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "films_by_decade_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("decade boom", res.get("message", ""))


class GetDiagnosticHardeningTests(unittest.TestCase):
    """Vague G #7 : runtime_support.get_diagnostic."""

    def test_get_diagnostic_handles_exception(self) -> None:
        from cinesort.ui.api import runtime_support

        api = _make_api()

        with patch.object(
            runtime_support,
            "_get_diagnostic_impl",
            side_effect=RuntimeError("diag boom"),
        ):
            res = runtime_support.get_diagnostic(api)

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "diagnostic_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("diag boom", res.get("message", ""))


class ListApplyHistoryHardeningTests(unittest.TestCase):
    """Vague G #8 : apply_support.list_apply_history."""

    def test_list_apply_history_handles_exception(self) -> None:
        from cinesort.ui.api import apply_support

        api = _make_api()

        with patch.object(
            apply_support,
            "_list_apply_history_impl",
            side_effect=RuntimeError("history boom"),
        ):
            res = apply_support.list_apply_history(api, "run_xyz")

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "apply_history_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("history boom", res.get("message", ""))


class StartPlanHardeningTests(unittest.TestCase):
    """Vague G #9 : run_flow_support.start_plan."""

    def test_start_plan_handles_exception(self) -> None:
        from cinesort.ui.api import run_flow_support

        api = _make_api()

        with patch.object(
            run_flow_support,
            "_start_plan_impl",
            side_effect=RuntimeError("start_plan boom"),
        ):
            res = run_flow_support.start_plan(api, {}, run_state_cls=MagicMock())

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "start_plan_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("start_plan boom", res.get("message", ""))


class PauseRunHardeningTests(unittest.TestCase):
    """Vague G #10 : run_control_support.pause_run."""

    def test_pause_run_handles_exception(self) -> None:
        from cinesort.ui.api import run_control_support

        api = _make_api()

        # Pause utilise _pause_or_save (helper interne du module). On le mocke
        # pour lever une RuntimeError "non geree" par les except internes.
        with patch.object(
            run_control_support,
            "_pause_or_save",
            side_effect=RuntimeError("pause boom"),
        ):
            res = run_control_support.pause_run(api, "run_xyz")

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "pause_run_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("pause boom", res.get("message", ""))


class GetPlanHardeningTests(unittest.TestCase):
    """Vague G #11 : history_support.get_plan."""

    def test_get_plan_handles_exception(self) -> None:
        from cinesort.ui.api import history_support

        api = _make_api()

        with patch.object(
            history_support,
            "_get_plan_impl",
            side_effect=RuntimeError("plan boom"),
        ):
            res = history_support.get_plan(api, "run_xyz", normalize_user_path=lambda *a, **kw: "")

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "plan_load_failed")
        self.assertTrue(res.get("user_message"))
        self.assertIn("plan boom", res.get("message", ""))


if __name__ == "__main__":
    unittest.main()
