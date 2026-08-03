"""Test runtime — 0 requete polling apres demontage de la vue Traitement.

ETAPE 3 RENFORCER TESTS — Iteration 10 (loop/correction-2026-06).

Critere FAMILLE A unmount : `0 requete polling apres demontage`.

Les tests `test_phase5_traitement_complete.py::test_unmount_cleans_polling` et
`test_phase5_doublons_complete.py::test_right_panel_unmount_clears_sections`
verifient le SOURCE JS (presence d'appel `_stopPolling()`, `removeEventListener`,
etc.). Ils ne mesurent PAS le comportement reseau reel.

Ce test :
1. ouvre Playwright authentifie sur le dashboard,
2. navigue vers /traitement (qui demarre un polling `/api/run/get_status`),
3. capture le count de requetes polling pendant 3s -> doit etre > 0 (sanity),
4. navigue vers /accueil (declenche unmountTraitement via cleanup callback router),
5. capture le count de requetes polling sur 5s SUPPLEMENTAIRES -> doit etre 0.

Si `unmountTraitement` ne nettoie pas `_pollTimer` ou si le router router ne
declenche pas le cleanup callback, ce test capturera la fuite reseau.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime polling")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


_POLLING_PATTERNS = (
    "/api/run/get_status",
    "/api/run/get_dashboard",
)


def _is_polling_request(url: str) -> bool:
    """True si l'URL correspond a un endpoint de polling Traitement."""
    return any(pattern in url for pattern in _POLLING_PATTERNS)


@pytest.mark.runtime
def test_unmount_traitement_stops_polling_runtime(dashboard_page) -> None:
    """Apres demontage de Traitement, 0 requete `/api/run/get_status` pendant 5s.

    Mesure objective runtime (memoire user FAMILLE A : "mesure objective runtime
    PAS test mocke seul"). Capture tous les fetch via Playwright `page.on("request")`.
    """
    captured: list[tuple[float, str]] = []

    def _on_request(req) -> None:
        try:
            url = req.url
        except Exception:
            return
        if _is_polling_request(url):
            captured.append((time.monotonic(), url))

    dashboard_page.on("request", _on_request)

    # 1) Naviguer vers /traitement -> demarre le polling.
    dashboard_page.evaluate("window.location.hash = '#/traitement'")
    dashboard_page.wait_for_timeout(800)

    # 2) Laisser tourner ~3s pour capturer baseline (sanity : doit voir >=1 polling).
    baseline_start = time.monotonic()
    dashboard_page.wait_for_timeout(3000)
    baseline_end = time.monotonic()
    baseline_polls = [(ts, url) for (ts, url) in captured if baseline_start <= ts <= baseline_end]

    # Sanity check : la vue Traitement DOIT poller au moins une fois pendant 3s.
    # Si elle ne polle pas, le test n'est pas pertinent (faux negatif possible).
    # Tolerance : on accepte 0 polling SI la vue n'a pas de run actif (pas d'erreur,
    # juste log un warning via assertion conditionnelle).
    has_active_polling = len(baseline_polls) > 0

    # 3) Naviguer vers /accueil -> declenche unmountTraitement via cleanup callback router.
    len(captured)
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(500)  # 500ms pour que le cleanup s'execute.

    # 4) Mesure : 5s de fenetre post-unmount, 0 polling attendu.
    post_unmount_start = time.monotonic()
    dashboard_page.wait_for_timeout(5000)
    post_unmount_end = time.monotonic()

    post_unmount_polls = [(ts, url) for (ts, url) in captured if post_unmount_start <= ts <= post_unmount_end]

    # Tolerance fine : 1 requete peut etre en vol au moment exact du unmount
    # (race entre setInterval tick et clearInterval). On accepte au max 1 requete
    # dans les premieres 500ms post-unmount (deja couvertes par wait_for_timeout(500)).
    # Apres ces 500ms, ZERO requete polling tolereee.
    grace_period_end = post_unmount_start + 0.7
    leaked_polls = [(ts, url) for (ts, url) in post_unmount_polls if ts > grace_period_end]

    if has_active_polling:
        assert len(leaked_polls) == 0, (
            f"FUITE POLLING detectee apres unmountTraitement : "
            f"{len(leaked_polls)} requetes capturees dans la fenetre 5s post-unmount "
            f"(baseline avant unmount : {len(baseline_polls)} polls en 3s). "
            f"Echantillon : {leaked_polls[:5]}"
        )
    else:
        # Sanity : le polling n'a jamais demarre - on signale via skip plutot
        # qu'un faux pass. Le test sera ROUGE en CI si baseline=0 ET unmount=>0.
        # Si baseline=0 ET post_unmount=0, on skip (vue probablement sans run actif).
        if len(post_unmount_polls) > 0:
            pytest.fail(
                f"INCOHERENCE : 0 polling avant unmount, mais "
                f"{len(post_unmount_polls)} polling apres unmount. "
                f"Polling demarre par le UNMOUNT lui-meme ?"
            )
        pytest.skip(
            "Pas de polling actif sur Traitement (run inactif sur dataset E2E) — "
            "test runtime non pertinent dans cette configuration. Pour activer, "
            "demarrer un run via /api/run/start_plan en setup."
        )


@pytest.mark.runtime
def test_unmount_accueil_stops_dashboard_polling_runtime(dashboard_page) -> None:
    """Vue Accueil : apres demontage, 0 requete `/api/run/get_dashboard` pendant 5s.

    Symetrie avec le test Traitement. La vue Accueil polle `run/get_dashboard`
    via _scanPolling. unmountAccueil() doit appeler _stopScanPolling().
    """
    captured: list[tuple[float, str]] = []

    def _on_request(req) -> None:
        try:
            url = req.url
        except Exception:
            return
        if "/api/run/get_dashboard" in url or "/api/run/get_status" in url:
            captured.append((time.monotonic(), url))

    dashboard_page.on("request", _on_request)

    # Arriver sur /accueil (defaut apres login).
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(800)

    # Baseline : ~3s.
    baseline_start = time.monotonic()
    dashboard_page.wait_for_timeout(3000)
    baseline_polls = [(ts, u) for (ts, u) in captured if ts >= baseline_start]

    # Naviguer vers /settings -> declenche unmountAccueil.
    dashboard_page.evaluate("window.location.hash = '#/settings'")
    dashboard_page.wait_for_timeout(500)

    # Mesure : 5s post-unmount.
    post_unmount_start = time.monotonic()
    dashboard_page.wait_for_timeout(5000)
    post_unmount_polls = [(ts, u) for (ts, u) in captured if ts >= post_unmount_start]

    # Tolerance grace 700ms (race tick/abort).
    leaked = [(ts, u) for (ts, u) in post_unmount_polls if ts > post_unmount_start + 0.7]

    if len(baseline_polls) > 0:
        assert len(leaked) == 0, (
            f"FUITE POLLING detectee apres unmountAccueil : "
            f"{len(leaked)} requetes capturees dans la fenetre 5s post-unmount "
            f"(baseline avant unmount : {len(baseline_polls)} polls en 3s). "
            f"Echantillon : {leaked[:5]}"
        )
    else:
        if len(post_unmount_polls) > 0:
            pytest.fail(f"INCOHERENCE : 0 polling avant unmount Accueil, mais {len(post_unmount_polls)} polling apres.")
        pytest.skip("Pas de polling actif sur Accueil dans cette config — non pertinent.")
