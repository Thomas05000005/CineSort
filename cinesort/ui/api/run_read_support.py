from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import cinesort.domain.core as core
from cinesort.app.cleanup import preview_cleanup_residual_folders as _preview_cleanup_fn
from cinesort.domain.conversions import to_bool, to_int
from cinesort.domain.run_models import RunStatus
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._validators import requires_valid_run_id

# [auto-approve] Warnings qui EXCLUENT une row de l'auto-approbation. Source
# unique partagée par get_auto_approved_summary (compteur dashboard) et le seed
# READ-TIME de la Validation (seed_auto_approve_decisions).
_AUTO_CRITICAL_WARNINGS = {"nfo_title_mismatch", "nfo_year_mismatch", "year_conflict_folder_file"}
_AUTO_INTEGRITY_WARNINGS = {"integrity_header_invalid", "integrity_probe_failed"}

# [partition] Flags de CONFLIT (incohérence de source). Ils BLOQUENT l'auto-approbation
# pour que la tranche "Conflits" soit un SOUS-ENSEMBLE strict de "à examiner" (= NON
# auto-approuvable). Sans ça, un film en conflit pouvait être compté à la fois
# "auto-approuvable" ET "conflit" -> 843 + 157 > total (partition impossible).
# Source UNIQUE partagée avec dashboard_support._build_dashboard_section.
_CONFLICT_FLAGS = frozenset(
    {
        "year_conflict_folder_file",
        "nfo_year_mismatch",
        "nfo_title_mismatch",
        "nfo_file_mismatch",
        "runtime_mismatch",
        "runtime_mismatch_likely_wrong_film",
        "omdb_disagree",
        "title_ambiguity_detected",
        "not_a_movie",
        "year_missing",
    }
)


# Ensemble BLOQUANT complet (critique ∪ intégrité ∪ conflit).
_AUTO_BLOCKING = _AUTO_CRITICAL_WARNINGS | _AUTO_INTEGRITY_WARNINGS | _CONFLICT_FLAGS


def is_auto_approvable_flags(
    flags: Any, confidence: Any, proposed_title: Any, proposed_year: Any, threshold: int
) -> bool:
    """Cœur du prédicat auto-approvable sur un ENSEMBLE de flags EXPLICITE (censé déjà nettoyé
    des alertes ignorées). Permet aux compteurs KPI (dashboard / auto-approved summary) de
    calculer sur EXACTEMENT les mêmes flags effectifs que le payload get_plan
    (_subtract_ignored_flags) — sinon "Cas à vérifier" (KPI, flags bruts) diverge de
    "Tous problèmes" (liste, flags ignorés-soustraits) dès qu'une alerte bloquante est ignorée."""
    has_title = bool(proposed_title and str(proposed_title).strip())
    has_year = bool(proposed_year and int(proposed_year or 0) >= 1900)
    return int(confidence or 0) >= int(threshold) and not (set(flags or ()) & _AUTO_BLOCKING) and has_title and has_year


def is_auto_approvable(row: Any, threshold: int) -> bool:
    """[auto-approve] Prédicat sur une PlanRow (flags BRUTS). Confiance ≥ seuil, titre + année
    présents, aucun warning critique / d'intégrité / de conflit (un conflit bloque -> "conflits"
    ⊆ "à examiner"). Pour un calcul aligné sur le payload, utiliser is_auto_approvable_flags avec
    les flags effectifs."""
    return is_auto_approvable_flags(
        set(getattr(row, "warning_flags", None) or []),
        getattr(row, "confidence", 0),
        getattr(row, "proposed_title", ""),
        getattr(row, "proposed_year", 0),
        threshold,
    )


def ignored_alerts_by_row(store: Any, row_ids: List[str]) -> Dict[str, Set[str]]:
    """Codes d'alertes IGNORÉES par row (store.film_modal), pour aligner les compteurs sur le
    payload get_plan (history_support._subtract_ignored_flags). Best-effort : {} si indisponible."""
    out: Dict[str, Set[str]] = {}
    try:
        if store is not None and hasattr(store, "film_modal"):
            bulk = store.film_modal.list_ignored_alerts_bulk([str(r) for r in row_ids]) or {}
            for rid, codes in bulk.items():
                out[str(rid)] = {str(c) for c in (codes or [])}
    except Exception:  # noqa: BLE001 — best-effort
        return {}
    return out


