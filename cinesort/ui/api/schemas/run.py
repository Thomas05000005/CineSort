"""Schemas Pydantic pour `run_facade.start_plan` (V2.1).

Aligne sur l'endpoint REEL `RunFacade.start_plan(settings)` qui delegue
vers `CineSortApi._start_plan_impl`.

LES NOMS DE CLES SE RELEVENT, ILS NE S'INVENTENT PAS
----------------------------------------------------
Ce module a longtemps exige une cle `library_path` que la production ne
produit NULLE PART. La racine de bibliotheque vit sous `root` (str) et
`roots` (list[str]) — c'est `settings_support._migrate_root_to_roots` qui
les pose, et les trois appelants front (`accueil.js`, `traitement.js`,
`processing.js`) postent l'instantane rendu par `settings/get_settings`.

Consequence mesuree : `start_plan.request` echouait a **100 %**, et son
`logger.error("[pydantic-passive] ... validation failed")` partait a CHAQUE
lancement de scan. Un controle qui rougit toujours ne signale plus rien —
et sous `CINESORT_PYDANTIC_STRICT=1` il levait `ValueError`, rendant
l'endpoint inutilisable.

Le seul test qui traversait cette entree ne pouvait pas le voir : il ajoutait
`library_path` A COTE du vrai `root`, avec le commentaire « cle documentee
dans PlanSettings ». Le harnais satisfaisait le schema ; la production, non.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PlanSettings(BaseModel):
    """Contenu de la cle `settings` transmise a `RunFacade.start_plan(settings)`.

    Le body REST REEL est `{"settings": {"root": "...", "roots": [...], ...}}`.
    Aucune cle n'est OBLIGATOIRE : le body peut legitimement etre minimal, car
    `run_flow_support._hydrate_settings_from_store` fusionne ensuite le
    `settings.json` on-disk (c'est la raison d'etre de cette fonction). Exiger
    ici une cle que l'hydratation fournit plus tard recreerait l'echec a 100 %
    que ce modele vient de corriger.

    Ce qui reste verifie : la FORME (dict) et le TYPE des cles declarees. Une
    `roots` qui cesserait d'etre une liste de chaines, ou un `root` non textuel,
    sont de vraies derives et doivent rester visibles dans le log passif.
    """

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=False,
        populate_by_name=True,
    )

    root: Optional[str] = Field(
        default=None,
        description="Racine de bibliotheque (cle REELLE, posee par _migrate_root_to_roots).",
    )
    roots: Optional[List[str]] = Field(
        default=None,
        description="Racines multiples (cle REELLE). `root` en est le premier element.",
    )
    library_path: Optional[str] = Field(
        default=None,
        description=(
            "Alias historique. Aucun ecrivain du depot ne le produit ; conserve "
            "en tolerance pour un caller externe, jamais exige."
        ),
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Options additionnelles (compatibilite legacy : tout settings dict est tolere).",
    )


class StartPlanRequest(BaseModel):
    """Entree REST de `RunFacade.start_plan` : body `{"settings": {...}}`.

    La cle `settings` enveloppe un `PlanSettings`. `extra="allow"` au niveau
    top pour tolerer des cles additionnelles cote caller sans casser.
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

    Le chemin nominal rend `{ok: True, run_id, run_dir}`
    (`run_flow_support.py`). `run_id` reste donc REQUIS : contrairement aux
    deux autres reponses de ce paquet, celui-la est bien present dans le
    payload reel, et l'exiger attrape une regression utile.

    Reserve : la frontiere d'erreur de `start_plan` rend
    `{ok: False, error, message, user_message}` sans `run_id` — la validation
    passive y echoue donc, par construction. C'est un chemin d'ECHEC deja
    signale par ailleurs, pas le chemin nominal.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(default=True, description="True si le scan/plan a demarre correctement.")
    run_id: str = Field(..., min_length=1, description="Identifiant du run cree.")
    run_dir: Optional[str] = Field(
        default=None,
        description="Dossier du run (`runs/tri_films_<run_id>`), cle REELLE du payload nominal.",
    )
    plan_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Resume du plan (totaux, KPIs, scores tier). Optionnel : peut etre None"
        " si le plan n'a pas encore demarre (mode async).",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Avertissements non-bloquants (path invalide partiel, FS lent...).",
    )
