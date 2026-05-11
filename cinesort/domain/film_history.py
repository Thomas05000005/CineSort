"""Historique par film — reconstruction de la timeline d'un film a travers les runs.

Collecte les evenements (scan, score, apply, anomaly) depuis la BDD et les plan.jsonl
pour reconstituer l'historique complet d'un film specifique.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identite stable d'un film a travers les runs
# ---------------------------------------------------------------------------


def _extract_tmdb_id(row: Any) -> Optional[int]:
    """Extrait le tmdb_id depuis les candidates du PlanRow."""
    candidates = getattr(row, "candidates", None) or []
    for c in candidates:
        tid = getattr(c, "tmdb_id", None)
        if tid and isinstance(tid, int) and tid > 0:
            return tid
    return None


def _norm_title(title: str) -> str:
    """Normalisation minimale du titre pour la cle d'identite."""
    return title.strip().lower()


def film_identity_key(row: Any) -> str:
    """Calcule une cle d'identite stable pour un film a travers les runs.

    Priorite 1 : tmdb_id (stable, unique)
    Priorite 2 : titre+annee normalise (fallback)
    L'edition est incluse pour distinguer les multi-versions.
    """
    edition = str(getattr(row, "edition", None) or "").strip().lower()
    ed_suffix = f"|{edition}" if edition else ""

    tmdb_id = _extract_tmdb_id(row)
    if tmdb_id:
        return f"tmdb:{tmdb_id}{ed_suffix}"

    title = _norm_title(str(getattr(row, "proposed_title", "") or ""))
    year = int(getattr(row, "proposed_year", 0) or 0)
    return f"title:{title}|{year}{ed_suffix}"


# ---------------------------------------------------------------------------
# Lecture des plan.jsonl
# ---------------------------------------------------------------------------


