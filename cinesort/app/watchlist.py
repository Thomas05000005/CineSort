"""Watchlist import — compare une watchlist Letterboxd/IMDb avec la bibliotheque locale.

Parsing CSV (Letterboxd, IMDb), normalisation titres, matching titre+annee.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from typing import Any, Dict, List
import contextlib

logger = logging.getLogger("cinesort.watchlist")

# Articles initiaux a retirer pour le matching
_ARTICLES_RE = re.compile(
    r"^(?:the|a|an|le|la|les|l'|un|une|des|el|los|las|il|lo|gli|i)\s+",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    """Retire les diacritiques d'un texte."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _normalize_title(title: str) -> str:
    """Normalise un titre pour le matching : lowercase, sans accents, sans articles initiaux."""
    t = (title or "").strip().lower()
    t = _strip_accents(t)
    t = _ARTICLES_RE.sub("", t).strip()
    return t


# ---------------------------------------------------------------------------
# Parsing CSV
# ---------------------------------------------------------------------------


def parse_letterboxd_csv(csv_content: str) -> List[Dict[str, Any]]:
    """Parse un CSV Letterboxd (watchlist.csv). Colonnes : Date, Name, Year, Letterboxd URI."""
    films: List[Dict[str, Any]] = []
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            year = 0
            with contextlib.suppress(ValueError, TypeError):
                year = int(row.get("Year") or 0)
            films.append({"title": name, "year": year})
    except (csv.Error, UnicodeDecodeError) as exc:
        logger.warning("[watchlist] erreur parsing Letterboxd CSV: %s", exc)
    return films


def parse_imdb_csv(csv_content: str) -> List[Dict[str, Any]]:
    """Parse un CSV IMDb (watchlist export). Colonnes : Title, Year, Const."""
    films: List[Dict[str, Any]] = []
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            year = 0
            with contextlib.suppress(ValueError, TypeError):
                year = int(row.get("Year") or 0)
            imdb_id = (row.get("Const") or "").strip()
            films.append({"title": title, "year": year, "imdb_id": imdb_id or None})
    except (csv.Error, UnicodeDecodeError) as exc:
        logger.warning("[watchlist] erreur parsing IMDb CSV: %s", exc)
    return films


# ---------------------------------------------------------------------------
# Comparaison
# ---------------------------------------------------------------------------


def compare_watchlist(
    watchlist_films: List[Dict[str, Any]],
    local_rows: List[Any],
) -> Dict[str, Any]:
    """Compare les films de la watchlist avec la bibliotheque locale.

    Matching par titre normalise + annee (si disponible).
    """
    # Index local par titre normalise + annee
    local_keys: set[str] = set()
    local_title_only: set[str] = set()
    for row in local_rows:
        title = str(getattr(row, "proposed_title", "") or "")
        year = int(getattr(row, "proposed_year", 0) or 0)
        norm = _normalize_title(title)
        if norm:
            local_title_only.add(norm)
            if year:
                local_keys.add(f"{norm}|{year}")

    owned: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []

    # Pass 1 : matching exact (rapide, zero faux positif)
    for film in watchlist_films:
        title = film.get("title", "")
        year = film.get("year", 0)
        norm = _normalize_title(title)

        matched = False
        if norm and year and f"{norm}|{year}" in local_keys:
            matched = True
        elif norm and not year and norm in local_title_only:
            matched = True
        elif norm and year:
            # Fallback : titre seul (sans annee) si la watchlist a une annee mais le local non
            if norm in local_title_only:
                matched = True

        entry = {"title": title, "year": year}
        if matched:
            owned.append(entry)
        else:
            unmatched.append(entry)

    # Pass 2 : fuzzy matching sur les non-matches (rattrapage accents, ordre mots)
    missing: List[Dict[str, Any]] = []
    if unmatched:
        from rapidfuzz import fuzz as _fuzz

        # Construire un index local pour le fuzzy
        local_items_for_fuzzy: List[tuple[str, int]] = []
        for row in local_rows:
            t = str(getattr(row, "proposed_title", "") or "")
            y = int(getattr(row, "proposed_year", 0) or 0)
            n = _normalize_title(t)
            if n:
                local_items_for_fuzzy.append((n, y))

        _FUZZY_THRESHOLD = 85
        for entry in unmatched:
            norm_w = _normalize_title(entry["title"])
            w_year = entry.get("year", 0)
            found = False
            for local_norm, local_year in local_items_for_fuzzy:
                # Filtre annee strict si les deux ont une annee
                if w_year and local_year and w_year != local_year:
                    continue
                score = _fuzz.token_sort_ratio(norm_w, local_norm)
                if score >= _FUZZY_THRESHOLD:
                    owned.append(entry)
                    logger.debug("[watchlist] fuzzy match '%s' ~ '%s' (%d)", entry["title"], local_norm, int(score))
                    found = True
                    break
            if not found:
                missing.append(entry)

    total = len(watchlist_films)
    owned_count = len(owned)
    return {
        "total_watchlist": total,
        "owned": owned,
        "missing": missing,
        "owned_count": owned_count,
        "missing_count": len(missing),
        "coverage_pct": round(100.0 * owned_count / total, 1) if total > 0 else 100.0,
    }
