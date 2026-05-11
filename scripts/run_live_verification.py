from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_TESTS_DIR = REPO_ROOT / "tests" / "live"
PATTERNS = {
    "tmdb": "test_tmdb_live.py",
    "probe": "test_probe_tools_live.py",
    "pywebview": "test_pywebview_native_live.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run opt-in live verification suites for external integrations.")
    parser.add_argument(
        "--suite",
        action="append",
        choices=sorted(PATTERNS),
        help="Restrict execution to one or more live suites. Default: all suites.",
    )
    return parser.parse_args()


def load_live_env():
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(LIVE_TESTS_DIR))
    import live_env

    return live_env


def run_suite(suite: str) -> int:
    pattern = PATTERNS[suite]
    cmd = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(LIVE_TESTS_DIR),
        "-p",
        pattern,
        "-v",
    ]
    print(f"[RUN] suite={suite} pattern={pattern}")
    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    return int(completed.returncode)


def main() -> int:
    args = parse_args()
    suites = list(args.suite or PATTERNS.keys())
    live_env = load_live_env()

    print("[INFO] Verification standard = check_project.bat")
    print("[INFO] Les preuves live sont opt-in et n'entrent pas dans le gate standard.")
    print(
        "[INFO] Env attendues: CINESORT_LIVE_TMDB, CINESORT_TMDB_API_KEY, "
        "CINESORT_LIVE_PROBE, CINESORT_FFPROBE_PATH, CINESORT_MEDIAINFO_PATH, "
        "CINESORT_MEDIA_SAMPLE_PATH, CINESORT_LIVE_PYWEBVIEW"
    )
    print(json.dumps(live_env.describe_capabilities(), ensure_ascii=False, indent=2))

    result = 0
    for suite in suites:
        rc = run_suite(suite)
        if rc != 0 and result == 0:
            result = rc
    return result


if __name__ == "__main__":
    raise SystemExit(main())
