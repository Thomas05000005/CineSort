"""OMDb cross-check post-plan (Phase 6.2).

Apres `plan_multi_roots`, on parcourt les PlanRows avec confidence < seuil
configurable et on appelle OMDb pour valider/invalider le match TMDb. La
divergence pose un warning `omdb_disagree` ; la convergence boost la confidence.

Trade-off design :
- **Post-process** (vs in-line dans `_plan_item`) : evite la propagation
  d'OmdbClient a travers 4 niveaux de signatures et l'impact perf
  (rate-limit 1 req/s) qui aurait bloque le scan principal.
- **Title+year search** (vs IMDb id) : OMDb's `search_by_title` est moins
  precis qu'`find_by_imdb_id` mais marche meme sans NFO. Plus tard, on
  pourra prendre IMDb id du NFO en priorite.

Cf cinesort/infra/omdb_client.py pour le client.
Cf cinesort/ui/api/run_flow_support.py pour l'invocation.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from typing import Any, Callable, List, Optional, Tuple

from cinesort.domain.confidence_thresholds import confidence_label
from cinesort.domain.conversions import to_int
from cinesort.infra.omdb_client import OmdbClient, OmdbResult

logger = logging.getLogger(__name__)


# Warning flag pose en cas de divergence
WARN_OMDB_DISAGREE = "omdb_disagree"

# Bonus/malus appliques a la confidence
_BONUS_FULL_CONVERGENCE = 20  # title + year exacts
_BONUS_PARTIAL_CONVERGENCE = 5  # year exact mais title legerement different
_PENALTY_DIVERGENCE = -25  # title + year tous deux faux

# Tolerance annee pour "convergence partielle"
_YEAR_TOLERANCE = 1

# Pre-compile : _normalize_title_for_compare est appele dans une boucle sur des
# milliers de rows (cross_check_rows_with_omdb), evite N x recompilation.
_NON_ALPHANUM_RE = re.compile(r"[^a-z0-9]")

# AUDIT F24 (revue R1) : `notes` fige le couple label/score EN TOUTES LETTRES.
# core.build_plan_note ouvre la note par "Confiance MED (72/100)." et ce champ
# est stocke, serialise verbatim dans plan.jsonl, expose par dashboard_support et
# AFFICHE tel quel a l'utilisateur (traitement.js "Notes :"). Resynchroniser le
# seul `confidence_label` faisait dire "high" au badge et "MED (72/100)" a la
# note juste a cote — avant le correctif F24 les deux etaient au moins d'accord.
_CONFIDENCE_NOTE_RE = re.compile(r"^Confiance\s+[A-Za-z]+\s+\(\d+/100\)\.")


def resync_confidence_fields(row: Any, new_confidence: int) -> None:
    """Aligne `confidence_label` ET la 1re phrase de `notes` sur `new_confidence`.

    Helper PARTAGE par les deux post-process qui mutent `row.confidence`
    (omdb_cross_check et runtime_probe_check) : ce sont les seuls endroits ou le
    couple (confidence, label, notes) peut se desynchroniser, aucun consommateur
    aval ne recalculant ces champs derives.

    Tolerant par construction :
    - `confidence_label` n'est ecrit que si la row porte le champ (les stubs de
      test ne l'ont pas toujours) ;
    - `notes` n'est reecrit que si sa 1re phrase a bien la forme attendue ; une
      note absente, vide ou d'un autre format est laissee STRICTEMENT intacte
      (on ne mutile jamais un texte qu'on n'a pas produit).
    """
    label = confidence_label(int(new_confidence))
    if hasattr(row, "confidence_label"):
        row.confidence_label = label
    notes = getattr(row, "notes", None)
    if not isinstance(notes, str) or not notes:
        return
    updated, n_sub = _CONFIDENCE_NOTE_RE.subn(f"Confiance {label.upper()} ({int(new_confidence)}/100).", notes, count=1)
    if n_sub:
        row.notes = updated


@lru_cache(maxsize=2048)
def _normalize_title_for_compare(title: str) -> str:
    """Normalise un titre pour comparaison (lowercase, strip whitespace + punct).

    Cf #542 audit 2026-06-06 : la fonction execute 3 re.sub + 2
    unicodedata.normalize a chaque appel. Sur 5000 rows + multiple comparisons
    par row, c'est ~20k appels avec haute redondance (memes titres TMDb / OMDb
    apparaissent regulierement). lru_cache(2048) garde une emp reinte memoire
    minime (~200 KB) pour eviter la recomputation.
    """
    if not title:
        return ""
    s = title.lower().strip()
    # Strip accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Retire articles + ponctuation
    return _NON_ALPHANUM_RE.sub("", s)


def _compute_adjustment(
    chosen_title: str,
    chosen_year: Optional[int],
    omdb_result: OmdbResult,
) -> Tuple[int, Optional[str]]:
    """Retourne (bonus_confidence, warning_flag).

    Cas :
    - title+year tous deux match exact -> +20, no warning
    - year exact ET title proche (norm equal apres strip articles/punct) -> +20
    - year exact mais title different -> +5 (TMDb a peut-etre un titre traduit)
    - year ±1 ET title similaire -> +5 (delta possible : remaster, release date)
    - tout le reste -> -25 + warning omdb_disagree
    """
    if not omdb_result.year or not chosen_year:
        # OMDb sans annee : on ne peut pas comparer, no-op
        return 0, None

    norm_chosen = _normalize_title_for_compare(chosen_title)
    norm_omdb = _normalize_title_for_compare(omdb_result.title)
    title_match = bool(norm_chosen) and norm_chosen == norm_omdb

    year_diff = abs(omdb_result.year - chosen_year)
    year_exact = year_diff == 0
    year_close = year_diff <= _YEAR_TOLERANCE

    if title_match and year_exact:
        return _BONUS_FULL_CONVERGENCE, None
    if title_match and year_close:
        # Titre identique, annee differente d'1 max : convergence partielle
        return _BONUS_PARTIAL_CONVERGENCE, None
    if year_exact and not title_match:
        # Annee identique mais titre different : TMDb a peut-etre la traduction FR
        # et OMDb le titre original anglais. Convergence partielle.
        return _BONUS_PARTIAL_CONVERGENCE, None
    # Divergence franche : ni title ni year en commun
    return _PENALTY_DIVERGENCE, WARN_OMDB_DISAGREE


def cross_check_rows_with_omdb(
    rows: List[Any],
    omdb_client: OmdbClient,
    *,
    min_confidence_for_call: int = 90,
    log: Optional[Callable[[str, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> int:
    """Cross-check les PlanRows avec confidence basse contre OMDb.

    Modifie en place : ajuste `row.confidence` (clamp [0, 100]) et append le
    warning `omdb_disagree` a `row.warning_flags` en cas de divergence.

    Args:
        rows: liste de PlanRow (modifie en place)
        omdb_client: instance OmdbClient
        min_confidence_for_call: seuil sous lequel on appelle OMDb (default 90).
            `0` est une valeur legitime (l'UI clampe [0, 100]) et signifie
            "ne jamais appeler OMDb" : elle ne doit PAS retomber sur 90 (#791).
        log: callback de log optionnel
        should_cancel: callback de cancellation optionnel

    Returns:
        Nombre de rows qui ont ete cross-checkees (= ayant fait un appel OMDb).
    """
    if not rows or not omdb_client:
        return 0

    # `to_int` (et non `... or 90`) : un seuil regle a 0 par l'utilisateur doit
    # rester 0 (= OMDb desactive), seul None/invalide retombe sur 90. Cf la
    # regle de revue "sentinelle falsy" dans cinesort/domain/conversions.py.
    threshold = max(0, min(100, to_int(min_confidence_for_call, 90)))

    n_checked = 0
    n_converge = 0
    n_diverge = 0
    n_partial = 0
    n_no_response = 0

    for row in rows:
        if should_cancel and should_cancel():
            if log:
                log("INFO", f"OMDb cross-check cancele apres {n_checked} films")
            break

        confidence = getattr(row, "confidence", 0)
        if confidence >= threshold:
            continue

        title = str(getattr(row, "proposed_title", "") or "")
        year = getattr(row, "proposed_year", None)
        if not title or not year:
            continue

        try:
            omdb_result = omdb_client.search_by_title(title, int(year))
        except (ValueError, TypeError, OSError) as exc:
            logger.debug("omdb cross_check error for %r/%r: %s", title, year, exc)
            omdb_result = None

        n_checked += 1
        if omdb_result is None:
            n_no_response += 1
            continue

        bonus, warning = _compute_adjustment(title, year, omdb_result)
        new_confidence = max(0, min(100, confidence + bonus))
        row.confidence = new_confidence
        # AUDIT F24 : confidence_label ET notes sont des champs STOCKES
        # (domain/core.py) jamais recomputes en aval (serialises verbatim dans
        # plan.jsonl -> dashboard). Sans cette resynchro, une row 72/'med' boostee
        # a 92 gardait le badge 'med' et restait comptee dans "Cas a verifier", et
        # une row 88/'high' penalisee a 63 gardait un badge 'high' mensonger.
        # Revue R1 : `notes` porte le MEME couple en toutes lettres ("Confiance
        # MED (72/100).") et etait laisse perime -> badge et note se contredisaient.
        # Garde `bonus` : si OMDb n'a pas d'annee (bonus 0) rien n'a bouge, on ne
        # touche a rien.
        if bonus:
            resync_confidence_fields(row, new_confidence)

        if warning:
            flags = getattr(row, "warning_flags", None)
            if flags is None:
                row.warning_flags = [warning]
            elif warning not in flags:
                flags.append(warning)
            n_diverge += 1
        elif bonus >= _BONUS_FULL_CONVERGENCE:
            n_converge += 1
        elif bonus > 0:
            n_partial += 1

    if log:
        log(
            "INFO",
            f"OMDb cross-check : {n_checked} appels, {n_converge} convergence forte, "
            f"{n_partial} partielle, {n_diverge} divergence, {n_no_response} no-response",
        )

    return n_checked
