"""Issue #623 (volet 1) — le marqueur `@manager: disable_fk` doit etre STRICT.

Le manager de migrations peut desactiver les cles etrangeres le temps d'une
migration, sur demande explicite du fichier SQL. C'est la procedure NORMALE
recommandee par SQLite pour recreer une table (cf migration 025, qui fait
`DROP TABLE runs` alors que `errors`, `quality_reports` et `anomalies` la
referencent en `ON DELETE CASCADE`).

Le danger est l'inverse : desactiver les FK pour une migration qui n'en a PAS
besoin. Une simple mention du marqueur dans un commentaire descriptif — « cette
migration n'utilise volontairement pas @manager: disable_fk » — suffisait a le
declencher tant que la detection etait un `in` sur le texte brut du fichier.
Les deux chemins de boot posent donc un matcher STRICT : la ligne, une fois
trimee, doit COMMENCER par `-- @manager: disable_fk`.

Ces tests mesurent l'EFFET (une suppression se propage-t-elle en cascade ?),
pas la forme du code : un test qui grepperait le source serait vert sur
n'importe quelle reecriture et rouge sur toute amelioration.

Chaque cas est double : la migration piegeuse (le marqueur n'est PAS en tete de
ligne -> FK actives -> cascade) ET sa jumelle legitime (marqueur en tete ->
FK coupees -> pas de cascade). Sans la jumelle, un test vert ne prouverait rien :
il pourrait l'etre parce que le PRAGMA n'a aucun effet dans ce montage.

Base PRE-EXISTANTE : les deux scenarios appliquent d'abord la migration de base,
INSERENT des donnees, puis appliquent la migration suivante — jamais sur une DB
fraiche, ou une cascade n'aurait rien a supprimer.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.migration_manager import MigrationManager
from cinesort.infra.db.sqlite_store import SQLiteStore

# Migration de base : un parent, un enfant en ON DELETE CASCADE.
_BASE_SQL = """\
-- Migration de base du scenario de test.
CREATE TABLE IF NOT EXISTS mig_parent (
  id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS mig_child (
  id        INTEGER PRIMARY KEY,
  parent_id INTEGER NOT NULL REFERENCES mig_parent(id) ON DELETE CASCADE
);

PRAGMA user_version = 1;
"""

# Migration piegeuse : le marqueur apparait dans une phrase, pas en tete de
# ligne. Elle ne recree aucune table : les FK doivent rester ACTIVES.
_TRAP_SQL = """\
-- Cette migration ne recree aucune table, elle ne doit donc surtout pas
-- utiliser @manager: disable_fk — les contraintes doivent rester actives.
DELETE FROM mig_parent WHERE id = 1;

PRAGMA user_version = 2;
"""

# Migration legitime : marqueur en tete de ligne, FK coupees pour de bon.
_LEGIT_SQL = """\
-- @manager: disable_fk
-- Recreation de table facon SQLite « Section 7 » (ici simplifiee au DELETE
-- qui declencherait la cascade indesirable).
DELETE FROM mig_parent WHERE id = 1;

PRAGMA user_version = 2;
"""


class DisableFkMarkerStrictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="cinesort_disable_fk_623_"))
        self.addCleanup(shutil.rmtree, self.tmp_root, ignore_errors=True)
        self.migrations_dir = self.tmp_root / "migrations"
        self.migrations_dir.mkdir(parents=True)
        self.db_path = self.tmp_root / "store.sqlite3"

    def _seed_pre_existing_db(self) -> None:
        """Applique la migration de base, PUIS peuple la DB.

        L'ordre compte : la migration suivante s'executera sur une base qui a
        deja des donnees, seul cas ou une cascade est observable.
        """
        (self.migrations_dir / "001_base.sql").write_text(_BASE_SQL, encoding="utf-8")
        MigrationManager(db_path=self.db_path, migrations_dir=self.migrations_dir).apply()
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("INSERT INTO mig_parent(id) VALUES (1)")
            conn.execute("INSERT INTO mig_child(id, parent_id) VALUES (10, 1)")
        self.assertEqual(self._child_count(), 1, "amorcage du scenario casse")

    def _child_count(self) -> int:
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM mig_child").fetchone()[0])

    def _write_next_migration(self, sql: str) -> None:
        (self.migrations_dir / "002_next.sql").write_text(sql, encoding="utf-8")

    # -- Chemin 1 : MigrationManager.apply (migration par migration) --------

    def test_marqueur_cite_dans_une_phrase_ne_coupe_pas_les_fk(self) -> None:
        self._seed_pre_existing_db()
        self._write_next_migration(_TRAP_SQL)

        version = MigrationManager(db_path=self.db_path, migrations_dir=self.migrations_dir).apply()

        self.assertEqual(version, 2)
        self.assertEqual(
            self._child_count(),
            0,
            "les FK ont ete desactivees par un simple commentaire : la cascade "
            "attendue n'a pas eu lieu et l'enfant est devenu orphelin",
        )

    def test_marqueur_en_tete_de_ligne_coupe_bien_les_fk(self) -> None:
        """Contre-test : sans lui, le test precedent pourrait etre vert a tort."""
        self._seed_pre_existing_db()
        self._write_next_migration(_LEGIT_SQL)

        version = MigrationManager(db_path=self.db_path, migrations_dir=self.migrations_dir).apply()

        self.assertEqual(version, 2)
        self.assertEqual(
            self._child_count(),
            1,
            "le marqueur legitime n'a pas coupe les FK : la migration 025 "
            "(DROP TABLE runs) perdrait errors/quality_reports/anomalies",
        )

    def test_les_fk_sont_restaurees_dans_le_meme_apply(self) -> None:
        """Le PRAGMA est repose a ON pour la migration SUIVANTE.

        Les deux migrations sont appliquees par un SEUL `apply()`, donc sur une
        SEULE connexion : c'est la seule facon d'observer la restauration. Avec
        deux `apply()` successifs, `connect_sqlite` reposerait `foreign_keys=ON`
        a l'ouverture et le test serait vert meme sans le `finally` — il
        mesurerait le PRAGMA de connexion, pas la restauration.
        """
        self._seed_pre_existing_db()
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("INSERT INTO mig_parent(id) VALUES (2)")
            conn.execute("INSERT INTO mig_child(id, parent_id) VALUES (20, 2)")
        # 002 est marquee (FK coupees), 003 ne l'est pas (FK attendues actives).
        self._write_next_migration(_LEGIT_SQL)
        (self.migrations_dir / "003_after.sql").write_text(
            "-- Migration ordinaire : aucune raison de tourner sans FK.\n"
            "DELETE FROM mig_parent WHERE id = 2;\n\nPRAGMA user_version = 3;\n",
            encoding="utf-8",
        )

        version = MigrationManager(db_path=self.db_path, migrations_dir=self.migrations_dir).apply()

        self.assertEqual(version, 3)
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            remaining = {int(r[0]) for r in conn.execute("SELECT id FROM mig_child")}
        self.assertEqual(
            remaining,
            {10},
            "les FK n'ont pas ete restaurees apres la migration marquee : la "
            "migration suivante a tourne sans integrite referentielle sur la "
            "meme connexion",
        )

    # -- Chemin 2 : bootstrap self-heal (script concatene) ------------------

    def test_marqueur_cite_dans_une_phrase_ne_coupe_pas_les_fk_au_bootstrap(self) -> None:
        """Le bootstrap self-heal rejoue TOUT le script sur une DB peuplee.

        C'est le second chemin de boot ; il porte sa propre copie du predicat.
        Un correctif applique au seul MigrationManager le laisserait derriere.
        """
        self._seed_pre_existing_db()
        self._write_next_migration(_TRAP_SQL)
        store = SQLiteStore(self.db_path, migrations_dir=self.migrations_dir)

        store._bootstrap_schema_latest()

        self.assertEqual(
            self._child_count(),
            0,
            "bootstrap : les FK ont ete desactivees par un simple commentaire",
        )

    def test_marqueur_en_tete_de_ligne_coupe_bien_les_fk_au_bootstrap(self) -> None:
        self._seed_pre_existing_db()
        self._write_next_migration(_LEGIT_SQL)
        store = SQLiteStore(self.db_path, migrations_dir=self.migrations_dir)

        store._bootstrap_schema_latest()

        self.assertEqual(
            self._child_count(),
            1,
            "bootstrap : le marqueur legitime n'a pas coupe les FK",
        )


if __name__ == "__main__":
    unittest.main()
