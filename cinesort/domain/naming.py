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

from cinesort.domain.codec_ranks import AUDIO_CODEC_RANK as _AUDIO_CODEC_RANK
from cinesort.domain.codec_ranks import format_audio_channels as _format_audio_channels

# VQ-1 : import depuis path_utils (feuille) au lieu de core. Casse le cycle
# domain<->domain core -> duplicate_support -> (lazy) naming -> core.
# `cinesort.domain.core.windows_safe` reste un alias re-exporte pour backward
# compat avec les callers externes (apply_core, plan_support_*, etc.).
from cinesort.domain.path_utils import windows_safe

# --- B02-TAGS-BRACKETS : parsing des tags providers depuis input names -----
# Symetrique a `tmdb_tag` produit par build_naming_context (ligne ~191).
# Supporte les variantes Plex / Jellyfin / Radarr / TRaSH :
#   {tmdb-12345}, [tmdb-12345], [tmdbid-12345], {tmdb:12345}, {tmdb_12345}
#   [imdbid-tt1234567], {imdb-tt1234567}, [imdb:tt1234567]
# La regex tolere espaces internes et casse melangee.
#
# Fix ultra-audit 2026-08-31 (#9) : ce module portait la SEULE des trois copies
# qui tenait cette promesse d'espaces internes. Elle est desormais la seule tout
# court, hebergee par `scene_parser` (feuille du domaine, sans import interne).
from cinesort.domain.scene_parser import _PROVIDER_IMDB_TAG_RE, _PROVIDER_TMDB_TAG_RE

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
        # ITER7 etape 3 : variable opt-in alimentee par cfg.separator (UI).
        # Permet aux templates custom d'utiliser le selecteur "Separateur" sans
        # casser les templates existants qui n'y font pas reference.
        "sep",
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
    # F14 : le pattern historique `\s+-\s+(?=[\[\(])` supprimait le tiret meme
    # quand toutes les variables etaient PLEINES ("{title} - [{resolution}]" ->
    # "Inception [1080p]"), violant le template configure. Les groupes vides ont
    # deja ete retires par les patterns 1-3 : le seul indice restant d'une
    # variable videe est le RESIDU d'espace (double espace) qu'elle laisse. On
    # exige donc ce residu, d'un cote ou de l'autre du tiret. Ces deux patterns
    # doivent rester AVANT le collapse `\s{2,}` ci-dessous, qui ecraserait le
    # residu et les rendrait inoperants.
    (re.compile(r"\s+-\s{2,}(?=[\[\(])"), " "),  # variable videe APRES le tiret
    (re.compile(r"\s{2,}-\s+(?=[\[\(])"), " "),  # variable videe AVANT le tiret
    (re.compile(r"\s{2,}"), " "),  # espaces multiples
]

# --- Anti-mutilation : garde sur la deduplication d'annee de queue ---------
#
# Regle inviolable n2 : une heuristique qui PEUT amputer un titre doit etre
# ABANDONNEE, pas rafistolee.
#
# `title_helpers.strip_trailing_year_if_equal` retire l'annee de QUEUE d'un titre
# quand elle egale {year}, pour eviter "Le Havre 2011 (2011)". Sur un titre qui
# porte une PLAGE d'annees, la borne HAUTE de la plage est, textuellement, une
# annee de queue. Mesure sur un scan reel (dossier `Le.Parrain.Trilogie.1972-1990/`
# contenant 3 .mkv), avant ce garde-fou :
#     Le Parrain Trilogie 1972-1990 (1972)
#     Le Parrain Trilogie 1972-1990 (1974)
#     Le Parrain Trilogie 1972      (1990)   <- ampute, et INCOHERENT avec ses soeurs
# et l'apply DEPLACE : les 3 films de la meme trilogie finissaient dans 3 dossiers
# de noms differents, dont un FAUX ("Trilogie 1972"), avec errors=0.
#
# On ne cherche PAS a reconnaitre une plage : chaque separateur oublie rouvrirait
# le trou ('-', ' - ', en-dash, '/', parentheses...) — c'est exactement l'iteration
# que la regle interdit. On exige la preuve INVERSE, qui ne depend d'aucun
# separateur : le strip n'est autorise que si le titre ne contient qu'UN SEUL
# jeton d'annee (celui de queue), donc que sa suppression ne peut rien detruire
# d'autre que la redondance visee. Deux jetons ou plus -> ABSTENTION totale, le
# titre passe intact. Une redondance cosmetique ("Titre 1999 2001 (2001)") reste
# toujours preferable a une amputation.
#
# Effet de bord voulu : la garde ne depend que du TITRE, jamais de l'annee de la
# ligne. Deux lignes soeurs issues du meme dossier source, qui partagent donc le
# meme titre, sont desormais tranchees a l'identique.
_YEAR_TOKEN_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

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
    "sep": " ",
}


