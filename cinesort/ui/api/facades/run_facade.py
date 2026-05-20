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

from typing import Any, Dict

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

    # ---------- Run Control (V8-01 spec 08 Traitement §5) ----------
    def pause_run(self, run_id: str) -> Dict[str, Any]:
        """Suspend un run actif (signaling + DB PAUSED).

        Cf CineSortApi._pause_run_impl pour la doc complete.
        """
        return self._api._pause_run_impl(run_id)

    def resume_run(self, run_id: str) -> Dict[str, Any]:
        """Reprend un run PAUSED ou SAVED (signaling + DB RUNNING).

        Cf CineSortApi._resume_run_impl pour la doc complete.
        """
        return self._api._resume_run_impl(run_id)

    def save_for_later(self, run_id: str) -> Dict[str, Any]:
        """Sauvegarde un run pour plus tard (signaling + DB SAVED).

        Cf CineSortApi._save_for_later_impl pour la doc complete.
        """
        return self._api._save_for_later_impl(run_id)

    def list_pending_runs(self) -> Dict[str, Any]:
        """Liste les runs PAUSED / SAVED / AWAITING_VALIDATION.

        Cf CineSortApi._list_pending_runs_impl pour la doc complete.
        """
        return self._api._list_pending_runs_impl()
