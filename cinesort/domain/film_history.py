"""Historique par film — reconstruction de la timeline d'un film a travers les runs.

Collecte les evenements (scan, score, apply, anomaly) depuis la BDD et les plan.jsonl
pour reconstituer l'historique complet d'un film specifique.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.domain.title_helpers import strip_trailing_year_if_equal

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

    # LOTD-DUP-TITLE-YEAR (revue round 1) : meme tolerance que movie_key —
    # "Titre 2005"|2005 et "Titre"|2005 partagent l'identite (timeline film),
    # "Blade Runner 2049"|2017 reste distinct. Le proposed_title n'est pas modifie.
    year = int(getattr(row, "proposed_year", 0) or 0)
    raw_title = str(getattr(row, "proposed_title", "") or "")
    title = _norm_title(strip_trailing_year_if_equal(raw_title, year))
    return f"title:{title}|{year}{ed_suffix}"


# ---------------------------------------------------------------------------
# Lecture des plan.jsonl
# ---------------------------------------------------------------------------


def _resolve_run_dir(state_dir: Path, run_id: str) -> Path:
    """Resout le dossier d'un run. AUDIT 2026-06-10 (REAL 2/2) : les vrais
    dossiers sont `runs/tri_films_<run_id>` (infra.state.new_run), pas
    `runs/<run_id>` -> get_film_history/list_films_with_history ne trouvaient
    jamais plan.jsonl et retournaient 0 evenement / 0 film. domain ne peut pas
    importer infra.state (import-linter) : on duplique la convention de nommage,
    en tolerant aussi un dossier non prefixe (robustesse)."""
    runs = state_dir / "runs"
    prefixed = runs / f"tri_films_{run_id}"
    if prefixed.exists():
        return prefixed
    bare = runs / run_id
    if bare.exists():
        return bare
    return prefixed  # defaut : convention canonique


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


def identity_key_from_dict(data: Dict[str, Any]) -> str:
    """Calcule la cle d'identite depuis un dict plan.jsonl (sans instancier PlanRow).

    Variante de :func:`film_identity_key` qui opere sur un dict brut (plan.jsonl
    deserialise) plutot que sur un PlanRow. Source unique partagee entre le
    domain (timeline) et l'UI (film_support.get_film_full).
    """
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

    # R2 (revue round 2) : identity_key_from_dict est LE chemin vivant
    # (film_support.get_film_full + timeline) ; film_identity_key ne l'est pas.
    # La tolerance d'annee doit donc etre ici pour que "Le Grand Voyage 2005" et
    # "Le Grand Voyage" (annee 2005) partagent une timeline unique.
    year = int(data.get("proposed_year") or 0)
    title = _norm_title(strip_trailing_year_if_equal(str(data.get("proposed_title") or ""), year))
    return f"title:{title}|{year}{ed_suffix}"


# ---------------------------------------------------------------------------
# Reconstruction de la timeline
# ---------------------------------------------------------------------------


# Meme defaut que `ApplyRepository.list_apply_batches_for_run(limit=10)` : la
# timeline s'appuyait sur ce defaut implicite, la version groupee doit le rendre
# explicite pour ne pas changer silencieusement le nombre de batches examines.
_TIMELINE_BATCHES_PER_RUN = 10


def _collect_timeline_matches(
    film_id: str,
    state_dir: Path,
    runs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Pour chaque run, retrouve la ligne de plan.jsonl qui porte `film_id`.

    Phase PURE FICHIERS, sans aucun acces DB : c'est elle qui fournit la liste
    des couples (run_id, row_id) que les requetes groupees vont ensuite servir
    en un nombre CONSTANT d'allers-retours SQLite (issue #577).
    """
    matches: List[Dict[str, Any]] = []
    for run in runs:
        run_id = str(run.get("run_id") or "")
        run_ts = float(run.get("start_ts") or run.get("created_ts") or 0)
        if not run_id:
            continue

        # Chemin du plan.jsonl pour ce run
        run_dir = _resolve_run_dir(state_dir, run_id)
        plan_path = run_dir / "plan.jsonl"
        plan_rows = _load_plan_rows_from_jsonl(plan_path)

        # Chercher le film dans ce run
        for row_data in plan_rows:
            if identity_key_from_dict(row_data) == film_id:
                matches.append(
                    {
                        "run_id": run_id,
                        "run_ts": run_ts,
                        "row": row_data,
                        "row_id": str(row_data.get("row_id") or ""),
                    }
                )
                break
    return matches


