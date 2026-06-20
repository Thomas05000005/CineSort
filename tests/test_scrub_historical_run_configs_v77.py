"""GATE AUDIT 2026-06-11 (R4-P6) — purge des secrets historiques de runs.config_json.

Le fix R1b (63517d7) masque les secrets des NOUVEAUX runs, mais les
runs.config_json ecrits avant restent en clair dans la base SQLite (residuel
confirme par la verification totale). scrub_historical_run_configs re-masque
au boot les _SECRET_FIELDS non-masques des lignes existantes.

Memoire projet : migrations/cleanups SQLite testes sur base PRE-EXISTANTE
(fixture M-00 arretee a v5), pas seulement fraiche.
"""

from __future__ import annotations

import json
import sqlite3
import time
import unittest

from cinesort.ui.api.run_flow_support import scrub_historical_run_configs
from cinesort.ui.api.settings_support import _SECRET_MASK
from tests._helpers import existing_db_fixture


class _ConnCtx:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return None


class _StoreShim:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _managed_conn(self) -> _ConnCtx:
        return _ConnCtx(self._conn)


def _insert_run(conn: sqlite3.Connection, run_id: str, config: dict | str) -> None:
    raw = config if isinstance(config, str) else json.dumps(config, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json)
        VALUES(?, 'DONE', ?, 'C:/root', 'C:/state', ?)
        """,
        (run_id, time.time(), raw),
    )
    conn.commit()


def _get_config(conn: sqlite3.Connection, run_id: str) -> str:
    cur = conn.execute("SELECT config_json FROM runs WHERE run_id = ?", (run_id,))
    return str(cur.fetchone()[0])


class ScrubHistoricalRunConfigsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path, self.conn = existing_db_fixture(5)
        self.store = _StoreShim(self.conn)

    def tearDown(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def test_clear_secret_is_masked(self) -> None:
        """Coeur du GATE : un run historique avec tmdb_api_key EN CLAIR est re-masque."""
        _insert_run(self.conn, "r-leak", {"library_path": "C:/films", "tmdb_api_key": "sk-REAL-1234"})
        report = scrub_historical_run_configs(self.store)
        self.assertEqual(report["scrubbed"], 1, report)
        cfg = json.loads(_get_config(self.conn, "r-leak"))
        self.assertEqual(cfg["tmdb_api_key"], _SECRET_MASK)
        self.assertNotIn("sk-REAL-1234", _get_config(self.conn, "r-leak"))
        # Les champs non-secrets sont intacts.
        self.assertEqual(cfg["library_path"], "C:/films")

    def test_nested_settings_dict_also_scrubbed(self) -> None:
        _insert_run(
            self.conn, "r-nested",
            {"settings": {"jellyfin_api_key": "jf-SECRET", "root": "C:/films"}},
        )
        report = scrub_historical_run_configs(self.store)
        self.assertEqual(report["scrubbed"], 1, report)
        cfg = json.loads(_get_config(self.conn, "r-nested"))
        self.assertEqual(cfg["settings"]["jellyfin_api_key"], _SECRET_MASK)
        self.assertEqual(cfg["settings"]["root"], "C:/films")

    def test_already_masked_untouched_and_idempotent(self) -> None:
        _insert_run(self.conn, "r-masked", {"tmdb_api_key": _SECRET_MASK, "root": "C:/films"})
        r1 = scrub_historical_run_configs(self.store)
        self.assertEqual(r1["scrubbed"], 0, r1)
        # Idempotence avec un run reellement scrubbe :
        _insert_run(self.conn, "r-leak2", {"omdb_api_key": "omdb-REAL"})
        r2 = scrub_historical_run_configs(self.store)
        self.assertEqual(r2["scrubbed"], 1, r2)
        r3 = scrub_historical_run_configs(self.store)
        self.assertEqual(r3["scrubbed"], 0, "2e passe : plus rien a re-masquer")

    def test_invalid_json_tolerated(self) -> None:
        _insert_run(self.conn, "r-bad", "{pas du json")
        report = scrub_historical_run_configs(self.store)  # ne doit pas lever
        self.assertEqual(report["scrubbed"], 0)
        self.assertEqual(_get_config(self.conn, "r-bad"), "{pas du json")

    def test_no_secret_run_untouched(self) -> None:
        _insert_run(self.conn, "r-clean", {"root": "C:/films", "tmdb_enabled": False})
        before = _get_config(self.conn, "r-clean")
        report = scrub_historical_run_configs(self.store)
        self.assertEqual(report["scrubbed"], 0)
        self.assertEqual(_get_config(self.conn, "r-clean"), before)

    def test_none_store_noop(self) -> None:
        report = scrub_historical_run_configs(None)
        self.assertEqual(report, {"scanned": 0, "scrubbed": 0})


if __name__ == "__main__":
    unittest.main()
