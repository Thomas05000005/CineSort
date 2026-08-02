"""Regression tests — audit ultra 2026-07-13 HIGH-2 / HIGH-3 (H1 + H2).

Le SEUL call site de production du scoring qualite,
``quality_report_support._probe_and_score``, appelait
``compute_quality_score`` SANS ``film_year``, ``subtitle_info``,
``encode_warnings`` ni ``audio_analysis``. Consequences :

- H1 : 4 modules de scoring morts -> ``_apply_era_bonuses_helper`` (bonus
  patrimoine / malus SD jamais appliques), le bloc sous-titres de
  ``_score_extras`` (toggle ``include_subtitles`` = no-op), et surtout
  ``_apply_encode_warnings_helper`` (malus upscale/reencode/4k_light jamais
  deduits) et ``_apply_commentary_penalty_helper``.
- H2 (meme call site) : ``rule_context`` construit avec ``year=0``,
  ``subtitle_count=0``, ``subtitle_languages=[]``, ``warning_flags=[]`` ->
  une regle custom ``year < 1990`` matchait TOUS les films (biblio entiere
  penalisee a tort), et ``subtitle_count == 0`` matchait meme les films
  ayant 12 pistes.

Le fix passe au call site les donnees qui existent DEJA (row.proposed_year,
normalized["subtitles"], analyze_encode_quality(detected),
analyze_audio(audio_tracks)), avec un two-pass : la passe 1 derive
``metrics.detected`` (pour analyze_encode_quality) puis la passe 2 persiste
le score DEFINITIF avec toutes ses sources (anti-pattern A resolu).

Chaque test ci-dessous ECHOUE avant le fix et PASSE apres.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from cinesort.domain import default_quality_profile
from cinesort.ui.api import quality_report_support


def _probe(bitrate_kbps: int, *, subtitles: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Normalized probe dict d'un 1080p h264 (upscale si bitrate bas).

    F16 : le champ `bitrate` d'une probe normalisee est en BITS/S (la couche
    probe passe tout par conversions.to_optional_bitrate). Le parametre du
    helper reste exprime en kb/s pour la lisibilite des appelants, la conversion
    se fait ici. Avant ce correctif la fixture stockait des kb/s bruts, ce qui
    faisait lire 9000 kb/s comme 9 kb/s une fois la normalisation corrigee.
    """
    return {
        "probe_quality": "FULL",
        "video": {
            "width": 1920,
            "height": 1080,
            "codec": "h264",
            "bitrate": int(bitrate_kbps) * 1000,
            "bit_depth": 8,
        },
        "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "eng", "bitrate": 640_000}],
        "subtitles": subtitles if subtitles is not None else [],
    }


def _run_probe_and_score(
    normalized: Dict[str, Any],
    *,
    profile: Optional[Dict[str, Any]] = None,
    proposed_year: int = 0,
) -> Dict[str, Any]:
    """Execute le VRAI ``_probe_and_score`` (scoring reel, probe mocke) et
    retourne les kwargs passes a ``upsert_quality_report`` (= le rapport
    DEFINITIF persiste : score / tier / reasons / metrics)."""
    api = MagicMock()
    api._effective_probe_settings_for_runtime.return_value = {}

    store = MagicMock()
    # None -> `out` retombe sur le dict fallback deterministe (pas de MagicMock).
    store.quality.get_quality_report.return_value = None

    run_row = {"state_dir": "/tmp"}
    row = MagicMock()
    row.folder = f"/tmp/Movie ({proposed_year or 2010})"
    row.proposed_title = "Movie"
    row.proposed_year = proposed_year
    row.video = "Movie.1080p.mkv"
    row.candidates = []  # aucune candidate -> aucun appel TMDb

    prof = profile if profile is not None else default_quality_profile()
    probe_result = {"normalized": normalized, "cache_hit": False}

    with patch.object(quality_report_support, "ProbeService") as mock_probe_cls:
        mock_probe = MagicMock()
        mock_probe.probe_file.return_value = probe_result
        mock_probe_cls.return_value = mock_probe
        quality_report_support._probe_and_score(
            api,
            store,
            run_row,
            "run_test",
            "row_1",
            row,
            "/tmp/Movie/Movie.mkv",
            profile_json=prof,
            active_profile_id="default",
            active_profile_version=1,
        )

    assert store.quality.upsert_quality_report.called, "upsert_quality_report doit etre appele"
    return dict(store.quality.upsert_quality_report.call_args.kwargs)


class EncodeWarningsAmputationTests(unittest.TestCase):
    """H1 : ``_apply_encode_warnings_helper`` doit maintenant s'appliquer."""

    def test_upscale_gets_upscale_suspect_penalty(self) -> None:
        up = _run_probe_and_score(_probe(1400))
        clean = _run_probe_and_score(_probe(9000))

        up_reasons = " || ".join(up.get("reasons") or [])
        clean_reasons = " || ".join(clean.get("reasons") or [])

        # ISOLE le fix : le malus "Upscale suspect" (-8) n'existe QUE si
        # encode_warnings est transmis a compute_quality_score.
        self.assertIn("Upscale suspect", up_reasons)
        self.assertNotIn("Upscale suspect", clean_reasons)
        # Le score persiste de l'upscale est strictement inferieur au vrai 1080p.
        self.assertLess(int(up["score"]), int(clean["score"]))

    def test_clean_1080p_has_no_encode_warning(self) -> None:
        clean = _run_probe_and_score(_probe(9000))
        for r in clean.get("reasons") or []:
            self.assertNotIn("Upscale", r)
            self.assertNotIn("Re-encode", r)


