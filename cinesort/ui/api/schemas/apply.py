"""Schemas Pydantic pour `RunFacade.apply` (V2.1).

Signature reelle :
    apply(run_id, decisions, dry_run, quarantine_unapproved, apply_atomic=False)

On modelise `ApplyRequest` aligne exactement sur cette signature (cf
memoire : `endpoints REELS run_facade.py: start_plan/check_duplicates/apply
complet — NE PAS inventer noms`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApplyRequest(BaseModel):
    """Entree de `RunFacade.apply(run_id, decisions, dry_run, quarantine_unapproved)`."""

    model_config = ConfigDict(extra="allow")

    run_id: str = Field(..., min_length=1, description="Identifiant du run a appliquer.")
    decisions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dict {row_id: {decision, ok, dest_override, locks, ...}} ou {} si aucun override.",
    )
    dry_run: bool = Field(
        default=True,
        description="True = simulation (aucun deplacement filesystem reel).",
    )
    quarantine_unapproved: bool = Field(
        default=False,
        description="True = deplacer les rows non-approuvees dans `_review/_unapproved/`.",
    )
    apply_atomic: bool = Field(
        default=False,
        description="Vague P / VP-A : True declenche un rollback FS+DB forward sur exception.",
    )


class ApplyOperationError(BaseModel):
    """Erreur d'une operation d'apply individuelle (entry dans `errors[]`)."""

    model_config = ConfigDict(extra="allow")

    row_id: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1, description="Code d'erreur stable (cf BUG-* / quality codes).")
    message: str = Field(default="", description="Message lisible (peut etre i18n-resolu cote front).")


class ApplyResponse(BaseModel):
    """Sortie de `RunFacade.apply`.

    Champs structurants : `applied`, `errors`, `undo_token`. La shape reelle
    contient bien d'autres cles (`batch_id`, `apply_atomic_rolled_back`,
    `dry_run`, `quarantine_destinations`, ...) — toutes acceptees via
    `extra="allow"` pour preserver la backward compat.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True, description="True si le batch a abouti (ou rollback complet).")
    applied: int = Field(
        default=0,
        ge=0,
        description="Nombre d'operations effectivement appliquees (ou simulees en dry-run).",
    )
    errors: List[ApplyOperationError] = Field(
        default_factory=list,
        description="Liste des erreurs par row (vide si tout est OK).",
    )
    undo_token: Optional[str] = Field(
        default=None,
        description="Token opaque consommable par `undo_last_apply` (None si dry_run ou rollback complet).",
    )
    batch_id: Optional[str] = Field(
        default=None,
        description="Identifiant du batch apply (pour traversal apply_operations).",
    )
    dry_run: bool = Field(
        default=False,
        description="Echo de l'argument d'entree pour rappel cote UI.",
    )
