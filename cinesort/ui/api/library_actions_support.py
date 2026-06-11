"""Phase 4 spec 07 + spec 06 — Actions Library (mark_for_deletion, rescan, export).

Endpoints :
    mark_single_for_deletion(row_id, run_id)    — single (spec 06 Modal Film) [renomme audit 2026-05-24]
    mark_for_deletion_bulk(row_ids, run_id)     — bulk (spec 07 Bibliotheque)
    rescan_row(run_id, row_id)                  — single (spec 06)
    rescan_rows_bulk(row_ids, run_id)           — bulk (spec 07)
    export_films(row_ids, format, run_id)       — CSV / JSON / NDJSON

Persistance :
- Les marqueurs de suppression sont stockes dans un fichier
  `deletion_marks.json` dans le run_dir (cote du `validation.json`).
  Format : {"row_ids": ["abc", "def"], "marked_ts": {"abc": 1234567.0}}.
- Les exports sont ecrits dans `%LOCALAPPDATA%/CineSort/exports/`.
- Les rescans sont lances via JobRunner (job background).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.app.merge_metadata import merge_metadata
from cinesort.domain.film_identity import compute_film_id, is_path_film_id
from cinesort.infra import state
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.library_support import _build_library_rows, _resolve_run_id
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers persistance "deletion_marks.json"
# ---------------------------------------------------------------------------


def _deletion_marks_path(api: Any, run_id: str) -> Optional[Path]:
    """Resout le chemin du fichier deletion_marks.json pour ce run."""
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=True)
        return run_paths.run_dir / "deletion_marks.json"
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("_deletion_marks_path failed run_id=%s: %s", run_id, exc)
        return None


def _read_deletion_marks(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"row_ids": [], "marked_ts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"row_ids": [], "marked_ts": {}}
        row_ids = list(data.get("row_ids") or [])
        marked_ts = dict(data.get("marked_ts") or {})
        return {"row_ids": [str(r) for r in row_ids], "marked_ts": marked_ts}
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.warning("_read_deletion_marks corrupted path=%s: %s", path, exc)
        return {"row_ids": [], "marked_ts": {}}


def _write_deletion_marks(path: Path, data: Dict[str, Any]) -> None:
    state.atomic_write_json(path, data)


def _persist_marks(api: Any, run_id: str, new_row_ids: List[str]) -> int:
    """Persiste les marqueurs. Retourne le nombre de rows nouvellement marques."""
    path = _deletion_marks_path(api, run_id)
    if path is None:
        raise RuntimeError("Impossible de resoudre le chemin de persistance.")
    current = _read_deletion_marks(path)
    existing = set(current["row_ids"])
    marked_ts: Dict[str, float] = current["marked_ts"]
    now = time.time()
    added = 0
    for rid in new_row_ids:
        rid_s = str(rid).strip()
        if not rid_s:
            continue
        if rid_s not in existing:
            existing.add(rid_s)
            added += 1
        marked_ts[rid_s] = now
    _write_deletion_marks(path, {"row_ids": sorted(existing), "marked_ts": marked_ts})
    return added


# ---------------------------------------------------------------------------
# Endpoint : mark_single_for_deletion (single) + mark_for_deletion_bulk (bulk)
# ---------------------------------------------------------------------------


# Fix audit 2026-05-24 : renomme `mark_for_deletion` -> `mark_single_for_deletion`
# pour eviter l'ambiguite avec `library_support.mark_for_deletion(api, run_id, row_id)`
# qui a une signature *inversee* (run_id, row_id) vs (row_id, run_id) ici.
def mark_single_for_deletion(
    api: Any,
    row_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Marque un seul film pour deplacement vers `_user_marked_for_deletion/` au prochain apply.

    Args:
        row_id: identifiant du film a marquer
        run_id: run cible (None = dernier run actif)

    Returns:
        {ok: bool, row_id: str, run_id: str} ou {ok: False, error: ...}
    """
    rid = str(row_id or "").strip()
    if not rid:
        return _err_response("row_id requis.", category="validation", level="info", log_module=__name__)
    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)
    try:
        _persist_marks(api, resolved, [rid])
        return {"ok": True, "row_id": rid, "run_id": resolved}
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def mark_for_deletion_bulk(
    api: Any,
    row_ids: List[str],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Version bulk de mark_for_deletion.

    Args:
        row_ids: liste des row_ids a marquer (peut etre vide)
        run_id: run cible (None = dernier run actif)

    Returns:
        {ok: bool, count: int, failed: list[str], run_id: str}
        - count : nombre de rows nouvellement ajoutees (deja marquees ne comptent pas)
        - failed : row_ids ignores (vides ou invalides)
    """
    if not isinstance(row_ids, list):
        return _err_response(
            "row_ids doit etre une liste.",
            category="validation",
            level="info",
            log_module=__name__,
        )
    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)

    valid: List[str] = []
    failed: List[str] = []
    for raw in row_ids:
        rid_s = str(raw or "").strip()
        if rid_s:
            valid.append(rid_s)
        else:
            failed.append(str(raw))

    try:
        count = _persist_marks(api, resolved, valid)
        return {
            "ok": True,
            "count": count,
            "failed": failed,
            "run_id": resolved,
            "total_requested": len(row_ids),
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# ---------------------------------------------------------------------------
# Endpoint : rescan_row (single, synchrone) + rescan_rows_bulk (JobRunner)
# ---------------------------------------------------------------------------


def _rescan_single_row_full_pipeline(api: Any, run_id: str, row_id: str) -> Dict[str, Any]:
    """Vraie implementation spec 06 §3.6 : probe + perceptual + TMDb re-match + plan update.

    Pipeline complet pour 1 row (synchrone, sans JobRunner) :
      1. Invalide quality_reports + perceptual_reports en DB (delegation
         a run_flow_support.rescan_row).
      2. Re-execute probe ffprobe + mediainfo via get_quality_report
         (force reuse_existing=False).
      3. Re-execute analyse perceptuelle LPIPS V2 via get_perceptual_report.
      4. Re-execute match TMDb (search_movie + scoring) via
         plan_support.replan_single_row sur le fichier video.
      5. Met a jour le plan.jsonl : remplace l'ancienne row par la nouvelle
         (avec nouveau score / confidence / proposed_title / candidates).
    """
    from cinesort.ui.api import run_flow_support  # noqa: PLC0415

    base_result = run_flow_support.rescan_row(api, run_id, row_id)
    if not isinstance(base_result, dict) or not base_result.get("ok"):
        return (
            base_result
            if isinstance(base_result, dict)
            else _err_response(
                "Echec rescan probe/perceptual.",
                category="runtime",
                level="error",
                log_module=__name__,
            )
        )

    tmdb_rematched = False
    candidates_count = 0
    new_row_json: Optional[Dict[str, Any]] = None
    try:
        new_row_json = _rematch_tmdb_and_update_plan(api, run_id, row_id)
        if new_row_json is not None:
            tmdb_rematched = True
            candidates_count = len(new_row_json.get("candidates") or [])
    except (OSError, AttributeError, KeyError, TypeError, ValueError, ImportError) as exc:
        logger.warning(
            "rescan_row: TMDb re-match failed (best-effort), row_id=%s run_id=%s: %s",
            row_id,
            run_id,
            exc,
        )

    return {
        "ok": True,
        "run_id": str(run_id),
        "row_id": str(row_id),
        "plan_row": new_row_json or base_result.get("plan_row"),
        "quality": base_result.get("quality") or {},
        "perceptual": base_result.get("perceptual") or {},
        "tmdb_rematched": tmdb_rematched,
        "candidates_count": candidates_count,
    }


def _get_field_locks_repo(api: Any):
    """Best-effort acces au FieldLocksRepository via le store.

    Retourne None si infra non dispo, ou si l'attribut field_locks n'existe
    pas (tests avec mocks legers). Toujours wrappe en try/except — un echec
    d'acces field_locks ne doit JAMAIS faire planter rescan/rematch.
    """
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_get_field_locks_repo: infra unavailable: %s", exc)
        return None
    return getattr(store, "field_locks", None)


def _list_locked_field_names(api: Any, film_id: str) -> List[str]:
    """Liste les noms de champs verrouilles pour film_id (vide si aucun)."""
    if not film_id:
        return []
    repo = _get_field_locks_repo(api)
    if repo is None:
        return []
    try:
        locks = repo.list_locks(film_id)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("list_locks failed film_id=%s: %s", film_id, exc)
        return []
    return [str(lk.get("field_name") or "") for lk in locks if lk.get("field_name")]


def _rematch_tmdb_and_update_plan(api: Any, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
    """Relance le match TMDb pour 1 row + persiste la nouvelle row dans plan.jsonl.

    Vague P / VP-C :
        - Consulte `field_locks` AVANT d'ecraser les champs de target.
        - Appelle `migrate_locks(old_film_id, new_film_id)` lors de la
          transition `path:<sha1>` -> `tmdb:<id>` (fix #5 ROADMAP_VAGUE_P).
    """
    try:
        # AUDIT 2026-06-10 : _internal_settings (secrets en clair) au lieu du
        # payload masque -> _build_tmdb_client_optional construisait sinon un
        # TmdbClient avec tmdb_api_key="••••••••" et tout re-match echouait 401.
        settings = api._internal_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_rematch_tmdb: run_paths_for failed: %s", exc)
        return None

    plan_jsonl = getattr(run_paths, "plan_jsonl", None)
    if plan_jsonl is None or not plan_jsonl.exists():
        return None

    all_rows: List[Dict[str, Any]] = []
    target_idx: Optional[int] = None
    with open(plan_jsonl, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            all_rows.append(data)
            if str(data.get("row_id") or "") == str(row_id):
                target_idx = len(all_rows) - 1

    if target_idx is None:
        return None

    target = all_rows[target_idx]
    folder_path = Path(str(target.get("folder") or ""))
    video_path = folder_path / str(target.get("video") or "")
    if not video_path.exists() or not folder_path.exists():
        logger.debug("_rematch_tmdb: video introuvable %s", video_path)
        return None

    cfg = _build_cfg_for_row(api, settings, root=folder_path)
    if cfg is None:
        return None
    tmdb = _build_tmdb_client_optional(settings, state_dir)

    from cinesort.app.plan_support import plan_row_to_jsonable, replan_single_row  # noqa: PLC0415

    kind = "collection" if str(target.get("kind") or "") == "collection" else "single"

    # AUDIT 2026-06-11 (R3e gap[3] + R4-P4) : passer la VRAIE racine du scan a
    # replan (cfg a root=folder_path, donc sans racine explicite folder_name
    # serait derive du stem fichier -> replan non idempotent). R4-P4 : en
    # multi-roots, runs.root ne stocke que roots[0] ; passer roots[0] pour un
    # film d'un root SECONDAIRE faussait folder_name (un film pose a la racine
    # de R2 heritait du nom du dossier R2 au lieu du stem). On choisit donc le
    # root qui CONTIENT reellement le film, sinon None (compat pre-R3e).
    # P4 v2 : la row porte source_root (le root EXACT du scan, core.py:424) —
    # candidat autoritaire teste en premier, avant les roots reconstruits de la DB.
    scan_root = _resolve_scan_root_for_replan(
        api, run_id, folder_path, priority_candidates=[target.get("source_root")]
    )

    new_row = replan_single_row(
        cfg, folder_path, video_path, tmdb=tmdb, kind=kind, library_root=scan_root
    )
    if new_row is None:
        return None

    new_row_json = plan_row_to_jsonable(new_row)
    new_row_json["row_id"] = str(row_id)

    # Vague P / VP-C : barriere merge_metadata + migrate_locks.
    # 1. Calcul des film_id ancien / nouveau.
    # 2. Si transition path: -> tmdb:, migrate_locks vers le nouveau id.
    # 3. Consulte les locks (nouveau id) et applique merge_metadata pour
    #    ne pas ecraser les champs verrouilles.
    try:
        old_film_id = compute_film_id(target)
        new_film_id = compute_film_id(new_row_json)
        if (
            old_film_id
            and new_film_id
            and old_film_id != new_film_id
            and is_path_film_id(old_film_id)
        ):
            repo = _get_field_locks_repo(api)
            if repo is not None:
                try:
                    migrated = repo.migrate_locks(old_film_id, new_film_id)
                    if migrated:
                        logger.info(
                            "field_locks migrate %s -> %s : %d lock(s)",
                            old_film_id,
                            new_film_id,
                            migrated,
                        )
                except (OSError, AttributeError, TypeError, ValueError) as exc:
                    logger.warning("migrate_locks failed: %s", exc)

        locked_names = _list_locked_field_names(api, new_film_id)
        if locked_names:
            # source = nouvelle row enrichie, target = ancienne row preservee
            new_row_json = merge_metadata(
                source=new_row_json,
                target=target,
                locked_fields=locked_names,
                replace_data=True,
            )
            new_row_json["row_id"] = str(row_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("field_locks integration failed (best-effort): %s", exc)

    all_rows[target_idx] = new_row_json
    tmp_path = plan_jsonl.with_suffix(plan_jsonl.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fp:
        for r in all_rows:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp_path.replace(plan_jsonl)

    if tmdb is not None:
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(AttributeError, OSError):
            tmdb.flush()

    return new_row_json


def _resolve_scan_root_for_replan(
    api: Any,
    run_id: str,
    folder_path: Path,
    *,
    priority_candidates: Optional[List[Any]] = None,
) -> Optional[Path]:
    """Retourne la racine du scan qui CONTIENT folder_path, ou None.

    AUDIT 2026-06-11 (R4-P4) : runs.root ne stocke que roots[0] (compat). Les
    roots complets d'un scan multi-roots sont dans runs.config_json ('roots',
    fallback 'root'/'library_path'). Un candidat n'est retenu que s'il est
    folder_path lui-meme ou un de ses ancetres : passer un root etranger a
    replan_single_row fausserait _folder_is_root (un film pose a la racine d'un
    root secondaire perdrait son stem). None = compat pre-R3e (cfg.root==folder).

    Revue adversaire R4 (P4 v2) :
    - `priority_candidates` (ex: PlanRow.source_root, le root AUTORITATIF du
      scan porte par la row) sont testes en premier, ordre fourni.
    - Parmi les candidats DB, le PLUS PROFOND gagne : avec des roots imbriques
      (Films + Films/Films4K, config seulement warnee par validate_roots), le
      premier-match retournait Films pour un film de Films4K -> folder_name
      contamine, la classe de bug que ce helper doit eliminer.
    - Les candidats sont normalises (strip/quotes, expandvars, expanduser)
      avant resolve : config_json persiste les roots BRUTS pre-normalisation.
    """

    def _norm(raw: Any) -> Optional[Path]:
        text = str(raw or "").strip().strip('"').strip()
        if not text:
            return None
        try:
            return Path(os.path.expandvars(text)).expanduser().resolve()
        except (OSError, ValueError):
            return None

    try:
        folder_res = folder_path.resolve()
    except (OSError, ValueError):
        folder_res = folder_path

    def _contains(cand: Path) -> bool:
        return cand == folder_res or cand in folder_res.parents

    for raw in priority_candidates or []:
        cand_p = _norm(raw)
        if cand_p is not None and _contains(cand_p):
            return cand_p

    try:
        found = api._find_run_row(run_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return None
    if not found:
        return None
    row = found[0]

    candidates: List[str] = []
    root_str = str(row.get("root") or "").strip()
    if root_str:
        candidates.append(root_str)
    cfg_raw = row.get("config_json")
    try:
        cfg = json.loads(cfg_raw) if isinstance(cfg_raw, str) and cfg_raw.strip() else cfg_raw
    except (TypeError, ValueError, json.JSONDecodeError):
        cfg = None
    if isinstance(cfg, dict):
        roots_raw = cfg.get("roots")
        if isinstance(roots_raw, list):
            candidates.extend(str(r) for r in roots_raw if str(r or "").strip())
        for key in ("root", "library_path"):
            val = str(cfg.get(key) or "").strip()
            if val:
                candidates.append(val)

    best: Optional[Path] = None
    for cand in candidates:
        cand_p = _norm(cand)
        if cand_p is None or not _contains(cand_p):
            continue
        if best is None or len(cand_p.parts) > len(best.parts):
            best = cand_p
    return best


def _build_cfg_for_row(api: Any, settings: Dict[str, Any], *, root: Path):
    """Construit un core.Config minimal pour re-executer _plan_item sur 1 row."""
    try:
        if hasattr(api, "_build_cfg_from_settings"):
            return api._build_cfg_from_settings(settings, root)
        from cinesort.ui.api.settings_support import build_cfg_from_settings  # noqa: PLC0415

        return build_cfg_from_settings(
            settings,
            root=root,
            default_collection_folder_name="_collections",
            default_empty_folders_folder_name="_empty",
            default_residual_cleanup_folder_name="_residuals",
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_build_cfg_for_row failed: %s", exc)
        return None


def _build_tmdb_client_optional(settings: Dict[str, Any], state_dir: Path):
    """Construit un TmdbClient si une cle est configuree, sinon None."""
    api_key = str(settings.get("tmdb_api_key") or "").strip()
    if not api_key:
        return None
    try:
        from cinesort.infra.tmdb_client import TmdbClient  # noqa: PLC0415

        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        return TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )
    except (ImportError, OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("TmdbClient build failed (best-effort): %s", exc)
        return None


def _build_rescan_job_fn(api: Any, run_id: str, row_ids: List[str]):
    """Build un job_fn compatible JobRunner pour rescanner N rows via le vrai pipeline.

    VN-E.3 : accepte `should_pause` (kwarg optionnel) injecte par le JobRunner.
    La cancellation prevaut sur la pause.
    """

    def job_fn(should_cancel, should_pause=None) -> Dict[str, Any]:
        import time as _time

        processed = 0
        skipped = 0
        for rid in row_ids:
            # VN-E.3 : pause cooperative AVANT cancel check.
            if should_pause is not None:
                try:
                    while bool(should_pause()):
                        if should_cancel():
                            break
                        _time.sleep(0.5)
                except Exception:  # noqa: BLE001
                    pass
            if should_cancel():
                break
            try:
                res = _rescan_single_row_full_pipeline(api, run_id, rid)
                if isinstance(res, dict) and res.get("ok"):
                    processed += 1
                else:
                    skipped += 1
            except (OSError, AttributeError, TypeError, ValueError, ImportError) as exc:
                logger.warning("rescan failed row_id=%s: %s", rid, exc)
                skipped += 1
        return {
            "ok": True,
            "rescan": {
                "run_id": run_id,
                "processed": processed,
                "skipped": skipped,
                "requested": len(row_ids),
            },
        }

    return job_fn


def rescan_rows_bulk(
    api: Any,
    row_ids: List[str],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Lance un job background pour relancer probe + analyse + match TMDb sur N rows.

    Returns:
        {ok: bool, job_id: str, count: int, run_id: str}
    """
    if not isinstance(row_ids, list):
        return _err_response(
            "row_ids doit etre une liste.",
            category="validation",
            level="info",
            log_module=__name__,
        )
    valid = [str(r).strip() for r in row_ids if str(r or "").strip()]
    if not valid:
        return _err_response("Aucun row_id valide.", category="validation", level="info", log_module=__name__)

    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)

    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        _store, runner = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    if runner is None:
        return _err_response("JobRunner indisponible.", category="state", level="warning", log_module=__name__)

    job_fn = _build_rescan_job_fn(api, resolved, valid)
    try:
        job_id = runner.start_job(
            job_fn=job_fn,
            root=str(state_dir),  # placeholder : rescan ne touche pas a la racine du scan
            state_dir=str(state_dir),
            config={"rescan_run_id": resolved, "rescan_row_ids": valid},
        )
    except RuntimeError as exc:
        # Un autre run est en cours
        return _err_response(str(exc), category="state", level="info", log_module=__name__)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    return {
        "ok": True,
        "job_id": job_id,
        "count": len(valid),
        "run_id": resolved,
    }


