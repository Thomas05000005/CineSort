"""Schemas Pydantic pour `RunFacade.check_duplicates` (V2.1).

Modele POLYMORPHIQUE des groupes de doublons via Pydantic discriminated
unions (`Field(discriminator="kind")`). Deux kinds reels dans le code
metier :

- `collision`  : destinations identiques apres rename (chemin cible commun)
- `similarity` : films distincts proches par signature perceptuelle

BACKWARD COMPAT : `extra="allow"` partout — un caller peut envoyer plus de
cles, on les conserve.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _DuplicateGroupBase(BaseModel):
    """Base commune aux deux kinds de groupes de doublons."""

    model_config = ConfigDict(extra="allow")

    group_key: str = Field(..., min_length=1, description="Cle stable du groupe.")
    row_ids: List[str] = Field(
        default_factory=list,
        description="Identifiants des rows membres du groupe (>=2 attendus).",
    )


class DuplicateGroupCollision(_DuplicateGroupBase):
    """Groupe de doublons par collision de destination (rename identique)."""

    kind: Literal["collision"] = "collision"
    dest_path: str = Field(
        ...,
        min_length=1,
        description="Chemin de destination commun cause de la collision.",
    )


class DuplicateGroupSimilarity(_DuplicateGroupBase):
    """Groupe de doublons par similarite perceptuelle / fingerprint."""

    kind: Literal["similarity"] = "similarity"
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de similarite dans [0.0, 1.0] (1.0 = identique).",
    )
    signal: str = Field(
        default="perceptual",
        description="Signal qui a declenche la detection (perceptual / audio_fp / vision...).",
    )


# Union discriminee : Pydantic v2 utilise `Annotated[..., Field(discriminator=...)]`
# pour un dispatch O(1) sur la cle `kind`.
DuplicateGroup = Annotated[
    Union[DuplicateGroupCollision, DuplicateGroupSimilarity],
    Field(discriminator="kind"),
]


class CheckDuplicatesRequest(BaseModel):
    """Entree de `RunFacade.check_duplicates(run_id, decisions)`.

    Alignee sur la signature reelle (run_id + decisions dict). Le body REST
    REEL est `{"run_id":"...","decisions":{}}` — `decisions` est un dict
    (PAS une list), typé `dict[str, Any]` pour absorber la grande variete
    de cles legacy (ok, decision, dest_override, ...).
    """

    model_config = ConfigDict(extra="allow")

    run_id: str = Field(..., min_length=1, description="Identifiant du run cible.")
    decisions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dict {row_id: {decision, ok, dest_override, ...}} ou {} au 1er appel.",
    )


class CheckDuplicatesResponse(BaseModel):
    """Sortie de `RunFacade.check_duplicates`.

    `groups` est la liste polymorphique discriminee par `kind`. Les autres
    champs (compteurs, warnings) suivent la shape historique.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True)
    run_id: str = Field(..., min_length=1)
    groups: List[DuplicateGroup] = Field(
        default_factory=list,
        description="Groupes de doublons detectes (collision ou similarity).",
    )
    total_groups: int = Field(default=0, ge=0)
    total_rows_in_groups: int = Field(default=0, ge=0)
    warnings: List[str] = Field(default_factory=list)
    diagnostics: Optional[Dict[str, Any]] = Field(default=None)
