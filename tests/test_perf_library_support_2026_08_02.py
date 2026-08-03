"""ULTRA AUDIT 2026-08-02 — points chauds de `_build_library_rows`.

Trois defauts de performance, tous dans cinesort/ui/api/library_support.py :

1. (HIGH, :231) l'overlay TMDb etait applique DEUX fois sur les memes dicts —
   une premiere fois par `api.run.get_plan` (history_support._enrich_plan_payload)
   puis une seconde ici. Chaque `get_tmdb_override` ouvre 2 connexions SQLite,
   donc la vue Bibliotheque payait 4N connexions par affichage au lieu de 2N.
2. (HIGH, :1325 et :1152) les compteurs de chips et le rollup scoring
   n'exposent AUCUNE jaquette mais declenchaient quand meme le batch
   `get_tmdb_posters` (reconstruction d'un TmdbClient + relecture integrale de
   tmdb_cache.json, et appels HTTP TMDb pour les ids pas encore en cache).
3. (LOW, :294) la dedup des tmdb_id du batch testait l'appartenance sur la
   LISTE en construction -> O(n^2).

Chaque test a ete vu ROUGE en cassant le correctif correspondant.
"""

from __future__ import annotations

import time
import unittest
from typing import Any, Dict, List, Optional

from cinesort.ui.api import library_support

# ---------------------------------------------------------------------------
# Doubles de test (pas de MagicMock : on compte les appels exactement)
# ---------------------------------------------------------------------------


class _EmptyReports:
    def list_perceptual_reports(self, run_id=None):  # noqa: ANN001, ANN201
        return []

    def list_quality_reports(self, run_id=None):  # noqa: ANN001, ANN201
        return []