def effective_flags(raw_flags: Any, ignored_codes: Any) -> Set[str]:
    """Flags EFFECTIFS = bruts MOINS les alertes ignorées (miroir de _subtract_ignored_flags)."""
    ignored = ignored_codes or ()
    return {str(f) for f in (raw_flags or []) if str(f) not in ignored}


def reconcile_subtitle_flags(flags: Any, present_langs: Set[str]) -> List[str]:
    """Retire les flags 'subtitle_missing_<lang>' PÉRIMÉS dont la langue est en fait
    présente (embarquée/externe). Les autres flags sont conservés à l'identique.

    La langue extraite du flag est normalisée ISO 639-1 (via _normalize_iso639) pour
    matcher un `present_langs` déjà normalisé — robuste aux plans anciens qui portent
    'subtitle_missing_french' / 'subtitle_missing_fra' au lieu de 'subtitle_missing_fr'.
    La détection des langues présentes vit dans history_support._present_langs_from_payload
    (lecture du DICT payload) — source unique côté écran Traitement."""
    from cinesort.domain.subtitle_helpers import _normalize_iso639

    out: List[str] = []
    for flag in flags or []:
        text = str(flag)
        if text.startswith("subtitle_missing_"):
            raw = text[len("subtitle_missing_") :].strip().lower()
            lang = _normalize_iso639(raw) or raw
            if lang and lang in present_langs:
                continue  # faux positif : la langue EST présente -> drop
        out.append(text)
    return out


def build_qr_by_id(quality_reports: Any) -> Dict[str, Dict[str, Any]]:
    """Index quality_reports par row_id (miroir librarian.py:64-69)."""
    qr_by_id: Dict[str, Dict[str, Any]] = {}
    for qr in quality_reports or []:
        if not isinstance(qr, dict):
            continue
        rid = str(qr.get("row_id") or "")
        if rid:
            qr_by_id[rid] = qr
    return qr_by_id


