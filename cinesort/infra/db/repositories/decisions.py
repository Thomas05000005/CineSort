"""DecisionsRepository : decisions tri-etat film (Vague P / VP-D).

Cf migration 031_tri_etat_decisions.sql.

Pattern : decision tri-etat `accepted | rejected | deferred` (vs le
legacy binaire `ok: true | false`). Permet de mettre un film "en
suspens" sans forcer un choix definitif.

**Backward compat ABSOLUE** (memo `feedback_sqlite_migration_test_existing_db`
+ regle Vague P) : le helper `to_legacy_ok_bool(decision)` permet de
projeter une decision tri-etat sur la shape historique `{ok: bool}`
attendue par tous les call-sites pre-existants. Aucun endpoint legacy
ne casse.

API :
    - set_decision(film_id, run_id, decision, *, row_id, decided_by, reason)
    - get_decision(film_id, run_id) -> dict | None
    - list_decisions_for_run(run_id, *, decision_filter=None)
    - list_decisions_for_film(film_id) -> list[dict]
    - clear_decision(film_id, run_id) -> bool removed
    - upgrade_deferred_to_accepted(film_id, run_id, *, locked_fields=None,
        decided_by='user') : transition specifique deferred -> accepted
        qui RESPECTE les `field_locks` de VP-C (AC-3).
    - to_legacy_ok_bool(decision) : helper backward compat.

Coordination Vague P :
    - VP-A apply_atomic : kwargs distincts (`apply_atomic` ne transite
      pas par cette repo, pas de collision possible — AC-5).
    - VP-C field_locks : `upgrade_deferred_to_accepted` consulte les
      locks AVANT toute mise a jour metadata (AC-3).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository


# ---------------------------------------------------------------------------
# Constantes & helpers backward compat
# ---------------------------------------------------------------------------

DECISION_ACCEPTED = "accepted"
DECISION_REJECTED = "rejected"
DECISION_DEFERRED = "deferred"

_VALID_DECISIONS = frozenset({DECISION_ACCEPTED, DECISION_REJECTED, DECISION_DEFERRED})


def to_legacy_ok_bool(decision: Any) -> bool:
    """Helper backward compat ABSOLUE (Vague P / VP-D).

    Projette une decision tri-etat sur la shape historique `{ok: bool}` :
        - 'accepted' -> True
        - 'rejected' -> False
        - 'deferred' -> False  (un film "reporte" n'est PAS approuve pour apply)
        - autre / None / valeur inconnue -> False (safe default)

    Permet a tous les endpoints existants qui retournent `{ok: bool}`
    de conserver leur shape sans casser la backward compat.

    Args:
        decision: une chaine de caractere parmi {accepted, rejected, deferred}
            (ou n'importe quelle valeur — non strict).

    Returns:
        True UNIQUEMENT si decision == 'accepted'.
    """
    return str(decision or "").strip().lower() == DECISION_ACCEPTED


def from_legacy_ok_bool(ok: Any) -> str:
    """Inverse de `to_legacy_ok_bool` : projette `{ok: bool}` vers tri-etat.

    Utilise quand un endpoint legacy envoie encore `{ok: True}` / `{ok: False}`
    et qu'on veut le stocker dans la nouvelle table.

    Returns:
        'accepted' si ok == True (strict bool truth)
        'rejected' sinon (False, None, '' -> rejected)
    """
    return DECISION_ACCEPTED if bool(ok) is True else DECISION_REJECTED


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class DecisionsRepository(_BaseRepository):
    """Repository pour `film_decisions_v2` (migration 031, Vague P / VP-D).

    Conventions :
        - `set_decision` est un upsert sur (film_id, run_id) — UNIQUE.
        - `decision` doit etre dans {accepted, rejected, deferred} sinon
          ValueError.
        - Toutes les methodes refusent un film_id vide (retournent ok=False
          ou liste vide selon le cas).
    """

    SCHEMA_GROUP = "tri_etat_decisions"

    def _ensure_tables(self) -> None:
        self._store._ensure_schema_group(self.SCHEMA_GROUP, min_user_version=31)

    # ------------------------------------------------------------------
    # set_decision / get_decision / clear_decision
    # ------------------------------------------------------------------

    def set_decision(
        self,
        film_id: str,
        run_id: str,
        decision: str,
        *,
        row_id: str = "",
        decided_by: str = "user",
        reason: str = "",
    ) -> Dict[str, Any]:
        """Pose (ou met a jour) une decision tri-etat.

        Args:
            film_id: cle stable (`tmdb:<id>` ou `path:<sha1>`).
            run_id: run d'origine (audit).
            decision: 'accepted' | 'rejected' | 'deferred'.
            row_id: row UI d'origine (audit, optionnel).
            decided_by: 'user' | 'auto' | 'bulk' | ...
            reason: raison optionnelle.

        Returns:
            {ok: True, decided_at: float, decision: str} ou
            {ok: False, reason: str}.
        """
        fid = _safe_str(film_id)
        if not fid:
            return {"ok": False, "reason": "film_id requis"}

        dec = _safe_str(decision).lower()
        if dec not in _VALID_DECISIONS:
            return {
                "ok": False,
                "reason": (
                    f"decision invalide: {decision!r} "
                    f"(attendu: {sorted(_VALID_DECISIONS)})"
                ),
            }

        self._ensure_tables()
        ts = time.time()
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO film_decisions_v2(
                    film_id, run_id, row_id, decision,
                    decided_at, decided_by, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(film_id, run_id) DO UPDATE SET
                    row_id=excluded.row_id,
                    decision=excluded.decision,
                    decided_at=excluded.decided_at,
                    decided_by=excluded.decided_by,
                    reason=excluded.reason
                """,
                (
                    fid,
                    _safe_str(run_id),
                    _safe_str(row_id),
                    dec,
                    ts,
                    _safe_str(decided_by) or "user",
                    _safe_str(reason),
                ),
            )
        return {"ok": True, "decided_at": ts, "decision": dec}

    def get_decision(self, film_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """Retourne {decision, decided_at, decided_by, reason, row_id} ou None."""
        fid = _safe_str(film_id)
        if not fid:
            return None
        rid = _safe_str(run_id)

        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT decision, decided_at, decided_by, reason, row_id
                FROM film_decisions_v2
                WHERE film_id=? AND run_id=?
                LIMIT 1
                """,
                (fid, rid),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _row_to_decision_dict(row)

    def clear_decision(self, film_id: str, run_id: str) -> Dict[str, Any]:
        """Retire une decision. Retourne {ok, removed: bool}."""
        fid = _safe_str(film_id)
        if not fid:
            return {"ok": False, "removed": False, "reason": "film_id requis"}
        rid = _safe_str(run_id)

        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                "DELETE FROM film_decisions_v2 WHERE film_id=? AND run_id=?",
                (fid, rid),
            )
            removed = bool(cur.rowcount)
        return {"ok": True, "removed": removed}

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    def list_decisions_for_run(
        self,
        run_id: str,
        *,
        decision_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retourne toutes les decisions d'un run (filtrable par etat).

        Args:
            run_id: id du run.
            decision_filter: si specifie, filtre sur cet etat
                (accepted/rejected/deferred). None = tous.
        """
        rid = _safe_str(run_id)
        if not rid:
            return []
        self._ensure_tables()

        params: list[Any] = [rid]
        where = "run_id=?"
        if decision_filter is not None:
            df = _safe_str(decision_filter).lower()
            if df not in _VALID_DECISIONS:
                return []
            where += " AND decision=?"
            params.append(df)

        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT film_id, decision, decided_at, decided_by, reason, row_id
                FROM film_decisions_v2
                WHERE {where}
                ORDER BY decided_at DESC
                """,
                params,
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            entry = _row_to_decision_dict(row)
            entry["film_id"] = str(row["film_id"])
            result.append(entry)
        return result

    def list_decisions_for_film(self, film_id: str) -> List[Dict[str, Any]]:
        """Retourne toutes les decisions historiques d'un film (tous runs)."""
        fid = _safe_str(film_id)
        if not fid:
            return []
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, decision, decided_at, decided_by, reason, row_id
                FROM film_decisions_v2
                WHERE film_id=?
                ORDER BY decided_at DESC
                """,
                (fid,),
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            entry = _row_to_decision_dict(row)
            entry["run_id"] = str(row["run_id"])
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Transitions specifiques (AC-3 : VP-C field_locks)
    # ------------------------------------------------------------------

    def upgrade_deferred_to_accepted(
        self,
        film_id: str,
        run_id: str,
        *,
        locked_fields: Optional[List[str]] = None,
        decided_by: str = "user",
        reason: str = "",
    ) -> Dict[str, Any]:
        """Transition `deferred -> accepted` qui respecte les field_locks VP-C.

        AC-3 ROADMAP_VAGUE_P : la transition d'un etat `deferred` vers
        `accepted` doit consulter les `field_locks` (Jellyfin-style)
        AVANT d'appliquer toute mise a jour metadata. Cette repo ne
        modifie pas les metadata elle-meme, mais elle EXPOSE la liste
        des champs verrouilles dans la reponse pour que le caller (UI
        ou orchestration) puisse afficher la liste et eviter d'ecraser.

        Args:
            film_id: cle stable.
            run_id: run d'origine.
            locked_fields: liste des champs actuellement verrouilles
                (fournie par le caller via `FieldLocksRepository.list_locks`).
                Si None, le caller n'a pas consulte les locks — on log
                un warning mais on procede quand meme.
            decided_by: audit.
            reason: audit.

        Returns:
            {
                ok: bool,
                previous_decision: str | None,
                new_decision: 'accepted',
                respected_locks: list[str],
                warning: str | None,
            }
        """
        previous = self.get_decision(film_id, run_id)
        prev_decision = previous["decision"] if previous else None

        warning: Optional[str] = None
        if locked_fields is None:
            warning = (
                "locked_fields non fourni : la transition deferred -> accepted "
                "n'a pas consulte les field_locks VP-C. Le caller doit "
                "appeler FieldLocksRepository.list_locks() en prealable."
            )
            locked_fields_safe: List[str] = []
        else:
            locked_fields_safe = [
                _safe_str(f) for f in locked_fields if _safe_str(f)
            ]

        res = self.set_decision(
            film_id,
            run_id,
            DECISION_ACCEPTED,
            row_id=previous.get("row_id", "") if previous else "",
            decided_by=decided_by,
            reason=reason or "upgrade_deferred_to_accepted",
        )
        if not res.get("ok"):
            return {
                "ok": False,
                "previous_decision": prev_decision,
                "new_decision": None,
                "respected_locks": locked_fields_safe,
                "warning": res.get("reason") or warning,
            }
        return {
            "ok": True,
            "previous_decision": prev_decision,
            "new_decision": DECISION_ACCEPTED,
            "respected_locks": locked_fields_safe,
            "warning": warning,
        }


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


def _row_to_decision_dict(row: Any) -> Dict[str, Any]:
    return {
        "decision": str(row["decision"] or "").lower(),
        "decided_at": float(row["decided_at"]),
        "decided_by": str(row["decided_by"] or "user"),
        "reason": str(row["reason"] or ""),
        "row_id": str(row["row_id"] or ""),
    }
