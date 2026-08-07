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
    """Vue Accueil : apres demontage, 0 requete `run/get_dashboard` QUI LUI SOIT
    IMPUTABLE pendant 5 s.

    CE TEST NE S'EST JAMAIS EXECUTE JUSQU'AU 2026-08-07. Il capturait toute
    requete vers `run/get_dashboard`, sans distinguer l'appelant. Deux
    consequences, mesurees :

    1. `components/scan-banner.js` polle CETTE MEME ROUTE toutes les 5 s de
       facon globale et permanente, et re-tique sur chaque `hashchange` — donc
       a chaque navigation declenchee par le test. Ses requetes etaient
       comptees comme une fuite de la vue Accueil.
    2. La banniere ne demarre PAS sans authentification (`initScanBanner` sort
       si `!hasToken()`). Or le harnais n'avait aucun jeton : il vivait sur le
       bypass d'auth loopback. Il n'y avait donc AUCUN polling du tout, la
       ligne de base valait 0, et le test partait en `skip` a chaque fois.

    Le retrait du bypass a donne un jeton au harnais, la banniere a demarre, et
    le test a signale « INCOHERENCE : 0 polling avant, 2 apres ». Les deux
    requetes etaient celles de la banniere : un tick de `hashchange` et un tick
    d'intervalle. Zero fuite reelle.

    L'attribution se fait desormais par la PILE D'APPEL (`journal_fetch`), la
    seule chose qui distingue deux appelants d'une meme route.
    """
    from tests.e2e_dashboard.conftest import horloge_page, journal_fetch

    # Arriver sur /accueil (defaut apres login).
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(800)

    # Ligne de base : ~3 s, hors banniere.
    base_debut = horloge_page(dashboard_page)
    dashboard_page.wait_for_timeout(3000)
    base = journal_fetch(
        dashboard_page, depuis_ms=base_debut, motif_url="/api/run/get_dashboard", exclure_module="scan-banner"
    )

    # Naviguer vers /settings -> declenche unmountAccueil.
    dashboard_page.evaluate("window.location.hash = '#/settings'")
    dashboard_page.wait_for_timeout(500)

    # Mesure : 5 s post-demontage.
    apres_debut = horloge_page(dashboard_page)
    dashboard_page.wait_for_timeout(5000)
    fuites = journal_fetch(
        dashboard_page,
        depuis_ms=apres_debut + 700,  # grace 700 ms (course tick/abort)
        motif_url="/api/run/get_dashboard",
        exclure_module="scan-banner",
    )

    # CONTRE-EPREUVE : la banniere DOIT etre visible dans le journal. Si elle
    # est absente, c'est que rien ne polle du tout — et l'assertion ci-dessous
    # passerait pour la mauvaise raison, exactement comme avant.
    banniere = [
        e
        for e in journal_fetch(dashboard_page, motif_url="/api/run/get_dashboard")
        if "scan-banner" in str(e.get("pile", ""))
    ]
    assert banniere, (
        "aucune requete de scan-banner observee : le harnais n'est pas authentifie, "
        "ou le journal de fetch n'est pas installe — l'assertion suivante ne prouverait rien"
    )

    assert not fuites, (
        f"FUITE POLLING apres unmountAccueil : {len(fuites)} requete(s) imputables a la vue "
        f"dans la fenetre de 5 s (ligne de base avant demontage : {len(base)} en 3 s). "
        f"Echantillon : {[e['url'] for e in fuites[:3]]}"
    )