class EraBonusAmputationTests(unittest.TestCase):
    """H1 : ``_apply_era_bonuses_helper`` doit s'appliquer via film_year."""

    def test_heritage_bonus_applied_for_old_film_in_hd(self) -> None:
        old = _run_probe_and_score(_probe(9000), proposed_year=1965)
        reasons = " || ".join(old.get("reasons") or [])
        # Sans film_year, _apply_era_bonuses_helper sort immediatement.
        self.assertIn("patrimoine", reasons)

    def test_modern_penalty_applied_for_recent_film_in_sd(self) -> None:
        modern = _run_probe_and_score(_probe(9000), proposed_year=2022)
        reasons = " || ".join(modern.get("reasons") or [])
        self.assertIn("recent", reasons)

    def test_heritage_scores_higher_than_modern_same_file(self) -> None:
        old = _run_probe_and_score(_probe(9000), proposed_year=1965)
        modern = _run_probe_and_score(_probe(9000), proposed_year=2022)
        self.assertGreater(int(old["score"]), int(modern["score"]))


class CustomRuleContextAmputationTests(unittest.TestCase):
    """H2 : ``rule_context`` doit recevoir year/subtitle_count reels."""

    def _profile_with_rule(self, field: str, op: str, value: Any) -> Dict[str, Any]:
        prof = default_quality_profile()
        prof["custom_rules"] = [
            {
                "id": "test_rule",
                "enabled": True,
                "conditions": [{"field": field, "op": op, "value": value}],
                "action": {"type": "score_delta", "value": -30, "reason": "test"},
            }
        ]
        return prof

    def _applied_rule_ids(self, kwargs: Dict[str, Any]) -> List[str]:
        return list((kwargs.get("metrics") or {}).get("applied_rule_ids") or [])

    def test_year_rule_does_not_match_modern_film(self) -> None:
        # Une regle "year < 1990" NE doit PAS matcher un film de 2020.
        # Avant le fix : year=0 < 1990 -> matchait TOUTE la bibliotheque.
        prof = self._profile_with_rule("year", "<", 1990)
        kwargs = _run_probe_and_score(_probe(9000), profile=prof, proposed_year=2020)
        self.assertNotIn("test_rule", self._applied_rule_ids(kwargs))

    def test_year_rule_still_matches_genuinely_old_film(self) -> None:
        # Garde-fou : la regle reste FONCTIONNELLE pour un vrai vieux film.
        prof = self._profile_with_rule("year", "<", 1990)
        kwargs = _run_probe_and_score(_probe(9000), profile=prof, proposed_year=1965)
        self.assertIn("test_rule", self._applied_rule_ids(kwargs))

    def test_subtitle_count_rule_does_not_match_film_with_subs(self) -> None:
        # Une regle "subtitle_count == 0" NE doit PAS matcher un film ayant 2
        # pistes de sous-titres. Avant le fix : subtitle_info=None -> count=0.
        prof = self._profile_with_rule("subtitle_count", "=", 0)
        subs = [{"language": "fra"}, {"language": "eng"}]
        kwargs = _run_probe_and_score(_probe(9000, subtitles=subs), profile=prof)
        self.assertNotIn("test_rule", self._applied_rule_ids(kwargs))


class CallSiteContractTests(unittest.TestCase):
    """Contrat de call site (robuste au recalibrage des seuils) : la passe
    FINALE de compute_quality_score doit recevoir les 4 sources ressuscitees."""

    def test_final_call_receives_all_four_sources(self) -> None:
        api = MagicMock()
        api._effective_probe_settings_for_runtime.return_value = {}
        store = MagicMock()
        store.quality.get_quality_report.return_value = None

        row = MagicMock()
        row.folder = "/tmp/Movie (1965)"
        row.proposed_title = "Movie"
        row.proposed_year = 1965
        row.video = "Movie.1080p.mkv"
        row.candidates = []

        normalized = _probe(1400, subtitles=[{"language": "fra"}, {"language": "eng"}])
        probe_result = {"normalized": normalized, "cache_hit": False}

        # compute_quality_score mocke : la passe 1 doit exposer metrics.detected
        # pour que analyze_encode_quality flague l'upscale (1080p h264 @1400).
        fake_report = {
            "score": 50,
            "tier": "Silver",
            "reasons": [],
            "metrics": {"detected": {"height": 1080, "bitrate_kbps": 1400, "video_codec": "h264"}},
        }
        with patch.object(quality_report_support, "ProbeService") as mock_probe_cls, patch.object(
            quality_report_support, "compute_quality_score", return_value=fake_report
        ) as mock_score:
            mock_probe = MagicMock()
            mock_probe.probe_file.return_value = probe_result
            mock_probe_cls.return_value = mock_probe
            quality_report_support._probe_and_score(
                api,
                store,
                {"state_dir": "/tmp"},
                "run_test",
                "row_1",
                row,
                "/tmp/Movie/Movie.mkv",
                profile_json={"id": "default", "version": 1},
                active_profile_id="default",
                active_profile_version=1,
            )

        # Two-pass : compute_quality_score appele deux fois.
        self.assertEqual(mock_score.call_count, 2)
        # La DERNIERE (passe finale) porte les 4 sources ressuscitees.
        final_kwargs = mock_score.call_args.kwargs
        self.assertEqual(final_kwargs.get("film_year"), 1965)
        self.assertIn("upscale_suspect", final_kwargs.get("encode_warnings") or [])
        self.assertIsInstance(final_kwargs.get("audio_analysis"), dict)
        sub_info = final_kwargs.get("subtitle_info") or {}
        self.assertEqual(int(sub_info.get("count") or 0), 2)
        self.assertIn("fra", sub_info.get("languages") or [])


if __name__ == "__main__":
    unittest.main()
