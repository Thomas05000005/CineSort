"""VP-F (Vague P batch 6) — Recyclarr YAML round-trip lossless (AC-2).

Tests :
- YAML dump/load minimal subset (scalaires, listes, dicts imbriques).
- Round-trip CineSort profile -> Recyclarr YAML -> CineSort profile sans perte.
- Detection lossy (YAML Recyclarr "natif" sans cle cinesort_profile).
- Validation defensive (taille max, lignes trop longues, structure invalide).
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import default_quality_profile
from cinesort.ui.api.profiles_support_import_export import (
    MAX_YAML_BYTES,
    _profile_to_recyclarr_dict,
    _recyclarr_dict_to_profile,
    yaml_dump,
    yaml_load,
)


class YamlScalarRoundtripTests(unittest.TestCase):
    """yaml_dump + yaml_load doivent etre inverses pour les scalaires."""

    def test_bool_true(self) -> None:
        out = yaml_load(yaml_dump({"flag": True}))
        self.assertIs(out["flag"], True)

    def test_bool_false(self) -> None:
        out = yaml_load(yaml_dump({"flag": False}))
        self.assertIs(out["flag"], False)

    def test_null(self) -> None:
        out = yaml_load(yaml_dump({"v": None}))
        self.assertIsNone(out["v"])

    def test_int(self) -> None:
        out = yaml_load(yaml_dump({"n": 42}))
        self.assertEqual(out["n"], 42)

    def test_float(self) -> None:
        out = yaml_load(yaml_dump({"x": 3.14}))
        self.assertAlmostEqual(out["x"], 3.14)

    def test_simple_string(self) -> None:
        out = yaml_load(yaml_dump({"name": "hello"}))
        self.assertEqual(out["name"], "hello")

    def test_string_with_special_chars(self) -> None:
        out = yaml_load(yaml_dump({"text": "a: b"}))
        self.assertEqual(out["text"], "a: b")

    def test_numeric_string_stays_string(self) -> None:
        # "10000" doit revenir str, pas int.
        out = yaml_load(yaml_dump({"id": "10000"}))
        self.assertEqual(out["id"], "10000")
        self.assertIsInstance(out["id"], str)


class YamlContainerRoundtripTests(unittest.TestCase):
    def test_flat_dict(self) -> None:
        src = {"a": 1, "b": "two", "c": True}
        out = yaml_load(yaml_dump(src))
        self.assertEqual(out, src)

    def test_nested_dict(self) -> None:
        src = {"outer": {"inner": {"deep": 42}}}
        out = yaml_load(yaml_dump(src))
        self.assertEqual(out, src)

    def test_list_of_scalars(self) -> None:
        src = {"items": [1, 2, 3]}
        out = yaml_load(yaml_dump(src))
        self.assertEqual(out, src)

    def test_list_of_dicts(self) -> None:
        src = {"profiles": [{"name": "A", "score": 100}, {"name": "B", "score": 200}]}
        out = yaml_load(yaml_dump(src))
        self.assertEqual(out, src)

    def test_empty_dict(self) -> None:
        out = yaml_load(yaml_dump({"empty": {}}))
        self.assertEqual(out["empty"], {})

    def test_empty_list(self) -> None:
        out = yaml_load(yaml_dump({"empty": []}))
        self.assertEqual(out["empty"], [])


class YamlDefensesTests(unittest.TestCase):
    def test_oversized_yaml_rejected(self) -> None:
        big = "x" * (MAX_YAML_BYTES + 1)
        with self.assertRaises(ValueError):
            yaml_load(big)

    def test_excessively_long_line_rejected(self) -> None:
        # 4097 chars sans newline -> ligne > MAX_LINE_LENGTH.
        long_line = "k: " + "x" * 4095
        with self.assertRaises(ValueError):
            yaml_load(long_line)

    def test_non_str_input_raises_typeerror(self) -> None:
        with self.assertRaises(TypeError):
            yaml_load(123)  # type: ignore[arg-type]


class ProfileToRecyclarrDictTests(unittest.TestCase):
    def test_basic_structure(self) -> None:
        profile = default_quality_profile()
        d = _profile_to_recyclarr_dict(profile)
        self.assertIn("quality_profiles", d)
        self.assertEqual(len(d["quality_profiles"]), 1)
        first = d["quality_profiles"][0]
        self.assertIn("name", first)
        self.assertIn("upgrade", first)
        self.assertIn("cinesort_profile", first)

    def test_upgrade_until_score_default(self) -> None:
        profile = default_quality_profile()
        d = _profile_to_recyclarr_dict(profile)
        self.assertEqual(d["quality_profiles"][0]["upgrade"]["until_score"], 10000)

    def test_upgrade_until_score_custom(self) -> None:
        profile = default_quality_profile()
        profile["upgrade_until_score"] = 5500
        d = _profile_to_recyclarr_dict(profile)
        self.assertEqual(d["quality_profiles"][0]["upgrade"]["until_score"], 5500)

    def test_typeerror_on_non_dict(self) -> None:
        with self.assertRaises(TypeError):
            _profile_to_recyclarr_dict("not a dict")  # type: ignore[arg-type]


class RecyclarrToProfileTests(unittest.TestCase):
    def test_roundtrip_lossless_with_cinesort_key(self) -> None:
        profile = default_quality_profile()
        profile["id"] = "RoundtripTest_v1"
        profile["upgrade_until_score"] = 7500
        d = _profile_to_recyclarr_dict(profile)
        restored = _recyclarr_dict_to_profile(d)

        self.assertIsNotNone(restored)
        assert restored is not None  # for mypy
        self.assertEqual(restored["id"], "RoundtripTest_v1")
        self.assertEqual(restored["upgrade_until_score"], 7500)
        # Tiers preserves.
        self.assertEqual(restored["tiers"], profile["tiers"])
        self.assertEqual(restored["weights"], profile["weights"])

    def test_roundtrip_via_yaml_text(self) -> None:
        profile = default_quality_profile()
        profile["id"] = "RoundtripYaml_v1"
        profile["upgrade_until_score"] = 8888
        d = _profile_to_recyclarr_dict(profile)
        yaml_text = yaml_dump(d)
        parsed = yaml_load(yaml_text)
        restored = _recyclarr_dict_to_profile(parsed)

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored["id"], "RoundtripYaml_v1")
        self.assertEqual(restored["upgrade_until_score"], 8888)

    def test_lossy_fallback_without_cinesort_key(self) -> None:
        """YAML Recyclarr natif (sans cinesort_profile) -> profil reconstruit best-effort."""
        recyclarr_native = {
            "quality_profiles": [
                {
                    "name": "RemuxFlow_v1",
                    "upgrade": {"allowed": True, "until_score": 12345},
                    "min_format_score": 0,
                }
            ]
        }
        restored = _recyclarr_dict_to_profile(recyclarr_native)
        self.assertIsNotNone(restored)
        assert restored is not None
        # Lossy : reconstruit avec default profile, mais conserve name + score.
        self.assertEqual(restored["id"], "RemuxFlow_v1")
        self.assertEqual(restored["upgrade_until_score"], 12345)

    def test_returns_none_on_empty(self) -> None:
        self.assertIsNone(_recyclarr_dict_to_profile({}))
        self.assertIsNone(_recyclarr_dict_to_profile({"quality_profiles": []}))

    def test_returns_none_on_non_dict(self) -> None:
        self.assertIsNone(_recyclarr_dict_to_profile("garbage"))  # type: ignore[arg-type]


class RecyclarrEndpointTests(unittest.TestCase):
    """Test des endpoints (export/import) via une stub API."""

    def _make_stub_api(self, active_profile: dict | None = None):
        profile = active_profile or default_quality_profile()
        from unittest.mock import MagicMock

        api = MagicMock()
        api._active_quality_profile_payload.return_value = {
            "profile_id": profile.get("id", "default_v1"),
            "profile_version": 1,
            "profile_json": profile,
        }
        # Simule la facade settings.
        settings_facade = MagicMock()
        settings_facade.get_settings.return_value = {
            "custom_quality_profiles": [],
            "active_quality_profile_id": "",
        }
        # save_settings rebondit avec un payload ok.
        settings_facade.save_settings.return_value = {"ok": True}
        api.settings = settings_facade
        api._save_active_quality_profile = MagicMock()
        return api, profile

    def test_export_endpoint_returns_yaml(self) -> None:
        from cinesort.ui.api.profiles_support_import_export import (
            export_recyclarr_yaml,
        )

        api, profile = self._make_stub_api()
        res = export_recyclarr_yaml(api)
        self.assertTrue(res.get("ok"))
        self.assertIn("yaml", res)
        self.assertIn("quality_profiles", res["yaml"])

    def test_import_endpoint_roundtrip(self) -> None:
        from cinesort.ui.api.profiles_support_import_export import (
            export_recyclarr_yaml,
            import_recyclarr_yaml,
        )

        api, _ = self._make_stub_api()
        exported = export_recyclarr_yaml(api)
        self.assertTrue(exported.get("ok"))

        result = import_recyclarr_yaml(api, exported["yaml"], activate=False)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(result.get("lossy"), "Round-trip avec cinesort_profile = lossless")

    def test_import_empty_text_rejected(self) -> None:
        from cinesort.ui.api.profiles_support_import_export import (
            import_recyclarr_yaml,
        )

        api, _ = self._make_stub_api()
        result = import_recyclarr_yaml(api, "")
        self.assertFalse(result.get("ok"))

    def test_import_invalid_yaml_rejected(self) -> None:
        from cinesort.ui.api.profiles_support_import_export import (
            import_recyclarr_yaml,
        )

        api, _ = self._make_stub_api()
        # Pas de cle 'quality_profiles' -> None -> rejet.
        result = import_recyclarr_yaml(api, "totally_unknown_key: 42\n")
        self.assertFalse(result.get("ok"))


if __name__ == "__main__":
    unittest.main()
