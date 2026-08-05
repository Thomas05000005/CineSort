# Fix audit 2026-05-25 (v1.5.4) Vague I : test BUG 2 — coherence du compte
# "sans subs FR" entre la page Bibliotheque et le rapport Qualite.
"""Tests pour la coherence du compte "sans subs FR" entre les vues
Bibliotheque et Qualite (Vague I, BUG 2).

Les 2 endpoints utilisent maintenant la meme source de verite (fusion
externes detectes au scan + pistes embarquees persistees dans
`quality_reports.metrics.subtitles_embedded`).

Tests :
1. `_build_library_rows` fusionne `subtitle_languages` quand un
   `quality_report` contient `subtitles_embedded`.
2. `_row_subs_missing_fr` ne flag pas a tort un film qui a FR embarque.
3. Le compte "subs_missing_fr" cote chip est egal au nombre de films
   sans FR dans library_rows.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from cinesort.domain.librarian import generate_suggestions
from cinesort.ui.api import library_support


def _plan_row(row_id: str, *, subtitle_languages=None, subtitle_missing_langs=None):
    """Construit un dict plan row minimal (sortie de api.run.get_plan)."""
    return {
        "row_id": row_id,
        "proposed_title": f"Film {row_id}",
        "proposed_year": 2020,
        "proposed_source": "tmdb",
        "confidence": 90,
        "subtitle_languages": subtitle_languages or [],
        "subtitle_missing_langs": subtitle_missing_langs or [],
        "source_path": f"/tmp/{row_id}.mkv",
        "mtime": 0,
        "tmdb_id": 1234,
        "size_bytes": 0,
    }


def _quality_report(row_id: str, *, embedded_subs=None):
    """Construit un quality_report avec subtitles_embedded dans metrics."""
    return {
        "row_id": row_id,
        "score": 75,
        "tier": "Gold",
        "metrics": {
            "subtitles_embedded": embedded_subs or [],
            "video": {"width": 1920, "height": 1080},
        },
    }


def _patch_store(api: MagicMock, *, plan_rows, quality_list, perc_list=None):
    """Patche les acces store + api.run.get_plan pour _build_library_rows."""
    store = MagicMock()
    store.perceptual.list_perceptual_reports.return_value = perc_list or []
    store.quality.list_quality_reports.return_value = quality_list
    api._get_or_create_infra.return_value = (store, MagicMock())
    api.settings.get_settings.return_value = {"state_dir": "/tmp"}
    api.run.get_plan.return_value = {"ok": True, "rows": plan_rows}
    return store


class BuildLibraryRowsMergesEmbeddedSubsTests(unittest.TestCase):
    """Vague I BUG 2 : `_build_library_rows` fusionne externes + embedded."""

    def test_external_fr_only_no_change(self) -> None:
        """Sans quality_report, seules les langues externes (PlanRow) comptent."""
        api = MagicMock()
        plan_rows = [_plan_row("R1", subtitle_languages=["fr"])]
        _patch_store(api, plan_rows=plan_rows, quality_list=[])

        rows = library_support._build_library_rows(api, "run_xyz")
        self.assertEqual(len(rows), 1)
        self.assertIn("fr", rows[0]["subtitle_languages"])
        self.assertEqual(rows[0]["subtitle_missing_langs"], [])

    def test_embedded_fr_merges_into_subtitle_languages(self) -> None:
        """Une piste FR EMBARQUEE doit faire apparaitre 'fr' dans
        `subtitle_languages` meme si le scan n'avait detecte aucun externe."""
        api = MagicMock()
        plan_rows = [
            _plan_row(
                "R1",
                subtitle_languages=[],  # scan n'a vu aucun externe
                subtitle_missing_langs=["fr"],  # donc scan a flag FR manquant
            )
        ]
        quality_list = [
            _quality_report(
                "R1",
                embedded_subs=[{"index": 2, "language": "fra", "forced": False}],
            )
        ]
        _patch_store(api, plan_rows=plan_rows, quality_list=quality_list)

        rows = library_support._build_library_rows(api, "run_xyz")
        self.assertEqual(len(rows), 1)
        self.assertIn(
            "fr",
            rows[0]["subtitle_languages"],
            "FR embarque doit fusionner dans subtitle_languages",
        )
        # subtitle_missing_langs doit aussi etre nettoye
        self.assertNotIn(
            "fr",
            rows[0]["subtitle_missing_langs"],
            "FR ne doit plus etre flag missing si embarque",
        )

    def test_embedded_iso639_variants_normalize_to_fr(self) -> None:
        """`fra`, `fre`, `french`, `FRENCH` doivent tous normaliser vers `fr`."""
        for tag in ("fra", "fre", "fr", "french", "FRENCH"):
            api = MagicMock()
            plan_rows = [_plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"])]
            quality_list = [
                _quality_report(
                    "R1",
                    embedded_subs=[{"index": 0, "language": tag, "forced": False}],
                )
            ]
            _patch_store(api, plan_rows=plan_rows, quality_list=quality_list)
            rows = library_support._build_library_rows(api, "run_xyz")
            self.assertIn(
                "fr",
                rows[0]["subtitle_languages"],
                f"Tag '{tag}' doit normaliser vers 'fr'",
            )


class RowSubsMissingFrConsistencyTests(unittest.TestCase):
    """Vague I BUG 2 : `_row_subs_missing_fr` aligne avec la fusion."""

    def test_external_fr_not_flagged_missing(self) -> None:
        row = {"subtitle_languages": ["fr"], "subtitle_missing_langs": []}
        self.assertFalse(library_support._row_subs_missing_fr(row))

    def test_no_subs_at_all_flagged_missing(self) -> None:
        row = {"subtitle_languages": [], "subtitle_missing_langs": []}
        self.assertTrue(library_support._row_subs_missing_fr(row))

    def test_only_en_flagged_missing_fr(self) -> None:
        row = {"subtitle_languages": ["en"], "subtitle_missing_langs": ["fr"]}
        self.assertTrue(library_support._row_subs_missing_fr(row))


def _plan_row_obj(row_id, *, subtitle_languages=None, subtitle_missing_langs=None):
    """PlanRow-like object (acces via getattr) pour le chemin QUALITE
    (librarian.generate_suggestions). Reflete le MEME film que _plan_row()."""
    return SimpleNamespace(
        row_id=row_id,
        proposed_title=f"Film {row_id}",
        proposed_source="tmdb",
        confidence=90,
        warning_flags=[],
        subtitle_languages=subtitle_languages or [],
        subtitle_missing_langs=subtitle_missing_langs or [],
        tmdb_collection_id=None,
        tmdb_collection_name=None,
    )


def _quality_report_qr(row_id, *, embedded_subs=None):
    """quality_report cote librarian (meme schema metrics.subtitles_embedded
    que la vue Bibliotheque)."""
    return {
        "row_id": row_id,
        "score": 75,
        "tier": "Gold",
        "metrics": {
            "subtitles_embedded": embedded_subs or [],
            "video": {"width": 1920, "height": 1080},
            "detected": {"video_codec": "hevc", "resolution": "1080p", "height": 1080},
        },
    }


class LibraryAndQualityCountAlignmentTests(unittest.TestCase):
    """Vague L (subs-2) : invariant d'alignement NON-TAUTOLOGIQUE.

    L'ancien test comparait deux derivations de la MEME liste _build_library_rows
    (toujours egales par construction). On compare desormais les DEUX vrais
    chemins de production sur LE MEME film a FR embarque :

      - chemin BIBLIOTHEQUE : library_support._build_library_rows + _row_subs_missing_fr
      - chemin QUALITE      : domain.librarian.generate_suggestions (suggestion
                              "missing_subtitles")

    Avant le fix subs-1, generate_suggestions ignore metrics.subtitles_embedded
    -> il compte le film comme "sans FR" alors que la Bibliotheque le compte
    comme OK -> divergence -> ce test ECHOUE. Apres le fix, les 2 concordent.
    """

    def _bibliotheque_missing_fr(self, api) -> int:
        rows = library_support._build_library_rows(api, "run_xyz")
        return sum(1 for r in rows if library_support._row_subs_missing_fr(r))

    def _qualite_missing_fr(self, plan_rows_obj, quality_list) -> int:
        result = generate_suggestions(plan_rows_obj, quality_list, {"subtitle_expected_languages": ["fr"]})
        for sugg in result.get("suggestions", []):
            if sugg.get("id") == "missing_subtitles":
                return int(sugg.get("count") or 0)
        return 0

    def test_alignment_single_film_fr_embedded(self) -> None:
        """1 film, FR uniquement EMBARQUE. Biblio dit "OK", Qualite doit aussi.

        C'est LE cas du BUG : avant subs-1, Qualite=1 et Biblio=0 -> echec.
        """
        api = MagicMock()
        plan_rows_dict = [_plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"])]
        plan_rows_obj = [_plan_row_obj("R1", subtitle_languages=[], subtitle_missing_langs=["fr"])]
        quality_list = [_quality_report("R1", embedded_subs=[{"language": "fra", "forced": False}])]
        quality_list_qr = [_quality_report_qr("R1", embedded_subs=[{"language": "fra", "forced": False}])]
        _patch_store(api, plan_rows=plan_rows_dict, quality_list=quality_list)

        biblio = self._bibliotheque_missing_fr(api)
        qualite = self._qualite_missing_fr(plan_rows_obj, quality_list_qr)

        self.assertEqual(biblio, 0, "Biblio : FR embarque -> 0 manquant")
        self.assertEqual(
            qualite,
            biblio,
            "subs-1 : Qualite doit concorder avec Bibliotheque (FR embarque compte)",
        )

    def test_alignment_mixed_films(self) -> None:
        """3 films : 2 avec FR embarque, 1 sans aucun FR. Les 2 vues : 1 manquant."""
        api = MagicMock()
        plan_rows_dict = [
            _plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row("R2", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row("R3", subtitle_languages=[], subtitle_missing_langs=["fr"]),
        ]
        plan_rows_obj = [
            _plan_row_obj("R1", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row_obj("R2", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row_obj("R3", subtitle_languages=[], subtitle_missing_langs=["fr"]),
        ]
        quality_list = [
            _quality_report("R1", embedded_subs=[{"language": "fra", "forced": False}]),
            _quality_report("R2", embedded_subs=[{"language": "fre", "forced": False}]),
        ]
        quality_list_qr = [
            _quality_report_qr("R1", embedded_subs=[{"language": "fra", "forced": False}]),
            _quality_report_qr("R2", embedded_subs=[{"language": "fre", "forced": False}]),
        ]
        _patch_store(api, plan_rows=plan_rows_dict, quality_list=quality_list)

        biblio = self._bibliotheque_missing_fr(api)
        qualite = self._qualite_missing_fr(plan_rows_obj, quality_list_qr)

        self.assertEqual(biblio, 1, "Seul R3 (sans FR) doit etre manquant")
        self.assertEqual(qualite, biblio, "subs-1 : les 2 vues concordent")

    def test_alignment_german_embedded_not_french(self) -> None:
        """Film avec GER embarque (pas FR) : doit compter manquant des 2 cotes.

        CASSE si _normalize_iso639 collapse 'ger' -> 'fr' (mutation testing).
        """
        api = MagicMock()
        plan_rows_dict = [_plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"])]
        plan_rows_obj = [_plan_row_obj("R1", subtitle_languages=[], subtitle_missing_langs=["fr"])]
        quality_list = [_quality_report("R1", embedded_subs=[{"language": "ger", "forced": False}])]
        quality_list_qr = [_quality_report_qr("R1", embedded_subs=[{"language": "ger", "forced": False}])]
        _patch_store(api, plan_rows=plan_rows_dict, quality_list=quality_list)

        biblio = self._bibliotheque_missing_fr(api)
        qualite = self._qualite_missing_fr(plan_rows_obj, quality_list_qr)

        self.assertEqual(biblio, 1, "GER embarque != FR -> manquant cote Biblio")
        self.assertEqual(qualite, 1, "GER embarque != FR -> manquant cote Qualite")


if __name__ == "__main__":
    unittest.main()
