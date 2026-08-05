from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.domain.run_models import RunStatus
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


def _subtract_ignored_flags(api: Any, payload_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Retire des warning_flags les alertes ignorees persistees (spec 06 §3.3).

    E2-bis (revue Lot E) : run/get_plan servait les warning_flags bruts — une
    alerte ignoree via library/mark_alert_ignored re-apparaissait a chaque
    reload de la vue Traitement (seul get_film_full filtrait,
    cf film_support.py). Requete bulk (1 par plan), best-effort : en cas de
    store indisponible, les flags bruts sont conserves.
    """
    try:
        from cinesort.ui.api.library_support import _get_store

        store = _get_store(api)
        if store is None or not hasattr(store, "film_modal"):
            return payload_rows
        row_ids = [str(r.get("row_id") or "") for r in payload_rows if isinstance(r, dict)]
        ignored = store.film_modal.list_ignored_alerts_bulk(row_ids)
        if not ignored:
            return payload_rows
        for row in payload_rows:
            if not isinstance(row, dict):
                continue
            codes = ignored.get(str(row.get("row_id") or ""))
            flags = row.get("warning_flags")
            if codes and isinstance(flags, list):
                row["warning_flags"] = [f for f in flags if str(f) not in codes]
    # R2 (revue Lot E round 2) : sqlite3.Error n'herite PAS d'OSError — sans
    # lui, un 'database is locked' pendant un apply concurrent faisait echouer
    # get_plan ENTIER alors que le plan etait servable (le best-effort promis
    # ici ne couvrait que store=None). RuntimeError : rollback de migration
    # dans store.initialize().
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        logger.debug("subtract_ignored_flags error: %s", exc)
    return payload_rows


def _present_langs_from_payload(row: Dict[str, Any], qr_by_id: Dict[str, Dict[str, Any]]) -> set:
    """Langues sous-titres présentes (externe ∪ embarqué) pour une row de PAYLOAD (dict).
    Même union externe∪embarqué que librarian.py:132-158 / library_support, mais lisant
    le DICT payload sérialisé (source unique de la réconciliation côté écran Traitement)."""
    from cinesort.domain.subtitle_helpers import _normalize_iso639

    present: set = set()
    for lang in row.get("subtitle_languages") or []:
        norm = _normalize_iso639(lang) or str(lang).strip().lower()
        if norm:
            present.add(norm)
    qr = qr_by_id.get(str(row.get("row_id") or "")) or {}
    metrics = qr.get("metrics") if isinstance(qr.get("metrics"), dict) else {}
    embedded = metrics.get("subtitles_embedded")
    if isinstance(embedded, list):
        for track in embedded:
            if isinstance(track, dict):
                raw = (track.get("language") or "").strip().lower()
                if raw:
                    norm = _normalize_iso639(raw)
                    if norm:
                        present.add(norm)
    return present


def _full_langs_from_payload(row: Dict[str, Any], qr_by_id: Dict[str, Dict[str, Any]]) -> set:
    """Langues avec une piste EMBARQUÉE complète (non forcée), pour une row de PAYLOAD.

    F12 : réconcilie `subtitle_forced_only_<lang>` quand le film a en réalité une piste
    complète MUXÉE que le scan n'a pas vue. On ne lit PAS `row["subtitle_languages"]` :
    ce champ ne distingue pas une piste forcée d'une piste complète (cf. la garde de
    `reconcile_subtitle_flags`)."""
    from cinesort.ui.api.run_read_support import full_langs_from_embedded

    qr = qr_by_id.get(str(row.get("row_id") or "")) or {}
    metrics = qr.get("metrics") if isinstance(qr.get("metrics"), dict) else {}
    return full_langs_from_embedded(metrics.get("subtitles_embedded"))


def _enrich_plan_payload(api: Any, run_id: str, payload_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[écran Traitement/Vérification] Enrichit chaque row du payload :
      - ``display_title`` : titre sans l'année dupliquée (colonne ANNÉE séparée),
      - ``warning_flags`` : réconciliés — retire les faux ``subtitle_missing_<lang>``
        dont la langue est en fait présente (FR muxé ignoré au scan) et les faux
        ``subtitle_forced_only_<lang>`` démentis par une piste muxée COMPLÈTE,
      - ``auto_approvable`` : bool (le frontend filtre « à examiner » sur NON auto_approvable
        et affiche « Cas à vérifier » = nombre de NON auto_approvable, cohérent backend).
    Best-effort : toute erreur (store/settings/quality indisponible) laisse le payload intact.
    """
    try:
        from cinesort.domain.conversions import to_int
        from cinesort.domain.title_helpers import strip_trailing_year_if_equal
        from cinesort.ui.api.film_support import (
            apply_tmdb_overrides_bulk,
            list_tmdb_overrides_bulk,
            overlay_tmdb_override,
        )
        from cinesort.ui.api.library_support import _get_store
        from cinesort.ui.api.run_read_support import (
            _AUTO_CRITICAL_WARNINGS,
            _AUTO_INTEGRITY_WARNINGS,
            _CONFLICT_FLAGS,
            build_qr_by_id,
            reconcile_subtitle_flags,
        )

        store = _get_store(api)
        qr_by_id: Dict[str, Dict[str, Any]] = {}
        if store is not None and hasattr(store, "quality"):
            with contextlib.suppress(Exception):
                qr_by_id = build_qr_by_id(store.quality.list_quality_reports(run_id=run_id))
        try:
            threshold = to_int(api._get_settings_impl().get("auto_approve_threshold"), 85)
        except Exception:  # noqa: BLE001 — settings illisibles -> défaut 85
            threshold = 85
        blocking = _CONFLICT_FLAGS | _AUTO_CRITICAL_WARNINGS | _AUTO_INTEGRITY_WARNINGS
        # PERF (ultra-audit 2026-08, CRITICAL) : les overrides TMDb du run sont
        # lus en UNE requete au lieu de 2 connexions SQLite PAR ROW (2N pour un
        # plan de N films : 40 s / 2002 connexions mesurees a N=1000, meme table
        # vide). `None` = lecture bulk indisponible OU partielle -> on retombe
        # sur le chemin par row (dans la boucle), lent mais correct : jamais un
        # plan silencieusement privé de ses overrides. `{}` = run réellement
        # sans override -> rien à appliquer, mais les rows sont bien marquées.
        #
        # `apply_tmdb_overrides_bulk` pose `TMDB_OVERLAY_DONE_KEY` lui-même sur
        # les rows traitées (PR #849) : sans cela, `library_support` — qui est
        # fail-closed sur ce marqueur — reprendrait la relecture par row et le
        # N+1 supprimé ici reviendrait par la vue Bibliothèque. Il est appelé
        # AVANT la boucle : l'overlay doit précéder le calcul de
        # `display_title`, qui lit `proposed_title`/`proposed_year`.
        overrides = list_tmdb_overrides_bulk(store, run_id)
        if overrides is not None:
            with contextlib.suppress(Exception):
                apply_tmdb_overrides_bulk(payload_rows, overrides)

        for row in payload_rows:
            if not isinstance(row, dict):
                continue
            # HIGH-13 (2026-07-13) : overlay de l'override TMDb manuel AVANT tout
            # calcul, pour que la Validation pré-cochée seede le bon titre/année/
            # confiance (traitement.js lit r.proposed_year) et que l'apply voie le
            # même titre que le modal fiche film / que l'overlay _validate_apply.
            # Chemin de repli uniquement : le lot a déjà été appliqué ci-dessus
            # quand la lecture groupée a abouti.
            if overrides is None:
                with contextlib.suppress(Exception):
                    overlay_tmdb_override(store, run_id, row)
            try:
                # 1) titre d'affichage sans année dupliquée (helper testé, protège "Blade Runner 2049")
                with contextlib.suppress(Exception):
                    row["display_title"] = strip_trailing_year_if_equal(
                        str(row.get("proposed_title") or ""), row.get("proposed_year")
                    )
                row.setdefault("display_title", str(row.get("proposed_title") or ""))
                # 2) réconciliation sous-titres (faux subtitle_missing_<lang> retirés)
                flags = row.get("warning_flags")
                if isinstance(flags, list) and qr_by_id:
                    present = _present_langs_from_payload(row, qr_by_id)
                    row["warning_flags"] = reconcile_subtitle_flags(
                        flags, present, _full_langs_from_payload(row, qr_by_id)
                    )
                # 3) auto_approvable (sur les flags réconciliés). to_int : robuste à un
                #    proposed_year/confidence non numérique (n'abandonne pas la boucle).
                cur = {str(f) for f in (row.get("warning_flags") or [])}
                has_title = bool(str(row.get("proposed_title") or "").strip())
                has_year = to_int(row.get("proposed_year"), 0) >= 1900
                row["auto_approvable"] = bool(
                    to_int(row.get("confidence"), 0) >= threshold and not (cur & blocking) and has_title and has_year
                )
            except Exception as row_exc:  # noqa: BLE001 — best-effort PAR ROW
                logger.debug("enrich_plan_payload row error: %s", row_exc)
                continue
    except Exception as exc:  # noqa: BLE001 — enrichissement best-effort
        logger.debug("enrich_plan_payload error: %s", exc)
    return payload_rows


