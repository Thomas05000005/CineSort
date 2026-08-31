"""Regression — ultra-audit 2026-08-03 : classe de resolution et codec audio canoniques.

Quatre defauts distincts, tous nes du meme reflexe (lire une valeur BRUTE du
probe la ou une valeur CANONIQUE existe deja) :

1. ``quality_score`` : ``_apply_era_bonuses_helper`` recevait la hauteur ffprobe
   BRUTE. Un 1080p scope 2.35:1 mesure 1920x800 -> ``height >= 1080`` faux ->
   bonus « classique » (+4) au lieu de « patrimoine » (+8), soit un tier entier
   perdu sur toute la plage de debit realiste, uniquement a cause du ratio.
2. ``duplicate_compare`` : le critere « Resolution » comparait la hauteur BRUTE.
   Deux crops du meme film (1920x800 vs 1920x816) s'affichaient « 720p vs 720p »
   et produisaient malgre tout un delta de 30 points -> « Garder B, archiver A »
   sur le fichier 6,7x mieux debite, applicable en masse via « Auto-decider tous ».
3. ``quality_report_support`` : ``api._tmdb_client()`` n'existe pas sur
   CineSortApi ; le ``hasattr`` avalait l'absence -> tout le scoring genre-aware
   P4.2 etait du code mort. Le rallumer exige de desamorcer d'abord le meme piege
   de hauteur brute dans ``_apply_genre_adjustments_helper`` (genre_rules teste
   ``height < 1080``).
4. ``quality_score`` : ffprobe range 'DTS-HD MA' dans ``profile`` et l'Atmos dans
   ``is_atmos``, jamais dans ``codec``. Tous les consommateurs lisaient donc
   'dts' -> bonus +6 au lieu de +10, token de hierarchie inatteignable, bucket
   dashboard « DTS-HD MA » toujours vide, et un probe qui ECHOUE (fallback par le
   nom, qui synthetise 'dts-hd ma') scorait MIEUX qu'un probe qui reussit.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from cinesort.domain import compute_quality_score, default_quality_profile
from cinesort.domain.duplicate_compare import compare_by_criteria, compare_duplicates
from cinesort.domain.quality_score import (
    _apply_genre_adjustments_helper,
    _audio_codec_rank,
    _best_audio_track,
    _canonical_audio_codec,
    _hierarchy_audio_codec_token,
)
from cinesort.ui.api import quality_report_support

# Racine bidon : aucune I/O n'a lieu (ProbeService et le store sont mockes).
# On evite volontairement `/tmp` (Bandit B108) alors qu'aucun fichier temporaire
# n'est cree ici.
_FAKE_ROOT = "Z:/films-de-test"


def _probe(
    *,
    width: int = 1920,
    height: int = 1080,
    codec: str = "h264",
    bitrate_kbps: int = 12000,
    audio: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "probe_quality": "FULL",
        "video": {
            "width": width,
            "height": height,
            "codec": codec,
            "bitrate": bitrate_kbps * 1000,
            "bit_depth": 8,
        },
        "audio_tracks": (
            audio if audio is not None else [{"codec": "ac3", "channels": 6, "language": "eng", "bitrate": 640_000}]
        ),
        "subtitles": [{"language": "fra"}],
    }


def _score(normalized: Dict[str, Any], *, film_year: Optional[int] = None, release_name: str = "Film.mkv"):
    return compute_quality_score(
        normalized_probe=normalized,
        profile=default_quality_profile(),
        folder_name="Film (1965)",
        expected_title="Film",
        expected_year=film_year or 0,
        release_name=release_name,
        film_year=film_year,
    )


def _reasons(res: Dict[str, Any]) -> str:
    return " || ".join(res.get("reasons") or [])


class EraBonusUsesResolutionClassTests(unittest.TestCase):
    """Defaut 1 : le bonus d'ere doit suivre la CLASSE, pas la hauteur brute."""

    def test_scope_1080p_gets_heritage_bonus_like_flat_1080p(self) -> None:
        scope = _score(_probe(width=1920, height=800), film_year=1965)
        flat = _score(_probe(width=1920, height=1080), film_year=1965)
        self.assertIn("patrimoine", _reasons(scope))
        # Le payload etait auto-contradictoire : detected.resolution disait deja 1080p.
        self.assertEqual((scope["metrics"]["detected"])["resolution"], "1080p")
        self.assertEqual(scope["score"], flat["score"])
        self.assertEqual(scope["tier"], flat["tier"])

    def test_scope_720p_gets_classic_bonus(self) -> None:
        # 1280x536 = vrai 720p scope : hauteur brute 536 < 720 -> aucune raison d'ere avant.
        res = _score(_probe(width=1280, height=536, bitrate_kbps=5000), film_year=1965)
        self.assertIn("classique", _reasons(res))

    def test_true_720p_does_not_get_heritage_bonus(self) -> None:
        """Non-regression : la CLASSE reste discriminante, elle n'aplatit pas tout."""
        res = _score(_probe(width=1280, height=720, bitrate_kbps=5000), film_year=1965)
        self.assertIn("classique", _reasons(res))
        self.assertNotIn("patrimoine", _reasons(res))

    def test_sd_film_gets_no_era_bonus(self) -> None:
        """Non-regression : un vrai SD ne recoit aucun bonus d'ere."""
        res = _score(_probe(width=720, height=576, bitrate_kbps=2000), film_year=1965)
        self.assertNotIn("patrimoine", _reasons(res))
        self.assertNotIn("classique", _reasons(res))


