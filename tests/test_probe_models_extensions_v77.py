"""Tests pour les extensions probe_models (Vague M, M-05).

Verifie :
1. ProbeSources : invariant "at least one source" si !manual_override.
2. ProbeSources.merge_audio_track : tracking piste-par-piste.
3. RenameProposal.to_dict / from_dict roundtrip serialisation.
4. ProbeResult : composition NormalizedProbe + sources accessible.
5. BACKWARD COMPAT : NormalizedProbe seul fonctionne toujours.
6. __all__ exporte les nouveaux types.
"""

from __future__ import annotations

import unittest

from cinesort.domain.probe_models import (
    OP_TYPE_RENAME,
    PROBE_QUALITY_FAILED,
    PROBE_QUALITY_FULL,
    NormalizedProbe,
    OpType,
    ProbeResult,
    ProbeSources,
    RenameProposal,
)


class ProbeSourcesTests(unittest.TestCase):
    """Tests dataclass ProbeSources : invariants + tracking par piste."""

    def test_at_least_one_source_required_if_not_manual(self) -> None:
        with self.assertRaises(ValueError):
            ProbeSources(mediainfo=False, ffprobe=False, manual_override=False)

    def test_mediainfo_only_is_valid(self) -> None:
        src = ProbeSources(mediainfo=True, ffprobe=False, manual_override=False)
        self.assertTrue(src.mediainfo)
        self.assertFalse(src.ffprobe)
        self.assertFalse(src.manual_override)

    def test_ffprobe_only_is_valid(self) -> None:
        src = ProbeSources(mediainfo=False, ffprobe=True, manual_override=False)
        self.assertTrue(src.ffprobe)

    def test_both_sources_is_valid(self) -> None:
        src = ProbeSources(mediainfo=True, ffprobe=True, manual_override=False)
        self.assertTrue(src.mediainfo)
        self.assertTrue(src.ffprobe)

    def test_manual_override_allows_no_other_source(self) -> None:
        src = ProbeSources(mediainfo=False, ffprobe=False, manual_override=True)
        self.assertTrue(src.manual_override)

    def test_merge_audio_track_records_field_source(self) -> None:
        src = ProbeSources(mediainfo=True, ffprobe=True)
        src.merge_audio_track(0, "codec", "ffprobe")
        src.merge_audio_track(0, "channels", "mediainfo")
        src.merge_audio_track(1, "codec", "mediainfo+ffprobe")

        self.assertEqual(src.audio_tracks[0]["codec"], "ffprobe")
        self.assertEqual(src.audio_tracks[0]["channels"], "mediainfo")
        self.assertEqual(src.audio_tracks[1]["codec"], "mediainfo+ffprobe")

    def test_merge_audio_track_overrides_previous_source(self) -> None:
        src = ProbeSources(mediainfo=True)
        src.merge_audio_track(0, "codec", "mediainfo")
        src.merge_audio_track(0, "codec", "ffprobe")
        self.assertEqual(src.audio_tracks[0]["codec"], "ffprobe")

    def test_merge_audio_track_rejects_negative_idx(self) -> None:
        src = ProbeSources(mediainfo=True)
        with self.assertRaises(ValueError):
            src.merge_audio_track(-1, "codec", "ffprobe")

    def test_merge_audio_track_rejects_empty_field(self) -> None:
        src = ProbeSources(mediainfo=True)
        with self.assertRaises(ValueError):
            src.merge_audio_track(0, "", "ffprobe")

    def test_merge_audio_track_rejects_empty_source(self) -> None:
        src = ProbeSources(mediainfo=True)
        with self.assertRaises(ValueError):
            src.merge_audio_track(0, "codec", "")

    def test_to_dict_serialises_all_fields(self) -> None:
        src = ProbeSources(mediainfo=True, ffprobe=False)
        src.merge_audio_track(0, "codec", "mediainfo")
        d = src.to_dict()
        self.assertEqual(d["mediainfo"], True)
        self.assertEqual(d["ffprobe"], False)
        self.assertEqual(d["audio_tracks"], {0: {"codec": "mediainfo"}})


