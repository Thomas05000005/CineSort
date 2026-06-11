"""GATE AUDIT 2026-06-11 (R4-P5) — les filtres du drawer Qualite filtrent enfin.

CRITIC-1 (verification totale) : le drawer Qualite
(qualite-filters-drawer.js) envoie {sources:['BluRay','WEB-DL',...],
decades:['1990',...], audio_languages:['FR','EN','Multi','Autre']} vers
library/get_films_by_decade qui reutilise library_support._row_matches — mais
_row_matches ne lisait QUE 'source' (singulier, drawer Biblio), jamais
'sources' ni 'decades', et 'Autre' (audio) ne matchait jamais. Resultat :
filtres morts (toutes les rows passaient).

Apres : 'sources' lu comme alias avec normalisation des libelles
(WEB-DL/WEB-Rip -> web, HDTV/Autre -> other), 'decades' filtre sur year//10
(tolere '1990s'), 'Autre' audio = vraie langue hors fr/en. Le filtre 'genres'
reste non applicable (les rows n'embarquent pas les genres TMDb — manque de
donnees documente) ; period_days est consomme par quality/get_history.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.library_support import _row_matches


def _row(**kw):
    base = {"codec": "hevc", "resolution": "1080p", "media_source": "bluray",
            "audio_languages": ["fra"], "subtitle_languages": [], "title": "X",
            "year": 1994}
    base.update(kw)
    return base


class QualiteDrawerSourcesTests(unittest.TestCase):
    def test_sources_bluray_label_matches(self) -> None:
        self.assertTrue(_row_matches(_row(media_source="bluray"), {"sources": ["BluRay"]}))
        self.assertFalse(_row_matches(_row(media_source="web"), {"sources": ["BluRay"]}))

    def test_sources_webdl_webrip_labels_match_web(self) -> None:
        self.assertTrue(_row_matches(_row(media_source="web"), {"sources": ["WEB-DL"]}))
        self.assertTrue(_row_matches(_row(media_source="web"), {"sources": ["WEB-Rip"]}))
        self.assertFalse(_row_matches(_row(media_source="dvd"), {"sources": ["WEB-DL"]}))

    def test_sources_hdtv_and_autre_match_other(self) -> None:
        self.assertTrue(_row_matches(_row(media_source="other"), {"sources": ["HDTV"]}))
        self.assertTrue(_row_matches(_row(media_source="other"), {"sources": ["Autre"]}))
        self.assertFalse(_row_matches(_row(media_source="bluray"), {"sources": ["Autre"]}))

    def test_singular_source_key_still_works(self) -> None:
        # Non-regression drawer Biblio (cle 'source', valeurs deja backend).
        self.assertTrue(_row_matches(_row(media_source="web"), {"source": ["web"]}))


class QualiteDrawerDecadesTests(unittest.TestCase):
    def test_decade_match(self) -> None:
        self.assertTrue(_row_matches(_row(year=1994), {"decades": ["1990"]}))
        self.assertFalse(_row_matches(_row(year=2010), {"decades": ["1990"]}))

    def test_decade_tolerates_s_suffix(self) -> None:
        self.assertTrue(_row_matches(_row(year=1994), {"decades": ["1990s"]}))

    def test_decade_multi_select(self) -> None:
        self.assertTrue(_row_matches(_row(year=2024), {"decades": ["1990", "2020"]}))

    def test_year_zero_excluded_when_filter_active(self) -> None:
        self.assertFalse(_row_matches(_row(year=0), {"decades": ["1990"]}))


class QualiteDrawerAudioAutreTests(unittest.TestCase):
    def test_autre_matches_non_fr_en_language(self) -> None:
        self.assertTrue(_row_matches(_row(audio_languages=["hin"]), {"audio_languages": ["Autre"]}))
        self.assertTrue(_row_matches(_row(audio_languages=["jpn"]), {"audio_languages": ["Autre"]}))

    def test_autre_does_not_match_fr_en_only(self) -> None:
        self.assertFalse(_row_matches(_row(audio_languages=["fra"]), {"audio_languages": ["Autre"]}))
        self.assertFalse(_row_matches(_row(audio_languages=["eng"]), {"audio_languages": ["Autre"]}))

    def test_uppercase_fr_label_matches(self) -> None:
        # Le drawer Qualite envoie 'FR'/'EN' en majuscules.
        self.assertTrue(_row_matches(_row(audio_languages=["fra"]), {"audio_languages": ["FR"]}))


class CombinedQualitePayloadTests(unittest.TestCase):
    def test_full_qualite_drawer_payload(self) -> None:
        # Payload exact du drawer Qualite (EMPTY_FILTERS + selections).
        filters = {"decades": ["1990"], "genres": [], "sources": ["BluRay"],
                   "audio_languages": ["FR"], "period_days": 30}
        self.assertTrue(_row_matches(_row(year=1994, media_source="bluray",
                                          audio_languages=["fra"]), filters))
        self.assertFalse(_row_matches(_row(year=1994, media_source="web",
                                           audio_languages=["fra"]), filters))
        self.assertFalse(_row_matches(_row(year=2005, media_source="bluray",
                                           audio_languages=["fra"]), filters))


if __name__ == "__main__":
    unittest.main()
