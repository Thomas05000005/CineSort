"""F12 — langue lue avant les tags de variante Plex/Jellyfin (.fr.forced.srt).

Avant le correctif, `detect_language_from_suffix` ne lisait que le DERNIER
token : 'Inception (2010).fr.forced.srt' -> '' -> faux flag
`subtitle_missing_fr` sur un film qui A son sous-titre FR.

Revue adverse (2 defauts corriges ici) :

1. la marche arriere n'etait bornee que par « premier token inconnu = stop »,
   ce qui ne protege PAS quand le dernier mot du titre est lui-meme une cle de
   `_LANG_MAP` : 'Dr.No.forced.srt' rendait 'no' (norvegien) sur « Dr. No ».
   La borne est desormais le STEM DE LA VIDEO, fourni par le chemin de
   production ; sans lui on ne traverse plus rien (semantique d'avant F12).
2. le garde anti-mutilation livre etait un FAUX VERT : ses 4 cas avaient tous
   un dernier token qui n'est pas un tag de variante, donc la marche arriere
   n'etait jamais exercee et le test passait a l'identique sans le correctif.
   Les cas ci-dessous ont tous un tag de variante EN DERNIER, seule forme qui
   exerce reellement la borne.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.domain.subtitle_helpers import (
    build_subtitle_report,
    detect_language_from_suffix,
)


class DetectLanguageBeforeFlagTokens(unittest.TestCase):
    """Contrat REEL : la traversee des tags exige le stem de la video."""

    def test_langue_avant_tag_special(self) -> None:
        stem = "Inception (2010)"
        for name, expected in (
            ("Inception (2010).fr.forced.srt", "fr"),
            ("Inception (2010).fre.sdh.srt", "fr"),
            ("Inception (2010).en.cc.srt", "en"),
            ("Inception (2010).fr.forced.sdh.srt", "fr"),
            ("Inception (2010).en.default.srt", "en"),
        ):
            with self.subTest(name=name):
                self.assertEqual(detect_language_from_suffix(name, video_stem=stem), expected)

    def test_mot_du_titre_avant_le_tag_n_est_jamais_une_langue(self) -> None:
        """Le cas que le garde precedent n'exercait PAS (tag de variante EN DERNIER).

        'no' et 'it' sont de vraies cles de _LANG_MAP : sans la borne stem video,
        la marche arriere traverse 'forced' puis mutile le titre en langue.
        """
        for name, stem in (
            ("Dr.No.forced.srt", "Dr.No"),
            ("Dr.No.sdh.srt", "Dr.No"),
            ("Dr.No.forced.sdh.srt", "Dr.No"),
            ("Movie.Chapter.It.forced.srt", "Movie.Chapter.It"),
            ("The.Foreign.Exchange.forced.srt", "The.Foreign.Exchange"),
        ):
            with self.subTest(name=name):
                self.assertEqual(detect_language_from_suffix(name, video_stem=stem), "")

    def test_sans_stem_video_on_ne_traverse_aucun_tag(self) -> None:
        """Hors contexte, aucune heuristique ne separe 'Dr.No' de 'Film.fr'.

        On rend donc exactement ce que rendait la version d'avant F12 (dernier
        token seul) plutot que d'inventer une langue.
        """
        self.assertEqual(detect_language_from_suffix("Dr.No.forced.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.Chapter.It.forced.srt"), "")
        self.assertEqual(detect_language_from_suffix("Inception (2010).fr.forced.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.fr.srt"), "fr")

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_token_de_titre_jamais_lu_comme_langue(self) -> None:
        """Borne historique : un mot du titre ne devient jamais une langue."""
        self.assertEqual(detect_language_from_suffix("The.Danish.Girl.2015.srt"), "")
        self.assertEqual(detect_language_from_suffix("French.Connection.1971.srt"), "")
        self.assertEqual(detect_language_from_suffix("Ma.Vie.De.Courgette.2016.srt"), "")
        self.assertEqual(detect_language_from_suffix("Le.Film.multi.srt"), "")

    def test_comportement_historique_inchange(self) -> None:
        self.assertEqual(detect_language_from_suffix("Movie.fr.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.eng.srt"), "en")
        self.assertEqual(detect_language_from_suffix("Movie.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.forced.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.sdh.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.hi.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.cc.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.xyz123.srt"), "")


class SubtitleReportWithFlagTokens(unittest.TestCase):
    """Chemin de PRODUCTION complet (celui que voit l'utilisateur)."""

    def _report(self, video_name: str, sub_names, expected):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / video_name
            video.write_bytes(b"\x00")
            for sub_name in sub_names:
                (folder / sub_name).write_text("", encoding="utf-8")
            return build_subtitle_report(folder, video, expected)

    def test_forced_seul_compte_comme_langue_presente(self) -> None:
        report = self._report("Inception (2010).mkv", ["Inception (2010).fr.forced.srt"], ["fr"])
        self.assertEqual(report.languages, ["fr"])
        self.assertEqual(report.missing_languages, [])
        self.assertEqual(report.count, 1)

    def test_forced_plus_full_ne_sont_pas_un_doublon(self) -> None:
        report = self._report(
            "Inception (2010).mkv",
            ["Inception (2010).fr.srt", "Inception (2010).fr.forced.srt"],
            ["fr"],
        )
        self.assertEqual(report.languages, ["fr"])
        self.assertEqual(report.missing_languages, [])
        self.assertEqual(report.duplicate_languages, [])
        self.assertEqual(report.count, 2)

    def test_titre_termine_par_un_code_langue_n_invente_pas_de_langue(self) -> None:
        """« Dr. No » + sous-titre force : aucune langue, FR toujours signale absent."""
        report = self._report("Dr.No.mkv", ["Dr.No.forced.srt"], ["fr"])
        self.assertEqual(report.languages, [])
        self.assertEqual(report.missing_languages, ["fr"])
        self.assertEqual(report.count, 1)

    def test_mot_de_titre_homonyme_d_un_tag_ne_masque_pas_un_doublon(self) -> None:
        """'The.Foreign.Exchange' : 'foreign' est un mot du TITRE, pas un tag.

        Avant le correctif, _subtitle_flag_tokens balayait tous les tokens, voyait
        'foreign' dans les deux sous-titres, les sautait tous les deux et perdait
        le VRAI doublon de langue.
        """
        report = self._report(
            "The.Foreign.Exchange.mkv",
            ["The.Foreign.Exchange.fr.srt", "The.Foreign.Exchange.french.srt"],
            [],
        )
        self.assertEqual(report.count, 2)
        self.assertEqual(report.duplicate_languages, ["fr"])

    # --- NON-REGRESSION -----------------------------------------------------

    def test_vrai_doublon_de_langue_toujours_detecte(self) -> None:
        """Deux pistes FR completes (aucun tag) restent un doublon signale."""
        report = self._report("Movie.mkv", ["Movie.fr.srt", "Movie.french.srt"], [])
        self.assertEqual(report.count, 2)
        self.assertEqual(report.duplicate_languages, ["fr"])

    def test_langue_reellement_absente_toujours_signalee(self) -> None:
        report = self._report("Movie.mkv", ["Movie.en.srt"], ["fr"])
        self.assertEqual(report.missing_languages, ["fr"])


if __name__ == "__main__":
    unittest.main()
