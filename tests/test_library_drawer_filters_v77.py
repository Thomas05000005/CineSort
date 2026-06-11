"""GATE AUDIT 2026-06-11 (R3) — les filtres du drawer biblio matchent enfin.

Avant : codec "h265" vs backend "hevc" ; resolution "480p" vs "sd" ; source
compare a proposed_source (identification) ; audio_languages ISO639-2/3 brut vs
drawer fr/en ; subtitle "none" excluait les films SANS sous-titres -> chaque
filtre retournait 0 resultat.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.library_support import _media_source_label, _row_matches, _to_iso639_1


class DrawerFilterTests(unittest.TestCase):
    def _row(self, **kw):
        base = {"codec": "hevc", "resolution": "1080p", "media_source": "bluray",
                "audio_languages": ["eng"], "subtitle_languages": ["fre"], "title": "X"}
        base.update(kw)
        return base

    # --- Codec : drawer h265 -> backend hevc ---
    def test_codec_h265_matches_hevc(self) -> None:
        self.assertTrue(_row_matches(self._row(codec="hevc"), {"codec": ["h265"]}))
        self.assertFalse(_row_matches(self._row(codec="h264"), {"codec": ["h265"]}))

    def test_codec_other(self) -> None:
        self.assertTrue(_row_matches(self._row(codec="vp9"), {"codec": ["other"]}))
        self.assertFalse(_row_matches(self._row(codec="h264"), {"codec": ["other"]}))

    # --- Resolution : drawer 480p -> backend sd ; other -> unknown ---
    def test_resolution_480p_matches_sd(self) -> None:
        self.assertTrue(_row_matches(self._row(resolution="sd"), {"resolution": ["480p"]}))
        self.assertFalse(_row_matches(self._row(resolution="1080p"), {"resolution": ["480p"]}))

    def test_resolution_other_matches_unknown(self) -> None:
        self.assertTrue(_row_matches(self._row(resolution="unknown"), {"resolution": ["other"]}))
        self.assertFalse(_row_matches(self._row(resolution="4k"), {"resolution": ["other"]}))

    # --- Source : media source derivee, pas proposed_source ---
    def test_source_filter_uses_media_source(self) -> None:
        self.assertTrue(_row_matches(self._row(media_source="web"), {"source": ["web"]}))
        self.assertFalse(_row_matches(self._row(media_source="bluray"), {"source": ["web"]}))

    def test_media_source_label_derivation(self) -> None:
        self.assertEqual(_media_source_label("Movie.2020.1080p.BluRay.x264-GRP.mkv"), "bluray")
        self.assertEqual(_media_source_label("Movie.2020.WEB-DL.x264.mkv"), "web")
        self.assertEqual(_media_source_label("Movie.2020.HDTV.mkv"), "other")

    # --- Audio langues : ISO normalise + multi ---
    def test_audio_language_iso_normalized(self) -> None:
        self.assertEqual(_to_iso639_1("eng"), "en")
        self.assertEqual(_to_iso639_1("fra"), "fr")
        self.assertTrue(_row_matches(self._row(audio_languages=["fra"]), {"audio_languages": ["fr"]}))

    def test_audio_multi(self) -> None:
        self.assertTrue(_row_matches(self._row(audio_languages=["eng", "fra"]), {"audio_languages": ["multi"]}))
        self.assertFalse(_row_matches(self._row(audio_languages=["eng"]), {"audio_languages": ["multi"]}))

    # --- AUDIT 2026-06-11 (R4-P3) : langues hors _LANG_MAP comptees, non-langues exclues ---
    def test_audio_multi_with_unmapped_language(self) -> None:
        """Un film eng+hin (hindi hors _LANG_MAP) EST multi-langues. Avant,
        hin -> '' -> discard -> 1 seule langue comptee -> 'multi' ratait."""
        self.assertTrue(_row_matches(self._row(audio_languages=["eng", "hin"]), {"audio_languages": ["multi"]}))
        self.assertTrue(_row_matches(self._row(audio_languages=["hin", "tam"]), {"audio_languages": ["multi"]}))

    def test_audio_und_is_not_a_second_language(self) -> None:
        """'und' (indetermine, tres frequent ffprobe) n'est pas une vraie 2e langue."""
        self.assertFalse(_row_matches(self._row(audio_languages=["eng", "und"]), {"audio_languages": ["multi"]}))

    def test_subtitle_none_excludes_unmapped_language_subs(self) -> None:
        """Un film avec des sous-titres hindi A des sous-titres : il ne doit pas
        matcher 'Aucun'. Avant, hin -> '' -> discard -> set vide -> matchait."""
        self.assertFalse(_row_matches(self._row(subtitle_languages=["hin"]), {"subtitle_languages": ["none"]}))
        self.assertFalse(_row_matches(self._row(subtitle_languages=["und"]), {"subtitle_languages": ["none"]}))

    def test_audio_unmapped_does_not_match_fr(self) -> None:
        # Non-regression : un code brut conserve ne matche pas un filtre fr/en.
        self.assertFalse(_row_matches(self._row(audio_languages=["hin"]), {"audio_languages": ["fr"]}))

    # --- Sous-titres : "none" = aucun sous-titre ---
    def test_subtitle_none_selects_films_without_subs(self) -> None:
        self.assertTrue(_row_matches(self._row(subtitle_languages=[]), {"subtitle_languages": ["none"]}))
        self.assertFalse(_row_matches(self._row(subtitle_languages=["fre"]), {"subtitle_languages": ["none"]}))

    def test_subtitle_language_normalized(self) -> None:
        self.assertTrue(_row_matches(self._row(subtitle_languages=["fra"]), {"subtitle_languages": ["fr"]}))

    def test_no_filter_passes(self) -> None:
        self.assertTrue(_row_matches(self._row(), {}))


if __name__ == "__main__":
    unittest.main()
