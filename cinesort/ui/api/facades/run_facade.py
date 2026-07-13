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

import logging
import os
from typing import Any, Dict, Optional

from cinesort.ui.api import library_actions_support
from cinesort.ui.api.facades._base import _BaseFacade

logger = logging.getLogger(__name__)

# V2.1 — Feature flag Pydantic strict (defaut 0 = passif).
# Memoire critique : "BACKWARD COMPAT ABSOLUE : TOUS les changements V2 =
# migration progressive avec feature flag, ancien code fonctionne TOUJOURS
# pendant transition. Aucun breaking change."
# - CINESORT_PYDANTIC_STRICT=0 (defaut) : on tente la validation, on log
#   un warning si elle echoue, et on retombe sur le dict legacy.
# - CINESORT_PYDANTIC_STRICT=1 : la validation devient bloquante.
_PYDANTIC_STRICT_ENV = "CINESORT_PYDANTIC_STRICT"


def _pydantic_strict_enabled() -> bool:
    """Lit le feature flag a chaque appel (toggleable a chaud en dev)."""
    return os.environ.get(_PYDANTIC_STRICT_ENV, "0").strip() not in ("", "0", "false", "False")


def _validate_passive(model_cls: Any, payload: Any, *, endpoint: str) -> Any:
    """Valide un payload via Pydantic en mode passif (memoire BACKWARD COMPAT).

    - Si pydantic n'est pas importable -> retourne payload tel quel (silencieux).
    - Si validation OK -> retourne le dict mode_dump (compat REST/dict legacy).
    - Si validation KO + flag PASSIF -> warning + retourne payload original.
    - Si validation KO + flag STRICT -> raise ValueError.
    """
    try:
        # Import LAZY pour ne pas casser le boot si pydantic est absent du
        # bundle (PyInstaller minimal). Le module est dans `requirements.txt`
        # pour les installs normales.
        from pydantic import ValidationError  # type: ignore
    except ImportError:
        return payload

    try:
        validated = model_cls.model_validate(payload)
        # On retourne dict (compat REST/JS frontend qui consomme via JSON).
        return validated.model_dump(mode="python")
    except ValidationError as exc:
        if _pydantic_strict_enabled():
            raise ValueError(f"Pydantic strict validation failed for {endpoint}: {exc}") from exc
        # ITER3 2026-06-08 (branche ii.b PYDANTIC SILENCIEUX) : on conserve le
        # fallback dict pour la BACKWARD COMPAT ABSOLUE (le run ne doit JAMAIS
        # casser sur une validation passive), mais on ELEVE le niveau de log a
        # ERROR pour rendre l'avalage visible dans les diagnostics. Un warning
        # passait inapercu et masquait des shapes d'entree appauvries (ex:
        # settings sans tmdb_api_key -> TMDb silencieusement desactive).
        logger.error(
            "[pydantic-passive] %s validation failed (flag=0, fallback dict): %s",
            endpoint,
            exc,
        )
        return payload
    except Exception as exc:  # noqa: BLE001 — defensif : ne JAMAIS casser le run.
        logger.error(
            "[pydantic-passive] %s unexpected error (flag=%s, fallback): %s",
            endpoint,
            _pydantic_strict_enabled(),
            exc,
        )
        return payload


