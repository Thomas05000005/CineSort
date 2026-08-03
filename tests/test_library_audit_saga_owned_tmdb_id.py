"""#714 — l'audit des sagas lisait une clef FANTOME `tmdb_id` sur une PlanRow.

`PlanRow` (`cinesort/domain/core.py`) n'a aucun `tmdb_id` top-level : le tmdb_id
reel vit sur les `Candidate`. Le seul producteur de `row["tmdb_id"]` est
`film_support.overlay_tmdb_override`, applique par `_enrich_plan_payload`
uniquement pour les overrides TMDb MANUELS. Donc `owned_tmdb_ids` restait vide,
le match primaire de `get_incomplete_sagas` etait mort, et la completude des
sagas reposait sur le seul repli (titre, annee) — qui echoue des que le titre
propose n'est pas celui de TMDb (langue differente, edition, ponctuation) :
l'utilisateur voyait des films qu'il POSSEDE listes comme manquants.

Les rows de ces tests sont serialisees par le VRAI serialiseur de production
(`run_data_support.serialize_rows_for_payload`), jamais ecrites a la main : un
dict fabrique avec une clef `tmdb_id` reintroduirait exactement le mirage qui a
laisse vivre le defaut.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import cinesort.domain.core as core
from cinesort.ui.api import library_audit_support
from cinesort.ui.api.library_audit_support import (
    _load_plan_rows_with_collection,
    _plan_row_tmdb_id,
    get_incomplete_sagas,
)
from cinesort.ui.api.run_data_support import serialize_rows_for_payload

_DIE_HARD_COLLECTION_ID = 1570


def _candidate(
    title: str, year: int | None, tmdb_id: int | None, *, score: float = 0.9, source: str = "tmdb"
) -> core.Candidate:
    return core.Candidate(title=title, year=year, source=source, tmdb_id=tmdb_id, score=score)


def _plan_row(
    row_id: str,
    title: str,
    year: int,
    candidates: List[core.Candidate],
    *,
    collection_id: int | None = _DIE_HARD_COLLECTION_ID,
) -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="single",
        folder=f"C:/Films/{title} ({year})",
        video=f"{title}.mkv",
        proposed_title=title,
        proposed_year=year,
        proposed_source="tmdb",
        confidence=90,
        confidence_label="high",
        candidates=candidates,
        tmdb_collection_id=collection_id,
        tmdb_collection_name="Die Hard Collection" if collection_id else None,
    )


def _payload(rows: List[core.PlanRow]) -> List[Dict[str, Any]]:
    """Serialisation de production : c'est exactement ce que rend get_plan."""
    return serialize_rows_for_payload(rows)


def _api_serving(payload: List[Dict[str, Any]]) -> Any:
    api = MagicMock()
    api.run.get_plan.return_value = {"ok": True, "rows": payload}
    return api


# ── Premisse : la clef top-level n'existe pas ────────────────────────


def test_plan_row_has_no_top_level_tmdb_id() -> None:
    """Premisse du defaut, verifiee sur le dataclass ET sur sa serialisation."""
    assert "tmdb_id" not in {f.name for f in fields(core.PlanRow)}

    row = _plan_row("r1", "Die Hard", 1988, [_candidate("Die Hard", 1988, 562)])
    assert "tmdb_id" not in _payload([row])[0]


# ── Resolution du tmdb_id ────────────────────────────────────────────


def test_tmdb_id_resolved_from_the_matching_candidate() -> None:
    row = _payload([_plan_row("r1", "Die Hard", 1988, [_candidate("Die Hard", 1988, 562)])])[0]
    assert _plan_row_tmdb_id(row) == 562


def test_manual_override_wins_over_candidates() -> None:
    """`overlay_tmdb_override` pose `tmdb_id`/`chosen_tmdb_id` : la priorite du
    helper canonique `_resolve_chosen_tmdb_id` doit rester respectee."""
    row = _payload([_plan_row("r1", "Die Hard", 1988, [_candidate("Die Hard", 1988, 562)])])[0]
    row["tmdb_id"] = 999
    row["chosen_tmdb_id"] = 999
    assert _plan_row_tmdb_id(row) == 999