def _load_plan_rows_from_jsonl(plan_path: Path) -> List[Dict[str, Any]]:
    """Charge un plan.jsonl et retourne les dicts bruts. Skip les lignes invalides."""
    rows: List[Dict[str, Any]] = []
    if not plan_path.is_file():
        return rows
    try:
        with open(plan_path, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        rows.append(data)
                except (json.JSONDecodeError, ValueError):
                    logger.debug("plan.jsonl ligne %d invalide dans %s", line_no, plan_path)
    except (OSError, PermissionError) as exc:
        logger.debug("Impossible de lire %s: %s", plan_path, exc)
    return rows


def _identity_key_from_dict(data: Dict[str, Any]) -> str:
    """Calcule la cle d'identite depuis un dict plan.jsonl (sans instancier PlanRow)."""
    edition = str(data.get("edition") or "").strip().lower()
    ed_suffix = f"|{edition}" if edition else ""

    # Chercher tmdb_id dans les candidates
    tmdb_id = None
    for c in data.get("candidates") or []:
        if isinstance(c, dict):
            tid = c.get("tmdb_id")
            if tid and isinstance(tid, int) and tid > 0:
                tmdb_id = tid
                break

    if tmdb_id:
        return f"tmdb:{tmdb_id}{ed_suffix}"

    title = _norm_title(str(data.get("proposed_title") or ""))
    year = int(data.get("proposed_year") or 0)
    return f"title:{title}|{year}{ed_suffix}"


# ---------------------------------------------------------------------------
# Reconstruction de la timeline
# ---------------------------------------------------------------------------


def get_film_timeline(
    film_id: str,
    state_dir: Path,
    store: Any,
) -> Dict[str, Any]:
    """Reconstruit la timeline complete d'un film a travers tous les runs.

    Retourne un dict avec film_id, title, year, events[], current_score, scan_count, apply_count.
    """
    # Recuperer tous les runs tries par date
    runs = store.get_runs_summary(limit=100)
    runs.sort(key=lambda r: float(r.get("start_ts") or r.get("created_ts") or 0))

    events: List[Dict[str, Any]] = []
    title = ""
    year = 0
    current_score: Optional[int] = None
    previous_score: Optional[int] = None
    scan_count = 0
    apply_count = 0

    for run in runs:
        run_id = str(run.get("run_id") or "")
        run_ts = float(run.get("start_ts") or run.get("created_ts") or 0)
        if not run_id:
            continue

        # Chemin du plan.jsonl pour ce run
        run_dir = state_dir / "runs" / run_id
        plan_path = run_dir / "plan.jsonl"
        plan_rows = _load_plan_rows_from_jsonl(plan_path)

        # Chercher le film dans ce run
        matched_row: Optional[Dict[str, Any]] = None
        matched_row_id: Optional[str] = None
        for row_data in plan_rows:
            if _identity_key_from_dict(row_data) == film_id:
                matched_row = row_data
                matched_row_id = str(row_data.get("row_id") or "")
                break

        if not matched_row:
            continue

        # Mettre a jour le titre/annee (derniere valeur connue)
        title = str(matched_row.get("proposed_title") or title)
        year = int(matched_row.get("proposed_year") or year)

        # Evenement scan
        scan_count += 1
        scan_event: Dict[str, Any] = {
            "type": "scan",
            "run_id": run_id,
            "ts": run_ts,
            "confidence": int(matched_row.get("confidence") or 0),
            "source": str(matched_row.get("proposed_source") or ""),
            "warnings": matched_row.get("warning_flags") or [],
            "edition": matched_row.get("edition"),
        }
        events.append(scan_event)

        # Evenement score (quality report)
        if matched_row_id:
            qr = store.get_quality_report(run_id=run_id, row_id=matched_row_id)
            if qr:
                score = int(qr.get("score") or 0)
                delta = (score - previous_score) if previous_score is not None else 0
                events.append(
                    {
                        "type": "score",
                        "run_id": run_id,
                        "ts": float(qr.get("ts") or run_ts),
                        "score": score,
                        "tier": str(qr.get("tier") or ""),
                        "delta": delta,
                    }
                )
                previous_score = score
                current_score = score

        # Evenements apply (operations sur ce row_id)
        if matched_row_id:
            batches = store.list_apply_batches_for_run(run_id=run_id)
            for batch in batches:
                if batch.get("dry_run"):
                    continue
                batch_id = str(batch.get("batch_id") or "")
                if not batch_id:
                    continue
                ops = store.list_apply_operations_by_row(batch_id=batch_id, row_id=matched_row_id)
                if ops:
                    apply_count += 1
                    op_list = [
                        {
                            "op": str(op.get("op_type") or ""),
                            "from": str(op.get("src_path") or ""),
                            "to": str(op.get("dst_path") or ""),
                            "undo_status": str(op.get("undo_status") or "PENDING"),
                        }
                        for op in ops
                    ]
                    events.append(
                        {
                            "type": "apply",
                            "run_id": run_id,
                            "ts": float(batch.get("ended_ts") or batch.get("started_ts") or run_ts),
                            "operations": op_list,
                        }
                    )

    # Trier par timestamp
    events.sort(key=lambda e: float(e.get("ts") or 0))

    return {
        "film_id": film_id,
        "title": title,
        "year": year,
        "events": events,
        "current_score": current_score,
        "scan_count": scan_count,
        "apply_count": apply_count,
    }


# ---------------------------------------------------------------------------
# Liste des films avec resume d'historique
# ---------------------------------------------------------------------------


def list_films_overview(
    state_dir: Path,
    store: Any,
    *,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retourne la liste des films du dernier run avec un resume d'historique.

    Pour chaque film : film_id, title, year, score, scan_count estimatif.
    """
    # Dernier run termine
    runs = store.get_runs_summary(limit=5)
    last_run = None
    for r in runs:
        if str(r.get("status") or "") == "DONE":
            last_run = r
            break
    if not last_run:
        return []

    run_id = str(last_run.get("run_id") or "")
    run_dir = state_dir / "runs" / run_id
    plan_path = run_dir / "plan.jsonl"
    plan_rows = _load_plan_rows_from_jsonl(plan_path)

    films: List[Dict[str, Any]] = []
    for row_data in plan_rows[:limit]:
        fid = _identity_key_from_dict(row_data)
        row_id = str(row_data.get("row_id") or "")
        score: Optional[int] = None
        tier = ""
        if row_id:
            qr = store.get_quality_report(run_id=run_id, row_id=row_id)
            if qr:
                score = int(qr.get("score") or 0)
                tier = str(qr.get("tier") or "")
        films.append(
            {
                "film_id": fid,
                "title": str(row_data.get("proposed_title") or ""),
                "year": int(row_data.get("proposed_year") or 0),
                "edition": row_data.get("edition"),
                "score": score,
                "tier": tier,
                "row_id": row_id,
            }
        )

    return films
