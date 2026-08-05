"""Revue adversaire de la PR#854 — ce que le correctif initial laissait passer.

Le lot « raisonner sur la CLASSE de resolution » etait juste sur le principe mais
s'arretait avant la production. Quatre trous, tous reproduits avant correction :

1. ``run_flow_support._build_pseudo_probe`` est le SEUL producteur de probes du
   comparateur de doublons, et il ne propageait que la HAUTEUR. Les nouveaux
   seuils s'appliquaient donc a la hauteur seule, ou la branche ``h >= 1000``
   ecrase tout l'intervalle 1000-2099 : un 2160p scope ``3840x1600`` devenait
   classe 1080p, a egalite avec un vrai 1080p. Les 30 points perdus retournaient
   le verdict vers « Garder B, archiver A » -- verdict applicable en masse via
   « Auto-decider tous », perdants deplaces a l'apply.
2. Les scores DEJA PERSISTES n'etaient pas invalides : les 3 cles du gate de
   cache viennent toutes du PROFIL, qui est persiste, donc un changement de
   REGLE dans le code ne les fait pas bouger. L'analyse en masse passant
   ``reuse_existing=True`` par defaut, une bibliotheque melangeait
   silencieusement ancienne et nouvelle formule dans le meme classement de tiers.
3. ``_effective_resolution_height`` derivait la classe INCONDITIONNELLEMENT,
   alors que ``_resolution_label`` retombe sur le nom de release : un fichier
   mesure ``700x400`` mais nomme ``.1080p.`` recevait le bonus « patrimoine en
   HD ». La mesure doit primer sur le nom de fichier.
4. ``_hierarchy_audio_codec_token`` fait un substring sur ``dts-hd`` : depuis que
   le helper lit l'etiquette canonique, un DTS-HD HRA (LOSSY) recevait le token
   ``dts_hd_ma`` et devenait eligible au plancher de tier du lossless.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from cinesort.domain import compute_quality_score, default_quality_profile
from cinesort.domain.duplicate_compare import compare_by_criteria, compare_duplicates
from cinesort.domain.quality_score import (
    SCORING_RULES_VERSION,
    _audio_codec_rank,
    _best_audio_track,
    _effective_resolution_height,
    _hierarchy_audio_codec_token,
)
from cinesort.ui.api import quality_report_support
from cinesort.ui.api.run_flow_support import _build_pseudo_probe, _quality_info_for_row

_FAKE_ROOT = "Z:/films-de-test"


def _detected(
    *,
    resolution: str,
    width: int,
    height: int,
    bitrate_kbps: int,
    video_codec: str = "hevc",
    audio_codec: str = "dts-hd ma",
    audio_channels: int = 6,
    resolution_source: str = "probe",
) -> Dict[str, Any]:
    """`metrics.detected` d'un quality_report, tel que persiste en base."""
    return {
        "resolution": resolution,
        "resolution_source": resolution_source,
        "width": width,
        "height": height,
        "bitrate_kbps": bitrate_kbps,
        "video_codec": video_codec,
        "audio_best_codec": audio_codec,
        "audio_best_channels": audio_channels,
        "duration_s": 7200,
    }


def _resolution_criterion(a: Dict[str, Any], b: Dict[str, Any]):
    return next(c for c in compare_by_criteria(a, b) if c.name == "resolution")