def test_non_matching_candidate_is_never_used() -> None:
    """`PlanRow.candidates` n'est PAS trie par score : `pick_best_candidate`
    classe une copie locale. Un candidat en tete de liste qui ne correspond pas
    a la proposition designe un AUTRE film — l'utiliser declarerait possede un
    film absent."""
    row = _payload(
        [
            _plan_row(
                "r1",
                "Die Hard",
                1988,
                [
                    _candidate("Die Hard 2", 1990, 1573, score=0.2),
                    _candidate("Die Hard", 1988, 562, score=0.95),
                ],
            )
        ]
    )[0]
    assert _plan_row_tmdb_id(row) == 562


def test_no_candidate_matches_returns_none() -> None:
    row = _payload([_plan_row("r1", "Un film inconnu", 2001, [_candidate("Autre chose", 1999, 42)])])[0]
    assert _plan_row_tmdb_id(row) is None


def test_candidate_without_tmdb_id_returns_none() -> None:
    """Un candidat NFO/nom n'a pas de tmdb_id : ne rien inventer."""
    row = _payload([_plan_row("r1", "Die Hard", 1988, [_candidate("Die Hard", 1988, None, source="nfo")])])[0]
    assert _plan_row_tmdb_id(row) is None


def test_missing_year_is_not_a_wildcard() -> None:
    """Une row non resolue (`_build_unresolved_row`) a `proposed_year = 0` et des
    candidats sans annee : matcher sur le seul titre reviendrait a revendiquer la
    possession d'un film que rien n'a identifie."""
    row = _payload([_plan_row("r1", "Die Hard", 0, [_candidate("Die Hard", None, 562)])])[0]
    assert _plan_row_tmdb_id(row) is None


def test_highest_scoring_match_wins_on_title_year_tie() -> None:
    row = _payload(
        [
            _plan_row(
                "r1",
                "Die Hard",
                1988,
                [
                    _candidate("Die Hard", 1988, 111, score=0.4),
                    _candidate("Die Hard", 1988, 562, score=0.99),
                ],
            )
        ]
    )[0]
    assert _plan_row_tmdb_id(row) == 562


def test_load_plan_rows_exposes_the_resolved_tmdb_id() -> None:
    payload = _payload([_plan_row("r1", "Die Hard", 1988, [_candidate("Die Hard", 1988, 562)])])
    rows = _load_plan_rows_with_collection(_api_serving(payload), "run-1")
    assert [r["tmdb_id"] for r in rows] == [562]


# ── Symptome utilisateur : faux « films manquants » ──────────────────


@patch("cinesort.ui.api.library_audit_support._fetch_collection_parts")
@patch("cinesort.ui.api.library_audit_support._resolve_latest_run_id", return_value="run-1")
def test_owned_film_with_localized_title_is_not_reported_missing(_rid, mock_parts) -> None:
    """Le repli (titre, annee) echoue des que le titre propose differe de celui
    de TMDb — cas nominal d'une bibliotheque francaise face a une collection
    fetchee en une autre langue. Seul le match par tmdb_id sauve la mise.
    """
    payload = _payload(
        [
            _plan_row("r1", "Piege de cristal", 1988, [_candidate("Piege de cristal", 1988, 562)]),
            _plan_row("r2", "58 minutes pour vivre", 1990, [_candidate("58 minutes pour vivre", 1990, 1573)]),
        ]
    )
    mock_parts.return_value = [
        {"tmdb_id": 562, "title": "Die Hard", "year": 1988},
        {"tmdb_id": 1573, "title": "Die Hard 2", "year": 1990},
        {"tmdb_id": 1571, "title": "Die Hard with a Vengeance", "year": 1995},
    ]

    result = get_incomplete_sagas(_api_serving(payload))

    assert result["ok"]
    assert len(result["sagas"]) == 1, f"une seule saga attendue : {result['sagas']}"
    saga = result["sagas"][0]
    missing_ids = {f["tmdb_id"] for f in saga["missing_films"]}
    assert missing_ids == {1571}, (
        f"films possedes signales manquants : {sorted(missing_ids)} — le match "
        "primaire par tmdb_id est mort, seul le repli titre+annee opere."
    )
    assert saga["missing_count"] == 1
    assert {f["tmdb_id"] for f in saga["owned_films"]} == {562, 1573}


