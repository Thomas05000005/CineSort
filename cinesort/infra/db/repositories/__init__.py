"""Repositories d'acces aux donnees SQLite (issue #85).

Avant : 7 mixins heritaient de _StoreBase et partageaient self._managed_conn,
self._ensure_schema_group, etc. — couplage implicite, ordre MRO fragile,
tests difficiles a isoler.

Apres : 7 Repository en composition, chacun recevant ses dependances
(conn_factory, schema_ensurer, etc.) en injection au constructeur.

SQLiteStore agrege les 7 Repository : self.apply = ApplyRepository(...),
self.quality = QualityRepository(...), etc.

Pour la backward-compat pendant la migration, SQLiteStore conserve des
methodes wrappers qui deleguent aux Repository : store.get_quality_report(...)
→ store.quality.get_report(...). Les wrappers seront supprimes en phase D
quand tous les callers seront migres vers store.{repo}.X().
"""

from __future__ import annotations

from cinesort.infra.db.repositories._base import _BaseRepository
from cinesort.infra.db.repositories.anomaly import AnomalyRepository
from cinesort.infra.db.repositories.apply import ApplyRepository
from cinesort.infra.db.repositories.perceptual import PerceptualRepository
from cinesort.infra.db.repositories.probe import ProbeRepository
from cinesort.infra.db.repositories.quality import QualityRepository
from cinesort.infra.db.repositories.run import RunRepository
from cinesort.infra.db.repositories.scan import ScanRepository

__all__ = [
    "_BaseRepository",
    "AnomalyRepository",
    "ApplyRepository",
    "PerceptualRepository",
    "ProbeRepository",
    "QualityRepository",
    "RunRepository",
    "ScanRepository",
]
