# -*- coding: utf-8 -*-
"""Lot « Bibliothecaire et regles personnalisees » — issues #617, #662, #723.

Les trois defauts ont ete REPRODUITS sur le code d'avant correctif (mesures
reelles, pas deduites) :

  #617  generate_suggestions -> sections A (codecs obsoletes) et E (basse
        resolution) lisaient `detected.get("title")`. Le dict `detected` vient
        de quality_score._build_quality_metrics_helper et ne porte QUE des
        metriques techniques ; la table `quality_reports` n'a pas de colonne
        titre. Mesure : details == ['r1'] (row_id) au lieu de
        ['Le Grand Bleu'].

  #662  1 row SAINE + 3 quality_reports orphelins (row_id absents des rows)
        -> health_score == -200. `problem_ids` melange des row_id venus des
        rows (blocs B/C/D/F) et des reports (blocs A/E), `total_rows` ne compte
        que les rows. Le score negatif remonte jusqu'a l'insight
        « Sante bibliotheque : -200/100 » (dashboard_support section 3c).

  #723  score_multiplier = -1.5 sur un film a 90 -> score 0, donc tier Reject,
        et `validate_rules` acceptait la regle (ok=True). Un film classe Reject
        par une faute de saisie peut etre SUPPRIME par l'utilisateur : le
        silence est le defaut principal.

Chaque garde a ete mutee SEPAREMENT dans le code source (occurrence unique
verifiee, rouge constate, restauration verifiee par hash) :
  G1 librarian section A (titre)        G4 custom_rules._act_score_mult
  G2 librarian section E (titre)        G5 custom_rules._validate_action
  G3 librarian health score (intersection)
"""

from __future__ import annotations

import gc
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import cinesort.ui.api.cinesort_api as backend
from cinesort.domain.custom_rules import apply_custom_rules, validate_rules
from cinesort.domain.librarian import generate_suggestions
from cinesort.domain.quality_score import compute_quality_score, default_quality_profile


class _Row:
    """Stub PlanRow : generate_suggestions lit tout via getattr."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _healthy_row(row_id: str, title: str) -> _Row:
    """Row SANS aucun probleme detectable par generate_suggestions.

    Sous-titres FR presents, aucun flag doublon, identification fiable (tmdb_id
    resolu). Sans cela le row serait lui-meme dans problem_ids et le test ne
    distinguerait plus « orphelin ignore » de « orphelin compte ».
    """
    return _Row(
        row_id=row_id,
        proposed_title=title,
        subtitle_languages=["fr"],
        warning_flags=[],
        tmdb_id=550,
        proposed_source="nfo",
        confidence=90,
        proposed_year=1988,
    )


def _report(row_id: str, **detected: Any) -> Dict[str, Any]:
    return {"row_id": row_id, "metrics": {"detected": dict(detected)}}


def _suggestion(result: Dict[str, Any], sug_id: str) -> Dict[str, Any]:
    for sug in result.get("suggestions") or []:
        if sug.get("id") == sug_id:
            return sug
    raise AssertionError(f"suggestion {sug_id!r} absente de {result.get('suggestions')!r}")


# ---------------------------------------------------------------------------
# #617 — le titre affiche vient des rows, pas d'un champ inexistant
# ---------------------------------------------------------------------------
class Issue617TitleFromRowsTests(unittest.TestCase):
    def test_codec_obsolete_details_contain_the_film_title(self) -> None:
        rows = [_healthy_row("r1", "Le Grand Bleu")]
        reports = [_report("r1", video_codec="xvid", resolution="1080p", height=1080)]
        sug = _suggestion(generate_suggestions(rows, reports, {}), "codec_obsolete")
        self.assertEqual(sug["details"], ["Le Grand Bleu"])

    def test_low_resolution_details_contain_the_film_title(self) -> None:
        rows = [_healthy_row("r2", "Les Bronzes")]
        reports = [_report("r2", video_codec="h264", resolution="sd", height=480)]
        sug = _suggestion(generate_suggestions(rows, reports, {}), "low_resolution")
        self.assertEqual(sug["details"], ["Les Bronzes"])

    def test_title_is_never_the_technical_row_id_when_the_row_is_known(self) -> None:
        """Le row_id ne doit apparaitre dans AUCUN detail quand la row existe."""
        rows = [_healthy_row("row-abcdef123456", "Subway")]
        reports = [_report("row-abcdef123456", video_codec="divx", resolution="sd", height=576)]
        result = generate_suggestions(rows, reports, {})
        for sug in result["suggestions"]:
            self.assertNotIn("row-abcdef123456", sug["details"], sug)

    def test_orphan_report_still_falls_back_to_row_id(self) -> None:
        """Repli conserve : sans row correspondante, on n'invente pas de titre."""
        rows = [_healthy_row("r1", "Le Grand Bleu")]
        reports = [_report("orphan-1", video_codec="wmv")]
        sug = _suggestion(generate_suggestions(rows, reports, {}), "codec_obsolete")
        self.assertEqual(sug["details"], ["orphan-1"])


