"""Pydantic v2.13+ schemas pour les endpoints REELS du run_facade (V2.1).

Endpoints couverts (memoire utilisateur : "endpoints REELS run_facade.py:
start_plan / check_duplicates / apply complet — NE PAS inventer noms") :

- start_plan          -> StartPlanRequest / StartPlanResponse
- check_duplicates    -> CheckDuplicatesRequest / CheckDuplicatesResponse
- apply               -> ApplyRequest / ApplyResponse

BACKWARD COMPAT ABSOLUE (memoire : "TOUS les changements V2 = migration
progressive avec feature flag, ancien code fonctionne TOUJOURS") :

- Tous les schemas tolerent les champs supplementaires (`extra="allow"`)
  pour ne pas casser un caller qui envoie plus de cles que le schema
  documente. La validation est passive par defaut.
- L'integration dans run_facade utilise le feature flag
  `CINESORT_PYDANTIC_STRICT` (defaut 0 = passif : on log un warning et on
  retombe sur le payload `dict[str, Any]` legacy si la validation echoue).
- Lorsque le flag passe a 1, l'echec de validation devient bloquant.

Aucun schema ne fait de transformation des donnees lourdes : la couche
domain (`run_models`, `probe_models`, `perceptual.models`) reste la source
de verite metier — ces Pydantic models sont purement des contrats I/O API.
"""

from __future__ import annotations

# Re-exports publics (utilises par run_facade + scripts/generate_api_schema.py).
from cinesort.ui.api.schemas.apply import (
    ApplyRequest,
    ApplyResponse,
)
from cinesort.ui.api.schemas.duplicates import (
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
    DuplicateGroup,
    DuplicateGroupCollision,
    DuplicateGroupSimilarity,
)
from cinesort.ui.api.schemas.run import (
    PlanSettings,
    StartPlanRequest,
    StartPlanResponse,
)

__all__ = [
    "PlanSettings",
    "StartPlanRequest",
    "StartPlanResponse",
    "CheckDuplicatesRequest",
    "CheckDuplicatesResponse",
    "DuplicateGroup",
    "DuplicateGroupCollision",
    "DuplicateGroupSimilarity",
    "ApplyRequest",
    "ApplyResponse",
]
