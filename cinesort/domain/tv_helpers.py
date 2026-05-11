from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Regex for S01E01, S1E5, S01.E01, etc. (point optionnel entre S et E)
_SE_RE = re.compile(r"[Ss](\d{1,2})\.?[Ee](\d{1,3})")
# Regex for 1x01, 2x05, etc. (\b pour eviter faux positifs comme "Movie.1080p.2x04")
_XE_RE = re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b")
# Regex for "Episode 5", "Ep.10", etc.
_EP_RE = re.compile(r"\b(?:episode|ep)[ ._-]?(\d{1,3})\b", re.IGNORECASE)
# Regex for "Season 1 Episode 1", "Saison 2 Episode 5", etc.
_SEASON_EPISODE_TEXT_RE = re.compile(
    r"(?:Season|Saison)\s+(\d{1,2})\s+(?:Episode|[EÉ]pisode)\s+(\d{1,3})",
    re.IGNORECASE,
)
# Regex for "Season N" folder names.
_SEASON_FOLDER_RE = re.compile(r"^(?:season|saison)[ ._-]?(\d{1,2})$", re.IGNORECASE)
# Noise to strip from series title guesses.
_TV_NOISE_RE = re.compile(
    r"\b("
    r"2160p|1080p|720p|480p|"
    r"x265|x264|hevc|avc|h\.?265|h\.?264|"
    r"bluray|bdrip|webrip|web-?dl|hdtv|dvdrip|"
    r"dts|aac|ac3|truehd|atmos|"
    r"repack|proper|multi|vostfr|vf|french"
    r")\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass(frozen=True)
class TvInfo:
    """Parsed TV episode metadata from folder/file names."""

    series_name: str
    season: Optional[int]
    episode: Optional[int]
    year: Optional[int] = None


def _clean_series_name(raw: str) -> str:
    """Strip codec/resolution noise and normalize a series title guess."""
    name = _TV_NOISE_RE.sub(" ", raw)
    name = re.sub(r"[\[\](){}]", " ", name)
    name = re.sub(r"[._-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Remove trailing year if present.
    name = re.sub(r"\s+\d{4}\s*$", "", name).strip()
    return name


def _extract_season_from_folder(folder_name: str) -> Optional[int]:
    """If folder_name is "Season N" or "Saison N", return N."""
    m = _SEASON_FOLDER_RE.match(folder_name.strip())
    return int(m.group(1)) if m else None


def parse_tv_info(folder: Path, video: Path) -> Optional[TvInfo]:
    """Extract TV series metadata from folder and video file names.

    Returns TvInfo if a TV episode pattern (S01E01, 1x01, Episode N) is found
    in the video filename. Returns None if no TV pattern is detected.
    """
    video_name = video.stem

    # 1. Try S01E01 pattern.
    m = _SE_RE.search(video_name)
    if m:
        season = int(m.group(1))
        episode = int(m.group(2))
        # Series name = everything before the S01E01 pattern.
        title_part = video_name[: m.start()]
    else:
        # 2. Try 1x01 pattern.
        m = _XE_RE.search(video_name)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
            title_part = video_name[: m.start()]
        else:
            # 3. Try "Season N Episode N" text pattern (FR/EN) — avant "Episode N" simple
            m = _SEASON_EPISODE_TEXT_RE.search(video_name)
            if m:
                season = int(m.group(1))
                episode = int(m.group(2))
                title_part = video_name[: m.start()]
            else:
                # 4. Try "Episode N" pattern (sans saison).
                m = _EP_RE.search(video_name)
                if m:
                    season = None
                    episode = int(m.group(1))
                    title_part = video_name[: m.start()]
                else:
                    return None

    # Derive series name from folder hierarchy.
    folder_name = folder.name
    season_from_folder = _extract_season_from_folder(folder_name)

    if season_from_folder is not None:
        # Folder is "Season N" — series name is the parent folder.
        if season is None:
            season = season_from_folder
        series_raw = folder.parent.name
    else:
        # Folder is the series folder (or mixed). Use folder name or title_part from filename.
        series_raw = title_part.strip() if title_part.strip() else folder_name

    series_name = _clean_series_name(series_raw)
    if not series_name:
        series_name = _clean_series_name(folder_name)
    if not series_name:
        series_name = folder_name

    # Extract year from folder name or series title.
    year = None
    year_match = _YEAR_RE.search(folder.parent.name if season_from_folder is not None else folder_name)
    if year_match:
        year = int(year_match.group(1))

    return TvInfo(
        series_name=series_name,
        season=season,
        episode=episode,
        year=year,
    )
