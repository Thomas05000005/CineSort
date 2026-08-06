"""Ou passe le temps d'une ouverture de connexion SQLite ? Mesure rejouable.

    ./.venv/Scripts/python.exe scripts/mesure_cout_connexion.py

POURQUOI CE SCRIPT EXISTE. Le plan de remise en etat attribuait le surcout de
`connect_sqlite` aux « ~14 PRAGMA par appel ». La mesure dit autre chose, et
c'est ce qui decide de la forme du correctif :

    sqlite3.connect nu (+close)          0,084 ms
    les 8 PRAGMA sur connexion TIEDE     0,008 ms
    les 8 PRAGMA sur connexion FRAICHE   1,100 ms      <-- 90 % du total
    connect_sqlite (total)               1,215 ms

Les MEMES instructions coutent 140 fois plus sur un handle neuf : `journal_mode
= WAL` doit ouvrir et verrouiller le fichier -wal, `mmap_size` doit mapper. Ce
n'est donc pas leur NOMBRE qui coute — retirer six des quatorze n'a rendu que
1,7 % (A/B bras alternes, 150 tours par bras).

CONSEQUENCE : alleger la liste des PRAGMA ne servira a rien. Le gain est dans la
REUTILISATION de la connexion (scope de requete, puis cache par thread pour les
threads longs) — c'est la conclusion du plan, mais pour une raison qui n'y etait
pas ecrite, et cette raison-la dit ou ne PAS chercher.

DEUX PIEGES DE MESURE RENCONTRES, a ne pas refaire :

1. `cProfile` ajoute son cout a CHAQUE appel. Il attribuait 49 us par `execute`
   la ou la mesure directe en donne 1,5 : il fait paraitre couteux ce qui est
   frequent. On mesure ici sans profileur.
2. Une premiere sonde utilisait un fichier SQLite NU. Sans la table
   `pragma_history` (migration 028), `_record_pragma_history` echoue, RELACHE son
   verrou de frequence, et la relecture reste forcee a chaque ouverture — la
   sonde mesurait exactement le seul cas ou l'optimisation ne s'applique pas.
   D'ou le `SQLiteStore(...).initialize()` ci-dessous : il n'est pas decoratif.
"""

from __future__ import annotations

import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cinesort.infra.db.connection import connect_sqlite  # noqa: E402
from cinesort.infra.db.pragma_profile import (  # noqa: E402
    apply_pragmas,
    detect_storage_type,
    should_record_pragma_history,
)
from cinesort.infra.db.sqlite_store import SQLiteStore  # noqa: E402

TOURS = 150


def _mediane(fn) -> float:
    echantillons = []
    for _ in range(TOURS):
        debut = time.perf_counter()
        fn()
        echantillons.append((time.perf_counter() - debut) * 1000.0)
    return statistics.median(echantillons)


def main() -> None:
    with tempfile.TemporaryDirectory() as dossier:
        db = Path(dossier) / "cinesort.db"
        SQLiteStore(db).initialize()
        connect_sqlite(str(db)).close()  # amorce le verrou d'historique

        etapes: dict[str, float] = {
            "sqlite3.connect nu (+close)": _mediane(lambda: sqlite3.connect(str(db)).close()),
            "detect_storage_type": _mediane(lambda: detect_storage_type(str(db))),
            "should_record_pragma_history": _mediane(
                lambda: should_record_pragma_history(str(db), "local_ssd", "connect")
            ),
        }

        tiede = sqlite3.connect(str(db))
        try:
            etapes["8 PRAGMA sur connexion TIEDE"] = _mediane(
                lambda: apply_pragmas(tiede, "local_ssd", record_history=False, readback=False)
            )
        finally:
            tiede.close()

        def _fraiche():
            conn = sqlite3.connect(str(db))
            try:
                apply_pragmas(conn, "local_ssd", record_history=False, readback=False)
            finally:
                conn.close()

        etapes["8 PRAGMA sur connexion FRAICHE"] = _mediane(_fraiche)
        total = _mediane(lambda: connect_sqlite(str(db)).close())

        print(f"mediane sur {TOURS} tours\n")
        print(f"{'etape':36} {'ms':>8} {'% total':>9}")
        print("-" * 56)
        for nom, ms in sorted(etapes.items(), key=lambda kv: -kv[1]):
            print(f"{nom:36} {ms:8.3f} {ms / total * 100:8.1f} %")
        print("-" * 56)
        print(f"{'connect_sqlite (TOTAL)':36} {total:8.3f} {100.0:8.1f} %")
        print()
        cout_pragma_froid = etapes["8 PRAGMA sur connexion FRAICHE"] - etapes["sqlite3.connect nu (+close)"]
        facteur = cout_pragma_froid / max(etapes["8 PRAGMA sur connexion TIEDE"], 1e-9)
        print(f"Les MEMES 8 PRAGMA coutent x{facteur:.0f} sur un handle neuf.")
        print("Le gain est dans la REUTILISATION de la connexion, pas dans l'allegement des PRAGMA.")


if __name__ == "__main__":
    main()
