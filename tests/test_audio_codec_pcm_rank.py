"""Regression — audit 2026-08-19 : le codec PCM / LPCM n'etait classe NULLE PART.

`codec_ranks` porte les deux tables de rang audio du depot :

- `AUDIO_CODEC_RANK` (lookup EXACT) alimente `quality_score._audio_codec_rank`
  et `duplicate_compare._audio_codec_rank_value` ;
- `AUDIO_CODEC_RANK_PATTERNS` (substring) alimente
  `audio_analysis._classify_codec` et `audio_perceptual.select_best_audio_track`.

Aucune des deux n'avait d'entree PCM. Toute piste PCM tombait donc au rang **0**,
c'est-a-dire SOUS le MP3 et l'AAC (rang 1), avec trois consequences mesurables :

1. `_best_audio_track` / `_best_audio` elisaient une piste AAC secondaire comme
   « meilleure piste » face a la piste LPCM principale d'un remux ;
2. le critere « Audio codec » du comparateur de doublons (poids 15) etait perdu
   par le fichier PCM face a n'importe quel AAC, avec le libelle « ? » — or ce
   comparateur designe le gagnant que « Auto-decider tous » archive ;
3. le badge audio retombait sur `_TIER_MAP[0]`, soit « bronze ».

C'est la signature EXACTE de deux correctifs deja passes sur ces memes tables :
les etiquettes composees de l'ultra-audit 2026-08-03 (`truehd atmos`, `dts:x`) et
les formes hyphenees de la revue PR#854 (`ac-3`, `e-ac-3`), qui « retombaient a 0,
soit SOUS l'AAC ». PCM est le cas restant.

Et le depot le contredisait lui-meme : `release_name_parser._PATTERNS_AUDIO`
declare `("pcm", lossless=True)` et `quality_score._NAME_AUDIO_CODEC_TO_PROBE`
mappe `"pcm" -> "pcm"`. Le fallback par le NOM fabriquait donc une etiquette
qu'aucune table ne savait lire.

Le rang 3 retenu n'est pas un arbitrage nouveau : c'est celui de FLAC, l'autre
lossless de ces tables.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict

from cinesort.domain.audio_analysis import _classify_codec, analyze_audio
from cinesort.domain.codec_ranks import AUDIO_CODEC_RANK
from cinesort.domain.duplicate_compare import compare_by_criteria
from cinesort.domain.quality_score import (
    _audio_codec_rank,
    _best_audio_track,
    _canonical_audio_codec,
)

# Variantes reellement rendues par les backends probe du depot :
# - ffprobe ne rend JAMAIS "pcm" nu, mais une variante par format d'echantillon ;
# - MediaInfo rend le `Format` "PCM" (cf. infra/probe/_normalize_mediainfo.py) ;
# - le fallback par le nom de release synthetise "pcm".
_PCM_CODECS = ("pcm_s16le", "pcm_s24le", "pcm_bluray", "pcm_dvd", "PCM", "pcm", "lpcm")


def _video(bitrate: int = 20_000_000) -> Dict[str, Any]:
    return {"height": 1080, "width": 1920, "codec": "h264", "bitrate": bitrate}


class CanonicalPcmLabelTests(unittest.TestCase):
    def test_toutes_les_formes_pcm_donnent_une_etiquette_unique(self) -> None:
        for codec in _PCM_CODECS:
            with self.subTest(codec=codec):
                self.assertEqual(_canonical_audio_codec({"codec": codec}), "pcm")

    def test_la_derivation_reste_idempotente(self) -> None:
        self.assertEqual(_canonical_audio_codec({"codec": _canonical_audio_codec({"codec": "pcm_s24le"})}), "pcm")

    def test_pcm_est_une_cle_exacte_de_la_table_de_rang(self) -> None:
        # Le lookup de `_audio_codec_rank` / `_audio_codec_rank_value` est EXACT :
        # sans cette cle, l'etiquette canonique retombe a 0 via le `.get(..., 0)`.
        self.assertEqual(AUDIO_CODEC_RANK.get("pcm"), 3)


class PcmRankTests(unittest.TestCase):
    def test_le_rang_pcm_est_celui_du_lossless_pas_zero(self) -> None:
        for codec in _PCM_CODECS:
            with self.subTest(codec=codec):
                self.assertEqual(_audio_codec_rank({"codec": codec, "channels": 6}), 3)

    def test_pcm_passe_devant_aac_et_mp3(self) -> None:
        pcm = _audio_codec_rank({"codec": "pcm_s24le", "channels": 6})
        self.assertGreater(pcm, _audio_codec_rank({"codec": "aac", "channels": 2}))
        self.assertGreater(pcm, _audio_codec_rank({"codec": "mp3", "channels": 2}))

    def test_les_autres_rangs_ne_bougent_pas(self) -> None:
        """Contre-test : le correctif ne redistribue aucun autre codec."""
        self.assertEqual(_audio_codec_rank({"codec": "truehd", "channels": 8}), 5)
        self.assertEqual(_audio_codec_rank({"codec": "flac", "channels": 2}), 3)
        self.assertEqual(_audio_codec_rank({"codec": "ac3", "channels": 6}), 2)
        self.assertEqual(_audio_codec_rank({"codec": "aac", "channels": 2}), 1)
        self.assertEqual(_audio_codec_rank({"codec": "dts", "profile": "DTS", "channels": 6}), 2)


class BestTrackTests(unittest.TestCase):
    def test_la_piste_lpcm_est_elue_devant_une_piste_aac_secondaire(self) -> None:
        lpcm = {"codec": "pcm_s24le", "channels": 6, "bitrate": 6_912_000, "language": "eng"}
        aac = {"codec": "aac", "channels": 2, "bitrate": 192_000, "language": "fra"}
        self.assertEqual(_best_audio_track([aac, lpcm])["codec"], "pcm_s24le")


class DuplicateComparatorTests(unittest.TestCase):
    def test_le_remux_lpcm_ne_perd_plus_le_critere_audio_face_a_un_aac(self) -> None:
        remux = {"video": _video(), "audio_tracks": [{"codec": "pcm_s24le", "channels": 6}]}
        webdl = {"video": _video(9_000_000), "audio_tracks": [{"codec": "aac", "channels": 2}]}
        crit = next(c for c in compare_by_criteria(remux, webdl) if c.name == "audio_codec")
        self.assertEqual(crit.winner, "a")

    def test_le_critere_reste_perdu_par_un_aac_face_a_un_flac(self) -> None:
        """Contre-test : le verdict vient bien du rang, pas d'un effet de bord."""
        flac = {"video": _video(), "audio_tracks": [{"codec": "flac", "channels": 6}]}
        webdl = {"video": _video(9_000_000), "audio_tracks": [{"codec": "aac", "channels": 2}]}
        crit = next(c for c in compare_by_criteria(flac, webdl) if c.name == "audio_codec")
        self.assertEqual(crit.winner, "a")


class BadgeAudioTests(unittest.TestCase):
    def test_le_badge_pcm_n_est_plus_inconnu_bronze(self) -> None:
        rank, label = _classify_codec("pcm_s24le", "")
        self.assertEqual((rank, label), (3, "PCM"))

    def test_le_tier_du_badge_suit_le_rang(self) -> None:
        report = analyze_audio([{"codec": "pcm_bluray", "channels": 6, "language": "eng"}])
        # `badge_tier` est le SEUL champ que cette assertion vise : `best_format`
        # est verifie a part pour qu'aucune des deux ne puisse etre satisfaite par
        # l'autre source (le libelle vient de la table, le tier de `_TIER_MAP`).
        self.assertEqual(report["badge_tier"], "gold")
        self.assertEqual(report["best_format"], "PCM")


if __name__ == "__main__":
    unittest.main()
