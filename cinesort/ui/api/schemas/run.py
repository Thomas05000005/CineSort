"""Schemas Pydantic pour `run_facade.start_plan` (V2.1).

Aligne sur l'endpoint REEL `RunFacade.start_plan(settings)` qui delegue
vers `CineSortApi._start_plan_impl`. Aucune invention de noms (memoire
utilisateur : `start_plan` est le bon nom).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PlanSettings(BaseModel):
    """Settings dict transmis a `RunFacade.start_plan(settings)`.

    Le body REST REEL est `{"settings": {"library_path": "...", ...}}` — ce
    wrapper modelise le contenu de la cle `settings`. `library_path` est
    obligatoire ; toutes les autres options legacy (~50 cles) passent par
    `options` ou directement en extra (`extra="allow"`).
    """

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=False,
        populate_by_name=True,
    )

    library_path: str = Field(
        ...,
        min_length=1,
        description="Chemin de la bibliotheque a scanner (Windows path accepte).",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Options additionnelles (compatibilite legacy : tout settings dict est tolere).",
    )


class StartPlanRequest(BaseModel):
    """Entree REST de `RunFacade.start_plan` : body `{"settings": {...}}`.

    Aligne sur le body REEL observe en prod (memoire utilisateur). La cle
    `settings` enveloppe un `PlanSettings` (qui contient `library_path` +
    options legacy). `extra="allow"` au niveau top pour tolerer des cles
    additionnelles cote caller sans casser.
    """

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=False,
        populate_by_name=True,
    )

    settings: PlanSettings = Field(
        ...,
        description="Wrapper REST autour du dict settings passe a start_plan.",
    )


class StartPlanResponse(BaseModel):
    """Sortie de `RunFacade.start_plan`.

    Le legacy retourne historiquement `{ok, run_id, ...}`. On modelise les
    champs structurants (`run_id`, `plan_summary`) sans rejeter le reste
    (extra="allow") pour rester backward-compat.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True, description="True si le scan/plan a demarre correctement.")
    run_id: str = Field(..., min_length=1, description="Identifiant du run cree.")
    plan_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Resume du plan (totaux, KPIs, scores tier). Optionnel : peut etre None"
        " si le plan n'a pas encore demarre (mode async).",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Avertissements non-bloquants (path invalide partiel, FS lent...).",
    )
