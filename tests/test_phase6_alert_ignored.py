"""Phase 6 spec 06 §3.3 — Tests de la persistance des alertes ignorees.

Couvre :
- mark_alert_ignored insere en DB (idempotent via UNIQUE)
- get_film_full filtre les warning_flags par alertes ignorees
- get_film_full retourne row._ignored_alerts pour permettre le filtre cote front
- mark_alert_ignored retourne already_ignored=True au 2e appel (DOM/UX info)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cinesort.infra.db.sqlite_store import SQLiteStore


class MarkAlertIgnoredBackendTests(unittest.TestCase):
    """Verifie l'insertion et l'idempotence cote infra (FilmModalRepository)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.store = SQLiteStore(Path(self.tmpdir.name) / "test.db")

    def test_insert_first_time(self) -> None:
        res = self.store.film_modal.insert_ignored_alert("r1", "subtitle_missing_fr")
        self.assertTrue(res["ok"])
        self.assertTrue(res["inserted"])
        self.assertGreater(res["ignored_at"], 0)

    def test_insert_idempotent(self) -> None:
        self.store.film_modal.insert_ignored_alert("r1", "alert_x")
        res2 = self.store.film_modal.insert_ignored_alert("r1", "alert_x")
        self.assertTrue(res2["ok"])
        self.assertFalse(res2["inserted"])

    def test_list_ignored_alerts(self) -> None:
        self.store.film_modal.insert_ignored_alert("r1", "a")
        self.store.film_modal.insert_ignored_alert("r1", "b")
        self.store.film_modal.insert_ignored_alert("r2", "a")
        alerts_r1 = self.store.film_modal.list_ignored_alerts("r1")
        self.assertEqual(set(alerts_r1), {"a", "b"})
        self.assertEqual(set(self.store.film_modal.list_ignored_alerts("r2")), {"a"})

    def test_is_alert_ignored(self) -> None:
        self.store.film_modal.insert_ignored_alert("r1", "x")
        self.assertTrue(self.store.film_modal.is_alert_ignored("r1", "x"))
        self.assertFalse(self.store.film_modal.is_alert_ignored("r1", "other"))


