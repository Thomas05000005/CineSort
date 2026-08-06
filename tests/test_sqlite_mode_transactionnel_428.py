"""Le mode transactionnel de `connect_sqlite` est un INVARIANT porteur (#428).

Deux morceaux du depot sont ecrits contre lui, et le disent :

  - `MigrationManager.apply` pose son propre `BEGIN` (migration_manager.py:288)
    puis `commit`/`rollback` — c'est ce qui rend une migration atomique ;
  - `_record_pragma_history` commit explicitement son INSERT (pragma_profile.py:354)
    « pour qu'un connect_sqlite suivi d'un BEGIN fonctionne toujours ».

Ce que #428 proposait — `isolation_level="DEFERRED"` — ne protege PAS cet
invariant. MESURE, traces SQL emises :

    defaut (rien passe)          : BEGIN
    isolation_level="DEFERRED"   : BEGIN DEFERRED

Pour SQLite ce sont les MEMES : une transaction est deferred par defaut. Et
depuis Python 3.12, `isolation_level` n'est honore que tant que `autocommit`
vaut `LEGACY_TRANSACTION_CONTROL` — donc le jour ou ce defaut changerait,
l'avoir explicite n'aurait rien change :

    rien passe / LEGACY epingle  : BEGIN implicite, in_transaction=True,
                                   BEGIN explicite REFUSE
    autocommit=True              : aucun BEGIN implicite, in_transaction=False,
                                   BEGIN explicite ACCEPTE

Ces tests portent donc sur le COMPORTEMENT observable dont depend le depot, et
non sur la valeur d'un attribut — une assertion `conn.isolation_level == ""`
serait une tautologie : elle ne verifierait que le fait d'avoir ecrit la ligne.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.connection import connect_sqlite


class ModeTransactionnelImpliciteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dossier = Path(tempfile.mkdtemp(prefix="cinesort_tx428_"))
        self.addCleanup(shutil.rmtree, str(self.dossier), True)
        self.conn = connect_sqlite(str(self.dossier / "store.sqlite3"))
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE t (x INTEGER)")
        self.conn.commit()

    def test_un_DML_ouvre_une_transaction_implicite(self) -> None:
        """Sans cela, chaque ecriture serait durable immediatement.

        C'est la propriete qui rend `MigrationManager` capable d'annuler une
        migration a moitie appliquee.
        """
        self.assertFalse(self.conn.in_transaction, "pre-condition : aucune transaction ouverte")
        self.conn.execute("INSERT INTO t VALUES (1)")
        self.assertTrue(
            self.conn.in_transaction,
            "aucune transaction implicite apres un DML : le mode transactionnel a change, "
            "et les rollback du depot ne protegent plus rien.",
        )

    def test_un_rollback_annule_vraiment_l_ecriture(self) -> None:
        """La consequence concrete de l'invariant, et non sa forme."""
        self.conn.execute("INSERT INTO t VALUES (42)")
        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM t").fetchone()[0], 0)

    def test_un_BEGIN_explicite_est_refuse_pendant_une_transaction_implicite(self) -> None:
        """Le detail exact que `_record_pragma_history` contourne par son commit.

        Si ce test tombe, son commentaire (pragma_profile.py:315) devient faux
        et son `commit()` devient un mystere pour le prochain lecteur.
        """
        self.conn.execute("INSERT INTO t VALUES (1)")
        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute("BEGIN")

    def test_un_BEGIN_explicite_passe_sur_une_connexion_au_repos(self) -> None:
        """L'autre moitie : c'est ce que `MigrationManager.apply` fait a l'ouverture."""
        self.conn.execute("BEGIN")
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()


if __name__ == "__main__":
    unittest.main()
