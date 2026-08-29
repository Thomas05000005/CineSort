"""GATE AUDIT 2026-06-10 (REAL 2/2, invariant titres) — parse_scene_title ne
mutile plus les titres reels.

Deux bugs corriges :
1. _AUDIO_RESIDUE_RE : separateur de canal optionnel + tokens nus "ma"/"hra"
   mutilaient "21 Jump Street", "50 First Dates", "Ma Vie de Courgette", etc.
2. _RELEASE_GROUP_RE applique sans garde scene -> "Thor - Ragnarok" -> "Thor".
"""

from __future__ import annotations

import unittest

from cinesort.domain.scene_parser import parse_scene_title


class TitlePreservationTests(unittest.TestCase):
    def test_number_titles_not_mutilated(self) -> None:
        self.assertEqual(parse_scene_title("21 Jump Street (2012)"), "21 Jump Street")
        self.assertEqual(parse_scene_title("50 First Dates"), "50 First Dates")
        self.assertEqual(parse_scene_title("20 000 Leagues Under the Sea (1954)"), "20 000 Leagues Under the Sea")

    def test_ma_titlecase_word_preserved(self) -> None:
        self.assertEqual(parse_scene_title("Ma Vie de Courgette"), "Ma Vie de Courgette")

    def test_subtitle_after_dash_preserved_without_tech_marker(self) -> None:
        self.assertEqual(parse_scene_title("Thor - Ragnarok (2017)"), "Thor - Ragnarok")
        self.assertEqual(parse_scene_title("Blade - Trinity (2004)"), "Blade - Trinity")
        self.assertEqual(parse_scene_title("Cloverfield - Paradox"), "Cloverfield - Paradox")

    def test_subtitle_preserved_even_with_single_quality_tag(self) -> None:
        """GATE R4-P2 (regression R1a/50acdaf) : un nommage personnel
        'Titre - SousTitre TAG' ne doit PAS perdre son sous-titre quand un tag
        qualite isole (4K/DV/SDR/XviD/PROPER/HDLight...) declenche
        had_tech_marker. Signal structurel : un release group scene est COLLE
        au tiret (' -GROUP'), un sous-titre a un espace des deux cotes."""
        cases = {
            "Thor - Ragnarok 4K.mkv": "Thor - Ragnarok",
            "Thor - Ragnarok (2017) 4K.mkv": "Thor - Ragnarok",
            "Thor - Ragnarok DV.mkv": "Thor - Ragnarok",
            "Cloverfield - Paradox SDR.mkv": "Cloverfield - Paradox",
            "Blade - Trinity FHD.mkv": "Blade - Trinity",
            "Rocky - Balboa XviD.mkv": "Rocky - Balboa",
            "John Wick - Parabellum HDLight.mkv": "John Wick - Parabellum",
            "Batman - Begins PROPER.mkv": "Batman - Begins",
            "Kill Bill - Vol1 REPACK.mkv": "Kill Bill - Vol1",
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_scene_title(raw), expected, raw)

    def test_subtitle_preserved_with_full_tech_chain(self) -> None:
        # Cas pre-existant (mutile aussi AVANT R1a) repare par le tiret colle :
        # le sous-titre espace survit meme a une chaine technique complete.
        self.assertEqual(parse_scene_title("Title - Sub 1080p x264.mkv"), "Title - Sub")


class RealReleaseStillCleanedTests(unittest.TestCase):
    def test_release_group_stripped_when_tech_marker_present(self) -> None:
        self.assertEqual(
            parse_scene_title("Thor.Ragnarok.2017.1080p.BluRay.x264-SPARKS"),
            "Thor Ragnarok 2017",
        )

    def test_dts_hd_ma_audio_tag_still_stripped(self) -> None:
        # "MA" en majuscules (tag audio) toujours retire ; titre propre.
        self.assertEqual(
            parse_scene_title("Movie.2015.1080p.BluRay.DTS-HD.MA.5.1.x264-Tigole.mkv"),
            "Movie 2015",
        )

    def test_channel_layout_still_stripped(self) -> None:
        self.assertEqual(
            parse_scene_title("Dune.Part.Two.2024.2160p.BluRay.DTS-HD.MA.7.1-SWTYBLZ.mkv"),
            "Dune Part Two 2024",
        )

    def test_release_group_stripped_with_legacy_codec_markers(self) -> None:
        # GATE R1a (regression introduite par le 1er fix) : les tags techniques
        # autres que x264/1080p (XviD, DivX, EAC3, HDLight) doivent AUSSI declencher
        # le strip du release group. _NOISE_RE est la source unique.
        self.assertEqual(parse_scene_title("Old.Movie.1998.XviD-DEiTY.avi"), "Old Movie 1998")
        self.assertEqual(parse_scene_title("Film.2020.DVDRip.DivX-ABC.avi"), "Film 2020")
        self.assertEqual(parse_scene_title("Film.1998.HDLight-DEiTY.mkv"), "Film 1998")
        # EAC3 : le release group -NTb doit etre retire (le residu AMZN/WEB est un
        # autre sujet, non couvert ici).
        self.assertNotIn("-NTb", parse_scene_title("Movie.2023.AMZN.WEB.EAC3-NTb.mkv"))


if __name__ == "__main__":
    unittest.main()


