"""ULTRA-AUDIT 2026-08 — N+1 de connexions SQLite sur le chargement de plan.

CRITICAL (history_support._enrich_plan_payload) : la boucle appelait
`overlay_tmdb_override` PAR ROW ; `film_modal.get_tmdb_override` enchaine
`_ensure_tables()` (1 connexion) puis `_managed_conn()` (2e connexion), soit
EXACTEMENT 2 ouvertures de connexion SQLite par film — 2N pour un plan de N
films, meme quand la table `film_tmdb_overrides` est vide. Mesure d'audit :
40 s / 2002 connexions a N=1000.

HIGH (film_support._find_plan_row) : la fiche film demandait le plan ENTIER
(serialisation + enrichissement des N rows, donc le N+1 ci-dessus) puis jetait
les N-1 autres rows.

Les tests comptent les OUVERTURES DE CONNEXION reelles (monkeypatch de
`connect_sqlite` dans le namespace de sqlite_store) et le nombre de rows
reellement serialisees, avec un vrai SQLiteStore. Chaque test de perf est
double d'une assertion de CORRECTION (l'override reste applique) qui doit
rester verte avec ou sans le correctif.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from cinesort.infra.db import sqlite_store as _sqlite_store_mod
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import film_support, history_support

_REAL_CONNECT = _sqlite_store_mod.connect_sqlite


class _ConnCounter:
    """Compte les ouvertures de connexion SQLite reelles du SQLiteStore."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args: Any, **kwargs: Any):
        self.count += 1
        return _REAL_CONNECT(*args, **kwargs)


# --------------------------------------------------------------------------
# Faux api minimal (memes helpers que ceux consommes par history_support)
# --------------------------------------------------------------------------
@dataclass
class _FakePlanRow:
    row_id: str
    proposed_title: str = "Auto Title"
    proposed_year: int = 1999
    confidence: int = 50
    warning_flags: List[str] = field(default_factory=list)
    subtitle_languages: List[str] = field(default_factory=list)
    tmdb_id: int = 111


class _FakeRunState:
    def __init__(self, rows: List[_FakePlanRow]) -> None:
        self.done = True
        self.rows = rows
        self.paths = None


class _FakeSettingsFacade:
    def __init__(self, state_dir: str) -> None:
        self._state_dir = state_dir

    def get_settings(self) -> Dict[str, Any]:
        return {"state_dir": self._state_dir}


class _FakeApi:
    def __init__(self, store: SQLiteStore, rows: List[_FakePlanRow], state_dir: str) -> None:
        self._store = store
        self._rows = rows
        self._state_dir = state_dir
        self.settings = _FakeSettingsFacade(state_dir)
        self.serialized_counts: List[int] = []

    # -- helpers consommes par history_support ---------------------------
    def _get_run(self, _run_id: str) -> _FakeRunState:
        return _FakeRunState(self._rows)

    def _serialize_rows_for_payload(self, rows: List[_FakePlanRow]) -> List[Dict[str, Any]]:
        self.serialized_counts.append(len(rows))
        return [
            {
                "row_id": r.row_id,
                "proposed_title": r.proposed_title,
                "proposed_year": r.proposed_year,
                "confidence": r.confidence,
                "warning_flags": list(r.warning_flags),
                "subtitle_languages": list(r.subtitle_languages),
                "tmdb_id": r.tmdb_id,
                "candidates": [],
            }
            for r in rows
        ]

    def _get_or_create_infra(self, _state_dir: Path):
        return self._store, None

    def _get_settings_impl(self) -> Dict[str, Any]:
        return {"auto_approve_threshold": 85}