@patch("cinesort.ui.api.library_audit_support._fetch_collection_parts")
@patch("cinesort.ui.api.library_audit_support._resolve_latest_run_id", return_value="run-1")
def test_complete_saga_with_localized_titles_disappears(_rid, mock_parts) -> None:
    payload = _payload(
        [
            _plan_row("r1", "Piege de cristal", 1988, [_candidate("Piege de cristal", 1988, 562)]),
            _plan_row("r2", "58 minutes pour vivre", 1990, [_candidate("58 minutes pour vivre", 1990, 1573)]),
        ]
    )
    mock_parts.return_value = [
        {"tmdb_id": 562, "title": "Die Hard", "year": 1988},
        {"tmdb_id": 1573, "title": "Die Hard 2", "year": 1990},
    ]

    result = get_incomplete_sagas(_api_serving(payload))

    assert result["sagas"] == [], "saga complete listee comme incomplete"


@patch("cinesort.ui.api.library_audit_support._fetch_collection_parts")
@patch("cinesort.ui.api.library_audit_support._resolve_latest_run_id", return_value="run-1")
def test_genuinely_missing_film_is_still_reported(_rid, mock_parts) -> None:
    """Non-regression : le correctif ne doit pas rendre l'audit aveugle."""
    payload = _payload([_plan_row("r1", "Piege de cristal", 1988, [_candidate("Piege de cristal", 1988, 562)])])
    mock_parts.return_value = [
        {"tmdb_id": 562, "title": "Die Hard", "year": 1988},
        {"tmdb_id": 1573, "title": "Die Hard 2", "year": 1990},
    ]

    result = get_incomplete_sagas(_api_serving(payload))

    assert len(result["sagas"]) == 1
    assert [f["tmdb_id"] for f in result["sagas"][0]["missing_films"]] == [1573]


def test_module_reads_no_ghost_key_on_plan_rows() -> None:
    """Ratchet : plus aucune clef fantome lue sur une row de plan dans ce module.

    Le canari enregistre toute clef lue qui n'est ni un champ du dataclass
    PlanRow, ni un enrichissement REELLEMENT pose par le payload.

    Dette hors perimetre de ce lot (meme famille, autres fichiers) : le repli
    `nfo_title` — champ inexistant sur PlanRow et pose par aucun producteur —
    survit dans `library_support.py:422`, `history_support.py:332/550/578`,
    `tmdb_support.py:196` et `web/dashboard/components/film-detail.js`. Il est
    supprime ici, pas ailleurs : ce test ne couvre que ce module.
    """
    resolved = _plan_row("r1", "Die Hard", 1988, [_candidate("Die Hard", 1988, 562)])
    # 2e row a titre VIDE : elle force la branche de repli du titre, seul endroit
    # ou une clef fantome peut se cacher derriere un court-circuit `or`.
    untitled = _plan_row("r2", "Die Hard", 1988, [], collection_id=None)
    untitled.proposed_title = ""

    known = {f.name for f in fields(core.PlanRow)}
    # Clefs REELLEMENT ajoutees au payload par _enrich_plan_payload / overlay.
    enriched = {"display_title", "auto_approvable", "tmdb_id", "chosen_tmdb_id"}
    seen_unknown: List[str] = []

    class _Canary(dict):
        def get(self, key: Any, default: Any = None) -> Any:  # type: ignore[override]
            if key not in known and key not in enriched:
                seen_unknown.append(str(key))
            return super().get(key, default)

    canaries = [_Canary(payload) for payload in _payload([resolved, untitled])]
    rows = _load_plan_rows_with_collection(_api_serving(canaries), "run-1")

    assert not seen_unknown, f"clef(s) fantome(s) lue(s) sur une PlanRow : {sorted(set(seen_unknown))}"
    assert [r["tmdb_id"] for r in rows] == [562, None]
    assert rows[1]["title"] == ""


def test_library_audit_support_is_the_only_saga_reader() -> None:
    """Garde-fou de perimetre : `_collect_owned_by_collection` doit consommer la
    valeur DEJA resolue, jamais re-lire la clef brute sur la row de plan."""
    rows = [{"tmdb_id": 562, "title": "Die Hard", "year": 1988, "tmdb_collection_id": _DIE_HARD_COLLECTION_ID}]
    grouped = library_audit_support._collect_owned_by_collection(rows)
    bucket = grouped[_DIE_HARD_COLLECTION_ID]
    assert [f["tmdb_id"] for f in bucket["owned_films"]] == [562]
