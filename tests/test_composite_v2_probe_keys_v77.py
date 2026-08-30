"""GATE AUDIT 2026-06-10 (REAL 2/2) — composite_score_v2 lit les BONNES cles du
probe normalise.

- _score_hdr lisait has_hdr10/has_dv/has_hdr10_plus alors que le probe expose
  hdr10/hdr_dolby_vision/hdr10_plus -> tout HDR10/DV score comme SDR (60/0.3).
- La regle fake-lossless lisait `audio` alors que la cle est `audio_tracks` ->
  has_lossless_codec toujours False, malus jamais applique.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cinesort.domain.perceptual.composite_score_v2 import (
    _score_hdr,
    apply_contextual_adjustments,
)
from cinesort.domain.perceptual.models import SubScore


class ScoreHdrKeysTests(unittest.TestCase):
    def _video(self):
        return SimpleNamespace(has_hdr10_plus_detected=False)

    def test_hdr10_scored_as_hdr_not_sdr(self) -> None:
        probe = {"video": {"hdr10": True, "max_cll": 1000, "max_fall": 400}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertGreaterEqual(value, 75.0, "HDR10 doit etre score HDR, pas SDR (60)")
        self.assertEqual(conf, 1.0)

    def test_dolby_vision_detected(self) -> None:
        probe = {"video": {"hdr_dolby_vision": True, "dv_profile": "5"}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertEqual(value, 80.0)  # DV5
        self.assertEqual(conf, 1.0)

    def test_sdr_still_neutral(self) -> None:
        probe = {"video": {"hdr10": False}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertEqual(value, 60.0)
        self.assertEqual(conf, 0.3)

    def test_old_keys_no_longer_trigger_hdr(self) -> None:
        # Les anciennes (mauvaises) cles ne doivent PLUS declencher HDR.
        probe = {"video": {"has_hdr10": True, "has_dv": True}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertEqual(value, 60.0)  # SDR car has_* ne sont pas les vraies cles


class FakeLosslessAudioTracksTests(unittest.TestCase):
    def _audio_subs(self):
        return [SubScore(name="spectral_cutoff", value=40.0, weight=1.0, confidence=1.0, label_fr="Coupe")]

    def test_fake_lossless_fires_with_audio_tracks_key(self) -> None:
        probe = {"audio_tracks": [{"codec": "flac"}]}
        _v, audio_out, _trace = apply_contextual_adjustments(
            [],
            self._audio_subs(),
            None,
            probe,
            None,
            None,
            [],
            False,
            "modern",
        )
        sub = next(s for s in audio_out if s.name == "spectral_cutoff")
        # Le malus fake-lossless a ete applique -> value < 40 (valeur initiale).
        self.assertLess(sub.value, 40.0, "malus fake-lossless non applique")

    def test_old_audio_key_no_longer_fires(self) -> None:
        # Avec l'ancienne cle `audio`, audio_tracks serait vide -> pas de malus.
        probe = {"audio": [{"codec": "flac"}]}
        _v, audio_out, _trace = apply_contextual_adjustments(
            [],
            self._audio_subs(),
            None,
            probe,
            None,
            None,
            [],
            False,
            "modern",
        )
        sub = next(s for s in audio_out if s.name == "spectral_cutoff")
        self.assertEqual(sub.value, 40.0, "pas de malus si la cle audio_tracks est absente")


class LeCodecEstLuSOUS_SA_FORME_BRUTETests(unittest.TestCase):
    """La regle fake-lossless comparait le codec BRUT a une liste de 4 chaines.

    `("flac", "truehd", "dts-hd ma", "mlp")`, en egalite EXACTE sur ce que rend
    ffprobe. Or ffprobe ne dit pas « pcm » : il dit `pcm_s24le`, `pcm_s16le`,
    `pcm_bluray`. Aucune de ces formes n'appartenait a la liste, donc le malus
    « fake lossless » ne pouvait PAS se declencher sur un remux PCM — le format
    ou il compte le plus, puisqu'un vrai PCM est enorme et un faux saute aux
    yeux au spectre.

    C'est la QUATRIEME table du depot qui encode « ce codec est-il sans perte »,
    et la seule a le faire par egalite sur la forme brute. `codec_ranks` porte
    deja un motif `("pcm", 3, "PCM")` avec le commentaire « couvre lpcm /
    pcm_s24le / pcm_bluray » : la connaissance existait, elle n'etait pas
    partagee.

    Meme famille que le defaut corrige juste au-dessus dans ce fichier — la
    fonction lisait la mauvaise CLE ; ici elle lit la bonne cle mais compare mal
    sa VALEUR.
    """

    def _audio_subs(self):
        return [SubScore(name="spectral_cutoff", value=40.0, weight=1.0, confidence=1.0, label_fr="Coupe")]

    def _malus_applique(self, codec: str) -> bool:
        _v, audio_out, _trace = apply_contextual_adjustments(
            [],
            self._audio_subs(),
            None,
            {"audio_tracks": [{"codec": codec}]},
            None,
            None,
            [],
            False,
            "modern",
        )
        return next(s for s in audio_out if s.name == "spectral_cutoff").value < 40.0

    def test_les_formes_reelles_de_pcm_declenchent_le_malus(self) -> None:
        for brut in ("pcm_s24le", "pcm_s16le", "pcm_bluray", "lpcm", "PCM"):
            with self.subTest(codec=brut):
                self.assertTrue(
                    self._malus_applique(brut),
                    f"{brut} est SANS PERTE et ffprobe l'ecrit ainsi : le malus doit mordre",
                )

    def test_un_codec_AVEC_PERTE_ne_declenche_rien(self) -> None:
        """Temoin. Sans lui, « corriger » pourrait vouloir dire mordre partout."""
        for brut in ("aac", "ac3", "eac3", "mp3", "opus"):
            with self.subTest(codec=brut):
                self.assertFalse(
                    self._malus_applique(brut),
                    f"{brut} est AVEC PERTE : un spectre coupe y est normal, pas suspect",
                )

    def test_les_formes_deja_couvertes_le_restent(self) -> None:
        """`mlp` en fait partie : l'ancienne liste le connaissait.

        `mlp` (Meridian Lossless Packing, le coeur du TrueHD) est un
        `codec_name` ffprobe a part entiere et n'a AUCUNE entree dans
        `AUDIO_CODEC_RANK_PATTERNS`. Le retirer en passant a la table aurait ete
        une regression silencieuse : il est traite explicitement.
        """
        for brut in ("flac", "truehd", "dts-hd ma", "mlp"):
            with self.subTest(codec=brut):
                self.assertTrue(self._malus_applique(brut))

    def test_atmos_est_tranche_par_son_PORTEUR_pas_par_son_nom(self) -> None:
        """Le mot « atmos » ne dit pas si le flux est sans perte.

        Porte par du TrueHD il l'est ; porte par de l'E-AC-3 (JOC, streaming) il
        ne l'est pas. La table des rangs place pourtant `atmos` en tete, ce qui
        aurait classe les deux pareil. On applique la regle qu'
        `audio_analysis._classify_codec` utilise deja : c'est le TrueHD qui
        decide.
        """
        self.assertTrue(self._malus_applique("truehd atmos"), "TrueHD Atmos est SANS PERTE")
        self.assertFalse(self._malus_applique("eac3 atmos"), "E-AC-3 Atmos (JOC) est AVEC PERTE")


if __name__ == "__main__":
    unittest.main()