class _PlanPerfBase(unittest.TestCase):
    N = 60

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_perf_ovr_")
        self.store = SQLiteStore(Path(self._tmp) / "t.sqlite")
        self.store.initialize()
        self.rows = [_FakePlanRow(row_id=f"r{i:04d}") for i in range(self.N)]
        self.api = _FakeApi(self.store, self.rows, self._tmp)
        # Un seul override, sur une row du milieu : le defaut se manifeste
        # meme quand la table est quasi vide (le cout est l'ouverture de
        # connexion, pas le SELECT).
        self.target = self.rows[self.N // 2].row_id
        self.store.film_modal.upsert_tmdb_override(
            run_id="R1",
            row_id=self.target,
            tmdb_id=999,
            new_confidence=92,
            proposed_title="Chosen Title",
            proposed_year=2011,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


class EnrichPlanPayloadConnectionsTests(_PlanPerfBase):
    """CRITICAL : le nombre de connexions ne doit plus croitre avec N."""

    def test_enrich_plan_does_not_open_two_connections_per_row(self) -> None:
        payload = self.api._serialize_rows_for_payload(self.rows)
        counter = _ConnCounter()
        with patch.object(_sqlite_store_mod, "connect_sqlite", counter):
            out = history_support._enrich_plan_payload(self.api, "R1", payload)

        # CORRECTION (doit rester vert AVEC et SANS le correctif) : l'override
        # est applique, et lui seul.
        by_id = {r["row_id"]: r for r in out}
        self.assertEqual(by_id[self.target]["proposed_title"], "Chosen Title")
        self.assertEqual(by_id[self.target]["proposed_year"], 2011)
        self.assertEqual(by_id[self.target]["confidence"], 92)
        self.assertEqual(by_id[self.target]["chosen_tmdb_id"], 999)
        other = self.rows[0].row_id
        self.assertEqual(by_id[other]["proposed_title"], "Auto Title")
        self.assertEqual(by_id[other]["proposed_year"], 1999)

        # PERF : avant le correctif, 2 connexions par row (>= 2*N) pour les
        # overrides, plus les lectures bulk. Le budget est volontairement
        # large : ce qui compte est qu'il ne depende PAS de N.
        self.assertLess(
            counter.count,
            self.N,
            f"{counter.count} connexions SQLite pour {self.N} rows : le N+1 par row est de retour",
        )

    def test_falls_back_to_per_row_when_bulk_unavailable(self) -> None:
        """Le chemin de repli ne doit JAMAIS perdre un override.

        Si la lecture bulk echoue (table absente, base verrouillee, store
        incomplet), on retombe sur la lecture par row : lent mais correct.
        """
        payload = self.api._serialize_rows_for_payload(self.rows)
        with patch.object(film_support, "list_tmdb_overrides_bulk", return_value=None):
            out = history_support._enrich_plan_payload(self.api, "R1", payload)
        by_id = {r["row_id"]: r for r in out}
        self.assertEqual(by_id[self.target]["proposed_year"], 2011)
        self.assertEqual(by_id[self.target]["confidence"], 92)


class ListTmdbOverridesBulkTests(_PlanPerfBase):
    def test_bulk_returns_all_overrides_of_the_run_only(self) -> None:
        self.store.film_modal.upsert_tmdb_override(
            run_id="R2", row_id=self.target, tmdb_id=7, new_confidence=10, proposed_title="Other run", proposed_year=1
        )
        got = film_support.list_tmdb_overrides_bulk(self.store, "R1")
        self.assertIsNotNone(got)
        self.assertEqual(set(got), {self.target})
        self.assertEqual(got[self.target]["tmdb_id"], 999)
        self.assertEqual(got[self.target]["proposed_title"], "Chosen Title")
        self.assertEqual(got[self.target]["proposed_year"], 2011)
        self.assertEqual(got[self.target]["new_confidence"], 92)

    def test_empty_run_returns_empty_dict_not_none(self) -> None:
        """`{}` (aucun override) et `None` (lecture impossible) sont distincts.

        Les confondre ferait retomber tout run sans override sur le chemin par
        row — c'est-a-dire exactement le N+1 que le correctif supprime.
        """
        self.assertEqual(film_support.list_tmdb_overrides_bulk(self.store, "RUN_SANS_OVERRIDE"), {})

    def test_returns_none_when_store_has_no_film_modal(self) -> None:
        self.assertIsNone(film_support.list_tmdb_overrides_bulk(object(), "R1"))
        self.assertIsNone(film_support.list_tmdb_overrides_bulk(None, "R1"))
        self.assertIsNone(film_support.list_tmdb_overrides_bulk(self.store, ""))

    def test_returns_none_when_read_fails(self) -> None:
        """Echec de lecture -> `None`, jamais `{}` : sinon les overrides du run
        seraient silencieusement effaces du plan servi (le repli par row ne se
        declencherait plus). Couvre aussi sqlite3.Error, qui n'herite PAS
        d'OSError."""
        import sqlite3

        class _RaisingRepo:
            def __init__(self, exc: BaseException) -> None:
                self._exc = exc

            def _ensure_tables(self) -> None:
                raise self._exc

        class _PartialRepo:
            """Repo sans les helpers _BaseRepository (fake de test historique)."""

            def get_tmdb_override(self, *, run_id: str, row_id: str) -> None:
                return None

        for exc in (sqlite3.OperationalError("database is locked"), OSError("io"), RuntimeError("migration")):
            store = type("_S", (), {"film_modal": _RaisingRepo(exc)})()
            self.assertIsNone(film_support.list_tmdb_overrides_bulk(store, "R1"), exc)
        store = type("_S", (), {"film_modal": _PartialRepo()})()
        self.assertIsNone(film_support.list_tmdb_overrides_bulk(store, "R1"))

    def test_bulk_opens_a_constant_number_of_connections(self) -> None:
        counter = _ConnCounter()
        with patch.object(_sqlite_store_mod, "connect_sqlite", counter):
            film_support.list_tmdb_overrides_bulk(self.store, "R1")
        self.assertLessEqual(counter.count, 3, f"{counter.count} connexions pour une lecture bulk")


class BulkOverlayMarkerContractTests(_PlanPerfBase):
    """FUSION #853 x #849 — la lecture GROUPEE doit honorer le contrat du
    marqueur `TMDB_OVERLAY_DONE_KEY`.

    #849 rend `library_support._build_library_rows` fail-closed : marqueur
    absent => il relit `film_tmdb_overrides` par row. Deux facons de casser la
    composition, chacune verrouillee ici :
      - le chemin bulk ne pose PAS le marqueur -> la Bibliotheque repaye les 2N
        connexions que cette PR vient de supprimer (perte du gain, pas du sens) ;
      - le chemin bulk pose le marqueur sur un resultat PARTIEL -> le choix TMDb
        manuel disparait EN SILENCE, la Bibliotheque ne relisant plus (bug R7-3
        re-ouvert : perte du sens, celle qui compte).
    """

    def _corrupt_one_override_row(self) -> None:
        """Insere une ligne indecodable (tmdb_id non numerique) dans le run.

        Pas de STRICT sur la table (migration 023) : SQLite stocke bien le texte
        dans une colonne INTEGER, donc `int()` leve a la relecture — exactement
        ce que rencontre `get_tmdb_override` sur le chemin par row.
        """
        with self.store.film_modal._managed_conn() as conn:  # noqa: SLF001
            conn.execute(
                """
                INSERT INTO film_tmdb_overrides(
                    run_id, row_id, tmdb_id, new_confidence,
                    proposed_title, proposed_year, chosen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("R1", "r0001", "pas-un-entier", 5, "Corrompu", 2000, 0.0),
            )

    def test_bulk_path_stamps_the_marker_on_every_row_read(self) -> None:
        """Lecture groupee aboutie => marqueur sur TOUTES les rows lues, y
        compris celles sans override (le marqueur dit « lecture aboutie », pas
        « override applique »)."""
        payload = self.api._serialize_rows_for_payload(self.rows)
        out = history_support._enrich_plan_payload(self.api, "R1", payload)

        self.assertTrue(all(r.get(film_support.TMDB_OVERLAY_DONE_KEY) for r in out))

    def test_partial_bulk_read_returns_none_not_a_truncated_dict(self) -> None:
        """Une ligne indecodable rend la lecture groupee NON FIABLE : `None`,
        pas un dict ampute qui se ferait passer pour complet."""
        self._corrupt_one_override_row()

        self.assertIsNone(film_support.list_tmdb_overrides_bulk(self.store, "R1"))

    def test_partial_bulk_read_marks_no_row_and_falls_back(self) -> None:
        """LE point de la fusion : un echec PARTIEL de la lecture groupee ne doit
        marquer AUCUNE row. Sinon la Bibliotheque, qui fait confiance au
        marqueur, servirait un plan silencieusement prive de ses overrides —
        le choix TMDb manuel disparaitrait sans un mot (bug R7-3)."""
        self._corrupt_one_override_row()

        # L'enrichissement retombe sur le chemin par row : l'override VALIDE est
        # toujours applique, et la row dont l'override est illisible n'est PAS
        # marquee -> la Bibliotheque la relira au lieu de la croire a jour.
        payload = self.api._serialize_rows_for_payload(self.rows)
        out = history_support._enrich_plan_payload(self.api, "R1", payload)
        by_id = {r["row_id"]: r for r in out}
        self.assertEqual(by_id[self.target]["proposed_title"], "Chosen Title")
        self.assertEqual(by_id[self.target]["confidence"], 92)
        self.assertNotIn(film_support.TMDB_OVERLAY_DONE_KEY, by_id["r0001"])

    def test_apply_bulk_marks_nothing_when_read_unavailable(self) -> None:
        """`overrides=None` (lecture impossible) : aucune row touchee, aucune
        marquee — c'est ce qui rend le repli par row obligatoire en aval."""
        rows = [{"row_id": "r0", "proposed_title": "Auto"}, {"row_id": "r1"}]

        self.assertEqual(film_support.apply_tmdb_overrides_bulk(rows, None), 0)

        for r in rows:
            self.assertNotIn(film_support.TMDB_OVERLAY_DONE_KEY, r)
        self.assertEqual(rows[0]["proposed_title"], "Auto")

    def test_apply_bulk_skips_rows_without_row_id(self) -> None:
        """Meme regle que `overlay_tmdb_override` : sans row_id, aucun etat
        d'override n'est connu pour cette row -> pas de marqueur."""
        rows: List[Dict[str, Any]] = [{"proposed_title": "Sans row_id"}, {"row_id": "", "proposed_title": "Vide"}]

        self.assertEqual(film_support.apply_tmdb_overrides_bulk(rows, {}), 0)

        for r in rows:
            self.assertNotIn(film_support.TMDB_OVERLAY_DONE_KEY, r)

    def test_apply_bulk_marks_rows_read_without_override(self) -> None:
        """`{}` = run lu, sans aucun override : les rows SONT marquees (rien a
        appliquer n'est pas un echec) — sans quoi la Bibliotheque relirait tout."""
        rows = [{"row_id": "r0", "proposed_title": "Auto"}]

        self.assertEqual(film_support.apply_tmdb_overrides_bulk(rows, {}), 0)

        self.assertTrue(rows[0][film_support.TMDB_OVERLAY_DONE_KEY])
        self.assertEqual(rows[0]["proposed_title"], "Auto")


class FindPlanRowSingleRowTests(_PlanPerfBase):
    """HIGH : la fiche film ne doit plus materialiser tout le plan."""

    def test_find_plan_row_serializes_only_the_requested_row(self) -> None:
        self.api.serialized_counts.clear()
        counter = _ConnCounter()
        with patch.object(_sqlite_store_mod, "connect_sqlite", counter):
            row = film_support._find_plan_row(self.api, "R1", self.target)

        # CORRECTION (vert des deux cotes) : c'est bien la bonne row, enrichie
        # (override TMDb applique, display_title et auto_approvable calcules).
        self.assertIsNotNone(row)
        self.assertEqual(row["row_id"], self.target)
        self.assertEqual(row["proposed_title"], "Chosen Title")
        self.assertEqual(row["proposed_year"], 2011)
        self.assertEqual(row["chosen_tmdb_id"], 999)
        self.assertIn("display_title", row)
        self.assertIn("auto_approvable", row)

        # PERF : une seule row serialisee, et un nombre de connexions
        # independant de la taille du plan.
        self.assertEqual(
            self.api.serialized_counts,
            [1],
            f"rows serialisees={self.api.serialized_counts} : tout le plan est encore materialise",
        )
        self.assertLess(
            counter.count,
            self.N,
            f"{counter.count} connexions SQLite pour UNE row sur un plan de {self.N}",
        )

    def test_unknown_row_id_returns_none(self) -> None:
        self.assertIsNone(film_support._find_plan_row(self.api, "R1", "row_inexistante"))
        self.assertIsNone(film_support._find_plan_row(self.api, "R1", ""))


if __name__ == "__main__":
    unittest.main()
