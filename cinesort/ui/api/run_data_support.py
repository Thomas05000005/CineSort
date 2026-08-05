"""Internal run data serialization helpers for the pywebview API facade."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import cinesort.domain.core as core
from cinesort.domain.conversions import to_int
from cinesort.infra.state import atomic_write_text
from cinesort.ui.api.settings_support import clamp_year

logger = logging.getLogger(__name__)

#: Nombre de numeros de ligne cites dans le message d'erreur (le reste est
#: resume par "...") — un plan entierement illisible ne doit pas produire un
#: message de plusieurs milliers de caracteres dans l'UI.
_MAX_REPORTED_INVALID_LINES = 5


class PlanCorruptedError(ValueError):
    """`plan.jsonl` contient des lignes illisibles : le plan chargé serait AMPUTÉ.

    Issue #519. Le correctif « propose » par l'audit etait d'ignorer la ligne
    fautive et de continuer. C'est le sens PERMISSIF sur un chemin destructif :
    `plan.jsonl` est le fichier que l'APPLY relit pour renommer et DEPLACER des
    dossiers de films. Un plan ampute de trois lignes s'appliquerait avec
    `errors=0` et trois films resteraient silencieusement en place, sans que
    personne ne puisse le savoir — exactement le « succes silencieux » proscrit.

    On leve donc, comme avant, mais en NOMMANT la perte : nombre de lignes
    illisibles, leurs numeros, et le nombre de lignes lisibles. Le fichier est
    parcouru EN ENTIER avant de lever, pour que le compteur soit complet et pas
    seulement « la premiere ligne qui a casse ».

    Herite de ``ValueError`` — donc de la meme famille que le
    ``json.JSONDecodeError`` leve auparavant : tous les appelants qui
    attrapaient deja `ValueError` (apply, get_plan, load_validation, resync)
    continuent de l'attraper, aucun chemin d'erreur existant n'est perdu.
    """

    def __init__(self, path: Any, invalid_lines: List[int], readable_rows: int) -> None:
        self.path = str(path)
        self.invalid_lines = list(invalid_lines)
        self.readable_rows = int(readable_rows)
        self.invalid_count = len(self.invalid_lines)
        head = ", ".join(str(n) for n in self.invalid_lines[:_MAX_REPORTED_INVALID_LINES])
        if self.invalid_count > _MAX_REPORTED_INVALID_LINES:
            head += ", ..."
        super().__init__(
            f"Plan corrompu: {self.invalid_count} ligne(s) illisible(s) "
            f"(ligne(s) {head}) sur {self.invalid_count + self.readable_rows} "
            f"entree(s) dans {self.path}"
        )


def write_plan_jsonl(plan_jsonl: Path, rows: List[Dict[str, Any]]) -> None:
    """Reecrit `plan.jsonl` EN ENTIER, de facon atomique ET durable.

    Ecrivain UNIQUE des reecritures de plan : `library_actions_support.
    _rematch_tmdb_and_update_plan` et `tmdb_support.enrich_tmdb_ids_by_title`
    derivaient tous les deux `plan_jsonl.with_suffix(suffix + ".tmp")` du meme
    `run_id`, soit le MEME chemin au caractere pres. Ils sont concurrents pour
    de vrai : `enrich_tmdb_ids_by_title` tourne dans le thread daemon
    `tmdb-enrich-<run_id>` lance en fin de scan (run_flow_support.py:634)
    pendant que le rematch est declenchable depuis l'UI sous
    `ThreadingHTTPServer`. C'est le defaut #732, mais sur les donnees de
    l'utilisateur : `plan.jsonl` est le fichier que l'APPLY relit pour
    renommer les dossiers sur disque. Aucun des deux n'avait de fsync non plus.

    `mkdir=False` : si le dossier du run a disparu, echouer (comme le faisait
    l'`open()` d'avant) plutot que ressusciter un run fantome.
    """
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    atomic_write_text(plan_jsonl, payload, mkdir=False)


def serialize_rows_for_payload(rows: List[core.PlanRow]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for row in rows:
        data = asdict(row)
        data["candidates"] = [asdict(candidate) for candidate in row.candidates]
        payload.append(data)
    return payload


def candidate_from_json(data: Dict[str, Any]) -> core.Candidate:
    tmdb_id: int | None
    try:
        tmdb_id = int(data["tmdb_id"]) if data.get("tmdb_id") is not None else None
    except (KeyError, OSError, TypeError, ValueError):
        tmdb_id = None
    year: int | None
    try:
        year = int(data["year"]) if data.get("year") is not None else None
    except (OSError, KeyError, TypeError, ValueError):
        year = None
    # R8-091 (filet F2-d) : champs collection TMDb perdus au reload (asymetrie de
    # round-trip, meme classe que R8-027/R8-090). Le jumeau plan_row_from_jsonable
    # (plan_support_core.py:82-86) les parse deja ; ici ils etaient absents ->
    # tout candidat voyait son id+nom de collection nulles au rechargement.
    collection_id: int | None
    try:
        collection_id = int(data["tmdb_collection_id"]) if data.get("tmdb_collection_id") not in (None, "", 0) else None
    except (OSError, KeyError, TypeError, ValueError):
        collection_id = None
    return core.Candidate(
        title=str(data.get("title") or ""),
        year=year,
        source=str(data.get("source") or "unknown"),
        tmdb_id=tmdb_id,
        poster_url=str(data.get("poster_url")) if data.get("poster_url") else None,
        score=float(data.get("score") or 0.0),
        note=str(data.get("note") or ""),
        tmdb_collection_id=collection_id,
        tmdb_collection_name=str(data.get("tmdb_collection_name") or "") or None,
    )


def _optional_str(data: Dict[str, Any], key: str) -> str | None:
    raw = data.get(key)
    return str(raw) if raw else None


def _str_list(data: Dict[str, Any], key: str) -> List[str]:
    return [str(s) for s in (data.get(key) or [])]


def _parse_candidates(data: Dict[str, Any]) -> List[core.Candidate]:
    raw = data.get("candidates")
    if not isinstance(raw, list):
        return []
    return [candidate_from_json(item) for item in raw if isinstance(item, dict)]


def _parse_warning_flags(data: Dict[str, Any]) -> List[str]:
    raw = data.get("warning_flags")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item or "").strip()]


def _str_with_default(data: Dict[str, Any], key: str, default: str = "") -> str:
    return str(data.get(key) or default)


def _parse_basic_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_id": _str_with_default(data, "row_id"),
        "kind": _str_with_default(data, "kind", "single"),
        "folder": _str_with_default(data, "folder"),
        "video": _str_with_default(data, "video"),
        "proposed_title": _str_with_default(data, "proposed_title"),
        "proposed_year": to_int(data.get("proposed_year"), 0),
        "proposed_source": _str_with_default(data, "proposed_source", "unknown"),
        "confidence": to_int(data.get("confidence"), 0),
        "confidence_label": _str_with_default(data, "confidence_label", "low"),
        "notes": _str_with_default(data, "notes"),
        "detected_year": to_int(data.get("detected_year"), 0),
        "detected_year_reason": _str_with_default(data, "detected_year_reason"),
    }


def _parse_optional_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nfo_path": _optional_str(data, "nfo_path"),
        "collection_name": _optional_str(data, "collection_name"),
        "tmdb_collection_id": to_int(data.get("tmdb_collection_id"), 0) or None,
        "tmdb_collection_name": _optional_str(data, "tmdb_collection_name"),
        "edition": _optional_str(data, "edition"),
        "source_root": _optional_str(data, "source_root"),
        # R8-027 (F2-d, F-META-01) : row_from_json (reload apply post-redemarrage) ne
        # reparsait PAS nfo_runtime alors que l'autre deserialiseur (plan_support_core:110)
        # le parse -> apres restart, la detection "duree -> autre film" + la desambiguisation
        # +/-10 min etaient degradees (nfo_runtime=None). On le restaure (meme idiome que
        # tmdb_collection_id : to_int defaut 0 -> None, comportement absent/invalide preserve).
        "nfo_runtime": to_int(data.get("nfo_runtime"), 0) or None,
    }


def _parse_subtitle_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "subtitle_count": to_int(data.get("subtitle_count"), 0),
        "subtitle_languages": _str_list(data, "subtitle_languages"),
        "subtitle_formats": _str_list(data, "subtitle_formats"),
        "subtitle_missing_langs": _str_list(data, "subtitle_missing_langs"),
        "subtitle_orphans": to_int(data.get("subtitle_orphans"), 0),
    }


def _parse_tv_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """AUDIT 2026-06-10 (REAL 2/2) : restaure les champs TV (absents avant ->
    remis a None). Sans eux, apres redemarrage de l'app (RunState plus en
    memoire), apply rechargeait les rows via plan.jsonl puis apply_tv_episode
    renommait avec season=0/episode=0 -> fichiers TV 'S00E00 - .ext' (violation
    invariant renommage + perte d'info)."""

    def _opt_int(key: str) -> Optional[int]:
        v = data.get(key)
        return int(v) if v not in (None, "") else None

    return {
        "tv_series_name": _optional_str(data, "tv_series_name"),
        "tv_season": _opt_int("tv_season"),
        "tv_episode": _opt_int("tv_episode"),
        "tv_episode_title": _optional_str(data, "tv_episode_title"),
        "tv_tmdb_series_id": _opt_int("tv_tmdb_series_id"),
    }


def row_from_json(data: Dict[str, Any]) -> core.PlanRow:
    return core.PlanRow(
        candidates=_parse_candidates(data),
        warning_flags=_parse_warning_flags(data),
        **_parse_basic_fields(data),
        **_parse_optional_fields(data),
        **_parse_subtitle_fields(data),
        **_parse_tv_fields(data),
    )


def load_rows_from_plan_jsonl(run_paths: Any) -> List[core.PlanRow]:
    """Charge le plan d'un run. Refuse un plan AMPUTE (issue #519).

    Deux formes de perte silencieuse existaient ici :

    1. ``json.loads`` sans garde : la premiere ligne corrompue faisait remonter
       un ``JSONDecodeError`` nu. Le refus etait correct (sens restrictif), mais
       le message ne disait ni combien de lignes etaient touchees ni lesquelles,
       et l'analyse s'arretait a la premiere.
    2. ``if isinstance(data, dict)`` : une ligne JSON valide mais non-dict
       (``null``, ``[]``, un nombre) etait jetee **sans un mot**. Celle-la
       produisait bel et bien un plan ampute sans erreur — un film disparaissait
       du plan que l'apply execute.

    Les deux comptent desormais comme des lignes illisibles. Le fichier est lu
    en entier (compteur complet), puis ``PlanCorruptedError`` est levee ; les
    lignes lisibles ne sont **jamais** retournees partiellement, sinon l'apply
    renommerait/deplacerait un sous-ensemble du plan avec ``errors=0``.
    """
    plan_path = run_paths.plan_jsonl
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan introuvable: {plan_path}")
    rows: List[core.PlanRow] = []
    invalid_lines: List[int] = []
    with plan_path.open("r", encoding="utf-8") as file_obj:
        for line_no, raw_line in enumerate(file_obj, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                invalid_lines.append(line_no)
                continue
            if isinstance(data, dict):
                rows.append(row_from_json(data))
            else:
                invalid_lines.append(line_no)
    if invalid_lines:
        error = PlanCorruptedError(plan_path, invalid_lines, len(rows))
        logger.error("%s", error)
        raise error
    return rows


def _invalidate_dashboard_cache(api: Any, run_paths: Any) -> None:
    """Supprime dashboard_cache.json (best-effort).

    AUDIT 2026-07-13 (HIGH-17) : la signature du cache dashboard est calculee
    sur plan.jsonl (mtime/taille, dashboard_cache_support.py:37) alors que le
    payload est construit depuis RunState.rows. Une reecriture du plan change la
    signature : un cache ecrit entre la reecriture et la resynchronisation
    memoire serait valide au sens de load_dashboard_cache tout en contenant des
    donnees perimees (empoisonnement persistant, survit au redemarrage). On le
    purge donc a chaque reecriture du plan.
    """
    try:
        cache_path = api._dashboard_cache_path(run_paths)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("dashboard cache path indisponible: %s", exc)
        return
    try:
        cache_path.unlink(missing_ok=True)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("purge dashboard cache impossible path=%s: %s", cache_path, exc)


def resync_run_state_rows(api: Any, run_id: str) -> bool:
    """Recharge RunState.rows depuis plan.jsonl apres une reecriture du plan.

    AUDIT 2026-07-13 (HIGH-17 / HIGH-19) : `rs.rows` n'etait assigne QU'UNE fois
    (fin de scan, run_flow_support.py:490) alors que plusieurs chemins
    reecrivent plan.jsonl apres coup (re-match TMDb d'un rescan, enrichissement
    tmdb_id). Or tous les lecteurs PREFERENT le snapshot memoire au fichier
    (history_support._get_plan_impl, apply_support.run_context_for_apply,
    dashboard_support, run_read_support) : sans resynchronisation, l'UI
    reaffichait l'ancien match et surtout l'apply renommait les dossiers avec
    l'ANCIEN titre/annee/edition, tant que l'app n'avait pas redemarre.

    Best-effort : si le run n'est pas en memoire (les lecteurs relisent alors
    plan.jsonl directement) ou si le plan est illisible, on laisse l'etat en
    place plutot que de le corrompre.

    Returns:
        True si le snapshot memoire a ete rafraichi.
    """
    rid = str(run_id or "").strip()
    if not rid:
        return False
    try:
        run_state = api._get_run(rid)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.warning("resync_run_state_rows: _get_run echoue run_id=%s: %s", rid, exc)
        return False
    if run_state is None:
        return False

    run_paths = getattr(run_state, "paths", None)
    if run_paths is None:
        return False
    try:
        rows = load_rows_from_plan_jsonl(run_paths)
    except (OSError, AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("resync_run_state_rows: relecture plan.jsonl echouee run_id=%s: %s", rid, exc)
        return False

    lock = getattr(run_state, "lock", None)
    if lock is None:
        run_state.rows = rows
    else:
        with lock:
            run_state.rows = rows

    _invalidate_dashboard_cache(api, run_paths)
    return True


# Fix audit 2026-05-25 (v1.5.4) Vague I : source unique de verite pour le
# compteur "nombre de films d'un run". Le bug 853 vs 855 venait du fait que
# - dashboard / library / apply : utilisaient stats.planned_rows (snapshot DB
#   fige au scan, potentiellement obsolete si plan.jsonl reecrit)
# - validation / doublons : utilisaient len(rows) charge live depuis plan.jsonl
# On aligne tout le monde sur count_plan_rows() = nombre de PlanRow non-null
# valides dans plan.jsonl, source faisant autorite. Si plan.jsonl est
# inaccessible, fallback sur stats.planned_rows pour ne pas casser l'UI.
def compute_total_fallback(
    run_row: Dict[str, Any] | None,
    stats_obj: Dict[str, Any] | None,
) -> int:
    """Calcule le fallback "nombre de films" quand plan.jsonl est inaccessible.

    Fix audit 2026-05-26 (v1.5.6) Vague L : count-2. Avant ce helper,
    chaque endpoint avait son propre ordre de priorite divergent :
      - dashboard_support.py:80 : stats.planned_rows -> run_row.total -> 0
      - history_support.py:228  : run_row.total -> stats.planned_rows -> 0
      - run_flow_support.py:772 : run_row.total -> 0
    Resultat : trois compteurs distincts pour le meme run quand plan.jsonl
    manque.

    Choix senior : on PRIORISE stats.planned_rows car c'est le snapshot
    persiste a la fin du run, refletant le nombre de PlanRow effectivement
    ecrits dans plan.jsonl au moment de mark_run_done. run_row.total = total
    de dossiers DECOUVERTS pendant le scan (discover_total) — toujours >=
    planned_rows car certains dossiers explores sont ignores (pas de video)
    ou regroupes (multi-version d'un meme film). Pour un fallback qui doit
    approcher au plus pres len(plan.jsonl), planned_rows est le meilleur
    proxy. run_row.total ne sert que pour les runs RUNNING ou FAILED avant
    mark_run_done (stats absentes).

    Args:
        run_row: dict du run depuis store.run (peut etre None).
        stats_obj: dict deserialise de run_row.stats_json (peut etre None).

    Returns:
        Meilleure estimation entiere positive ou 0.
    """
    if isinstance(stats_obj, dict):
        try:
            planned = int(stats_obj.get("planned_rows") or 0)
            if planned > 0:
                return planned
        except (TypeError, ValueError):
            pass
    if isinstance(run_row, dict):
        try:
            total = int(run_row.get("total") or 0)
            if total > 0:
                return total
        except (TypeError, ValueError):
            pass
    return 0


def count_plan_rows(run_paths: Any, *, fallback: int = 0) -> int:
    """Retourne le nombre de PlanRow valides dans plan.jsonl.

    Source unique de verite pour tous les compteurs de films de l'UI.

    Args:
        run_paths: RunPaths avec .plan_jsonl.
        fallback: valeur si plan.jsonl absent ou illisible (defaut 0).

    Returns:
        Nombre de lignes JSONL non-vides qui contiennent un dict (1 PlanRow).
    """
    try:
        plan_path = run_paths.plan_jsonl
    except AttributeError:
        return int(fallback or 0)
    try:
        if not plan_path.exists():
            return int(fallback or 0)
    except (OSError, AttributeError):
        return int(fallback or 0)
    count = 0
    unreadable = 0
    try:
        with plan_path.open("r", encoding="utf-8") as file_obj:
            for line in file_obj:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    data = json.loads(line_s)
                except ValueError:
                    # Ligne malformee : elle ne peut pas etre comptee, mais elle
                    # n'est plus passee sous silence (issue #519).
                    unreadable += 1
                    continue
                if not isinstance(data, dict):
                    unreadable += 1
                elif data.get("row_id"):
                    count += 1
    except (OSError, PermissionError):
        return int(fallback or 0)
    if unreadable:
        # Issue #519 : ce compteur est la source unique de verite du "nombre de
        # films" affiche partout (dashboard, historique, bibliotheque). Sur un
        # plan corrompu il renvoie donc un nombre INFERIEUR a la realite. On ne
        # fabrique pas de nombre plausible a la place (le fallback
        # stats.planned_rows serait une mesure inventee) : on renvoie le compte
        # honnete des lignes exploitables, et on dit que le plan est ampute.
        # L'apply, lui, REFUSE ce plan (load_rows_from_plan_jsonl -> PlanCorruptedError).
        logger.warning(
            "count_plan_rows: %d ligne(s) illisible(s) dans %s — le compteur (%d) sous-estime le plan",
            unreadable,
            plan_path,
            count,
        )
    return count


def load_decisions_from_validation(api: Any, run_paths: Any, *, env_truthy_fn: Any) -> Dict[str, Dict[str, Any]]:
    validation_path = run_paths.validation_json
    if not validation_path.exists():
        return {}
    try:
        data = json.loads(validation_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        decisions: Dict[str, Dict[str, Any]] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, dict):
                decisions[key] = dict(value)
        return decisions
    except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError) as exc:
        state_dir_guess = api._state_dir
        try:
            state_dir_guess = run_paths.run_dir.parent.parent
        except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError):
            state_dir_guess = api._state_dir
        api._debug_log(
            state_dir=state_dir_guess,
            run_id=run_paths.run_id,
            enabled=env_truthy_fn("CINESORT_DEBUG"),
            message=f"_load_decisions_from_validation warning path={validation_path} error={exc}",
        )
        logger.debug("Validation JSON invalide ignoree path=%s err=%s", validation_path, exc)
        return {}


def merge_decisions(
    primary: Dict[str, Dict[str, Any]], fallback: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for key in set(primary.keys()) | set(fallback.keys()):
        out: Dict[str, Any] = {}
        fallback_value = fallback.get(key)
        if isinstance(fallback_value, dict):
            out.update(fallback_value)
        primary_value = primary.get(key)
        if isinstance(primary_value, dict):
            out.update(primary_value)
        merged[key] = out
    return merged


def normalize_decisions_for_rows(
    rows: List[core.PlanRow],
    decisions: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    safe: Dict[str, Dict[str, Any]] = {}
    incoming = decisions if isinstance(decisions, dict) else {}

    for row in rows:
        raw = incoming.get(row.row_id, {})
        raw = raw if isinstance(raw, dict) else {}
        ok = bool(raw.get("ok", False))
        title_in = str(raw.get("title") or row.proposed_title).strip()
        title = core.windows_safe(title_in) if title_in else core.windows_safe(row.proposed_title)
        year_raw = to_int(raw.get("year"), row.proposed_year)
        year = clamp_year(year_raw)
        if year == 0:
            year = clamp_year(int(row.proposed_year or 0))
        entry: Dict[str, Any] = {
            "ok": ok,
            "title": title,
            "year": year,
        }
        # Fix R6-03 : preserver le tri-etat `decision` lors du round-trip
        # disque vers validation.json. Sans cela, l'etat `deferred` (Reporter)
        # est perdu apres save+reload et redevient indistinguable d'un
        # `rejected` (ok=false). Backward compat : on n'ajoute la cle que si
        # la valeur entrante est valide dans {accepted, rejected, deferred} ;
        # sinon on garde la shape legacy `{ok, title, year}`.
        decision_raw = raw.get("decision")
        if isinstance(decision_raw, str) and decision_raw in (
            "accepted",
            "rejected",
            "deferred",
        ):
            entry["decision"] = decision_raw
        safe[row.row_id] = entry
    return safe
