"""FieldLocksRepository : verrous champ-par-champ Jellyfin-style (Vague P / VP-C).

Cf migration 030_field_locks.sql.

Pattern Jellyfin `LockedFields` : chaque (film_id, field_name) verrouille
une valeur qui ne sera plus ecrasee par un rescan/refresh automatique
(OMDb, TMDb, mediainfo, ffprobe). Le verrou n'est leve que sur action
explicite de l'utilisateur (`clear_lock`) ou suite a un Identify manuel
(migration de l'ancien film_id vers le nouveau via `migrate_locks`).

Lecon bug Jellyfin #15549 : les locks doivent survivre a close/reopen
de la connexion SQLite — d'ou le test `test_field_locks_persistence.py`
qui valide ce contrat.

API :
    - set_lock(film_id, field_name, value, *, run_id, row_id, source)
    - clear_lock(film_id, field_name) -> bool removed
    - get_lock(film_id, field_name) -> {locked_value, locked_at, source} | None
    - is_locked(film_id, field_name) -> bool
    - list_locks(film_id) -> list[dict]
    - migrate_locks(old_film_id, new_film_id) -> int migrated_count
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository


class FieldLocksRepository(_BaseRepository):
    """Repository pour `film_field_locks` (migration 030, Vague P / VP-C).

    Conventions :
        - `locked_value` est serialise en JSON (str/int/float/dict/list).
        - `set_lock` est un upsert sur (film_id, field_name) — UNIQUE.
        - Toutes les methodes refusent un film_id ou field_name vide
          (retournent ok=False ou raise selon le cas).
    """

    SCHEMA_GROUP = "field_locks"

    def _ensure_tables(self) -> None:
        self._store._ensure_schema_group(self.SCHEMA_GROUP, min_user_version=30)

    # ------------------------------------------------------------------
    # set_lock / clear_lock / get_lock / is_locked / list_locks
    # ------------------------------------------------------------------

    def set_lock(
        self,
        film_id: str,
        field_name: str,
        locked_value: Any,
        *,
        run_id: str = "",
        row_id: str = "",
        source: str = "ui_lock",
    ) -> Dict[str, Any]:
        """Pose (ou met a jour) un verrou champ-par-champ.

        Args:
            film_id: cle stable (`tmdb:<id>` ou `path:<sha1>`).
            field_name: nom du champ (ex. "title", "year", "tmdb_id").
            locked_value: valeur a verrouiller (serialisee en JSON).
            run_id: run d'origine (audit, optionnel).
            row_id: row UI d'origine (audit, optionnel).
            source: "manual_identify" | "user_edit" | "ui_lock" | ...

        Returns:
            {ok: bool, locked_at: float} ou {ok: False, reason: str}.
        """
        fid = _safe_str(film_id)
        fname = _safe_str(field_name)
        if not fid or not fname:
            return {"ok": False, "reason": "film_id et field_name requis"}

        try:
            encoded = json.dumps(locked_value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            encoded = json.dumps(str(locked_value), ensure_ascii=False)

        self._ensure_tables()
        ts = time.time()
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO film_field_locks(
                    film_id, run_id, row_id, field_name,
                    locked_value, locked_at, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(film_id, field_name) DO UPDATE SET
                    run_id=excluded.run_id,
                    row_id=excluded.row_id,
                    locked_value=excluded.locked_value,
                    locked_at=excluded.locked_at,
                    source=excluded.source
                """,
                (
                    fid,
                    _safe_str(run_id),
                    _safe_str(row_id),
                    fname,
                    encoded,
                    ts,
                    _safe_str(source) or "ui_lock",
                ),
            )
        return {"ok": True, "locked_at": ts}

    def clear_lock(self, film_id: str, field_name: str) -> Dict[str, Any]:
        """Retire un verrou. Retourne {ok, removed: bool}."""
        fid = _safe_str(film_id)
        fname = _safe_str(field_name)
        if not fid or not fname:
            return {"ok": False, "removed": False, "reason": "film_id et field_name requis"}

        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                "DELETE FROM film_field_locks WHERE film_id=? AND field_name=?",
                (fid, fname),
            )
            removed = bool(cur.rowcount)
        return {"ok": True, "removed": removed}

    def get_lock(self, film_id: str, field_name: str) -> Optional[Dict[str, Any]]:
        """Retourne le verrou {locked_value, locked_at, source, run_id, row_id}
        ou None si pas de lock."""
        fid = _safe_str(film_id)
        fname = _safe_str(field_name)
        if not fid or not fname:
            return None

        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT locked_value, locked_at, source, run_id, row_id
                FROM film_field_locks
                WHERE film_id=? AND field_name=?
                LIMIT 1
                """,
                (fid, fname),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _row_to_lock_dict(row)

    def is_locked(self, film_id: str, field_name: str) -> bool:
        """True si le champ est verrouille pour ce film."""
        fid = _safe_str(film_id)
        fname = _safe_str(field_name)
        if not fid or not fname:
            return False
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM film_field_locks WHERE film_id=? AND field_name=? LIMIT 1",
                (fid, fname),
            )
            return cur.fetchone() is not None

    def list_locks(self, film_id: str) -> List[Dict[str, Any]]:
        """Retourne tous les locks d'un film (ordre asc sur field_name)."""
        fid = _safe_str(film_id)
        if not fid:
            return []
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT field_name, locked_value, locked_at, source, run_id, row_id
                FROM film_field_locks
                WHERE film_id=?
                ORDER BY field_name ASC
                """,
                (fid,),
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            entry = _row_to_lock_dict(row)
            entry["field_name"] = str(row["field_name"])
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # migrate_locks : fix #5 transition path: -> tmdb:
    # ------------------------------------------------------------------

    def migrate_locks(self, old_film_id: str, new_film_id: str) -> int:
        """Migre TOUS les locks de old_film_id vers new_film_id.

        Fix #5 ROADMAP_VAGUE_P : lors de l'Identify manuel ou d'un rematch
        automatique reussi, le film_id passe de `path:<sha1>` a
        `tmdb:<id>`. Les locks existants doivent suivre, sinon ils sont
        perdus (et le rescan suivant ecrase tout).

        Strategie : on parcourt les locks de old_film_id et on les
        re-injecte via set_lock sur new_film_id. set_lock fait un upsert,
        donc si un lock existe deja sur new_film_id pour le meme
        field_name, c'est l'ancien (le manuel) qui ecrase le nouveau.

        Implementation : transaction unique (DELETE+INSERT atomique).

        Args:
            old_film_id: l'ancien id (typiquement `path:...`).
            new_film_id: le nouveau id (typiquement `tmdb:...`).

        Returns:
            Nombre de locks effectivement migres.
        """
        old = _safe_str(old_film_id)
        new = _safe_str(new_film_id)
        if not old or not new:
            return 0
        if old == new:
            return 0

        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT field_name, locked_value, locked_at, source, run_id, row_id
                FROM film_field_locks
                WHERE film_id=?
                """,
                (old,),
            )
            rows = cur.fetchall()
            if not rows:
                return 0

            migrated = 0
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO film_field_locks(
                        film_id, run_id, row_id, field_name,
                        locked_value, locked_at, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(film_id, field_name) DO UPDATE SET
                        run_id=excluded.run_id,
                        row_id=excluded.row_id,
                        locked_value=excluded.locked_value,
                        locked_at=excluded.locked_at,
                        source=excluded.source
                    """,
                    (
                        new,
                        str(row["run_id"] or ""),
                        str(row["row_id"] or ""),
                        str(row["field_name"]),
                        str(row["locked_value"] or ""),
                        float(row["locked_at"]),
                        str(row["source"] or "ui_lock"),
                    ),
                )
                migrated += 1

            conn.execute(
                "DELETE FROM film_field_locks WHERE film_id=?",
                (old,),
            )
        return migrated


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""


def _decode_locked_value(raw: Any) -> Any:
    """Decode locked_value : essaie JSON puis fallback str brut."""
    if raw is None:
        return None
    s = str(raw)
    if not s:
        return ""
    try:
        return json.loads(s)
    except (TypeError, ValueError, json.JSONDecodeError):
        return s


def _row_to_lock_dict(row: Any) -> Dict[str, Any]:
    return {
        "locked_value": _decode_locked_value(row["locked_value"]),
        "locked_at": float(row["locked_at"]),
        "source": str(row["source"] or "ui_lock"),
        "run_id": str(row["run_id"] or ""),
        "row_id": str(row["row_id"] or ""),
    }