def get_film_timeline(
    film_id: str,
    state_dir: Path,
    store: Any,
) -> Dict[str, Any]:
    """Reconstruit la timeline complete d'un film a travers tous les runs.

    Retourne un dict avec film_id, title, year, events[], current_score, scan_count, apply_count.

    Issue #577 : le nombre de requetes SQLite ne depend plus du nombre de runs
    ou de batches. Trois appels groupes (rapports qualite, batches, operations)
    remplacent les `1 + 2 x runs + runs x batches` requetes unitaires d'avant.
    """
    # Recuperer tous les runs tries par date
    runs = store.run.get_runs_summary(limit=100)
    runs.sort(key=lambda r: float(r.get("start_ts") or r.get("created_ts") or 0))

    matches = _collect_timeline_matches(film_id, state_dir, runs)

    # --- Requetes groupees (nombre INDEPENDANT du nombre de runs) ------------
    quality_pairs = [(m["run_id"], m["row_id"]) for m in matches if m["row_id"]]
    reports = store.quality.get_quality_reports_for_pairs(pairs=quality_pairs)

    run_ids_with_row = [m["run_id"] for m in matches if m["row_id"]]
    batches_by_run = store.apply.list_apply_batches_for_runs(
        run_ids=run_ids_with_row,
        limit_per_run=_TIMELINE_BATCHES_PER_RUN,
    )
    wanted_batch_ids: List[str] = []
    for run_id in run_ids_with_row:
        for batch in batches_by_run.get(run_id) or []:
            if batch.get("dry_run"):
                continue
            batch_id = str(batch.get("batch_id") or "")
            if batch_id:
                wanted_batch_ids.append(batch_id)
    ops_by_batch_row = store.apply.list_apply_operations_for_rows(
        batch_ids=wanted_batch_ids,
        row_ids=[m["row_id"] for m in matches if m["row_id"]],
    )

    events: List[Dict[str, Any]] = []
    title = ""
    year = 0
    current_score: Optional[int] = None
    previous_score: Optional[int] = None
    scan_count = 0
    apply_count = 0

    for match in matches:
        run_id = str(match["run_id"])
        run_ts = float(match["run_ts"])
        matched_row: Dict[str, Any] = match["row"]
        matched_row_id = str(match["row_id"])

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
            qr = reports.get((run_id, matched_row_id))
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
            batches = batches_by_run.get(run_id) or []
            for batch in batches:
                if batch.get("dry_run"):
                    continue
                batch_id = str(batch.get("batch_id") or "")
                if not batch_id:
                    continue
                ops = ops_by_batch_row.get((batch_id, matched_row_id)) or []
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
    runs = store.run.get_runs_summary(limit=5)
    last_run = None
    for r in runs:
        if str(r.get("status") or "") == "DONE":
            last_run = r
            break
    if not last_run:
        return []

    run_id = str(last_run.get("run_id") or "")
    run_dir = _resolve_run_dir(state_dir, run_id)
    plan_path = run_dir / "plan.jsonl"
    plan_rows = _load_plan_rows_from_jsonl(plan_path)

    selected_rows = plan_rows[:limit]
    # Issue #577 (meme defaut, meme fonction voisine) : une requete par film,
    # jusqu'a 200 avec le plafond de l'endpoint. Une seule requete groupee ici.
    reports = store.quality.get_quality_reports_for_pairs(
        pairs=[(run_id, str(row_data.get("row_id") or "")) for row_data in selected_rows],
    )

    films: List[Dict[str, Any]] = []
    for row_data in selected_rows:
        fid = identity_key_from_dict(row_data)
        row_id = str(row_data.get("row_id") or "")
        score: Optional[int] = None
        tier = ""
        if row_id:
            qr = reports.get((run_id, row_id))
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
