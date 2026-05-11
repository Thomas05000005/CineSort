"""Tests du moteur de regles custom (G6)."""

from __future__ import annotations

import unittest

from cinesort.domain.custom_rules import (
    ACTIONS,
    FIELD_PATHS,
    MAX_CONDITIONS_PER_RULE,
    MAX_RULES_PER_PROFILE,
    OPERATORS,
    apply_custom_rules,
    evaluate_rule,
    validate_rules,
)
from cinesort.domain.custom_rules_templates import (
    TEMPLATE_CASUAL,
    TEMPLATE_PURIST,
    TEMPLATE_TRASH,
    TEMPLATES,
    get_template,
    list_templates,
)


def _make_context(**kwargs):
    detected = {
        "video_codec": "hevc",
        "audio_best_codec": "truehd",
        "resolution": "1080p",
        "bitrate_kbps": 8000,
        "audio_best_channels": 6,
        "hdr10": False,
        "hdr10_plus": False,
        "hdr_dolby_vision": False,
    }
    context = {
        "year": 2020,
        "subtitle_count": 2,
        "subtitle_languages": ["fr", "en"],
        "warning_flags": [],
        "edition": None,
        "duration_s": 7200,
    }
    computed = {
        "resolution_rank": 2,
        "tier_before": "Bon",
        "score_before": 70,
        "file_size_gb": 8.0,
        "tmdb_in_collection": False,
    }
    # Overrides
    for k, v in kwargs.items():
        if k in detected:
            detected[k] = v
        elif k in context:
            context[k] = v
        elif k in computed:
            computed[k] = v
    return {"detected": detected, "__context__": context, "__computed__": computed}


class TestOperators(unittest.TestCase):
    def test_eq(self):
        self.assertTrue(OPERATORS["="]("hevc", "hevc"))
        self.assertFalse(OPERATORS["="]("hevc", "avc"))

    def test_ne(self):
        self.assertTrue(OPERATORS["!="]("hevc", "avc"))
        self.assertFalse(OPERATORS["!="]("hevc", "hevc"))

    def test_lt(self):
        self.assertTrue(OPERATORS["<"](1500, 3000))
        self.assertFalse(OPERATORS["<"](3000, 1500))

    def test_le(self):
        self.assertTrue(OPERATORS["<="](1500, 1500))
        self.assertTrue(OPERATORS["<="](1000, 1500))

    def test_gt(self):
        self.assertTrue(OPERATORS[">"](3000, 1500))
        self.assertFalse(OPERATORS[">"](1500, 3000))

    def test_ge(self):
        self.assertTrue(OPERATORS[">="](3000, 3000))
        self.assertFalse(OPERATORS[">="](2999, 3000))

    def test_between(self):
        self.assertTrue(OPERATORS["between"](1985, [1970, 1995]))
        self.assertFalse(OPERATORS["between"](2020, [1970, 1995]))
        self.assertFalse(OPERATORS["between"](1985, [1970]))  # malformed

    def test_in(self):
        self.assertTrue(OPERATORS["in"]("xvid", ["xvid", "divx"]))
        self.assertFalse(OPERATORS["in"]("hevc", ["xvid", "divx"]))

    def test_not_in(self):
        self.assertTrue(OPERATORS["not_in"]("hevc", ["xvid", "divx"]))
        self.assertFalse(OPERATORS["not_in"]("xvid", ["xvid", "divx"]))

    def test_contains_list(self):
        self.assertTrue(OPERATORS["contains"](["fr", "en"], "fr"))
        self.assertFalse(OPERATORS["contains"](["fr", "en"], "de"))

    def test_contains_str(self):
        self.assertTrue(OPERATORS["contains"]("upscale_suspect", "upscale"))

    def test_not_contains(self):
        self.assertTrue(OPERATORS["not_contains"](["fr", "en"], "de"))
        self.assertFalse(OPERATORS["not_contains"](["fr", "en"], "fr"))


