"""M-1 audit QA 20260429 — tests fs_safety (timeout sur operations FS).

Verifie que :
- run_with_timeout retourne le resultat si fn termine a temps.
- run_with_timeout retourne default si fn hang plus longtemps que timeout.
- run_with_timeout tolere les exceptions.
- is_path_accessible / is_dir_accessible / safe_path_exists fonctionnent
  sur des paths normaux + simulent un timeout NAS via mock.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.fs_safety import (
    DEFAULT_FS_TIMEOUT_S,
    is_dir_accessible,
    is_path_accessible,
    run_with_timeout,
    safe_path_exists,
)


class RunWithTimeoutTests(unittest.TestCase):
    def test_returns_value_when_fn_completes(self) -> None:
        result = run_with_timeout(lambda: 42, timeout_s=1.0, default=-1)
        self.assertEqual(result, 42)

    def test_returns_default_on_timeout(self) -> None:
        """Cf issue #88 : timeout=1.0s + marge x3 pour tolerer la latence
        Windows + AV (l'ancien timeout=0.3s + marge 2x echouait sporadiquement).
        """

        def slow_fn() -> int:
            time.sleep(5.0)
            return 99

        start = time.monotonic()
        result = run_with_timeout(slow_fn, timeout_s=1.0, default=-1)
        elapsed = time.monotonic() - start
        self.assertEqual(result, -1)
        # Marge 3x = 3.0s. Le timeout reel est 1.0s, on tolere 2.0s de
        # latence Windows + AV scanning + threadpool teardown.
        self.assertLess(elapsed, 3.0, f"elapsed={elapsed:.3f}s (timeout=1.0s)")

    def test_returns_default_on_exception(self) -> None:
        def fail_fn() -> int:
            raise RuntimeError("boom")

        result = run_with_timeout(fail_fn, timeout_s=1.0, default="fallback")
        self.assertEqual(result, "fallback")

    def test_minimum_timeout_clamped(self) -> None:
        # timeout 0 ou negatif est clamped a 0.1s
        result = run_with_timeout(lambda: "ok", timeout_s=0.0, default="default")
        # Le clamp permet a fn() instantane de retourner avant timeout
        self.assertEqual(result, "ok")


class PathAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_fs_safety_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_is_path_accessible_existing_dir(self) -> None:
        self.assertTrue(is_path_accessible(self.tmp, timeout_s=5.0))

    def test_is_path_accessible_missing(self) -> None:
        self.assertFalse(is_path_accessible(self.tmp / "ghost", timeout_s=5.0))

    def test_is_dir_accessible_dir(self) -> None:
        self.assertTrue(is_dir_accessible(self.tmp, timeout_s=5.0))

    def test_is_dir_accessible_file(self) -> None:
        f = self.tmp / "file.txt"
        f.write_text("x")
        self.assertFalse(is_dir_accessible(f, timeout_s=5.0))

    def test_safe_path_exists_3_states(self) -> None:
        # True = exists
        self.assertTrue(safe_path_exists(self.tmp))
        # False = not exists
        self.assertFalse(safe_path_exists(self.tmp / "ghost"))

    def test_safe_path_exists_returns_none_on_timeout(self) -> None:
        """Mock un Path.exists() qui hang plus longtemps que le timeout."""
        # On mock Path.exists pour bloquer 2 secondes
        original_exists = Path.exists

        def slow_exists(self, *args, **kwargs):  # noqa: ANN001
            time.sleep(2.0)
            return original_exists(self, *args, **kwargs)

        with patch.object(Path, "exists", slow_exists):
            result = safe_path_exists(self.tmp, timeout_s=0.3)
        self.assertIsNone(result)  # 3-etat : None = timeout

    def test_is_path_accessible_returns_false_on_timeout(self) -> None:
        """Si le syscall hang, is_path_accessible retourne False (pas True)."""
        original_exists = Path.exists

        def slow_exists(self, *args, **kwargs):  # noqa: ANN001
            time.sleep(2.0)
            return original_exists(self, *args, **kwargs)

        with patch.object(Path, "exists", slow_exists):
            result = is_path_accessible(self.tmp, timeout_s=0.3)
        self.assertFalse(result)


class DefaultTimeoutConstantTests(unittest.TestCase):
    def test_default_is_reasonable(self) -> None:
        """DEFAULT_FS_TIMEOUT_S est dans la fourchette 5-30s."""
        self.assertGreaterEqual(DEFAULT_FS_TIMEOUT_S, 5.0)
        self.assertLessEqual(DEFAULT_FS_TIMEOUT_S, 30.0)


if __name__ == "__main__":
    unittest.main()
