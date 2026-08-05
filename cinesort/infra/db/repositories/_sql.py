"""Helpers SQL partages par les Repository (issue #448).

Une clause `IN (...)` construite avec un placeholder par element est bornee par
`SQLITE_MAX_VARIABLE_NUMBER` : 999 avant SQLite 3.32.0, 32766 depuis. Au-dela,
`sqlite3.OperationalError: too many SQL variables` est levee A LA PREPARATION —
la requete n'est pas plus lente, elle ECHOUE. Le remede est le decoupage en
lots, et il n'existe qu'UNE implementation pour tous les repositories.

`chunked` demande la taille EXPLICITEMENT : chaque module lit sa propre
constante au moment de l'appel, ce qui laisse les tests la reduire pour exercer
le chemin multi-paquet (une valeur par defaut liee a la definition rendrait ce
chemin intestable).

Attention a la semantique : le decoupage est sur pour un `IN` (l'union des lots
redonne l'ensemble), mais FAUX pour un `DELETE ... NOT IN` (chaque lot
supprimerait ce qui n'est pas dans CE lot-la). Cf. `scan.py`, qui resout les
entrees obsoletes AVANT de supprimer par lots.
"""

from __future__ import annotations

from typing import Iterator, List, Sequence, TypeVar

#: Taille de paquet par defaut. SQLite borne le nombre de parametres lies
#: (SQLITE_MAX_VARIABLE_NUMBER) ET la profondeur de l'arbre d'expression
#: (SQLITE_MAX_EXPR_DEPTH, 1000) ; 200 laisse une marge confortable sous les
#: deux, tout en tenant en UNE requete les tailles reelles (<= 100 runs).
SQL_CHUNK = 200

_T = TypeVar("_T")


def chunked(values: Sequence[_T], size: int) -> Iterator[List[_T]]:
    """Decoupe une sequence en paquets de `size` (jamais de paquet vide)."""
    step = max(1, int(size))
    for start in range(0, len(values), step):
        yield list(values[start : start + step])
