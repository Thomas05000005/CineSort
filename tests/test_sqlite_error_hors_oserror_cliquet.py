"""Regle inviolable n4 : `sqlite3.Error` n'herite PAS de `OSError`.

Un `except OSError` autour d'un appel de repository ne l'attrape donc pas. Ce
piege a deja avorte des apply APRES un deplacement fait sur disque, laissant un
etat mixte non annulable.

MESURE du 2026-08-06, par AST, critere volontairement STRICT :

    `except` contenant OSError, toutes causes    : 678
    dont SANS sqlite3.Error ET touchant le store :  68

Les 610 autres sont hors sujet (un `except OSError` autour d'un `read_text` n'a
rien a se reprocher) — c'est le filtre « touche un repository » qui donne le
chiffre utile.

POURQUOI UN CLIQUET ET PAS UNE CORRECTION EN MASSE. Le sens du correctif DEPEND
du site, et se tromper coute cher dans les deux directions :

  - sur un chemin de LECTURE (tableau de bord, historique, bibliotheque), une
    base verrouillee doit degrader l'affichage, pas rendre un HTTP 500 :
    ajouter `sqlite3.Error` est le bon geste ;
  - sur un chemin DESTRUCTIF, l'ajouter transforme un echec en succes
    silencieux. Le depot s'est deja fait prendre exactement la : ajouter
    `sqlite3.Error` a l'except d'`insert_apply_batch` laissait un apply
    s'executer SANS AUCUN JOURNAL, donc sans undo possible, et le rapportait ok
    (revue adversaire R1, cf. le commentaire sur place dans apply_support).

Un balayage uniforme ferait donc les deux erreurs a la fois. Ce test borne la
population — elle ne peut que DECROITRE — et laisse chaque site etre tranche
individuellement, avec son propre test.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

_REPERTOIRE_DU_DEPOT = Path(__file__).resolve().parents[1]

# PERIMETRE. Longtemps `Path("cinesort")` seul — et `app.py`, point d'entree de
# l'application, echappait donc a ce cliquet comme a CINQ autres controles
# statiques (recense dans `tests/test_bandit_perimetre_couvre_le_code.py`).
#
# L'elargissement est GRATUIT et c'est ce qui le rend utile : il revele
# ZERO site nouveau (mesure du 2026-08-31, temoin positif ci-dessous a l'appui).
# Un perimetre qu'on elargit le jour ou il coute quelque chose ne s'elargit
# jamais ; celui-ci se ferme pendant qu'il est gratuit, et c'est demain qu'il
# servira — le jour ou quelqu'un ecrira un `except OSError` dans `app.py`.
_RACINES = ("cinesort", "app.py", "scripts")


def _fichiers_python() -> list[Path]:
    """Les fichiers du perimetre. Une racine peut etre un FICHIER (`app.py`) :
    `Path("app.py").rglob("*.py")` ne rend rien, en silence.
    """
    fichiers: list[Path] = []
    for racine in _RACINES:
        chemin = _REPERTOIRE_DU_DEPOT / racine
        if chemin.is_dir():
            fichiers.extend(chemin.rglob("*.py"))
        elif chemin.is_file():
            fichiers.append(chemin)
    return sorted(fichiers)


# Ce nombre ne se recopie pas : il se remesure, et il ne doit JAMAIS remonter.
#
#   68 au 2026-08-06 (mesure d'origine)
#   65 apres le passage des 3 lectures du profil qualite actif a
#      `_ERREURS_DE_LECTURE_DU_PROFIL` (cinesort_api.py) : une base verrouillee
#      y faisait REMONTER `sqlite3.OperationalError` au lieu du repli prevu.
#   63 apres les deux `except` de `history_support.cleanup_old_runs` (#1022) :
#      un verrou transitoire sortait de la fonction et abandonnait les stores
#      SUIVANTS — une passe de retention entiere perdue pour un seul run.
#
# Le cliquet a signale la baisse tout seul — c'est son autre sens. Sans lui, un
# plafond reste acquis apres un correctif et 3 sites pourraient revenir en
# silence.
# 63 -> 59, le 2026-08-29, en DEUX temps :
#   63  population vue par l'ancien recensement (marge zero) ;
#   65  apres elargissement de `_ACCES_STORE` — deux sites reels etaient hors
#       radar, `resolved_store.run.insert_error` et
#       `default_store.run.list_pending_runs` ;
#   59  apres correction de six sites (regle inviolable n4).
#   59  le 2026-08-31, apres ELARGISSEMENT du perimetre a `app.py` et
#       `scripts/` : le nombre ne bouge pas, ces deux racines n'ont aucun site
#       a risque. C'est un elargissement gratuit, pas une absence de mesure —
#       `test_le_perimetre_VOIT_bien_app_py` l'epingle.
PLAFOND = 59


def _noms_exceptions(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"<nu>"}
    noeuds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    out: set[str] = set()
    for n in noeuds:
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(ast.unparse(n))
    return out


#: Un acces au store, quel que soit le NOM de la variable qui le porte.
#:
#: 2026-08-29 : ce recensement filtrait sur une liste FERMEE de prefixes
#: (`store.`, `self._store.`, `self.store.`, `_store.`) plus `.store.`. Il etait
#: donc aveugle a tout renommage de variable — mesure du jour, DEUX sites reels
#: lui echappaient : `resolved_store.run.insert_error` (cinesort_api.py:572) et
#: `default_store.run.list_pending_runs` (run_control_support.py:224). Le
#: cliquet avait 63 sites pour un plafond de 63, donc marge zero... sur une
#: population amputee.
#:
#: Le motif accepte desormais n'importe quel identifiant se terminant par
#: `store`, precede du debut de l'expression ou d'un point : `store.`,
#: `_store.`, `resolved_store.`, `self.default_store.`. Il ne mord PAS sur
#: `restore.` (le groupe optionnel doit se terminer par `_`).
_ACCES_STORE = re.compile(r"(?:^|\.)(?:[A-Za-z0-9]+_)*_?store\.", re.IGNORECASE)


def _touche_le_store(corps: list) -> bool:
    for noeud in ast.walk(ast.Module(body=corps, type_ignores=[])):
        if isinstance(noeud, ast.Attribute):
            if _ACCES_STORE.search(ast.unparse(noeud)):
                return True
    return False


def _sites_a_risque() -> list[str]:
    out: list[str] = []
    for chemin in _fichiers_python():
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = chemin.relative_to(_REPERTOIRE_DU_DEPOT).as_posix()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Try):
                continue
            for handler in noeud.handlers:
                noms = _noms_exceptions(handler)
                if "OSError" not in noms:
                    continue
                if any("sqlite3" in n or n in ("Exception", "BaseException") for n in noms):
                    continue
                if _touche_le_store(noeud.body):
                    out.append(f"{rel}:{handler.lineno}")
    return out


class CliquetSqliteErrorTests(unittest.TestCase):
    def test_la_mesure_trouve_bien_quelque_chose(self) -> None:
        """Sans ca, une regex ou un critere casse rendrait le cliquet complaisant :
        zero site trouve fait passer n'importe quel plafond."""
        self.assertGreater(len(_sites_a_risque()), 0)

    def test_le_perimetre_VOIT_bien_app_py(self) -> None:
        """Le compte est reste a 59 apres l'elargissement. Un zero a toujours
        deux lectures : « rien a signaler » ou « personne n'a regarde ». Ce
        test tranche — sans lui, une racine mal orthographiee rendrait un
        perimetre silencieusement ampute et un cliquet toujours vert.
        """
        fichiers = _fichiers_python()
        noms = {f.relative_to(_REPERTOIRE_DU_DEPOT).as_posix() for f in fichiers}

        self.assertIn("app.py", noms)
        self.assertTrue(any(n.startswith("scripts/") for n in noms), "scripts/ absent du perimetre")
        self.assertTrue(any(n.startswith("cinesort/") for n in noms), "cinesort/ absent du perimetre")

    def test_la_population_ne_REMONTE_pas(self) -> None:
        sites = _sites_a_risque()

        self.assertLessEqual(
            len(sites),
            PLAFOND,
            f"{len(sites)} sites (plafond {PLAFOND}) : un `except OSError` de plus entoure un appel de "
            "repository sans attraper sqlite3.Error. Ajouter `sqlite3.Error` au tuple SI le site est un "
            "chemin de LECTURE ; sur un chemin destructif, laisser remonter et le dire dans un commentaire.",
        )

    def test_le_plafond_n_est_pas_PERIME(self) -> None:
        """Un cliquet dont le plafond depasse largement la realite ne cliquette
        plus. Des que la population baisse, le plafond doit suivre."""
        sites = _sites_a_risque()

        self.assertGreaterEqual(
            len(sites),
            PLAFOND,
            f"{len(sites)} sites contre un plafond de {PLAFOND} : la population a baisse, "
            "abaisser PLAFOND d'autant pour que le cliquet garde sa marge zero.",
        )

    def test_sqlite3_Error_n_herite_toujours_PAS_de_OSError(self) -> None:
        """La premisse de tout ce fichier. Si elle changeait un jour, tout ce
        cliquet deviendrait du bruit — mieux vaut qu'il le dise lui-meme."""
        import sqlite3

        self.assertFalse(issubclass(sqlite3.Error, OSError))


if __name__ == "__main__":
    unittest.main()
