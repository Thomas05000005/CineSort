"""Fixtures E2E desktop — lance CineSort pywebview et connecte Playwright via CDP."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

try:
    import allure
except ImportError:
    allure = None

# Le dossier racine du projet
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CDP_PORT = int(os.environ.get("CINESORT_CDP_PORT", "9222"))
APP_READY_TIMEOUT_MS = 30_000


# ---------------------------------------------------------------------------
# Session-scoped : lance l'app une seule fois pour toute la session de tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app_process():
    """Lance CineSort avec le mode E2E active (CDP port ouvert)."""
    env = os.environ.copy()
    env["CINESORT_E2E"] = "1"
    env["CINESORT_CDP_PORT"] = str(CDP_PORT)

    python = sys.executable
    proc = subprocess.Popen(
        [python, "app.py"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Attendre que le port CDP soit disponible
    _wait_for_port("localhost", CDP_PORT, timeout_s=30)
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def browser(app_process):
    """Connecte Playwright au pywebview via Chrome DevTools Protocol."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    yield browser
    browser.close()
    pw.stop()


@pytest.fixture(scope="function")
def page(browser):
    """Recupere la page principale du pywebview et attend qu'elle soit prete."""
    ctx = browser.contexts[0]
    pg = ctx.pages[0]
    # Attendre que l'app soit completement initialisee
    pg.wait_for_function("() => window.__APP_READY__ === true", timeout=APP_READY_TIMEOUT_MS)
    return pg


# ---------------------------------------------------------------------------
# Fixture : mini-bibliotheque de test (20 films)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_library(tmp_path_factory):
    """Cree 20 films factices sur le disque pour les tests E2E."""
    from .fixtures.test_library import create_test_library

    base = tmp_path_factory.mktemp("e2e_films")
    return create_test_library(base)


# ---------------------------------------------------------------------------
# Screenshot automatique en cas d'echec (+ Allure)
# ---------------------------------------------------------------------------


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture un screenshot automatique si le test echoue."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        page = item.funcargs.get("page")
        if page:
            name = item.name.replace("/", "_").replace("::", "_")
            ss_dir = PROJECT_ROOT / "tests" / "e2e_desktop" / "screenshots"
            ss_dir.mkdir(exist_ok=True)
            path = ss_dir / f"FAIL_{name}.png"
            try:
                png = page.screenshot(path=str(path))
                if allure and png:
                    allure.attach(png, name=f"FAIL_{name}", attachment_type=allure.attachment_type.PNG)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for_port(host: str, port: int, timeout_s: int = 30) -> None:
    """Attend que le port soit ouvert (polling 1s)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    pytest.fail(f"Port {host}:{port} non disponible apres {timeout_s}s")