class DuplicateResolutionClassTests(unittest.TestCase):
    """Defaut 2 : le delta du critere Resolution doit suivre l'etiquette affichee."""

    @staticmethod
    def _dup_probe(*, height: int, bitrate_kbps: int, width: int = 0) -> Dict[str, Any]:
        video: Dict[str, Any] = {"height": height, "codec": "hevc", "bitrate": bitrate_kbps * 1000}
        if width:
            video["width"] = width
        return {"video": video, "audio_tracks": [{"codec": "ac3", "channels": 6}], "duration_s": 7200}

    def _resolution_criterion(self, a: Dict[str, Any], b: Dict[str, Any]):
        return next(c for c in compare_by_criteria(a, b) if c.name == "resolution")

    def test_two_scope_crops_are_a_tie(self) -> None:
        # Cas reproduit par l'audit : affichage « 720p vs 720p » mais delta -30.
        crit = self._resolution_criterion(
            self._dup_probe(height=800, bitrate_kbps=20000),
            self._dup_probe(height=816, bitrate_kbps=3000),
        )
        self.assertEqual(crit.value_a, crit.value_b)
        self.assertEqual(crit.winner, "tie")
        self.assertEqual(crit.points_delta, 0)

    def test_mod16_padding_is_a_tie(self) -> None:
        crit = self._resolution_criterion(
            self._dup_probe(height=1080, bitrate_kbps=25000),
            self._dup_probe(height=1088, bitrate_kbps=3000),
        )
        self.assertEqual((crit.value_a, crit.value_b), ("1080p", "1080p"))
        self.assertEqual(crit.points_delta, 0)

    def test_better_bitrate_file_is_no_longer_recommended_for_archiving(self) -> None:
        r = compare_duplicates(
            self._dup_probe(height=800, bitrate_kbps=20000),
            self._dup_probe(height=816, bitrate_kbps=3000),
        )
        self.assertNotEqual(r.winner, "b")
        self.assertNotIn("archiver A", r.recommendation)

    def test_width_disambiguates_scope_from_true_720p(self) -> None:
        crit = self._resolution_criterion(
            self._dup_probe(width=1920, height=800, bitrate_kbps=12000),
            self._dup_probe(width=1920, height=1080, bitrate_kbps=6000),
        )
        self.assertEqual((crit.value_a, crit.value_b), ("1080p", "1080p"))
        self.assertEqual(crit.points_delta, 0)

    def test_canonical_label_is_honoured_when_provided(self) -> None:
        a = {"video": {"resolution": "1080p", "height": 800, "codec": "hevc"}, "audio_tracks": []}
        b = {"video": {"resolution": "1080p", "height": 1080, "codec": "hevc"}, "audio_tracks": []}
        self.assertEqual(self._resolution_criterion(a, b).points_delta, 0)

    def test_real_resolution_gap_still_decides(self) -> None:
        """Non-regression : une VRAIE difference de classe garde tout son poids."""
        crit = self._resolution_criterion(
            self._dup_probe(height=2160, bitrate_kbps=25000),
            self._dup_probe(height=1080, bitrate_kbps=25000),
        )
        self.assertEqual((crit.winner, crit.points_delta), ("a", 30))
        crit2 = self._resolution_criterion(
            self._dup_probe(height=1080, bitrate_kbps=8000),
            self._dup_probe(height=720, bitrate_kbps=8000),
        )
        self.assertEqual((crit2.winner, crit2.points_delta), ("a", 30))

    def test_sd_heights_remain_discriminated(self) -> None:
        """Non-regression : sous 720p la hauteur brute reste comparee (576 > 360).

        L'ETIQUETTE de gauche est passee de « 480p » a « 576p » le 2026-08-31
        (constat #5). Ce test asserait la moitie ANNONCE de la divergence qu'il
        gardait : `_resolution_height` compare bien 576, mais `_resolution_label`
        re-classait cette valeur avec des seuils HAUTEUR (`h >= 480 -> "480p"`),
        donc toute la plage [480..679] s'affichait « 480p » -- et deux SD de la
        meme plage (720x576 PAL contre 720x480 NTSC) sortaient « 480p vs 480p »
        avec un delta de +30. La comparaison gardee ici est INCHANGEE (winner=a,
        30 points) ; seul l'affichage dit desormais ce qui a ete compare.
        """
        crit = self._resolution_criterion(
            self._dup_probe(height=576, bitrate_kbps=2000),
            self._dup_probe(height=360, bitrate_kbps=2000),
        )
        self.assertEqual((crit.value_a, crit.value_b), ("576p", "360p"))
        self.assertEqual(crit.winner, "a")
        self.assertEqual(crit.points_delta, 30)


