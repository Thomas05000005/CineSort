"""VO-C-BACKEND : tests du helper `compose_score_explanation`.

Le helper fusionne les sorties de `build_rich_explanation` (categories +
baseline + suggestions + narrative + top_positive/negative + factors) et de
`apply_custom_rules` (applied_rule_ids) en une structure waterfall unifiee
consommee par l'inspecteur frontend (`row.score_explanation_full`).

Regles de design verifiees ici :
1. Helper PURE : ne modifie pas les sources, deterministe.
2. Backward compat : si `quality_report` n'a pas d'explanation -> None.
3. categories sortie en LIST (avec name + label) et non en dict pour faciliter
   le rendu frontend.
4. custom_rules ajoute comme categorie synthetique SEULEMENT si
   applied_rule_ids non vide.
5. Sources d'`applied_rule_ids` : parametre explicite > metrics interne.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.dashboard_support import compose_score_explanation


def _fake_explanation() -> dict:
    """Reproduit la structure de sortie de build_rich_explanation."""
    return {
        "narrative": "Score Gold solide avec une vidéo correcte.",
        "top_positive": [{"label": "HEVC 10-bit", "weighted_delta": 5.2}],
        "top_negative": [{"label": "bitrate bas", "weighted_delta": -3.1}],
        "factors": [],
        "categories": {
            "video": {
                "subscore": 70,
                "weight": 60,
                "weight_pct": 60.0,
                "contribution": 42.0,
                "label": "Vidéo",
                "factors_count": 3,
                "positive_count": 2,
                "negative_count": 1,
            },
            "audio": {
                "subscore": 60,
                "weight": 30,
                "weight_pct": 30.0,
                "contribution": 18.0,
                "label": "Audio",
                "factors_count": 1,
                "positive_count": 1,
                "negative_count": 0,
            },
            "extras": {
                "subscore": 50,
                "weight": 10,
                "weight_pct": 10.0,
                "contribution": 5.0,
                "label": "Extras",
                "factors_count": 0,
                "positive_count": 0,
                "negative_count": 0,
            },
        },
        "baseline": {
            "tier_thresholds": {"Platinum": 70, "Gold": 66, "Silver": 55, "Bronze": 40},
            "next_tier": "Platinum",
            "distance_to_next_tier": 5,
        },
        "suggestions": ["Upgrader vers une meilleure résolution."],
    }


class ComposeScoreExplanationBackwardCompatTests(unittest.TestCase):
    """Le helper doit retourner None proprement quand aucune source utile."""

    def test_none_quality_report_returns_none(self):
        self.assertIsNone(compose_score_explanation(None))

    def test_empty_dict_returns_none(self):
        self.assertIsNone(compose_score_explanation({}))

    def test_non_dict_input_returns_none(self):
        # type: ignore[arg-type]
        self.assertIsNone(compose_score_explanation("garbage"))  # type: ignore[arg-type]

    def test_metrics_without_score_explanation_returns_none(self):
        metrics_only = {
            "probe_quality": "OK",
            "detected": {"resolution": "1080p"},
            "applied_rule_ids": [],
        }
        self.assertIsNone(compose_score_explanation(metrics_only))


class ComposeScoreExplanationMergeTests(unittest.TestCase):
    """Verifie la fusion explanation + custom_rules dans la structure waterfall."""

    def test_passthrough_fields_from_explanation(self):
        metrics = {"score_explanation": _fake_explanation(), "applied_rule_ids": []}
        out = compose_score_explanation(metrics)
        self.assertIsNotNone(out)
        assert out is not None  # for type narrowing
        self.assertEqual(out["narrative"], "Score Gold solide avec une vidéo correcte.")
        self.assertEqual(out["suggestions"], ["Upgrader vers une meilleure résolution."])
        self.assertEqual(out["baseline"]["next_tier"], "Platinum")
        self.assertEqual(out["baseline"]["distance_to_next_tier"], 5)
        self.assertEqual(len(out["top_positive"]), 1)
        self.assertEqual(out["top_positive"][0]["label"], "HEVC 10-bit")
        self.assertEqual(out["top_negative"][0]["label"], "bitrate bas")

    def test_categories_serialized_as_list_with_name_and_label(self):
        metrics = {"score_explanation": _fake_explanation()}
        out = compose_score_explanation(metrics)
        assert out is not None
        cats = out["categories"]
        self.assertIsInstance(cats, list)
        names = [c["name"] for c in cats]
        self.assertIn("video", names)
        self.assertIn("audio", names)
        self.assertIn("extras", names)
        video_entry = next(c for c in cats if c["name"] == "video")
        self.assertEqual(video_entry["label"], "Vidéo")
        self.assertEqual(video_entry["contribution"], 42.0)

    def test_applied_rule_ids_from_metrics_when_no_explicit_result(self):
        metrics = {
            "score_explanation": _fake_explanation(),
            "applied_rule_ids": ["rule-a", "rule-b"],
        }
        out = compose_score_explanation(metrics)
        assert out is not None
        self.assertEqual(out["applied_rule_ids"], ["rule-a", "rule-b"])

    def test_applied_rule_ids_explicit_parameter_overrides_metrics(self):
        metrics = {
            "score_explanation": _fake_explanation(),
            "applied_rule_ids": ["from-metrics"],
        }
        custom_result = {"applied_rule_ids": ["from-param"], "score": 50}
        out = compose_score_explanation(metrics, custom_result)
        assert out is not None
        self.assertEqual(out["applied_rule_ids"], ["from-param"])

    def test_custom_rules_category_added_when_rules_applied(self):
        metrics = {
            "score_explanation": _fake_explanation(),
            "applied_rule_ids": ["rule-x", "rule-y"],
        }
        out = compose_score_explanation(metrics)
        assert out is not None
        names = [c["name"] for c in out["categories"]]
        self.assertIn("custom_rules", names)
        cr = next(c for c in out["categories"] if c["name"] == "custom_rules")
        self.assertEqual(cr["label"], "Règles personnalisées")
        self.assertEqual(cr["rule_ids"], ["rule-x", "rule-y"])
        self.assertEqual(cr["rules_count"], 2)

    def test_custom_rules_category_absent_when_no_rules(self):
        metrics = {
            "score_explanation": _fake_explanation(),
            "applied_rule_ids": [],
        }
        out = compose_score_explanation(metrics)
        assert out is not None
        names = [c["name"] for c in out["categories"]]
        self.assertNotIn("custom_rules", names)

    def test_accepts_full_report_with_metrics_wrapper(self):
        # Cas ou on passe le report complet (avec metrics imbrique)
        report = {
            "score": 65,
            "tier": "Gold",
            "metrics": {
                "score_explanation": _fake_explanation(),
                "applied_rule_ids": ["alpha"],
            },
        }
        out = compose_score_explanation(report)
        assert out is not None
        self.assertEqual(out["applied_rule_ids"], ["alpha"])
        self.assertEqual(out["narrative"], "Score Gold solide avec une vidéo correcte.")

    def test_accepts_bare_score_explanation_dict(self):
        # Cas ou on passe directement le score_explanation
        out = compose_score_explanation(_fake_explanation())
        assert out is not None
        self.assertEqual(out["narrative"], "Score Gold solide avec une vidéo correcte.")
        # Pas de metrics -> applied_rule_ids vide par defaut
        self.assertEqual(out["applied_rule_ids"], [])


class ComposeScoreExplanationPurityTests(unittest.TestCase):
    """Verifie que le helper ne mute pas les inputs (pure function)."""

    def test_does_not_mutate_input_explanation(self):
        explanation = _fake_explanation()
        snapshot_categories_keys = set(explanation["categories"].keys())
        snapshot_suggestions = list(explanation["suggestions"])
        metrics = {
            "score_explanation": explanation,
            "applied_rule_ids": ["r1"],
        }
        _ = compose_score_explanation(metrics)
        # categories reste un dict avec les memes cles
        self.assertEqual(set(explanation["categories"].keys()), snapshot_categories_keys)
        self.assertEqual(explanation["suggestions"], snapshot_suggestions)
        # metrics non mute
        self.assertEqual(metrics["applied_rule_ids"], ["r1"])

    def test_does_not_mutate_custom_rules_result(self):
        custom_result = {"applied_rule_ids": ["r1", "r2"], "score": 50, "flags_added": []}
        snapshot_ids = list(custom_result["applied_rule_ids"])
        metrics = {"score_explanation": _fake_explanation()}
        _ = compose_score_explanation(metrics, custom_result)
        self.assertEqual(custom_result["applied_rule_ids"], snapshot_ids)


if __name__ == "__main__":
    unittest.main()