class RunFacade(_BaseFacade):
    """Bounded context Run : cycle de vie des scans + plans + apply preview."""

    def start_plan(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Demarre un scan+plan en thread background.

        Cf CineSortApi.start_plan pour la doc complete.

        V2.1 : validation Pydantic PASSIVE (StartPlanRequest/Response).
        Activable strict via env var CINESORT_PYDANTIC_STRICT=1 (defaut 0).
        En cas d'echec de validation, on log un warning et on retombe sur la
        shape `dict[str, Any]` historique (BACKWARD COMPAT ABSOLUE).
        """
        # Lazy import (perf : ne pas charger pydantic au boot des imports
        # legacy de run_facade — cf #83 phase A8 lazy imports).
        try:
            from cinesort.ui.api.schemas import StartPlanRequest, StartPlanResponse  # type: ignore
        except ImportError:
            # Pydantic absent ou schemas manquants -> shape legacy directe.
            return self._api._start_plan_impl(settings)

        # Validation passive de l'entree (settings -> StartPlanRequest).
        # ITER3 2026-06-08 fix racine (branche ii.b) : le schema
        # `StartPlanRequest` exige une cle top-level `settings: PlanSettings`
        # (cf cinesort/ui/api/schemas/run.py L56). Le caller REST passe
        # directement le dict `settings` en kwarg a `start_plan(settings=...)`,
        # donc on doit RE-WRAPPER avant validation. L'ancienne adaptation
        # construisait `{library_path, options}` SANS cle `settings`, ce qui
        # faisait echouer la validation a 100% (Field required: settings) et
        # masquait des deviations reelles via le fallback passif.
        # Backward compat : on tolere aussi un caller qui passerait deja le
        # wrapper `{settings: {...}}` (cas hypothetique de migration future).
        request_payload: Dict[str, Any]
        if isinstance(settings, dict) and "settings" in settings and isinstance(settings["settings"], dict):
            # Caller deja conforme au wrapper StartPlanRequest.
            request_payload = settings
        else:
            # Cas nominal : `settings` est le dict plat des options de scan,
            # on l'enrobe pour matcher le schema. extra="allow" sur PlanSettings
            # preserve toutes les cles legacy (tmdb_api_key, tmdb_enabled, ...).
            request_payload = {"settings": settings if isinstance(settings, dict) else {}}
        _ = _validate_passive(StartPlanRequest, request_payload, endpoint="start_plan.request")

        # Appel REEL (memoire utilisateur : endpoint REEL = start_plan).
        result = self._api._start_plan_impl(settings)

        # Validation passive de la sortie (best-effort, ne raise jamais
        # sauf flag strict).
        _ = _validate_passive(StartPlanResponse, result, endpoint="start_plan.response")
        return result

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

    # ---------- Phase 4 spec 07 : rescan bulk ----------

    def rescan_rows_bulk(self, row_ids: list, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Phase 4 spec 07 : version bulk de rescan_row (lance un JobRunner).

        Cf cinesort.ui.api.library_actions_support.rescan_rows_bulk.
        """
        return library_actions_support.rescan_rows_bulk(self._api, row_ids, run_id=run_id)

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

    # VQ-2 QUARANTAINE-TTL : 3 endpoints filesystem `_review` ----------
    def purge_quarantine_bucket(
        self, ttl_days: int = 30, dry_run: bool = False
    ) -> Dict[str, Any]:
        """Purge les fichiers du bucket `_review` > `ttl_days` jours (defaut 30).

        Appele par le cron `cinesort.app.quarantine_ttl.start_quarantine_ttl_cron`
        au boot puis toutes les 24h. Aussi disponible manuellement (debug).

        Retourne `{ok, deleted, bytes_freed, considered, errors, by_subdir, ...}`.
        """
        return self._api._purge_quarantine_bucket_impl(int(ttl_days), bool(dry_run))

    def purge_quarantine_bucket_all(self, dry_run: bool = False) -> Dict[str, Any]:
        """Vider integralement le bucket `_review` (sauf `_duplicates_user_decided`).

        Appele par l'UI bouton "Vider maintenant" (parametres > Quarantaine),
        protege cote front par dangerConfirmModal (countdown 3s si > 50 fichiers).
        """
        return self._api._purge_quarantine_bucket_all_impl(bool(dry_run))

    def list_quarantine_bucket(self, limit: int = 500) -> Dict[str, Any]:
        """Inventaire du bucket `_review` pour le viewer UI.

        Tronque a `limit` entrees (defaut 500), triees mtime DESC.
        Retourne `{ok, review_root, exists, files_count, total_size_bytes, files, by_subdir}`.
        """
        return self._api._list_quarantine_bucket_impl(int(limit))

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

    # ---------- Pass 1 cleanup : 12 endpoints legacy migres vers /api/run/* ----------

    def get_dashboard(self, run_id: str = "latest") -> Dict[str, Any]:
        """Dashboard d'un run (KPIs, distribution scores, anomalies, timeline)."""
        return self._api._get_dashboard_impl(run_id)

    def get_global_stats(self, limit_runs: int = 20) -> Dict[str, Any]:
        """Global dashboard : statistiques multi-run pour la bibliotheque."""
        return self._api._get_global_stats_impl(limit_runs)

    def get_sidebar_counters(self) -> Dict[str, Any]:
        """V3-04 : compteurs sidebar pour badges UI (validation/application/quality)."""
        return self._api._get_sidebar_counters_impl()

    def apply(
        self,
        run_id: str,
        decisions: Dict[str, Dict[str, Any]],
        dry_run: bool,
        quarantine_unapproved: bool,
        apply_atomic: bool = False,
    ) -> Dict[str, Any]:
        """Applique les decisions de validation (deplacements/renommages reels ou dry-run).

        Vague P / VP-A : `apply_atomic=True` (opt-in, default False) declenche
        un rollback FS+DB forward si une exception interrompt le batch. La
        signature retour reste `{ok: bool, ...}` (backward compat ABSOLUE).

        V2.1 : validation Pydantic PASSIVE (ApplyRequest/ApplyResponse).
        Activable strict via env var CINESORT_PYDANTIC_STRICT=1.
        """
        try:
            from cinesort.ui.api.schemas import ApplyRequest, ApplyResponse  # type: ignore
        except ImportError:
            return self._api._apply_impl(
                run_id, decisions, dry_run, quarantine_unapproved,
                apply_atomic=bool(apply_atomic),
            )

        _ = _validate_passive(
            ApplyRequest,
            {
                "run_id": run_id,
                "decisions": decisions or {},
                "dry_run": bool(dry_run),
                "quarantine_unapproved": bool(quarantine_unapproved),
                "apply_atomic": bool(apply_atomic),
            },
            endpoint="apply.request",
        )
        result = self._api._apply_impl(
            run_id, decisions, dry_run, quarantine_unapproved,
            apply_atomic=bool(apply_atomic),
        )
        _ = _validate_passive(ApplyResponse, result, endpoint="apply.response")
        return result

    def save_validation(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Persiste les decisions de validation dans validation.json (atomique).

        Vague P / VP-D : accepte AUSSI la nouvelle cle optionnelle
        `decision: 'accepted'|'rejected'|'deferred'` en plus du legacy
        `ok: bool`. La shape de retour reste `{ok: bool, path: str}`
        — **backward compat ABSOLUE** (AC-2 ROADMAP_VAGUE_P).

        Coordination Vague P :
          - VP-A `apply_atomic` : aucun conflit kwargs (apply_atomic
            transite par `apply()`, pas par `save_validation()`, AC-5).
          - VP-C `field_locks` : la transition `deferred -> accepted`
            consulte les locks via `DecisionsRepository
            .upgrade_deferred_to_accepted` (AC-3).
        """
        return self._api._save_validation_impl(run_id, decisions)

    def load_validation(self, run_id: str) -> Dict[str, Any]:
        """Recharge les decisions (approve/reject) persistees pour ce run."""
        return self._api._load_validation_impl(run_id)

    def check_duplicates(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Detecte les collisions de destination entre rows approuvees avant apply.

        V2.1 : validation Pydantic PASSIVE
        (CheckDuplicatesRequest / CheckDuplicatesResponse avec discriminator='kind'
        sur les groupes : collision | similarity). Backward compat absolue.
        """
        try:
            from cinesort.ui.api.schemas import (  # type: ignore
                CheckDuplicatesRequest,
                CheckDuplicatesResponse,
            )
        except ImportError:
            return self._api._check_duplicates_impl(run_id, decisions)

        _ = _validate_passive(
            CheckDuplicatesRequest,
            {"run_id": run_id, "decisions": decisions or {}},
            endpoint="check_duplicates.request",
        )
        result = self._api._check_duplicates_impl(run_id, decisions)
        _ = _validate_passive(CheckDuplicatesResponse, result, endpoint="check_duplicates.response")
        return result

    def check_duplicates_fusion(
        self,
        run_id: str,
        decisions: Dict[str, Dict[str, Any]],
        *,
        audio_weight: Optional[float] = None,
        video_weight: Optional[float] = None,
    ) -> Dict[str, Any]:
        """V2.4 — Detection fusion Chromaprint + videohash (feature flag).

        Backward compat ABSOLUE :
        - `check_duplicates` legacy ci-dessus reste inchange et seul actif par
          defaut. Aucun appelant existant n'est impacte (nouvelle methode =
          nouveau nom, opt-in).
        - Cet endpoint est gate par `CINESORT_FUSION_DOUBLONS` (off par defaut) ;
          si le flag est off, retourne `{ok: True, enabled: False, pairs: []}`
          pour permettre a la UI de tester l'opt-in proprement.

        Args:
            run_id : id du run plan (deja en `done`).
            decisions : decisions de validation (meme shape que check_duplicates).
            audio_weight / video_weight : ponderation optionnelle (None = defaults
                0.4 / 0.6 du module fusion_score).
        """
        return self._api._check_duplicates_fusion_impl(
            run_id,
            decisions,
            audio_weight=audio_weight,
            video_weight=video_weight,
        )

    def get_cleanup_residual_preview(self, run_id: str) -> Dict[str, Any]:
        """Preview du nettoyage de fin de run : dossiers vides + residuels identifies."""
        return self._api._get_cleanup_residual_preview_impl(run_id)

    def undo_last_apply(self, run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]:
        """Annule le dernier batch apply reel (undo v1). `dry_run=True` ne touche rien."""
        return self._api._undo_last_apply_impl(run_id, dry_run, atomic=atomic)

    def export_run_nfo(self, run_id: str, overwrite: bool = False, dry_run: bool = True) -> Dict[str, Any]:
        """Genere des fichiers .nfo (Kodi/Jellyfin) pour chaque film du run."""
        return self._api._export_run_nfo_impl(run_id, overwrite=overwrite, dry_run=dry_run)

    def export_apply_audit(
        self,
        run_id: str,
        batch_id: Optional[str] = None,
        as_format: str = "json",
    ) -> Dict[str, Any]:
        """P2.3 : journal d'audit JSONL d'un apply (complementaire a apply_operations)."""
        return self._api._export_apply_audit_impl(run_id, batch_id, as_format=as_format)

    def import_watchlist(self, csv_content: str, source: str) -> Dict[str, Any]:
        """Importe une watchlist CSV (Letterboxd/IMDb) et compare avec la bibliotheque locale."""
        return self._api._import_watchlist_impl(csv_content, source)

    # ---------- Auto-approve & Undo (sprint C1 — refactor #84 suite) ----------

    def get_auto_approved_summary(
        self,
        run_id: str,
        threshold: Optional[int] = None,
        enabled: bool = False,
        quarantine_corrupted: bool = False,
    ) -> Dict[str, Any]:
        """Resume des rows auto-approuvees selon le seuil de confiance (mode batch).

        Cf CineSortApi._get_auto_approved_summary_impl pour la doc complete.
        """
        return self._api._get_auto_approved_summary_impl(
            run_id,
            threshold=threshold,
            enabled=enabled,
            quarantine_corrupted=quarantine_corrupted,
        )

    def undo_last_apply_preview(self, run_id: str) -> Dict[str, Any]:
        """Preview (dry) de l'annulation du dernier batch apply reel (undo v1).

        Cf CineSortApi._undo_last_apply_preview_impl pour la doc complete.
        """
        return self._api._undo_last_apply_preview_impl(run_id)

    def undo_by_row_preview(self, run_id: str, batch_id: str = None) -> Dict[str, Any]:
        """Preview de l'annulation par film : resume par row_id du batch cible (undo v5).

        Cf CineSortApi._undo_by_row_preview_impl pour la doc complete.
        """
        return self._api._undo_by_row_preview_impl(run_id, batch_id=batch_id)

    def undo_selected_rows(
        self,
        run_id: str,
        row_ids: list = None,
        dry_run: bool = True,
        batch_id: str = None,
        atomic: bool = True,
    ) -> Dict[str, Any]:
        """Annule selectivement les rows choisies (undo v5). `dry_run=True` ne touche rien.

        Cf CineSortApi._undo_selected_rows_impl pour la doc complete.
        """
        return self._api._undo_selected_rows_impl(
            run_id,
            row_ids=row_ids,
            dry_run=dry_run,
            batch_id=batch_id,
            atomic=atomic,
        )
