"""VO-A-NAS backend -- benchmark perf SQLite + DB_LOCAL_GUARD UNC.

Ce module regroupe deux mecanismes lies a la validation du stockage choisi
par l'utilisateur pour la DB CineSort :

1. ``run_nas_benchmark(db_path, n_writes, n_reads)`` --
   Benchmark non destructif des ecritures + lectures SQLite sur le storage
   cible. Cree une table dediee ``__cinesort_nas_bench_<rand>`` que l'on
   DROP a la fin (fail-safe via try/finally). Mesure les percentiles
   p50/p95/p99 des temps individuels et un compteur de WAL checkpoints.

   Retourne un dict serialisable JSON :
       {
           "ok": bool,
           "db_path": str,
           "n_writes": int,
           "n_reads": int,
           "p50_write_ms": float, "p95_write_ms": float, "p99_write_ms": float,
           "p50_read_ms": float,  "p95_read_ms": float,  "p99_read_ms": float,
           "wal_growth_kb": float,        # difference taille WAL apres bench
           "checkpoint_count": int,        # nb de PRAGMA wal_checkpoint(PASSIVE) appeles
           "total_duration_s": float,
           "started_at": ISO-8601 UTC,
           "finished_at": ISO-8601 UTC,
       }

2. ``db_local_guard(db_path, allow_unc=False)`` --
   Garde fail-closed : leve ``RuntimeError`` si ``db_path`` est UNC
   (``\\\\server\\share\\...``) et que l'utilisateur n'a PAS donne son
   accord explicite (param ``allow_unc=True`` ou env var
   ``CINESORT_ALLOW_UNC_DB=1``). Cf memoire utilisateur "Sereo/CineSort
   migrations SQLite : tester DB pre-existante" + Sonarr #1886 (corruption
   silencieuse SQLite sur SMB) qui justifient ce blocage.

3. ``write_benchmark_report(result, state_dir)`` --
   Sauve le resultat du benchmark en JSON sous
   ``<state_dir>/diagnostics/nas_benchmark_<UTC ISO-8601 compact>.json``.
   Le dossier ``diagnostics/`` est cree si absent. Retourne le ``Path``
   ecrit.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import sqlite3
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB_LOCAL_GUARD : refuse les chemins UNC sauf override explicite.
# ---------------------------------------------------------------------------

_ENV_ALLOW_UNC = "CINESORT_ALLOW_UNC_DB"
_TRUTHY = {"1", "true", "yes", "on"}


def _is_unc_path(db_path: Path) -> bool:
    """True si ``db_path`` est un chemin UNC Windows (``\\\\server\\share\\...``).

    Implementation locale (pas d'import circulaire avec
    ``cinesort.infra.db.pragma_profile.is_unc_path``). On accepte aussi les
    variantes long-path Windows ``\\\\?\\UNC\\server\\share\\...``.
    """
    db_str = str(db_path)
    if db_str.startswith("\\\\?\\UNC\\"):
        return True
    if db_str.startswith("\\\\"):
        return True
    try:
        drive = Path(db_str).drive
    except (TypeError, ValueError, OSError):
        return False
    return drive.startswith("\\\\")


def db_local_guard(db_path: Path, allow_unc: bool = False) -> None:
    """Garde fail-closed : refuse UNC si pas d'accord explicite.

    Raises:
        RuntimeError: si ``db_path`` est UNC et que ni ``allow_unc=True`` ni
            ``CINESORT_ALLOW_UNC_DB=1`` n'est positionne.

    Comportement :
        * Chemin local Windows / POSIX : no-op, retour silencieux.
        * Chemin UNC + override explicite : log WARN, retour silencieux.
        * Chemin UNC sans override : leve ``RuntimeError`` avec message
          actionnable (mentionne la variable d'env de bypass).
    """
    path = Path(db_path)
    if not _is_unc_path(path):
        return  # storage local, rien a verifier.

    env_override = str(os.environ.get(_ENV_ALLOW_UNC, "")).strip().lower() in _TRUTHY
    if allow_unc or env_override:
        logger.warning(
            "DB_LOCAL_GUARD : DB SQLite sur chemin UNC autorisee par override "
            "(allow_unc=%s, env %s=%s) : %s. Risque corruption SMB connu "
            "(Sonarr #1886). Surveiller les checkpoints WAL.",
            allow_unc,
            _ENV_ALLOW_UNC,
            os.environ.get(_ENV_ALLOW_UNC, ""),
            path,
        )
        return

    raise RuntimeError(
        "DB_LOCAL_GUARD : la base SQLite CineSort est configuree sur un chemin "
        f"UNC (partage SMB/CIFS) : {path}\n"
        "Le stockage SQLite sur SMB est connu pour provoquer des corruptions "
        "silencieuses (cf Sonarr #1886). CineSort refuse de demarrer par "
        "defaut.\n"
        "Pour passer outre a vos risques et perils, definir la variable "
        f"d'environnement {_ENV_ALLOW_UNC}=1 ou rappeler db_local_guard avec "
        "allow_unc=True. Recommandation : utiliser un chemin local "
        "(C:\\Users\\<user>\\AppData\\Local\\CineSort\\db\\...) puis copier "
        "manuellement la DB sur le NAS pour sauvegarde."
    )


# ---------------------------------------------------------------------------
# Benchmark perf SQLite (write + read percentiles).
# ---------------------------------------------------------------------------


def _percentile(samples: List[float], pct: float) -> float:
    """Percentile interpole lineairement (pas de dependance numpy).

    ``samples`` doit etre non vide. ``pct`` dans [0, 100].
    """
    if not samples:
        return 0.0
    if pct <= 0:
        return float(min(samples))
    if pct >= 100:
        return float(max(samples))
    ordered = sorted(samples)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    frac = rank - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _wal_size_bytes(db_path: Path) -> int:
    """Taille du fichier ``<db>-wal`` en bytes, 0 si absent."""
    wal = db_path.with_name(db_path.name + "-wal")
    try:
        return int(wal.stat().st_size)
    except (FileNotFoundError, OSError):
        return 0


def _random_table_name() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"__cinesort_nas_bench_{suffix}"


def run_nas_benchmark(
    db_path: Path,
    n_writes: int = 1000,
    n_reads: int = 10000,
) -> Dict[str, Any]:
    """Benchmark non destructif des ecritures + lectures SQLite.

    Cree une table dediee ``__cinesort_nas_bench_<rand>``, INSERT
    ``n_writes`` lignes (chaque INSERT est mesure individuellement), SELECT
    ``n_reads`` lectures par primary key aleatoire, puis DROP la table.

    Le DROP TABLE et le checkpoint final sont executes dans ``finally`` pour
    garantir le nettoyage meme en cas d'erreur a mi-bench.

    Args:
        db_path: chemin vers la DB SQLite cible (peut etre local ou NAS).
        n_writes: nombre d'INSERT a executer (default 1000).
        n_reads: nombre de SELECT a executer (default 10000).

    Returns:
        dict structure documente dans le docstring du module.
    """
    db_path = Path(db_path)
    n_writes = max(1, int(n_writes))
    n_reads = max(1, int(n_reads))

    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()

    wal_before = _wal_size_bytes(db_path)

    write_times_ms: List[float] = []
    read_times_ms: List[float] = []
    checkpoint_count = 0
    table_name = _random_table_name()
    error_msg: Optional[str] = None
    ok = False

    conn: Optional[sqlite3.Connection] = None
    try:
        # On utilise sqlite3.connect direct pour ne PAS reposer sur
        # connect_sqlite() (qui pose des PRAGMA profil + emet du logging
        # d'audit non desire pour un benchmark transitoire). Le bench est
        # transparent vis-a-vis du PRAGMA profil deja applique a la DB
        # principale (le WAL et le journal_mode sont par-DB pas par-conn).
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")

        # 1. Creer la table dediee (pas TEMPORARY : on veut mesurer le vrai
        #    cout d'ecriture sur le storage cible, pas en RAM).
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table_name} ("
            " id INTEGER PRIMARY KEY,"
            " payload TEXT NOT NULL,"
            " ts REAL NOT NULL)"
        )

        # 2. Mesurer chaque INSERT (commit individuel pour stresser la
        #    durabilite WAL/SMB ; c'est l'usage reel CineSort qui commit
        #    apres chaque batch apply_rows).
        payload_blob = "x" * 256  # 256 char payload pour rester realiste
        for i in range(n_writes):
            t0 = time.perf_counter()
            conn.execute(
                f"INSERT INTO {table_name} (id, payload, ts) VALUES (?, ?, ?)",
                (i, payload_blob, time.time()),
            )
            conn.commit()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            write_times_ms.append(elapsed_ms)

            # Checkpoint periodique (toutes les 200 ecritures) : reflete le
            # comportement reel du profil PRAGMA NAS (wal_autocheckpoint=200).
            if (i + 1) % 200 == 0:
                try:
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    checkpoint_count += 1
                except sqlite3.Error as exc:
                    logger.debug("nas_bench: wal_checkpoint a echoue : %s", exc)

        # 3. Mesurer chaque SELECT par PK aleatoire.
        for _ in range(n_reads):
            target_id = random.randint(0, n_writes - 1)
            t0 = time.perf_counter()
            cur = conn.execute(
                f"SELECT payload, ts FROM {table_name} WHERE id = ?",
                (target_id,),
            )
            cur.fetchone()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            read_times_ms.append(elapsed_ms)

        ok = True
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("nas_bench: erreur pendant le benchmark")
    finally:
        if conn is not None:
            # Cleanup garanti (memoire utilisateur : benchmark non destructif).
            try:
                conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("nas_bench: DROP TABLE %s a echoue : %s", table_name, exc)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                checkpoint_count += 1
            except sqlite3.Error as exc:
                logger.debug("nas_bench: wal_checkpoint(TRUNCATE) final a echoue : %s", exc)
            try:
                conn.close()
            except sqlite3.Error:
                pass

    wal_after = _wal_size_bytes(db_path)
    wal_growth_kb = max(0.0, (wal_after - wal_before) / 1024.0)
    total_duration_s = time.monotonic() - started_monotonic
    finished_at = datetime.now(timezone.utc)

    result: Dict[str, Any] = {
        "ok": ok,
        "db_path": str(db_path),
        "n_writes": n_writes,
        "n_reads": n_reads,
        "p50_write_ms": _percentile(write_times_ms, 50.0),
        "p95_write_ms": _percentile(write_times_ms, 95.0),
        "p99_write_ms": _percentile(write_times_ms, 99.0),
        "p50_read_ms": _percentile(read_times_ms, 50.0),
        "p95_read_ms": _percentile(read_times_ms, 95.0),
        "p99_read_ms": _percentile(read_times_ms, 99.0),
        "wal_growth_kb": wal_growth_kb,
        "checkpoint_count": checkpoint_count,
        "total_duration_s": total_duration_s,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
    }
    if error_msg is not None:
        result["error"] = error_msg
    return result


# ---------------------------------------------------------------------------
# Persistance du rapport.
# ---------------------------------------------------------------------------


def write_benchmark_report(result: Dict[str, Any], state_dir: Path) -> Path:
    """Sauve ``result`` en JSON sous ``<state_dir>/diagnostics/nas_benchmark_<ts>.json``.

    Le timestamp utilise est UTC ISO-8601 compact (``YYYYMMDDTHHMMSSZ``)
    pour faciliter le tri lexicographique. Le dossier ``diagnostics/`` est
    cree si absent (parents=True).

    Args:
        result: dict retourne par ``run_nas_benchmark``.
        state_dir: dossier d'etat CineSort (typiquement ``%LOCALAPPDATA%\\CineSort``).

    Returns:
        Path absolu du fichier ecrit.
    """
    state_dir = Path(state_dir)
    diag_dir = state_dir / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # Timestamp compact pour tri lexicographique.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = diag_dir / f"nas_benchmark_{ts}.json"

    payload = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
    out_path.write_text(payload, encoding="utf-8")
    logger.info(
        "nas_bench: rapport ecrit %s (ok=%s, p95_write=%.2fms, p95_read=%.2fms)",
        out_path,
        result.get("ok"),
        float(result.get("p95_write_ms", 0.0)),
        float(result.get("p95_read_ms", 0.0)),
    )
    return out_path


__all__ = [
    "db_local_guard",
    "run_nas_benchmark",
    "write_benchmark_report",
]