class GenreScoringIsReachableTests(unittest.TestCase):
    """Defaut 3 : le client TMDb doit etre construit, et le malus de resolution
    genre doit raisonner sur la classe."""

    @staticmethod
    def _row(tmdb_id: int):
        row = MagicMock()
        row.folder = f"{_FAKE_ROOT}/Movie (2015)"
        row.proposed_title = "Movie"
        row.proposed_year = 2015
        row.video = "Movie.1080p.mkv"
        candidate = MagicMock()
        candidate.tmdb_id = tmdb_id
        row.candidates = [candidate] if tmdb_id else []
        return row

    def _run(self, tmdb_id: int, tmdb_client: Any):
        api = MagicMock()
        api._effective_probe_settings_for_runtime.return_value = {}
        store = MagicMock()
        store.quality.get_quality_report.return_value = None
        with (
            patch.object(quality_report_support, "ProbeService") as probe_cls,
            patch.object(quality_report_support, "_build_tmdb_client", return_value=tmdb_client) as build,
            patch.object(quality_report_support, "compute_quality_score", return_value={}) as score,
        ):
            probe = MagicMock()
            probe.probe_file.return_value = {"normalized": _probe(), "cache_hit": False}
            probe_cls.return_value = probe
            quality_report_support._probe_and_score(
                api,
                store,
                {"state_dir": _FAKE_ROOT},
                "run_test",
                "row_1",
                self._row(tmdb_id),
                f"{_FAKE_ROOT}/Movie/Movie.mkv",
                profile_json={"id": "default", "version": 1},
                active_profile_id="default",
                active_profile_version=1,
            )
        return build, score

    def test_tmdb_genres_reach_the_scorer(self) -> None:
        tmdb = MagicMock()
        tmdb.get_movie_metadata_for_perceptual.return_value = {"genres": ["Animation", "Family"]}
        build, score = self._run(27205, tmdb)
        self.assertTrue(build.called, "le client TMDb doit etre construit (api._tmdb_client n'existe pas)")
        self.assertEqual(score.call_args.kwargs.get("tmdb_genres"), ["Animation", "Family"])

    def test_no_candidate_means_no_tmdb_call(self) -> None:
        """Non-regression : pas de tmdb_id -> aucun client construit, genres None."""
        build, score = self._run(0, MagicMock())
        self.assertFalse(build.called)
        self.assertIsNone(score.call_args.kwargs.get("tmdb_genres"))

    @staticmethod
    def _genre_score(width: int, height: int) -> Dict[str, Any]:
        return compute_quality_score(
            normalized_probe=_probe(width=width, height=height),
            profile=default_quality_profile(),
            folder_name="Film (2015)",
            expected_title="Film",
            expected_year=2015,
            release_name="Film.mkv",
            tmdb_genres=["Action"],
        )

    def test_genre_low_resolution_malus_uses_resolution_class(self) -> None:
        # genre_rules:245 teste `height < 1080` : avec la hauteur BRUTE, tout
        # 1080p scope prenait un malus « resolution modeste » alors que
        # detected.resolution affichait deja '1080p'.
        res = self._genre_score(1920, 800)
        self.assertEqual((res["metrics"]["detected"])["resolution"], "1080p")
        self.assertEqual((res["metrics"]).get("primary_genre"), "action")
        self.assertNotIn("modeste", _reasons(res))

    def test_genre_low_resolution_malus_still_fires_on_real_sd(self) -> None:
        """Non-regression : un vrai 720p garde bien son malus de genre."""
        res = self._genre_score(1280, 720)
        self.assertIn("modeste", _reasons(res))

    def test_genre_helper_reads_the_height_it_is_given(self) -> None:
        """Contrat du helper : il tranche sur `video["height"]` (que l'appelant
        alimente avec la hauteur canonique)."""
        reasons: List[str] = []
        _apply_genre_adjustments_helper(
            tmdb_genres=["Action"],
            video={"height": 1080, "codec": "h264"},
            audio_analysis=None,
            encode_warnings=None,
            video_sub=60.0,
            audio_sub=50.0,
            extras_sub=50.0,
            factors=[],
            reasons=reasons,
        )
        self.assertNotIn("modeste", " || ".join(reasons))


