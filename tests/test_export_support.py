"""Tests unitaires pour export_support (HTML, NFO, CSV enrichi)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cinesort.app.export_support import (
    _build_nfo_xml,
    export_html_report,
    export_nfo_for_run,
)

_IS_WINDOWS = os.name == "nt"


def _make_dir_link(link: Path, target: Path) -> None:
    """Cree un lien de dossier vers `target` (meme approche que l'issue #517).

    Sous Windows : une VRAIE jonction NTFS (`mklink /J`), que `is_symlink()` ne
    voit pas — c'est ce qui rend le containment lexical insuffisant. Sa creation
    ne demande aucun privilege : un echec est une erreur dure, jamais un skip.
    """
    if _IS_WINDOWS:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not link.exists():
            raise AssertionError(f"mklink /J a echoue (rc={proc.returncode}): {proc.stdout} {proc.stderr}")
        return
    link.symlink_to(target, target_is_directory=True)


def _make_report(rows=None, counts=None):
    """Helper : construit un report payload minimal pour les tests."""
    default_counts = {
        "rows_total": 3,
        "validated_ok": 2,
        "quality_reports": 3,
        "quality_probe_partial": 0,
        "quality_tiers": {"premium": 1, "bon": 1, "moyen": 1},
    }
    default_rows = [
        {
            "run_id": "test-run-001",
            "row_id": "r1",
            "kind": "single",
            "folder": "D:\\Films\\Avatar (2009)",
            "video": "Avatar.mkv",
            "proposed_title": "Avatar",
            "proposed_year": 2009,
            "proposed_source": "nfo",
            "confidence": 95,
            "confidence_label": "high",
            "decision_ok": True,
            "decision_title": "Avatar",
            "decision_year": 2009,
            "quality_status": "analyzed",
            "quality_score": 92,
            "quality_tier": "premium",
            "probe_quality": "COMPLETE",
            "quality_resolution": "2160p",
            "quality_video_codec": "hevc",
            "quality_bitrate_kbps": 45000,
            "quality_audio_codec": "truehd",
            "quality_audio_channels": 8,
            "quality_hdr": "HDR10 + DV",
            "quality_subscore_video": 88,
            "quality_subscore_audio": 95,
            "quality_subscore_extras": 90,
            "quality_explanation": "Excellent encodage 4K HDR",
            "warning_flags": "",
            "nfo_present": True,
            "notes": "",
        },
    ]
    return {
        "run_id": "test-run-001",
        "generated_at": "2026-04-03 15:00:00",
        "run": {"root": "D:\\Films", "status": "DONE"},
        "counts": counts if counts is not None else default_counts,
        "rows": rows if rows is not None else default_rows,
    }


class TestHtmlReport(unittest.TestCase):
    """Tests pour export_html_report."""

    def test_contains_html_structure(self):
        html = export_html_report(_make_report())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)
        self.assertIn("CineSort", html)

    def test_contains_run_id(self):
        html = export_html_report(_make_report())
        self.assertIn("test-run-001", html)

    def test_contains_stats_cards(self):
        html = export_html_report(_make_report())
        self.assertIn("Films analysés", html)
        self.assertIn("Validés OK", html)

    def test_contains_svg_chart(self):
        html = export_html_report(_make_report())
        self.assertIn("<svg", html)
        # U1 audit : tiers renommes Platinum/Gold/Silver/Bronze/Reject.
        self.assertIn("Platinum", html)
        self.assertIn("Gold", html)

    def test_tier_colors_are_invariant(self):
        """GATE AUDIT 2026-06-10 : l'export HTML doit utiliser les couleurs tier
        INVARIANTES (memoire user / CLAUDE.md #2), pas les anciennes fausses."""
        from cinesort.app.export_support import _TIER_COLORS

        self.assertEqual(_TIER_COLORS["platinum"].upper(), "#E5E4E2")
        self.assertEqual(_TIER_COLORS["gold"].upper(), "#FFD700")
        self.assertEqual(_TIER_COLORS["silver"].upper(), "#C0C0C0")
        self.assertEqual(_TIER_COLORS["bronze"].upper(), "#CD7F32")
        # retro-compat alignee aussi
        self.assertEqual(_TIER_COLORS["bon"].upper(), "#FFD700")
        # plus aucune des anciennes couleurs fausses
        for bad in ("#e2e8f0", "#f59e0b", "#94a3b8", "#ca8a04"):
            self.assertNotIn(bad, [v.lower() for v in _TIER_COLORS.values()])

    def test_contains_table(self):
        html = export_html_report(_make_report())
        self.assertIn("Avatar", html)
        self.assertIn("2009", html)
        self.assertIn("<table", html)

    def test_empty_rows(self):
        report = _make_report(
            rows=[], counts={"rows_total": 0, "validated_ok": 0, "quality_reports": 0, "quality_tiers": {}}
        )
        html = export_html_report(report)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Détail des films (0)", html)

    def test_html_escapes_title(self):
        rows = _make_report()["rows"]
        rows[0]["proposed_title"] = '<script>alert("xss")</script>'
        html = export_html_report(_make_report(rows=rows))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestBuildNfoXml(unittest.TestCase):
    """Tests pour _build_nfo_xml."""

    def test_basic_nfo(self):
        xml = _build_nfo_xml("Avatar", 2009)
        self.assertIn("<title>Avatar</title>", xml)
        self.assertIn("<year>2009</year>", xml)
        self.assertIn('<?xml version="1.0"', xml)

    def test_with_tmdb_id(self):
        xml = _build_nfo_xml("Avatar", 2009, tmdb_id="19995")
        self.assertIn('type="tmdb"', xml)
        self.assertIn("19995", xml)

    def test_with_imdb_id(self):
        xml = _build_nfo_xml("Avatar", 2009, imdb_id="tt0499549")
        self.assertIn('type="imdb"', xml)
        self.assertIn("tt0499549", xml)

    def test_original_title(self):
        xml = _build_nfo_xml("Mon Voisin Totoro", 1988, original_title="Tonari no Totoro")
        self.assertIn("<originaltitle>Tonari no Totoro</originaltitle>", xml)

    def test_no_original_title_when_same(self):
        xml = _build_nfo_xml("Avatar", 2009, original_title="Avatar")
        self.assertNotIn("<originaltitle>", xml)

    def test_no_year_zero(self):
        xml = _build_nfo_xml("Test", 0)
        self.assertNotIn("<year>", xml)


class TestExportNfoForRun(unittest.TestCase):
    """Tests pour export_nfo_for_run."""

    def test_dry_run_no_file_written(self):
        rows = [{"folder": "D:\\Films\\Test", "video": "test.mkv", "proposed_title": "Test", "proposed_year": 2020}]
        result = export_nfo_for_run(rows, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["written"], 1)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["details"][0]["status"], "would_write")

    def test_skip_no_data(self):
        rows = [{"folder": "", "video": "", "proposed_title": "", "proposed_year": 0}]
        result = export_nfo_for_run(rows, dry_run=True)
        self.assertEqual(result["skipped_no_data"], 1)
        self.assertEqual(result["written"], 0)

    def test_skip_existing_nfo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "film.mkv"
            nfo = Path(tmpdir) / "film.nfo"
            video.touch()
            nfo.write_text("<movie></movie>", encoding="utf-8")
            rows = [{"folder": tmpdir, "video": "film.mkv", "proposed_title": "Film", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=False, dry_run=False)
            self.assertEqual(result["skipped_existing"], 1)
            self.assertEqual(result["written"], 0)

    def test_write_nfo_real(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "film.mkv", "proposed_title": "Mon Film", "proposed_year": 2024}]
            result = export_nfo_for_run(rows, overwrite=False, dry_run=False)
            self.assertEqual(result["written"], 1)
            nfo_path = Path(tmpdir) / "film.nfo"
            self.assertTrue(nfo_path.exists())
            content = nfo_path.read_text(encoding="utf-8")
            self.assertIn("<title>Mon Film</title>", content)
            self.assertIn("<year>2024</year>", content)

    def test_overwrite_existing_nfo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nfo = Path(tmpdir) / "film.nfo"
            nfo.write_text("<movie><title>Old</title></movie>", encoding="utf-8")
            rows = [{"folder": tmpdir, "video": "film.mkv", "proposed_title": "New", "proposed_year": 2024}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["written"], 1)
            content = nfo.read_text(encoding="utf-8")
            self.assertIn("<title>New</title>", content)


class TestNfoYearIsolation(unittest.TestCase):
    """Issue #720 — une annee non numerique isole SA row, sans avorter l'export."""

    def test_bad_year_does_not_abort_the_whole_export(self):
        """Le coeur du defaut : avant, `int("N/A")` remontait et tuait l'export entier."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"folder": tmpdir, "video": "casse.mkv", "proposed_title": "Casse", "proposed_year": "N/A"},
                {"folder": tmpdir, "video": "bon.mkv", "proposed_title": "Bon", "proposed_year": 2020},
            ]
            result = export_nfo_for_run(rows, dry_run=False)
            # le film sain est bel et bien exporte
            self.assertEqual(result["written"], 1)
            self.assertTrue((Path(tmpdir) / "bon.nfo").exists())
            # la row fautive est signalee, pas avalee
            self.assertEqual(result["errors"], 1)
            self.assertFalse((Path(tmpdir) / "casse.nfo").exists())
            statuses = [d["status"] for d in result["details"]]
            self.assertTrue(any(s.startswith("error:") and "annee" in s for s in statuses), statuses)

    def test_bad_decision_year_is_not_silently_replaced_by_proposed_year(self):
        """Une annee de decision fautive se signale, elle ne retombe pas en douce."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {
                    "folder": tmpdir,
                    "video": "x.mkv",
                    "proposed_title": "X",
                    "decision_year": "????",
                    "proposed_year": 1999,
                }
            ]
            result = export_nfo_for_run(rows, dry_run=True)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(result["written"], 0)

    def test_year_as_numeric_string_still_works(self):
        """Une annee JSON serialisee en chaine reste une annee valide."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": "2011"}]
            result = export_nfo_for_run(rows, dry_run=True)
            self.assertEqual(result["written"], 1)
            self.assertEqual(result["errors"], 0)

    def test_missing_year_is_not_an_error(self):
        """Une annee absente reste toleree (annee 0 = omise du NFO), ce n'est pas une erreur."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X"}]
            result = export_nfo_for_run(rows, dry_run=True)
            self.assertEqual(result["written"], 1)
            self.assertEqual(result["errors"], 0)

    def test_zero_year_sentinel_is_not_an_error(self):
        """0 et "0" sont la sentinelle « annee absente » du payload amont."""
        for sentinel in (0, "0"):
            with self.subTest(year=sentinel), tempfile.TemporaryDirectory() as tmpdir:
                rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": sentinel}]
                result = export_nfo_for_run(rows, dry_run=True)
                self.assertEqual(result["written"], 1)
                self.assertEqual(result["errors"], 0)

    def test_underscore_separator_is_not_silently_reinterpreted(self):
        """`int("1_999")` vaut 1999 : accepter cette valeur ecrirait une AUTRE annee."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": "1_999"}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(result["written"], 0)
            self.assertFalse((Path(tmpdir) / "x.nfo").exists())

    def test_year_outside_plausible_range_is_refused(self):
        """`<year>-500</year>` est ignore EN SILENCE par Kodi et Jellyfin."""
        for bad in ("-500", -500, 99999):
            with self.subTest(year=bad), tempfile.TemporaryDirectory() as tmpdir:
                rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": bad}]
                result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
                self.assertEqual(result["errors"], 1)
                self.assertEqual(result["written"], 0)

    def test_fractional_float_year_is_refused_instead_of_truncated(self):
        """`int(2020.7)` tronque a 2020 : une valeur reinterpretee sans le dire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": 2020.7}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(result["written"], 0)

    def test_integral_float_year_still_works(self):
        """Une annee JSON deserialisee en float entier reste une annee valide."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": 2020.0}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["written"], 1)
            self.assertIn("<year>2020</year>", (Path(tmpdir) / "x.nfo").read_text(encoding="utf-8"))


class TestNfoPathContainment(unittest.TestCase):
    """Issue #564 (CWE-22) — le .nfo ne peut pas s'ecrire hors du dossier du film."""

    def test_parent_traversal_in_video_is_refused_and_writes_nothing(self):
        """Un `..` dans `video` remontait d'un cran et ecrivait hors du dossier du film."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "film"
            base.mkdir()
            rows = [{"folder": str(base), "video": "../evil.mkv", "proposed_title": "Evil", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(result["written"], 0)
            self.assertFalse((Path(tmpdir) / "evil.nfo").exists())

    def test_absolute_video_path_is_refused(self):
        """`Path(folder) / video` avec `video` absolu ecrase le folder : la cible sort du dossier."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "film"
            base.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            rows = [
                {
                    "folder": str(base),
                    "video": str(outside / "pwned.mkv"),
                    "proposed_title": "Pwned",
                    "proposed_year": 2020,
                }
            ]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["errors"], 1)
            self.assertFalse((outside / "pwned.nfo").exists())

    def test_traversal_is_refused_in_dry_run_too(self):
        """Le dry-run ne doit pas annoncer `would_write` sur un chemin qu'on refuserait."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "film"
            base.mkdir()
            rows = [{"folder": str(base), "video": "../evil.mkv", "proposed_title": "Evil", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, dry_run=True)
            self.assertEqual(result["written"], 0)
            self.assertEqual(result["errors"], 1)

    def test_nested_subfolder_video_stays_allowed(self):
        """Le containment ne doit pas interdire un video range dans un sous-dossier."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "sub").mkdir()
            rows = [{"folder": tmpdir, "video": "sub/film.mkv", "proposed_title": "Film", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["written"], 1)
            self.assertTrue((Path(tmpdir) / "sub" / "film.nfo").exists())

    def test_directory_junction_escape_is_refused(self):
        """La docstring annonce que le containment couvre les liens : on l'eprouve.

        Un sous-dossier du film qui est une jonction NTFS (ou un lien
        symbolique) vers l'exterieur : le chemin est LEXICALEMENT contenu, seul
        le containment sur les chemins RESOLUS peut le refuser.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "film"
            base.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            _make_dir_link(base / "lien", outside)

            rows = [{"folder": str(base), "video": "lien/pwned.mkv", "proposed_title": "Pwned", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(result["written"], 0)
            self.assertFalse((outside / "pwned.nfo").exists())

    def test_refused_row_does_not_reflect_the_tampered_path(self):
        """Coherence avec #427 : la valeur refusee est loggee, pas renvoyee a l'UI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "film"
            base.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            tampered = str(outside / "pwned.mkv")
            rows = [{"folder": str(base), "video": tampered, "proposed_title": "Pwned", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["errors"], 1)
            reflected = " ".join(f"{d.get('path')} {d.get('status')}" for d in result["details"])
            self.assertNotIn("pwned", reflected.lower(), reflected)

    def test_written_path_is_the_one_that_was_validated(self):
        """On ecrit sur le chemin RESOLU, celui sur lequel le containment a porte.

        `sub/../x.mkv` reste dans le dossier du film, mais son chemin BRUT
        traverse `sub` : ecrire dessus rouvre la fenetre entre la verification
        et l'ecriture (`sub` transforme en lien entre les deux). pathlib ne
        replie pas `..`, la difference brut/resolu est donc observable.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "film"
            (base / "sub").mkdir(parents=True)
            rows = [{"folder": str(base), "video": "sub/../x.mkv", "proposed_title": "X", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["written"], 1)
            announced = Path(result["details"][0]["path"])
            self.assertNotIn("..", announced.parts)
            self.assertEqual(announced, announced.resolve())
            self.assertTrue(announced.is_file())


class TestNfoProviderIds(unittest.TestCase):
    """Issue #612 — tmdb_id/imdb_id doivent atterrir dans le .nfo."""

    def test_row_ids_are_written_into_the_nfo(self):
        """Bout en bout : les identifiants de la row atterrissent dans le fichier ecrit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {
                    "folder": tmpdir,
                    "video": "avatar.mkv",
                    "proposed_title": "Avatar",
                    "proposed_year": 2009,
                    "original_title": "Avatar: The Way of Water",
                    "tmdb_id": 19995,
                    "imdb_id": "tt0499549",
                }
            ]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["written"], 1)
            content = (Path(tmpdir) / "avatar.nfo").read_text(encoding="utf-8")
            self.assertIn('<uniqueid type="tmdb" default="true">19995</uniqueid>', content)
            self.assertIn('<uniqueid type="imdb">tt0499549</uniqueid>', content)
            self.assertIn("<originaltitle>Avatar: The Way of Water</originaltitle>", content)

    def test_malformed_imdb_id_is_not_written(self):
        """Un imdb_id hors format empeche Jellyfin de telecharger les jaquettes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {
                    "folder": tmpdir,
                    "video": "x.mkv",
                    "proposed_title": "X",
                    "proposed_year": 2009,
                    "imdb_id": "not-an-imdb-id",
                }
            ]
            export_nfo_for_run(rows, overwrite=True, dry_run=False)
            content = (Path(tmpdir) / "x.nfo").read_text(encoding="utf-8")
            self.assertNotIn("not-an-imdb-id", content)
            self.assertNotIn("uniqueid", content)

    def test_sentinel_zero_tmdb_id_is_treated_as_absent(self):
        """0 est la sentinelle « absent » du payload amont, pas un identifiant fautif."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "x.mkv", "proposed_title": "X", "proposed_year": 2009, "tmdb_id": 0}]
            export_nfo_for_run(rows, overwrite=True, dry_run=False)
            content = (Path(tmpdir) / "x.nfo").read_text(encoding="utf-8")
            self.assertNotIn("uniqueid", content)


class TestNfoDefaultUniqueId(unittest.TestCase):
    """Issue #612 — Kodi ne retient que l'uniqueid marque default="true"."""

    def test_imdb_becomes_default_when_tmdb_absent(self):
        """Sans TMDb, IMDb doit porter `default="true"` sinon Kodi perd l'appariement."""
        xml = _build_nfo_xml("Avatar", 2009, imdb_id="tt0499549")
        self.assertIn('<uniqueid type="imdb" default="true">tt0499549</uniqueid>', xml)

    def test_exactly_one_default_when_both_ids_present(self):
        """Kodi ne garde qu'un identifiant par defaut : il ne doit y en avoir qu'un de marque."""
        xml = _build_nfo_xml("Avatar", 2009, tmdb_id="19995", imdb_id="tt0499549")
        self.assertEqual(xml.count('default="true"'), 1)
        self.assertIn('<uniqueid type="tmdb" default="true">19995</uniqueid>', xml)
        self.assertIn('<uniqueid type="imdb">tt0499549</uniqueid>', xml)


class TestCsvEnrichedPayload(unittest.TestCase):
    """Tests pour le CSV enrichi via dashboard_support."""

    def test_csv_has_enriched_columns(self):
        from cinesort.ui.api.dashboard_support import report_to_csv_text

        report = _make_report()
        csv_text = report_to_csv_text(report)
        # Vérifier les en-têtes enrichis
        header = csv_text.split("\n")[0]
        self.assertIn("confidence;", header)
        self.assertIn("quality_resolution", header)
        self.assertIn("quality_video_codec", header)
        self.assertIn("quality_bitrate_kbps", header)
        self.assertIn("quality_audio_codec", header)
        self.assertIn("quality_hdr", header)
        self.assertIn("warning_flags", header)
        self.assertIn("nfo_present", header)

    def test_csv_row_data(self):
        from cinesort.ui.api.dashboard_support import report_to_csv_text

        report = _make_report()
        csv_text = report_to_csv_text(report)
        lines = csv_text.strip().split("\n")
        self.assertEqual(len(lines), 2)  # header + 1 data row
        self.assertIn("Avatar", lines[1])
        self.assertIn("2160p", lines[1])
        self.assertIn("hevc", lines[1])


class TestHdrLabel(unittest.TestCase):
    """Tests pour _hdr_label dans dashboard_support."""

    def test_sdr(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({}), "SDR")

    def test_hdr10(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({"hdr10": True}), "HDR10")

    def test_dolby_vision(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({"hdr_dolby_vision": True}), "DV")

    def test_dv_plus_hdr10(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({"hdr_dolby_vision": True, "hdr10": True}), "DV + HDR10")


if __name__ == "__main__":
    unittest.main()
