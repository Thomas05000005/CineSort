"""Le rescan cherche les verrous sous un film_id que RIEN n'ecrit jamais.

`_rematch_tmdb_and_update_plan` est le SEUL endroit du produit qui honore les
`film_field_locks` : il lit les noms verrouilles, puis appelle `merge_metadata`
en `replace_data=True` pour que la nouvelle row TMDb ecrase l'ancienne sauf sur
ces champs. Toute la fonctionnalite tient donc a une seule chose : chercher les
verrous sous le BON `film_id`.

Il les cherchait sous `compute_film_id(new_row_json)`, et cette valeur ne peut
structurellement JAMAIS etre un `tmdb:<id>` :

    new_row_json = plan_row_to_jsonable(PlanRow)   # = asdict(PlanRow)

et le dataclass `PlanRow` **ne porte aucun champ `tmdb_id`** (mesure : 31 champs,
dont `tmdb_collection_id`, `tv_tmdb_series_id` — jamais `tmdb_id`). Or
`compute_film_id` rend `tmdb:<id>` des qu'il trouve `tmdb_id` ou
`proposed_tmdb_id`, et retombe sur `path:<sha1(folder|video)>` sinon.

    compute_film_id(plan_row_to_jsonable(PlanRow(...)))  ->  path:c4ad80d7...

`target`, LUI, en porte un : `enrich_tmdb_ids_by_title` ecrit `row["tmdb_id"]`
dans plan.jsonl (tmdb_support.py:262, suivi de `write_plan_jsonl`) depuis le
thread `tmdb-enrich-<run_id>` lance en fin de scan. Et `set_film_tmdb_candidate`
(Identify manuel) migre explicitement les verrous vers `tmdb:<id>`
(library_support.py:1978).

Les deux bouts ne se rencontraient donc jamais :

    verrous ecrits/migres sous : tmdb:438631
    rescan les cherchait sous  : path:c4ad80d7...   -> 0 nom verrouille
    -> merge_metadata(locked_fields=[], replace_data=True)  -> tout ecrase

Le verrou etait silencieusement inoperant pour tout film dont l'id TMDb est
connu — c'est-a-dire precisement les films qu'un re-match va modifier. Le cas
sain (aucun id TMDb jamais resolu) est le seul qui fonctionnait.

POURQUOI LA SUITE NE L'A PAS VU. Les deux fichiers de test du sujet
(`test_field_locks_noms_qui_protegent`, `test_merge_metadata_resistance_rescan`)
appellent `merge_metadata` en lui PASSANT `locked_fields` a la main. Ils sautent
par-dessus le seul endroit ou le defaut vit — la resolution du `film_id`. C'est
le piege n1 du CLAUDE.md : la panne doit etre injectee a la couche de PRODUCTION.
Ce fichier pilote donc `_rematch_tmdb_and_update_plan` en entier, avec un vrai
`FieldLocksRepository` sur une vraie base.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import cinesort.domain.core as core
from cinesort.infra import state
from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.repositories.field_locks import FieldLocksRepository
from cinesort.ui.api import library_actions_support
from cinesort.ui.api.run_data_support import load_rows_from_plan_jsonl
from tests._helpers import _project_migrations_dir

RUN_ID = "r1"
TMDB_ID = 438631
TITRE_VERROUILLE = "Dune, la premiere partie"
TITRE_DU_REMATCH = "Dune"


def _run_paths(state_dir: Path, run_id: str = RUN_ID, *, ensure_exists: bool = True) -> state.RunPaths:
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    if ensure_exists:
        run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _plan_row(**over: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "row_id": "f1",
        "kind": "single",
        "folder": "",
        "video": "movie.mkv",
        "proposed_title": TITRE_VERROUILLE,
        "proposed_year": 2021,
        "proposed_source": "name",
        "confidence": 40,
        "confidence_label": "low",
        "candidates": [],
        "edition": None,
    }
    row.update(over)
    return row


class _StoreAvecVerrous:
    """Store minimal portant un VRAI FieldLocksRepository sur une vraie base.

    Meme forme que le `_FakeStore` de `test_field_locks_migration_path_to_tmdb` :
    le repository fait de vrais INSERT/SELECT, seule la fabrique de connexion est
    simplifiee.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.field_locks = FieldLocksRepository(self)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _managed_conn(self):
        @contextmanager
        def _ctx():
            with closing(self._connect()) as conn, conn:
                yield conn

        return _ctx()

    def _ensure_schema_group(self, group_name: str, *, min_user_version: Optional[int] = None) -> None:
        return None


