"""Detection et inventaire des sous-titres externes a cote des videos.

Pas de renommage — les sous-titres suivent le dossier lors du move/rename.
Detection de langue par suffixe de nom de fichier (sous-titres EXTERNES) OU
via les pistes EMBARQUEES dans le conteneur (MKV/MP4) si un probe normalise
est fourni — fix Vague F 2026-05-25 (v1.5.3) : 853 films flagges a tort en
"subtitle_missing_fr" parce que la detection ignorait les pistes embarquees.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# -- Extensions sous-titres -------------------------------------------

SUBTITLE_EXTS = frozenset({".srt", ".ass", ".sub", ".sup", ".idx"})

# -- Mapping langues (ISO 639-1 ← ISO 639-2, noms courants, tags) ----

_LANG_MAP: Dict[str, str] = {
    # ISO 639-1
    "fr": "fr",
    "en": "en",
    "es": "es",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "nl": "nl",
    "ja": "ja",
    "zh": "zh",
    "ko": "ko",
    "ru": "ru",
    "ar": "ar",
    "pl": "pl",
    "sv": "sv",
    "da": "da",
    "fi": "fi",
    "no": "no",
    "cs": "cs",
    "hu": "hu",
    "ro": "ro",
    "tr": "tr",
    "el": "el",
    "he": "he",
    "th": "th",
    "vi": "vi",
    # ISO 639-2 / bibliographic
    "fre": "fr",
    "fra": "fr",
    "eng": "en",
    "spa": "es",
    "ger": "de",
    "deu": "de",
    "ita": "it",
    "por": "pt",
    "dut": "nl",
    "nld": "nl",
    "jpn": "ja",
    "chi": "zh",
    "zho": "zh",
    "kor": "ko",
    "rus": "ru",
    "ara": "ar",
    "pol": "pl",
    "swe": "sv",
    "dan": "da",
    "fin": "fi",
    "nor": "no",
    "cze": "cs",
    "ces": "cs",
    "hun": "hu",
    "rum": "ro",
    "ron": "ro",
    "tur": "tr",
    "gre": "el",
    "ell": "el",
    "heb": "he",
    "tha": "th",
    "vie": "vi",
    # Noms courants
    "french": "fr",
    "english": "en",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "dutch": "nl",
    "japanese": "ja",
    "chinese": "zh",
    "korean": "ko",
    "russian": "ru",
    "arabic": "ar",
    "polish": "pl",
    "swedish": "sv",
    "danish": "da",
    "finnish": "fi",
    "norwegian": "no",
    "czech": "cs",
    "hungarian": "hu",
    "romanian": "ro",
    "turkish": "tr",
    "greek": "el",
    "hebrew": "he",
    "thai": "th",
    "vietnamese": "vi",
    # Tags speciaux (pas des langues → "")
    "forced": "",
    "sdh": "",
    "hi": "",
    "cc": "",
    "commentary": "",
    "multi": "",
    "und": "",
    # Tags FR courants
    "vostfr": "fr",
    "vf": "fr",
    "vo": "en",
}


# -- Dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class SubtitleInfo:
    """Info sur un fichier sous-titre detecte."""

    filename: str
    ext: str
    language: str  # ISO 639-1 ("fr", "en") ou "" si inconnu
    language_source: str  # "suffix" | "unknown"
    is_orphan: bool  # True si pas de video correspondante


@dataclass(frozen=True)
class SubtitleReport:
    """Resume des sous-titres pour un film (une video dans un dossier)."""

    count: int
    languages: List[str]  # langues uniques detectees
    formats: List[str]  # extensions uniques
    orphans: int  # sous-titres sans video associee
    missing_languages: List[str]  # langues attendues absentes
    duplicate_languages: List[str]  # langues detectees en double
    details: List[SubtitleInfo]  # liste complete


# -- Fonctions publiques -----------------------------------------------


def detect_language_from_suffix(filename: str) -> str:
    """Detecte la langue depuis le suffixe du nom de fichier.

    Ex: 'Inception.fr.srt' → 'fr', 'Movie.eng.srt' → 'en', 'Movie.srt' → ''
    """
    stem = Path(filename).stem  # "Inception.fr" pour "Inception.fr.srt"
    parts = stem.rsplit(".", 1)
    if len(parts) < 2:
        return ""
    tag = parts[-1].strip().lower()
    return _LANG_MAP.get(tag, "")


def find_subtitles_in_folder(folder: Path) -> List[SubtitleInfo]:
    """Liste tous les fichiers sous-titres dans un dossier (non recursif)."""
    results: List[SubtitleInfo] = []
    try:
        entries = list(folder.iterdir())
    except (PermissionError, OSError):
        return []

    for entry in entries:
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if ext not in SUBTITLE_EXTS:
            continue
        lang = detect_language_from_suffix(entry.name)
        lang_source = "suffix" if lang else "unknown"
        results.append(
            SubtitleInfo(
                filename=entry.name,
                ext=ext,
                language=lang,
                language_source=lang_source,
                is_orphan=True,  # sera corrige par match_subtitles_to_video
            )
        )
    return sorted(results, key=lambda s: s.filename.lower())


def match_subtitles_to_video(
    subtitles: List[SubtitleInfo],
    video_stem: str,
) -> List[SubtitleInfo]:
    """Filtre les sous-titres qui correspondent a une video (par stem).

    Match si : sub_stem == video_stem OU sub_name commence par video_stem + '.'
    Les sous-titres matches sont retournes avec is_orphan=False.
    """
    if not video_stem:
        return []
    vs = video_stem.lower()
    matched: List[SubtitleInfo] = []
    for sub in subtitles:
        sub_name_no_ext = Path(sub.filename).stem.lower()
        # Exact stem match (ex: Movie.srt ↔ Movie.mkv)
        # Ou prefix match (ex: Movie.fr.srt ↔ Movie.mkv)
        if sub_name_no_ext == vs or sub_name_no_ext.startswith(vs + "."):
            matched.append(
                SubtitleInfo(
                    filename=sub.filename,
                    ext=sub.ext,
                    language=sub.language,
                    language_source=sub.language_source,
                    is_orphan=False,
                )
            )
    return matched


def _normalize_iso639(raw: str) -> str:
    """Normalise un tag de langue ISO 639-1/-2/-3 vers ISO 639-1.

    Vague F 2026-05-25 (v1.5.3) : utilise _LANG_MAP pour aligner la detection
    des pistes embarquees (ex: ffprobe expose `fra`, `fre`, MediaInfo `fr`).
    Renvoie "" si non resolvable ou tag special (forced/sdh/...).
    """
    return _LANG_MAP.get((raw or "").strip().lower(), "")


def build_subtitle_report(
    folder: Path,
    video: Path,
    expected_languages: Optional[List[str]] = None,
    *,
    embedded_subtitles: Optional[List[Dict[str, Any]]] = None,
) -> SubtitleReport:
    """Construit le rapport sous-titres pour une video dans un dossier.

    1. Trouve tous les sous-titres EXTERNES (fichiers .srt/.ass/.sub a cote)
    2. Matche ceux qui correspondent a la video (par stem)
    3. Detecte les langues EXTERNES (suffixe) + EMBARQUEES (probe ffprobe/mediainfo)
    4. Verifie les langues attendues vs union(externes, embarquees)
    5. Detecte les orphelins (externes) et doublons (externes)

    Fix Vague F 2026-05-25 (v1.5.3) : `embedded_subtitles` (optionnel, default
    None pour backward-compat) est la liste `normalized_probe["subtitles"]`,
    chaque item est `{"index": int, "language": str|None, "forced": bool}`.
    Les langues embarquees fusionnent avec les externes pour le calcul des
    langues manquantes — fixant les 853 films flagges a tort.
    """
    all_subs = find_subtitles_in_folder(folder)
    video_stem = video.stem
    matched = match_subtitles_to_video(all_subs, video_stem)

    # Orphelins : sous-titres du dossier qui ne matchent aucune video
    matched_filenames = {s.filename.lower() for s in matched}
    orphan_count = sum(1 for s in all_subs if s.filename.lower() not in matched_filenames)

    # Langues externes (fichiers .srt/.ass/... a cote du .mkv)
    external_languages: Set[str] = {s.language for s in matched if s.language}

    # Langues embarquees (pistes subtitle dans le conteneur)
    # Fix audit 2026-05-25 (v1.5.3) Vague F : auparavant ignorees → faux
    # positifs "subtitle_missing_fr" sur 853 films avec FR embarque.
    embedded_languages: Set[str] = set()
    if embedded_subtitles:
        for track in embedded_subtitles:
            if not isinstance(track, dict):
                continue
            raw_lang = (track.get("language") or "").strip().lower()
            if not raw_lang:
                # piste sans tag de langue → ignoree (ne pas inventer)
                continue
            normalized = _normalize_iso639(raw_lang)
            if normalized:
                embedded_languages.add(normalized)

    all_languages = external_languages | embedded_languages

    languages = sorted(all_languages)
    formats = sorted({s.ext for s in matched})

    # Fix audit 2026-05-26 (v1.5.6) Vague L (subs-3) : normalisation SYMETRIQUE.
    # Avant, `expected_languages` etait seulement .lower().strip() sans passer par
    # _LANG_MAP. Donc une attente saisie en ISO 639-2 ou en nom courant
    # ('french'/'francais'/'fra'/'fre') ne matchait JAMAIS les langues detectees
    # (deja normalisees en 'fr') -> tous les films flagges "manquant" a tort.
    # Maintenant : on normalise les DEUX cotes via _normalize_iso639, et on
    # compare des codes ISO 639-1 canoniques. On garde le code original dans la
    # liste `missing` quand il n'est pas resolvable (pour ne pas masquer une
    # saisie utilisateur erronee).
    expected_pairs = [
        (raw, _normalize_iso639(raw))
        for raw in (lang.strip() for lang in (expected_languages or []) if lang)
        if raw
    ]
    missing = [
        (norm or raw)
        for raw, norm in expected_pairs
        if (norm or raw.lower()) not in all_languages
    ]

    # Doublons de langue : restent sur les sous-titres EXTERNES uniquement
    # (un MKV avec 2 pistes FR embarquees n'est pas un probleme utilisateur).
    lang_counts: Dict[str, int] = {}
    for s in matched:
        if s.language:
            lang_counts[s.language] = lang_counts.get(s.language, 0) + 1
    duplicates = sorted(lang for lang, cnt in lang_counts.items() if cnt > 1)

    return SubtitleReport(
        count=len(matched),
        languages=languages,
        formats=formats,
        orphans=orphan_count,
        missing_languages=missing,
        duplicate_languages=duplicates,
        details=matched,
    )