# --- Provider tags parsing (B02-TAGS-BRACKETS) ----------------------------


@dataclass(frozen=True)
class ProviderTags:
    """Tags providers extraits d'un nom de dossier/fichier.

    Tous les champs sont optionnels : `ProviderTags()` est l'absence de tag.
    `tmdb_id` est un int positif si trouve, `imdb_id` une chaine "ttXXXXXXX"
    lowercase.
    """

    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None

    @property
    def has_any(self) -> bool:
        """True si au moins un tag a ete extrait."""
        return self.tmdb_id is not None or self.imdb_id is not None


def extract_provider_tags(name: str) -> ProviderTags:
    """Extrait `{tmdb-XXX}` / `[imdbid-ttXXX]` depuis un nom de dossier/fichier.

    Symetrique a la sortie de `build_naming_context` (cle `tmdb_tag`).
    Supporte les variantes Plex / Jellyfin / Radarr / TRaSH.

    Args:
        name: Nom de dossier ou fichier (sans extension).

    Returns:
        ProviderTags(tmdb_id=..., imdb_id=...) ou ProviderTags() si rien trouve.
    """
    if not name:
        return ProviderTags()
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    m = _PROVIDER_TMDB_TAG_RE.search(name)
    if m:
        try:
            value = int(m.group(1))
            if value > 0:
                tmdb_id = value
        except (ValueError, TypeError):
            tmdb_id = None
    m = _PROVIDER_IMDB_TAG_RE.search(name)
    if m:
        imdb_id = m.group(1).lower()
    return ProviderTags(tmdb_id=tmdb_id, imdb_id=imdb_id)


def strip_provider_tags(name: str) -> str:
    """Retire les tags providers d'un nom pour le pipeline de nettoyage.

    A appeler AVANT `clean_title_guess` / `parse_scene_title` afin d'eviter
    que les chiffres TMDb (ex `27205`) ne polluent le titre extrait ou ne
    soient confondus avec une annee.

    Args:
        name: Nom brut (dossier ou fichier).

    Returns:
        Nom debarrasse des `{tmdb-...}` / `[imdbid-...]`, espaces normalises.
    """
    if not name:
        return name
    cleaned = _PROVIDER_TMDB_TAG_RE.sub(" ", name)
    cleaned = _PROVIDER_IMDB_TAG_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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
    separator: Optional[str] = None,
) -> Dict[str, str]:
    """Construit le dictionnaire de variables pour le template de renommage."""
    ctx: Dict[str, str] = {}

    # Toujours disponibles. NB : la déduplication de l'année de queue ("Titre 2005 (2005)")
    # est faite dans _apply_template, conditionnée à la présence de {year} dans le template
    # (un template custom SANS {year} conserve donc l'année du titre — pas de perte d'info).
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
        best = _best_audio_track(audio_tracks)
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

    # ITER7 etape 3 : variable opt-in {sep} approvisionnee depuis cfg.separator.
    # Coerce-and-default identique a Config.normalized()/_save_section_naming.
    # Templates existants ("{title} ({year})") ne referencent pas {sep} -> rendu
    # strictement inchange (STOP_FORK CUSTOM TEMPLATE preserve, voir
    # docs/internal/BILAN_ITER7_2026-06-08.md section 1.d). Cle absente ou
    # invalide -> defaut " " (espace) aligne sur le sentinel save UI.
    sep_value = str(separator) if separator is not None else " "
    if sep_value not in {".", " ", "_", "-"}:
        sep_value = " "
    ctx["sep"] = sep_value

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