def _base_avec_migration_030(racine: Path) -> Path:
    db_path = racine / "store.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        sql = (_project_migrations_dir() / "030_field_locks.sql").read_text(encoding="utf-8")
        for stmt in _split_sql_statements(sql):
            conn.execute(stmt)
        conn.execute("PRAGMA user_version = 30")
        conn.commit()
    finally:
        conn.close()
    return db_path


class _StubRunState:
    def __init__(self, paths: state.RunPaths, rows: List[core.PlanRow], store: Any) -> None:
        self.paths = paths
        self.rows = rows
        self.lock = threading.Lock()
        self.cfg = SimpleNamespace(root=Path("."))
        self.store = store
        self.done = True
        self.log = lambda _lvl, _msg: None


class _StubApi:
    """Surface reellement utilisee par `_rematch_tmdb_and_update_plan`."""

    def __init__(self, state_dir: Path, run_state: _StubRunState, store: Any) -> None:
        self._state_dir = state_dir
        self._run_state = run_state
        self._store = store
        self._settings = {"state_dir": str(state_dir), "tmdb_api_key": ""}
        self.settings = SimpleNamespace(get_settings=lambda: dict(self._settings))

    def _internal_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    def _run_paths_for(self, state_dir: Path, run_id: str, *, ensure_exists: bool) -> state.RunPaths:
        return _run_paths(Path(state_dir), run_id, ensure_exists=ensure_exists)

    def _get_run(self, run_id: str) -> Optional[_StubRunState]:
        return self._run_state if str(run_id) == RUN_ID else None

    def _find_run_row(self, run_id: str) -> None:
        return None

    def _load_rows_from_plan_jsonl(self, run_paths: state.RunPaths) -> List[core.PlanRow]:
        return load_rows_from_plan_jsonl(run_paths)

    def _serialize_rows_for_payload(self, rows: List[core.PlanRow]) -> List[Dict[str, Any]]:
        from cinesort.ui.api.run_data_support import serialize_rows_for_payload

        return serialize_rows_for_payload(rows)

    def _get_or_create_infra(self, state_dir: Path):
        return self._store, None

    def _dashboard_cache_path(self, run_paths: state.RunPaths) -> Path:
        return run_paths.run_dir / "dashboard_cache.json"


class _Harnais:
    """Un run pret a rejouer un re-match TMDb sur une row unique."""

    def __init__(self, tmp: Path, *, row_extra: Optional[Dict[str, Any]] = None) -> None:
        self.tmp = tmp
        self.films = tmp / "films" / "Dune (2021)"
        self.films.mkdir(parents=True, exist_ok=True)
        (self.films / "movie.mkv").write_bytes(b"x")

        self.paths = _run_paths(tmp)
        row = _plan_row(folder=str(self.films), **(row_extra or {}))
        self.paths.plan_jsonl.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.row_persistee = row

        self.store = _StoreAvecVerrous(_base_avec_migration_030(tmp))
        self.run_state = _StubRunState(self.paths, load_rows_from_plan_jsonl(self.paths), self.store)
        self.api = _StubApi(tmp, self.run_state, self.store)

    def rejoue_le_rematch(self) -> Optional[Dict[str, Any]]:
        fresh = core.PlanRow(
            row_id="ignore-moi",
            kind="single",
            folder=str(self.films),
            video="movie.mkv",
            proposed_title=TITRE_DU_REMATCH,
            proposed_year=2021,
            proposed_source="tmdb",
            confidence=95,
            confidence_label="high",
            candidates=[],
        )
        with patch("cinesort.app.plan_support.replan_single_row", return_value=fresh):
            return library_actions_support._rematch_tmdb_and_update_plan(self.api, RUN_ID, "f1")

    def titre_dans_le_plan(self) -> str:
        ligne = self.paths.plan_jsonl.read_text(encoding="utf-8").strip().splitlines()[0]
        return str(json.loads(ligne).get("proposed_title") or "")


