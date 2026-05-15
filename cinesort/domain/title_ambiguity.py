"""P2.2 : résolution "deux films même titre".

Scénario type — "Dune (1984)" vs "Dune (2021)" :
  - Nom de dossier `Dune.1080p/` sans année → TMDb retourne les deux.
  - Sans désambiguïsation contextuelle, le candidat le plus populaire gagne
    (probablement 2021), mais l'utilisateur a peut-être la version 1984.

Ce module fournit deux fonctions pures :

- `detect_title_ambiguity(candidates)` : retourne True s'il y a 2+ candidats
  avec le même titre normalisé (même si années différentes).
- `disambiguate_by_context(candidates, context)` : promeut le candidat qui
  matche le mieux les indices contextuels (année du nom, NFO tmdb_id,
  runtime probe vs NFO). Retourne les candidats modifiés + flag booléen.

Comportement rétrocompatible — si aucune ambiguïté, les candidats sont
retournés inchangés et `ambiguous = False`.

Plex/Jellyfin/tinyMediaManager laissent l'utilisateur résoudre manuellement
l'ambiguïté via une UI "Fix Match". CineSort va plus loin : désambiguïsation
automatique sur signaux contextuels, fallback UI seulement si résolution
impossible (flag `title_ambiguity_detected`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple


# Articles à strip avant comparaison (matching cross-langue plus robuste).
# Note : les apostrophes sont converties en espaces lors de la normalisation,
# donc "l'" devient "l " avant le strip d'article. Même remarque pour "d ".
_LEADING_ARTICLES = ("the ", "le ", "la ", "les ", "l ", "un ", "une ", "des ", "a ", "an ", "d ")


def normalize_title_for_ambiguity(title: str) -> str:
    """Normalise un titre pour détection d'ambiguïté.

    Règles :
      - lowercase
      - strip accents (unicode NFKD)
      - retire ponctuation
      - collapse espaces multiples
      - retire article initial (the, le, la, un, a...)

    Exemples :
      "The Thing"    -> "thing"
      "Dune: Part 1" -> "dune part 1"
      "L'Été"        -> "ete"
    """
    if not title:
        return ""
    s = unicodedata.normalize("NFKD", str(title))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for art in _LEADING_ARTICLES:
        if s.startswith(art):
            s = s[len(art) :]
            break
    return s


def detect_title_ambiguity(candidates: List[Any]) -> Tuple[bool, Optional[str]]:
    """True si au moins 2 candidats TMDb ont le même titre normalisé.

    Les candidats "nfo" et "name" sont ignorés (leur titre vient du nom de
    fichier, pas d'une ambiguïté réelle). Seule l'ambiguïté côté TMDb nous
    intéresse (2 films distincts qui partagent un titre).

    Retourne (ambigu, titre_normalise) — le titre est utile pour logs/UI.
    """
    tmdb_groups: Dict[str, int] = {}
    first_match: Optional[str] = None
    for c in candidates:
        source = str(getattr(c, "source", "") or "").lower()
        if source not in ("tmdb", "nfo_tmdb", "nfo_imdb"):
            continue
        title = str(getattr(c, "title", "") or "")
        key = normalize_title_for_ambiguity(title)
        if not key:
            continue
        tmdb_groups[key] = tmdb_groups.get(key, 0) + 1
        if tmdb_groups[key] >= 2 and first_match is None:
            first_match = key
    is_ambiguous = any(v >= 2 for v in tmdb_groups.values())
    return is_ambiguous, first_match


def _score_boost_for_context_match(
    candidate: Any,
    context: Dict[str, Any],
) -> Tuple[float, List[str]]:
    """Calcule le boost à appliquer au score d'un candidat selon les matches contextuels.

    Signaux, ordre de force décroissante :
      1. NFO tmdb_id correspond exactement -> +0.15 (signal le plus fort)
      2. Année du dossier/fichier correspond exactement -> +0.10
      3. Année du dossier/fichier à ±1 an -> +0.05
      4. Runtime probe proche du runtime NFO -> +0.03 (signal faible mais
         présent — surtout utile pour trancher entre remakes proches en année).

    Retourne (boost, raisons) — les raisons servent à la note du candidat.
    """
    boost = 0.0
    reasons: List[str] = []

    nfo_tmdb_id = context.get("nfo_tmdb_id")
    if nfo_tmdb_id and getattr(candidate, "tmdb_id", None):
        try:
            if int(nfo_tmdb_id) == int(candidate.tmdb_id):
                boost += 0.15
                reasons.append("nfo_tmdb_id exact")
        except (TypeError, ValueError):
            pass

    name_year = context.get("name_year")
    cand_year = getattr(candidate, "year", None)
    if name_year is not None and cand_year is not None:
        try:
            delta = abs(int(cand_year) - int(name_year))
            if delta == 0:
                boost += 0.10
                reasons.append("annee exacte")
            elif delta == 1:
                boost += 0.05
                reasons.append("annee ±1")
        except (TypeError, ValueError):
            pass

    nfo_runtime = context.get("nfo_runtime")
    candidate_runtime = getattr(candidate, "runtime_min", None)
    if nfo_runtime and candidate_runtime:
        try:
            if abs(int(candidate_runtime) - int(nfo_runtime)) <= 10:
                boost += 0.03
                reasons.append("runtime proche nfo")
        except (TypeError, ValueError):
            pass

    return boost, reasons


def disambiguate_by_context(
    candidates: List[Any],
    context: Dict[str, Any],
) -> Tuple[List[Any], bool, Optional[str]]:
    """Ajoute un boost aux candidats qui matchent les indices contextuels.

    Ne modifie les scores QUE si une ambiguïté est détectée — c'est volontaire :
    on ne veut pas sur-promouvoir un match année dans les cas non ambigus.

    Args:
        candidates : liste de `Candidate` (dataclasses frozen).
        context : dict avec `name_year`, `nfo_tmdb_id`, `nfo_runtime` (optionnels).

    Returns:
        (nouvelle_liste, ambigu, titre_ambigu) — nouvelle_liste a les scores
        ajustés sur les candidats matchant. `ambigu=True` si détection ambiguïté.
        `titre_ambigu` est le titre normalisé qui a causé l'ambiguïté.
    """
    is_ambiguous, ambiguous_title = detect_title_ambiguity(candidates)
    if not is_ambiguous:
        return candidates, False, None

    out: List[Any] = []
    for c in candidates:
        # On ne boost que les candidats dont le titre normalisé correspond
        # au groupe ambigu — les autres restent intacts.
        title_key = normalize_title_for_ambiguity(str(getattr(c, "title", "") or ""))
        if title_key != ambiguous_title:
            out.append(c)
            continue
        boost, reasons = _score_boost_for_context_match(c, context)
        if boost == 0.0:
            out.append(c)
            continue
        new_score = min(1.0, float(c.score) + boost)
        note_extra = "disambig: " + ",".join(reasons)
        existing_note = str(getattr(c, "note", "") or "")
        new_note = f"{existing_note}, {note_extra}" if existing_note else note_extra
        promoted = replace(c, score=new_score, note=new_note)
        out.append(promoted)

    return out, True, ambiguous_title


__all__ = [
    "normalize_title_for_ambiguity",
    "detect_title_ambiguity",
    "disambiguate_by_context",
]
