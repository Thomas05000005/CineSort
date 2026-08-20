"""Schemas Pydantic pour `RunFacade.check_duplicates` (V2.1).

LA FORME EST RELEVEE DANS LE CODE QUI L'ECRIT
---------------------------------------------
Ce module modelisait une union discriminee sur une cle `kind` valant
`collision` ou `similarity`, avec `group_key`, `row_ids`, `dest_path` et
`similarity_score`. **Aucune de ces cles n'existe.** Le producteur unique du
payload est `domain/duplicate_support.find_duplicate_targets`, et il rend :

    {checked_rows, total_groups, groups, mergeable_count, mergeables}

ou chaque groupe vaut `{title, year, rows, existing_paths, plan_conflict,
scope}` — enrichi ensuite par `run_flow_support` de `comparison`,
`winner_decided`, `winner_row_id`, `winner_side`, et le tout complete de
`size_savings_total`. `check_duplicates` renvoie `{"ok": True, **data}` :
il n'y a **jamais** de `run_id` dans la reponse.

`CheckDuplicatesResponse` exigeait pourtant `run_id` : la validation passive
echouait donc a **100 %**, et son `logger.error` partait a chaque ouverture de
l'ecran Doublons. Un controle qui rougit toujours ne signale plus rien — et
sous `CINESORT_PYDANTIC_STRICT=1` il levait `ValueError`, rendant l'endpoint
inutilisable.

BACKWARD COMPAT : `extra="allow"` partout — les enrichissements successifs
(`comparison`, `winner_*`) traversent intacts, et un caller peut envoyer plus
de cles sans casser.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DuplicateGroupRow(BaseModel):
    """Un membre d'un groupe de doublons.

    Forme relevee sur `find_duplicate_targets` (le dict empile dans
    `planned_idx`). `year` y est une CHAINE — c'est `str(year)` a l'ecriture,
    alors que le `year` du groupe est un `int` : l'asymetrie est reelle et
    modelisee telle quelle plutot que lissee.
    """

    model_config = ConfigDict(extra="allow")

    row_id: str = Field(default="", description="Identifiant de la ligne du plan.")
    kind: str = Field(default="", description="`single` | `collection` (les `tv_episode` sont exclus en amont).")
    title: str = Field(default="", description="Titre passe par `windows_safe`.")
    year: str = Field(default="", description="Annee SERIALISEE EN CHAINE (cf docstring).")
    target: str = Field(default="", description="Destination planifiee, miroir de `apply_single`.")
    source_folder: str = Field(default="", description="Dossier source actuel.")
    source_root: str = Field(default="", description="Racine d'origine (multi-root), '' si inconnue.")
    warning_flags: List[str] = Field(
        default_factory=list,
        description="Flags RECONCILIES (cf `_reconciled_row_flags`), jamais bruts.",
    )


class DuplicateGroup(BaseModel):
    """Un groupe de doublons tel que `find_duplicate_targets` l'empile.

    Le nom est conserve (il est re-exporte par `schemas/__init__`), mais ce
    n'est plus une union discriminee : le producteur ne pose aucune cle `kind`
    au niveau du GROUPE — seuls ses `rows` en portent une, et elle vaut
    `single`/`collection`, jamais `collision`/`similarity`.
    """

    model_config = ConfigDict(extra="allow")

    title: str = Field(default="", description="Titre commun aux membres du groupe.")
    year: int = Field(default=0, description="Annee commune (0 = annee invalide, cf `year_invalid`).")
    rows: List[DuplicateGroupRow] = Field(
        default_factory=list,
        description="Membres du groupe (>= 2, sauf groupe ne portant qu'un `existing_paths`).",
    )
    existing_paths: List[str] = Field(
        default_factory=list,
        description="Dossiers deja presents sur disque pour cette identite (cape a 8 par le producteur).",
    )
    plan_conflict: bool = Field(
        default=False,
        description="Deux membres visent la MEME destination normalisee.",
    )
    scope: str = Field(default="", description="`cross_root` | `same_root` | `same_folder`.")


class DuplicateGroupCollision(BaseModel):
    """Forme HISTORIQUE, jamais produite par ce depot.

    Conservee uniquement parce qu'elle est re-exportee par
    `cinesort/ui/api/schemas/__init__.py`; elle n'entre plus dans
    `CheckDuplicatesResponse`. A retirer avec son export le jour ou l'on
    tranchera la compatibilite de ce paquet.
    """

    model_config = ConfigDict(extra="allow")

    kind: Literal["collision"] = "collision"
    group_key: str = Field(default="", description="Cle stable du groupe (forme historique).")
    row_ids: List[str] = Field(default_factory=list)
    dest_path: str = Field(default="", description="Chemin de destination commun (forme historique).")


class DuplicateGroupSimilarity(BaseModel):
    """Forme HISTORIQUE, jamais produite par ce depot (cf `DuplicateGroupCollision`)."""

    model_config = ConfigDict(extra="allow")

    kind: Literal["similarity"] = "similarity"
    group_key: str = Field(default="", description="Cle stable du groupe (forme historique).")
    row_ids: List[str] = Field(default_factory=list)
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    signal: str = Field(default="perceptual")


class CheckDuplicatesRequest(BaseModel):
    """Entree de `RunFacade.check_duplicates(run_id, decisions)`.

    Alignee sur la signature reelle (run_id + decisions dict). Le body REST
    REEL est `{"run_id":"...","decisions":{}}` — `decisions` est un dict
    (PAS une list), type `dict[str, Any]` pour absorber la grande variete
    de cles legacy (ok, decision, dest_override, ...).
    """

    model_config = ConfigDict(extra="allow")

    run_id: str = Field(..., min_length=1, description="Identifiant du run cible.")
    decisions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dict {row_id: {decision, ok, dest_override, ...}} ou {} au 1er appel.",
    )


class CheckDuplicatesResponse(BaseModel):
    """Sortie de `RunFacade.check_duplicates` : `{"ok": True, **data}`.

    AUCUN CHAMP REQUIS. Toutes les cles declarees ici sont celles que le
    producteur pose reellement ; `run_id` n'en fait PAS partie et ne doit pas
    y revenir (cf `tests/test_contract_schemas_payload_reel.py`, qui derive la
    liste des champs du payload PRODUIT et non d'une recopie).
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True)
    checked_rows: int = Field(default=0, ge=0, description="Lignes examinees (approuvees, hors tv_episode).")
    total_groups: int = Field(default=0, ge=0, description="Groupes EMIS (borne par `max_groups`, defaut 120).")
    groups: List[DuplicateGroup] = Field(default_factory=list)
    mergeable_count: int = Field(default=0, ge=0, description="Total des fusions possibles, AVANT la coupe a 200.")
    mergeables: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Fusions possibles, liste capee a 200 par le producteur.",
    )
    size_savings_total: Optional[int] = Field(
        default=None,
        description="Octets recuperables agreges. Absent quand le payload vient directement du domaine.",
    )
