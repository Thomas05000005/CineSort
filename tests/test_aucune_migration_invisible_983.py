"""Tout fichier `.sql` du repertoire de migrations doit etre VU par le manager.

LE DEFAUT (#983). `_MIGRATION_FILE_RE` exige un SOULIGNE apres le numero :

    ^(?P<version>\\d+)_.*\\.sql$

Or `032-vector-search-tables.sql` portait un TIRET. Le fichier etait donc
invisible pour les DEUX chemins de demarrage — ni `MigrationManager.apply`, ni
`SQLiteStore._bootstrap_schema_latest` ne le jouaient.

MESURE, sur le repertoire reel :

    AVANT   fichiers=32  vues=31  latest=31  invisibles=['032-vector-search-tables.sql']
    APRES   fichiers=32  vues=32  latest=32  invisibles=[]

RIEN NE LE RATTRAPAIT. `vec_films_hash` n'est pas dans `REQUIRED_SCHEMA_TABLES`,
donc l'auto-reparation ne la recree jamais ; et le rattrapage runtime suppose
n'existe pas (`SqliteVecAdapter.create_vec_table` leve `NotImplementedError`).

CE TEST EST LE VRAI LIVRABLE. Renommer 032 corrige UN fichier ; cette garde
empeche la CLASSE entiere. Sans elle, la prochaine migration mal nommee
disparaitrait exactement de la meme facon, sans un mot.

POURQUOI LE RENOMMAGE ACCOMPAGNE FINALEMENT LA GARDE. L'issue le deconseillait,
craignant « le chargement de l'extension sqlite-vec » et « create_vec_table non
implementee ». La lecture du fichier refute les deux : il ne contient qu'un
`CREATE TABLE IF NOT EXISTS` d'une table PLATE et un `PRAGMA user_version`, et
son propre en-tete precise que la table virtuelle `vec0` sera creee A RUNTIME,
« PAS dans cette migration (l'extension n'est pas garantie chargee) ». S'y
ajoutent trois mesures : le drapeau `similar_films` est desactive par defaut,
le manager FILTRE les `PRAGMA user_version` du SQL et pose la version lui-meme,
et 22 des 32 migrations portent ce meme PRAGMA — c'est la convention du depot.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.migration_manager import MigrationManager

_REPERTOIRE = Path(__file__).resolve().parents[1] / "cinesort" / "infra" / "db" / "migrations"


def _manager(db: Path) -> MigrationManager:
    return MigrationManager(db, _REPERTOIRE)


class AucuneMigrationNEstINVISIBLETests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_983_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_chaque_fichier_sql_est_vu_par_le_manager(self) -> None:
        """LA garde. Un fichier absent de cette liste n'est joue par AUCUN des
        deux chemins de demarrage, et rien ne le rattrape."""
        sur_disque = {p.name for p in _REPERTOIRE.glob("*.sql")}
        vues = {chemin.name for _version, chemin in _manager(self._tmp / "c.sqlite").list_migrations()}

        invisibles = sorted(sur_disque - vues)
        self.assertEqual(
            invisibles,
            [],
            f"ces migrations ne seront JAMAIS jouees : {invisibles}. "
            f"Le motif attendu est `<numero>_<description>.sql` — un tiret apres "
            f"le numero suffit a les rendre invisibles, sans aucune erreur.",
        )

    def test_le_manager_n_invente_pas_de_migration(self) -> None:
        """L'autre sens : une entree vue sans fichier signalerait un motif trop
        laxiste (ex. un `.sql.bak` accepte)."""
        sur_disque = {p.name for p in _REPERTOIRE.glob("*.sql")}
        vues = {chemin.name for _version, chemin in _manager(self._tmp / "c.sqlite").list_migrations()}

        self.assertEqual(sorted(vues - sur_disque), [])

    def test_les_numeros_de_version_sont_UNIQUES(self) -> None:
        """Deux fichiers de meme numero : l'un des deux serait silencieusement
        ignore ou rejoue selon l'ordre de tri."""
        versions = [v for v, _ in _manager(self._tmp / "c.sqlite").list_migrations()]

        doublons = sorted({v for v in versions if versions.count(v) > 1})
        self.assertEqual(doublons, [], f"numeros de migration en double : {doublons}")

    def test_latest_version_suit_le_dernier_fichier(self) -> None:
        """Contre-epreuve du defaut d'origine : `latest_version` rendait 31 alors
        que le repertoire portait bien une 032."""
        numeros = []
        for p in _REPERTOIRE.glob("*.sql"):
            m = re.match(r"^(\d+)", p.name)
            if m:
                numeros.append(int(m.group(1)))

        self.assertEqual(_manager(self._tmp / "c.sqlite").latest_version(), max(numeros))


