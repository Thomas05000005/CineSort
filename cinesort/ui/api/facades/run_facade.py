"""RunFacade : bounded context Run Flow (issue #84 PR 2 — migration complete).

Cf docs/internal/REFACTOR_PLAN_84.md.

7 methodes du bounded context Run :
    - start_plan : demarre scan+plan en thread background
    - get_status : progression + logs + sante d'un run
    - get_plan : liste PlanRow persistees (plan.jsonl)
    - export_run_report : export json/csv/html du rapport
    - cancel_run : pose cancel_requested=1
    - build_apply_preview : plan avant/apres des deplacements
    - list_apply_history : batches apply reels + dry-run

Strategie Strangler Fig + Adapter pattern :
- Les 7 methodes existent EN PARALLELE sur CineSortApi (preserve backward-compat)
- Cette facade delegue simplement vers self._api.X
- Les nouveaux call sites peuvent utiliser api.run.X(...)
- Les anciens call sites (api.X(...)) continuent de fonctionner
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cinesort.ui.api.facades._base import _BaseFacade


class RunFacade(_BaseFacade):
    """Bounded context Run : cycle de vie des scans + plans + apply preview."""

    def start_plan(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Demarre un scan+plan en thread background.

        Cf CineSortApi.start_plan pour la doc complete.
        """
        return self._api._start_plan_impl(settings)

    def get_status(self, run_id: str, last_log_index: int = 0) -> Dict[str, Any]:
        """Progression + logs + sante d'un run.

        Cf CineSortApi.get_status pour la doc complete.
        """
        return self._api._get_status_impl(run_id, last_log_index)

    def get_plan(self, run_id: str) -> Dict[str, Any]:
        """Retourne la liste des PlanRow persistees dans plan.jsonl.

        Cf CineSortApi.get_plan pour la doc complete.
        """
        return self._api._get_plan_impl(run_id)

    def export_run_report(self, run_id: str, fmt: str = "json") -> Dict[str, Any]:
        """Exporte le rapport du run au format json / csv / html.

        Cf CineSortApi.export_run_report pour la doc complete.
        """
        return self._api._export_run_report_impl(run_id, fmt)

    def cancel_run(self, run_id: str) -> Dict[str, Any]:
        """Demande l'annulation d'un run en cours (pose cancel_requested=1).

        Cf CineSortApi.cancel_run pour la doc complete.
        """
        return self._api._cancel_run_impl(run_id)

    def build_apply_preview(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Plan structure "avant/apres" des deplacements, par film.

        Cf CineSortApi.build_apply_preview pour la doc complete.
        """
        return self._api._build_apply_preview_impl(run_id, decisions)

    def list_apply_history(self, run_id: str) -> Dict[str, Any]:
        """Historique de tous les applies d'un run (batches reels + dry-run).

        Cf CineSortApi.list_apply_history pour la doc complete.
        """
        return self._api._list_apply_history_impl(run_id)

    # ----- Historique (spec 09) -----
    def get_history_stats(self, run_id: str) -> Dict[str, Any]:
        """Detail complet d'un run pour l'inspecteur Historique.

        Retourne `{ok, run: {run_id, started_ts, duration_s, status,
        total_rows, applied_rows, validated_count, rejected_count,
        errors_count, conflicts_count, duplicates_groups, score_avg,
        films_by_tier, apply_operations: [...]}}` avec fallback gracieux
        si certaines tables/JSON ne sont pas disponibles.

        Cf spec 09 §6 (Source backend).
        """
        return self._api._get_history_stats_impl(run_id)

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        """Supprime un run de l'historique (DB seulement, pas les fichiers video).

        Cascade :
        - errors / quality_reports / anomalies (FK CASCADE)
        - perceptual_reports / apply_batches / apply_operations (manuel)

        Cf spec 09 §4 (action dangereuse — frontend affiche modale).
        """
        return self._api._delete_run_impl(run_id)

    def cleanup_old_runs(self, retention_days: int = 90) -> Dict[str, Any]:
        """Supprime tous les runs > N jours (defaut 90).

        Appele :
        - manuellement (debug / forcer la purge)
        - automatiquement au boot par le cron retention_cleanup

        Retourne `{ok, deleted_count, deleted_run_ids: [...], retention_days}`.
        """
        return self._api._cleanup_old_runs_impl(retention_days)
    def rescan_row(self, run_id: str, row_id: str) -> Dict[str, Any]:
        """Spec 06 §3.6 : relance probe + analyse perceptuelle pour 1 row.

        Cf CineSortApi._rescan_row_impl pour la doc complete.
        """
        return self._api._rescan_row_impl(run_id, row_id)

    def mark_duplicate_winner(
        self,
        run_id: str,
        group_key: str,
        winner_row_id: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Phase 4 doublons : persiste la decision utilisateur "garder ce winner".

        Cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md
        section 3. Les autres rows du groupe seront deplaces vers
        <root>/_review/_duplicates_user_decided/ a l'apply.

        Returns:
            {ok, group_key, winner_row_id, losers, decided_ts}.
        """
        return self._api._mark_duplicate_winner_impl(run_id, group_key, winner_row_id, notes)