class TestEvaluateRule(unittest.TestCase):
    def test_all_match(self):
        ctx = _make_context(video_codec="hevc", resolution="1080p")
        rule = {
            "conditions": [
                {"field": "video_codec", "op": "=", "value": "hevc"},
                {"field": "resolution", "op": "=", "value": "1080p"},
            ],
            "match": "all",
        }
        self.assertTrue(evaluate_rule(rule, ctx))

    def test_all_one_fails(self):
        ctx = _make_context(video_codec="hevc", resolution="720p")
        rule = {
            "conditions": [
                {"field": "video_codec", "op": "=", "value": "hevc"},
                {"field": "resolution", "op": "=", "value": "1080p"},
            ],
            "match": "all",
        }
        self.assertFalse(evaluate_rule(rule, ctx))

    def test_any_one_matches(self):
        ctx = _make_context(video_codec="hevc", resolution="720p")
        rule = {
            "conditions": [
                {"field": "video_codec", "op": "=", "value": "hevc"},
                {"field": "resolution", "op": "=", "value": "1080p"},
            ],
            "match": "any",
        }
        self.assertTrue(evaluate_rule(rule, ctx))

    def test_empty_conditions(self):
        self.assertFalse(evaluate_rule({"conditions": []}, _make_context()))

    def test_unknown_field_ignored(self):
        ctx = _make_context()
        rule = {"conditions": [{"field": "unknown", "op": "=", "value": "x"}]}
        self.assertFalse(evaluate_rule(rule, ctx))

    def test_unknown_operator_ignored(self):
        ctx = _make_context()
        rule = {"conditions": [{"field": "video_codec", "op": "LIKE", "value": "hevc"}]}
        self.assertFalse(evaluate_rule(rule, ctx))


class TestApplyActions(unittest.TestCase):
    def test_score_delta_positive(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": 10, "reason": "Bonus HEVC"},
            }
        ]
        r = apply_custom_rules(70, ctx, rules)
        self.assertEqual(r["score"], 80)
        self.assertIn("r1", r["applied_rule_ids"])
        self.assertTrue(any("Bonus HEVC" in x for x in r["reasons"]))

    def test_score_delta_negative_clamped(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": -200},
            }
        ]
        r = apply_custom_rules(70, ctx, rules)
        self.assertEqual(r["score"], 0)

    def test_score_multiplier(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_multiplier", "value": 1.1},
            }
        ]
        r = apply_custom_rules(70, ctx, rules)
        self.assertEqual(r["score"], 77)

    def test_force_score(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "force_score", "value": 85},
            }
        ]
        r = apply_custom_rules(40, ctx, rules)
        self.assertEqual(r["score"], 85)

    def test_force_tier(self):
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "year", "op": "<=", "value": 1970}],
                "action": {"type": "force_tier", "value": "Premium"},
            }
        ]
        ctx2 = _make_context(year=1965)
        r = apply_custom_rules(70, ctx2, rules)
        self.assertEqual(r["force_tier"], "Premium")

    def test_cap_max_triggers(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "cap_max", "value": 65},
            }
        ]
        r = apply_custom_rules(80, ctx, rules)
        self.assertEqual(r["score"], 65)

    def test_cap_max_no_effect(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "cap_max", "value": 90},
            }
        ]
        r = apply_custom_rules(80, ctx, rules)
        self.assertEqual(r["score"], 80)

    def test_cap_min(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "cap_min", "value": 50},
            }
        ]
        r = apply_custom_rules(40, ctx, rules)
        self.assertEqual(r["score"], 50)

    def test_flag_warning(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "flag_warning", "value": "custom_flag", "reason": "Test"},
            }
        ]
        r = apply_custom_rules(70, ctx, rules)
        self.assertIn("custom_flag", r["flags_added"])