class PseudoProbeCarriesTheResolutionClassTests(unittest.TestCase):
    """Trou 1 : en production le comparateur ne recevait que la hauteur."""

    def test_uhd_scope_is_no_longer_recommended_for_archiving(self) -> None:
        """Le scenario de la revue : un UHD scope de 46 Go partait a l'archivage."""
        uhd_scope = _build_pseudo_probe(_detected(resolution="2160p", width=3840, height=1600, bitrate_kbps=55000))
        hd_flat = _build_pseudo_probe(
            _detected(
                resolution="1080p",
                width=1920,
                height=1080,
                bitrate_kbps=10000,
                video_codec="h264",
                audio_codec="truehd atmos",
                audio_channels=8,
            )
        )
        crit = _resolution_criterion(uhd_scope, hd_flat)
        self.assertEqual((crit.value_a, crit.value_b), ("2160p", "1080p"))
        self.assertEqual((crit.winner, crit.points_delta), ("a", 30))
        verdict = compare_duplicates(uhd_scope, hd_flat)
        self.assertEqual(verdict.winner, "a")
        self.assertNotIn("archiver A", verdict.recommendation)

    def test_scope_1080p_still_beats_a_true_720p(self) -> None:
        scope = _build_pseudo_probe(_detected(resolution="1080p", width=1920, height=800, bitrate_kbps=12000))
        true_720 = _build_pseudo_probe(_detected(resolution="720p", width=1280, height=720, bitrate_kbps=5000))
        crit = _resolution_criterion(scope, true_720)
        self.assertEqual((crit.value_a, crit.value_b), ("1080p", "720p"))
        self.assertEqual((crit.winner, crit.points_delta), ("a", 30))

    def test_case_left_open_by_the_pr_is_now_a_tie(self) -> None:
        """`1920x800` @12 Mbps vs `1920x1080` @6 Mbps : meme classe, donc egalite.

        C'est le cas frontal du finding d'origine, que la PR documentait comme
        « reste ouvert » faute de propagation.
        """
        scope = _build_pseudo_probe(_detected(resolution="1080p", width=1920, height=800, bitrate_kbps=12000))
        flat = _build_pseudo_probe(_detected(resolution="1080p", width=1920, height=1080, bitrate_kbps=6000))
        crit = _resolution_criterion(scope, flat)
        self.assertEqual((crit.value_a, crit.value_b), ("1080p", "1080p"))
        self.assertEqual((crit.winner, crit.points_delta), ("tie", 0))

    def test_real_class_gap_keeps_its_full_weight(self) -> None:
        """Non-regression : deux geometries flat de classes differentes."""
        uhd = _build_pseudo_probe(_detected(resolution="2160p", width=3840, height=2160, bitrate_kbps=50000))
        hd = _build_pseudo_probe(_detected(resolution="1080p", width=1920, height=1080, bitrate_kbps=20000))
        crit = _resolution_criterion(uhd, hd)
        self.assertEqual((crit.winner, crit.points_delta), ("a", 30))

    def test_a_label_deduced_from_the_release_name_is_not_propagated(self) -> None:
        """La mesure prime sur le nom, cote comparateur aussi.

        Probe echoue -> aucune dimension mesuree et etiquette deduite du NOM.
        Propager cette etiquette laisserait un nom de fichier voler 30 points a
        un fichier reellement mesure.
        """
        from_name = _detected(
            resolution="2160p", width=0, height=0, bitrate_kbps=3000, resolution_source="name_fallback"
        )
        pseudo = _build_pseudo_probe(from_name)
        self.assertEqual(pseudo["video"]["resolution"], "")
        measured_hd = _build_pseudo_probe(_detected(resolution="1080p", width=1920, height=1080, bitrate_kbps=20000))
        crit = _resolution_criterion(pseudo, measured_hd)
        self.assertNotEqual(crit.winner, "a")
        self.assertEqual(crit.points_delta, 0)

    def test_a_legacy_report_without_the_source_field_falls_back_on_width(self) -> None:
        """Deuxieme garde, independante de l'etiquette.

        Les rapports persistes par une version anterieure peuvent ne pas porter
        `resolution_source` : l'etiquette n'est alors pas propagee (on ne sait
        pas si elle vient d'une mesure) et c'est la LARGEUR qui doit trancher.
        Sans elle, la hauteur seule reclasse encore le scope en 1080p.
        """
        legacy_uhd_scope = {"width": 3840, "height": 1600, "bitrate_kbps": 55000, "video_codec": "hevc"}
        legacy_hd_flat = {"width": 1920, "height": 1080, "bitrate_kbps": 20000, "video_codec": "hevc"}
        pseudo_a = _build_pseudo_probe(legacy_uhd_scope)
        self.assertEqual(pseudo_a["video"]["resolution"], "")
        crit = _resolution_criterion(pseudo_a, _build_pseudo_probe(legacy_hd_flat))
        self.assertEqual((crit.value_a, crit.value_b), ("2160p", "1080p"))
        self.assertEqual((crit.winner, crit.points_delta), ("a", 30))

    def test_the_ab_cards_finally_display_the_dimensions(self) -> None:
        """Effet de bord verifie : `_quality_info_for_row` construit `WxH`.

        Ce helper (R8-059/F5) composait deja `resolution` = « largeur x hauteur »
        pour les cartes A/B de l'ecran Doublons, mais son seul fournisseur de
        probe n'a jamais porte `width` : la condition `if w and h` etait fausse
        et la ligne Resolution n'a jamais pu s'afficher.
        """
        probe = _build_pseudo_probe(_detected(resolution="2160p", width=3840, height=1600, bitrate_kbps=55000))
        info = _quality_info_for_row(None, "run_test", {"row_id": ""}, probe)
        self.assertEqual(info.get("resolution"), "3840x1600")


