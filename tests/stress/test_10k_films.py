"""V4-01 — Stress test 10 000 films : perf + RAM + DB size.

Skip par defaut. Lancer avec :
    CINESORT_STRESS=1 .venv313/Scripts/python.exe -m unittest tests.stress.test_10k_films -v

Cible les operations DB qui sont le goulot d'etranglement reel des endpoints
get_dashboard / get_global_stats / get_library_filtered :
  - list_quality_reports (utilise par dashboard + library)
  - list_perceptual_reports (utilise par library)
  - get_global_tier_distribution (utilise par dashboard)
  - get_global_tier_v2_distribution (utilise par Home overview)
  - get_quality_counts_for_runs (utilise par dashboard + global_stats)
  - get_global_score_v2_trend (utilise par Home trend chart)
  - dashboard_support._compute_v2_tier_distribution / _compute_space_analysis

Pas d'instantiation api/runner : on stresse la couche DB directement, qui est
le seul facteur qui depend lineairement du nombre de films.
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List


_STRESS_FILMS = int(os.environ.get("CINESORT_STRESS_COUNT") or "10000")
_PERF_BUDGET_S = 2.0
_RAM_BUDGET_MB = 1024
_DB_BUDGET_MB = 100


def _measured(label: str, fn: Callable[[], Any]) -> Dict[str, Any]:
    """Mesure duree + taille resultat (len si applicable) d'un appel."""
    gc.collect()
    t0 = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - t0
    size: Any = None
    if hasattr(result, "__len__"):
        try:
            size = len(result)
        except TypeError:
            size = None
    return {"label": label, "elapsed_s": elapsed, "size": size, "result": result}


class Stress10kTests(unittest.TestCase):
    """Stress test 10 000 films : valide perf, RAM et taille DB."""

    tmpdir: str
    db_path: Path
    store: Any
    run_id: str
    measurements: List[Dict[str, Any]]
    gen_duration_s: float
    db_size_mb: float

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("CINESORT_STRESS") != "1":
            raise unittest.SkipTest("Stress test : set CINESORT_STRESS=1 to run")

        sys.path.insert(0, ".")
        cls.tmpdir = tempfile.mkdtemp(prefix="cinesort_stress_")
        cls.db_path = Path(cls.tmpdir) / "stress.db"

        from tests.stress.generate_demo_library import generate_films

        stats = generate_films(_STRESS_FILMS, cls.db_path)
        cls.run_id = stats["run_id"]
        cls.gen_duration_s = stats["duration_s"]
        cls.db_size_mb = cls.db_path.stat().st_size / 1024 / 1024

        from cinesort.infra.db.sqlite_store import SQLiteStore

        cls.store = SQLiteStore(cls.db_path)
        cls.store.initialize()
        cls.measurements = []

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

        report_lines = [
            "",
            "=== V4-01 stress test measurements ===",
            f"Films generes : {_STRESS_FILMS}",
            f"Duree generation : {cls.gen_duration_s:.2f}s",
            f"Taille DB : {cls.db_size_mb:.2f} MB",
            "",
            "Operations DB (cibles < 2.0s sur 10k films) :",
        ]
        for m in cls.measurements:
            size_part = f" -> {m['size']} items" if m["size"] is not None else ""
            report_lines.append(f"  {m['label']:<40} {m['elapsed_s'] * 1000:>8.1f} ms{size_part}")
        print("\n".join(report_lines))

    def _record(self, label: str, fn: Callable[[], Any]) -> Dict[str, Any]:
        m = _measured(label, fn)
        type(self).measurements.append(m)
        return m

    def test_db_size_under_budget(self) -> None:
        self.assertLess(
            type(self).db_size_mb,
            _DB_BUDGET_MB,
            f"DB > {_DB_BUDGET_MB} MB sur {_STRESS_FILMS} films : {type(self).db_size_mb:.1f} MB",
        )

    def test_list_quality_reports_under_budget(self) -> None:
        m = self._record(
            "list_quality_reports",
            lambda: type(self).store.list_quality_reports(run_id=type(self).run_id),
        )
        self.assertEqual(m["size"], _STRESS_FILMS)
        self.assertLess(
            m["elapsed_s"],
            _PERF_BUDGET_S,
            f"list_quality_reports trop lent : {m['elapsed_s']:.2f}s sur {_STRESS_FILMS} films",
        )

    def test_list_perceptual_reports_under_budget(self) -> None:
        m = self._record(
            "list_perceptual_reports",
            lambda: type(self).store.list_perceptual_reports(run_id=type(self).run_id),
        )
        self.assertEqual(m["size"], _STRESS_FILMS)
        self.assertLess(
            m["elapsed_s"],
            _PERF_BUDGET_S,
            f"list_perceptual_reports trop lent : {m['elapsed_s']:.2f}s",
        )

    def test_aggregations_under_budget(self) -> None:
        run_ids = [type(self).run_id]
        store = type(self).store

        m1 = self._record(
            "get_global_tier_distribution",
            lambda: store.get_global_tier_distribution(limit_runs=20),
        )
        m2 = self._record(
            "get_global_tier_v2_distribution",
            lambda: store.get_global_tier_v2_distribution(run_ids=run_ids),
        )
        m3 = self._record(
            "get_quality_counts_for_runs",
            lambda: store.get_quality_counts_for_runs(run_ids),
        )
        m4 = self._record(
            "get_anomaly_counts_for_runs",
            lambda: store.anomaly.get_anomaly_counts_for_runs(run_ids),
        )
        m5 = self._record(
            "get_top_anomaly_codes",
            lambda: store.anomaly.get_top_anomaly_codes(limit_runs=20, limit_codes=10),
        )
        m6 = self._record(
            "get_global_score_v2_trend",
            lambda: store.get_global_score_v2_trend(since_ts=0.0),
        )

        for m in (m1, m2, m3, m4, m5, m6):
            self.assertLess(
                m["elapsed_s"],
                _PERF_BUDGET_S,
                f"{m['label']} trop lent : {m['elapsed_s']:.2f}s",
            )

    def test_dashboard_support_helpers_under_budget(self) -> None:
        from cinesort.ui.api import dashboard_support

        store = type(self).store
        run_id = type(self).run_id

        m1 = self._record(
            "_compute_v2_tier_distribution",
            lambda: dashboard_support._compute_v2_tier_distribution(store, [run_id]),
        )
        m2 = self._record(
            "_compute_trend_30days",
            lambda: dashboard_support._compute_trend_30days(store),
        )
        m3 = self._record(
            "_compute_space_analysis",
            lambda: dashboard_support._compute_space_analysis(store, run_id),
        )

        for m in (m1, m2, m3):
            self.assertLess(
                m["elapsed_s"],
                _PERF_BUDGET_S,
                f"{m['label']} trop lent : {m['elapsed_s']:.2f}s",
            )

    def test_ram_pic_under_budget(self) -> None:
        store = type(self).store
        run_id = type(self).run_id

        gc.collect()
        tracemalloc.start()
        try:
            for _ in range(5):
                _ = store.list_quality_reports(run_id=run_id)
                _ = store.list_perceptual_reports(run_id=run_id)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        peak_mb = peak_bytes / 1024 / 1024
        type(self).measurements.append(
            {"label": "tracemalloc_peak_5x_lists", "elapsed_s": 0.0, "size": int(peak_mb), "result": None}
        )
        self.assertLess(peak_mb, _RAM_BUDGET_MB, f"Pic RAM > {_RAM_BUDGET_MB} MB : {peak_mb:.1f} MB")


if __name__ == "__main__":
    unittest.main()
