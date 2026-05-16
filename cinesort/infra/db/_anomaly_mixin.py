"""_AnomalyMixin : thin wrapper backward-compat (issue #85 phase B2).

Migration #85 phase B2 (2026-05-16) : le code metier a ete deplace dans
`cinesort.infra.db.repositories.anomaly.AnomalyRepository`. Ce mixin devient
un thin wrapper qui delegue a `self.anomaly.X()` pour preserver l'API
publique de SQLiteStore (`store.get_anomaly_counts_for_runs(...)` etc.).

Phase B8 future : SQLiteStore arretera d'heriter de ce mixin.
"""

from __future__ import annotations

from typing import Any, Dict, List


class _AnomalyMixin:
    """Backward-compat wrappers : delegue a self.anomaly (AnomalyRepository)."""

    def _ensure_anomalies_table(self) -> None:
        self.anomaly._ensure_anomalies_table()

    def get_anomaly_counts_for_runs(self, run_ids: List[str]) -> Dict[str, int]:
        return self.anomaly.get_anomaly_counts_for_runs(run_ids)

    def get_anomaly_stats(self, *, run_id: str) -> Dict[str, Any]:
        return self.anomaly.get_anomaly_stats(run_id=run_id)

    def get_top_anomaly_codes(self, *, limit_runs: int = 20, limit_codes: int = 10) -> List[Dict[str, Any]]:
        return self.anomaly.get_top_anomaly_codes(limit_runs=limit_runs, limit_codes=limit_codes)

    def list_anomalies_for_run(self, *, run_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self.anomaly.list_anomalies_for_run(run_id=run_id, limit=limit)