class LaMigration032EstREELLEMENTAppliqueeTests(unittest.TestCase):
    """La garde compte des noms ; ces tests regardent la BASE.

    Un motif corrige qui n'aboutirait pas a la creation de la table laisserait
    le defaut entier — le fichier serait vu, et toujours sans effet.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_983_db_"))
        self.db = self._tmp / "cinesort.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _tables(self) -> set[str]:
        with sqlite3.connect(str(self.db)) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def _user_version(self) -> int:
        with sqlite3.connect(str(self.db)) as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def test_sur_une_base_NEUVE_la_table_est_creee(self) -> None:
        _manager(self.db).apply()

        self.assertIn("vec_films_hash", self._tables())
        self.assertEqual(self._user_version(), 32)

    def test_sur_une_base_PRE_EXISTANTE_arretee_a_31(self) -> None:
        """Regle du depot : une migration se teste sur une base PRE-EXISTANTE,
        pas seulement sur une base fraiche. C'est le cas de tout utilisateur
        actuel — sa base est a 31 et n'a jamais vu la 032.
        """
        m = _manager(self.db)
        m.apply()
        with sqlite3.connect(str(self.db)) as conn:
            conn.execute("DROP TABLE IF EXISTS vec_films_hash")
            conn.execute("PRAGMA user_version = 31")
        self.assertNotIn("vec_films_hash", self._tables())

        _manager(self.db).apply()

        self.assertIn("vec_films_hash", self._tables(), "la base existante n'a pas recu la 032")
        self.assertEqual(self._user_version(), 32)

    def test_un_rejeu_ne_DETRUIT_PAS_les_donnees(self) -> None:
        """L'idempotence qui compte : rejouer la 032 preserve le contenu.

        DEUX CORRECTIONS SUCCESSIVES ONT ETE NECESSAIRES ICI.

        1. La premiere version enchainait deux `apply()` sans rien entre eux.
           Elle n'eprouvait RIEN — mesure :

               apres 1er apply : user_version=32
               migrations que le 2e apply va jouer : []

           Le manager saute toute migration deja appliquee : le second appel
           etait un no-op, et le test assertait qu'un no-op ne change rien.
           Signale par CodeRabbit sur la PR #1011, verifie par la mesure.

        2. Remettre `user_version` a 31 fait bien rejouer la 032 — mais le
           motif avance pour ce correctif (« sinon on ne detecte pas la
           suppression de IF NOT EXISTS ») est FAUX, et la mutation le montre :
           retirer les trois `IF NOT EXISTS` du fichier laisse le test VERT.
           La raison est dans le manager lui-meme, qui absorbe ces erreurs :

               db: migration 032 — instruction 0 ignoree (idempotence):
                   table vec_films_hash already exists

           Aucun test passant par `apply()` ne peut donc eprouver la presence
           de `IF NOT EXISTS` : la garde vit un cran plus haut. Ecrire une
           assertion sur cette base aurait produit un vert permanent presente
           comme une preuve.

        CE QUE CE TEST EPROUVE DONC. La propriete qui reste observable, et qui
        est celle qui compte pour un utilisateur : un rejeu ne doit pas
        RECREER la table, donc pas perdre ses lignes. Une migration ecrite en
        `DROP TABLE` + `CREATE TABLE` passerait toutes les assertions de forme
        (tables identiques, version 32) en detruisant les donnees.
        """
        _manager(self.db).apply()
        with sqlite3.connect(str(self.db)) as conn:
            conn.execute("INSERT INTO vec_films_hash(film_id, embedding) VALUES (7, ?)", (b"",))
            conn.commit()
        avant = self._tables()

        with sqlite3.connect(str(self.db)) as conn:
            conn.execute("PRAGMA user_version = 31")
        self.assertIn("vec_films_hash", self._tables(), "precondition : la table doit rester en place")

        _manager(self.db).apply()

        with sqlite3.connect(str(self.db)) as conn:
            lignes = conn.execute("SELECT film_id FROM vec_films_hash").fetchall()
        self.assertEqual(
            [r[0] for r in lignes],
            [7],
            "le rejeu a PERDU les lignes : la migration recree la table au lieu de la respecter",
        )
        self.assertEqual(self._tables(), avant)
        self.assertEqual(self._user_version(), 32)

    def test_le_bootstrap_direct_la_contient_AUSSI(self) -> None:
        """Le second chemin de demarrage. `_bootstrap_schema_latest` rejoue le
        script complet : il l'ignorait tout autant."""
        from cinesort.infra.db.migration_manager import MigrationManager as MM

        # `build_bootstrap_script` rend un TUPLE `(script, version)`. Une
        # premiere version de ce test faisait `assertIn(..., tuple)`, ce qui
        # teste l'appartenance aux ELEMENTS et non la sous-chaine : il rougissait
        # en accusant le code, alors que le defaut etait dans l'assertion.
        script, version = MM(self.db, _REPERTOIRE).build_bootstrap_script()

        self.assertIn("vec_films_hash", script, "le chemin de bootstrap direct ignore toujours la 032")
        self.assertEqual(version, 32)


if __name__ == "__main__":
    unittest.main()