class MarkAlertIgnoredApiTests(unittest.TestCase):
    """Verifie l'endpoint library/mark_alert_ignored."""

    def test_endpoint_returns_already_ignored_on_second_call(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        store = MagicMock()
        # 1er appel : inserted=True ; 2e : inserted=False
        store.film_modal.insert_ignored_alert.side_effect = [
            {"ok": True, "inserted": True, "ignored_at": 100.0},
            {"ok": True, "inserted": False, "ignored_at": 200.0},
        ]
        api._get_or_create_infra.return_value = (store, MagicMock())
        api.settings.get_settings.return_value = {"state_dir": "/tmp"}

        res1 = library_support.mark_alert_ignored(api, "r1", "code_x")
        res2 = library_support.mark_alert_ignored(api, "r1", "code_x")

        self.assertTrue(res1["ok"])
        self.assertFalse(res1["already_ignored"])
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["already_ignored"])

    def test_endpoint_validates_inputs(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        self.assertFalse(library_support.mark_alert_ignored(api, "", "code")["ok"])
        self.assertFalse(library_support.mark_alert_ignored(api, "r1", "")["ok"])


class GetFilmFullFiltersIgnoredAlertsTests(unittest.TestCase):
    """get_film_full filtre les warning_flags par alertes ignorees + persist."""

    def _build_api_with_ignored(self, ignored_codes: list) -> MagicMock:
        api = MagicMock()
        api.settings.get_settings.return_value = {"state_dir": "/tmp"}
        api.run.get_plan.return_value = {
            "ok": True,
            "rows": [
                {
                    "row_id": "f1",
                    "proposed_title": "La Doublure",
                    "proposed_year": 2006,
                    "warning_flags": ["subtitle_missing_fr", "root_level_source", "duplicate_cross_root"],
                    "candidates": [{"tmdb_id": 12345, "title": "La Doublure", "year": 2006}],
                }
            ],
        }
        store = MagicMock()
        store.run.list_runs.return_value = [{"run_id": "r1"}]
        store.perceptual.get_perceptual_report.return_value = None
        store.quality.get_quality_report.return_value = None
        store.film_modal.list_ignored_alerts.return_value = ignored_codes
        api._get_or_create_infra.return_value = (store, MagicMock())
        api.integrations.get_tmdb_posters.return_value = {"ok": True, "posters": {}}
        return api

    def test_filter_removes_ignored_alerts_from_warning_flags(self) -> None:
        from cinesort.ui.api import film_support

        api = self._build_api_with_ignored(["root_level_source"])
        res = film_support.get_film_full(api, "r1", "f1")

        self.assertTrue(res["ok"])
        row = res["row"]
        # root_level_source ignored -> retire des warning_flags
        self.assertNotIn("root_level_source", row["warning_flags"])
        # Les autres restent
        self.assertIn("subtitle_missing_fr", row["warning_flags"])
        self.assertIn("duplicate_cross_root", row["warning_flags"])
        # _ignored_alerts est expose pour le front (filtre redondant cote UI)
        self.assertIn("root_level_source", row["_ignored_alerts"])

    def test_no_ignored_alerts_passes_through_unchanged(self) -> None:
        from cinesort.ui.api import film_support

        api = self._build_api_with_ignored([])
        res = film_support.get_film_full(api, "r1", "f1")

        self.assertTrue(res["ok"])
        row = res["row"]
        # Les 3 alertes initiales preservees
        self.assertEqual(
            set(row["warning_flags"]), {"subtitle_missing_fr", "root_level_source", "duplicate_cross_root"}
        )
        # _ignored_alerts absent ou vide
        self.assertNotIn("_ignored_alerts", row)

    def test_multiple_ignored_alerts(self) -> None:
        from cinesort.ui.api import film_support

        api = self._build_api_with_ignored(["root_level_source", "duplicate_cross_root"])
        res = film_support.get_film_full(api, "r1", "f1")

        row = res["row"]
        self.assertEqual(row["warning_flags"], ["subtitle_missing_fr"])
        self.assertEqual(set(row["_ignored_alerts"]), {"root_level_source", "duplicate_cross_root"})


class PersistenceAcrossSessionsTests(unittest.TestCase):
    """Spec 06 §3.3 : alerte ignoree doit rester ignoree apres refresh (= relancer get_film_full)."""

    def test_alert_stays_ignored_across_get_film_full_calls(self) -> None:
        """Apres mark_alert_ignored, un nouveau get_film_full ne renvoie plus l'alerte."""
        from cinesort.ui.api import film_support, library_support

        # Setup : 1 vraie DB SQLite partagee
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "test.db")
            api = MagicMock()
            api.settings.get_settings.return_value = {"state_dir": tmp}
            api.run.get_plan.return_value = {
                "ok": True,
                "rows": [
                    {
                        "row_id": "r_persist",
                        "warning_flags": ["alert_a", "alert_b"],
                        "candidates": [],
                    }
                ],
            }
            store_mock = MagicMock(wraps=store)
            # On utilise les vraies methodes du film_modal
            store_mock.film_modal = store.film_modal
            store_mock.run.list_runs.return_value = [{"run_id": "r1"}]
            store_mock.perceptual.get_perceptual_report.return_value = None
            store_mock.quality.get_quality_report.return_value = None
            api._get_or_create_infra.return_value = (store_mock, MagicMock())
            api.integrations.get_tmdb_posters.return_value = {"ok": True, "posters": {}}

            # Step 1 : avant mark_alert_ignored -> les 2 alertes presentes
            res1 = film_support.get_film_full(api, "r1", "r_persist")
            self.assertEqual(set(res1["row"]["warning_flags"]), {"alert_a", "alert_b"})

            # Step 2 : on marque alert_a comme ignoree (via vraie insertion DB)
            mark_res = library_support.mark_alert_ignored(api, "r_persist", "alert_a")
            self.assertTrue(mark_res["ok"])

            # Step 3 : refresh get_film_full -> alert_a doit avoir disparu
            res2 = film_support.get_film_full(api, "r1", "r_persist")
            self.assertNotIn("alert_a", res2["row"]["warning_flags"])
            self.assertIn("alert_b", res2["row"]["warning_flags"])
            self.assertIn("alert_a", res2["row"]["_ignored_alerts"])


if __name__ == "__main__":
    unittest.main()
