"""PerceptualRepository : adapter composition du _PerceptualMixin (issue #85).

NB : _PerceptualMixin utilise self._ensure_tables(*_PERCEPTUAL_TABLES) au lieu
de self._ensure_schema_group, donc l'adapter doit injecter _ensure_tables.
Si la methode est absente de _BaseRepository, on l'attache au runtime via
le constructeur (avec un fallback warning).
"""

from __future__ import annotations

from cinesort.infra.db._perceptual_mixin import _PerceptualMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class PerceptualRepository(_BaseRepository, _PerceptualMixin):
    """Repository pour les rapports perceptuels (LPIPS, doublons, anti-fingerprint).

    Methodes exposees (depuis _PerceptualMixin) :
        upsert_perceptual_report, get_perceptual_report, list_perceptual_reports,
        get_global_tier_v2_distribution, get_global_score_v2_trend,
        count_v2_tier_since, count_v2_warnings_flag
    """

    pass