class TestApplyPriority(unittest.TestCase):
    def test_priority_order(self):
        ctx = _make_context()
        rules = [
            {
                "id": "low_priority_high_num",
                "priority": 100,
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": -10},
            },
            {
                "id": "high_priority_low_num",
                "priority": 1,
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": 20},
            },
        ]
        r = apply_custom_rules(50, ctx, rules)
        # Sorted asc: +20 applied first (50->70), then -10 (70->60)
        self.assertEqual(r["score"], 60)
        self.assertEqual(r["applied_rule_ids"], ["high_priority_low_num", "low_priority_high_num"])

    def test_disabled_rule_skipped(self):
        ctx = _make_context()
        rules = [
            {
                "id": "r1",
                "enabled": False,
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": 10},
            }
        ]
        r = apply_custom_rules(70, ctx, rules)
        self.assertEqual(r["score"], 70)
        self.assertEqual(r["applied_rule_ids"], [])

    def test_no_rules(self):
        r = apply_custom_rules(70, _make_context(), [])
        self.assertEqual(r["score"], 70)
        self.assertEqual(r["applied_rule_ids"], [])

    def test_none_rules(self):
        r = apply_custom_rules(70, _make_context(), None)
        self.assertEqual(r["score"], 70)


class TestValidation(unittest.TestCase):
    def test_valid_rule(self):
        ok, errs, norm = validate_rules(
            [
                {
                    "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                    "action": {"type": "score_delta", "value": 10},
                }
            ]
        )
        self.assertTrue(ok, msg=str(errs))
        self.assertEqual(len(norm), 1)
        self.assertEqual(norm[0]["id"], "rule_0")

    def test_not_a_list(self):
        ok, errs, _ = validate_rules({"rules": []})
        self.assertFalse(ok)
        self.assertTrue(any("liste" in e for e in errs))

    def test_too_many_rules(self):
        rules = [
            {
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": 0},
            }
        ] * (MAX_RULES_PER_PROFILE + 1)
        ok, errs, _ = validate_rules(rules)
        self.assertFalse(ok)

    def test_too_many_conditions(self):
        rule = {
            "conditions": [{"field": "video_codec", "op": "=", "value": "x"}] * (MAX_CONDITIONS_PER_RULE + 1),
            "action": {"type": "score_delta", "value": 0},
        }
        ok, errs, _ = validate_rules([rule])
        self.assertFalse(ok)
        self.assertTrue(any("conditions" in e for e in errs))

    def test_unknown_field_rejected(self):
        ok, errs, _ = validate_rules(
            [
                {
                    "conditions": [{"field": "bogus_field", "op": "=", "value": "x"}],
                    "action": {"type": "score_delta", "value": 0},
                }
            ]
        )
        self.assertFalse(ok)

    def test_unknown_operator_rejected(self):
        ok, errs, _ = validate_rules(
            [
                {
                    "conditions": [{"field": "video_codec", "op": "LIKE", "value": "x"}],
                    "action": {"type": "score_delta", "value": 0},
                }
            ]
        )
        self.assertFalse(ok)

    def test_between_requires_pair(self):
        ok, errs, _ = validate_rules(
            [
                {
                    "conditions": [{"field": "year", "op": "between", "value": [1970]}],
                    "action": {"type": "score_delta", "value": 0},
                }
            ]
        )
        self.assertFalse(ok)

    def test_no_conditions(self):
        ok, errs, _ = validate_rules([{"conditions": [], "action": {"type": "score_delta", "value": 0}}])
        self.assertFalse(ok)

    def test_unknown_action_type(self):
        ok, errs, _ = validate_rules(
            [
                {
                    "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                    "action": {"type": "delete_file", "value": 0},
                }
            ]
        )
        self.assertFalse(ok)


class TestFields(unittest.TestCase):
    def test_all_17_fields_declared(self):
        expected = {
            "video_codec",
            "audio_codec",
            "resolution",
            "resolution_rank",
            "year",
            "bitrate_kbps",
            "audio_channels",
            "has_hdr10",
            "has_hdr10p",
            "has_dv",
            "subtitle_count",
            "subtitle_langs",
            "warning_flags",
            "edition",
            "tier_before",
            "score_before",
            "file_size_gb",
            "duration_s",
            "tmdb_in_collection",
        }
        self.assertEqual(set(FIELD_PATHS.keys()), expected)

    def test_all_11_operators_declared(self):
        self.assertEqual(len(OPERATORS), 11)

    def test_all_7_actions_declared(self):
        self.assertEqual(len(ACTIONS), 7)


