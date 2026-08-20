"""Schemas Pydantic pour `RunFacade.apply` (V2.1).

Signature reelle :
    apply(run_id, decisions, dry_run, quarantine_unapproved, apply_atomic=False)

`ApplyRequest` est aligne exactement sur cette signature — et il l'etait deja :
`run_facade.apply` construit lui-meme le dict valide, cle par cle.

CE QUI A CHANGE : `ApplyResponse` NE VALIDAIT RIEN
--------------------------------------------------
L'ancien modele declarait `applied`, `errors` (liste d'objets), `undo_token`,
`batch_id` et `dry_run`. **Aucune de ces cinq cles n'existe dans le payload
d'apply.** Le vrai payload de succes est :

    {ok, result, apply_batch_id, journal_finalized, undo_available}
    (+ `journal_warning` et `verdict`, poses seulement en cas d'anomalie)

Tous les compteurs, dont `errors` — un **entier**, pas une liste — vivent sous
`result` (c'est `ApplyResult.__dict__`).

Comme les cinq champs etaient tous optionnels, la validation PASSAIT toujours,
en prenant cinq defauts inventes. C'est le symetrique exact du defaut de
`duplicates.py` / `run.py` : la, un champ requis absent faisait echouer 100 %
des appels ; ici, des champs absents faisaient reussir 100 % des appels **sans
rien verifier**. Sur l'endpoint DESTRUCTIF du depot, un filet qui ne peut rien
attraper est pire qu'aucun filet : il se lit comme une garantie.

Le garde qui empeche la fiction de revenir est
`tests/test_contract_schemas_payload_reel.py` : il DERIVE la liste des champs
du payload reellement produit, il ne la recopie pas.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

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
    """Forme HISTORIQUE d'une erreur d'operation, jamais produite par ce depot.

    Conservee parce qu'elle est re-exportee ; elle n'entre plus dans
    `ApplyResponse`. Le payload reel ne porte aucune liste d'erreurs : il porte
    un COMPTEUR `result.errors` (int) et des messages sous
    `result.error_messages`.
    """

    model_config = ConfigDict(extra="allow")

    row_id: str = Field(default="")
    code: str = Field(default="", description="Code d'erreur stable (cf BUG-* / quality codes).")
    message: str = Field(default="", description="Message lisible (peut etre i18n-resolu cote front).")


class ApplyResponse(BaseModel):
    """Sortie de `RunFacade.apply`.

    Champs structurants, tous releves dans `apply_support` :

    - `result` : `ApplyResult.__dict__` aplati. C'est la que vivent `renames`,
      `moves`, `quarantined`, `skipped` et `errors` (**int**).
    - `apply_batch_id` : identifiant du batch, `None` en dry-run ou si
      `insert_apply_batch` a echoue.
    - `journal_finalized` : `close_apply_batch(DONE)` a REELLEMENT abouti.
    - `undo_available` : l'annulation est armee (batch clos + au moins une
      operation journalisee).
    - `journal_warning` / `verdict` : poses UNIQUEMENT en cas d'anomalie, donc
      absents du payload nominal.

    Le chemin d'ECHEC rend `{ok: False, message, ...}` enrichi de
    `atomic_rollback` et `apply_batch_id` : il est couvert par `extra="allow"`
    et par les champs optionnels ci-dessous, sans qu'aucun ne soit requis.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True, description="True si le batch a abouti (ou rollback complet).")
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="`ApplyResult.__dict__` : compteurs (dont `errors`, un ENTIER) et diagnostics.",
    )
    apply_batch_id: Optional[str] = Field(
        default=None,
        description="Identifiant du batch apply. None en dry-run ou si le journal n'a pas pu s'ouvrir.",
    )
    journal_finalized: Optional[bool] = Field(
        default=None,
        description="False = batch reste PENDING, donc undo perdu pour cet apply.",
    )
    undo_available: Optional[bool] = Field(
        default=None,
        description="True si l'annulation de ce batch est reellement armee.",
    )
    journal_warning: Optional[str] = Field(
        default=None,
        description="Alerte 'undo indisponible' ; ABSENT quand tout va bien.",
    )
    verdict: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Verdict annonce/journal (`app/verdicts.py`) ; ABSENT quand tout concorde.",
    )
    atomic_rollback: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Synthese du rollback atomique, posee seulement sur le chemin d'echec.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Message utilisateur du chemin d'echec (`_responses.err`).",
    )
