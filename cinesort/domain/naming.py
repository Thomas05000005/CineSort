"""Profils de renommage — templates configurables pour les noms de dossiers/fichiers.

Syntaxe : variables entre accolades {title}, {year}, etc.
Variables manquantes → chaine vide, separateurs orphelins nettoyes.
Le resultat final est toujours passe dans windows_safe().
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.codec_ranks import format_audio_channels as _format_audio_channels

# VQ-1 : import depuis path_utils (feuille) au lieu de core. Casse le cycle
# domain<->domain core -> duplicate_support -> (lazy) naming -> core.
# `cinesort.domain.core.windows_safe` reste un alias re-exporte pour backward
# compat avec les callers externes (apply_core, plan_support_*, etc.).
from cinesort.domain.path_utils import windows_safe

logger = logging.getLogger(__name__)

# --- Template par defaut (comportement identique a l'historique) ----------
_DEFAULT_MOVIE_TEMPLATE = "{title} ({year})"
_DEFAULT_TV_TEMPLATE = "{series} ({year})"

# --- Variables reconnues --------------------------------------------------
_KNOWN_VARS = frozenset(
    {
        # Toujours disponibles (PlanRow)
        "title",
        "year",
        "source",
        # TMDb
        "tmdb_id",
        "tmdb_tag",
        "original_title",
        # Probe video
        "resolution",
        "video_codec",
        "hdr",
        "bitrate",
        "container",
        # Probe audio
        "audio_codec",
        "channels",
        # Qualite
        "quality",
        "score",
        # TV
        "series",
        "season",
        "episode",
        "ep_title",
        # Edition (Director's Cut, Extended, IMAX, etc.)
        "edition",
        "edition-tag",
    }
)

# Regex pour extraire les variables d'un template
_VAR_RE = re.compile(r"\{([\w-]+)\}")

# Regex pour nettoyer les separateurs orphelins apres substitution
_CLEANUP_PATTERNS = [
    (re.compile(r"\[\s*\]"), ""),  # crochets vides
    (re.compile(r"\(\s*\)"), ""),  # parentheses vides
    (re.compile(r"\{\s*\}"), ""),  # accolades vides (residuelles)
    (re.compile(r"\s*-\s*$"), ""),  # tiret en fin
    (re.compile(r"^\s*-\s*"), ""),  # tiret en debut
    (re.compile(r"\s+-\s+(?=[\[\(])"), " "),  # tiret avant crochet/parenthese vide
    (re.compile(r"\s{2,}"), " "),  # espaces multiples
]

# Seuil de warning pour la longueur du path (preventif, ~20 chars de marge avant MAX_PATH)
_PATH_LENGTH_WARNING = 240

# VQ-3 : kill-switch MAX_PATH Windows. La limite historique Windows est 260
# chars (avec terminateur null). Au-dela on bascule en OSError obscur "Le
# chemin specifie est introuvable" ou "Nom de fichier trop long" selon le cas.
# Le kill-switch refuse de tenter le rename/move quand la cible depasserait
# ce seuil, en remontant un SKIP propre plutot qu'une exception cryptique.
# Le seuil exact 260 garde 0 char de marge ; on accepte 259 chars max pour
# inclure le terminateur null cote API Win32.
_PATH_LENGTH_KILL_SWITCH = 259


# --- Presets --------------------------------------------------------------


@dataclass(frozen=True)
class NamingProfile:
    """Profil de renommage avec templates film et TV."""

    id: str
    label: str
    movie_template: str
    tv_template: str


PRESETS: Dict[str, NamingProfile] = {
    "default": NamingProfile(
        id="default",
        label="Standard",
        movie_template="{title} ({year})",
        tv_template="{series} ({year})",
    ),
    "plex": NamingProfile(
        id="plex",
        label="Plex",
        movie_template="{title} ({year}) {tmdb_tag}",
        tv_template="{series} ({year})",
    ),
    "jellyfin": NamingProfile(
        id="jellyfin",
        label="Jellyfin",
        movie_template="{title} ({year}) [{resolution}]",
        tv_template="{series} ({year})",
    ),
    "quality": NamingProfile(
        id="quality",
        label="Qualite",
        movie_template="{title} ({year}) [{resolution} {video_codec}]",
        tv_template="{series} ({year})",
    ),
    "custom": NamingProfile(
        id="custom",
        label="Personnalise",
        movie_template=_DEFAULT_MOVIE_TEMPLATE,
        tv_template=_DEFAULT_TV_TEMPLATE,
    ),
}

# Mock hardcode pour le preview (Inception)
PREVIEW_MOCK_CONTEXT: Dict[str, str] = {
    "title": "Inception",
    "year": "2010",
    "source": "tmdb",
    "tmdb_id": "27205",
    "tmdb_tag": "{tmdb-27205}",
    "original_title": "Inception",
    "resolution": "1080p",
    "video_codec": "hevc",
    "hdr": "SDR",
    "bitrate": "15000",
    "container": "mkv",
    "audio_codec": "truehd",
    "channels": "7.1",
    "quality": "Premium",
    "score": "92",
    "series": "Inception",
    "season": "01",
    "episode": "01",
    "ep_title": "",
    "edition": "",
    "edition-tag": "",
}


# --- Construction du contexte --------------------------------------------


def build_naming_context(
    *,
    title: str = "",
    year: int = 0,
    source: str = "",
    tmdb_id: Optional[int] = None,
    original_title: str = "",
    probe_data: Optional[Dict[str, Any]] = None,
    quality_data: Optional[Dict[str, Any]] = None,
    tv_series_name: str = "",
    tv_season: int = 0,
    tv_episode: int = 0,
    tv_episode_title: str = "",
    edition: str = "",
) -> Dict[str, str]:
    """Construit le dictionnaire de variables pour le template de renommage."""
    ctx: Dict[str, str] = {}

    # Toujours disponibles
    ctx["title"] = str(title or "").strip()
    ctx["year"] = str(year) if year and year > 0 else ""
    ctx["source"] = str(source or "").strip()

    # TMDb
    ctx["tmdb_id"] = str(tmdb_id) if tmdb_id else ""
    ctx["tmdb_tag"] = f"{{tmdb-{tmdb_id}}}" if tmdb_id else ""
    ctx["original_title"] = str(original_title or "").strip()

    # Probe video
    probe = probe_data or {}
    video = probe.get("video") or {}
    ctx["resolution"] = _resolution_label(video)
    ctx["video_codec"] = _codec_label(video.get("codec"))
    ctx["hdr"] = _hdr_label(video)
    ctx["bitrate"] = str(video.get("bitrate") or "")
    ctx["container"] = str(probe.get("container") or "")

    # Probe audio (meilleure piste)
    audio_tracks = probe.get("audio_tracks") or []
    if audio_tracks:
        best = audio_tracks[0]
        ctx["audio_codec"] = _codec_label(best.get("codec"))
        channels = best.get("channels")
        ctx["channels"] = _channels_label(channels) if channels else ""
    else:
        ctx["audio_codec"] = ""
        ctx["channels"] = ""

    # Qualite
    qd = quality_data or {}
    ctx["quality"] = str(qd.get("tier") or "").strip()
    ctx["score"] = str(qd.get("score") or "") if qd.get("score") else ""

    # TV
    ctx["series"] = str(tv_series_name or title or "").strip()
    ctx["season"] = f"{tv_season:02d}" if tv_season and tv_season > 0 else ""
    ctx["episode"] = f"{tv_episode:02d}" if tv_episode and tv_episode > 0 else ""
    ctx["ep_title"] = str(tv_episode_title or "").strip()

    # Edition (Director's Cut, Extended, IMAX, etc.)
    ed = str(edition or "").strip()
    ctx["edition"] = ed
    ctx["edition-tag"] = f"{{edition-{ed}}}" if ed else ""

    return ctx


# --- Formatage ------------------------------------------------------------


def format_movie_folder(template: str, context: Dict[str, str]) -> str:
    """Formate un nom de dossier film a partir du template et du contexte."""
    tpl = template.strip() if template else _DEFAULT_MOVIE_TEMPLATE
    result = _apply_template(tpl, context)
    logger.debug("naming: template='%s' result='%s'", tpl, result)
    return result


def format_tv_series_folder(template: str, context: Dict[str, str]) -> str:
    """Formate un nom de dossier serie TV a partir du template et du contexte."""
    tpl = template.strip() if template else _DEFAULT_TV_TEMPLATE
    return _apply_template(tpl, context)


def _apply_template(template: str, context: Dict[str, str]) -> str:
    """Substitue les variables, nettoie les separateurs orphelins, sanitise pour Windows."""

    # Substituer les variables
    def _replacer(m: re.Match) -> str:
        var_name = m.group(1)
        return context.get(var_name, "")

    result = _VAR_RE.sub(_replacer, template)

    # Nettoyer les separateurs orphelins
    for pattern, replacement in _CLEANUP_PATTERNS:
        result = pattern.sub(replacement, result)

    result = result.strip()

    # Fallback si le resultat est vide
    if not result:
        fallback = context.get("title", "Film")
        year = context.get("year", "")
        result = f"{fallback} ({year})" if year else fallback

    return windows_safe(result)


# --- Validation -----------------------------------------------------------


def validate_template(template: str) -> Tuple[bool, List[str]]:
    """Valide un template de renommage. Retourne (valide, liste d'erreurs)."""
    errors: List[str] = []

    if not template or not template.strip():
        errors.append("Le template est vide.")
        return False, errors

    # Verifier que les accolades sont equilibrees
    depth = 0
    for ch in template:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            errors.append("Accolade fermante sans ouvrante.")
            break
    if depth > 0:
        errors.append("Accolade ouvrante sans fermante.")

    # Verifier que les variables sont connues
    for m in _VAR_RE.finditer(template):
        var_name = m.group(1)
        if var_name not in _KNOWN_VARS:
            errors.append(f"Variable inconnue : {{{var_name}}}")

    # Verifier qu'il y a au moins {title} ou {series}
    found_vars = set(_VAR_RE.findall(template))
    if not found_vars & {"title", "series"}:
        errors.append("Le template doit contenir au moins {title} ou {series}.")

    return len(errors) == 0, errors


def check_path_length(root: str, folder_name: str) -> Optional[str]:
    """Verifie si le path resultant depasse le seuil de warning. Retourne le message ou None."""
    full = f"{root}\\{folder_name}"
    if len(full) > _PATH_LENGTH_WARNING:
        return f"Chemin long ({len(full)} chars, seuil {_PATH_LENGTH_WARNING}) : {full[:80]}..."
    return None


def check_path_length_killswitch(target_path: str) -> Optional[str]:
    """VQ-3 : kill-switch MAX_PATH Windows.

    Retourne un message d'erreur (a logger + remonter via res.error_messages)
    si `target_path` depasse la limite historique Windows (MAX_PATH = 260).
    Retourne None si le path est exploitable.

    Backward compat : tout path <= 259 chars renvoie None (comportement
    identique a l'absence de check). Seuls les paths anormalement longs
    sont rejetes.

    Args:
        target_path: Chemin complet cible (str ou repr de Path).

    Returns:
        Message d'erreur explicite si > 259 chars, None sinon.
    """
    path_str = str(target_path)
    length = len(path_str)
    if length > _PATH_LENGTH_KILL_SWITCH:
        preview = path_str[:80] + "..." if length > 80 else path_str
        return (
            f"PATH_TOO_LONG : chemin cible {length} chars (max Windows "
            f"MAX_PATH = {_PATH_LENGTH_KILL_SWITCH + 1}), skip pour eviter "
            f"OSError obscur : {preview}"
        )
    return None


# --- Helpers prives -------------------------------------------------------


def _resolution_label(video: Dict[str, Any]) -> str:
    """Determine le label de resolution a partir des dimensions video.

    Hotfix2 2026-06-02 (SCAN-1 propagation) : utilise width+height (et non
    plus height seule) pour aligner sur quality_score._resolution_label.
    L'ancienne logique classait les films cinema 1920x800 (ratio 2.35:1) en
    720p alors que ce sont des 1080p natifs. Pattern coherent : width est le
    critere principal (1920 = 1080p toujours, peu importe l aspect ratio).
    """
    h = video.get("height")
    w = video.get("width")
    if not h and not w:
        return ""
    width = max(0, int(w or 0))
    height = max(0, int(h or 0))
    if width >= 3800 or height >= 2100:
        return "2160p"
    if width >= 1900 or height >= 1000:
        return "1080p"
    if width >= 1280 or height >= 680:
        return "720p"
    if height >= 480:
        return "480p"
    if height > 0:
        return f"{height}p"
    return ""


def _codec_label(codec: Any) -> str:
    """Normalise le label d'un codec."""
    c = str(codec or "").strip().lower()
    _MAP = {
        "h264": "x264",
        "avc": "x264",
        "h265": "hevc",
        "hevc": "hevc",
        "av1": "av1",
        "vp9": "vp9",
        "mpeg4": "xvid",
        "xvid": "xvid",
        "divx": "divx",
        "aac": "aac",
        "ac3": "ac3",
        "eac3": "eac3",
        "truehd": "truehd",
        "dts": "dts",
        "flac": "flac",
        "opus": "opus",
        "mp3": "mp3",
    }
    return _MAP.get(c, c)


def _hdr_label(video: Dict[str, Any]) -> str:
    """Determine le label HDR."""
    if video.get("hdr_dolby_vision"):
        return "DV"
    if video.get("hdr10_plus"):
        return "HDR10+"
    if video.get("hdr10"):
        return "HDR10"
    return "SDR"


def _channels_label(channels: Any) -> str:
    """Formate le nombre de canaux audio en label lisible.

    VN-F.1 : delegue a `codec_ranks.format_audio_channels` (sentinel `""`).
    """
    return _format_audio_channels(channels, invalid="")


# --- Conformance check ----------------------------------------------------


def folder_matches_template(
    folder_name: str,
    template: str,
    title: str,
    year: int,
) -> bool:
    """Verifie si un nom de dossier correspond au resultat attendu du template.

    Compare le nom normalise du dossier avec le resultat formate du template.
    Le template est applique avec un contexte minimal (title + year) puis
    compare au dossier via normalisation tokens.
    """
    if not folder_name or not title:
        return False

    ctx = build_naming_context(title=title, year=year)
    expected = format_movie_folder(template, ctx)

    # Comparaison normalisee (ignorer casse, espaces multiples)
    return _norm_compare(folder_name) == _norm_compare(expected)


def _norm_compare(s: str) -> str:
    """Normalise une chaine pour la comparaison de conformance.

    NFC-normalise puis casefold pour gerer correctement les equivalences
    Windows/SMB (case-only, NFC vs NFD, eszett allemand, ligatures).
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "").strip().casefold())