_DTS_HD_MA = {"codec": "dts", "profile": "DTS-HD MA", "channels": 6, "language": "eng", "bitrate": 3_000_000}


class CanonicalAudioCodecTests(unittest.TestCase):
    """Defaut 4 : la variante audio vit dans `profile` / `is_atmos`, pas dans `codec`."""

    def test_dts_hd_ma_is_detected_from_profile(self) -> None:
        res = _score(_probe(audio=[dict(_DTS_HD_MA)]))
        self.assertIn("Audio DTS-HD MA", _reasons(res))
        self.assertEqual((res["metrics"]["detected"])["audio_best_codec"], "dts-hd ma")
        self.assertEqual(_hierarchy_audio_codec_token(_DTS_HD_MA), "dts_hd_ma")

    def test_plain_dts_stays_plain_dts(self) -> None:
        """Non-regression : sans profile lossless, rien ne change."""
        plain = {"codec": "dts", "profile": "DTS", "channels": 6, "language": "eng", "bitrate": 750_000}
        res = _score(_probe(audio=[plain]))
        self.assertIn("Audio DTS", _reasons(res))
        self.assertNotIn("Audio DTS-HD MA", _reasons(res))
        self.assertEqual((res["metrics"]["detected"])["audio_best_codec"], "dts")

    def test_truehd_atmos_reaches_its_hierarchy_token(self) -> None:
        track = {"codec": "truehd", "channels": 8, "is_atmos": True}
        self.assertEqual(_canonical_audio_codec(track), "truehd atmos")
        self.assertEqual(_hierarchy_audio_codec_token(track), "truehd_atmos")
        # Le rang ne bouge pas : truehd valait deja 5.
        self.assertEqual(_audio_codec_rank(track), 5)

    def test_lossy_atmos_keeps_its_carrier_rank(self) -> None:
        """Non-regression : l'Atmos lossy (E-AC-3 JOC) ne gagne pas de rang."""
        self.assertEqual(_audio_codec_rank({"codec": "eac3", "channels": 6, "is_atmos": True}), 2)
        self.assertEqual(_audio_codec_rank({"codec": "ac3", "channels": 6}), 2)
        self.assertEqual(_audio_codec_rank({"codec": "flac", "channels": 2}), 3)

    def test_best_track_prefers_dts_hd_ma_over_flac(self) -> None:
        flac = {"codec": "flac", "channels": 2, "bitrate": 1_500_000}
        self.assertEqual(_best_audio_track([flac, dict(_DTS_HD_MA)])["profile"], "DTS-HD MA")

    def test_probe_and_name_fallback_agree_on_the_audio_label(self) -> None:
        """Le probe qui REUSSIT doit reconnaitre ce que le fallback par le NOM
        reconnaissait deja.

        Le fallback ``_merge_probe_with_name_hints`` synthetise 'dts-hd ma'
        depuis le nom de release ; le probe reel, lui, lisait 'dts' -> deux
        verdicts audio contradictoires pour le meme fichier selon que ffprobe
        avait reussi ou non (et un ecart de score en faveur de l'echec).

        NB : le reste de l'ecart de score vient des compensations du bloc
        `probe_quality == FAILED` (+22 audio / +24 extras), hors perimetre de ce
        correctif — d'ou une assertion sur le LIBELLE, pas sur le score.
        """
        release = "Dune.2021.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-GROUP"
        probed = _score(_probe(audio=[dict(_DTS_HD_MA)]), release_name=release)
        failed = _score(
            {"probe_quality": "FAILED", "video": {}, "audio_tracks": [], "subtitles": []},
            release_name=release,
        )
        self.assertIn("Audio DTS-HD MA", _reasons(failed))
        self.assertIn("Audio DTS-HD MA", _reasons(probed))

    def test_duplicate_comparator_ranks_dts_hd_ma_above_eac3(self) -> None:
        remux = {
            "video": {"height": 1080, "width": 1920, "codec": "h264", "bitrate": 28_000_000},
            "audio_tracks": [{"codec": "dts-hd ma", "channels": 6}],
            "duration_s": 7200,
        }
        webdl = {
            "video": {"height": 1080, "width": 1920, "codec": "h264", "bitrate": 9_000_000},
            "audio_tracks": [{"codec": "eac3", "channels": 6}],
            "duration_s": 7200,
        }
        crit = next(c for c in compare_by_criteria(remux, webdl) if c.name == "audio_codec")
        self.assertEqual(crit.winner, "a")
        self.assertEqual(compare_duplicates(remux, webdl).winner, "a")

    def test_duplicate_comparator_reads_the_probe_profile_field(self) -> None:
        """Le comparateur doit voir DTS-HD MA meme quand il recoit une piste
        ffprobe brute (codec='dts' + profile='DTS-HD MA')."""
        a = {"video": {"height": 1080, "codec": "h264"}, "audio_tracks": [dict(_DTS_HD_MA)]}
        b = {"video": {"height": 1080, "codec": "h264"}, "audio_tracks": [{"codec": "eac3", "channels": 6}]}
        crit = next(c for c in compare_by_criteria(a, b) if c.name == "audio_codec")
        self.assertEqual((crit.value_a, crit.value_b, crit.winner), ("dts-hd ma", "ac3", "a"))

    def test_composed_canonical_labels_keep_their_rank_in_the_comparator(self) -> None:
        """Les etiquettes composees ('truehd atmos') ne sont pas des cles exactes
        de AUDIO_CODEC_RANK : sans table d'alias elles tomberaient a 0, soit sous
        l'AC3 du fichier concurrent."""
        a = {"video": {"height": 1080, "codec": "h264"}, "audio_tracks": [{"codec": "truehd atmos", "channels": 8}]}
        b = {"video": {"height": 1080, "codec": "h264"}, "audio_tracks": [{"codec": "ac3", "channels": 6}]}
        crit = next(c for c in compare_by_criteria(a, b) if c.name == "audio_codec")
        self.assertEqual(crit.winner, "a")


if __name__ == "__main__":
    unittest.main()