class RenameProposalTests(unittest.TestCase):
    """Tests RenameProposal : serialisation roundtrip + defauts."""

    def test_minimal_construction(self) -> None:
        p = RenameProposal(
            src_path="/in/foo.mkv",
            target_path="/out/Foo (2024).mkv",
            op_type=OpType.RENAME,
        )
        self.assertEqual(p.src_path, "/in/foo.mkv")
        # VN-F.4 : op_type canonique UPPERCASE aligne sur le contrat journal/apply.
        # VO-D-2 : StrEnum equality preserve la comparaison avec la string brute.
        self.assertEqual(p.op_type, "RENAME")
        self.assertEqual(p.op_type, OpType.RENAME)
        # Backward compat alias OP_TYPE_RENAME == OpType.RENAME.value.
        self.assertEqual(p.op_type, OP_TYPE_RENAME)
        self.assertFalse(p.no_op)
        self.assertEqual(p.reason, "")
        self.assertIsNone(p.confidence)
        self.assertIsNone(p.source)
        self.assertEqual(p.alternatives, [])
        self.assertEqual(p.reasons, [])

    def test_to_dict_then_from_dict_roundtrip(self) -> None:
        p = RenameProposal(
            src_path="/in/movie.mkv",
            target_path="/out/Movie (2024) [tt12345].mkv",
            op_type=OpType.MOVE,
            no_op=False,
            reason="title+year+imdb match",
            confidence=0.92,
            source="auto",
            alternatives=["/out/Movie 2024.mkv"],
            reasons=["title=Movie", "year=2024", "imdb=tt12345"],
        )
        as_dict = p.to_dict()
        rebuilt = RenameProposal.from_dict(as_dict)
        self.assertEqual(rebuilt, p)

    def test_from_dict_ignores_unknown_fields(self) -> None:
        data = {
            "src_path": "/a",
            "target_path": "/b",
            # VO-D-2 : OpType.RENAME serialise comme str (StrEnum) -> from_dict OK.
            "op_type": OpType.RENAME,
            "internal_debug_field": "should-be-ignored",
            "future_field_v8": 42,
        }
        p = RenameProposal.from_dict(data)
        self.assertEqual(p.src_path, "/a")
        self.assertEqual(p.target_path, "/b")
        self.assertEqual(p.op_type, "RENAME")

    def test_from_dict_uses_defaults_for_missing_fields(self) -> None:
        p = RenameProposal.from_dict({"src_path": "/a", "target_path": "/a", "op_type": OpType.NOOP, "no_op": True})
        self.assertTrue(p.no_op)
        self.assertEqual(p.reasons, [])
        self.assertIsNone(p.confidence)

    def test_to_dict_is_json_safe_types(self) -> None:
        p = RenameProposal(
            src_path="/a",
            target_path="/b",
            op_type=OpType.RENAME,
            confidence=0.5,
        )
        d = p.to_dict()
        # Verifie qu'aucune valeur n'est un type exotique non serialisable.
        for key, value in d.items():
            self.assertIn(
                type(value).__name__,
                {"str", "bool", "float", "int", "list", "NoneType"},
                f"Champ {key} = {value!r} (type {type(value).__name__}) non json-safe",
            )


class ProbeResultTests(unittest.TestCase):
    """Tests ProbeResult : composition + acces aux donnees normalisees."""

    def _make_normalized(self) -> NormalizedProbe:
        return NormalizedProbe(
            path="/some/file.mkv",
            container="matroska",
            duration_s=7200.0,
            video={"codec": "hevc", "width": 3840, "height": 2160},
            audio_tracks=[{"codec": "truehd", "channels": 8}],
            probe_quality=PROBE_QUALITY_FULL,
        )

    def test_composition_exposes_normalized(self) -> None:
        nrm = self._make_normalized()
        src = ProbeSources(mediainfo=True, ffprobe=True)
        result = ProbeResult(normalized=nrm, sources=src)

        self.assertIs(result.normalized, nrm)
        self.assertEqual(result.normalized.video["width"], 3840)
        self.assertEqual(result.normalized.probe_quality, PROBE_QUALITY_FULL)

    def test_raw_payloads_optional(self) -> None:
        nrm = self._make_normalized()
        src = ProbeSources(manual_override=True)
        result = ProbeResult(normalized=nrm, sources=src)
        self.assertIsNone(result.raw_mediainfo)
        self.assertIsNone(result.raw_ffprobe)

    def test_raw_payloads_preserved_when_provided(self) -> None:
        nrm = self._make_normalized()
        src = ProbeSources(mediainfo=True, ffprobe=True)
        raw_mi = {"media": {"track": []}}
        raw_ff = {"streams": [], "format": {}}
        result = ProbeResult(normalized=nrm, sources=src, raw_mediainfo=raw_mi, raw_ffprobe=raw_ff)
        self.assertEqual(result.raw_mediainfo, raw_mi)
        self.assertEqual(result.raw_ffprobe, raw_ff)

    def test_to_dict_contains_normalized_and_sources(self) -> None:
        nrm = self._make_normalized()
        src = ProbeSources(mediainfo=True)
        src.merge_audio_track(0, "codec", "mediainfo")
        result = ProbeResult(normalized=nrm, sources=src)
        d = result.to_dict()
        self.assertIn("normalized", d)
        self.assertIn("sources", d)
        self.assertEqual(d["normalized"]["video"]["width"], 3840)
        self.assertEqual(d["sources"]["mediainfo"], True)


