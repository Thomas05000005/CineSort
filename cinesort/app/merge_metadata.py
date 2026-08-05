"""Vague P / VP-C : merge_metadata barriere anti-ecrasement (Jellyfin MergeData).

Calque le pattern Jellyfin `MergeData` : tout enrichissement provenant
d'une source externe (OMDb, TMDb, rescan probe, NFO refresh) passe par
cette barriere AVANT d'ecraser le `target`. La barriere consulte les
`locked_fields` et :
    - garde la valeur de target intacte si le champ est verrouille,
    - sinon ecrase target avec la valeur source (mode "fill missing"
      ou "replace" selon `replace_data`).

Cette fonction est volontairement pure (zero IO) : elle prend des dicts
en entree et retourne un dict. Les callers (library_actions_support,
rescan pipeline) sont responsables :
    1. de lire `locked_fields` via `store.field_locks.list_locks(film_id)`,
    2. d'appeler `merge_metadata(...)`,
    3. d'ecrire le resultat dans plan.jsonl / validation.json / DB.

Coexistence `film_tmdb_overrides` : la table de la migration 023 vit
toujours en parallele. `film_tmdb_overrides` gere le choix d'un *match*
TMDb manuel, `film_field_locks` gere les verrous *champ-par-champ*. Les
deux n'entrent pas en conflit (zero regression backward compat).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Mapping, Optional, Set

logger = logging.getLogger(__name__)


def merge_metadata(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    locked_fields: Optional[Iterable[str]] = None,
    *,
    replace_data: bool = False,
) -> Dict[str, Any]:
    """Fusionne `source` dans `target` en respectant les `locked_fields`.

    Args:
        source: dict avec les valeurs provenant d'un enrichissement externe
            (OMDb, TMDb, probe, NFO...).
        target: dict avec les valeurs actuelles (a preserver si lock).
        locked_fields: noms de champs verrouilles (iterable de str). Tout
            field dans cette liste est conserve depuis `target`, jamais
            ecrase. Insensible a la casse.
        replace_data: si False (defaut "completer les manques uniquement"),
            ne remplace que les champs vides/None de `target`. Si True
            (mode "Tout reconstruire"), ecrase `target` avec `source` sauf
            sur les locked_fields.
            #638 : "vide" == `None`, chaine blanche, ou collection vide. Un
            `0`, un `0.0` ou un `False` sont des valeurs PRESENTES et ne sont
            donc JAMAIS ecrases dans ce mode (cf. `_is_empty`).

    Returns:
        Nouveau dict (ne mute jamais ni `source` ni `target`).

    Semantique :
        - replace_data=False (defaut) : merge cooperatif. Pour chaque cle
          de `source`, si la cle est vide/manquante dans `target` ET pas
          verrouillee, on copie depuis source. Sinon on garde target.
        - replace_data=True : merge ecrasant ("Tout reconstruire"). On
          ecrase target avec source pour toutes les cles non-verrouillees.
          Les cles verrouillees gardent leur valeur target intacte.
    """
    locked = _normalize_locked_fields(locked_fields)
    result: Dict[str, Any] = dict(target or {})

    if not source:
        return result

    for field, src_value in source.items():
        if not isinstance(field, str):
            continue
        # Comparaison case-insensitive sur le nom de champ (Jellyfin-style).
        if field.lower() in locked:
            # Champ verrouille : on ne touche jamais a target.
            continue

        if replace_data:
            # Mode "Tout reconstruire" : on ecrase tout sauf locks.
            result[field] = src_value
            continue

        # Mode "Completer les manques uniquement" (defaut).
        if _is_empty(result.get(field)):
            result[field] = src_value

    return result


def _normalize_locked_fields(locked_fields: Optional[Iterable[str]]) -> Set[str]:
    """Normalise une iterable de noms de champ en set lowercase."""
    if not locked_fields:
        return set()
    out: Set[str] = set()
    for name in locked_fields:
        if isinstance(name, str) and name.strip():
            out.add(name.strip().lower())
    return out


def _is_empty(value: Any) -> bool:
    """Retourne True si value est consideree "manquante" (a remplir).

    #638 : la branche `isinstance(value, (int, float)) and value == 0` a ete
    RETIREE. Elle contredisait la docstring du module ("ne remplace que les
    champs vides/None de target") et confondait deux choses :

    * `0` / `0.0` sont des valeurs PRESENTES (`community_rating=0.0`, un
      compteur a zero, un seuil volontairement nul). En mode "completer les
      manques", les ecraser depuis une source externe est une perte de donnee ;
    * `bool` etant une sous-classe de `int`, `False == 0` : un flag
      explicitement desactive (`has_subtitles=False`) etait lui aussi traite
      comme manquant, donc ecrasable.

    Un appelant dont la convention est "0 signifie absent" (c'est le cas de
    `proposed_year` cote plan, ou 0 encode "annee inconnue") doit normaliser
    ce champ en `None` AVANT d'appeler `merge_metadata` : la barriere ne peut
    pas deviner, champ par champ, si un zero est un sentinel ou une mesure.
    """
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True
    return False


__all__ = ["merge_metadata"]
