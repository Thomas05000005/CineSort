"""AnomalyRepository : adapter composition du _AnomalyMixin (issue #85)."""

from __future__ import annotations

from cinesort.infra.db._anomaly_mixin import _AnomalyMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class AnomalyRepository(_BaseRepository, _AnomalyMixin):
    """Repository pour la table anomalies (warnings detectes pendant scan/apply).

    Methodes exposees (depuis _AnomalyMixin) :
        get_anomaly_counts_for_runs, get_anomaly_stats,
        get_top_anomaly_codes, list_anomalies_for_run
    """

    pass
