"""Le NOM DE DOSSIER elisait la mauvaise piste audio — 4e site de « la meilleure piste ».

`naming._audio_track_sort_key` lisait le rang du codec par un lookup EXACT sur le
`codec` BRUT du probe (`AUDIO_CODEC_RANK.get(codec, 0)`). Or aucun backend ne
rend la forme canonique :

- ffprobe range le codec de BASE dans `codec` ('dts', 'truehd') et la VARIANTE
  dans des champs SEPARES (`profile`, `is_atmos`, `is_dts_x`) ;
- ffprobe ne rend jamais « pcm » nu, mais `pcm_s16le`, `pcm_s24le`, `pcm_bluray` ;
- MediaInfo rend son `Format` : 'AC-3', 'E-AC-3', 'PCM'.

Aucune de ces formes n'est une cle de `AUDIO_CODEC_RANK`, donc toutes retombaient
au rang **0** — c'est-a-dire SOUS l'AAC (1) et le MP3 (1). Une piste de
COMMENTAIRES en AAC 2.0 etait alors elue « meilleure piste » face a la piste
principale d'un remux, et c'est elle qui alimentait `{audio_codec}` et
`{channels}` dans le nom du DOSSIER — la seule chose que ce produit renomme.

C'est exactement le defaut R8-039 / ultra-audit 2026-08-03, deja corrige dans les
TROIS autres implementations de « la meilleure piste » du depot :
`quality_score._best_audio_track`, `duplicate_compare._best_audio`, puis
`audio_perceptual.select_best_audio_track` le 2026-08-31. Ce site-la est reste en
arriere parce qu'il est ne « self-contained » en PR#758, AVANT que la derivation
canonique n'existe — et la docstring de `audio_perceptual._track_codec_rank`
affirme pourtant noir sur blanc qu'il passe par elle.

Ce que ces tests verrouillent :
  - la piste principale d'un remux gagne sur une piste de commentaires, sur les
    formes que les backends produisent REELLEMENT ;
  - le contre-test : les cas deja corrects ne bougent pas (aucune redistribution
    de rang n'est introduite) ;
  - le CABLAGE reel, via `build_naming_context` — l'assertion porte sur
    `channels`, que SEULE la piste elue peut produire : un « 5.1 » ne peut pas
    venir d'une autre source du contexte.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from cinesort.domain.naming import _best_audio_track, build_naming_context

_AAC_COMMENTAIRES: Dict[str, Any] = {"codec": "aac", "channels": 2, "bitrate": 192_000, "language": "fra"}


def _probe(tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"video": {"height": 1080, "codec": "hevc"}, "audio_tracks": tracks, "container": "mkv"}


class LaPistePrincipaleGagneTests(unittest.TestCase):
    """Chaque forme brute qui retombait au rang 0, donc SOUS l'AAC."""

    def test_pcm_ffprobe_bat_une_aac_de_commentaires(self) -> None:
        for codec in ("pcm_s16le", "pcm_s24le", "pcm_bluray", "pcm_dvd"):
            with self.subTest(codec=codec):
                principale = {"codec": codec, "channels": 6, "bitrate": 6_912_000, "language": "eng"}
                elue = _best_audio_track([_AAC_COMMENTAIRES, principale])
                self.assertEqual(elue["codec"], codec)

    def test_les_formes_hyphenees_de_mediainfo_battent_une_aac(self) -> None:
        # `Format` MediaInfo, cf. infra/probe/_normalize_mediainfo.py.
        for codec in ("AC-3", "E-AC-3"):
            with self.subTest(codec=codec):
                principale = {"codec": codec, "channels": 6, "bitrate": 640_000, "language": "eng"}
                elue = _best_audio_track([_AAC_COMMENTAIRES, principale])
                self.assertEqual(elue["codec"], codec)

    def test_dts_hd_ma_passe_devant_une_piste_flac_secondaire(self) -> None:
        """La variante vit dans `profile` : sur le codec brut, 'dts' vaut 2, sous FLAC (3)."""
        principale = {"codec": "dts", "profile": "DTS-HD MA", "channels": 8, "bitrate": 4_000_000}
        flac_secondaire = {"codec": "flac", "channels": 2, "bitrate": 900_000}
        elue = _best_audio_track([flac_secondaire, principale])
        self.assertEqual(elue["codec"], "dts")


class LesCasDEJACorrectsNeBougentPasTests(unittest.TestCase):
    """Contre-test : le correctif ne redistribue AUCUN rang deja etabli."""

    def test_truehd_reste_devant_une_aac(self) -> None:
        truehd = {"codec": "truehd", "channels": 8, "bitrate": 4_500_000}
        self.assertEqual(_best_audio_track([_AAC_COMMENTAIRES, truehd])["codec"], "truehd")

    def test_une_aac_seule_reste_elue(self) -> None:
        self.assertEqual(_best_audio_track([_AAC_COMMENTAIRES])["codec"], "aac")

    def test_a_rang_egal_le_nombre_de_canaux_departage_toujours(self) -> None:
        stereo = {"codec": "ac3", "channels": 2, "bitrate": 192_000}
        multicanal = {"codec": "ac3", "channels": 6, "bitrate": 640_000}
        self.assertEqual(_best_audio_track([stereo, multicanal])["channels"], 6)

    def test_liste_vide(self) -> None:
        self.assertEqual(_best_audio_track([]), {})


class CablageDansLeNomDeDossierTests(unittest.TestCase):
    """Le site d'appel REEL : c'est le nom du dossier qui portait la valeur fausse."""

    def test_le_contexte_decrit_la_piste_principale_et_non_les_commentaires(self) -> None:
        remux = {"codec": "pcm_s24le", "channels": 6, "bitrate": 6_912_000, "language": "eng"}
        ctx = build_naming_context(title="Film", year=2020, probe_data=_probe([_AAC_COMMENTAIRES, remux]))
        # `channels` est l'assertion qui compte : « 5.1 » ne peut venir que de la
        # piste elue, alors que le libelle du codec pourrait etre satisfait par
        # une autre source du contexte.
        self.assertEqual(ctx["channels"], "5.1")
        self.assertEqual(ctx["audio_codec"], "pcm_s24le")

    def test_le_contexte_reste_juste_quand_la_piste_principale_est_deja_reconnue(self) -> None:
        """Contre-test du cablage : aucun deplacement sur un cas qui marchait."""
        ctx = build_naming_context(
            title="Film",
            year=2020,
            probe_data=_probe([_AAC_COMMENTAIRES, {"codec": "truehd", "channels": 8}]),
        )
        self.assertEqual(ctx["channels"], "7.1")
        self.assertEqual(ctx["audio_codec"], "truehd")


if __name__ == "__main__":
    unittest.main()
