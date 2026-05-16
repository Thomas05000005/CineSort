"""_ProbeMixin : thin wrapper backward-compat (issue #85 phase B1).

Migration #85 phase B1 (2026-05-16) : le code metier a ete deplace dans
`cinesort.infra.db.repositories.probe.ProbeRepository`. Ce mixin devient
un thin wrapper qui delegue a `self.probe.X()` pour preserver l'API
publique de SQLiteStore (`store.get_probe_cache(...)` etc.) sans casser
les call sites existants.

Phase B8 future : SQLiteStore arretera d'heriter de ce mixin, les callers
migreront vers `store.probe.X(...)`, et ce fichier sera supprime.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class _ProbeMixin:
    """Backward-compat wrappers : delegue a self.probe (ProbeRepository).

    SQLiteStore.__init__ definit self.probe = ProbeRepository(self), donc
    quand un caller appelle store.get_probe_cache(...), Python suit la MRO
    jusqu'a ce mixin qui delegue.
    """

    def _ensure_probe_cache_table(self) -> None:
        self.probe._ensure_probe_cache_table()

    def get_probe_cache(
        self,
        *,
        path: str,
        size: int,
        mtime: float,
        tool: str,
    ) -> Optional[Dict[str, Any]]:
        return self.probe.get_probe_cache(path=path, size=size, mtime=mtime, tool=tool)

    def upsert_probe_cache(
        self,
        *,
        path: str,
        size: int,
        mtime: float,
        tool: str,
        raw_json: Dict[str, Any],
        normalized_json: Dict[str, Any],
        ts: Optional[float] = None,
    ) -> None:
        self.probe.upsert_probe_cache(
            path=path,
            size=size,
            mtime=mtime,
            tool=tool,
            raw_json=raw_json,
            normalized_json=normalized_json,
            ts=ts,
        )

    def prune_probe_cache(self, *, retention_days: int = 90) -> int:
        return self.probe.prune_probe_cache(retention_days=retention_days)
