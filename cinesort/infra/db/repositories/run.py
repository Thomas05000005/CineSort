"""RunRepository : adapter composition du _RunMixin (issue #85)."""

from __future__ import annotations

from cinesort.infra.db._run_mixin import _RunMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class RunRepository(_BaseRepository, _RunMixin):
    """Repository pour le cycle de vie des runs + journal d'erreurs.

    Methodes exposees (depuis _RunMixin) :
        insert_run_pending, mark_run_running, update_run_progress,
        mark_cancel_requested, mark_run_done, mark_run_cancelled,
        mark_run_failed, insert_error, get_run, list_errors,
        get_latest_run, list_runs, get_runs_summary, get_error_counts_for_runs
    """

    pass