class VerrouHonoreQuelQueSoitLIdTests(unittest.TestCase):
    def test_un_verrou_sous_tmdb_survit_au_rematch(self) -> None:
        """LE defaut. `enrich_tmdb_ids_by_title` a pose `tmdb_id` dans plan.jsonl
        et l'Identify manuel a migre le verrou sous `tmdb:<id>` : le rescan doit
        l'honorer."""
        with tempfile.TemporaryDirectory() as tmp_s:
            h = _Harnais(Path(tmp_s), row_extra={"tmdb_id": TMDB_ID})
            h.store.field_locks.set_lock(f"tmdb:{TMDB_ID}", "proposed_title", TITRE_VERROUILLE)

            out = h.rejoue_le_rematch()

            self.assertIsNotNone(out)
            self.assertEqual(
                h.titre_dans_le_plan(),
                TITRE_VERROUILLE,
                "le verrou pose sous tmdb:<id> a ete ignore : le rescan a ecrase le titre",
            )

    def test_un_verrou_sous_path_survit_aussi(self) -> None:
        """Non-regression du seul cas qui fonctionnait deja : aucun id TMDb
        connu, verrou sous `path:<sha1>`."""
        with tempfile.TemporaryDirectory() as tmp_s:
            h = _Harnais(Path(tmp_s))
            from cinesort.domain.film_identity import compute_film_id

            h.store.field_locks.set_lock(compute_film_id(h.row_persistee), "proposed_title", TITRE_VERROUILLE)

            h.rejoue_le_rematch()

            self.assertEqual(h.titre_dans_le_plan(), TITRE_VERROUILLE)

    def test_SANS_verrou_le_rematch_ecrase_bien(self) -> None:
        """Contre-epreuve indispensable : sans elle, un `merge_metadata` qui ne
        remplacerait plus rien ferait passer les deux tests ci-dessus."""
        with tempfile.TemporaryDirectory() as tmp_s:
            h = _Harnais(Path(tmp_s), row_extra={"tmdb_id": TMDB_ID})

            h.rejoue_le_rematch()

            self.assertEqual(h.titre_dans_le_plan(), TITRE_DU_REMATCH)

    def test_un_verrou_sur_un_AUTRE_film_ne_protege_rien(self) -> None:
        """Seconde contre-epreuve : le correctif ne doit pas honorer n'importe
        quel verrou de la table, seulement ceux du film concerne."""
        with tempfile.TemporaryDirectory() as tmp_s:
            h = _Harnais(Path(tmp_s), row_extra={"tmdb_id": TMDB_ID})
            h.store.field_locks.set_lock("tmdb:999999", "proposed_title", "Un autre film")

            h.rejoue_le_rematch()

            self.assertEqual(h.titre_dans_le_plan(), TITRE_DU_REMATCH)


class LIdDeriveDeLaNouvelleRowNePeutPasEtreTmdbTests(unittest.TestCase):
    """La cause racine, verrouillee a part : si `PlanRow` gagnait un jour un champ
    `tmdb_id`, ce test rougirait et signalerait que le contournement ci-dessus
    peut etre simplifie."""

    def test_PlanRow_ne_porte_aucun_champ_tmdb_id(self) -> None:
        import dataclasses

        noms = {f.name for f in dataclasses.fields(core.PlanRow)}

        self.assertNotIn("tmdb_id", noms)
        self.assertNotIn("proposed_tmdb_id", noms)

    def test_compute_film_id_sur_une_row_serialisee_est_toujours_path(self) -> None:
        from cinesort.app.plan_support_core import plan_row_to_jsonable
        from cinesort.domain.film_identity import compute_film_id, is_path_film_id

        row = core.PlanRow(
            row_id="r1",
            kind="single",
            folder="/lib/Dune (2021)",
            video="Dune.mkv",
            proposed_title="Dune",
            proposed_year=2021,
            proposed_source="tmdb",
            confidence=95,
            confidence_label="high",
            candidates=[],
        )

        self.assertTrue(is_path_film_id(compute_film_id(plan_row_to_jsonable(row))))


if __name__ == "__main__":
    unittest.main()
