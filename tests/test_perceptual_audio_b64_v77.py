"""MEGA-HOTFIX bug (2) : couverture tracked_run + encoding audio_b64.

Verifie que `compute_audio_fingerprint` :

1. Utilise bien `tracked_run` (cleanup garanti des childs ffmpeg/fpcalc,
   memoire `feedback_cinesort_design` : subprocess direct, pas de wrapper).
2. Retourne un fingerprint base64 ASCII (`audio_b64`) lorsque fpcalc
   repond avec une liste d'entiers 32-bit.
3. Gracefully renvoie None si fpcalc echoue (returncode != 0, JSON
   invalide, OSError, TimeoutExpired) sans propager d'exception au caller.

Les tests mockent `tracked_run` au niveau du module
`cinesort.domain.perceptual.audio_fingerprint` pour eviter toute
dependance reelle a un binaire fpcalc sur la machine CI/dev.
"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cinesort.domain.perceptual import audio_fingerprint


def _make_completed_process(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Reproduit le shape de subprocess.CompletedProcess utilise dans le module."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _encode_expected(fp_ints):
    buf = struct.pack(f"<{len(fp_ints)}I", *fp_ints)
    return base64.b64encode(buf).decode("ascii")


class ComputeFingerprintTrackedRunTests(unittest.TestCase):
    """Verifie l'usage du wrapper tracked_run dans le path direct fpcalc."""

    def test_returns_b64_string_on_success(self) -> None:
        fp_ints = [1, 2, 3, 4, 0xDEADBEEF]
        stdout_json = json.dumps({"fingerprint": fp_ints})
        cp = _make_completed_process(stdout=stdout_json)

        with patch.object(audio_fingerprint, "tracked_run", return_value=cp) as mock_run:
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,  # < MIN -> offset=0, path direct
                fpcalc_path="/fake/fpcalc",
            )

        self.assertIsNotNone(out, "Doit renvoyer un fingerprint base64")
        self.assertIsInstance(out, str)
        # Le b64 doit etre ASCII (sortie .decode("ascii") dans _encode_fingerprint).
        out.encode("ascii")  # ne doit pas lever
        self.assertEqual(out, _encode_expected(fp_ints))
        mock_run.assert_called_once()

    def test_tracked_run_called_with_fpcalc_cmd_for_short_files(self) -> None:
        fp_ints = [42]
        stdout_json = json.dumps({"fingerprint": fp_ints})
        cp = _make_completed_process(stdout=stdout_json)

        with patch.object(audio_fingerprint, "tracked_run", return_value=cp) as mock_run:
            audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=5.0,
                fpcalc_path="/fake/fpcalc",
            )

        args, kwargs = mock_run.call_args
        cmd = args[0]
        # Premier element = chemin fpcalc fourni.
        self.assertEqual(cmd[0], "/fake/fpcalc")
        self.assertIn("-json", cmd)
        self.assertIn("-raw", cmd)
        # tracked_run doit etre invoque avec capture_output + text=True (semantique
        # subprocess.run et compatible mock CompletedProcess).
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))
        # timeout floor >= 1s (max(1.0, ...) dans le code).
        self.assertGreaterEqual(float(kwargs.get("timeout") or 0.0), 1.0)

    def test_returns_none_on_non_zero_returncode(self) -> None:
        cp = _make_completed_process(returncode=2, stdout="", stderr="fpcalc fatal")
        with patch.object(audio_fingerprint, "tracked_run", return_value=cp):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_on_invalid_json(self) -> None:
        cp = _make_completed_process(stdout="not-json")
        with patch.object(audio_fingerprint, "tracked_run", return_value=cp):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_on_empty_fingerprint(self) -> None:
        cp = _make_completed_process(stdout=json.dumps({"fingerprint": []}))
        with patch.object(audio_fingerprint, "tracked_run", return_value=cp):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_on_missing_fingerprint_key(self) -> None:
        cp = _make_completed_process(stdout=json.dumps({}))
        with patch.object(audio_fingerprint, "tracked_run", return_value=cp):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_on_non_numeric_fingerprint_entries(self) -> None:
        cp = _make_completed_process(stdout=json.dumps({"fingerprint": ["abc", "def"]}))
        with patch.object(audio_fingerprint, "tracked_run", return_value=cp):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_on_timeout_expired(self) -> None:
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["fpcalc"], timeout=1.0)

        with patch.object(audio_fingerprint, "tracked_run", side_effect=raise_timeout):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_on_os_error(self) -> None:
        def raise_oserror(*args, **kwargs):
            raise OSError("binary not found")

        with patch.object(audio_fingerprint, "tracked_run", side_effect=raise_oserror):
            out = audio_fingerprint.compute_audio_fingerprint(
                "/fake/media.mkv",
                duration_s=10.0,
                fpcalc_path="/fake/fpcalc",
            )
        self.assertIsNone(out)

    def test_returns_none_when_fpcalc_unavailable(self) -> None:
        # `resolve_fpcalc_path` retourne None -> court-circuit total.
        with patch.object(audio_fingerprint, "resolve_fpcalc_path", return_value=None):
            with patch.object(audio_fingerprint, "tracked_run") as mock_run:
                out = audio_fingerprint.compute_audio_fingerprint(
                    "/fake/media.mkv",
                    duration_s=10.0,
                    fpcalc_path=None,
                )
        self.assertIsNone(out)
        mock_run.assert_not_called()


class FingerprintEncodingTests(unittest.TestCase):
    """Verifie l'encodage base64 (_encode_fingerprint) du resultat."""

    def test_encode_known_vector(self) -> None:
        ints = [0, 1, 0xFFFFFFFF]
        encoded = audio_fingerprint._encode_fingerprint(ints)
        # Decode back -> on doit retrouver la liste exacte.
        decoded = audio_fingerprint._decode_fingerprint(encoded)
        self.assertEqual(decoded, ints)

    def test_b64_alphabet_only(self) -> None:
        # Sortie base64 standard (ASCII), pas de caractere non-ASCII.
        ints = list(range(100))
        encoded = audio_fingerprint._encode_fingerprint(ints)
        # base64 standard : [A-Za-z0-9+/=]
        for c in encoded:
            self.assertIn(
                c,
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
                f"caractere non base64 detecte : {c!r}",
            )

    def test_clamps_to_uint32(self) -> None:
        # Le module masque & 0xFFFFFFFF -> meme avec un grand entier on doit
        # avoir un encodage stable et decodable.
        big = (1 << 64) | 0xABCDEF
        ints = [big & 0xFFFFFFFF]
        encoded = audio_fingerprint._encode_fingerprint(ints)
        decoded = audio_fingerprint._decode_fingerprint(encoded)
        self.assertEqual(decoded, [0xABCDEF])


if __name__ == "__main__":
    unittest.main()