class MeasurementBeatsTheReleaseNameTests(unittest.TestCase):
    """Trou 3 : la derivation inconditionnelle laissait le NOM ecraser la MESURE."""

    def test_measured_height_wins_over_a_name_derived_label(self) -> None:
        self.assertEqual(
            _effective_resolution_height(
                video={"height": 400},
                vr={"resolution_label": "1080p", "resolution_source": "name_fallback"},
            ),
            400,
        )

    def test_probe_sourced_label_is_still_canonical(self) -> None:
        """Le coeur du lot reste intact : un 1080p scope mesure vaut bien 1080."""
        self.assertEqual(
            _effective_resolution_height(
                video={"height": 800},
                vr={"resolution_label": "1080p", "resolution_source": "probe"},
            ),
            1080,
        )

    def test_without_any_measurement_the_name_class_still_applies(self) -> None:
        """Non-regression du fix Vague K (2026-05-25) : sans probe, le nom sert."""
        self.assertEqual(
            _effective_resolution_height(
                video={"height": 0},
                vr={"resolution_label": "1080p", "resolution_source": "name_fallback"},
            ),
            1080,
        )

    @staticmethod
    def _score(width: int, height: int, release_name: str) -> Dict[str, Any]:
        return compute_quality_score(
            normalized_probe={
                "probe_quality": "FULL",
                "video": {"width": width, "height": height, "codec": "h264", "bitrate": 6_000_000, "bit_depth": 8},
                "audio_tracks": [{"codec": "ac3", "channels": 6, "language": "eng"}],
                "subtitles": [],
            },
            profile=default_quality_profile(),
            folder_name="Film (1965)",
            expected_title="Film",
            expected_year=1965,
            release_name=release_name,
            film_year=1965,
        )

    def test_a_tiny_file_named_1080p_gets_no_heritage_bonus(self) -> None:
        res = self._score(700, 400, "Film.1965.1080p.BluRay.x264-GRP.mkv")
        reasons = " || ".join(res.get("reasons") or [])
        self.assertEqual((res["metrics"]["detected"])["resolution_source"], "name_fallback")
        self.assertNotIn("patrimoine", reasons)
        self.assertNotIn("classique", reasons)

    def test_a_measured_scope_1080p_still_gets_it(self) -> None:
        """Non-regression : la vraie mesure garde le benefice du lot."""
        res = self._score(1920, 800, "Film.1965.BluRay.x264-GRP.mkv")
        self.assertIn("patrimoine", " || ".join(res.get("reasons") or []))


class LossyAudioKeepsItsHierarchyTokenTests(unittest.TestCase):
    """Trou 4 : le DTS-HD HRA (lossy) atteignait le plancher de tier du lossless."""

    def test_dts_hd_hra_is_not_promoted_to_the_lossless_token(self) -> None:
        hra = {"codec": "dts", "profile": "DTS-HD HRA", "channels": 6}
        self.assertEqual(_hierarchy_audio_codec_token(hra), "dts")

    def test_dts_hd_ma_still_reaches_its_token(self) -> None:
        """Non-regression : le lossless, lui, doit bien y arriver."""
        ma = {"codec": "dts", "profile": "DTS-HD MA", "channels": 6}
        self.assertEqual(_hierarchy_audio_codec_token(ma), "dts_hd_ma")

    def test_dts_x_still_reaches_its_own_token(self) -> None:
        self.assertEqual(_hierarchy_audio_codec_token({"codec": "dts", "is_dts_x": True}), "dts_x")

    def test_hyphenated_ac3_atmos_keeps_its_carrier_rank(self) -> None:
        """Revue Sourcery : 'ac-3 atmos' n'etait pas dans la table d'alias."""
        self.assertEqual(_audio_codec_rank({"codec": "ac-3", "channels": 6, "is_atmos": True}), 2)

    def test_hyphenated_codecs_of_the_mediainfo_backend_are_ranked(self) -> None:
        """`Format` MediaInfo = 'AC-3' / 'E-AC-3' : les deux valaient 0, sous AAC."""
        self.assertEqual(_audio_codec_rank({"codec": "ac-3", "channels": 6}), 2)
        self.assertEqual(_audio_codec_rank({"codec": "e-ac-3", "channels": 6}), 2)

    def test_an_aac_track_no_longer_outranks_the_main_ac3_track(self) -> None:
        """Consequence concrete du rang 0 : la piste AAC etait elue « meilleure »."""
        best = _best_audio_track(
            [
                {"codec": "ac-3", "channels": 6, "language": "fre"},
                {"codec": "aac", "channels": 2, "language": "eng"},
            ]
        )
        self.assertEqual(best.get("codec"), "ac-3")