class MotsAmbigusDeLaListeINCONDITIONNELLETests(unittest.TestCase):
    """T-DOM-1 : `_NOISE_RE` retirait des mots qui sont de vrais titres de films.

    `_NOISE_RE` s'applique PARTOUT dans le nom, y compris AVANT le token annee —
    c'est-a-dire a l'interieur du titre lui-meme. Une poignee de ses ~50 jetons
    sont des mots courants :

        Cam (2018)              -> ''              le titre ENTIER disparaissait
        Opus (2025)             -> ''              idem
        Internal Affairs (1990) -> 'Affairs 1990'
        Complete Unknown (2016) -> 'Unknown 2016'

    Le depot connaissait deja le probleme et l'avait resolu : `_AFTER_YEAR_NOISE`
    ne retire ses jetons que s'ils apparaissent APRES l'annee — « The French
    Connection 2 1975 » garde son « French ». Trois jetons (`cam`, `proper`,
    `repack`) figuraient dans les DEUX listes.

    Mais l'ordre du pipeline decide : `_NOISE_RE` est l'etape 3, le traitement
    position-aware l'etape 7. La liste inconditionnelle consommait les jetons
    quatre etapes avant que la position-aware puisse les voir. Une garde en
    aveuglait une autre en s'executant AVANT elle, en lui retirant sa matiere —
    et la docstring de l'etape 7, qui enumere « FRENCH, CUT, EDITION, WEB »,
    n'en mentionnait aucun : le code disait deja que ce chemin etait mort.

    Les deux moities de cette classe comptent autant l'une que l'autre. Deplacer
    les jetons sans verifier qu'ils sont TOUJOURS retires apres l'annee
    remplacerait un defaut par un autre : des tags scene laisses dans le titre,
    et une recherche TMDb ratee pour une autre raison.
    """

    #: Titre attendu -> nom de fichier. Films reels, verifiables.
    TITRES_REELS = {
        "Cam": "Cam (2018).mkv",
        "Cam 2018": "Cam.2018.1080p.WEB-DL.x264-GROUP.mkv",
        "Opus": "Opus (2025).mkv",
        "Internal Affairs 1990": "Internal.Affairs.1990.1080p.BluRay.x264.mkv",
        "Complete Unknown 2016": "Complete.Unknown.2016.1080p.WEB-DL.mkv",
        "Hybrid 2007": "Hybrid.2007.720p.mkv",
        "Limited 2019": "Limited.2019.1080p.mkv",
        "Proper 2022": "Proper.2022.1080p.mkv",
    }

    #: Le sens inverse : ces memes jetons, APRES l'annee, restent des tags scene.
    TAGS_APRES_ANNEE = (
        "Movie.2019.LIMITED.1080p.BluRay.mkv",
        "Movie.2019.PROPER.1080p.mkv",
        "Movie.2019.COMPLETE.BluRay.mkv",
        "Movie.2019.INTERNAL.1080p.mkv",
        "Movie.2019.CAM.mkv",
        "Movie.2019.1080p.Opus.mkv",
        "Movie.2019.HYBRID.1080p.mkv",
    )

    def test_un_mot_ambigu_AVANT_l_annee_appartient_au_titre(self) -> None:
        for attendu, fichier in self.TITRES_REELS.items():
            with self.subTest(fichier=fichier):
                self.assertEqual(parse_scene_title(fichier), attendu)

    def test_le_meme_mot_APRES_l_annee_reste_un_tag_scene(self) -> None:
        for fichier in self.TAGS_APRES_ANNEE:
            with self.subTest(fichier=fichier):
                self.assertEqual(parse_scene_title(fichier), "Movie 2019")

    def test_un_mot_ambigu_AU_MILIEU_du_titre_est_intouchable(self) -> None:
        """L'ancrage `$` de `_TRAILING_AMBIGU_RE`, ne dependant d'aucun autre test.

        Sans ce garde, « A Complete Unknown » (2024, le biopic Dylan) devient
        « A Unknown » : le jeton est precede d'un caractere non blanc, donc la
        garde « pas le seul jeton » le laisse passer, et seule la fin de chaine
        l'arrete.

        Ce test est ne d'un mutant SURVIVANT : retirer le `$` laissait toute la
        batterie verte, parce qu'aucun cas n'avait de jeton ambigu AILLEURS
        qu'en fin de nom.
        """
        cas = {
            "A.Complete.Unknown.2024.1080p.WEB-DL.mkv": "A Complete Unknown 2024",
            "The.Internal.Affairs.1990.1080p.mkv": "The Internal Affairs 1990",
            "Une.Limited.Histoire.2011.720p.mkv": "Une Limited Histoire 2011",
        }
        for fichier, attendu in cas.items():
            with self.subTest(fichier=fichier):
                self.assertEqual(parse_scene_title(fichier), attendu)

    def test_les_tags_NON_ambigus_restent_inconditionnels(self) -> None:
        """Temoin : le gros de `_NOISE_RE` ne doit pas bouger.

        Aucun film ne s'appelle « x265 » ni « DTS-HD ». Les deplacer aussi
        serait une regression silencieuse — ces jetons apparaissent parfois
        AVANT l'annee dans les nommages personnels.
        """
        self.assertEqual(parse_scene_title("Dune.2021.2160p.UHD.BluRay.x265.mkv"), "Dune 2021")
        self.assertEqual(parse_scene_title("Heat.1995.1080p.mkv"), "Heat 1995")
        self.assertEqual(parse_scene_title("Interstellar.2014.1080p.BluRay.x264.mkv"), "Interstellar 2014")
        self.assertEqual(parse_scene_title("Camino.2008.1080p.mkv"), "Camino 2008")
