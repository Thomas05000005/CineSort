"""Phase 4 spec 07 + spec 06 — Actions Library (mark_for_deletion, rescan, export).

Endpoints :
    mark_single_for_deletion(row_id, run_id)    — single (spec 06 Modal Film) [renomme audit 2026-05-24]
    mark_for_deletion_bulk(row_ids, run_id)     — bulk (spec 07 Bibliotheque)
    rescan_row(run_id, row_id)                  — single (spec 06)
    rescan_rows_bulk(row_ids, run_id)           — bulk (spec 07)
    export_films(row_ids, format, run_id)       — CSV / JSON / NDJSON

Persistance :
- Les marqueurs de suppression sont stockes dans la table DB
  `film_marked_for_deletion` (store film_modal) — STORE UNIQUE depuis l'audit
  2026-07-13 (HIGH-18). L'ancien fichier `deletion_marks.json` (purement
  additif, aucun chemin d'annulation) n'est plus ecrit : les marques deja sur
  disque sont migrees a la lecture (migrate_legacy_deletion_marks) puis le
  fichier est supprime.
- Les exports sont ecrits dans `<state_dir>/exports/` — le `state_dir` des
  settings, pas le dossier par defaut (issue #522). Sans `state_dir` configure,
  cela reste `%LOCALAPPDATA%/CineSort/exports/`.
- Les rescans sont lances via JobRunner (job background).
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.app.merge_metadata import merge_metadata
from cinesort.domain.conversions import to_bool as _to_bool
from cinesort.domain.film_identity import compute_film_id, is_path_film_id
from cinesort.infra import state
from cinesort.ui.api import run_data_support, run_flow_support
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.library_support import _build_library_rows, _resolve_run_id
from cinesort.ui.api.settings_support import build_cfg_from_settings, normalize_user_path

logger = logging.getLogger(__name__)


# Revue adversaire 2026-07-13 (defaut 3) : `sqlite3.Error` N'HERITE PAS d'OSError.
# Les helpers de marquage ci-dessous sont des filets "best-effort, sans perte" —
# une sqlite3.OperationalError("database is locked") ne doit donc pas les
# traverser et faire planter l'apply / la vue Bibliotheque / unmark. Meme tuple
# que library_support._get_store (RuntimeError = rollback migration a l'init).
_DB_ERRORS = (
    OSError,
    AttributeError,
    KeyError,
    RuntimeError,
    TypeError,
    ValueError,
    sqlite3.Error,
)


# ---------------------------------------------------------------------------
# Helpers persistance "deletion_marks.json"
# ---------------------------------------------------------------------------


def _deletion_marks_path(api: Any, run_id: str) -> Optional[Path]:
    """Resout le chemin du fichier deletion_marks.json (legacy) pour ce run.

    Revue adversaire 2026-07-13 (defaut 6) : `ensure_exists=False` — ce helper
    n'est plus appele que par des chemins de LECTURE/drain (vue Bibliotheque,
    apply, unmark). Avec ensure_exists=True, le simple affichage de la
    Bibliotheque RECREAIT `runs/tri_films_<id>/` pour un run purge du disque
    (dossiers fantomes a chaque rendu).
    """
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        return run_paths.run_dir / "deletion_marks.json"
    except _DB_ERRORS as exc:
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


def _film_modal_repo(api: Any) -> Any:
    """Repo DB `film_modal` (table film_marked_for_deletion), ou None si indispo."""
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)
    except _DB_ERRORS as exc:
        logger.warning("_film_modal_repo: infra indisponible: %s", exc)
        return None
    return getattr(store, "film_modal", None)


# SQL identique a FilmModalRepository.mark_for_deletion (meme UPSERT idempotent).
# Duplique ici uniquement pour pouvoir marquer N films en UNE transaction : le
# repo n'expose pas (encore) de variante bulk, et l'appel unitaire ouvre une
# connexion + _ensure_tables PAR FILM (revue adversaire 2026-07-13, defaut 2 :
# 9,6 s pour 500 films sur un endpoint synchrone -> UI gelee).
_MARK_FOR_DELETION_SQL = """
INSERT INTO film_marked_for_deletion(run_id, row_id, marked_at, source_path)
VALUES (?, ?, ?, ?)
ON CONFLICT(run_id, row_id) DO UPDATE SET
    marked_at=excluded.marked_at,
    source_path=excluded.source_path