class BackwardCompatNormalizedProbeTests(unittest.TestCase):
    """Garde-fou : NormalizedProbe seul doit continuer a fonctionner."""

    def test_normalized_probe_minimal_construction_still_works(self) -> None:
        # Construction minimale historique (path uniquement)
        probe = NormalizedProbe(path="/x/movie.mkv")
        self.assertEqual(probe.path, "/x/movie.mkv")
        self.assertEqual(probe.probe_quality, PROBE_QUALITY_FAILED)
        self.assertEqual(probe.video, {})
        self.assertEqual(probe.audio_tracks, [])
        self.assertEqual(probe.subtitles, [])

    def test_normalized_probe_to_dict_unchanged(self) -> None:
        probe = NormalizedProbe(
            path="/x/movie.mkv",
            container="matroska",
            video={"codec": "hevc"},
            probe_quality=PROBE_QUALITY_FULL,
        )
        d = probe.to_dict()
        # Champs historiques presents
        self.assertEqual(d["path"], "/x/movie.mkv")
        self.assertEqual(d["container"], "matroska")
        self.assertEqual(d["video"], {"codec": "hevc"})
        self.assertEqual(d["probe_quality"], PROBE_QUALITY_FULL)
        # Aucun champ de Vague M ne pollue NormalizedProbe.to_dict
        self.assertNotIn("sources_tracking", d)
        self.assertNotIn("raw_mediainfo", d)
        self.assertNotIn("raw_ffprobe", d)

    def test_normalized_probe_signature_extra_fields_still_optional(self) -> None:
        """Les champs Vague K (container_format_long, chapters, etc.) restent
        optionnels avec defauts inchanges."""
        probe = NormalizedProbe(path="/x")
        self.assertIsNone(probe.container_format_long)
        self.assertIsNone(probe.container_size_bytes)
        self.assertEqual(probe.chapters, [])


class ProbeModelsExportsTests(unittest.TestCase):
    """Verifie que __all__ expose les nouveaux types pour `from ... import *`."""

    def test_all_contains_new_types(self) -> None:
        from cinesort.domain import probe_models

        self.assertIn("ProbeSources", probe_models.__all__)
        self.assertIn("RenameProposal", probe_models.__all__)
        self.assertIn("ProbeResult", probe_models.__all__)
        # Et conserve les exports historiques
        self.assertIn("NormalizedProbe", probe_models.__all__)
        self.assertIn("PROBE_QUALITY_FULL", probe_models.__all__)
        # VN-F.4 : constantes OpType canoniques exposees.
        self.assertIn("OP_TYPE_RENAME", probe_models.__all__)
        self.assertIn("OP_TYPE_MOVE", probe_models.__all__)
        self.assertIn("OP_TYPE_NOOP", probe_models.__all__)
        self.assertIn("OP_TYPE_VALUES", probe_models.__all__)
        # VO-D-2 : OpType StrEnum expose en single source of truth.
        self.assertIn("OpType", probe_models.__all__)
        self.assertEqual(probe_models.OpType.RENAME, "RENAME")
        self.assertEqual(probe_models.OpType.MOVE, probe_models.OP_TYPE_MOVE)
        self.assertEqual(probe_models.OpType.NOOP, probe_models.OP_TYPE_NOOP)


if __name__ == "__main__":
    unittest.main()
