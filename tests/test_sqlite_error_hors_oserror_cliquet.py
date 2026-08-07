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
import unittest
from pathlib import Path

_RACINE = Path("cinesort")

# Mesure du 2026-08-06. Ce nombre ne se recopie pas : il se remesure, et il ne
# doit JAMAIS remonter.
PLAFOND = 68


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


def _touche_le_store(corps: list) -> bool:
    for noeud in ast.walk(ast.Module(body=corps, type_ignores=[])):
        if isinstance(noeud, ast.Attribute):
            texte = ast.unparse(noeud)
            if texte.startswith(("store.", "self._store.", "self.store.", "_store.")) or ".store." in texte:
                return True
    return False


def _sites_a_risque() -> list[str]:
    out: list[str] = []
    for chemin in sorted(_RACINE.rglob("*.py")):
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = chemin.as_posix()
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
