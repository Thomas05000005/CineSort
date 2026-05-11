"""P4.3 : tests pour import/export profils qualité."""

from __future__ import annotations

import json
import unittest

from cinesort.domain.profile_exchange import (
    MAX_JSON_BYTES,
    SCHEMA_NAME,
    SCHEMA_VERSION_MAX,
    extract_import_metadata,
    parse_and_validate_import,
    serialize_profile_export,
    wrap_profile_for_export,
)
from cinesort.domain.quality_score import default_quality_profile


class WrapProfileTests(unittest.TestCase):
    def test_wrap_includes_schema_fields(self):
        profile = default_quality_profile()
        wrapped = wrap_profile_for_export(profile, name="Test", author="Alice")
        self.assertEqual(wrapped["schema"], SCHEMA_NAME)
        self.assertEqual(wrapped["schema_version"], SCHEMA_VERSION_MAX)
        self.assertEqual(wrapped["name"], "Test")
        self.assertEqual(wrapped["author"], "Alice")
        self.assertIn("exported_at", wrapped)
        self.assertIn("profile", wrapped)

    def test_wrap_profile_block_matches(self):
        profile = default_quality_profile()
        wrapped = wrap_profile_for_export(profile)
        self.assertEqual(wrapped["profile"]["weights"], profile["weights"])

    def test_wrap_empty_metadata(self):
        profile = default_quality_profile()
        wrapped = wrap_profile_for_export(profile)
        self.assertEqual(wrapped["name"], "")
        self.assertEqual(wrapped["author"], "")

    def test_wrap_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            wrap_profile_for_export("not a dict")  # type: ignore

    def test_wrap_truncates_long_strings(self):
        profile = default_quality_profile()
        very_long = "x" * 5000
        wrapped = wrap_profile_for_export(profile, name=very_long, description=very_long)
        # Truncated to MAX_STRING_FIELD_LEN (1024)
        self.assertLessEqual(len(wrapped["name"]), 1024)
        self.assertLessEqual(len(wrapped["description"]), 1024)


class SerializeTests(unittest.TestCase):
    def test_roundtrip(self):
        profile = default_quality_profile()
        wrapped = wrap_profile_for_export(profile, name="Roundtrip")
        json_str = serialize_profile_export(wrapped)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["schema"], SCHEMA_NAME)
        self.assertEqual(parsed["name"], "Roundtrip")

    def test_json_is_human_readable(self):
        profile = default_quality_profile()
        wrapped = wrap_profile_for_export(profile)
        json_str = serialize_profile_export(wrapped)
        # Doit être indenté (lignes multiples)
        self.assertIn("\n", json_str)


class ParseImportValidTests(unittest.TestCase):
    def _valid_export(self, profile=None):
        p = profile or default_quality_profile()
        return serialize_profile_export(wrap_profile_for_export(p, name="Test"))

    def test_valid_roundtrip(self):
        content = self._valid_export()
        ok, profile, msg = parse_and_validate_import(content)
        self.assertTrue(ok, msg)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertIn("weights", profile)
        self.assertIn("tiers", profile)

    def test_ok_message_empty(self):
        content = self._valid_export()
        ok, _, msg = parse_and_validate_import(content)
        self.assertTrue(ok)
        self.assertEqual(msg, "")


class ParseImportInvalidTests(unittest.TestCase):
    def test_invalid_json(self):
        ok, p, msg = parse_and_validate_import("not a json")
        self.assertFalse(ok)
        self.assertIn("JSON invalide", msg)
        self.assertIsNone(p)

    def test_empty(self):
        ok, _, msg = parse_and_validate_import("")
        self.assertFalse(ok)
        self.assertIn("vide", msg.lower())

    def test_wrong_schema(self):
        bad = json.dumps({"schema": "some.other.schema", "schema_version": 1, "profile": {}})
        ok, _, msg = parse_and_validate_import(bad)
        self.assertFalse(ok)
        self.assertIn("Schéma", msg)

    def test_missing_schema_version(self):
        bad = json.dumps({"schema": SCHEMA_NAME, "profile": {}})
        ok, _, msg = parse_and_validate_import(bad)
        self.assertFalse(ok)
        self.assertIn("schema_version", msg)

    def test_future_schema_version_rejected(self):
        bad = json.dumps({"schema": SCHEMA_NAME, "schema_version": SCHEMA_VERSION_MAX + 100, "profile": {}})
        ok, _, msg = parse_and_validate_import(bad)
        self.assertFalse(ok)
        self.assertIn("trop récent", msg)

    def test_missing_profile(self):
        bad = json.dumps({"schema": SCHEMA_NAME, "schema_version": 1})
        ok, _, msg = parse_and_validate_import(bad)
        self.assertFalse(ok)
        self.assertIn("profile", msg.lower())

    def test_profile_missing_required_fields(self):
        bad = json.dumps({"schema": SCHEMA_NAME, "schema_version": 1, "profile": {"foo": "bar"}})
        ok, _, msg = parse_and_validate_import(bad)
        self.assertFalse(ok)
        # Manque "weights" et "tiers"
        self.assertTrue("weights" in msg.lower() or "tiers" in msg.lower() or "incomplet" in msg.lower())

    def test_non_dict_root(self):
        bad = json.dumps(["not", "a", "dict"])
        ok, _, msg = parse_and_validate_import(bad)
        self.assertFalse(ok)

    def test_huge_content_rejected(self):
        huge = "x" * (MAX_JSON_BYTES + 1024)
        ok, _, msg = parse_and_validate_import(huge)
        self.assertFalse(ok)
        self.assertIn("volumineux", msg.lower())


class MetadataExtractionTests(unittest.TestCase):
    def test_extract_metadata(self):
        profile = default_quality_profile()
        wrapped = wrap_profile_for_export(profile, name="My Pro", author="Bob", description="Cool profile")
        content = serialize_profile_export(wrapped)
        meta = extract_import_metadata(content)
        self.assertEqual(meta["name"], "My Pro")
        self.assertEqual(meta["author"], "Bob")
        self.assertEqual(meta["description"], "Cool profile")

    def test_extract_malformed_returns_empty_strings(self):
        meta = extract_import_metadata("not json")
        self.assertEqual(meta["name"], "")
        self.assertEqual(meta["author"], "")


if __name__ == "__main__":
    unittest.main()
