from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")
PAREN_YEAR_RE = re.compile(r"[\(\[\{]\s*(19\d{2}|20\d{2})\s*[\)\]\}]")
REMASTER_HINT_RE = re.compile(
    r"\b("
    r"remaster(?:ed)?|restor(?:ed|ation)|restaure(?:e|es|ee|ees)?|"
    r"anniversary|re[- ]?release|reissue|"
    r"director'?s[ ._-]?cut|final[ ._-]?cut|extended|special[ ._-]?edition|collector'?s[ ._-]?edition|redux"
    r")\b",
    re.IGNORECASE,
)

NOISE_RE = re.compile(
    r"""
    (\b(
        2160p|1080p|720p|480p|
        4k|uhd|hdr|hdr10plus|hdr10\+|dv|dolby|vision|
        bluray|brrip|bdrip|webrip|web[- ]dl|hdtv|remux|
        x265|x264|hevc|avc|xvid|divx|h\.?264|h\.?265|
        truehd|dts|dtshd|dts-hd|dts:x|atmos|aac|ac3|eac3|ddp|opus|flac|mp3|
        dd5\.?1|5\.?1|7\.?1|2\.?0|stereo|
        multi|truefrench|vf|vfi|vff|vo|vof|vostfr|vost|subfrench|
        10bit|8bit|
        extended|unrated|proper|repack|internal|limited|
        qtz|a3l|hdlight|4klight|
        hybrid|complete|dubbed|
        mhd|uhdrip
    )\b)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Weights for title similarity scoring.
_COV_MIN_WEIGHT = 0.65
_COV_MAX_WEIGHT = 0.35
_SEQ_WEIGHT = 0.58
_TOK_WEIGHT = 0.42

ARTICLES = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "de",
    "du",
    "d",
    "et",
    "ou",
    "el",
    "los",
    "las",
    "del",
    "y",
    "il",
    "lo",
    "gli",
    "i",
    "uno",
    "una",
    "di",
    "da",
}

_ROMAN_NUMBERS = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
}


def extract_year(text: str) -> Optional[int]:
    if not text:
        return None
    paren = [int(m.group(1)) for m in PAREN_YEAR_RE.finditer(text)]
    if paren:
        y = paren[-1]
        return y if 1900 <= y <= 2100 else None
    all_years = [int(m.group(1)) for m in YEAR_RE.finditer(text)]
    if not all_years:
        return None
    y = all_years[-1]
    return y if 1900 <= y <= 2100 else None


def extract_all_years(text: str) -> List[int]:
    if not text:
        return []
    out: List[int] = []
    for m in YEAR_RE.finditer(text):
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            out.append(y)
    return out


def _last_parenthesized_year(text: str) -> Optional[int]:
    years = [int(m.group(1)) for m in PAREN_YEAR_RE.finditer(text or "")]
    for y in reversed(years):
        if 1900 <= y <= 2100:
            return y
    return None


def infer_name_year(folder_name: str, video_name: str) -> Tuple[Optional[int], str, bool]:
    """Extract the most likely release year from folder/video names. Returns (year, reason, remaster_hint)."""
    logger.debug("infer_name_year: folder=%r video=%r", folder_name, video_name)
    combined = f"{folder_name} {video_name}"
    remaster_hint = bool(REMASTER_HINT_RE.search(combined))

    folder_paren = _last_parenthesized_year(folder_name)
    video_paren = _last_parenthesized_year(video_name)
    if folder_paren is not None and video_paren is not None:
        if folder_paren == video_paren:
            return folder_paren, "annee coherente dossier/fichier (parentheses)", remaster_hint
        if remaster_hint and abs(folder_paren - video_paren) >= 3:
            return (
                min(folder_paren, video_paren),
                "annee de sortie deduite (conflit parenthese + indice remaster)",
                True,
            )
        return (
            video_paren,
            f"conflit dossier/fichier ({folder_paren} vs {video_paren}), annee video privilegiee",
            remaster_hint,
        )

    if folder_paren is not None:
        return folder_paren, "annee du dossier (parentheses)", remaster_hint
    if video_paren is not None:
        return video_paren, "annee du fichier video (parentheses)", remaster_hint

    folder_years = extract_all_years(folder_name)
    video_years = extract_all_years(video_name)

    if remaster_hint and len(video_years) >= 2:
        earliest = min(video_years)
        latest = max(video_years)
        if latest - earliest >= 3:
            return earliest, "annee de sortie deduite (indice remaster/restaure)", True

    folder_year = folder_years[-1] if folder_years else None
    video_year = video_years[-1] if video_years else None

    if folder_year is not None and video_year is not None:
        if folder_year == video_year:
            return video_year, "annee coherente dossier/fichier", remaster_hint
        if remaster_hint and abs(folder_year - video_year) >= 3:
            return min(folder_year, video_year), "annee de sortie deduite (indice remaster/restaure)", True
        return video_year, "annee issue du fichier video", remaster_hint

    if video_year is not None:
        return video_year, "annee issue du fichier video", remaster_hint
    if folder_year is not None:
        return folder_year, "annee issue du dossier", remaster_hint
    return None, "aucune annee detectee", remaster_hint


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def clean_title_guess(text: str) -> str:
    # Phase 6.3 : delegue au scene_parser (regex etendues, edition strip,
    # release group strip, audio residue). Fallback historique conserve si
    # le parser retourne une chaine vide.
    from cinesort.domain.scene_parser import parse_scene_title

    parsed = parse_scene_title(text)
    if parsed:
        return parsed
    # Fallback : pipeline historique (cas degenere ou input vide)
    name = Path(text).stem
    name = name.replace(".", " ").replace("_", " ")
    name = re.sub(r"\(\s*(19\d{2}|20\d{2})\s*\)", "", name)
    name = NOISE_RE.sub(" ", name)
    name = re.sub(r"\b(?:[257]\s+1|2\s+0)\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(
        r"(?:\b(?:multi|truefrench|french|vf|vfi|vff|vo|vof|vostfr|vost|subfrench)\b\s*)+$",
        " ",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(r"\s+", " ", name).strip(" -_")
    return name.strip()


def title_prefix_before_parenthesized_year(text: str) -> str:
    raw = (Path(text).stem if text else "").strip()
    if not raw:
        return ""
    m = re.match(r"^(.*?)\s*[\(\[\{]\s*(19\d{2}|20\d{2})\s*[\)\]\}]", raw)
    if not m:
        return ""
    prefix = " ".join(m.group(1).split()).strip(" -_.")
    return prefix


def _norm_for_tokens(s: str) -> str:
    s = s.lower()
    s = _strip_accents(s)
    s = NOISE_RE.sub(" ", s)
    s = re.sub(r"\(\s*(19\d{2}|20\d{2})\s*\)", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens(s: str) -> List[str]:
    s2 = _norm_for_tokens(s)
    toks = [t for t in s2.split() if t]
    if len(toks) <= 2:
        return toks
    out = [t for t in toks if t not in ARTICLES and len(t) > 1]
    return out if len(out) >= 2 else toks


def seq_ratio(a: str, b: str) -> float:
    """Ratio de similarite entre deux chaines (0.0 a 1.0).

    Utilise rapidfuzz.fuzz.ratio() — drop-in pour difflib.SequenceMatcher.ratio()
    mais 5-100x plus rapide. Le resultat est divise par 100 car rapidfuzz
    retourne 0-100 alors que l'API interne attend 0.0-1.0.
    """
    if not a and not b:
        return 0.0
    from rapidfuzz import fuzz

    return fuzz.ratio(a, b) / 100.0


def title_match_score(nfo_title: str, candidate: str) -> Tuple[float, float]:
    ta = set(tokens(nfo_title))
    tb = set(tokens(candidate))
    cov = 0.0
    if tb:
        cov = len(ta & tb) / len(tb)
    na = _norm_for_tokens(nfo_title)
    nb = _norm_for_tokens(candidate)
    seq = seq_ratio(na, nb) if na and nb else 0.0
    return cov, seq


def _parse_small_seq_token(token: str) -> Optional[int]:
    t = (token or "").strip().lower()
    if not t:
        return None
    if t.isdigit():
        n = int(t)
        if 2 <= n <= 20:
            return n
        return None
    return _ROMAN_NUMBERS.get(t)


def _extract_trailing_sequel_num(text: str) -> Optional[int]:
    toks = [t for t in _norm_for_tokens(text or "").split() if t]
    if not toks:
        return None
    for i in range(len(toks) - 1, -1, -1):
        n = _parse_small_seq_token(toks[i])
        if n is None:
            continue
        prev = toks[i - 1] if i > 0 else ""
        if prev in {"episode", "ep", "part", "chapter", "chapitre", "vol", "volume"}:
            return None
        return n
    return None


def _title_similarity(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    cov_ab, seq = title_match_score(query, candidate)
    cov_ba, _ = title_match_score(candidate, query)
    tok = (_COV_MIN_WEIGHT * min(cov_ab, cov_ba)) + (_COV_MAX_WEIGHT * max(cov_ab, cov_ba))
    sim = (_SEQ_WEIGHT * seq) + (_TOK_WEIGHT * tok)
    return max(0.0, min(1.0, sim))


def _tmdb_prefix_equivalent(query: str, candidate: str) -> bool:
    nq = _norm_for_tokens(query)
    nc = _norm_for_tokens(candidate)
    if not nq or not nc:
        return False
    if nq == nc:
        return True
    tq = [t for t in nq.split() if t]
    tc = [t for t in nc.split() if t]
    if len(tq) < 2 or len(tc) < 2:
        return False
    return nc.startswith(nq + " ") or nq.startswith(nc + " ")


def _expand_tmdb_queries(queries: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()

    def add_query(raw: str) -> None:
        q = " ".join((raw or "").split()).strip()
        if len(q) < 2:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(q)

    for q in queries:
        q2 = " ".join((q or "").split())
        if not q2:
            continue
        add_query(q2)

        for m in re.finditer(r"\(([^()]{2,80})\)", q2):
            add_query(m.group(1))

        no_paren = re.sub(r"\([^)]*\)", " ", q2)
        add_query(no_paren)

        for sep in (" - ", " ? ", " ? ", ":", "/", "|"):
            if sep in q2:
                add_query(q2.split(sep, 1)[0])
                break

    return out
