"""P4.2 : règles de scoring genre-aware.

Le scoring classique utilise des seuils de bitrate universels. En réalité,
les exigences diffèrent selon le genre :

- **Animation** : contenu graphique aux aplats et contours nets. Les artifacts
  de compression sont immédiatement visibles (banding, mosquito noise), mais
  le contenu se compresse bien (peu de grain, peu de textures complexes).
  Netflix vise "pristine" à 1.1 Mbps AV1 pour animation — seuil bitrate peut
  être plus bas sans perte perceptuelle majeure.

- **Action / Thriller** : beaucoup de mouvement, grain fréquent, scènes
  sombres détaillées. Demande un bitrate plus élevé pour préserver la
  fidélité. HDR très apprécié car rend les scènes sombres.

- **Documentary** : souvent du 720p acceptable (material d'archive), moins
  de pénalité sur résolution modeste.

- **Horror** : scènes sombres très fréquentes, HDR10 bit précieux.

- **Drama** : entre Action et Documentary, règles de base applicables.

Ce module fournit des règles pures qui, combinées au scoring classique,
produisent des bonus/malus contextuels. Le genre est dérivé des `tmdb_genres`
du film (liste fournie par TMDb, voir `_get_movie_detail_cached`).

Approche conservative : les ajustements sont modérés (3-6 points) pour ne
pas destabiliser le scoring global. Le but est de rendre le scoring plus
juste, pas de le bouleverser.

Sources consultées :
- Netflix AV1 streaming decoder (1.1 Mbps pristine animation)
- HEVC bitrate guide 4K (25-35 Mbps pristine live-action)
- AVS Forum min bitrate 4K indistinguishable from lossless
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# Mapping canonique genre TMDb → clé interne.
# Les genres TMDb sont en anglais ("Animation", "Action", "Thriller", ...).
_GENRE_CANONICAL: Dict[str, str] = {
    "animation": "animation",
    "action": "action",
    "thriller": "thriller",
    "horror": "horror",
    "documentary": "documentary",
    "comedy": "comedy",
    "drama": "drama",
    # Alias FR fréquents
    "animation ": "animation",
    "épouvante-horreur": "horror",
    "horreur": "horror",
    "documentaire": "documentary",
    "comédie": "comedy",
    "drame": "drama",
    "policier": "thriller",
}


# Règles par genre. Chaque règle est un dict :
#   bitrate_leniency : multiplicateur [0.7-1.2] appliqué aux seuils de bitrate
#                      (< 1.0 = plus tolérant, > 1.0 = plus strict).
#   modern_codec_bonus : bonus extra sur video_sub si codec moderne (HEVC/AV1).
#   hdr_bonus : bonus extra si HDR10 / HDR10+ / Dolby Vision.
#   atmos_bonus : bonus extra si audio Atmos/TrueHD.
#   grain_malus : malus sur grain détecté (négatif = pénalise le grain).
#   low_resolution_malus : malus sur résolution < 1080p (négatif).
_GENRE_RULES: Dict[str, Dict[str, float]] = {
    "animation": {
        "bitrate_leniency": 0.75,  # animation se compresse bien
        "modern_codec_bonus": 3.0,  # AV1/HEVC exceptionnellement adaptés
        "hdr_bonus": 0.0,
        "atmos_bonus": 0.0,
        "grain_malus": -5.0,  # grain parasite en animation
        "low_resolution_malus": -3.0,
    },
    "action": {
        "bitrate_leniency": 1.15,  # beaucoup de mouvement → plus de bitrate
        "modern_codec_bonus": 0.0,
        "hdr_bonus": 3.0,  # HDR très apprécié sur action
        "atmos_bonus": 3.0,
        "grain_malus": 0.0,
        "low_resolution_malus": -5.0,
    },
    "thriller": {
        "bitrate_leniency": 1.10,
        "modern_codec_bonus": 0.0,
        "hdr_bonus": 2.0,
        "atmos_bonus": 2.0,
        "grain_malus": 0.0,
        "low_resolution_malus": -4.0,
    },
    "horror": {
        "bitrate_leniency": 1.10,  # scènes sombres exigeantes
        "modern_codec_bonus": 0.0,
        "hdr_bonus": 4.0,  # HDR extrêmement précieux sur scènes sombres
        "atmos_bonus": 3.0,  # immersion audio majeure
        "grain_malus": 0.0,
        "low_resolution_malus": -4.0,
    },
    "documentary": {
        "bitrate_leniency": 0.90,  # souvent bas débit acceptable (archive)
        "modern_codec_bonus": 1.0,
        "hdr_bonus": 0.0,
        "atmos_bonus": 0.0,
        "grain_malus": 0.0,
        "low_resolution_malus": -1.0,  # tolérance sur 720p (archive)
    },
    "comedy": {
        "bitrate_leniency": 1.00,  # neutre
        "modern_codec_bonus": 0.0,
        "hdr_bonus": 0.0,
        "atmos_bonus": 1.0,
        "grain_malus": 0.0,
        "low_resolution_malus": -3.0,
    },
    "drama": {
        "bitrate_leniency": 1.05,
        "modern_codec_bonus": 0.0,
        "hdr_bonus": 2.0,  # drama bénéficie d'HDR (lumière naturelle)
        "atmos_bonus": 1.0,
        "grain_malus": 0.0,
        "low_resolution_malus": -3.0,
    },
}


def canonical_genre(genre: str) -> Optional[str]:
    """Retourne la clé canonique d'un genre TMDb, ou None si inconnu."""
    if not genre:
        return None
    key = str(genre).strip().lower()
    return _GENRE_CANONICAL.get(key)


