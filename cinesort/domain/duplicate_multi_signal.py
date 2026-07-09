"""Detection multi-signal des doublons (VN-D.1).

Phase A: strict-metadata (existant, equivalent a `movie_key`).
Phase B: fuzzy titre via rapidfuzz token_sort_ratio >= 88 + year tolerance +-1.
Phase C: comparaison Chromaprint via `compare_audio_fingerprints` (>= 0.85).

Architecture: ce module est pur (pas d'I/O, pas de DB). Il prend en entree des
`MultiSignalCandidate` (titre + annee + edition + fingerprint optionnel) et
retourne des groupes (chaque groupe est une liste d'identifiants opaques).

Le pipeline est configurable via `phases=[...]` afin d'autoriser un rollback
par feature flag si un bug est detecte (cf user memory "Pas de modification
titres films au-dela renommage configure" - on ne touche jamais aux titres,
on les utilise seulement pour le matching).

Performance: pour Phase B, on indexe les candidats restants par (premiere
lettre normalisee, annee) afin d'eviter la comparaison NxN. Pour Phase C,
on filtre par annee +-2 (seuil deliberement plus large que Phase B) avant
de calculer la distance Hamming, qui reste O(longueur_fingerprint).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from cinesort.domain._fuzzy_normalize import normalize_for_fuzzy as _normalize_for_fuzzy
from cinesort.domain.title_helpers import strip_trailing_year_if_equal

logger = logging.getLogger(__name__)

# Seuils Phase B (fuzzy title)
FUZZY_TITLE_MIN_SCORE = 88  # rapidfuzz token_sort_ratio (0-100)
FUZZY_YEAR_TOLERANCE = 1  # +-1 an

# Seuil Phase C (audio fingerprint)
FINGERPRINT_MIN_SIMILARITY = 0.85  # compare_audio_fingerprints (0.0-1.0)
FINGERPRINT_YEAR_PRE_FILTER = 2  # +-2 ans pour pre-filtrer avant compare

# Phases supportees
PHASE_STRICT_METADATA = "strict_metadata"
PHASE_FUZZY_TITLE = "fuzzy_title"
PHASE_AUDIO_FINGERPRINT = "audio_fingerprint"

DEFAULT_PHASES: Tuple[str, ...] = (
    PHASE_STRICT_METADATA,
    PHASE_FUZZY_TITLE,
    PHASE_AUDIO_FINGERPRINT,
)


@dataclass(frozen=True)
class MultiSignalCandidate:
    """Candidat pour le grouping multi-signal.

    Attributs:
        item_id: identifiant opaque (ex: row_id ou path).
        title: titre normalise pour affichage (non transforme).
        year: annee (int >= 1900 ou 0 si inconnu).
        edition: edition (Director's Cut, Extended, IMAX, etc.) ou None.
        audio_fingerprint: chaine base64 Chromaprint (cf compute_audio_fingerprint) ou None.
    """

    item_id: str
    title: str
    year: int
    edition: Optional[str] = None
    audio_fingerprint: Optional[str] = None


@dataclass
class MultiSignalGroup:
    """Groupe de doublons detectes.

    Attributs:
        members: identifiants opaques des items du groupe.
        phase: phase qui a cree/elargi le groupe (strict_metadata, fuzzy_title, audio_fingerprint).
        representative_title: titre du premier item du groupe (pour log/debug).
        representative_year: annee du premier item (pour log/debug).
    """

    members: List[str] = field(default_factory=list)
    phase: str = PHASE_STRICT_METADATA
    representative_title: str = ""
    representative_year: int = 0


@dataclass
class MultiSignalResult:
    """Resultat du grouping multi-signal.

    Attributs:
        groups: groupes de >=2 items (les singletons sont exclus).
        phases_used: liste effectivement appliquee.
        phase_counts: nombre de groupes crees ou augmentes par phase (debug).
    """

    groups: List[MultiSignalGroup] = field(default_factory=list)
    phases_used: List[str] = field(default_factory=list)
    phase_counts: Dict[str, int] = field(default_factory=dict)


def _normalize_title_for_fuzzy(title: str) -> str:
    """Normalisation legere pour fuzzy (delegue au module domain dedie).

    Refactor iter4b 2026-06-09: l'ancien import lazy `from cinesort.app
    ._fuzzy_utils import normalize_for_fuzzy` violait `domain_pure`
    (domain -> app). La fonction est maintenant rangee dans
    `cinesort.domain._fuzzy_normalize` (pure string, sans dependance) et
    importee top-level.
    """
    return _normalize_for_fuzzy(title)


def _index_token(norm_title: str) -> str:
    """Renvoie un token d'indexation stable invariant a l'ordre des mots.

    On utilise le PREMIER token apres tri alphabetique des tokens du titre
    normalise. Cela garantit que "lord of the rings" et "rings of the lord the"
    aient la meme cle d'index (apres tri: ['lord','of','rings','the'] -> 'lord').

    Justification: `rapidfuzz.fuzz.token_sort_ratio` trie les tokens avant
    de comparer ; il faut donc indexer sur une cle stable au meme tri.
    Sinon, un candidat avec ordre des mots different serait place dans un
    bucket different et jamais compare.
    """
    if not norm_title:
        return ""
    tokens = sorted(t for t in norm_title.split() if t)
    if not tokens:
        return ""
    # Premier token apres tri (ex: 'lord' pour les exemples Lord of the Rings)
    return tokens[0]


def _strict_key(candidate: MultiSignalCandidate, *, norm_for_tokens) -> str:
    """Cle Phase A: identique a `duplicate_support.movie_key`."""
    # R2 (revue round 2) : realigne sur movie_key qui strippe desormais l'annee
    # de queue == annee du couple ("Titre 2005"|2005 == "Titre"|2005). Sans ce
    # strip, la Phase A multi-signal et movie_key divergeaient (invariant
    # docstring "identique a movie_key" casse).
    year = int(candidate.year or 0)
    key_title = strip_trailing_year_if_equal(candidate.title, year)
    base = f"{norm_for_tokens(key_title)}|{year}"
    edition = (candidate.edition or "").strip().lower()
    if edition:
        return f"{base}|{edition}"
    return base


def _phase_a_strict_metadata(
    candidates: Sequence[MultiSignalCandidate],
    *,
    norm_for_tokens,
) -> Tuple[List[MultiSignalGroup], List[MultiSignalCandidate]]:
    """Phase A: cluster strict-metadata. Retourne (groupes, candidats_restants)."""
    buckets: Dict[str, List[MultiSignalCandidate]] = {}
    for c in candidates:
        if not (1900 <= int(c.year or 0) <= 2100):
            continue
        key = _strict_key(c, norm_for_tokens=norm_for_tokens)
        buckets.setdefault(key, []).append(c)

    groups: List[MultiSignalGroup] = []
    remaining: List[MultiSignalCandidate] = []

    # Ajouter aussi les candidats avec year invalide (ils n'ont pas ete buckets)
    invalid_year_ids = {
        c.item_id for c in candidates if not (1900 <= int(c.year or 0) <= 2100)
    }
    for c in candidates:
        if c.item_id in invalid_year_ids:
            remaining.append(c)

    for key, items in buckets.items():
        if len(items) >= 2:
            groups.append(
                MultiSignalGroup(
                    members=[i.item_id for i in items],
                    phase=PHASE_STRICT_METADATA,
                    representative_title=items[0].title,
                    representative_year=int(items[0].year or 0),
                )
            )
        else:
            remaining.extend(items)

    return groups, remaining


def _phase_b_fuzzy_title(
    candidates: Sequence[MultiSignalCandidate],
    existing_groups: List[MultiSignalGroup],
    *,
    min_score: int = FUZZY_TITLE_MIN_SCORE,
    year_tolerance: int = FUZZY_YEAR_TOLERANCE,
) -> Tuple[List[MultiSignalGroup], List[MultiSignalCandidate]]:
    """Phase B: fuzzy title + year +-1.

    Pour chaque candidat restant, on cherche d'abord parmi les groupes deja
    crees (Phase A) un titre representatif suffisamment proche. Si trouve,
    on ajoute au groupe. Sinon, on essaie de fusionner avec un autre
    candidat restant via le meme critere (et on cree un nouveau groupe).

    Indexation: les candidats restants sont indexes par (premiere lettre
    normalisee, plage d'annee) pour eviter le NxN naif sur 1000+ films.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.warning("rapidfuzz indisponible : phase B (fuzzy_title) sautee")
        return [], list(candidates)

    if not candidates:
        return [], []

    # Normalise pour matching
    norm_titles: Dict[str, str] = {
        c.item_id: _normalize_title_for_fuzzy(c.title) for c in candidates
    }

    new_groups: List[MultiSignalGroup] = []
    remaining: List[MultiSignalCandidate] = []
    consumed_ids: set[str] = set()

    # Indexer les groupes existants par (token-stable, annee)
    # pour Phase A -> Phase B (ajout d'un candidat a un groupe existant).
    # NB: la cle utilise `_index_token` (premier token apres tri) afin
    # d'etre invariante a l'ordre des mots, comme token_sort_ratio.
    def _phase_a_index() -> Dict[Tuple[str, int], List[Tuple[str, MultiSignalGroup]]]:
        idx: Dict[Tuple[str, int], List[Tuple[str, MultiSignalGroup]]] = {}
        for g in existing_groups:
            rep_norm = _normalize_title_for_fuzzy(g.representative_title)
            if not rep_norm:
                continue
            token = _index_token(rep_norm)
            idx.setdefault((token, int(g.representative_year)), []).append(
                (rep_norm, g)
            )
        return idx

    a_index = _phase_a_index()

    def _find_group_match(c: MultiSignalCandidate) -> Optional[MultiSignalGroup]:
        norm = norm_titles[c.item_id]
        if not norm:
            return None
        token = _index_token(norm)
        best_group: Optional[MultiSignalGroup] = None
        best_score = -1.0
        for dy in range(-year_tolerance, year_tolerance + 1):
            for rep_norm, g in a_index.get((token, c.year + dy), []):
                score = fuzz.token_sort_ratio(norm, rep_norm)
                if score >= min_score and score > best_score:
                    best_score = score
                    best_group = g
        return best_group

    # Pass 1: tenter d'ajouter chaque candidat a un groupe Phase A existant
    for c in candidates:
        if c.item_id in consumed_ids:
            continue
        group_match = _find_group_match(c)
        if group_match is not None:
            group_match.members.append(c.item_id)
            consumed_ids.add(c.item_id)
            logger.debug(
                "phase B (fuzzy_title -> group): item=%s ajoute au groupe '%s' (%d)",
                c.item_id,
                group_match.representative_title,
                group_match.representative_year,
            )

    # Pass 2: parmi les non-consommes, regrouper entre eux via fuzzy
    leftovers = [c for c in candidates if c.item_id not in consumed_ids]

    # Indexer par (token-stable, annee) ; meme justification que pour
    # `_phase_a_index` : la cle doit etre invariante au tri des tokens.
    leftover_index: Dict[Tuple[str, int], List[MultiSignalCandidate]] = {}
    for c in leftovers:
        norm = norm_titles[c.item_id]
        if not norm:
            continue
        token = _index_token(norm)
        leftover_index.setdefault((token, c.year), []).append(c)

    visited: set[str] = set()
    for c in leftovers:
        if c.item_id in visited:
            continue
        norm = norm_titles[c.item_id]
        if not norm:
            remaining.append(c)
            continue
        token = _index_token(norm)
        cluster: List[MultiSignalCandidate] = [c]
        visited.add(c.item_id)
        for dy in range(-year_tolerance, year_tolerance + 1):
            for other in leftover_index.get((token, c.year + dy), []):
                if other.item_id in visited:
                    continue
                other_norm = norm_titles[other.item_id]
                if not other_norm:
                    continue
                score = fuzz.token_sort_ratio(norm, other_norm)
                if score >= min_score:
                    cluster.append(other)
                    visited.add(other.item_id)
                    logger.debug(
                        "phase B (fuzzy_title -> new): %s ~ %s = %d",
                        c.title,
                        other.title,
                        int(score),
                    )

        if len(cluster) >= 2:
            new_groups.append(
                MultiSignalGroup(
                    members=[i.item_id for i in cluster],
                    phase=PHASE_FUZZY_TITLE,
                    representative_title=cluster[0].title,
                    representative_year=int(cluster[0].year or 0),
                )
            )
        else:
            remaining.append(c)

    return new_groups, remaining


def _phase_c_audio_fingerprint(
    candidates: Sequence[MultiSignalCandidate],
    *,
    min_similarity: float = FINGERPRINT_MIN_SIMILARITY,
    year_pre_filter: int = FINGERPRINT_YEAR_PRE_FILTER,
) -> Tuple[List[MultiSignalGroup], List[MultiSignalCandidate]]:
    """Phase C: comparaison Chromaprint sur les candidats encore non groupes.

    Pre-filtre: on ne compare que les paires d'annee proche (+-year_pre_filter)
    pour eviter le NxN sur 1000+ films. Pour les films sans fingerprint, ils
    restent dans `remaining`.
    """
    try:
        from cinesort.domain.perceptual.audio_fingerprint import (
            compare_audio_fingerprints,
        )
    except ImportError:
        logger.warning("audio_fingerprint indisponible : phase C sautee")
        return [], list(candidates)

    with_fp = [c for c in candidates if c.audio_fingerprint]
    without_fp = [c for c in candidates if not c.audio_fingerprint]

    if len(with_fp) < 2:
        return [], list(candidates)

    # Indexer par annee pour pre-filtrer
    by_year: Dict[int, List[MultiSignalCandidate]] = {}
    for c in with_fp:
        by_year.setdefault(c.year, []).append(c)

    # Union-find leger pour fusionner les composantes connexes
    parent: Dict[str, str] = {c.item_id: c.item_id for c in with_fp}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    cand_by_id = {c.item_id: c for c in with_fp}

    # Comparer paires d'annees proches
    seen_pairs: set[Tuple[str, str]] = set()
    for c in with_fp:
        for dy in range(-year_pre_filter, year_pre_filter + 1):
            neighbours = by_year.get(c.year + dy, [])
            for other in neighbours:
                if other.item_id == c.item_id:
                    continue
                pair = tuple(sorted([c.item_id, other.item_id]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                sim = compare_audio_fingerprints(
                    c.audio_fingerprint, other.audio_fingerprint
                )
                if sim is None:
                    continue
                if sim >= min_similarity:
                    union(c.item_id, other.item_id)
                    logger.debug(
                        "phase C (audio_fingerprint): %s ~ %s sim=%.3f",
                        c.title,
                        other.title,
                        sim,
                    )

    # Reconstruire les groupes a partir de l'union-find
    clusters: Dict[str, List[MultiSignalCandidate]] = {}
    for item_id in parent:
        root = find(item_id)
        clusters.setdefault(root, []).append(cand_by_id[item_id])

    groups: List[MultiSignalGroup] = []
    grouped_ids: set[str] = set()
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        groups.append(
            MultiSignalGroup(
                members=[m.item_id for m in members],
                phase=PHASE_AUDIO_FINGERPRINT,
                representative_title=members[0].title,
                representative_year=int(members[0].year or 0),
            )
        )
        grouped_ids.update(m.item_id for m in members)

    remaining = [c for c in with_fp if c.item_id not in grouped_ids] + without_fp
    return groups, remaining


def group_by_multi_signal(
    candidates: Iterable[MultiSignalCandidate],
    *,
    phases: Optional[Sequence[str]] = None,
    norm_for_tokens=None,
    fuzzy_min_score: int = FUZZY_TITLE_MIN_SCORE,
    fuzzy_year_tolerance: int = FUZZY_YEAR_TOLERANCE,
    fingerprint_min_similarity: float = FINGERPRINT_MIN_SIMILARITY,
    fingerprint_year_pre_filter: int = FINGERPRINT_YEAR_PRE_FILTER,
) -> MultiSignalResult:
    """Regroupe les candidats selon les phases activees.

    Args:
        candidates: iterable de `MultiSignalCandidate`.
        phases: liste ordonnee des phases a activer parmi
            (strict_metadata, fuzzy_title, audio_fingerprint).
            None = DEFAULT_PHASES (toutes activees).
        norm_for_tokens: callable str -> str pour normaliser les titres en
            Phase A (compat avec `duplicate_support.movie_key`). Si None,
            on utilise un fallback lower() identique a la regle historique.
        fuzzy_min_score: seuil rapidfuzz token_sort_ratio (0-100), defaut 88.
        fuzzy_year_tolerance: tolerance annee Phase B, defaut +-1.
        fingerprint_min_similarity: seuil Hamming Phase C, defaut 0.85.
        fingerprint_year_pre_filter: tolerance annee pre-filtre Phase C, defaut +-2.

    Returns:
        MultiSignalResult avec groupes (>=2 membres) et compteurs par phase.
    """
    cand_list: List[MultiSignalCandidate] = list(candidates)
    if not cand_list:
        return MultiSignalResult(phases_used=[], phase_counts={})

    if phases is None:
        phases = DEFAULT_PHASES
    phases = list(phases)

    if norm_for_tokens is None:
        # Fallback compatible avec duplicate_support.movie_key historique
        def norm_for_tokens(s: str) -> str:
            return (s or "").strip().lower()

    all_groups: List[MultiSignalGroup] = []
    phase_counts: Dict[str, int] = {}
    remaining = cand_list

    if PHASE_STRICT_METADATA in phases:
        groups_a, remaining = _phase_a_strict_metadata(
            remaining, norm_for_tokens=norm_for_tokens
        )
        all_groups.extend(groups_a)
        phase_counts[PHASE_STRICT_METADATA] = len(groups_a)

    if PHASE_FUZZY_TITLE in phases:
        groups_b, remaining = _phase_b_fuzzy_title(
            remaining,
            all_groups,
            min_score=fuzzy_min_score,
            year_tolerance=fuzzy_year_tolerance,
        )
        all_groups.extend(groups_b)
        # Compter aussi les ajouts a Phase A
        phase_counts[PHASE_FUZZY_TITLE] = len(groups_b)

    if PHASE_AUDIO_FINGERPRINT in phases:
        groups_c, remaining = _phase_c_audio_fingerprint(
            remaining,
            min_similarity=fingerprint_min_similarity,
            year_pre_filter=fingerprint_year_pre_filter,
        )
        all_groups.extend(groups_c)
        phase_counts[PHASE_AUDIO_FINGERPRINT] = len(groups_c)

    logger.info(
        "multi_signal grouping: phases=%s groups_total=%d counts=%s",
        phases,
        len(all_groups),
        phase_counts,
    )

    return MultiSignalResult(
        groups=all_groups,
        phases_used=phases,
        phase_counts=phase_counts,
    )


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def candidates_from_rows(
    rows: Iterable[Any],
    decisions: Dict[str, Dict[str, object]],
    *,
    fingerprint_lookup=None,
) -> List[MultiSignalCandidate]:
    """Construit la liste des `MultiSignalCandidate` depuis les rows de plan.

    Args:
        rows: iterable de PlanRow (duck-typed : row_id, proposed_title,
            proposed_year, edition).
        decisions: dict[row_id, {ok, title, year, ...}] (validation utilisateur).
        fingerprint_lookup: callable optional row_id -> Optional[str] qui
            retourne le fingerprint Chromaprint base64. Si None, Phase C
            n'aura aucun signal.

    Returns:
        Liste filtree des candidats ok=True avec year valide.
    """
    out: List[MultiSignalCandidate] = []
    for row in rows:
        dec = decisions.get(row.row_id, {})
        if not bool(dec.get("ok", False)):
            continue
        title = str(dec.get("title") or row.proposed_title or "").strip()
        if not title:
            continue
        try:
            year = int(dec.get("year") or row.proposed_year)
        except (ValueError, TypeError):
            year = int(getattr(row, "proposed_year", 0) or 0)
        if not (1900 <= year <= 2100):
            continue
        edition = getattr(row, "edition", None)
        fp: Optional[str] = None
        if fingerprint_lookup is not None:
            try:
                fp = fingerprint_lookup(row.row_id)
            except (OSError, KeyError, AttributeError, ValueError) as exc:
                logger.debug(
                    "fingerprint_lookup error for row %s: %s", row.row_id, exc
                )
                fp = None
        out.append(
            MultiSignalCandidate(
                item_id=row.row_id,
                title=title,
                year=year,
                edition=edition,
                audio_fingerprint=fp,
            )
        )
    return out


def augment_groups_with_multi_signal(
    base_groups: List[Dict[str, object]],
    rows: Iterable[Any],
    decisions: Dict[str, Dict[str, object]],
    *,
    phases: Optional[Sequence[str]] = None,
    norm_for_tokens=None,
    fingerprint_lookup=None,
) -> List[Dict[str, object]]:
    """Ajoute aux groupes existants ceux detectes par fuzzy + fingerprint.

    Ne supprime jamais un groupe existant (backward compat). Les nouveaux
    groupes detectes par Phase B / C sont ajoutes a la liste sortie avec :
        - `detection_phase`: "fuzzy_title" ou "audio_fingerprint"
        - `advisory`: True (signal informatif, pas un conflit de target)
        - `rows`: liste des row_id du groupe

    Args:
        base_groups: groupes existants (sortie de `find_duplicate_targets`).
        rows: PlanRows.
        decisions: decisions utilisateur.
        phases: phases a activer (default: DEFAULT_PHASES, donc toutes).
        norm_for_tokens: cf `group_by_multi_signal`.
        fingerprint_lookup: callable row_id -> Optional[str] pour Phase C.

    Returns:
        Liste enrichie de groupes (les avis multi-signal sont marques par
        `advisory=True` et `detection_phase`).
    """
    candidates = candidates_from_rows(
        rows, decisions, fingerprint_lookup=fingerprint_lookup
    )
    if not candidates:
        return list(base_groups)

    # Ids deja dans des groupes existants
    existing_ids: set[str] = set()
    for g in base_groups:
        for item in g.get("rows", []) or []:
            rid = item.get("row_id") if isinstance(item, dict) else None
            if rid:
                existing_ids.add(str(rid))

    result = group_by_multi_signal(
        candidates,
        phases=phases,
        norm_for_tokens=norm_for_tokens,
    )

    enriched = list(base_groups)
    for g in result.groups:
        # Filtrer : si TOUS les membres sont deja groupes par base, on saute
        new_members = [m for m in g.members if m not in existing_ids]
        if len(new_members) < 2 and not (
            len(g.members) >= 2 and any(m not in existing_ids for m in g.members)
        ):
            continue
        # Skip Phase A (deja gere par base_groups identique)
        if g.phase == PHASE_STRICT_METADATA:
            continue
        enriched.append(
            {
                "title": g.representative_title,
                "year": g.representative_year,
                "rows": [
                    {"row_id": rid, "kind": "advisory"} for rid in g.members
                ],
                "existing_paths": [],
                "plan_conflict": False,
                "advisory": True,
                "detection_phase": g.phase,
            }
        )

    return enriched
