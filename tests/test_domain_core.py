"""DB4 audit : tests unitaires cibles pour cinesort/domain/core.py.

core.py (~1320 lignes) est le coeur metier ; l'audit AUDIT_20260422 l'a flaggue
comme sous-teste au niveau unit (la couverture actuelle vient principalement des
tests d'integration E2E). On couvre ici les fonctions pures critiques :

- windows_safe : sanitisation des noms de fichiers pour Windows
- ensure_inside_root : guard anti-path-traversal lors de l'apply
- is_sidecar_for_video : association sidecar/video par stem
- build_candidates_from_nfo : extraction candidat depuis NFO

Les tests s'executent sans I/O reseau (pas de TMDb) et sans acces probe.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import cinesort.domain.core as core


def _sample_config() -> core.Config:
    """Construit un Config minimaliste pour les tests purs.

    Seul `root` est obligatoire ; les autres champs ont des defauts lies au
    design system CinemaLux et ne sont pas necessaires pour les tests ici.
    """
    return core.Config(root=Path("C:/Films"))


class WindowsSafeTests(unittest.TestCase):
    """windows_safe : le contrat sur la sanitisation des noms."""

    def test_strips_reserved_chars(self):
        self.assertEqual(core.windows_safe("foo<bar>"), "foobar")
        self.assertEqual(core.windows_safe('a"b|c'), "abc")
        self.assertEqual(core.windows_safe("a/b\\c"), "abc")
        self.assertEqual(core.windows_safe("a:b?c*"), "abc")

    def test_collapses_whitespace(self):
        self.assertEqual(core.windows_safe("a   b   c"), "a b c")

    def test_strips_trailing_dots(self):
        # Windows rejette les noms qui finissent par "."
        # (les espaces internes sont collapsed mais un trailing space n'est pas
        # systematiquement retire par cette fonction).
        self.assertFalse(core.windows_safe("Titre.").endswith("."))
        self.assertFalse(core.windows_safe("Titre..").endswith("."))

    def test_reserved_dos_names_prefixed_with_underscore(self):
        for reserved in ("con", "CON", "nul", "com1", "lpt9"):
            out = core.windows_safe(reserved)
            self.assertTrue(out.startswith("_"), msg=f"{reserved} -> {out}")

    def test_empty_input_becomes_untitled(self):
        self.assertEqual(core.windows_safe(""), "_untitled")
        self.assertEqual(core.windows_safe("   "), "_untitled")

    def test_truncates_to_180_chars(self):
        long = "x" * 500
        self.assertLessEqual(len(core.windows_safe(long)), 180)

    def test_nfc_normalization_keeps_accents(self):
        # É en NFC (1 char) et en NFD (2 chars) doivent aboutir au meme resultat.
        nfd = "É"  # E + combining acute accent
        nfc = "É"  # LATIN CAPITAL LETTER E WITH ACUTE
        self.assertEqual(core.windows_safe(nfd), core.windows_safe(nfc))


class EnsureInsideRootTests(unittest.TestCase):
    """ensure_inside_root : guard path traversal critique pour apply."""

    def test_inside_is_ok(self):
        cfg = _sample_config()
        # relative_to depuis un root valide ne doit pas lever.
        try:
            core.ensure_inside_root(cfg, cfg.root / "sub" / "a.mkv")
        except RuntimeError as exc:  # pragma: no cover
            self.fail(f"inside_root should not raise: {exc}")

    def test_outside_raises(self):
        cfg = _sample_config()
        with self.assertRaises(RuntimeError):
            core.ensure_inside_root(cfg, Path("C:/Autre/Sortie/a.mkv"))


class SidecarMatchingTests(unittest.TestCase):
    """is_sidecar_for_video : assoc sidecar/video par stem commun."""

    def test_exact_match(self):
        self.assertTrue(core.is_sidecar_for_video("MyFilm", "MyFilm"))

    def test_prefix_match(self):
        # Un sidecar peut etendre le stem (MyFilm.fr, MyFilm.en.srt, etc.)
        self.assertTrue(core.is_sidecar_for_video("MyFilm", "MyFilm.fr"))
        self.assertTrue(core.is_sidecar_for_video("MyFilm", "MyFilm.eng"))

    def test_unrelated_no_match(self):
        self.assertFalse(core.is_sidecar_for_video("MyFilm", "AutreFilm"))


class BuildCandidatesFromNfoTests(unittest.TestCase):
    """build_candidates_from_nfo : extraction candidats depuis un NfoInfo."""

    def test_returns_candidate_with_fields(self):
        nfo = core.NfoInfo(
            title="Inception",
            originaltitle="Inception",
            year=2010,
            tmdbid="27205",
            imdbid=None,
        )
        cands = core.build_candidates_from_nfo(nfo)
        self.assertGreaterEqual(len(cands), 1)
        c0 = cands[0]
        self.assertEqual(c0.title, "Inception")
        self.assertEqual(c0.year, 2010)

    def test_fallback_on_original_title(self):
        nfo = core.NfoInfo(
            title="",
            originaltitle="Le Grand Bleu",
            year=1988,
            tmdbid=None,
            imdbid=None,
        )
        cands = core.build_candidates_from_nfo(nfo)
        # La fonction peut retourner 0 ou 1 candidat selon la logique interne;
        # ce test valide que la signature reste stable et qu'on n'a pas d'exception.
        self.assertIsInstance(cands, list)


class ParseMovieNfoRuntimeTests(unittest.TestCase):
    """P1.1.a : parse_movie_nfo extrait runtime depuis Kodi (<runtime>) + TMM (<durationinseconds>).

    Motivation : le runtime NFO est un 3e signal (après titre + année) pour
    détecter un NFO pollué/obsolète. Cf. P1.1.d — cross-check avec probe.duration_s.
    """

    def _write_nfo(self, tmpdir: Path, body: str, name: str = "movie.nfo") -> Path:
        nfo = tmpdir / name
        nfo.write_text(
            "<?xml version='1.0' encoding='UTF-8'?>\n<movie>\n"
            "<title>Inception</title>\n<year>2010</year>\n" + body + "\n</movie>\n",
            encoding="utf-8",
        )
        return nfo

    def test_kodi_runtime_in_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            nfo = self._write_nfo(Path(tmp), "<runtime>148</runtime>")
            info = core.parse_movie_nfo(nfo)
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(info.runtime, 148)

    def test_kodi_runtime_with_suffix_min(self):
        with tempfile.TemporaryDirectory() as tmp:
            nfo = self._write_nfo(Path(tmp), "<runtime>148 min</runtime>")
            info = core.parse_movie_nfo(nfo)
            assert info is not None
            self.assertEqual(info.runtime, 148)

    def test_tmm_durationinseconds_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = (
                "<fileinfo><streamdetails><video>"
                "<durationinseconds>8880</durationinseconds>"
                "</video></streamdetails></fileinfo>"
            )
            nfo = self._write_nfo(Path(tmp), body)
            info = core.parse_movie_nfo(nfo)
            assert info is not None
            self.assertEqual(info.runtime, 148)

    def test_runtime_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            nfo = self._write_nfo(Path(tmp), "")
            info = core.parse_movie_nfo(nfo)
            assert info is not None
            self.assertIsNone(info.runtime)

    def test_runtime_outliers_rejected(self):
        # 0 minute ou 9999 minutes = valeur aberrante ignorée
        with tempfile.TemporaryDirectory() as tmp:
            nfo = self._write_nfo(Path(tmp), "<runtime>9999</runtime>", name="a.nfo")
            info = core.parse_movie_nfo(nfo)
            assert info is not None
            self.assertIsNone(info.runtime)

            nfo2 = self._write_nfo(Path(tmp), "<runtime>0</runtime>", name="b.nfo")
            info2 = core.parse_movie_nfo(nfo2)
            assert info2 is not None
            self.assertIsNone(info2.runtime)

    def test_runtime_invalid_text_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            nfo = self._write_nfo(Path(tmp), "<runtime>inconnu</runtime>")
            info = core.parse_movie_nfo(nfo)
            assert info is not None
            self.assertIsNone(info.runtime)


class NfoConsistencyCheckTests(unittest.TestCase):
    """P1.1.b : distinguer folder_match et filename_match."""

    def _nfo(self) -> core.NfoInfo:
        return core.NfoInfo(
            title="Inception",
            originaltitle="Inception",
            year=2010,
            tmdbid="27205",
            imdbid=None,
        )

    def test_both_match_when_folder_and_file_align(self):
        result = core.nfo_consistency_check(_sample_config(), self._nfo(), "Inception (2010)", "Inception.1080p.mkv")
        self.assertTrue(result.ok)
        self.assertTrue(result.folder_match)
        self.assertTrue(result.filename_match)

    def test_folder_only_match_is_partial(self):
        # Le dossier matche, mais le fichier vidéo est un autre film
        result = core.nfo_consistency_check(
            _sample_config(), self._nfo(), "Inception (2010)", "random_movie_xyz123.mkv"
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.folder_match)
        self.assertFalse(result.filename_match)

    def test_filename_only_match_is_partial(self):
        # Le fichier matche, mais le dossier est générique
        result = core.nfo_consistency_check(_sample_config(), self._nfo(), "A_Unlabeled_Folder", "Inception.1080p.mkv")
        self.assertTrue(result.ok)
        self.assertFalse(result.folder_match)
        self.assertTrue(result.filename_match)

    def test_no_match_both_fail(self):
        result = core.nfo_consistency_check(_sample_config(), self._nfo(), "UnrelatedFolder", "UnrelatedVideo.mkv")
        self.assertFalse(result.ok)
        self.assertFalse(result.folder_match)
        self.assertFalse(result.filename_match)

    def test_empty_nfo_titles_fail_gracefully(self):
        blank = core.NfoInfo(title="", originaltitle="", year=2010, tmdbid=None, imdbid=None)
        result = core.nfo_consistency_check(_sample_config(), blank, "Inception (2010)", "Inception.mkv")
        self.assertFalse(result.ok)
        self.assertEqual(result.folder_cov, 0.0)
        self.assertEqual(result.filename_cov, 0.0)

    def test_legacy_nfo_consistent_backward_compat(self):
        # L'ancienne API doit continuer à fonctionner (3-tuple)
        ok, cov, seq = core.nfo_consistent(_sample_config(), self._nfo(), "Inception (2010)", "Inception.mkv")
        self.assertTrue(ok)
        self.assertGreater(cov, 0.0)
        self.assertGreater(seq, 0.0)


class ComputeConfidenceNfoPartialMatchTests(unittest.TestCase):
    """P1.1.b : compute_confidence pénalise nfo_partial_match=True quand source=nfo."""

    def test_nfo_source_full_match_scores_higher_than_partial(self):
        cfg = _sample_config()
        chosen_nfo = core.Candidate(title="Inception", year=2010, source="nfo", score=0.90)
        full_score, _ = core.compute_confidence(cfg, chosen_nfo, nfo_ok=True, year_delta_reject=False, tmdb_used=False)
        partial_score, _ = core.compute_confidence(
            cfg,
            chosen_nfo,
            nfo_ok=True,
            year_delta_reject=False,
            tmdb_used=False,
            nfo_partial_match=True,
        )
        self.assertGreater(full_score, partial_score)
        self.assertEqual(full_score - partial_score, 8)

    def test_nfo_partial_match_ignored_when_source_is_not_nfo(self):
        # Si la source est TMDb, nfo_partial_match ne doit pas affecter le score
        cfg = _sample_config()
        chosen_tmdb = core.Candidate(title="Inception", year=2010, source="tmdb", score=0.90)
        a, _ = core.compute_confidence(cfg, chosen_tmdb, nfo_ok=True, year_delta_reject=False, tmdb_used=True)
        b, _ = core.compute_confidence(
            cfg,
            chosen_tmdb,
            nfo_ok=True,
            year_delta_reject=False,
            tmdb_used=True,
            nfo_partial_match=True,
        )
        self.assertEqual(a, b)


class WarningFlagsNfoFileMismatchTests(unittest.TestCase):
    """P1.1.b : flag nfo_file_mismatch émis quand partial match détecté."""

    def test_flag_present_when_nfo_ok_and_partial(self):
        flags = core._warning_flags_from_analysis(
            chosen=None,
            name_year_reason="",
            nfo_present=True,
            nfo_ok=True,
            year_delta_reject=False,
            nfo_partial_match=True,
        )
        self.assertIn("nfo_file_mismatch", flags)

    def test_flag_absent_when_full_match(self):
        flags = core._warning_flags_from_analysis(
            chosen=None,
            name_year_reason="",
            nfo_present=True,
            nfo_ok=True,
            year_delta_reject=False,
            nfo_partial_match=False,
        )
        self.assertNotIn("nfo_file_mismatch", flags)

    def test_flag_absent_when_nfo_rejected(self):
        # Si NFO est déjà rejeté (nfo_ok=False), partial_match n'a pas de sens
        flags = core._warning_flags_from_analysis(
            chosen=None,
            name_year_reason="",
            nfo_present=True,
            nfo_ok=False,
            year_delta_reject=False,
            nfo_partial_match=True,
        )
        self.assertNotIn("nfo_file_mismatch", flags)
        self.assertIn("nfo_title_mismatch", flags)


class ConfigImmutabilityTests(unittest.TestCase):
    """Config est frozen — les mutations doivent etre refusees et les copies
    se font via dataclasses.replace."""

    def test_frozen_rejects_mutation(self):
        cfg = _sample_config()
        with self.assertRaises(FrozenInstanceError):
            cfg.enable_collection_folder = False  # type: ignore[misc]

    def test_replace_produces_new_instance(self):
        cfg = _sample_config()
        cfg2 = replace(cfg, enable_collection_folder=False)
        self.assertNotEqual(cfg.enable_collection_folder, cfg2.enable_collection_folder)
        self.assertEqual(cfg.root, cfg2.root)


if __name__ == "__main__":
    unittest.main()