@requires_valid_run_id
def get_plan(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur cet endpoint appele par la vue Traitement (step Apply / validation).
    try:
        return _get_plan_impl(api, run_id, normalize_user_path=normalize_user_path)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("get_plan failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "plan_load_failed",
            "message": str(exc),
            "user_message": ("Impossible de charger le plan du run. Le fichier est peut-etre corrompu."),
        }


def _load_plan_rows(api: Any, run_id: str, *, normalize_user_path: Any) -> Tuple[Any, Dict[str, Any] | None]:
    """Charge les PlanRow d'un run : memoire d'abord, puis plan.jsonl.

    Retourne ``(rows, None)`` ou ``(None, reponse_erreur)``. Extrait de
    ``_get_plan_impl`` pour que ``get_plan_row`` (fiche film) partage EXACTEMENT
    les memes regles de resolution et les memes messages d'erreur.
    """
    rs = api._get_run(run_id)
    if rs:
        if not rs.done:
            return None, _err_response("Plan pas pret.", category="state", level="debug", log_module=__name__)
        rows = rs.rows
        if not rows:
            try:
                rows = api._load_rows_from_plan_jsonl(rs.paths)
            except (ImportError, OSError) as exc:
                # Fix audit 2026-05-24 (v1.5.1) : "Plan introuvable" est un cas
                # legitime (run cleanup orphelin, run FAILED dont le plan.jsonl
                # n'a jamais ete ecrit). Loguer en debug au lieu d'error pour
                # eviter la pollution des logs.
                return None, _err_response(str(exc), category="state", level="debug", log_module=__name__)
        return rows, None

    found = api._find_run_row(run_id)
    if not found:
        return None, _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
    row, _store = found
    status_text = str(row.get("status") or "")
    if status_text not in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
        return None, _err_response("Plan pas pret.", category="state", level="debug", log_module=__name__)
    run_paths = api._run_paths_for(
        normalize_user_path(row.get("state_dir"), api._state_dir), run_id, ensure_exists=False
    )
    try:
        return api._load_rows_from_plan_jsonl(run_paths), None
    except (OSError, KeyError, TypeError, ValueError) as exc:
        # Fix audit 2026-05-24 (v1.5.1) : voir commentaire ci-dessus.
        return None, _err_response(str(exc), category="state", level="debug", log_module=__name__)


def _get_plan_impl(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    """Implementation reelle de get_plan, sans wrap global (Vague G)."""
    logger.debug("api: get_plan run_id=%s", run_id)
    rows, err = _load_plan_rows(api, run_id, normalize_user_path=normalize_user_path)
    if err is not None:
        return err
    try:
        payload = api._serialize_rows_for_payload(rows)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="state", level="debug", log_module=__name__)
    return {"ok": True, "rows": _enrich_plan_payload(api, run_id, _subtract_ignored_flags(api, payload))}


def _row_id_of(row: Any) -> str:
    """row_id d'une PlanRow (dataclass) ou d'une row deja serialisee (dict)."""
    if isinstance(row, dict):
        return str(row.get("row_id") or "")
    return str(getattr(row, "row_id", "") or "")


def get_plan_row(api: Any, run_id: str, row_id: str, *, normalize_user_path: Any) -> Dict[str, Any] | None:
    """UNE row de plan enrichie, sans serialiser NI enrichir tout le plan.

    PERF (ultra-audit 2026-08, HIGH) : la fiche film passait par
    ``run/get_plan``, qui serialise les N rows du run et les enrichit toutes
    (2 connexions SQLite par row pour l'override TMDb), pour ensuite jeter les
    N-1 autres : 9,2 s et ~2000 connexions mesurees a N=1000 pour renvoyer une
    seule ligne. On filtre desormais la PlanRow AVANT la serialisation et on ne
    fait passer qu'elle dans la MEME chaine (alertes ignorees, override TMDb,
    reconciliation des sous-titres, display_title, auto_approvable) : memes
    champs en sortie, cout independant de la taille du plan.

    Retourne ``None`` si le run, le plan ou la row sont introuvables — c'est le
    contrat attendu par les appelants (fiche film), qui rendent alors leur
    propre erreur "Film introuvable".
    """
    wanted = str(row_id or "")
    if not wanted:
        return None
    rows, err = _load_plan_rows(api, run_id, normalize_user_path=normalize_user_path)
    if err is not None or not rows:
        return None
    match = next((r for r in rows if _row_id_of(r) == wanted), None)
    if match is None:
        return None
    payload = api._serialize_rows_for_payload([match])
    if not payload:
        return None
    enriched = _enrich_plan_payload(api, run_id, _subtract_ignored_flags(api, payload))
    return enriched[0] if enriched else None


@requires_valid_run_id
def load_validation(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    from cinesort.domain.conversions import to_bool
    from cinesort.ui.api.run_read_support import seed_auto_approve_decisions

    rs = api._get_run(run_id)
    if rs:
        path = rs.paths.validation_json
        if not path.exists():
            # [auto-approve] Première visite (aucune validation.json). Si
            # auto_approve_enabled, on pré-remplit la Validation (overlay
            # read-only, jamais persisté) ; sinon comportement inchangé (vide).
            # Lecture settings défensive : un settings illisible → comportement
            # historique (décisions vides), jamais une exception (revue adversaire).
            try:
                _auto_on = to_bool(api._get_settings_impl().get("auto_approve_enabled"), False)
            except Exception:  # noqa: BLE001 — best-effort, pas d'auto-approve si settings KO
                _auto_on = False
            if not _auto_on:
                return {"ok": True, "decisions": {}}
            rows = rs.rows if rs.rows else api._load_rows_from_plan_jsonl(rs.paths)
            seeded = seed_auto_approve_decisions(api, rows, {})
            return {"ok": True, "decisions": api._normalize_decisions_for_rows(rows, seeded)}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows = rs.rows
                if not rows:
                    rows = api._load_rows_from_plan_jsonl(rs.paths)
                # [auto-approve] Overlay read-only ; no-op si le flag est off.
                seeded = seed_auto_approve_decisions(api, rows, data)
                return {"ok": True, "decisions": api._normalize_decisions_for_rows(rows, seeded)}
            return {"ok": True, "decisions": {}}
        except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError) as exc:
            api._debug_log(
                state_dir=api._state_dir,
                run_id=run_id,
                enabled=api._debug_enabled(),
                message=f"load_validation(memory) warning run_id={run_id} error={exc}",
            )
            logger.debug("load_validation(memory) ignoree run_id=%s err=%s", run_id, exc)
            return {"ok": True, "decisions": {}}

    found = api._find_run_row(run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
    row, _store = found
    state_dir = normalize_user_path(row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    data = api._load_decisions_from_validation(run_paths)
    try:
        rows = api._load_rows_from_plan_jsonl(run_paths)
        # [auto-approve] Overlay read-only ; no-op si le flag est off.
        seeded = seed_auto_approve_decisions(api, rows, data)
        return {"ok": True, "decisions": api._normalize_decisions_for_rows(rows, seeded)}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        api._debug_log(
            state_dir=state_dir,
            run_id=run_id,
            enabled=api._debug_enabled(),
            message=f"load_validation(disk) warning run_id={run_id} error={exc}",
        )
        logger.debug("load_validation(disk) ignoree run_id=%s err=%s", run_id, exc)
        return {"ok": True, "decisions": {}}


@requires_valid_run_id
def cancel_run(api: Any, run_id: str) -> Dict[str, Any]:
    # Fix audit 2026-05-25 (v1.5.3) Vague F : action destructive non-protegee
    # provoquait HTTP 500 + run zombie. Wrap global pour garantir une reponse.
    try:
        rs = api._get_run(run_id)
        if not rs:
            return _err_response(
                "Run introuvable.", category="resource", level="info", log_module=__name__, run_id=run_id
            )

        accepted = rs.runner.request_cancel(run_id)
        snap = rs.runner.get_status(run_id)
        return {
            "ok": bool(accepted),
            "run_id": run_id,
            "status": snap.status.value if snap else None,
            "cancel_requested": bool(snap.cancel_requested) if snap else bool(accepted),
            "done": bool(snap.done) if snap else False,
        }
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("cancel_run failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "cancel_run_failed",
            "message": str(exc),
            "user_message": ("Impossible d'annuler le run. Il continuera en arriere-plan."),
        }


def _store_for_run(api: Any, run_id: str) -> Tuple[Dict[str, Any], Any] | None:
    """Resout (row, store) pour un run_id. Wrapper trivial autour de _find_run_row."""
    found = api._find_run_row(run_id)
    if not found:
        return None
    return found[0], found[1]


def _readable_duplicate_group(group_key: str, winner_row: Dict[str, Any]) -> Tuple[str, Any]:
    """Titre + annee LISIBLES d'un groupe de doublons pour l'Inspecteur Historique.

    AUDIT 2026-07-13 (M16) : la `group_key` est une cle technique. Quand un groupe
    n'expose pas de cle explicite, `_group_key_for` (run_flow_support.py) retourne
    le fallback "titre minuscule|annee" (ex. "le seigneur des anneaux|2001").
    L'ancien code ne parsait que le format "Titre (AAAA)" et affichait donc cette
    cle BRUTE. On prefere le titre PROPRE du row gagnant (casse correcte, meme
    source que winner_label), et on ne parse la cle qu'en repli (gagnant absent du
    plan) — en tolerant les DEUX formats.
    """
    title = str(winner_row.get("proposed_title") or winner_row.get("nfo_title") or "").strip()
    year: Any = None
    winner_year = winner_row.get("proposed_year")
    if winner_year:
        with contextlib.suppress(TypeError, ValueError):
            year = int(winner_year) or None
    if title:
        return title, year

    gk = str(group_key or "").strip()
    m = re.search(r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2})\)", gk)
    if m:
        return (m.group("title").strip() or "(Sans titre)"), int(m.group("year"))
    if "|" in gk:
        # Fallback _group_key_for : "titre|annee" (annee = dernier segment).
        raw_title, _, raw_year = gk.rpartition("|")
        if raw_year.strip().isdigit():
            year = int(raw_year.strip())
        return (raw_title.strip() or gk or "(Sans titre)"), year
    return (gk or "(Sans titre)"), year


@requires_valid_run_id
def get_history_stats(api: Any, run_id: str) -> Dict[str, Any]:
    """Retourne le detail complet d'un run pour l'inspecteur Historique (spec 09).

    Format attendu :
        {ok, run: {run_id, started_ts, duration_s, status, total_rows,
                   applied_rows, validated_count, rejected_count,
                   errors_count, conflicts_count, duplicates_groups,
                   score_avg, films_by_tier, apply_operations: [...]}}

    Fallback gracieux : si certaines tables/JSON ne sont pas disponibles, les
    champs concernes valent 0 / [] / None plutot que d'echouer.
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500.
    try:
        return _get_history_stats_impl(api, run_id)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("get_history_stats failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "history_stats_failed",
            "message": str(exc),
            "user_message": ("Impossible de charger les details du run. Verifie l'historique ou redemarre l'app."),
        }


def _get_history_stats_impl(api: Any, run_id: str) -> Dict[str, Any]:
    """Implementation reelle de get_history_stats, sans wrap global (Vague F)."""
    logger.debug("api: get_history_stats run_id=%s", run_id)
    found = _store_for_run(api, run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__, run_id=run_id)
    row, store = found

    started_ts = float(row.get("started_ts") or row.get("created_ts") or 0.0)
    ended_ts = float(row.get("ended_ts") or 0.0)
    duration_s = round(ended_ts - started_ts, 1) if (started_ts and ended_ts) else 0.0
    status = str(row.get("status") or "PENDING")

    # stats_json contient le snapshot fin de run (planned_rows, applied_count, ...).
    stats_obj: Dict[str, Any] = {}
    raw_stats = row.get("stats_json")
    if isinstance(raw_stats, str) and raw_stats:
        try:
            parsed = json.loads(raw_stats)
            if isinstance(parsed, dict):
                stats_obj = parsed
        except (ValueError, json.JSONDecodeError) as exc:
            logger.debug("get_history_stats: stats_json invalide run_id=%s err=%s", run_id, exc)

    # Fix audit 2026-05-25 (v1.5.4) Vague I : aligner total_rows sur la
    # source unique de verite = nombre de PlanRow dans plan.jsonl. Le
    # snapshot DB (run_row.total ou stats.planned_rows) peut etre obsolete.
    # Fix audit 2026-05-26 (v1.5.6) Vague L : count-2. Fallback delegue a
    # compute_total_fallback() pour aligner avec dashboard/run_flow (avant
    # cet helper, history priorisait row.total puis stats.planned_rows,
    # dashboard l'inverse, run_flow ne lisait que row.total).
    from cinesort.ui.api.run_data_support import (
        compute_total_fallback as _compute_total_fallback,
    )
    from cinesort.ui.api.run_data_support import (
        count_plan_rows as _count_plan_rows,
    )

    try:
        _hist_run_paths = api._run_paths_for(
            normalize_user_path(row.get("state_dir"), api._state_dir),
            run_id,
            ensure_exists=False,
        )
        total_rows = _count_plan_rows(
            _hist_run_paths,
            fallback=_compute_total_fallback(row, stats_obj),
        )
    except (AttributeError, OSError, TypeError, ValueError):
        total_rows = _compute_total_fallback(row, stats_obj)
    # AUDIT 2026-07-13 (HIGH-7) : applied_count vit dans apply_batches.summary_json
    # (ecrit par l'apply), PAS dans runs.stats_json (cle jamais ecrite) -> lecture
    # de la source reelle (repare retroactivement les runs deja en base). Le
    # fallback stats_obj est conserve pour les fixtures/demo. _last_batch est
    # reutilise plus bas (bloc "Apply operations") -> 0 requete supplementaire.
    _last_batch: Dict[str, Any] | None = None
    try:
        _last_batch = store.apply.get_last_reversible_apply_batch(run_id) if store else None
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: last apply batch err run_id=%s err=%s", run_id, exc)
    applied_rows = int(
        ((_last_batch or {}).get("summary") or {}).get("applied_count") or stats_obj.get("applied_count") or 0
    )

    # Quality reports : count + tier distribution + score moyen.
    validated_count = 0
    rejected_count = 0
    score_avg: float | None = None
    films_by_tier: Dict[str, int] = {}
    try:
        quality_reports = store.quality.list_quality_reports(run_id=run_id) if store else []
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: list_quality_reports err run_id=%s err=%s", run_id, exc)
        quality_reports = []
    if quality_reports:
        scores: List[float] = []
        for rep in quality_reports:
            tier = str(rep.get("tier") or "").strip().lower()
            if tier:
                films_by_tier[tier] = films_by_tier.get(tier, 0) + 1
            score = rep.get("score")
            if score is not None:
                with contextlib.suppress(TypeError, ValueError):
                    scores.append(float(score))
            # "reject" tier = rejected, anything else with score > 0 = validated.
            if tier == "reject":
                rejected_count += 1
            elif tier:
                validated_count += 1
        if scores:
            score_avg = round(sum(scores) / len(scores), 1)

    # Errors associes au run.
    errors_count = 0
    try:
        errs = store.run.list_errors(run_id) if store else []
        errors_count = len(errs) if errs else 0
    except (OSError, AttributeError, TypeError) as exc:
        logger.debug("get_history_stats: list_errors err run_id=%s err=%s", run_id, exc)

    # Conflicts (anomalies severity != info) si presents dans stats_obj, sinon 0.
    conflicts_count = int(stats_obj.get("conflicts_count") or stats_obj.get("anomalies_total") or 0)

    # Duplicates groups : on lit depuis stats_obj si dispo, sinon 0.
    duplicates_groups = int(stats_obj.get("duplicates_groups") or 0)

    # Apply operations : derniere batch reel (non dry-run) DONE.
    apply_operations: List[Dict[str, Any]] = []
    try:
        if store and _last_batch:
            ops = store.apply.list_apply_operations(batch_id=_last_batch.get("batch_id"))
            apply_operations = [
                {
                    "op_index": int(op.get("op_index") or 0),
                    "op_type": str(op.get("op_type") or ""),
                    "src_path": str(op.get("src_path") or ""),
                    "dst_path": str(op.get("dst_path") or ""),
                    "reversible": bool(int(op.get("reversible") or 0)),
                    "undo_status": str(op.get("undo_status") or "PENDING"),
                }
                for op in ops
            ]
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: apply_operations err run_id=%s err=%s", run_id, exc)

    # AUDIT 2026-06-14 (R7-6) : detail des films + doublons pour l'Inspecteur
    # Historique (onglets Films / Doublons). Avant, ces cles n'etaient pas
    # renvoyees -> "(detail non disponible)" systematique + recherche par titre
    # qui ne matchait jamais.
    films: List[Dict[str, Any]] = []
    # R8-061/062 (F5) : plan rows + décisions doublons chargés UNE fois, partagés
    # par les deux onglets (Films -> statut ; Doublons -> label gagnant).
    row_by_id: Dict[str, Dict[str, Any]] = {}
    try:
        plan_res = api.run.get_plan(run_id) if hasattr(api, "run") else None
        plan_rows = (plan_res or {}).get("rows") or [] if isinstance(plan_res, dict) else []
        row_by_id = {str(r.get("row_id")): r for r in plan_rows if isinstance(r, dict)}
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: plan rows err run_id=%s err=%s", run_id, exc)
    # AUDIT 2026-07-13 (HIGH-9) : la vraie DECISION utilisateur vit dans
    # validation.json (tri-etat accepted/rejected/deferred), PAS sur la PlanRow
    # serialisee (asdict(PlanRow) n'a aucun champ `decision` -> pr.get("decision")
    # valait TOUJOURS ""). On charge la MEME facade que get_plan ci-dessus.
    val_decisions: Dict[str, Any] = {}
    try:
        _vres = api.run.load_validation(run_id) if hasattr(api, "run") else None
        if isinstance(_vres, dict) and _vres.get("ok"):
            val_decisions = _vres.get("decisions") or {}
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: validation err run_id=%s err=%s", run_id, exc)
    dup_decisions: List[Dict[str, Any]] = []
    dup_row_ids: set = set()
    try:
        dup_decisions = (store.apply.list_duplicate_decisions(run_id=run_id) if store else []) or []
        for _d in dup_decisions:
            wr = str(_d.get("winner_row_id") or "")
            if wr:
                dup_row_ids.add(wr)
            for _lr in _d.get("loser_row_ids") or []:
                dup_row_ids.add(str(_lr))
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: dup decisions err run_id=%s err=%s", run_id, exc)
    try:
        for rep in quality_reports:
            rid = str(rep.get("row_id") or "")
            pr = row_by_id.get(rid, {})
            year = int(pr.get("proposed_year") or 0) or None
            films.append(
                {
                    "film_id": rid,
                    "title": str(pr.get("proposed_title") or pr.get("nfo_title") or "").strip() or f"Film {rid}",
                    "year": year,
                    "tier": str(rep.get("tier") or "").strip().lower(),
                    "score": rep.get("score"),
                    # R8-062 (F5) : statut lu par historique.js _filmStatusLabel
                    # (decision tri-état + is_duplicate). Avant : undefined -> toujours « Approuvé ».
                    # HIGH-9 (2026-07-13) : source = validation.json (tri-état
                    # accepted/rejected/deferred). Vide pour un film non décidé ->
                    # le front retombe sur le tier. NB : pas de fallback ok→rejected
                    # car load_validation matérialise TOUTES les rows (ok=False par
                    # défaut) -> ce fallback classerait tout film non décidé « Rejeté ».
                    "decision": str((val_decisions.get(rid) or {}).get("decision") or "").strip().lower(),
                    "is_duplicate": rid in dup_row_ids,
                }
            )
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: films detail err run_id=%s err=%s", run_id, exc)

    duplicates_decided: List[Dict[str, Any]] = []
    try:
        for dec in dup_decisions:
            gk = str(dec.get("group_key") or "")
            winner_row_id = str(dec.get("winner_row_id") or "")
            winner_row = row_by_id.get(winner_row_id, {})
            # R8-061 (F5) : label gagnant lisible (front lit g.winner_label, sinon « — »).
            # NB : size_savings n'est PAS persisté dans duplicate_decisions -> non rendu
            # ici (résidu documenté ; nécessiterait de le stocker à la décision).
            winner_label = (
                str(winner_row.get("proposed_title") or winner_row.get("nfo_title") or "").strip()
                or winner_row_id
                or "—"
            )
            # AUDIT 2026-07-13 (M16) : la group_key est TECHNIQUE — le fallback
            # `_group_key_for` (run_flow_support.py) vaut "titre minuscule|annee"
            # ("le seigneur des anneaux|2001"), que la regex parenthesee ne matchait
            # PAS -> le titre brut de la cle s'affichait dans l'Historique. On lit
            # le titre PROPRE du row gagnant (deja charge), avec parsing de la cle
            # en repli quand le gagnant est introuvable dans le plan.
            dup_title, dup_year = _readable_duplicate_group(gk, winner_row)
            duplicates_decided.append(
                {
                    "title": dup_title,
                    "year": dup_year,
                    "winner": winner_row_id,
                    "winner_label": winner_label,
                }
            )
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: duplicates detail err run_id=%s err=%s", run_id, exc)

    return {
        "ok": True,
        "run": {
            "run_id": run_id,
            "started_ts": started_ts,
            "ended_ts": ended_ts,
            "duration_s": duration_s,
            "status": status,
            "total_rows": total_rows,
            "applied_rows": applied_rows,
            "validated_count": validated_count,
            "rejected_count": rejected_count,
            "errors_count": errors_count,
            "conflicts_count": conflicts_count,
            "duplicates_groups": duplicates_groups,
            "score_avg": score_avg,
            "films_by_tier": films_by_tier,
            "apply_operations": apply_operations,
            # R7-6 : detail pour les onglets Films / Doublons de l'Inspecteur.
            "films": films,
            "duplicates_decided": duplicates_decided,
            "duplicates_skipped": [],
        },
    }


@requires_valid_run_id
def delete_run(api: Any, run_id: str) -> Dict[str, Any]:
    """Supprime un run de l'historique (DB seulement, pas les fichiers video).

    Cf spec 09 §4 : action dangereuse. Le frontend a deja affiche une modale
    de confirmation avant d'appeler cet endpoint.

    Cascade :
    - runs (1 row)
    - errors, quality_reports, anomalies (FK CASCADE)
    - perceptual_reports, apply_batches + apply_operations (cascade manuelle)

    Les fichiers d'etat sur disque (plan.jsonl, validation.json, ui_log.txt)
    NE sont PAS touches — ils seront elimines a la rotation par retention.
    """
    logger.debug("api: delete_run run_id=%s", run_id)
    found = _store_for_run(api, run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__, run_id=run_id)
    _row, store = found
    try:
        deleted = store.run.delete_run(run_id)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        return _err_response(
            t("errors.run_deletion_failed", detail=str(exc)),
            category="runtime",
            level="error",
            log_module=__name__,
            run_id=run_id,
        )

    # Purge aussi le RunState en memoire si present (sinon on garde une coquille
    # vide qui pointe vers une row supprimee).
    try:
        with api._runs_lock:
            api._runs.pop(run_id, None)
    except (AttributeError, KeyError) as exc:
        logger.debug("delete_run: purge runs memoire ignoree run_id=%s err=%s", run_id, exc)

    logger.info("delete_run: run_id=%s deleted_records=%d", run_id, deleted)
    return {"ok": True, "run_id": run_id, "deleted_records": int(deleted)}


def cleanup_old_runs(api: Any, retention_days: int = 90) -> Dict[str, Any]:
    """Supprime tous les runs dont la date la plus recente est > N jours.

    Iteration sur tous les stores actifs (multi state_dir). Retourne le
    nombre total de runs supprimes + la liste des run_ids.

    Cette fonction est appelable :
    - Manuellement via l'API (debug / forcer la purge)
    - Automatiquement au boot par le cron retention_cleanup (cf
      cinesort.app.retention_cleanup.start_retention_cron)
    """
    try:
        days = max(1, int(retention_days or 0))
    except (TypeError, ValueError):
        days = 90
    cutoff_ts = time.time() - (days * 86400.0)

    deleted_ids: List[str] = []
    # Iteration sur tous les stores connus (multi state_dir, cas tests + LAN).
    try:
        with api._runs_lock:
            stores = [store for store, _runner in api._infra_by_state_dir.values()]
    except AttributeError:
        stores = []
    # S'assurer que le store par defaut est inclus meme si pas encore initialise.
    try:
        default_store, _runner = api._get_or_create_infra(api._state_dir)
        if default_store not in stores:
            stores.append(default_store)
    except (AttributeError, OSError, RuntimeError) as exc:
        logger.debug("cleanup_old_runs: default store lookup err: %s", exc)

    for store in stores:
        try:
            run_ids = store.run.list_runs_older_than(cutoff_ts=cutoff_ts)
        except (OSError, AttributeError, TypeError, ValueError) as exc:
            logger.warning("cleanup_old_runs: list_runs_older_than err: %s", exc)
            continue
        for rid in run_ids:
            try:
                store.run.delete_run(rid)
                deleted_ids.append(rid)
            except (OSError, AttributeError, TypeError, ValueError) as exc:
                logger.warning("cleanup_old_runs: delete_run err run_id=%s err=%s", rid, exc)

    logger.info("cleanup_old_runs: deleted %d runs older than %d days", len(deleted_ids), days)
    return {
        "ok": True,
        "deleted_count": len(deleted_ids),
        "deleted_run_ids": deleted_ids,
        "retention_days": days,
    }


def _real_path(value: Path) -> Path:
    """Chemin REEL canonise, pour comparer des chemins et non des chaines.

    ``os.path.realpath`` resout jonctions NTFS, points de montage, noms courts
    8.3 et liens ; ``os.path.normcase`` neutralise la casse (NTFS est
    insensible a la casse). Les DEUX cotes d'une comparaison de zone doivent
    passer par ici : sinon deux ecritures du meme chemin reel paraissent
    differentes et un dossier legitime est refuse.
    """
    return Path(os.path.normcase(os.path.realpath(str(value))))


def open_path(api: Any, path: str, *, default_root: str, normalize_user_path: Any) -> Dict[str, Any]:
    try:
        raw_path = str(path or "").strip()
        if not raw_path:
            return _err_response("Chemin vide.", category="validation", level="info", log_module=__name__)

        candidate = Path(raw_path)
        if not candidate.exists():
            return _err_response("Chemin introuvable.", category="resource", level="warning", log_module=__name__)

        # Fix audit 2026-05-25 (v1.5.3) Vague H : refuser les symlinks pour
        # eviter path traversal. Sans ce check, candidate (non-resolu) servait
        # a os.startfile() alors que la verification d'autorisation portait
        # sur resolved_path : un symlink dans une base autorisee permettait
        # d'ouvrir n'importe quel chemin du systeme.
        if candidate.is_symlink():
            logger.warning("open_path refuse : symlink detecte %s", candidate)
            return _err_response(
                "Les liens symboliques ne sont pas autorises.",
                category="permission",
                level="warning",
                log_module=__name__,
            )

        settings = api.settings.get_settings()
        root_raw = str(settings.get("root") or "").strip()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())

        resolved_path = candidate.resolve()
        # Fix 2026-08-03 : ici vivait une 2e garde qui comparait des CHAINES
        # (``str(resolved_path) != str(candidate.absolute())``) pour deviner un
        # symlink parent. Or ``resolve()`` reecrit la chaine sans qu'aucun lien
        # n'existe des que le chemin traverse une jonction NTFS, un point de
        # montage, un nom court 8.3 ou une casse differente (NTFS est
        # insensible a la casse) : une bibliotheque placee derriere une
        # jonction se voyait refuser un dossier parfaitement normal.
        # La protection anti path-traversal de la Vague H (2026-05-25) reste
        # entiere, portee par trois faits INDEPENDANTS de l'ecriture du chemin :
        #  1. les liens symboliques sont refuses explicitement ci-dessus
        #     (``candidate.is_symlink()``) ;
        #  2. un lien situe dans le chemin PARENT est neutralise par le controle
        #     de zone ci-dessous, qui compare des chemins REELS des deux cotes
        #     (``_real_path``) : la cible du lien sort de la zone autorisee, donc
        #     le chemin est refuse ;
        #  3. ``os.startfile()`` n'ouvre que le chemin RESOLU, jamais
        #     ``candidate`` : meme autorise, un lien ne peut pas faire ouvrir
        #     autre chose que sa cible deja validee.
        open_target = resolved_path
        resolved_to_check = resolved_path
        if resolved_path.is_file():
            open_target = resolved_path.parent
            resolved_to_check = resolved_path.parent
        elif not resolved_path.is_dir():
            return _err_response(
                "Chemin invalide (ni fichier ni dossier).", category="validation", level="warning", log_module=__name__
            )

        allowed = False
        allowed_bases: List[Path] = [state_dir]
        if root_raw:
            allowed_bases.append(normalize_user_path(root_raw, Path(default_root)))

        # Comparaison de chemins REELS (et non de chaines) des deux cotes :
        # c'est ce controle qui porte desormais seul le refus d'une traversee
        # par un lien parent. ``relative_to`` compare composant par composant :
        # C:\lib2 n'est donc pas vu comme inclus dans C:\lib.
        real_target = _real_path(resolved_to_check)
        for base in allowed_bases:
            try:
                real_target.relative_to(_real_path(base))
                allowed = True
                break
            except (OSError, ValueError):
                continue
        if not allowed:
            return _err_response("Chemin non autorise.", category="permission", level="warning", log_module=__name__)

        # Fix audit 2026-05-25 (v1.5.3) Vague H : utiliser le chemin resolu
        # (deja valide ci-dessus) plutot que candidate, pour eviter qu'un
        # symlink contourne la verification d'autorisation.
        os.startfile(str(open_target))  # type: ignore[attr-defined]
        return {"ok": True}
    except (OSError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
