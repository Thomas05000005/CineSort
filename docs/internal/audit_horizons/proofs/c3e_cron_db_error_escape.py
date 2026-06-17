"""C3-E — Repro : les crons retention/quarantaine MEURENT sur une erreur sqlite
transitoire (database is locked) car le tuple d'except omet sqlite3.Error.

Cause racine partagee [15]+[16] : _run_cleanup_once / _run_purge_once attrapent
(AttributeError, OSError, RuntimeError, TypeError, ValueError) — PAS
sqlite3.OperationalError/DatabaseError (qui derivent de sqlite3.Error->Exception).
Donc une erreur 'database is locked' echappe -> sort de _worker -> le thread
daemon se termine DEFINITIVEMENT (plus aucune purge/retention jusqu'au restart).

Harnais (pur, aucun effet de bord) :
  T1  cleanup_old_runs leve sqlite3.OperationalError -> _run_cleanup_once RE-LEVE
      (ne swallow PAS) -> dans _worker, le thread mourrait.
  T2 (controle/falsifiabilite) : leve OSError -> _run_cleanup_once SWALLOW
      (return None) -> le cron survivrait. Prouve que le harnais discrimine.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/c3e_cron_db_error_escape.py
"""
from __future__ import annotations
import json
import sqlite3
import types

from cinesort.app import retention_cleanup, quarantine_ttl


class _FakeRun:
    def __init__(self, exc): self._exc = exc
    def cleanup_old_runs(self, retention_days): raise self._exc


class _FakeApi:
    def __init__(self, exc): self.run = _FakeRun(exc)


def _probe(fn, exc):
    """Retourne 'SWALLOW' si fn ne leve pas, sinon le nom de l'exception relevee."""
    try:
        fn(_FakeApi(exc), 90)
        return "SWALLOW (cron survit)"
    except BaseException as e:  # noqa: BLE001
        return f"RE-LEVE {type(e).__name__} (thread cron MEURT)"


def run():
    out = {}
    db_lock = sqlite3.OperationalError("database is locked")

    # T1 : retention cron face a un verrou DB
    out["T1_retention_sqlite_lock"] = {
        "comportement": _probe(retention_cleanup._run_cleanup_once, db_lock),
        "VERDICT": "BUG CONFIRME (cron meurt sur verrou DB)"
                   if "RE-LEVE" in _probe(retention_cleanup._run_cleanup_once, db_lock)
                   else "robuste",
    }
    # quarantine cron : meme pattern (_run_purge_once)
    out["T1b_quarantine_sqlite_lock"] = {
        "comportement": _probe(quarantine_ttl._run_purge_once, db_lock),
    }

    # T2 : controle -> OSError doit etre swallow (falsifiabilite)
    out["T2_controle_OSError"] = {
        "comportement": _probe(retention_cleanup._run_cleanup_once, OSError("disk glitch")),
        "VERDICT": "harnais DISCRIMINE (OSError swallow, sqlite re-leve)"
                   if "SWALLOW" in _probe(retention_cleanup._run_cleanup_once, OSError("x"))
                   else "ne discrimine pas",
    }

    # T3 : confirmer que sqlite3.OperationalError n'est PAS dans le tuple attrape
    out["T3_taxonomie"] = {
        "OperationalError_est_OSError": issubclass(sqlite3.OperationalError, OSError),
        "OperationalError_est_RuntimeError": issubclass(sqlite3.OperationalError, RuntimeError),
        "OperationalError_base": sqlite3.OperationalError.__mro__[1].__name__,
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
