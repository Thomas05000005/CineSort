"""QualityRepository : adapter composition du _QualityMixin (issue #85)."""

from __future__ import annotations

from cinesort.infra.db._quality_mixin import _QualityMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class QualityRepository(_BaseRepository, _QualityMixin):
    """Repository pour les profils qualite + rapports + feedback user.

    Methodes exposees (depuis _QualityMixin) :
        get_active_quality_profile, save_quality_profile, get_quality_report,
        upsert_quality_report, list_quality_reports,
        insert_user_quality_feedback, list_user_quality_feedback,
        delete_user_quality_feedback, get_quality_report_stats,
        get_global_tier_distribution, get_unscored_film_count,
        get_quality_counts_for_runs
    """

    pass
