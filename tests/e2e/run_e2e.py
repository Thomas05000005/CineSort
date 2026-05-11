#!/usr/bin/env python3
"""Script helper pour lancer les tests E2E CineSort.

Usage :
    python tests/e2e/run_e2e.py                    # lance tout
    python tests/e2e/run_e2e.py --headed            # navigateur visible
    python tests/e2e/run_e2e.py -k test_01_login    # filtre tests
    python tests/e2e/run_e2e.py --update-snapshots  # regenerer baselines visuelles
    python tests/e2e/run_e2e.py --install            # installer le navigateur Chromium
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    args = sys.argv[1:]

    # --visual-catalog : generer le catalogue visuel + rapport HTML
    if "--visual-catalog" in args:
        args.remove("--visual-catalog")
        headed = "--headed" in args
        catalog_args = [sys.executable, os.path.join(os.path.dirname(__file__), "visual_catalog.py")]
        if headed:
            catalog_args.append("--headed")
            args.remove("--headed")
        print("[e2e] Generation du catalogue visuel...")
        rc = subprocess.call(catalog_args)
        if rc != 0:
            return rc
        report_args = [sys.executable, os.path.join(os.path.dirname(__file__), "generate_visual_report.py")]
        print("[e2e] Generation du rapport HTML...")
        rc = subprocess.call(report_args)
        report_path = os.path.join(os.path.dirname(__file__), "visual_report.html")
        if os.path.exists(report_path):
            print(f"[e2e] Rapport : {report_path}")
        return rc

    # --install : installer Chromium
    if "--install" in args:
        print("[e2e] Installation de Chromium via Playwright...")
        rc = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        if rc != 0:
            print("[e2e] Echec installation Chromium.")
            return rc
        print("[e2e] Chromium installe.")
        args.remove("--install")
        if not args:
            return 0

    # Verifier que pytest-playwright est installe
    try:
        import pytest  # noqa: F401
        import playwright  # noqa: F401
    except ImportError:
        print("[e2e] pytest-playwright non installe. Lancez : pip install pytest-playwright")
        return 1

    # --update-snapshots
    if "--update-snapshots" in args:
        os.environ["PLAYWRIGHT_UPDATE_SNAPSHOTS"] = "1"
        args.remove("--update-snapshots")

    # Construire les arguments pytest
    pytest_args = [
        "--browser",
        "chromium",
    ]

    # Passer les flags utilisateur
    headed = "--headed" in args
    if headed:
        pytest_args.append("--headed")
        args.remove("--headed")

    # Ajouter les flags restants (-k, -x, -v, etc.)
    pytest_args.extend(args)

    # Ajouter le dossier de tests
    if not any(a.startswith("tests/e2e") or a.startswith("tests\\e2e") for a in pytest_args):
        pytest_args.append("tests/e2e/")

    print(f"[e2e] pytest {' '.join(pytest_args)}")
    import pytest as _pytest

    rc = _pytest.main(pytest_args)

    # Afficher le rapport UI s'il a ete genere
    report = os.path.join(os.path.dirname(__file__), "ui_report.md")
    if os.path.exists(report):
        print(f"\n[e2e] Rapport UI genere : {report}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
