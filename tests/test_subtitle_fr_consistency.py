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
from unittest.mock import MagicMock, patch

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
            plan_rows = [
                _plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"])
            ]
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


class LibraryAndQualityCountAlignmentTests(unittest.TestCase):
    """Vague I BUG 2 : le compte "sans subs FR" de Bibliotheque == compte
    Qualite. C'est l'invariant attendu apres le fix : les 2 endpoints
    consomment la meme structure rows enrichie.

    On compare :
    - sum(_row_subs_missing_fr(row) pour row in library_rows)
    - vs sum(idem) sur la meme liste construite via _build_library_rows
    Les 2 doivent etre strictement egaux car alimentes par la meme source.
    """

    def test_alignment_when_embedded_present(self) -> None:
        """3 films : 2 avec FR embarque, 1 sans aucun subtitle FR."""
        api = MagicMock()
        plan_rows = [
            _plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row("R2", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row("R3", subtitle_languages=[], subtitle_missing_langs=["fr"]),
        ]
        quality_list = [
            _quality_report(
                "R1", embedded_subs=[{"language": "fra", "forced": False}]
            ),
            _quality_report(
                "R2", embedded_subs=[{"language": "fre", "forced": False}]
            ),
            # R3 : pas de quality_report -> reste flag missing FR
        ]
        _patch_store(api, plan_rows=plan_rows, quality_list=quality_list)

        rows = library_support._build_library_rows(api, "run_xyz")
        self.assertEqual(len(rows), 3)

        # Compte cote "Bibliotheque" (chip subs_missing_fr)
        missing_fr_count = sum(
            1 for r in rows if library_support._row_subs_missing_fr(r)
        )

        # Compte cote "Qualite" : meme logique, meme source de verite
        # (le rapport qualite agrege subtitle_languages des memes library rows).
        # Apres le fix Vague I, les 2 vues utilisent _build_library_rows comme
        # base, donc le compte derive est strictement identique.
        quality_missing_fr_count = sum(
            1
            for r in rows
            if not any(lang.startswith("fr") for lang in r.get("subtitle_languages") or [])
        )

        self.assertEqual(
            missing_fr_count,
            quality_missing_fr_count,
            "BUG 2 : les 2 vues doivent donner le meme compte 'sans subs FR'",
        )
        # Et le compte attendu est 1 (seul R3 sans FR embarque)
        self.assertEqual(missing_fr_count, 1)

    def test_alignment_when_all_have_fr_embedded(self) -> None:
        """Cas regression : 3 films, tous avec FR embarque -> 0 missing."""
        api = MagicMock()
        plan_rows = [
            _plan_row("R1", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row("R2", subtitle_languages=[], subtitle_missing_langs=["fr"]),
            _plan_row("R3", subtitle_languages=[], subtitle_missing_langs=["fr"]),
        ]
        quality_list = [
            _quality_report(
                rid, embedded_subs=[{"language": "fra", "forced": False}]
            )
            for rid in ("R1", "R2", "R3")
        ]
        _patch_store(api, plan_rows=plan_rows, quality_list=quality_list)
        rows = library_support._build_library_rows(api, "run_xyz")

        missing_fr_count = sum(
            1 for r in rows if library_support._row_subs_missing_fr(r)
        )
        quality_missing_fr_count = sum(
            1
            for r in rows
            if not any(lang.startswith("fr") for lang in r.get("subtitle_languages") or [])
        )

        self.assertEqual(missing_fr_count, 0, "Tous ont FR embarque -> 0 missing")
        self.assertEqual(missing_fr_count, quality_missing_fr_count)


if __name__ == "__main__":
    unittest.main()