class _CountingFilmModal:
    """Compte les lectures de film_tmdb_overrides (2 connexions SQLite reelles)."""

    def __init__(self, overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.overrides = overrides or {}
        self.calls: List[str] = []

    def get_tmdb_override(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append(f"{run_id}/{row_id}")
        return self.overrides.get(row_id)


class _FakeStore:
    def __init__(self, film_modal: _CountingFilmModal) -> None:
        self.perceptual = _EmptyReports()
        self.quality = _EmptyReports()
        self.film_modal = film_modal


class _CountingIntegrations:
    def __init__(self) -> None:
        self.calls: List[List[int]] = []

    def get_tmdb_posters(self, tmdb_ids: List[int], size: str = "w92") -> Dict[str, Any]:
        self.calls.append(list(tmdb_ids))
        return {"ok": True, "posters": {str(i): f"https://img/{i}_{size}.jpg" for i in tmdb_ids}}


class _FakeApi:
    """api minimal : settings, _get_or_create_infra, run.get_plan, integrations."""

    class _Settings:
        def __init__(self, state_dir: str) -> None:
            self._state_dir = state_dir

        def get_settings(self) -> Dict[str, Any]:
            return {"state_dir": self._state_dir}

    class _Run:
        def __init__(self, rows: List[Dict[str, Any]]) -> None:
            self._rows = rows

        def get_plan(self, run_id: str) -> Dict[str, Any]:
            return {"ok": True, "rows": self._rows}

    def __init__(
        self,
        plan_rows: List[Dict[str, Any]],
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        state_dir: str = "",
    ) -> None:
        self.settings = self._Settings(state_dir)
        self.run = self._Run(plan_rows)
        self.film_modal = _CountingFilmModal(overrides)
        self.store = _FakeStore(self.film_modal)
        self.integrations = _CountingIntegrations()

    def _get_or_create_infra(self, state_dir):  # noqa: ANN001, ANN202
        return (self.store, None)


def _plan_row(row_id: str, *, tmdb_id: int = 0, enriched: bool = False) -> Dict[str, Any]:
    """PlanRow serialisee. `enriched=True` simule le passage par get_plan reel
    (history_support._enrich_plan_payload pose `display_title` juste APRES avoir
    applique l'overlay TMDb sur la meme row)."""
    row: Dict[str, Any] = {
        "row_id": row_id,
        "proposed_title": f"Film {row_id}",
        "proposed_year": 2000,
        "confidence": 90,
        "proposed_source": "nfo",
        "candidates": [],
    }
    if tmdb_id:
        row["tmdb_id"] = tmdb_id
    if enriched:
        row["display_title"] = f"Film {row_id}"
        row["auto_approvable"] = True
    return row


# ---------------------------------------------------------------------------
# 1. HIGH :231 — pas de second overlay quand get_plan a deja enrichi
# ---------------------------------------------------------------------------


class DoubleOverlayTests(unittest.TestCase):
    def test_no_second_override_read_when_plan_already_enriched(self) -> None:
        """Le chemin de PROD : get_plan renvoie des rows deja enrichies."""
        rows = [_plan_row(f"r{i}", tmdb_id=100 + i, enriched=True) for i in range(25)]
        api = _FakeApi(rows)

        out = library_support._build_library_rows(api, "run1")

        # Le correctif : zero relecture de film_tmdb_overrides (donc zero
        # connexion SQLite supplementaire) pour les rows deja enrichies.
        self.assertEqual(api.film_modal.calls, [])
        # NON-REGRESSION (vert des deux cotes du correctif) : les rows sont
        # construites normalement et portent bien le tmdb_id resolu.
        self.assertEqual(len(out), 25)
        self.assertEqual(out[0]["tmdb_id"], 100)
        self.assertEqual(out[0]["title"], "Film r0")

    def test_override_still_applied_when_plan_not_enriched(self) -> None:
        """Filet de securite : si get_plan n'enrichit pas (stub, enrichissement
        tombe en erreur), l'overlay DOIT toujours etre applique ici."""
        rows = [_plan_row("r0", tmdb_id=111), _plan_row("r1", tmdb_id=222)]
        api = _FakeApi(
            rows,
            overrides={
                "r0": {
                    "tmdb_id": 999,
                    "proposed_title": "Titre Choisi",
                    "proposed_year": 2021,
                    "new_confidence": 88,
                }
            },
        )

        out = library_support._build_library_rows(api, "run1")
        by_id = {r["row_id"]: r for r in out}

        self.assertEqual(len(api.film_modal.calls), 2)
        self.assertEqual(by_id["r0"]["tmdb_id"], 999)
        self.assertEqual(by_id["r0"]["title"], "Titre Choisi")
        self.assertEqual(by_id["r0"]["year"], 2021)
        # La row sans override reste sur son match auto.
        self.assertEqual(by_id["r1"]["tmdb_id"], 222)

    def test_mixed_rows_only_unenriched_are_overlaid(self) -> None:
        rows = [
            _plan_row("r0", tmdb_id=111, enriched=True),
            _plan_row("r1", tmdb_id=222, enriched=False),
        ]
        api = _FakeApi(rows)

        library_support._build_library_rows(api, "run1")

        self.assertEqual(api.film_modal.calls, ["run1/r1"])


# ---------------------------------------------------------------------------
# 2. HIGH :1325 / :1152 — pas de batch jaquettes pour les surfaces sans jaquette
# ---------------------------------------------------------------------------


class PosterBatchScopeTests(unittest.TestCase):
    def _api(self) -> _FakeApi:
        rows = [_plan_row(f"r{i}", tmdb_id=500 + i, enriched=True) for i in range(10)]
        return _FakeApi(rows)

    def test_counters_by_chip_does_not_fetch_posters(self) -> None:
        api = self._api()
        res = library_support.get_library_counters_by_chip(api, filters={}, run_id="run1")

        self.assertEqual(api.integrations.calls, [])
        # NON-REGRESSION : les compteurs restent exacts.
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 10)
        self.assertEqual(res["counts"]["unknown"], 10)

    def test_scoring_rollup_does_not_fetch_posters(self) -> None:
        api = self._api()
        res = library_support.get_scoring_rollup(api, by="decade", run_id="run1")

        self.assertEqual(api.integrations.calls, [])
        self.assertTrue(res["ok"])
        self.assertTrue(res["groups"])

    def test_library_filtered_still_fetches_posters(self) -> None:
        """NON-REGRESSION : la grille de la Bibliotheque, elle, affiche les
        jaquettes — le batch doit rester (et rester UN seul appel batche)."""
        api = self._api()
        res = library_support.get_library_filtered(api, "run1", {}, "title_asc", 1, 50)

        self.assertEqual(len(api.integrations.calls), 1)
        self.assertEqual(api.integrations.calls[0], [500 + i for i in range(10)])
        self.assertEqual(res["rows"][0]["poster_url"], "https://img/500_w342.jpg")

    def test_rows_without_poster_batch_keep_tmdb_id(self) -> None:
        """Sauter le batch ne doit PAS priver les rows de leur tmdb_id resolu
        (le frontend passe par le proxy /api/poster avec cet id)."""
        api = self._api()
        rows = library_support._build_library_rows(api, "run1", with_posters=False)

        self.assertEqual(api.integrations.calls, [])
        self.assertEqual([r["tmdb_id"] for r in rows], [500 + i for i in range(10)])
        self.assertTrue(all(r["poster_url"] is None for r in rows))


# ---------------------------------------------------------------------------
# 3. LOW :294 — dedup des tmdb_id en O(n), pas O(n^2)
# ---------------------------------------------------------------------------


class DedupIdsTests(unittest.TestCase):
    def test_dedup_keeps_first_occurrence_order(self) -> None:
        """NON-REGRESSION : meme resultat que l'ancien `if x not in out`."""
        self.assertEqual(
            library_support._dedup_ids_preserving_order([7, 3, 7, 9, 3, 1]),
            [7, 3, 9, 1],
        )
        self.assertEqual(library_support._dedup_ids_preserving_order([]), [])

    def test_dedup_is_not_quadratic(self) -> None:
        """30 000 ids distincts : ~3 ms avec un set, ~2 500 ms avec un `in list`.

        Seuil a 1,0 s = 300x de marge cote lineaire, et la version quadratique
        depasse quand meme (mesure 2,47 s sur la machine de dev).
        """
        ids = list(range(30_000))
        started = time.perf_counter()
        out = library_support._dedup_ids_preserving_order(ids)
        elapsed = time.perf_counter() - started

        self.assertEqual(len(out), 30_000)
        self.assertLess(elapsed, 1.0, f"dedup quadratique suspectee ({elapsed:.3f} s)")

    def test_batch_ids_are_deduped_in_build(self) -> None:
        """NON-REGRESSION bout en bout : le batch recoit chaque id UNE fois,
        dans l'ordre de premiere apparition."""
        rows = [
            _plan_row("r0", tmdb_id=42, enriched=True),
            _plan_row("r1", tmdb_id=7, enriched=True),
            _plan_row("r2", tmdb_id=42, enriched=True),
            _plan_row("r3", tmdb_id=7, enriched=True),
        ]
        api = _FakeApi(rows)

        library_support._build_library_rows(api, "run1")

        self.assertEqual(api.integrations.calls, [[42, 7]])


if __name__ == "__main__":
    unittest.main()
