# -*- coding: utf-8 -*-
"""Corpus FIGE du moteur perceptuel, et le verdict qu'il en tire.

Separe du test pour une raison : l'outil qui RECALCULE les empreintes doit
importer exactement le meme corpus que celui qui les VERIFIE. Deux copies
divergeraient, et la divergence rendrait une empreinte fausse sans bruit.

Aucune valeur ici ne vient d'un fichier reel : ce sont des mesures inventees,
choisies pour franchir des seuils. Aucun tirage aleatoire non plus — une
empreinte ne peut pas dependre d'une graine.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from cinesort.domain.perceptual.audio_perceptual import _compute_audio_score, classify_drc
from cinesort.domain.perceptual.composite_score import build_perceptual_result
from cinesort.domain.perceptual.composite_score_v2 import compute_global_score_v2
from cinesort.domain.perceptual.mel_analysis import (
    _score_from_aac_holes,
    _score_from_flatness,
    _score_from_mp3_shelf,
    _score_from_soft_clip,
    detect_aac_holes,
)
from cinesort.domain.perceptual.models import AudioPerceptual, GrainAnalysis, VideoPerceptual

_V = dict(frames_analyzed=10, variance_mean=400.0, temporal_stddev=6.0)

#: `track_index=0` est OBLIGATOIRE sur chaque piste. `compute_audio_score` rend
#: `None` des que `track_index < 0`, et le defaut du champ est -1 : une premiere
#: version de ce corpus mesurait donc `audio_score = 0` sur les DIX cas, et
#: `global == visual` partout. L'empreinte aurait ete figee sur une constante.
#: C'est ce qui a motive `test_chaque_surface_VARIE`.
CAS_COMPOSITE_V1: Dict[str, Tuple[Any, Any, Any, Any]] = {
    "mastering_reference": (
        dict(
            _V,
            resolution_width=3840,
            resolution_height=2160,
            bit_depth_nominal=10,
            blockiness_mean=2.0,
            blur_mean=0.01,
            banding_mean=1.0,
            effective_bits_mean=9.8,
        ),
        None,
        dict(track_index=0, audio_score=88, track_codec="dts", track_channels=8, loudness_range=14.0),
        None,
    ),
    "faux_4k": (
        dict(
            _V,
            resolution_width=3840,
            resolution_height=2160,
            bit_depth_nominal=8,
            blockiness_mean=20.0,
            blur_mean=0.30,
            banding_mean=8.0,
            effective_bits_mean=6.0,
        ),
        None,
        dict(track_index=0, audio_score=55, track_codec="aac", track_channels=2, loudness_range=8.0),
        None,
    ),
    "dnr_upscale": (
        dict(
            _V,
            resolution_width=3840,
            resolution_height=2160,
            bit_depth_nominal=8,
            blockiness_mean=15.0,
            blur_mean=0.35,
            banding_mean=9.0,
            effective_bits_mean=7.0,
        ),
        None,
        dict(track_index=0, audio_score=60, track_codec="aac", track_channels=6, loudness_range=11.0),
        ["upscale_suspect"],
    ),
    "recompression_destructrice": (
        dict(
            _V,
            resolution_width=1920,
            resolution_height=1080,
            bit_depth_nominal=8,
            blockiness_mean=55.0,
            blur_mean=0.10,
            banding_mean=30.0,
            effective_bits_mean=7.0,
        ),
        None,
        dict(track_index=0, audio_score=42, track_codec="aac", track_channels=2, loudness_range=6.0),
        None,
    ),
    "audio_ecrase_streaming": (
        dict(
            _V,
            resolution_width=1920,
            resolution_height=1080,
            bit_depth_nominal=8,
            blockiness_mean=30.0,
            blur_mean=0.08,
            banding_mean=18.0,
            effective_bits_mean=7.5,
        ),
        None,
        dict(track_index=0, audio_score=35, track_codec="aac", track_channels=6, loudness_range=4.0),
        None,
    ),
    "banding_10bit": (
        dict(
            _V,
            resolution_width=1920,
            resolution_height=1080,
            bit_depth_nominal=10,
            blockiness_mean=10.0,
            blur_mean=0.05,
            banding_mean=25.0,
            effective_bits_mean=9.2,
        ),
        None,
        dict(track_index=0, audio_score=72, track_codec="eac3", track_channels=6, loudness_range=12.0),
        None,
    ),
    "dnr_film_classique": (
        dict(
            _V,
            resolution_width=1920,
            resolution_height=1080,
            bit_depth_nominal=8,
            blockiness_mean=8.0,
            blur_mean=0.40,
            banding_mean=6.0,
            effective_bits_mean=7.8,
        ),
        dict(grain_level=0.5, tmdb_year=1975, film_era="classic"),
        dict(track_index=0, audio_score=80, track_codec="flac", track_channels=2, loudness_range=15.0),
        None,
    ),
    "bruit_numerique_recent": (
        dict(
            _V,
            resolution_width=3840,
            resolution_height=2160,
            bit_depth_nominal=10,
            blockiness_mean=5.0,
            blur_mean=0.03,
            banding_mean=3.0,
            effective_bits_mean=9.5,
            temporal_stddev=12.0,
        ),
        dict(grain_level=9.0, tmdb_year=2021),
        dict(track_index=0, audio_score=90, track_codec="truehd", track_channels=8, loudness_range=20.0),
        None,
    ),
    "sans_audio": (
        dict(
            _V,
            resolution_width=1280,
            resolution_height=720,
            bit_depth_nominal=8,
            blockiness_mean=18.0,
            blur_mean=0.12,
            banding_mean=10.0,
            effective_bits_mean=7.2,
        ),
        None,
        None,
        None,
    ),
    #: CAS LIMITE, pas un scenario realiste. `BLUR_THRESHOLD_FAKE_4K` vaut 0.05 ;
    #: ce cas est a 0.12, donc au-dessus. Les autres cas 4K sont a 0.30 et 0.35 :
    #: un seuil deplace jusqu'a 0.28 les laissait TOUS du meme cote, et la
    #: mutation passait inapercue. Un seuil ne se garde qu'avec une valeur posee
    #: juste au-dessus de lui.
    "faux_4k_LIMITE_de_flou": (
        dict(
            _V,
            resolution_width=3840,
            resolution_height=2160,
            bit_depth_nominal=8,
            blockiness_mean=12.0,
            blur_mean=0.12,
            banding_mean=7.0,
            effective_bits_mean=6.5,
        ),
        None,
        dict(track_index=0, audio_score=58, track_codec="aac", track_channels=6, loudness_range=10.0),
        None,
    ),
    "sans_video": (None, None, dict(track_index=0, audio_score=65, track_codec="aac", track_channels=2), None),
}

#: Les DIX verdicts croises de `detect_cross_verdicts`. Le corpus doit tous les
#: produire : sans cette exigence, quelqu'un pourrait vider CAS_COMPOSITE_V1 de
#: la moitie de ses cas, recopier la nouvelle empreinte, et le cliquet
#: continuerait de passer pour complet.
VERDICTS_CROISES_ATTENDUS = frozenset(
    {
        "dnr_upscale_combo",
        "fake_4k",
        "lossy_recompress",
        "excellent_mastering",
        "audio_crushed",
        "streaming_source",
        "8bit_insufficient",
        "banding_10bit",
        "dnr_classic_film",
        "noise_digital",
    }
)

#: `classify_drc` porte la regle #752 du bump 1.1 : quand UNE SEULE des deux
#: metriques est disponible, la confiance est plafonnee. Les deux cas
#: `*_SEUL*` sont la pour ca, et l'empreinte les fige.
CAS_DRC: Dict[str, Tuple[Any, Any]] = {
    "les_deux_mesurees_cinema": (18.0, 16.0),
    "les_deux_mesurees_compresse": (7.0, 3.0),
    "les_deux_mesurees_standard": (12.0, 9.0),
    "crest_SEUL_752": (7.0, None),
    "lra_SEULE_752": (None, 3.0),
    "aucune_mesuree": (None, None),
}

CAS_AUDIO_SCORE: Dict[str, Tuple[Any, Any, Any, Any]] = {
    "complet_bon": (
        dict(lra=14.0, integrated=-24.0),
        dict(noise_floor=-70.0, dynamic_range=18.0, crest_factor=16.0),
        dict(clipping_pct=0.0),
        dict(mel_score=85),
    ),
    "complet_mauvais": (
        dict(lra=3.0, integrated=-9.0),
        dict(noise_floor=-40.0, dynamic_range=5.0, crest_factor=6.0),
        dict(clipping_pct=4.0),
        dict(mel_score=30),
    ),
    "sans_mel": (
        dict(lra=10.0, integrated=-18.0),
        dict(noise_floor=-60.0, dynamic_range=11.0, crest_factor=11.0),
        dict(clipping_pct=0.5),
        None,
    ),
    "tout_absent": (None, None, None, None),
}

CAS_AAC_SCORE = {
    "sain": dict(hole_ratio=0.0),
    "warn": dict(hole_ratio=0.15),
    "severe": dict(hole_ratio=0.45),
    "extreme": dict(hole_ratio=0.90),
}
CAS_SOFT_CLIP = {"aucun": dict(soft_clip_pct=0.0), "moyen": dict(soft_clip_pct=2.0), "fort": dict(soft_clip_pct=12.0)}
CAS_MP3_SHELF = {"absent": dict(shelf_detected=False), "present": dict(shelf_detected=True, cutoff_hz=16000.0)}
CAS_FLATNESS = {"tres_plat": 0.02, "median": 0.25, "tres_riche": 0.8}

#: (bandes muettes, bandes constantes-mais-fortes) du spectrogramme synthetique.
#: C'est ce qui exerce `MEL_AAC_HOLE_THRESHOLD_DB`, la premiere raison citee par
#: le bump 1.0 -> 1.1 (#660) : le seuil (-70 dB) doit rester strictement au-dessus
#: du plancher de `mel_to_db` (-80 dB), sans quoi aucune bande ne peut jamais
#: etre comptee.
#: (bandes muettes, bandes constantes, bandes LIMITES).
CAS_AAC_DETECTION: Dict[str, Tuple[int, int, int]] = {
    "aucun_trou": (0, 0, 0),
    "quelques_trous": (4, 0, 0),
    "au_dela_du_seuil_severe": (12, 0, 0),
    "presque_tout_muet": (60, 0, 0),
    "synthetique_SANS_trou": (0, 20, 0),
    "trous_ET_synthetique": (8, 16, 0),
    "bandes_LIMITES_seules": (0, 0, 6),
    "limites_ET_trous": (4, 0, 6),
}

#: Niveau des bandes « limites », choisi ENTRE deux valeurs plausibles du seuil.
#: Le seuil vaut -70 dB ; une bande a -68 dB est AU-DESSUS (pas un trou). Si
#: quelqu'un le remonte a -65, elle passe EN DESSOUS et devient un trou.
#:
#: Sans ces bandes, le corpus n'avait que des extremes — actives a ~-20 dB,
#: muettes a -90 dB — et une mutation du seuil de -70 a -65 laissait les SIX
#: tests VERTS. Le cliquet pretendait couvrir #660 sans pouvoir detecter un
#: deplacement de sa frontiere. C'est la mutation qui l'a dit, pas la relecture.
_DB_BANDE_LIMITE = -68.0


def _mel_synthetique(
    trous: int,
    constantes: int,
    limites: int = 0,
    bandes: int = 64,
    trames: int = 40,
) -> Tuple[np.ndarray, np.ndarray]:
    """Spectrogramme mel DETERMINISTE, oriente `(trames, bandes)`.

    `detect_aac_holes` fait `mel_spec_db[:, valid_idx].mean(axis=0)` : l'axe 0
    est le TEMPS, l'axe 1 les bandes. Une premiere version de ce corpus les
    avait inverses, et l'erreur a ete visible (IndexError) — contrairement a la
    suivante, qui ne l'etait pas : toutes les bandes y etaient constantes dans
    le temps, donc de variance nulle, donc `synthetic_ratio` valait 1.0 sur tous
    les cas. Une surface figee sur une constante ne fige rien.

    Quatre populations de bandes :
      - actives   : fortes et modulees dans le temps (ni trou, ni synthetique) ;
      - constantes: fortes mais figees (synthetiques, PAS des trous) ;
      - LIMITES   : posees a `_DB_BANDE_LIMITE`, de part et d'autre desquelles
                    un deplacement du seuil change le verdict ;
      - muettes   : -90 dB, franchement sous le seuil (trous ET synthetiques).

    Aucun `np.random` : une empreinte ne peut pas dependre d'une graine.
    """
    spec = np.zeros((trames, bandes), dtype=np.float64)
    for bande in range(bandes):
        spec[:, bande] = -20.0 + (bande % 5) * 0.5
    for trame in range(trames):
        spec[trame, : bandes - constantes - limites - trous] += (trame % 7) * 0.3
    if limites:
        debut = bandes - trous - limites
        spec[:, debut : debut + limites] = _DB_BANDE_LIMITE
    if trous:
        spec[:, bandes - trous :] = -90.0
    freqs = np.linspace(20.0, 20000.0, bandes)
    return spec, freqs


def verdicts() -> Dict[str, Dict[str, Any]]:
    """Le verdict de CHAQUE surface, sous une forme canonique et stable.

    Ni `ts` ni `analysis_duration_total_s` n'y figurent : ils dependent de
    l'horloge, et une empreinte qui bouge a chaque execution ne fige rien.
    """
    out: Dict[str, Dict[str, Any]] = {}

    composite_v1: Dict[str, Any] = {}
    for nom, (video, grain, audio, enc) in CAS_COMPOSITE_V1.items():
        resultat = build_perceptual_result(
            VideoPerceptual(**video) if video else None,
            GrainAnalysis(**grain) if grain else None,
            AudioPerceptual(**audio) if audio else None,
            encode_warnings=enc,
        )
        composite_v1[nom] = {
            "visual": resultat.visual_score,
            "audio": resultat.audio_score,
            "global": resultat.global_score,
            "tier": resultat.global_tier,
            "verdicts": sorted(item["id"] for item in resultat.cross_verdicts),
        }
    out["composite_v1"] = composite_v1

    out["drc"] = {nom: list(classify_drc(crest, lra)) for nom, (crest, lra) in CAS_DRC.items()}

    out["audio_score"] = {
        nom: _compute_audio_score(loud, astats, clip, mel) for nom, (loud, astats, clip, mel) in CAS_AUDIO_SCORE.items()
    }

    out["mel_scores"] = {
        **{f"aac:{k}": _score_from_aac_holes(v) for k, v in CAS_AAC_SCORE.items()},
        **{f"softclip:{k}": _score_from_soft_clip(v) for k, v in CAS_SOFT_CLIP.items()},
        **{f"mp3shelf:{k}": _score_from_mp3_shelf(v) for k, v in CAS_MP3_SHELF.items()},
        **{f"flatness:{k}": _score_from_flatness(v) for k, v in CAS_FLATNESS.items()},
    }

    detection: Dict[str, Any] = {}
    for nom, (trous, constantes, limites) in CAS_AAC_DETECTION.items():
        spec, freqs = _mel_synthetique(trous, constantes, limites)
        mesure = detect_aac_holes(spec, freqs)
        detection[nom] = {
            "hole_ratio": round(float(mesure["hole_ratio"]), 6),
            "synthetic_ratio": round(float(mesure["synthetic_ratio"]), 6),
            "verdict": mesure["verdict"],
        }
    out["aac_holes"] = detection

    composite_v2: Dict[str, Any] = {}
    for nom, (video, grain, audio, _enc) in CAS_COMPOSITE_V1.items():
        resultat = compute_global_score_v2(
            video_perceptual=VideoPerceptual(**video) if video else None,
            audio_perceptual=AudioPerceptual(**audio) if audio else None,
            grain_analysis=GrainAnalysis(**grain) if grain else None,
            normalized_probe={},
            duration_s=7200.0,
        )
        composite_v2[nom] = {"score": round(float(resultat.global_score), 4), "tier": resultat.global_tier}
    out["composite_v2"] = composite_v2

    return out
