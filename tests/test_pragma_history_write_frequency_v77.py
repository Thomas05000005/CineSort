"""GATE — l'audit `pragma_history` est OCCASIONNEL, pas une ecriture par connexion.

Bug (AUDIT ULTRA 2026-08, pragma_profile.py:229-268) : `apply_pragmas` a bien un
kwarg `record_history` mais `connect_sqlite` ne le passait jamais -> chaque
ouverture de connexion payait INSERT + `SELECT MAX(id)` + DELETE de purge +
`conn.commit()`. Or `SQLiteStore._managed_conn` ouvre une connexion NEUVE par
appel de repository (et `_with_schema_group` en ouvre 2-3), donc le cout etait
multiplie par un nombre de connexions deja excessif. Mesure locale avant fix :
60 connexions -> 60 INSERT, 3,91 ms/connexion contre 0,071 ms pour un
`sqlite3.connect` nu. La campagne precedente n'avait borne que la TAILLE de la
table (purge a 500 lignes), pas la FREQUENCE d'ecriture.

Fix : `connect_sqlite` interroge `should_record_pragma_history()`, un gate
memoire par processus qui n'autorise l'ecriture qu'au premier boot pour un
chemin DB donne, ou lors d'un CHANGEMENT de profil / de source.

L'historique garde sa valeur de diagnostic — les tests ci-dessous verrouillent
les deux cotes : la frequence EFFONDREE (gate) *et* les evenements qui doivent
continuer d'etre traces (boot, changement de profil, changement de source, DB
fraiche dont la table n'existait pas encore a la premiere connexion).
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.connection import connect_sqlite
from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.pragma_profile import reset_pragma_history_gate
from tests._helpers import _project_migrations_dir, existing_db_fixture

# Nombre de connexions simulant une rafale de repositories (`_managed_conn`).
_BURST = 25


def _apply_migration_028(conn: sqlite3.Connection) -> None:
    sql = (_project_migrations_dir() / "028_pragma_history.sql").read_text(encoding="utf-8")
    for stmt in _split_sql_statements(sql):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 28")
    conn.commit()


def _history(db_path: Path) -> list[tuple[str, str]]:
    """Renvoie [(profile_name, source), ...] ordonne par id."""
    with closing(sqlite3.connect(str(db_path))) as conn:
        return [
            (str(row[0]), str(row[1]))
            for row in conn.execute("SELECT profile_name, source FROM pragma_history ORDER BY id")
        ]


def _migrated_db() -> Path:
    """DB pre-existante deja porteuse de `pragma_history` (v28), connexion fermee."""
    db_path, conn = existing_db_fixture(28)
    conn.close()
    return db_path


class PragmaHistoryWriteFrequencyTests(unittest.TestCase):
    def setUp(self) -> None:
        # Le gate est un etat process-wide : on repart d'une ardoise vierge pour
        # que chaque test decrive exactement la sequence qu'il exerce.
        reset_pragma_history_gate()

    def tearDown(self) -> None:
        reset_pragma_history_gate()

    def test_burst_of_connections_writes_a_single_history_row(self) -> None:
        """GATE : N ouvertures identiques -> UNE seule ligne d'audit, pas N."""
        db_path = _migrated_db()
        reset_pragma_history_gate()
        self.assertEqual(_history(db_path), [], "pre-cond : table d'audit vide")

        for _ in range(_BURST):
            connect_sqlite(str(db_path)).close()

        rows = _history(db_path)
        self.assertEqual(
            len(rows),
            1,
            f"{_BURST} connexions doivent ecrire 1 ligne d'audit, pas {len(rows)}",
        )

    def test_profile_change_is_still_recorded(self) -> None:
        """NON-REGRESSION : le diagnostic survit — un changement de profil trace."""
        db_path = _migrated_db()
        reset_pragma_history_gate()

        connect_sqlite(str(db_path), profile="local_ssd").close()
        connect_sqlite(str(db_path), profile="local_ssd").close()
        connect_sqlite(str(db_path), profile="nas_smb").close()
        connect_sqlite(str(db_path), profile="nas_smb").close()

        profiles = [profile for profile, _source in _history(db_path)]
        self.assertEqual(
            profiles,
            ["local_ssd", "nas_smb"],
            "chaque changement de profil doit laisser une trace, les repetitions non",
        )

    def test_source_change_is_still_recorded(self) -> None:
        """NON-REGRESSION : auto vs manual_settings restent distinguables."""
        db_path = _migrated_db()
        reset_pragma_history_gate()

        # 1re connexion en autodetect (source='auto'), puis meme profil impose
        # explicitement par le caller (source='manual_settings').
        conn = connect_sqlite(str(db_path))
        conn.close()
        auto_profile = _history(db_path)[0][0]
        connect_sqlite(str(db_path), profile=auto_profile).close()

        sources = [source for _profile, source in _history(db_path)]
        self.assertEqual(sources, ["auto", "manual_settings"])

    def test_fresh_db_records_once_table_exists(self) -> None:
        """GATE : la reservation est relachee quand la table n'existe pas encore.

        Une DB fraiche est ouverte AVANT la migration 028 : l'INSERT echoue
        (table absente). Si le gate memorisait cette tentative, la DB n'aurait
        plus JAMAIS de ligne d'audit dans ce processus — le diagnostic serait
        perdu au moment ou il compte le plus (premier boot).
        """
        db_path, conn = existing_db_fixture(27)
        conn.close()
        reset_pragma_history_gate()

        # Ouvertures pre-028 : aucune table, aucun crash, aucune trace.
        connect_sqlite(str(db_path)).close()
        connect_sqlite(str(db_path)).close()

        with closing(sqlite3.connect(str(db_path))) as raw:
            _apply_migration_028(raw)

        connect_sqlite(str(db_path)).close()
        self.assertEqual(
            len(_history(db_path)),
            1,
            "la premiere connexion post-migration doit enfin ecrire l'audit",
        )

    def test_distinct_databases_are_tracked_independently(self) -> None:
        """NON-REGRESSION : le gate est par chemin DB, pas global."""
        first = _migrated_db()
        second = _migrated_db()
        reset_pragma_history_gate()

        connect_sqlite(str(first)).close()
        connect_sqlite(str(second)).close()

        self.assertEqual(len(_history(first)), 1)
        self.assertEqual(len(_history(second)), 1)

    def test_connection_still_usable_and_pragmas_applied(self) -> None:
        """NON-REGRESSION : ne pas ecrire l'audit ne degrade rien d'autre."""
        db_path = _migrated_db()
        reset_pragma_history_gate()

        connect_sqlite(str(db_path)).close()  # consomme le boot
        with closing(connect_sqlite(str(db_path))) as conn:  # connexion gatee
            self.assertEqual(int(conn.execute("PRAGMA foreign_keys").fetchone()[0]), 1)
            self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(), "wal")
            # Aucune transaction implicite pendante : un BEGIN doit passer (c'est
            # ce que le commit explicite de `_record_pragma_history` garantissait).
            conn.execute("BEGIN")
            conn.rollback()


class PragmaHistoryGateHelperTests(unittest.TestCase):
    """Le helper de decision, teste sans I/O disque."""

    def setUp(self) -> None:
        reset_pragma_history_gate()

    def tearDown(self) -> None:
        reset_pragma_history_gate()

    def test_gate_is_case_and_separator_insensitive(self) -> None:
        from cinesort.infra.db.pragma_profile import should_record_pragma_history

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Store.sqlite3"
            self.assertTrue(should_record_pragma_history(str(base), "local_ssd", "auto"))
            variant = str(base).replace("\\", "/") if "\\" in str(base) else str(base)
            self.assertFalse(should_record_pragma_history(variant, "local_ssd", "auto"))
            self.assertFalse(should_record_pragma_history(str(base).upper(), "local_ssd", "auto"))

    def test_gate_is_bounded(self) -> None:
        from cinesort.infra.db import pragma_profile as _pp

        cap = _pp._PRAGMA_HISTORY_GATE_MAX_ENTRIES
        for i in range(cap * 3):
            _pp.should_record_pragma_history(f"C:/nowhere/db_{i}.sqlite3", "local_ssd", "auto")
        self.assertLessEqual(len(_pp._pragma_history_gate), cap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
