"""T-DOM-1 : la table des BONUS contredisait la table des RANGS.

Le depot porte plusieurs encodages de « ce codec est-il bon ». L'audit du
2026-08-19 en a aligne deux — `AUDIO_CODEC_RANK` et `AUDIO_CODEC_RANK_PATTERNS` —
en donnant enfin un rang a PCM/LPCM, qui tombaient a 0, soit SOUS l'AAC.

Une TROISIEME table est restee en dehors : `profile["audio_bonuses"]`, lue par
`_audio_codec_bonus`, qui alimente le score de qualite. Elle n'a aucune entree
pour FLAC ni PCM. Mesure du 2026-08-29, sur le meme film ou seul le codec audio
change :

    TrueHD 16 | DTS-HD MA 16 | DTS 14 | AAC 14 | AC3 13 | FLAC 13 | PCM 13

Deux formats SANS PERTE classes sous des formats AVEC PERTE — et sous l'AAC,
que le rang place deux crans plus bas.

Ce qui n'est PAS corrige ici, et pourquoi : EAC3 et AC3 (rang 2) recoivent aussi
un bonus inferieur a l'AAC (rang 1). Mais `codec_ranks` documente une divergence
DELIBEREE sur eac3 entre ses deux tables, et « AAC haut debit contre AC3 » est un
arbitrage produit, pas un defaut. On ne rebalance pas le score de toute une
bibliotheque sur une opinion. L'invariant ci-dessous est donc borne a ce qui est
non ambigu : un codec sans perte ne peut pas valoir moins qu'un codec avec perte.
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import (
    _audio_codec_bonus,
    _canonical_audio_codec,
    default_quality_profile,
)

#: Etiquettes canoniques SANS PERTE. Source : le commentaire de `codec_ranks`
#: (« DTS-HD MA, Master Audio, lossless » / « FLAC, l'autre lossless ») et
#: `release_name_parser._PATTERNS_AUDIO`, qui porte le flag explicitement.
LOSSLESS = ("truehd atmos", "truehd", "dts-hd ma", "dts:x", "flac", "pcm")

#: Etiquettes canoniques AVEC PERTE, y compris les pieges deja documentes :
#: DTS-HD HRA est lossy malgre son nom (#807), et Atmos porte par de l'E-AC-3
#: l'est aussi.
LOSSY = ("dts-hd hra", "dts", "eac3", "ac3", "aac", "mp3", "opus")


class UnLosslessNeVautJamaisMoinsQuUnLossyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prof = default_quality_profile()

    def _bonus(self, etiquette: str) -> int:
        return _audio_codec_bonus(etiquette, self.prof)[0]

    def test_aucun_lossless_ne_passe_sous_un_lossy(self) -> None:
        fautes = [
            f"{sans} ({self._bonus(sans):+d}) < {avec} ({self._bonus(avec):+d})"
            for sans in LOSSLESS
            for avec in LOSSY
            if self._bonus(sans) < self._bonus(avec)
        ]
        self.assertEqual(
            fautes,
            [],
            "la table des bonus contredit la hierarchie des codecs : " + " ; ".join(fautes),
        )

    def test_les_formes_brutes_de_pcm_aboutissent_au_meme_bonus(self) -> None:
        """LPCM, PCM, pcm_s24le : trois ecritures du meme codec.

        Sans ce test, corriger « pcm » laisserait « lpcm » a zero — exactement la
        forme que `_canonical_audio_codec` existe pour absorber.
        """
        attendu = self._bonus("pcm")
        self.assertGreater(attendu, 0, "le temoin lui-meme est a zero")
        for brut in ("LPCM", "PCM", "pcm_s24le", "lpcm"):
            with self.subTest(brut=brut):
                self.assertEqual(self._bonus(_canonical_audio_codec({"codec": brut})), attendu)

    def test_le_lossless_reste_SOUS_les_lossless_premium(self) -> None:
        """FLAC/PCM sont sans perte, mais pas du multicanal cinema.

        Les remonter au niveau de TrueHD/DTS-HD MA serait remplacer une erreur
        par une autre : le rang de `codec_ranks` les place a 3, entre DTS-HD MA
        (4) et DTS (2), et le bonus doit suivre ce meme ordre.
        """
        self.assertLess(self._bonus("flac"), self._bonus("dts-hd ma"))
        self.assertLess(self._bonus("pcm"), self._bonus("truehd"))
        self.assertGreater(self._bonus("flac"), self._bonus("dts"))


class LaCleOptionnelleEstVALIDEEComme_les_autresTests(unittest.TestCase):
    """`flac_pcm_bonus` est optionnelle, pas dispensee de validation.

    `validate_quality_profile` normalise `truehd_atmos_bonus`, `dts_hd_ma_bonus`,
    `dts_bonus` et `aac_bonus` — mais pas la nouvelle cle. Un profil utilisateur
    portant une valeur non numerique atteignait donc `int(lossless_simple)` et
    levait `ValueError` PENDANT le scoring, pas a la validation.

    La valeur de repli n'est pas 0 : ramener un lossless a zero violerait
    l'invariant que cette cle existe precisement pour tenir. On retombe sur le
    meme calcul que quand la cle est absente.

    Signale par une revue automatique sur la PR qui a introduit la cle, puis
    verifie : la liste de `validate_quality_profile` ne la contenait pas.
    """

    def test_une_valeur_non_numerique_ne_casse_pas_le_scoring(self) -> None:
        import copy

        from cinesort.domain.quality_score import compute_quality_score, validate_quality_profile

        brut = copy.deepcopy(default_quality_profile())
        brut["audio_bonuses"]["flac_pcm_bonus"] = "pas un nombre"
        ok, _erreurs, prof = validate_quality_profile(brut)
        self.assertTrue(ok, "le profil doit rester acceptable, pas etre rejete")
        self.assertIsInstance(
            prof["audio_bonuses"]["flac_pcm_bonus"],
            int,
            "la cle n'a pas ete normalisee : elle atteindra `int()` pendant le scoring",
        )

        sonde = {
            "width": 1920,
            "height": 1080,
            "video_codec": "h264",
            "bitrate": 10000,
            "duration": 7200,
            "audio_tracks": [{"codec": "flac", "channels": 6, "language": "fre", "bitrate": 1500}],
            "subtitle_tracks": [],
        }
        r = compute_quality_score(normalized_probe=sonde, profile=brut)
        self.assertIsInstance(r["score"], int)

    def test_le_repli_ne_ramene_pas_le_lossless_sous_le_lossy(self) -> None:
        """Normaliser vers 0 remplacerait le defaut par celui qu'on vient de fermer."""
        import copy

        from cinesort.domain.quality_score import validate_quality_profile

        brut = copy.deepcopy(default_quality_profile())
        brut["audio_bonuses"]["flac_pcm_bonus"] = "pas un nombre"
        _ok, _e, prof = validate_quality_profile(brut)
        self.assertGreater(
            _audio_codec_bonus("flac", prof)[0],
            _audio_codec_bonus("dts", prof)[0],
            "une valeur invalide a fait retomber le lossless sous le lossy",
        )


if __name__ == "__main__":
    unittest.main()
