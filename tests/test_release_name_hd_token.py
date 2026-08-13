"""Le « HD » de `DTS-HD` n'est pas une resolution.

POURQUOI CE FICHIER EXISTE. Le motif de resolution 720p acceptait `\\bHD\\b(?!R)`.
Un tiret est une frontiere de mot : dans `DTS-HD.MA`, le `HD` est donc encadre de
deux frontieres, et le lookahead `(?!R)` ne le rejette pas (le caractere suivant
est un point). Toute release SANS token de resolution mais avec une piste
`DTS-HD*` — ou un `HD-DVD` — ressortait donc en `resolution_hint="720p"`,
`1280x720`, valeurs entierement INVENTEES :

    Heat.1995.REMUX.BluRay.DTS-HD.MA.5.1-FraMeSToR.mkv  ->  720p  1280x720

Consequence mesuree, sur un probe sans dimensions (PARTIAL), la ligne
d'explication du score annoncait :

    « +0 Specs deduites du nom de release: width, height, audio_track_synth »

alors que le nom ne porte AUCUNE indication de resolution. Le score lui-meme
n'etait pas fausse — `_resolution_label` a ses propres motifs, stricts — mais
l'explication affirmait au sujet du fichier quelque chose de faux.

CE QUE CES TESTS EPROUVENT. Que le token `HD` isole reste reconnu (c'est un
marqueur 720p historique legitime), et qu'il ne l'est plus des qu'il est colle a
un tiret ou a un autre mot — donc lorsqu'il appartient a un tag audio ou source.
Les cas sont ceux qui ont ete MESURES, pas des noms inventes.
"""

from __future__ import annotations

import unittest

from cinesort.domain.release_name_parser import parse_release_name

#: Noms SANS token de resolution dont le « HD » appartient a un autre tag.
_PAS_UNE_RESOLUTION = [
    "Heat.1995.REMUX.BluRay.DTS-HD.MA.5.1-FraMeSToR.mkv",
    "Le.Grand.Bleu.1988.BluRay.DTS-HD.MA.5.1-GROUPE.mkv",
    "Casino.1995.BluRay.DTS-HD.HRA.5.1-GRP.mkv",
    "Se7en.1995.BluRay.DTS-HD-GRP.mkv",
    "Fargo.1996.HD-DVD.AC3-GRP.mkv",
    "Alien.1979.BluRay.TrueHD.7.1.Atmos-GRP.mkv",
    "Movie.2020.BluRay.HDR.AC3-GRP.mkv",
    "Movie.2020.HDTV.AC3-GRP.mkv",
]

#: Noms ou « HD » EST le marqueur de resolution, seul entre deux separateurs.
_BIEN_UNE_RESOLUTION = [
    "Movie.2020.HD.x264-GRP.mkv",
    "Movie (2020) HD x264 AAC 2.0-GRP.mkv",
]


class LeTokenHDNEstUneResolutionQueSeulTests(unittest.TestCase):
    def test_un_HD_colle_a_un_autre_tag_n_invente_pas_de_720p(self) -> None:
        for nom in _PAS_UNE_RESOLUTION:
            with self.subTest(nom=nom):
                info = parse_release_name(nom)
                self.assertEqual(
                    info.resolution_hint,
                    "",
                    f"« {nom} » ne porte aucun token de resolution, or le parser en "
                    f"deduit {info.resolution_hint!r} ({info.width_hint}x{info.height_hint})",
                )
                self.assertEqual(info.width_hint, 0)
                self.assertEqual(info.height_hint, 0)

    def test_un_HD_isole_reste_un_marqueur_720p(self) -> None:
        """La restriction ne doit pas emporter le cas legitime."""
        for nom in _BIEN_UNE_RESOLUTION:
            with self.subTest(nom=nom):
                info = parse_release_name(nom)
                self.assertEqual(info.resolution_hint, "720p")
                self.assertEqual((info.width_hint, info.height_hint), (1280, 720))

    def test_les_tokens_de_resolution_explicites_priment_toujours(self) -> None:
        """Temoin : quand la resolution est ecrite, elle gagne — DTS-HD ou pas."""
        cas = {
            "Dune.2021.2160p.BluRay.DTS-HD.MA.7.1-GRP.mkv": ("2160p", 3840, 2160),
            "Dune.2021.1080p.BluRay.DTS-HD.MA.7.1-GRP.mkv": ("1080p", 1920, 1080),
            "Movie.2020.720p.WEB-DL.DTS-HD.MA-GRP.mkv": ("720p", 1280, 720),
            "Movie.2020.UHD.BluRay.AC3-GRP.mkv": ("2160p", 3840, 2160),
        }
        for nom, (label, w, h) in cas.items():
            with self.subTest(nom=nom):
                info = parse_release_name(nom)
                self.assertEqual((info.resolution_hint, info.width_hint, info.height_hint), (label, w, h))


if __name__ == "__main__":
    unittest.main()