class TestTemplates(unittest.TestCase):
    def test_three_templates_present(self):
        self.assertEqual(set(TEMPLATES.keys()), {"trash_like", "purist", "casual"})

    def test_trash_rules_valid(self):
        ok, errs, _ = validate_rules(TEMPLATE_TRASH)
        self.assertTrue(ok, msg=str(errs))

    def test_purist_rules_valid(self):
        ok, errs, _ = validate_rules(TEMPLATE_PURIST)
        self.assertTrue(ok, msg=str(errs))

    def test_casual_rules_valid(self):
        ok, errs, _ = validate_rules(TEMPLATE_CASUAL)
        self.assertTrue(ok, msg=str(errs))

    def test_get_template(self):
        tpl = get_template("trash_like")
        self.assertEqual(tpl["id"], "trash_like")
        self.assertTrue(len(tpl["rules"]) > 0)

    def test_get_template_unknown(self):
        self.assertEqual(get_template("bogus"), {})

    def test_list_templates(self):
        lst = list_templates()
        self.assertEqual(len(lst), 3)
        ids = {t["id"] for t in lst}
        self.assertEqual(ids, {"trash_like", "purist", "casual"})


class TestInjectionScoring(unittest.TestCase):
    """Verifie que compute_quality_score applique bien les custom_rules."""

    def test_custom_rules_modify_score(self):
        from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

        probe = {
            "probe_quality": "FULL",
            "video": {
                "codec": "hevc",
                "width": 1920,
                "height": 1080,
                "bitrate": 8000000,
                "bit_depth": 10,
                "hdr_dolby_vision": False,
                "hdr10_plus": False,
                "hdr10": False,
            },
            "audio_tracks": [{"codec": "truehd", "channels": 6, "language": "eng", "bitrate": 3000000}],
            "duration_s": 7200,
            "sources": {},
        }
        profile = default_quality_profile()
        result_before = compute_quality_score(normalized_probe=probe, profile=profile)

        profile["custom_rules"] = [
            {
                "id": "test_boost",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "score_delta", "value": -20, "reason": "Test pen"},
            }
        ]
        result_after = compute_quality_score(normalized_probe=probe, profile=profile)
        self.assertLess(result_after["score"], result_before["score"])

    def test_no_custom_rules_no_change(self):
        from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

        probe = {
            "probe_quality": "FULL",
            "video": {
                "codec": "hevc",
                "width": 1920,
                "height": 1080,
                "bitrate": 8000000,
                "bit_depth": 10,
                "hdr_dolby_vision": False,
                "hdr10_plus": False,
                "hdr10": False,
            },
            "audio_tracks": [{"codec": "truehd", "channels": 6, "language": "eng", "bitrate": 3000000}],
            "duration_s": 7200,
            "sources": {},
        }
        profile = default_quality_profile()
        r1 = compute_quality_score(normalized_probe=probe, profile=profile)
        profile["custom_rules"] = []
        r2 = compute_quality_score(normalized_probe=probe, profile=profile)
        self.assertEqual(r1["score"], r2["score"])

    def test_force_tier_from_rule(self):
        from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

        probe = {
            "probe_quality": "FULL",
            "video": {
                "codec": "hevc",
                "width": 1920,
                "height": 1080,
                "bitrate": 8000000,
                "bit_depth": 10,
                "hdr_dolby_vision": False,
                "hdr10_plus": False,
                "hdr10": False,
            },
            "audio_tracks": [{"codec": "truehd", "channels": 6, "language": "eng", "bitrate": 3000000}],
            "duration_s": 7200,
            "sources": {},
        }
        profile = default_quality_profile()
        profile["custom_rules"] = [
            {
                "id": "force_faible",
                "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
                "action": {"type": "force_tier", "value": "Faible"},
            }
        ]
        result = compute_quality_score(normalized_probe=probe, profile=profile)
        self.assertEqual(result["tier"], "Faible")


if __name__ == "__main__":
    unittest.main()