"""


def _mark_many(
    repo: Any,
    run_id: str,
    row_ids: List[str],
    source_paths: Dict[str, str],
) -> List[str]:
    """Marque N rows dans la table film_marked_for_deletion (une transaction).

    Returns:
        Les row_ids EN ECHEC ([] si tout est passe). Ne leve jamais.
    """
    rids = [str(r) for r in row_ids]
    if not rids:
        return []

    ensure = getattr(repo, "_ensure_tables", None)
    managed = getattr(repo, "_managed_conn", None)
    if callable(ensure) and callable(managed):
        ts = time.time()
        params = [(str(run_id), rid, ts, str(source_paths.get(rid, "") or "")) for rid in rids]
        try:
            ensure()
            with managed() as conn:
                conn.executemany(_MARK_FOR_DELETION_SQL, params)
            return []
        except _DB_ERRORS as exc:
            logger.warning(
                "mark_for_deletion batch echoue run_id=%s (%d row(s)): %s — fallback unitaire",
                run_id,
                len(rids),
                exc,
            )

    # Fallback : repo sans helpers de connexion (stubs de test) ou batch en echec.
    failed: List[str] = []
    for rid_s in rids:
        try:
            repo.mark_for_deletion(
                run_id=str(run_id),
                row_id=rid_s,
                source_path=str(source_paths.get(rid_s, "") or ""),
            )
        except _DB_ERRORS as exc:
            logger.warning("mark_for_deletion echoue row_id=%s run_id=%s: %s", rid_s, run_id, exc)
            failed.append(rid_s)
    return failed


def _plan_source_paths(api: Any, run_id: str) -> Optional[Dict[str, str]]:
    """Map row_id -> source_path (fallback folder) pour ce run.

    None si le plan est illisible (on ne veut pas invalider un marquage pour
    autant : cf _mark_rows_for_deletion).
    """
    try:
        plan = api.run.get_plan(run_id)
    except _DB_ERRORS as exc:
        logger.warning("_plan_source_paths: get_plan echoue run_id=%s: %s", run_id, exc)
        return None
    if not isinstance(plan, dict) or not plan.get("ok"):
        return None
    rows = plan.get("rows")
    if not isinstance(rows, list):
        return None
    out: Dict[str, str] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid_s = str(r.get("row_id") or "").strip()
        if rid_s:
            out[rid_s] = str(r.get("source_path") or r.get("folder") or "")
    return out


def migrate_legacy_deletion_marks(api: Any, run_id: str) -> List[str]:
    """AUDIT 2026-07-13 (HIGH-18) : migration a la lecture de deletion_marks.json.

    Historiquement le marquage bulk ecrivait dans `deletion_marks.json` (store
    purement ADDITIF, sans aucun chemin de retrait) tandis que le modal Film
    ecrivait dans la table DB `film_marked_for_deletion` — seule celle-ci sait
    annuler (unmark_for_deletion) et alimente le flag UI is_marked_for_deletion.
    L'apply lisait l'UNION : un marquage bulk etait donc IRREVOCABLE et INVISIBLE.

    On unifie sur le store DB. Cette fonction reverse les marques legacy encore
    presentes sur disque dans la DB, puis supprime le fichier (une seule fois).

    Best-effort et sans perte : si la DB est indisponible ou l'insertion echoue,
    le fichier est CONSERVE et ses row_ids restent retournes (l'apply continue
    de les honorer, comportement d'avant le fix).

    Returns:
        Les row_ids concernes (migres lors de cet appel, ou restes en attente).
    """
    path = _deletion_marks_path(api, run_id)
    if path is None:
        return []
    try:
        if not path.exists():
            return []
    except (OSError, AttributeError, TypeError, ValueError):
        return []

    row_ids = [str(r) for r in (_read_deletion_marks(path).get("row_ids") or []) if str(r).strip()]
    if not row_ids:
        # Fichier vide/corrompu : plus rien a honorer, on le retire.
        with contextlib.suppress(OSError, TypeError, ValueError):
            path.unlink(missing_ok=True)
        return []

    repo = _film_modal_repo(api)
    if repo is None:
        # Store DB indisponible : on ne perd rien, le JSON reste la source.
        return row_ids

    source_paths = _plan_source_paths(api, run_id) or {}
    failed = _mark_many(repo, run_id, row_ids, source_paths)
    if failed:
        logger.warning(
            "migrate_legacy_deletion_marks: insertion DB echouee run_id=%s (%d/%d) — JSON conserve",
            run_id,
            len(failed),
            len(row_ids),
        )
        return row_ids

    with contextlib.suppress(OSError, TypeError, ValueError):
        path.unlink(missing_ok=True)
    logger.info(
        "deletion_marks.json migre vers film_marked_for_deletion run_id=%s (%d marque(s))",
        run_id,
        len(row_ids),
    )
    return row_ids


def remove_legacy_deletion_mark(api: Any, run_id: str, row_id: str) -> bool:
    """Retire un row_id de `deletion_marks.json` (legacy). Filet pour unmark.

    Revue adversaire R3 2026-07-13 (defaut 4) : `migrate_legacy_deletion_marks`
    CONSERVE volontairement le JSON quand le drain vers la DB echoue (DB
    verrouillee/indisponible) — et l'apply honore alors ses row_ids
    (apply_support.py:1584, union DB + legacy). Or `unmark_for_deletion` jetait
    le retour du drain : le DELETE en DB ne trouvait rien (la marque n'y avait
    jamais ete inseree), l'endpoint repondait quand meme ok:True, l'UI affichait
    "demarque"... et le film repartait au bucket au prochain apply.

    On retire donc explicitement le row_id du store legacy. Ne leve jamais.

    Returns:
        True si le row_id n'est PLUS marque cote legacy (retire, ou deja absent,
        ou fichier inexistant — cas nominal ou le drain a reussi).
        False si le retrait a echoue : le film est TOUJOURS marque, l'appelant ne
        doit PAS pretendre que le demarquage a reussi.
    """
    path = _deletion_marks_path(api, run_id)
    if path is None:
        # Chemin non resolvable : on ne peut ni lire ni prouver l'absence de marque.
        return False
    try:
        if not path.exists():
            return True  # drain nominal : le JSON a deja ete supprime.
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("remove_legacy_deletion_mark: acces impossible run_id=%s: %s", run_id, exc)
        return False

    data = _read_deletion_marks(path)
    rid_s = str(row_id)
    row_ids = [str(r) for r in (data.get("row_ids") or [])]
    if rid_s not in row_ids:
        return True

    remaining = [r for r in row_ids if r != rid_s]
    marked_ts = {str(k): v for k, v in (data.get("marked_ts") or {}).items() if str(k) != rid_s}
    try:
        if remaining:
            path.write_text(
                json.dumps({"row_ids": remaining, "marked_ts": marked_ts}, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            path.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning(
            "remove_legacy_deletion_mark: ecriture echouee run_id=%s row_id=%s: %s",
            run_id,
            rid_s,
            exc,
        )
        return False
    logger.info("deletion_marks.json : marque legacy retiree run_id=%s row_id=%s", run_id, rid_s)
    return True


def _mark_rows_for_deletion(api: Any, run_id: str, row_ids: List[str]) -> Dict[str, Any]:
    """Marque des rows dans le SEUL store de verite (table film_marked_for_deletion).

    AUDIT 2026-07-13 (HIGH-18) : le bulk ecrivait dans deletion_marks.json, que
    ni `unmark_for_deletion` ni le flag `is_marked_for_deletion` ne consultent ->
    marquage de masse irrevocable. On passe par le meme store que le modal, donc
    annulable film par film.

    Revue adversaire 2026-07-13 (defaut 2) : 2 appels repo PAR FILM (chacun sa
    connexion + _ensure_tables) = 9,6 s pour 500 films sur un endpoint
    SYNCHRONE. On lit l'etat existant en UNE requete puis on insere en UNE
    transaction (cf _mark_many).

    Returns:
        {"count": int (rows nouvellement marquees), "failed": [row_id, ...]}
    """
    migrate_legacy_deletion_marks(api, run_id)

    repo = _film_modal_repo(api)
    if repo is None:
        raise RuntimeError("Store SQLite indisponible.")

    source_paths = _plan_source_paths(api, run_id)
    todo: List[str] = []
    failed: List[str] = []
    seen: set = set()
    for rid_s in row_ids:
        # Le plan fait foi quand il est lisible : ne jamais marquer (operation
        # destructive) un row_id qui n'existe pas dans le run.
        if source_paths is not None and rid_s not in source_paths:
            failed.append(rid_s)
            continue
        if rid_s in seen:
            continue
        seen.add(rid_s)
        todo.append(rid_s)
    if not todo:
        return {"count": 0, "failed": failed}

    try:
        already = {str(m.get("row_id") or "") for m in (repo.list_marked_for_deletion(run_id=str(run_id)) or [])}
    except _DB_ERRORS as exc:
        logger.warning("list_marked_for_deletion echoue run_id=%s: %s", run_id, exc)
        already = set()

    batch_failed = set(_mark_many(repo, run_id, todo, source_paths or {}))
    count = sum(1 for rid_s in todo if rid_s not in already and rid_s not in batch_failed)
    failed.extend(rid_s for rid_s in todo if rid_s in batch_failed)
    return {"count": count, "failed": failed}


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
        res = _mark_rows_for_deletion(api, resolved, [rid])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
    if res["failed"]:
        return _err_response(
            f"Film introuvable ou non marquable (row_id={rid}).",
            category="resource",
            level="info",
            log_module=__name__,
        )
    return {"ok": True, "row_id": rid, "run_id": resolved}


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
        res = _mark_rows_for_deletion(api, resolved, valid)
        return {
            "ok": True,
            "count": res["count"],
            "failed": failed + res["failed"],
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


def _locked_field_names_for_rematch(api: Any, target_film_id: str, new_film_id: str) -> List[str]:
    """Noms verrouilles a honorer au re-match, sous LES DEUX identites du film.

    Chercher sous la seule identite derivee de la NOUVELLE row rendait les
    verrous invisibles des qu'un id TMDb etait connu.

    `new_film_id` vient de `compute_film_id(plan_row_to_jsonable(PlanRow))`, donc
    de `asdict(PlanRow)` — et le dataclass `PlanRow` NE PORTE AUCUN champ
    `tmdb_id` (31 champs : `tmdb_collection_id`, `tv_tmdb_series_id`, jamais
    `tmdb_id`). `compute_film_id` n'y trouve jamais d'id TMDb et rend donc
    invariablement `path:<sha1(folder|video)>`.

    L'identite issue de `target` (la row persistee), elle, peut etre un
    `tmdb:<id>` : `enrich_tmdb_ids_by_title` ecrit `row["tmdb_id"]` dans
    plan.jsonl (tmdb_support.py:262 puis `write_plan_jsonl`) depuis le thread
    `tmdb-enrich-<run_id>` de fin de scan, et `set_film_tmdb_candidate` migre
    explicitement les verrous vers `tmdb:<id>` (library_support.py:1978).

    Les deux bouts ne se rencontraient jamais : verrous ranges sous `tmdb:<id>`,
    re-match les cherchant sous `path:<sha1>` -> zero nom verrouille ->
    `merge_metadata(replace_data=True)` ecrasait TOUT, titre corrige a la main
    compris. Le verrou etait inoperant pour tout film dont l'id TMDb est connu —
    c'est-a-dire precisement ceux qu'un re-match modifie.

    L'UNION est deliberee, plutot que « prendre l'identite de target » : elle ne
    peut qu'AJOUTER de la protection, jamais en retirer, et elle couvre les deux
    sens de la transition `path:` <-> `tmdb:` sans dependre de l'ordre des
    operations de l'utilisateur. La seconde lecture n'a lieu que si les deux
    identites different, donc jamais sur un film sans id TMDb.

    Cf tests/test_field_locks_id_du_rescan.py.
    """
    noms = _list_locked_field_names(api, new_film_id)
    if target_film_id and target_film_id != new_film_id:
        noms = list(dict.fromkeys(noms + _list_locked_field_names(api, target_film_id)))
    return noms


def _scan_subtitle_expected_languages(settings: Dict[str, Any]) -> Optional[List[str]]:
    """Langues de sous-titres attendues, DERIVEES COMME AU SCAN.

    Meme regle que run_flow_support (job_fn) : None = detection desactivee
    (replan laisse alors les champs subtitle_* a leur valeur par defaut), sinon
    la liste normalisee (eventuellement vide).
    """
    if not _to_bool(settings.get("subtitle_detection_enabled"), True):
        return None
    raw_langs = settings.get("subtitle_expected_languages")
    if isinstance(raw_langs, list):
        return [str(lang).strip().lower() for lang in raw_langs if str(lang).strip()]
    if isinstance(raw_langs, str) and raw_langs.strip():
        return [lang.strip().lower() for lang in raw_langs.split(",") if lang.strip()]
    return []


# Champs poses par le SCAN a l'echelle du run, que `replan_single_row` (qui ne
# voit qu'un fichier video isole) ne recalcule JAMAIS.
#   - source_root : annote par plan_support_dedup.plan_multi_roots (l.864), pas
#     par _plan_item. Une row replanifiee repartait donc avec source_root=None.
_SCAN_ONLY_FIELDS = ("source_root",)

# Kinds que `replan_single_row` sait reellement reproduire SANS PERTE (elle appelle
# `_plan_item`, et renormalise en "single" tout kind hors de cet ensemble — cf.
# plan_support_replan.py:875). Liste BLANCHE volontaire : tout autre kind
# ("extra" = bonus d'un dossier partage, "tv_episode", ou un kind futur) doit
# etre REFUSE au replan, jamais renormalise (cf. _rematch_tmdb_and_update_plan).
_REPLANNABLE_KINDS = frozenset({"single", "collection"})

# Idem pour les warning_flags poses APRES `_plan_item`, a une echelle que le
# replan (1 fichier video, hors contexte) ne peut pas reconstruire :
#   - root_level_source     : plan_support_core.py:739 (badge UI "Depuis la racine"),
#                             pose selon la position du dossier dans le scan.
#   - bonus_video           : plan_support_core.py:777, pose selon les AUTRES videos
#                             du dossier (detection "collection + bonus").
#   - duplicate_cross_root  : plan_support_dedup.py:783, pose selon les autres ROOTS.
# Un rescan les EFFACAIT (badges UI perdus, doublon cross-root redevenu invisible).
_SCAN_ONLY_WARNING_FLAGS = ("root_level_source", "bonus_video", "duplicate_cross_root")

# Fragment de notes ajoute par _detect_cross_root_duplicates (plan_support_dedup.py:786) :
# `row.notes += " | Aussi dans: <root1>, <root2>"`. Non reconstructible par le replan.
_CROSS_ROOT_NOTE_PREFIX = "Aussi dans:"


def _carry_over_scan_only_fields(target: Dict[str, Any], new_row_json: Dict[str, Any]) -> None:
    """Reporte sur la row replanifiee les champs que le replan ne recalcule pas.

    Revue adversaire 2026-07-13 (defaut 1, REGRESSION DESTRUCTIVE multi-root) :
    l'apply groupe les rows par racine avec
    `rk = getattr(row, "source_root", None) or str(cfg.root)`
    (apply_support.py:1602) et cfg.root ne contient que roots[0]. Avec le resync
    memoire (HIGH-17), un `source_root: null` ecrit par le rescan n'est plus
    seulement cosmetique dans plan.jsonl : il est recharge en memoire, donc un
    film du ROOT2 rescanne serait applique sous ROOT1 — DEPLACE DANS LA MAUVAISE
    RACINE. On restaure donc ces champs depuis la row d'origine.

    Revue adversaire R3 2026-07-13 (defaut 2, EFFACEMENT DE DONNEES) : idem pour
    les warning_flags/notes poses par le scan APRES `_plan_item`
    (root_level_source, bonus_video, duplicate_cross_root + note "Aussi dans:").
    Le replan ne voit qu'un fichier isole : il ne peut ni les recalculer, ni
    savoir qu'ils existaient -> un simple rescan les supprimait.
    """
    for field_name in _SCAN_ONLY_FIELDS:
        if not new_row_json.get(field_name) and target.get(field_name):
            new_row_json[field_name] = target[field_name]

    old_flags = [str(f) for f in (target.get("warning_flags") or [])]
    raw_new_flags = new_row_json.get("warning_flags")
    new_flags = [str(f) for f in raw_new_flags] if isinstance(raw_new_flags, list) else []
    carried = [f for f in _SCAN_ONLY_WARNING_FLAGS if f in old_flags and f not in new_flags]
    if carried:
        new_row_json["warning_flags"] = new_flags + carried
    elif isinstance(raw_new_flags, list):
        new_row_json["warning_flags"] = new_flags

    # La note "| Aussi dans: <root>" accompagne duplicate_cross_root : sans elle,
    # le badge doublon ne dit plus OU se trouve l'autre copie.
    if "duplicate_cross_root" not in carried:
        return
    new_notes = str(new_row_json.get("notes") or "").strip()
    for segment in str(target.get("notes") or "").split("|"):
        segment = segment.strip()
        if segment.startswith(_CROSS_ROOT_NOTE_PREFIX) and segment not in new_notes:
            new_notes = f"{new_notes} | {segment}" if new_notes else segment
    if new_notes:
        new_row_json["notes"] = new_notes


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

    # Revue adversaire 2026-07-13 (defaut 1) : replan_single_row ne sait produire
    # que des rows FILM (_plan_item) — le pipeline TV (_plan_tv_episode) n'est pas
    # atteignable ici. Rejouer le match sur un episode ecraserait kind +
    # tv_series_name / tv_season / tv_episode / tv_tmdb_series_id : l'apply
    # classerait ensuite l'episode comme un FILM. Tant que le resync memoire
    # (HIGH-17) n'existait pas, la row corrompue restait confinee a plan.jsonl ;
    # elle est desormais rechargee en memoire -> on refuse de replanifier.
    #
    # Revue adversaire R3 2026-07-13 (defaut 1, DESTRUCTIF — CRIT-1 rouvert par
    # une autre porte) : la liste NOIRE (tv_episode seul) laissait passer
    # kind="extra" (video bonus d'un dossier PARTAGE, plan_support_core.py:773).
    # Une row "extra" retombait dans le `else` en kind="single"
    # (replan_single_row:875 renormalise en "single" tout kind hors
    # {single, collection}), plan.jsonl etait reecrit ET recharge en memoire par
    # le resync — or apply_core traite kind="single" comme "dossier dedie"
    # (apply_core.py:1282) : marquer ce bonus pour suppression emportait de
    # nouveau TOUT le dossier (le film principal avec). On passe donc en liste
    # BLANCHE : seuls les kinds que replan_single_row sait reellement produire
    # sans perte sont replanifiables ; tout kind inconnu/futur est refuse par
    # defaut au lieu d'etre silencieusement renormalise en "single".
    row_kind = str(target.get("kind") or "single")
    if row_kind not in _REPLANNABLE_KINDS:
        logger.info(
            "_rematch_tmdb: row kind=%r (row_id=%s) non replanifiable — re-match TMDb ignore.",
            row_kind,
            row_id,
        )
        return None

    cfg = _build_cfg_for_row(api, settings, root=folder_path)
    if cfg is None:
        return None
    tmdb = _build_tmdb_client_optional(settings, state_dir)

    from cinesort.app.plan_support import plan_row_to_jsonable, replan_single_row  # noqa: PLC0415

    # row_kind est deja garanti dans _REPLANNABLE_KINDS par la garde ci-dessus :
    # plus aucune renormalisation silencieuse vers "single" n'a lieu ici.
    kind = row_kind

    # AUDIT 2026-06-11 (R3e gap[3] + R4-P4) : passer la VRAIE racine du scan a
    # replan (cfg a root=folder_path, donc sans racine explicite folder_name
    # serait derive du stem fichier -> replan non idempotent). R4-P4 : en
    # multi-roots, runs.root ne stocke que roots[0] ; passer roots[0] pour un
    # film d'un root SECONDAIRE faussait folder_name (un film pose a la racine
    # de R2 heritait du nom du dossier R2 au lieu du stem). On choisit donc le
    # root qui CONTIENT reellement le film, sinon None (compat pre-R3e).
    # P4 v2 : la row porte source_root (le root EXACT du scan, core.py:424) —
    # candidat autoritaire teste en premier, avant les roots reconstruits de la DB.
    scan_root = _resolve_scan_root_for_replan(api, run_id, folder_path, priority_candidates=[target.get("source_root")])

    new_row = replan_single_row(
        cfg,
        folder_path,
        video_path,
        tmdb=tmdb,
        kind=kind,
        library_root=scan_root,
        # Revue adversaire 2026-07-13 (defaut 1) : sans cet argument,
        # _apply_subtitle_detection sort immediatement (garde `is None`) et la
        # nouvelle row repart avec subtitle_count=0 / languages=[] /
        # missing_langs=[]. Le snapshot memoire etant desormais resynchronise, un
        # rescan EFFACAIT donc les infos sous-titres du film dans l'UI. Memes
        # regles de derivation que le scan (run_flow_support.py:424).
        subtitle_expected_languages=_scan_subtitle_expected_languages(settings),
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
        if old_film_id and new_film_id and old_film_id != new_film_id and is_path_film_id(old_film_id):
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

        locked_names = _locked_field_names_for_rematch(api, old_film_id, new_film_id)
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

    _carry_over_scan_only_fields(target, new_row_json)

    all_rows[target_idx] = new_row_json
    # Le `.tmp` etait NOMME EN DUR (`plan_jsonl.suffix + ".tmp"`) ici ET dans
    # `tmdb_support.enrich_tmdb_ids_by_title` : deux ecrivains reellement
    # concurrents sur le MEME chemin intermediaire (#732), sans fsync, sur le
    # fichier que l'apply relit pour renommer les dossiers. Cf write_plan_jsonl.
    # `run_data_support` est desormais importe en TETE (#779) : mesure du graphe
    # d'imports de tete, il ne remonte pas vers ce module, donc aucun cycle a
    # contourner. Ecrit en MODULE-STYLE, pas par symbole : les tests posent
    # `patch.object(run_data_support, "resync_run_state_rows")` sur le module
    # DEFINISSANT, et un import par symbole figerait la liaison a l'import.
    run_data_support.write_plan_jsonl(plan_jsonl, all_rows)

    # AUDIT 2026-07-13 (HIGH-17 / HIGH-19) : plan.jsonl vient de changer, mais le
    # snapshot memoire RunState.rows (prefere par get_plan ET par l'apply) date
    # toujours de la fin du scan -> sans cette resynchronisation, l'UI reaffiche
    # l'ancien match et l'apply renomme le dossier avec l'ANCIEN titre/annee/
    # edition (le re-scan parait sans effet jusqu'au redemarrage de l'app).
    run_data_support.resync_run_state_rows(api, run_id)

    if tmdb is not None:
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
        # `settings_support` etait DEJA une dependance de tete de ce module
        # (`normalize_user_path`) : differer ce second symbole ne differait rien (#779).
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
        processed = 0
        skipped = 0
        for rid in row_ids:
            # VN-E.3 : pause cooperative AVANT cancel check.
            if should_pause is not None:
                try:
                    while bool(should_pause()):
                        if should_cancel():
                            break
                        time.sleep(0.5)
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
            # LOTC-B1 : la cle config `rescan_run_id` marque ce run comme
            # utilitaire (sans plan propre) pour que _resolve_run_id le saute.
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


# Colonnes de l'export, dans l'ordre — SOURCE UNIQUE.
# Cette constante existait mais n'etait lue nulle part : la liste etait re-ecrite
# a la main 3 fois (entete CSV, ordre des valeurs CSV, cles de
# `_row_to_export_dict`), et la copie morte avait deja DERIVE (elle annoncait
# `tier_v2` / `audio_languages` / `subtitle_languages` la ou l'export emet
# `tier` / `audio_langs` / `subs_langs`). Les 3 sites en derivent desormais, et
# `test_export_fields_single_source` verrouille l'alignement.
_EXPORT_FIELDS = (
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
)


def _exports_dir(api: Any) -> Path:
    """Repertoire des exports : `<state_dir>/exports/`.

    Issue #522 : cette fonction ecrivait toujours dans
    `state.default_state_dir()/exports` (= `%LOCALAPPDATA%/CineSort/exports/`),
    en ignorant le `state_dir` configure par l'utilisateur. Un user-data
    deplace (NAS, 2e disque) laissait donc l'export dans l'ancien emplacement,
    hors de la zone que le reste du produit lit et purge.

    La zone d'ecriture reste BORNEE au dossier d'etat : on ne prend pas un
    chemin quelconque, seulement `settings["state_dir"]`, resolu par le meme
    `normalize_user_path` que les 5 autres sites du module. `state_dir` absent
    ou vide retombe sur `state.default_state_dir()` : comportement actuel
    inchange pour une configuration par defaut.
    """
    settings = api.settings.get_settings()
    state_dir = normalize_user_path(
        settings.get("state_dir") if isinstance(settings, dict) else None, state.default_state_dir()
    )
    base = state_dir / "exports"
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
        exports_dir = _exports_dir(api)
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"library_export_{resolved}_{ts}.{fmt_norm}"
        file_path = exports_dir / fname

        if fmt_norm == "csv":
            # AUDIT 2026-07-13 (M15) : aligner l'export Biblio sur la convention
            # Excel-FR DEJA appliquee par l'autre export CSV du produit
            # (dashboard_support.write_run_report_file / report_to_csv_text) :
            # BOM UTF-8 (`utf-8-sig`) + separateur ";". Sans BOM Excel FR casse
            # les accents ; avec le "," par defaut il ouvre tout en une colonne.
            # `newline=""` reste requis (csv.writer emet deja \r\n, cf LOTD-EXP-01)
            # et se transpose ici en `io.StringIO(newline="")` : aucune
            # traduction de fin de ligne, donc exactement les memes octets.
            #
            # Issue #479 site 2 : c'etait la DERNIERE branche non atomique de
            # cette fonction — JSON passait deja par `state.atomic_write_json`,
            # NDJSON par `state.atomic_write_text`. L'export CSV ecrivait en
            # place, donc Excel/LibreOffice pouvait ouvrir un fichier tronque.
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, delimiter=";")
            writer.writerow(list(_EXPORT_FIELDS))
            for row in export_rows:
                writer.writerow([_serialize_for_csv(row.get(k)) for k in _EXPORT_FIELDS])
            state.atomic_write_text(file_path, buffer.getvalue(), encoding="utf-8-sig")
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
        # Meme `.tmp` en dur que le reste de la famille #732 : deux exports
        # concurrents (ThreadingHTTPServer) visaient le meme intermediaire, et
        # aucun fsync ne protegeait la promotion d'un fichier tronque. Le
        # helper fait les deux. `newline="\n"` etait deja explicite : l'ecriture
        # binaire du helper produit exactement les memes octets.
        state.atomic_write_text(
            file_path,
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in export_rows),
        )
        return {
            "ok": True,
            "file_path": str(file_path),
            "count": count,
            "format": "ndjson",
            "run_id": resolved,
        }
    except (OSError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