def _dedupe_trailing_year(value: str, year: int) -> str:
    """Retire l'annee de queue redondante de *value*, mais SEULEMENT si c'est prouvablement sur.

    Garde anti-mutilation (cf. `_YEAR_TOKEN_RE`) : si *value* contient plus d'un
    jeton d'annee (`19xx`/`20xx`), l'annee de queue n'est plus prouvablement
    redondante — elle peut etre la borne haute d'une plage ("1972-1990",
    "1977 - 2019") ou une seconde annee signifiante. Dans ce cas on ABSTIENT :
    *value* est retourne intact, quitte a laisser une redondance cosmetique.

    Args:
        value: Titre/serie a dedupliquer (jamais un nom de fichier video).
        year: Annee que le template va reinjecter via `{year}`.

    Returns:
        *value* prive de son annee de queue si et seulement si cette annee est
        l'unique jeton d'annee du titre ET qu'elle egale *year* ; *value* intact
        dans tous les autres cas.
    """
    if len(_YEAR_TOKEN_RE.findall(value)) != 1:
        return value
    # Import tardif : casse le cycle domain<->domain (title_helpers <- core <- naming).
    from cinesort.domain.title_helpers import strip_trailing_year_if_equal

    return strip_trailing_year_if_equal(value, year)


def _apply_template(template: str, context: Dict[str, str]) -> str:
    """Substitue les variables, nettoie les separateurs orphelins, sanitise pour Windows."""

    # Fix double-année disque : si le template ré-injecte l'année via {year}, retirer l'année
    # de QUEUE redondante du titre/série (proposed_title issu d'un nom de fichier peut finir par
    # l'année, ex. "Le Havre 2011"). Sinon "{title} ({year})" produirait "Le Havre 2011 (2011)".
    # CONDITIONNÉ à "{year}" dans le template -> un template SANS {year} conserve l'année du titre
    # (pas de perte d'info). "Blade Runner 2049" (≠ année de sortie) et un titre-année nu ("1984")
    # sont préservés par le helper. Les titres portant une PLAGE d'années sont préservés par la
    # garde anti-mutilation de `_dedupe_trailing_year`. Copie locale : ne mute pas le contexte
    # de l'appelant.
    if "{year}" in (template or "") and context.get("year"):
        try:
            _yr = int(context["year"])
            context = dict(context)
            for _key in ("title", "series", "original_title"):
                if context.get(_key):
                    context[_key] = _dedupe_trailing_year(context[_key], _yr)
        except (TypeError, ValueError):
            pass

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


def check_path_length(root: str, folder_name: str, inner_name: str = "") -> Optional[str]:
    """Avertissement PREVENTIF : le chemin cible approche-t-il MAX_PATH ?

    Retourne le message, ou None si le chemin est confortable.

    Fix ultra-audit 2026-08-31 (#15). Deux defauts de la meme famille :

    1. **Le garde ne voyait pas ce que le kill-switch tue.** Il mesurait
       `root\\dossier` a 240 quand `check_path_length_killswitch` mesure le
       chemin cible COMPLET a 259. Or `windows_safe` tronque deja le nom de
       dossier a 180 : la longueur qui tue vient du nom de fichier INTERNE, que
       ce garde ne recevait pas. Mesure, root='D:\\Films', dossier de 180 chars,
       fichier interne de 74 chars -> kill-switch : PATH_TOO_LONG (260 chars) ;
       ce garde : None. Un seuil plus BAS qui ne peut pas se declencher avant
       le seuil plus HAUT n'est pas un garde, c'est un decor. `inner_name` rend
       les deux mesures comparables ; sans lui, le comportement est inchange.
    2. **Il n'avait AUCUN appelant de production** (`grep` : sa definition et
       deux fichiers de tests). Il est desormais appele par `apply_core`, sur
       le meme chemin candidat que le kill-switch, juste avant lui.
    """
    parts = [root, folder_name] + ([inner_name] if inner_name else [])
    full = "\\".join(parts)
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