def seed_auto_approve_decisions(
    api: Any, rows: List[Any], existing: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """[auto-approve] Overlay READ-TIME (ne PERSISTE RIEN) des décisions pour la
    Validation. Si `auto_approve_enabled`, pré-marque `decision=accepted`/`ok=True`
    pour chaque row SANS décision existante ET auto-approuvable (confiance ≥
    `auto_approve_threshold`). N'écrase JAMAIS une décision utilisateur existante.
    Le résultat est destiné à l'affichage (Étape Validation pré-remplie) ; il
    n'atteint le disque/apply QUE via un save_validation explicite de l'utilisateur.
    """
    try:
        settings = api._get_settings_impl()
    except Exception:  # noqa: BLE001 — best-effort : pas d'auto-approve si settings illisibles
        return existing if isinstance(existing, dict) else {}
    if not to_bool(settings.get("auto_approve_enabled"), False):
        return existing if isinstance(existing, dict) else {}
    threshold = to_int(settings.get("auto_approve_threshold"), 85)
    base: Dict[str, Dict[str, Any]] = dict(existing) if isinstance(existing, dict) else {}
    # Flags EFFECTIFS (bruts − alertes ignorées) : MÊME base que la carte "Auto-approuvables",
    # le KPI "Cas à vérifier" (dashboard) et la liste get_plan. Sinon la Validation ne pré-coche
    # PAS un film que TOUS les compteurs annoncent auto-approuvé (après un "Ignorer" sur une
    # alerte bloquante, à seuil < 85 où le fallback frontend conf≥85 ne masque plus l'écart).
    from cinesort.ui.api.library_support import _get_store

    _ignored = ignored_alerts_by_row(_get_store(api), [str(r.row_id) for r in rows])
    for row in rows:
        rid = str(row.row_id)
        if rid in base:
            continue  # décision existante (utilisateur / disque) → ne pas écraser
        _flags = effective_flags(row.warning_flags, _ignored.get(rid))
        if is_auto_approvable_flags(_flags, row.confidence, row.proposed_title, row.proposed_year, threshold):
            base[rid] = {
                "ok": True,
                "decision": "accepted",
                "title": row.proposed_title,
                "year": row.proposed_year,
            }
    return base


@requires_valid_run_id
def get_cleanup_residual_preview(api: Any, run_id: str) -> Dict[str, Any]:
    rs = api._get_run(run_id)
    if rs and not rs.done:
        return _err_response("Plan pas pret.", category="state", level="debug", log_module=__name__)

    found = api._find_run_row(run_id)
    if not rs and not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
    if found and not rs:
        row, _store = found
        status_text = str(row.get("status") or "")
        if status_text not in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
            return _err_response("Plan pas pret.", category="state", level="debug", log_module=__name__)

    # Fix audit 2026-05-24 : _run_context_for_apply peut lever FileNotFoundError
    # quand plan.jsonl est absent (run nettoye, FS desynchronise) -> 500 cote UI.
    # On capture les exceptions classiques d'acces fichiers/state pour renvoyer
    # un err_response propre (categorie state, niveau info).
    try:
        ctx = api._run_context_for_apply(run_id)
    except (OSError, FileNotFoundError, KeyError, TypeError, ValueError):
        return _err_response("Plan introuvable.", category="state", level="info", log_module=__name__)
    if not ctx:
        return _err_response("Plan indisponible.", category="state", level="info", log_module=__name__)

    cfg, _run_paths, rows, _log_fn, _store = ctx
    preview = _preview_cleanup_fn(cfg, api._touched_top_level_dirs_for_rows(cfg, rows))
    return {
        "ok": True,
        "run_id": run_id,
        "preview": preview,
    }


def resolve_media_path_for_row(
    api: Any,
    cfg: core.Config,
    row: core.PlanRow,
    *,
    env_truthy_fn: Any,
) -> Optional[Path]:
    folder = Path(str(row.folder or ""))
    if not folder.exists() or not folder.is_dir():
        return None

    video_name = str(row.video or "").strip()
    candidates: List[Path] = []
    if video_name:
        direct = folder / video_name
        candidates.append(direct)
        found_in_iterdir = False
        try:
            for path in folder.iterdir():
                if path.is_file() and path.name.lower() == video_name.lower():
                    candidates.append(path)
                    found_in_iterdir = True
        except (OSError, PermissionError, TypeError, ValueError) as exc:
            if env_truthy_fn("CINESORT_DEBUG"):
                api._debug_log(
                    state_dir=api._state_dir,
                    run_id=None,
                    enabled=True,
                    message=f"_resolve_media_path_for_row iterdir warning folder={folder}: {exc}",
                )
        # Audit 2026-05-14 : rglob recursif est lourd sur grosses arborescences NAS.
        # On ne descend dans les sous-dossiers que si iterdir n'a rien trouve.
        if not found_in_iterdir:
            try:
                for path in folder.rglob("*"):
                    if path.is_file() and path.name.lower() == video_name.lower():
                        candidates.append(path)
                        break
            except (OSError, PermissionError) as exc:
                if env_truthy_fn("CINESORT_DEBUG"):
                    api._debug_log(
                        state_dir=api._state_dir,
                        run_id=None,
                        enabled=True,
                        message=f"_resolve_media_path_for_row rglob warning folder={folder}: {exc}",
                    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    # LOTD-ITERVIDEOS-KWARG : min_video_bytes est keyword-only OBLIGATOIRE
    # (scan_helpers.iter_videos) — sans lui le fallback levait TypeError et
    # fuyait jusqu'au boundary de get_quality_report. Meme resolution du seuil
    # que les autres appelants (cfg.min_video_bytes sinon core.MIN_VIDEO_BYTES,
    # lu a l'appel car test_reset peut le patcher). TypeError/ValueError dans
    # l'except : un cfg.min_video_bytes non numerique doit degrader en
    # "media introuvable" (None), pas crasher.
    try:
        cfg_min = getattr(cfg, "min_video_bytes", None)
        min_bytes = int(cfg_min) if cfg_min is not None else core.MIN_VIDEO_BYTES
        videos = core.iter_videos(cfg, folder, min_video_bytes=min_bytes)
        if videos:
            return videos[0]
    except (OSError, PermissionError, TypeError, ValueError):
        return None
    return None


def touched_top_level_dirs_for_rows(
    cfg: core.Config,
    rows: List[core.PlanRow],
) -> Set[Path]:
    touched: Set[Path] = set()
    for row in rows:
        try:
            folder = Path(row.folder)
        except (OSError, PermissionError, ValueError):
            continue
        if folder.parent == cfg.root:
            touched.add(folder)
    return touched


@requires_valid_run_id
def get_auto_approved_summary(
    api: Any,
    run_id: str,
    threshold: Optional[int] = None,
    enabled: bool = False,
    quarantine_corrupted: bool = False,
) -> Dict[str, Any]:
    """Analyse rows for auto-approval: high confidence + no critical warnings.

    M-2 audit QA 20260429 : si quarantine_corrupted=True, les rows avec un
    warning d'integrite (integrity_header_invalid / integrity_probe_failed)
    sont auto-marquees pour quarantine et exclues de l'auto-approbation.
    Le frontend peut utiliser auto_quarantine_row_ids pour pre-cocher la
    decision "reject" sur ces films.
    """
    # [cohérence seuil] Si l'appelant ne fournit PAS de seuil (threshold=None, cas du frontend),
    # on lit le seuil AUTORITAIRE des settings (auto_approve_threshold), aligné sur
    # dashboard_support.review_queue_count. Sans ça, la carte "Auto-approuvables (≥N)" utilisait
    # le défaut 85 codé en dur pendant que "Cas à vérifier" utilisait le seuil settings ->
    # double-comptage des films dans [85, seuil) dès que le seuil réglé != 85. Un seuil
    # EXPLICITE (tests, appels ciblés) est respecté tel quel.
    if threshold is None:
        try:
            threshold = to_int(api._get_settings_impl().get("auto_approve_threshold"), 85)
        except Exception:  # noqa: BLE001 — best-effort
            threshold = 85
    rs = api._get_run(run_id)
    if not rs or not rs.done:
        return _err_response("Plan pas pret.", category="state", level="debug", log_module=__name__)
    rows = rs.rows if rs.rows else api._load_rows_from_plan_jsonl(rs.paths)
    if not rows:
        return {
            "ok": True,
            "auto_approved": 0,
            "manual_review": 0,
            "auto_quarantine": 0,
            "threshold": threshold,
            "enabled": enabled,
            "quarantine_corrupted": quarantine_corrupted,
        }

    auto_approved = 0
    manual_review = 0
    auto_quarantine = 0
    auto_row_ids: List[str] = []
    auto_quarantine_row_ids: List[str] = []

    # Flags EFFECTIFS (bruts − alertes ignorées) : cohérence avec le payload get_plan et le KPI
    # dashboard, sinon la carte "Auto-approuvables" et "Cas à vérifier" divergent de la liste
    # dès qu'une alerte bloquante est ignorée.
    from cinesort.ui.api.library_support import _get_store

    _ignored = ignored_alerts_by_row(_get_store(api), [str(r.row_id) for r in rows])
    for row in rows:
        flags = effective_flags(row.warning_flags, _ignored.get(str(row.row_id)))
        has_integrity_issue = bool(flags & _AUTO_INTEGRITY_WARNINGS)

        # M-2 : auto-quarantine prioritaire sur auto-approve
        if quarantine_corrupted and has_integrity_issue:
            auto_quarantine += 1
            auto_quarantine_row_ids.append(str(row.row_id))
            continue

        # Prédicat partagé avec le seed READ-TIME de la Validation (source unique).
        if enabled and is_auto_approvable_flags(
            flags, row.confidence, row.proposed_title, row.proposed_year, threshold
        ):
            auto_approved += 1
            auto_row_ids.append(str(row.row_id))
        else:
            manual_review += 1

    return {
        "ok": True,
        "auto_approved": auto_approved,
        "manual_review": manual_review,
        "auto_quarantine": auto_quarantine,
        "total": len(rows),
        "threshold": threshold,
        "enabled": enabled,
        "quarantine_corrupted": quarantine_corrupted,
        "auto_row_ids": auto_row_ids,
        "auto_quarantine_row_ids": auto_quarantine_row_ids,
    }