def rescan_row(
    api: Any,
    row_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Spec 06 §3.6 : relance probe + analyse + match TMDb pour 1 row (synchrone).

    Contrairement a rescan_rows_bulk (JobRunner background pour N rows), cette
    version synchrone est adaptee au Modal Film : l'utilisateur clique
    "Re-scanner ce fichier" et attend le resultat.

    Pipeline : invalide caches -> probe ffprobe/mediainfo -> analyse LPIPS V2
    -> re-match TMDb -> mise a jour plan.jsonl.
    """
    rid = str(row_id or "").strip()
    if not rid:
        return _err_response("row_id requis.", category="validation", level="info", log_module=__name__)
    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)
    try:
        return _rescan_single_row_full_pipeline(api, resolved, rid)
    except (OSError, AttributeError, KeyError, TypeError, ValueError, ImportError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# ---------------------------------------------------------------------------
# Endpoint : export_films (CSV / JSON)
# ---------------------------------------------------------------------------


_EXPORT_FIELDS = (
    "row_id",
    "title",
    "year",
    "score_v2",
    "tier_v2",
    "path",
    "size_bytes",
    "duration_min",
    "codec",
    "resolution",
    "audio_languages",
    "subtitle_languages",
    "warnings",
)


def _exports_dir() -> Path:
    """Repertoire des exports : `%LOCALAPPDATA%/CineSort/exports/`."""
    base = state.default_state_dir() / "exports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _row_to_export_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Filtre une row Library aux champs d'export selon spec 07."""
    return {
        "row_id": row.get("row_id"),
        "title": row.get("title"),
        "year": row.get("year"),
        "score_v2": row.get("score_v2"),
        "tier": row.get("tier_v2"),
        "path": row.get("path"),
        "size_bytes": row.get("size_bytes"),
        "duration_min": row.get("duration_min"),
        "codec": row.get("codec"),
        "resolution": row.get("resolution"),
        "audio_langs": list(row.get("audio_languages") or []),
        "subs_langs": list(row.get("subtitle_languages") or []),
        "warnings": list(row.get("warnings") or []),
    }


def _serialize_for_csv(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def export_films(
    api: Any,
    row_ids: List[str],
    fmt: str = "csv",
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Export CSV / JSON / NDJSON des films selectionnes (spec 07 - 07.4.4).

    Args:
        row_ids: row_ids a exporter. Si vide, exporte tous les films du run.
        fmt: "csv" | "json" | "ndjson"
        run_id: run cible (None = dernier)

    Returns:
        - format csv    : {ok, file_path, count, format}
        - format json   : {ok, file_path, films: [...], count, format}
        - format ndjson : {ok, file_path, count, format} (1 ligne JSON par film,
          adapte aux gros exports streamables)
    """
    fmt_norm = str(fmt or "csv").strip().lower()
    if fmt_norm not in ("csv", "json", "ndjson"):
        return _err_response(f"Format inconnu: {fmt}", category="validation", level="info", log_module=__name__)
    if not isinstance(row_ids, list):
        return _err_response(
            "row_ids doit etre une liste.",
            category="validation",
            level="info",
            log_module=__name__,
        )

    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)

    try:
        all_rows = _build_library_rows(api, resolved)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    if row_ids:
        wanted = {str(r).strip() for r in row_ids if str(r or "").strip()}
        selected = [r for r in all_rows if str(r.get("row_id") or "") in wanted]
    else:
        selected = list(all_rows)

    export_rows = [_row_to_export_dict(r) for r in selected]
    count = len(export_rows)

    try:
        exports_dir = _exports_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"library_export_{resolved}_{ts}.{fmt_norm}"
        file_path = exports_dir / fname

        if fmt_norm == "csv":
            with open(file_path, "w", encoding="utf-8", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(
                    [
                        "row_id",
                        "title",
                        "year",
                        "score_v2",
                        "tier",
                        "path",
                        "size_bytes",
                        "duration_min",
                        "codec",
                        "resolution",
                        "audio_langs",
                        "subs_langs",
                        "warnings",
                    ]
                )
                for row in export_rows:
                    writer.writerow(
                        [
                            _serialize_for_csv(row.get(k))
                            for k in [
                                "row_id",
                                "title",
                                "year",
                                "score_v2",
                                "tier",
                                "path",
                                "size_bytes",
                                "duration_min",
                                "codec",
                                "resolution",
                                "audio_langs",
                                "subs_langs",
                                "warnings",
                            ]
                        ]
                    )
            return {
                "ok": True,
                "file_path": str(file_path),
                "count": count,
                "format": "csv",
                "run_id": resolved,
            }

        if fmt_norm == "json":
            # JSON : ecrire le fichier ET retourner les films dans la reponse
            state.atomic_write_json(
                file_path,
                {
                    "run_id": resolved,
                    "exported_ts": time.time(),
                    "count": count,
                    "films": export_rows,
                },
            )
            return {
                "ok": True,
                "file_path": str(file_path),
                "films": export_rows,
                "count": count,
                "format": "json",
                "run_id": resolved,
            }

        # NDJSON : 1 ligne JSON par film (newline-delimited JSON), streamable.
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as fp:
            for row in export_rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(file_path)
        return {
            "ok": True,
            "file_path": str(file_path),
            "count": count,
            "format": "ndjson",
            "run_id": resolved,
        }
    except (OSError, PermissionError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