# ---------------------------------------------------------------------------
# #662 — health_score borne par construction
# ---------------------------------------------------------------------------
class Issue662HealthScoreTests(unittest.TestCase):
    def test_orphan_reports_do_not_drive_health_score_negative(self) -> None:
        rows = [_healthy_row("r1", "Le Grand Bleu")]
        reports = [
            _report("orphan-a", video_codec="xvid"),
            _report("orphan-b", video_codec="divx"),
            _report("orphan-c", video_codec="wmv"),
        ]
        result = generate_suggestions(rows, reports, {})
        # 1 row, saine : 100 % des FILMS DU PLAN vont bien. Avant le fix : -200.
        self.assertEqual(result["health_score"], 100)

    def test_health_score_stays_within_bounds_with_mixed_sources(self) -> None:
        rows = [_healthy_row("r1", "Alpha"), _healthy_row("r2", "Beta")]
        reports = [
            _report("r1", video_codec="xvid"),  # probleme REEL (row connue)
            _report("orphan-a", video_codec="divx"),
            _report("orphan-b", video_codec="mpeg2"),
        ]
        result = generate_suggestions(rows, reports, {})
        # 2 rows, 1 seule malade -> 50. Avant le fix : 2 - 3 = -1 -> -50.
        self.assertEqual(result["health_score"], 50)
        self.assertGreaterEqual(result["health_score"], 0)

    def test_real_problem_on_a_known_row_still_lowers_the_score(self) -> None:
        """Controle : l'intersection ne doit pas neutraliser les vrais problemes."""
        rows = [_healthy_row("r1", "Alpha")]
        reports = [_report("r1", video_codec="xvid")]
        self.assertEqual(generate_suggestions(rows, reports, {})["health_score"], 0)


# ---------------------------------------------------------------------------
# #723 — un multiplicateur negatif ne fait plus tomber un film en Reject
# ---------------------------------------------------------------------------
def _rule(value: Any, rule_id: str = "r1") -> Dict[str, Any]:
    return {
        "id": rule_id,
        "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
        "action": {"type": "score_multiplier", "value": value, "reason": "malus maison"},
    }


def _context() -> Dict[str, Any]:
    return {
        "detected": {"video_codec": "hevc"},
        "__context__": {"year": 2020},
        "__computed__": {"score_before": 90},
    }


class Issue723NegativeMultiplierTests(unittest.TestCase):
    def test_negative_multiplier_preserves_the_score(self) -> None:
        out = apply_custom_rules(90, _context(), [_rule(-1.5)])
        self.assertEqual(out["score"], 90)  # avant le fix : 0 -> Reject

    def test_negative_multiplier_is_reported_to_the_user(self) -> None:
        """Le silence est le defaut principal : la raison doit etre lisible."""
        out = apply_custom_rules(90, _context(), [_rule(-1.5)])
        joined = " | ".join(out["reasons"])
        self.assertIn("multiplicateur negatif", joined.lower())

    def test_negative_multiplier_is_logged(self) -> None:
        with self.assertLogs("cinesort.domain.custom_rules", level=logging.WARNING) as caught:
            apply_custom_rules(90, _context(), [_rule(-1.5)])
        self.assertTrue(any("score_multiplier" in m for m in caught.output), caught.output)

    def test_positive_multiplier_still_applies(self) -> None:
        """Controle anti-test-vacant : la regle FRAPPE bien ce contexte."""
        out = apply_custom_rules(70, _context(), [_rule(1.1)])
        self.assertEqual(out["score"], 77)

    def test_zero_multiplier_remains_allowed(self) -> None:
        """0 est une intention explicite (« annuler le score »), pas une faute."""
        out = apply_custom_rules(90, _context(), [_rule(0)])
        self.assertEqual(out["score"], 0)

    def test_validate_rules_refuses_a_negative_multiplier(self) -> None:
        ok, errs, _norm = validate_rules([_rule(-1.5)])
        self.assertFalse(ok)
        self.assertTrue(any("score_multiplier" in e for e in errs), errs)
        self.assertTrue(any("Reject" in e for e in errs), errs)

    def test_validate_rules_accepts_a_positive_multiplier(self) -> None:
        ok, errs, norm = validate_rules([_rule(1.2)])
        self.assertTrue(ok, errs)
        self.assertEqual(norm[0]["action"]["value"], 1.2)


