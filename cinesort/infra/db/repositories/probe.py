"""ProbeRepository : adapter composition du _ProbeMixin (issue #85)."""

from __future__ import annotations

from cinesort.infra.db._probe_mixin import _ProbeMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class ProbeRepository(_BaseRepository, _ProbeMixin):
    """Repository pour le cache ffprobe/mediainfo.

    Methodes exposees (depuis _ProbeMixin) :
        get_probe_cache, upsert_probe_cache, prune_probe_cache
    """

    pass