def _audio_track_sort_key(track: Dict[str, Any]) -> Tuple[int, int, int]:
    codec = str(track.get("codec") or "").strip().lower()
    rank = _AUDIO_CODEC_RANK.get(codec, 0) if codec else 0

    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    return (rank, _as_int(track.get("channels")), _as_int(track.get("bitrate")))


def _best_audio_track(audio_tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Meilleure piste audio pour les placeholders {audio_codec}/{channels}.

    Aligne sur `quality_score._best_audio_track` (R8-039) : rang codec d'abord
    (lossless > lossy), puis canaux, puis bitrate. Avant, `audio_tracks[0]`
    prenait l'ordre du conteneur -> une piste lossy compatible pouvait etiqueter
    le fichier avec un codec inferieur a la vraie meilleure piste.
    """
    if not audio_tracks:
        return {}
    return max(audio_tracks, key=_audio_track_sort_key)


# --- Conformance check ----------------------------------------------------


def folder_matches_template(
    folder_name: str,
    template: str,
    title: str,
    year: int,
    *,
    edition: str = "",
    separator: Optional[str] = None,
) -> bool:
    """Verifie si un nom de dossier correspond au resultat attendu du template.

    Le contrat est : « ce dossier porte-t-il DEJA le nom que le renommage
    ecrirait ? ». La reponse doit donc etre calculee avec **exactement** la
    meme chaine de rendu que les ecrivains reels (`apply_core.apply_single` et
    son miroir `duplicate_support.planned_target_folder`), sinon la conformance
    diverge de l'apply et on propose des renommages sans effet.

    Ces ecrivains appellent `build_naming_context(title=, year=, edition=,
    separator=)` — ni probe, ni qualite, ni tmdb_id. Les placeholders
    `{resolution}`, `{video_codec}`, `{tmdb_tag}`, `{quality}`, `{score}`... ne
    sont donc JAMAIS alimentes sur le chemin de renommage (seul l'apercu des
    reglages, `cinesort_api`, leur passe un probe). Un dossier qui porte un de
    ces segments n'est pas conforme : l'apply lui retirerait. Les elargir ici
    (regex `.*` sur placeholder variable) rendrait la conformance PLUS permissive
    que l'ecrivain et casserait l'invariant « planned == apply par construction »
    (cf. `duplicate_support.planned_target_folder`). Cf. #469.

    `edition` et `separator`, eux, SONT alimentes par les ecrivains : sans eux un
    dossier « Titre (Annee) {edition-Director's Cut} » produit par l'apply etait
    juge non conforme a son propre template.

    Args:
        folder_name: nom de dossier existant sur disque.
        template: `cfg.naming_movie_template`.
        title / year: identite retenue pour ce film.
        edition: edition detectee (`row.edition`), telle que passee a l'apply.
        separator: `cfg.separator`, tel que passe a l'apply (None -> defaut " ").
    """
    if not folder_name or not title:
        return False

    ctx = build_naming_context(title=title, year=year, edition=edition or "", separator=separator)
    expected = format_movie_folder(template, ctx)

    # Comparaison normalisee (ignorer casse, espaces multiples)
    return _norm_compare(folder_name) == _norm_compare(expected)


def _norm_compare(s: str) -> str:
    """Normalise une chaine pour la comparaison de conformance.

    NFC-normalise puis casefold pour gerer correctement les equivalences
    Windows/SMB (case-only, NFC vs NFD, eszett allemand, ligatures).
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "").strip().casefold())