def detect_primary_genre(tmdb_genres: Optional[List[str]]) -> Optional[str]:
    """Détecte le genre primaire depuis la liste TMDb.

    Stratégie : priorité aux genres les plus "différenciants" pour le scoring.
    Si plusieurs genres matchent, on préfère dans cet ordre :
    animation > horror > action > thriller > documentary > drama > comedy.
    """
    if not tmdb_genres:
        return None
    priority = ["animation", "horror", "action", "thriller", "documentary", "drama", "comedy"]
    canonical = {canonical_genre(g) for g in tmdb_genres if g}
    canonical.discard(None)
    for p in priority:
        if p in canonical:
            return p
    return None


def get_genre_rules(genre_key: Optional[str]) -> Optional[Dict[str, float]]:
    """Retourne les règles pour un genre canonique, ou None."""
    if not genre_key:
        return None
    return _GENRE_RULES.get(genre_key)


def compute_genre_adjustments(
    primary_genre: Optional[str],
    *,
    video_codec: str,
    height: int,
    has_hdr: bool,
    has_atmos: bool,
    has_heavy_grain: bool = False,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Calcule les ajustements de score liés au genre.

    Retourne (total_delta, factors_list). Les factors ont la même forme que
    dans quality_score.py : `{category, delta, label}` pour s'intégrer dans
    l'explain-score (P2.1).

    Args:
        primary_genre : clé canonique (animation, action, ...) ou None.
        video_codec : "hevc", "av1", "h264", ...
        height : résolution hauteur.
        has_hdr : True si HDR10/HDR10+/Dolby Vision détecté.
        has_atmos : True si audio Atmos/TrueHD détecté.
        has_heavy_grain : True si grain notable détecté (depuis perceptual).
    """
    rules = get_genre_rules(primary_genre)
    if not rules:
        return 0.0, []

    factors: List[Dict[str, Any]] = []
    total = 0.0

    codec_lc = (video_codec or "").lower()
    is_modern = codec_lc in ("hevc", "h265", "av1", "vp9")

    # Modern codec bonus (animation principalement)
    mcb = float(rules.get("modern_codec_bonus", 0.0) or 0.0)
    if mcb > 0 and is_modern:
        total += mcb
        factors.append(
            {
                "category": "video",
                "delta": int(mcb),
                "label": f"Genre '{primary_genre}' + codec moderne ({codec_lc.upper()})",
            }
        )

    # HDR bonus contextuel
    hdrb = float(rules.get("hdr_bonus", 0.0) or 0.0)
    if hdrb > 0 and has_hdr:
        total += hdrb
        factors.append(
            {
                "category": "video",
                "delta": int(hdrb),
                "label": f"Genre '{primary_genre}' + HDR (contexte apprécié)",
            }
        )

    # Atmos bonus
    atmosb = float(rules.get("atmos_bonus", 0.0) or 0.0)
    if atmosb > 0 and has_atmos:
        total += atmosb
        factors.append(
            {
                "category": "audio",
                "delta": int(atmosb),
                "label": f"Genre '{primary_genre}' + audio immersif",
            }
        )

    # Grain malus (animation pénalise le grain)
    gm = float(rules.get("grain_malus", 0.0) or 0.0)
    if gm < 0 and has_heavy_grain:
        total += gm
        factors.append(
            {
                "category": "video",
                "delta": int(gm),
                "label": f"Genre '{primary_genre}' + grain détecté (artefact probable)",
            }
        )

    # Low resolution malus contextuel
    lrm = float(rules.get("low_resolution_malus", 0.0) or 0.0)
    if lrm < 0 and height > 0 and height < 1080:
        total += lrm
        factors.append(
            {
                "category": "video",
                "delta": int(lrm),
                "label": f"Genre '{primary_genre}' + résolution modeste",
            }
        )

    return total, factors


def adjust_bitrate_threshold(base_threshold: int, primary_genre: Optional[str]) -> int:
    """Ajuste un seuil de bitrate selon le genre (animation plus tolérant, etc.).

    Retourne le seuil ajusté (arrondi à l'entier). Si genre inconnu → seuil inchangé.
    """
    rules = get_genre_rules(primary_genre)
    if not rules:
        return int(base_threshold)
    mult = float(rules.get("bitrate_leniency", 1.0) or 1.0)
    return int(round(base_threshold * mult))


__all__ = [
    "canonical_genre",
    "detect_primary_genre",
    "get_genre_rules",
    "compute_genre_adjustments",
    "adjust_bitrate_threshold",
]
