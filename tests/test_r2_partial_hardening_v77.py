"""GATE R2.2 (2026-06-11) — durcit les fixes 771c30c (film timeline events +
analyze_quality_batch scope=validated) qui n'avaient AUCUN test.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cinesort.ui.api import film_support, quality_support


class QualityScopeValidatedTests(unittest.TestCase):
    """_resolve_ids_from_scope(scope='validated') passe par api.run.load_validation
    (api.load_validation n'existe pas -> 500 avant le fix)."""

    def _api(self, *, has_run_load=True):
        api = MagicMock()
        api.run.get_plan.return_value = {
            "ok": True,
            "rows": [{"row_id": "r1"}, {"row_id": "r2"}, {"row_id": "r3"}],
        }
        if has_run_load:
            api.run.load_validation.return_value = {"ok": True, "decisions": {"r1": {"ok": True}, "r3": {"ok": True}}}
        return api

    def test_scope_validated_filters_via_run_load_validation(self) -> None:
        api = self._api()
        out = quality_support._resolve_ids_from_scope(api, "run1", "validated")
        api.run.load_validation.assert_called_once_with("run1")
        # seuls r1 et r3 sont valides
        ids = set(out.get("row_ids") or out.get("ids") or [])
        if not ids and isinstance(out, dict):
            # selon le shape : chercher la liste d'ids dans le payload
            for v in out.values():
                if isinstance(v, list):
                    ids = set(v)
                    break
        self.assertEqual(ids, {"r1", "r3"})

    def test_scope_validated_no_attribute_error(self) -> None:
        # api.run.load_validation leve AttributeError -> doit etre rattrape (pas de 500)
        api = self._api()
        api.run.load_validation.side_effect = AttributeError("boom")
        out = quality_support._resolve_ids_from_scope(api, "run1", "validated")
        self.assertIsInstance(out, dict)  # ne leve pas


class FilmHistoryEventsTests(unittest.TestCase):
    """get_film_full peuple history depuis la cle 'events' (pas 'history')."""

    def test_history_populated_from_events_key(self) -> None:
        api = MagicMock()
        row = {"row_id": "r1", "proposed_title": "X", "proposed_year": 2020,
               "candidates": [{"tmdb_id": 27205}], "folder": "C:/f", "video": "x.mkv"}
        events = [{"type": "scan", "run_id": "run1"}, {"type": "apply", "run_id": "run1"}]
        with patch.object(film_support, "_resolve_run_id", return_value="run1"), \
             patch.object(film_support, "_find_plan_row", return_value=row), \
             patch.object(film_support.film_history_support, "get_film_history",
                          return_value={"ok": True, "events": events}):
            # store/perceptual/quality renvoient None gracieusement
            api._get_or_create_infra.return_value = (MagicMock(), None)
            api.settings.get_settings.return_value = {"state_dir": "/tmp"}
            out = film_support._get_film_full_impl(api, "run1", "r1")
        self.assertEqual(out.get("history"), events, "history doit etre peuple depuis 'events'")

    def test_history_empty_when_no_events(self) -> None:
        api = MagicMock()
        row = {"row_id": "r1", "proposed_title": "X", "proposed_year": 2020, "candidates": []}
        with patch.object(film_support, "_resolve_run_id", return_value="run1"), \
             patch.object(film_support, "_find_plan_row", return_value=row), \
             patch.object(film_support.film_history_support, "get_film_history",
                          return_value={"ok": True, "events": []}):
            api._get_or_create_infra.return_value = (MagicMock(), None)
            api.settings.get_settings.return_value = {"state_dir": "/tmp"}
            out = film_support._get_film_full_impl(api, "run1", "r1")
        self.assertEqual(out.get("history"), [])


if __name__ == "__main__":
    unittest.main()
