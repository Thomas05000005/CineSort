"""Resolution des ROLES doublons — source unique, partagee UI et apply.

Ce module est une FEUILLE : il n'importe rien de `cinesort`, donc
`apply_support` et `run_flow_support` peuvent tous deux le prendre en import de
TETE malgre le cycle qui existe entre eux (`apply_support` importe
`run_flow_support` en differe, cf apply_support.py).

POURQUOI IL EXISTE
------------------
La table `duplicate_decisions` est upsert-only sur `(run_id, group_key)` et sa
cle DERIVE de `titre|annee`. Des que l'utilisateur corrige l'annee ou le titre
en Validation, la cle change et la decision precedente SURVIT — aucun DELETE
nulle part. Plusieurs decisions historiques peuvent donc se CHEVAUCHER sur un
meme row.

L'apply resout ces conflits GLOBALEMENT, par recence : un row declare gagnant
par une decision recente ne peut plus etre declare perdant par une plus
ancienne. L'affichage des doublons, lui, rattachait une decision par ENSEMBLE
EXACT de row_ids — un critere LOCAL.

Les deux divergeaient. Scenario mesure :

    decision ancienne sur {r1, r2} : gagnant r1, perdant r2
    decision recente  sur {r1, r3} : gagnant r3, perdant r1
    groupe affiche = {r1, r2}

L'affichage rattachait l'ANCIENNE decision et annoncait « r1 garde ». L'apply,
lui, resolvait r1 en PERDANT et le deplacait. L'utilisateur voyait une chose,
le disque en subissait une autre.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set


def resolve_duplicate_roles(
    decisions: Any,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, str]:
    """Role EFFECTIF de chaque row : "winner" ou "loser".

    Regle : la decision la PLUS RECENTE gagne. Le role est attribue une seule
    fois, en parcourant du plus recent au plus ancien.

    Une decision dont `loser_row_ids` est VIDE n'arbitre rien et est
    entierement ignoree : sans ce garde, elle confererait une immunite a son
    « gagnant » et ANNULERAIT une decision anterieure legitime qui, elle,
    designait ce row comme perdant. Cas reel : `mark_duplicate_winner` persiste
    `loser_row_ids=[]` avec un `decided_ts` FRAIS des que le groupe recharge
    n'a plus qu'UNE row.

    NB `decided_ts` ex-aequo (deux upserts dans le meme tick) : le tri Python
    est stable, donc l'ordre de lecture du repo (ORDER BY decided_ts DESC)
    tranche. Cas theorique, non deterministe, assume.
    """
    usable: List[Dict[str, Any]] = [dec for dec in (decisions or []) if isinstance(dec, dict)]
    try:
        ordered = sorted(usable, key=lambda d: float(d.get("decided_ts") or 0.0), reverse=True)
    except (TypeError, ValueError):
        # decided_ts illisible : on garde l'ordre du repo (deja DESC).
        ordered = usable

    role_by_row: Dict[str, str] = {}
    for dec in ordered:
        winner_id = str(dec.get("winner_row_id") or "").strip()
        losers_of_dec = [str(lid or "").strip() for lid in (dec.get("loser_row_ids") or [])]
        losers_of_dec = [lid for lid in losers_of_dec if lid and lid != winner_id]
        if not losers_of_dec:
            continue
        if winner_id:
            role_by_row.setdefault(winner_id, "winner")
        for loser_id in losers_of_dec:
            if role_by_row.setdefault(loser_id, "loser") == "winner" and log_fn is not None:
                log_fn(
                    "WARN",
                    f"Doublons : row {loser_id} est perdant d'une decision perimee "
                    "mais gagnant d'une decision plus recente -> conserve (non deplace).",
                )
    return role_by_row


def resolve_duplicate_loser_row_ids(
    decisions: Any,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Set[str]:
    """Les rows que l'apply deplacera effectivement."""
    return {row_id for row_id, role in resolve_duplicate_roles(decisions, log_fn).items() if role == "loser"}


def decision_matches_effective_roles(decision: Any, roles: Dict[str, str]) -> bool:
    """La decision decrit-elle encore ce que l'apply FERA ?

    Repond False des qu'un role a ete redistribue par une decision plus
    recente : gagnant devenu perdant, ou perdant devenu gagnant. Annoncer
    « decide » dans ce cas ferait promettre a l'UI l'inverse de ce que l'apply
    execute — sur un chemin qui DEPLACE des dossiers.
    """
    if not isinstance(decision, dict):
        return False
    winner = str(decision.get("winner_row_id") or "").strip()
    losers = [str(lid or "").strip() for lid in (decision.get("loser_row_ids") or [])]
    losers = [lid for lid in losers if lid and lid != winner]
    if not losers:
        # Sans perdant, la decision n'arbitre rien — meme regle qu'a l'apply.
        return False
    if winner and roles.get(winner) == "loser":
        return False
    return all(roles.get(lid) == "loser" for lid in losers)
