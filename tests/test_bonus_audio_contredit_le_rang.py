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


if __name__ == "__main__":
    unittest.main()