class ScoringRulesVersionInvalidatesPersistedScoresTests(unittest.TestCase):
    """Trou 2 : les rapports deja en base survivaient a un changement de regle."""

    def test_metrics_carry_the_scoring_rules_stamp(self) -> None:
        res = compute_quality_score(
            normalized_probe={
                "probe_quality": "FULL",
                "video": {"width": 1920, "height": 1080, "codec": "h264", "bitrate": 10_000_000},
                "audio_tracks": [{"codec": "ac3", "channels": 6}],
                "subtitles": [],
            },
            profile=default_quality_profile(),
            folder_name="Film (2015)",
            expected_title="Film",
            expected_year=2015,
            release_name="Film.mkv",
        )
        self.assertEqual((res["metrics"]).get("scoring_rules_version"), SCORING_RULES_VERSION)

    def test_the_invalid_profile_result_carries_it_too(self) -> None:
        """Sinon ce rapport-la porte une version inconnue et se re-score sans fin.

        Le profil est rendu invalide par des poids tous nuls -- seule cause de
        rejet de `validate_quality_profile`, qui complete tout le reste par
        defaut. `validation_errors` prouve qu'on est bien sur ce chemin-la.
        """
        res = compute_quality_score(
            normalized_probe={"probe_quality": "FULL", "video": {}, "audio_tracks": [], "subtitles": []},
            profile={"id": "casse", "version": 1, "weights": {"video": 0, "audio": 0, "extras": 0}},
            folder_name="Film (2015)",
            expected_title="Film",
            expected_year=2015,
            release_name="Film.mkv",
        )
        self.assertTrue((res["metrics"]).get("validation_errors"))
        self.assertEqual((res["metrics"]).get("scoring_rules_version"), SCORING_RULES_VERSION)

    @staticmethod
    def _call_with_existing(existing: Optional[Dict[str, Any]], *, with_plan_row: bool = False) -> Dict[str, Any]:
        """Joue le gate de cache avec un rapport deja persiste.

        Le chemin « pas de reutilisation » est rendu observable en ne fournissant
        aucune ligne de plan : la fonction repond alors par l'erreur
        « Film introuvable dans ce plan ». Un cache hit, lui, renvoie
        `status == "ignored_existing"` sans jamais regarder les lignes.

        `with_plan_row=True` fournit la ligne mais aucun media resolvable :
        c'est l'etat d'un run DEJA APPLIQUE (le dossier source a bouge).
        """
        api = MagicMock()
        api.settings.get_settings.return_value = {}
        plan_row = MagicMock()
        plan_row.row_id = "row_1"
        api._load_rows_from_plan_jsonl.return_value = [plan_row] if with_plan_row else []
        api._resolve_media_path_for_row.return_value = None
        api._get_run.return_value = None
        api._ensure_quality_profile.return_value = {
            "id": "CinemaLux_v1",
            "version": 1,
            "profile_json": default_quality_profile(),
        }
        store = MagicMock()
        store.quality.get_quality_report.return_value = existing
        api._find_run_row.return_value = ({"state_dir": _FAKE_ROOT}, store)
        with patch.object(quality_report_support, "enrich_quality_report_with_perceptual"):
            return quality_report_support.get_quality_report(api, "run_test", "row_1", {"reuse_existing": True})

    @staticmethod
    def _persisted(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Rapport persiste dont SEULE l'estampille de regles doit varier.

        Fusion PR#872 : le gate de cache exige desormais aussi l'empreinte du
        CONTENU du profil (N30). Elle est injectee par defaut dans toutes les
        fixtures — et non retiree des assertions — pour que ces tests continuent
        de mesurer ce qu'ils annoncent. Sans elle, tous les cas « pas de
        reutilisation » passeraient a cause de l'empreinte manquante, sans
        jamais exercer l'estampille de regles : des tests VACANTS.
        """
        base_metrics: Dict[str, Any] = {
            "profile_fingerprint": quality_report_support.profile_fingerprint(default_quality_profile())
        }
        base_metrics.update(metrics)
        return {
            "score": 55,
            "tier": "Silver",
            "profile_id": "CinemaLux_v1",
            "profile_version": 1,
            "metrics": base_metrics,
        }

    def test_a_report_scored_with_the_old_rules_is_not_reused(self) -> None:
        res = self._call_with_existing(self._persisted({"engine_version": "CinemaLux_v1", "probe_quality": "FULL"}))
        self.assertNotEqual(str(res.get("status")), "ignored_existing")
        self.assertFalse(bool(res.get("ok")))

    def test_a_report_scored_with_the_current_rules_is_reused(self) -> None:
        """Non-regression : le cache n'est pas simplement desactive."""
        res = self._call_with_existing(
            self._persisted(
                {
                    "engine_version": "CinemaLux_v1",
                    "scoring_rules_version": SCORING_RULES_VERSION,
                    "probe_quality": "FULL",
                }
            )
        )
        self.assertEqual(str(res.get("status")), "ignored_existing")
        self.assertTrue(bool(res.get("cache_hit_quality")))

    def test_the_profile_gate_still_applies_on_top(self) -> None:
        """Non-regression : l'invalidation historique par le profil tient toujours."""
        res = self._call_with_existing(
            self._persisted(
                {
                    "engine_version": "CinemaLux_v1_test_bump",
                    "scoring_rules_version": SCORING_RULES_VERSION,
                    "probe_quality": "FULL",
                }
            )
        )
        self.assertNotEqual(str(res.get("status")), "ignored_existing")

    def test_an_unreachable_media_degrades_to_the_stale_score_not_an_erreur(self) -> None:
        """Contrepartie de l'invalidation : ne pas casser les runs deja appliques.

        Apres un apply, `resolve_media_path_for_row` part du dossier SOURCE, qui
        n'existe plus : re-scorer est impossible. Rendre l'erreur « media
        introuvable » ferait DISPARAITRE un score que l'utilisateur voyait
        jusque-la. On rend l'ancien, marque `scoring_rules_stale`.
        """
        res = self._call_with_existing(
            self._persisted({"engine_version": "CinemaLux_v1", "probe_quality": "FULL"}),
            with_plan_row=True,
        )
        self.assertTrue(bool(res.get("ok")))
        self.assertEqual(str(res.get("status")), "ignored_existing")
        self.assertTrue(bool(res.get("scoring_rules_stale")))
        self.assertEqual(int(res.get("score") or 0), 55)

    def test_a_fresh_report_is_never_flagged_stale(self) -> None:
        """Non-regression : le drapeau ne fuit pas sur le cache hit normal."""
        res = self._call_with_existing(
            self._persisted(
                {
                    "engine_version": "CinemaLux_v1",
                    "scoring_rules_version": SCORING_RULES_VERSION,
                    "probe_quality": "FULL",
                }
            ),
            with_plan_row=True,
        )
        self.assertEqual(str(res.get("status")), "ignored_existing")
        self.assertNotIn("scoring_rules_stale", res)

    def test_a_profile_change_does_not_get_the_stale_fallback(self) -> None:
        """Le repli ne vaut QUE pour l'estampille de code.

        Un profil different (poids/seuils changes par l'utilisateur) doit
        continuer a produire l'erreur franche : rendre un score calcule avec un
        AUTRE profil serait un faux positif silencieux.
        """
        res = self._call_with_existing(
            self._persisted({"engine_version": "CinemaLux_v1_test_bump", "probe_quality": "FULL"}),
            with_plan_row=True,
        )
        self.assertFalse(bool(res.get("ok")))


def _score_with_audio(track: Dict[str, Any], *, rules: Optional[list] = None) -> Dict[str, Any]:
    """Score un 1080p neutre dont SEULE la piste audio varie."""
    profile = default_quality_profile()
    if rules is not None:
        profile = dict(profile)
        profile["custom_rules"] = rules
    return compute_quality_score(
        normalized_probe={
            "probe_quality": "FULL",
            "video": {"width": 1920, "height": 1080, "codec": "h264", "bitrate": 10_000_000},
            "audio_tracks": [track],
            "subtitles": [],
        },
        profile=profile,
        folder_name="Film (2015)",
        expected_title="Film",
        expected_year=2015,
        release_name="Film.mkv",
    )


_PREMIUM_REASON = "+4 Audio haut de gamme multicanal"


class PremiumMultichannelBonusFollowsTheCanonicalLabelTests(unittest.TestCase):
    """Revue CodeRabbit PR#854 : `"dts-hd" in a_codec` ne dit plus la meme chose.

    `_score_audio` lit l'etiquette CANONIQUE depuis ce lot. Le test litteral
    laissait donc le DTS:X ('dts:x') dehors alors que le lot le classe lossless
    premium, et laissait le DTS-HD HRA ('dts-hd hra', LOSSY) dedans alors que les
    deux autres consommateurs le ramenent au rang `dts`.
    """

    def test_dts_x_71_gets_the_premium_multichannel_bonus(self) -> None:
        res = _score_with_audio({"codec": "dts", "profile": "DTS-HD MA", "is_dts_x": True, "channels": 8})
        self.assertIn(_PREMIUM_REASON, res["reasons"])

    def test_dts_hd_ma_71_still_gets_it(self) -> None:
        res = _score_with_audio({"codec": "dts", "profile": "DTS-HD MA", "channels": 8})
        self.assertIn(_PREMIUM_REASON, res["reasons"])

    def test_truehd_atmos_71_still_gets_it(self) -> None:
        res = _score_with_audio({"codec": "truehd", "is_atmos": True, "channels": 8})
        self.assertIn(_PREMIUM_REASON, res["reasons"])

    def test_dts_hd_hra_71_does_not_get_it(self) -> None:
        """LOSSY : `_audio_codec_bonus` et `_hierarchy_audio_codec_token` le disent deja."""
        res = _score_with_audio({"codec": "dts", "profile": "DTS-HD HRA", "channels": 8})
        self.assertNotIn(_PREMIUM_REASON, res["reasons"])

    def test_the_channel_floor_is_untouched(self) -> None:
        """Non-regression du hotfix 2026-06-04 : premium en 5.1 n'y a pas droit."""
        res = _score_with_audio({"codec": "truehd", "is_atmos": True, "channels": 6})
        self.assertNotIn(_PREMIUM_REASON, res["reasons"])


class UserRulesKeepTheBaseAudioCodecTests(unittest.TestCase):
    """Revue CodeRabbit PR#854 : `audio_codec = "dts"` ne doit pas cesser de matcher.

    L'operateur `=` est une egalite STRICTE (`custom_rules._op_eq`). Basculer le
    champ sur l'etiquette canonique aurait desactive sans un mot les regles deja
    enregistrees par l'utilisateur.
    """

    @staticmethod
    def _rule(field: str, value: str) -> list:
        return [
            {
                "id": "sonde",
                "name": "sonde",
                "enabled": True,
                "priority": 10,
                "conditions": [{"field": field, "op": "=", "value": value}],
                "match": "all",
                "action": {"type": "flag_warning", "value": "TOUCHE", "reason": "sonde"},
            }
        ]

    def _flags(self, track: Dict[str, Any], field: str, value: str) -> list:
        res = _score_with_audio(track, rules=self._rule(field, value))
        return list(res["metrics"].get("custom_warning_flags") or [])

    def test_a_legacy_dts_rule_still_matches_a_dts_hd_ma_remux(self) -> None:
        track = {"codec": "dts", "profile": "DTS-HD MA", "channels": 6}
        self.assertIn("TOUCHE", self._flags(track, "audio_codec", "dts"))

    def test_a_legacy_truehd_rule_still_matches_a_truehd_atmos_track(self) -> None:
        track = {"codec": "truehd", "is_atmos": True, "channels": 8}
        self.assertIn("TOUCHE", self._flags(track, "audio_codec", "truehd"))

    def test_the_canonical_label_is_reachable_through_its_own_field(self) -> None:
        """Le gain du lot est preserve, mais sur un champ EXPLICITE."""
        track = {"codec": "dts", "profile": "DTS-HD MA", "channels": 6}
        self.assertIn("TOUCHE", self._flags(track, "audio_codec_canonical", "dts-hd ma"))

    def test_the_canonical_field_does_not_match_the_base_label(self) -> None:
        track = {"codec": "dts", "profile": "DTS-HD MA", "channels": 6}
        self.assertNotIn("TOUCHE", self._flags(track, "audio_codec_canonical", "dts"))

    def test_the_metrics_payload_still_exposes_the_canonical_label(self) -> None:
        """Le dashboard et le comparateur de doublons, eux, veulent la canonique."""
        res = _score_with_audio({"codec": "dts", "profile": "DTS-HD MA", "channels": 6})
        self.assertEqual(res["metrics"]["detected"].get("audio_best_codec"), "dts-hd ma")


if __name__ == "__main__":
    unittest.main()