class Issue723EndToEndScoringTests(unittest.TestCase):
    """Effet OBSERVABLE sur la chaine reelle de scoring (pas un dict interne).

    Le profil est passe tel quel a compute_quality_score, qui ne repasse PAS par
    validate_rules : c'est exactement le cas d'un profil deja persiste en base
    avant le durcissement de la validation.
    """

    def _probe(self) -> Dict[str, Any]:
        return {
            "probe_quality": "FULL",
            "probe_quality_reasons": ["Analyse technique complete."],
            "video": {
                "codec": "hevc",
                "width": 3840,
                "height": 2160,
                "bit_depth": 10,
                "bitrate_kbps": 60000,
                "hdr": {"dolby_vision": False, "hdr10_plus": False, "hdr10": True},
            },
            "audio": [{"codec": "truehd", "channels": 8, "language": "fra"}],
            "duration_s": 7200.0,
        }

    def _score_with_rule(self, value: Any) -> Dict[str, Any]:
        profile = default_quality_profile()
        profile["custom_rules"] = [_rule(value, rule_id="neg_mult")]
        return compute_quality_score(
            normalized_probe=self._probe(),
            profile=profile,
            expected_title="Demo Movie",
            expected_year=2022,
            release_name="Demo.Movie.2022.2160p.UHD.BluRay.Remux.TrueHD.Atmos",
        )

    def test_zero_multiplier_really_rejects_the_film(self) -> None:
        """Controle de cablage : la regle atteint bien ce film (sinon les tests
        suivants ne prouveraient rien)."""
        out = self._score_with_rule(0)
        self.assertEqual(int(out["score"]), 0)
        self.assertEqual(str(out["tier"]), "Reject")

    def test_negative_multiplier_does_not_reject_the_film(self) -> None:
        out = self._score_with_rule(-1)
        self.assertGreater(int(out["score"]), 0)
        self.assertNotEqual(str(out["tier"]), "Reject")

    def test_negative_multiplier_leaves_the_score_untouched(self) -> None:
        baseline = self._score_with_rule(1)
        out = self._score_with_rule(-1)
        self.assertEqual(int(out["score"]), int(baseline["score"]))

    def test_negative_multiplier_surfaces_in_the_score_reasons(self) -> None:
        out = self._score_with_rule(-1)
        joined = " | ".join(str(r) for r in out.get("reasons") or [])
        self.assertIn("multiplicateur negatif", joined.lower())


class Issue723SavePathTests(unittest.TestCase):
    """Le refus doit se produire sur le chemin d'appel REEL de l'utilisateur
    (facade quality.save_quality_profile), pas seulement dans le helper."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_rules723_")
        self.addCleanup(self._tmp.cleanup)
        # addCleanup est LIFO : ce collect passe AVANT la suppression du tmpdir
        # (connexions sqlite3 retenues par des cycles -> WinError 32 sinon).
        self.addCleanup(gc.collect)
        self.root = Path(self._tmp.name) / "root"
        self.state_dir = Path(self._tmp.name) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        saved = self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

    def _profile_with(self, value: Any) -> Dict[str, Any]:
        profile = default_quality_profile()
        profile["custom_rules"] = [_rule(value)]
        return profile

    def test_save_quality_profile_refuses_negative_multiplier(self) -> None:
        out = self.api.quality.save_quality_profile(self._profile_with(-2))
        self.assertFalse(out.get("ok"), out)
        errors = " | ".join(str(e) for e in out.get("errors") or [])
        self.assertIn("score_multiplier", errors)

    def test_save_quality_profile_accepts_positive_multiplier(self) -> None:
        """Controle : le refus vise la valeur negative, pas l'action elle-meme."""
        out = self.api.quality.save_quality_profile(self._profile_with(1.5))
        self.assertTrue(out.get("ok"), out)


if __name__ == "__main__":
    unittest.main()
