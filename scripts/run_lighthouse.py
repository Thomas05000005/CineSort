"""V4-05 — Lance Lighthouse sur le dashboard CineSort + parse resultats.

Usage:
  1. Lancer l'app dans un autre terminal : python app.py
  2. python scripts/run_lighthouse.py [token] [output_dir]

Pre-requis : Node.js + npx (Lighthouse est install a la volee via npx).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"
DEFAULT_CATEGORIES = ["performance", "accessibility", "best-practices"]
DEFAULT_OUTPUT_DIR = "audit/results/lighthouse"
THRESHOLDS_DISPLAY = {"performance": 70, "accessibility": 85, "best-practices": 85}


_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _resolve_npx() -> str | None:
    """Trouve l'executable npx (npx.cmd sur Windows)."""
    for name in ("npx.cmd", "npx"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _resolve_chrome_path() -> str | None:
    """Cherche Chrome puis fallback Edge (Chromium-based, OK pour Lighthouse)."""
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).is_file():
        return env_path
    for name in ("chrome.exe", "chrome", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _EDGE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def run_lighthouse(url: str, output_dir: Path, categories: list[str]) -> dict:
    """Lance Lighthouse et retourne {category: score 0-100}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / "lighthouse_report"
    json_path = output_dir / "lighthouse_report.report.json"

    npx = _resolve_npx()
    if not npx:
        raise RuntimeError("npx introuvable dans PATH. Install Node.js : https://nodejs.org/")

    # Construction explicite avec quoting pour Windows : npx.cmd s'execute
    # via cmd.exe et celui-ci interprete '&' comme separateur de commandes.
    # On quote l'URL en double-quotes pour preserver les '&'.
    chrome_flags = "--headless=new --no-sandbox --disable-gpu"
    cmd_parts = [
        f'"{npx}"',
        "--yes",
        "lighthouse",
        f'"{url}"',
        "--output=json",
        "--output=html",
        f'--output-path="{base}"',
        f'--chrome-flags="{chrome_flags}"',
        "--only-categories=" + ",".join(categories),
        "--quiet",
    ]
    cmd_str = " ".join(cmd_parts)

    env = os.environ.copy()
    chrome_path = _resolve_chrome_path()
    if chrome_path:
        env["CHROME_PATH"] = chrome_path
        logger.info("Using browser: %s", chrome_path)

    logger.info("Running: %s", cmd_str)
    # shell=True + string : cmd.exe parse correctement les guillemets doubles.
    result = subprocess.run(cmd_str, capture_output=True, text=True, timeout=180, env=env, shell=True)

    # Lighthouse peut returner code 1 pour un EPERM lors du cleanup tmp/Chrome,
    # alors que le rapport est deja ecrit. On verifie d'abord si le JSON existe.
    if not json_path.is_file():
        raise RuntimeError(
            f"Lighthouse JSON manquant : {json_path} "
            f"(code {result.returncode})\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-2000:]}"
        )
    if result.returncode != 0:
        # Rapport ecrit mais code != 0 → log warning et continue.
        logger.warning(
            "Lighthouse exited with code %d but report was generated. "
            "Probable cleanup error (EPERM on Chrome temp dir).",
            result.returncode,
        )

    data = json.loads(json_path.read_text(encoding="utf-8"))
    scores = {}
    for cat_id, cat_data in data.get("categories", {}).items():
        score = cat_data.get("score")
        scores[cat_id] = round((score or 0) * 100) if score is not None else None
    return scores


def main():
    parser = argparse.ArgumentParser(description="V4-05 Lighthouse runner")
    parser.add_argument(
        "token",
        nargs="?",
        default=os.environ.get("CINESORT_API_TOKEN", ""),
        help="REST API token (sinon CINESORT_API_TOKEN env var)",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Repertoire de sortie (defaut: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    if not args.token:
        print("[ERREUR] Token requis. Passe en arg ou via CINESORT_API_TOKEN.")
        print("  Le token est dans <state_dir>/settings.json -> rest_api_token")
        sys.exit(1)

    if not _resolve_npx():
        print("[ERREUR] Node.js + npx requis. Install: https://nodejs.org/")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    url = f"{DASHBOARD_URL}?ntoken={args.token}&native=1"

    print(f"Running Lighthouse on {url}")
    try:
        scores = run_lighthouse(url, output_dir, DEFAULT_CATEGORIES)
    except RuntimeError as exc:
        print(f"[ERREUR] {exc}")
        sys.exit(2)

    print("\n=== Scores ===")
    for cat in DEFAULT_CATEGORIES:
        score = scores.get(cat)
        if score is None:
            print(f"  ?  {cat}: N/A")
            continue
        seuil = THRESHOLDS_DISPLAY.get(cat, 80)
        verdict = "OK" if score >= seuil else "WARN" if score >= seuil - 15 else "FAIL"
        print(f"  [{verdict}] {cat}: {score}/100 (seuil {seuil})")

    print(f"\nRapport HTML : {output_dir}/lighthouse_report.report.html")

    summary = output_dir / "summary.json"
    summary.write_text(json.dumps(scores, indent=2), encoding="utf-8")
    print(f"Summary: {summary}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
