"""Interdit `with sqlite3.connect(...)` : cette forme NE FERME PAS la connexion.

Le gestionnaire de contexte d'une connexion sqlite3 valide ou annule la
TRANSACTION ; il ne ferme pas la connexion. C'est mesure :

    with sqlite3.connect(p) as conn:
        conn.execute("CREATE TABLE t(a)")
    conn.execute("SELECT 1")        # repond encore -> pas fermee

La consequence est invisible sous Linux et couteuse sous Windows : le handle
survit a la sortie du bloc, `shutil.rmtree` du dossier temporaire echoue, et
un `tearDown` ecrit `ignore_errors=True` avale l'echec. Le test passe, et
`%TEMP%` grossit d'un dossier par test.

MESURE (2026-08-31, bornes du garde abaissees a zero) : trois fichiers de
tests portaient 16 sites de cette forme.
`tests/test_aucune_migration_invisible_983.py` laissait **3** dossiers
`cinesort_983_db_*` par session — exactement ses trois tests. Apres passage a
`closing(...)`, **0**. C'est la moitie du depassement qui a rougi la CI du
run 33419486001 (13 entrees pour une borne de 12).

La forme correcte preserve les DEUX proprietes :

    with closing(sqlite3.connect(p)) as conn, conn:

`closing` ferme ; le second `conn` valide. L'ordre compte : le contexte
interne sort en premier (commit), puis `closing` ferme. Et `__enter__` d'une
connexion sqlite3 est neutre vis-a-vis des transactions (mesure :
`in_transaction` reste False a l'entree du bloc), donc cette reecriture ne
change RIEN au comportement observable.

CE QUE CE GARDE NE FAIT PAS — a lire avant de croire son vert :

  - Il LIT LE SOURCE. `tests/_temp_leak_guard.py` explique pourquoi c'est
    insuffisant en general : un `grep` declare propre un fichier qui ne
    nettoie qu'une classe sur trois. Ce garde est un COMPLEMENT du comptage,
    pas son remplacant. Il ferme une forme precise, celle qui MENT au
    lecteur : le mot-cle `with` donne a croire que la ressource est gouvernee.
  - Il ne dit rien de `conn = sqlite3.connect(...)` sans `with` (39 sites dans
    `tests/` au 2026-08-31). Cette forme-la n'affiche aucune promesse, et la
    plupart de ces fichiers ferment explicitement. Les traiter demanderait un
    cliquet chiffre, pas une interdiction.
  - `docs/internal/audit_horizons/proofs/` est hors perimetre : ce sont des
    scripts de preuve figes d'un audit passe, qui ne tournent pas en CI. Les
    reecrire falsifierait la trace de ce qui a reellement ete execute.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]

#: Perimetre : ce qui tourne en CI. Voir la limite documentee ci-dessus pour
#: `docs/`.
_PERIMETRE = ("tests", "cinesort", "scripts")

_INTERDIT = re.compile(r"\bwith\s+" + r"sqlite3\.connect\(")
#: CE FICHIER decrit le motif interdit, donc il le CONTIENT — dans sa docstring
#: et dans les donnees de la contre-epreuve. Au premier lancement il s'est
#: accuse lui-meme, 5 fois, ET PERSONNE D'AUTRE : c'est ce qui prouve que les
#: 16 sites corriges le sont sur tout le perimetre.
#:
#: Une exclusion ecrite comme une liste OUVERTE devient un depotoir : le
#: prochain fichier genant y serait ajoute au lieu d'etre corrige. D'ou
#: `test_l_exclusion_ne_GRANDIT_pas`, qui epingle son cardinal a 1.
_SEUL_FICHIER_EXCLU = Path(__file__).resolve().name


def _fichiers_python() -> list[Path]:
    fichiers = [_RACINE / "app.py"]
    for dossier in _PERIMETRE:
        fichiers.extend(sorted((_RACINE / dossier).rglob("*.py")))
    return [f for f in fichiers if f.exists() and f.name != _SEUL_FICHIER_EXCLU]


class AucuneConnexionSqliteNEstLaisseeOUVERTETests(unittest.TestCase):
    def test_la_forme_qui_ne_ferme_pas_est_ABSENTE(self) -> None:
        coupables = []
        for fichier in _fichiers_python():
            texte = fichier.read_text(encoding="utf-8", errors="replace")
            for numero, ligne in enumerate(texte.splitlines(), start=1):
                if _INTERDIT.search(ligne):
                    rel = fichier.relative_to(_RACINE).as_posix()
                    coupables.append(f"  {rel}:{numero}  {ligne.strip()}")
        self.assertEqual(
            coupables,
            [],
            "`with sqlite3.connect(...)` ne ferme pas la connexion (il ne fait que "
            "valider la transaction) ; sous Windows le handle survivant fait echouer "
            "`rmtree` et le dossier temporaire fuit.\n"
            "Ecrire : `with closing(sqlite3.connect(...)) as conn, conn:`\n" + "\n".join(coupables),
        )

    def test_le_motif_DISCRIMINE_reellement(self) -> None:
        """Contre-epreuve : sans elle, un motif casse rendrait le test ci-dessus
        vert pour toujours — un controle qui ne peut rendre qu'UNE valeur ne
        mesure rien.
        """
        doit_mordre = (
            "with sqlite3.connect(p) as conn:",
            "        with  sqlite3.connect(str(self.db)) as c:",
        )
        for ligne in doit_mordre:
            with self.subTest(ligne=ligne):
                self.assertIsNotNone(_INTERDIT.search(ligne))

        doit_passer = (
            "with closing(sqlite3.connect(p)) as conn, conn:",
            "conn = sqlite3.connect(p)",
            "with contextlib.closing(sqlite3.connect(p)) as conn:",
        )
        for ligne in doit_passer:
            with self.subTest(ligne=ligne):
                self.assertIsNone(_INTERDIT.search(ligne))

    def test_l_exclusion_ne_GRANDIT_pas(self) -> None:
        """Une seule exclusion, et c'est ce fichier. S'il en faut une deuxieme
        un jour, ce test rougit et oblige a la justifier plutot qu'a l'ajouter.
        """
        self.assertEqual(_SEUL_FICHIER_EXCLU, Path(__file__).resolve().name)
        self.assertNotIn(Path(__file__).resolve(), _fichiers_python())

    def test_le_perimetre_EXISTE_et_n_est_pas_vide(self) -> None:
        """Un `rglob` sur un dossier renomme rendrait zero fichier, donc zero
        coupable, donc un vert. La liste des fichiers est elle-meme une mesure.
        """
        fichiers = _fichiers_python()
        self.assertGreater(len(fichiers), 500, f"perimetre suspect : {len(fichiers)} fichier(s)")
        for dossier in _PERIMETRE:
            self.assertTrue((_RACINE / dossier).is_dir(), f"{dossier}/ introuvable")


if __name__ == "__main__":
    unittest.main()
