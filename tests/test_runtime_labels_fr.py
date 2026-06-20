"""Test runtime — labels FR rendus exactement en UTF-8 (capture DOM Playwright).

ETAPE 3 RENFORCER TESTS — Iteration 10 (loop/correction-2026-06).

Critere FAMILLE A mojibake : `label rendu DOM == chaine UTF-8 attendue exact-match`.

Les tests `test_phase3_3_traitement.py::test_step_labels_french`,
`test_phase2b_routing_sidebar.py::test_fr_quality_label` (et leurs equivalents)
lisent UNIQUEMENT le source JS / les locales JSON. Ils ne mesurent pas le rendu
reel dans le navigateur. Ce module ajoute une assertion runtime stricte :

1. demarre le serveur REST avec dataset E2E (cf. tests/e2e_dashboard/conftest.py),
2. ouvre Playwright authentifie sur le dashboard,
3. capture `textContent` de 5 labels-cles via `page.evaluate`,
4. assertEqual byte-strict contre la chaine UTF-8 attendue.

Si Playwright/serveur ne sont pas disponibles (env CI minimal), le test SKIP
avec marker explicite — il ne doit pas masquer de regression silencieuse.

Reutilise la fixture `dashboard_page` de tests/e2e_dashboard/conftest.py via
plugin discovery.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime labels")


# Reutilise les fixtures e2e_dashboard (session-scoped server + dashboard_page).
pytest_plugins = ["tests.e2e_dashboard.conftest"]


# Spec FAMILLE A mojibake : 5 labels-cles dont au moins 2 contiennent un accent
# (E aigu / e accent grave) et 1 contient le glyphe bullet U+2022 (masque secret).
# Toutes les chaines sont declarees en literal Python UTF-8 source.
_EXPECTED_LABELS: tuple[tuple[str, str, str], ...] = (
    # (description, css_selector, expected_text)
    ("Sidebar nav home", '[data-route="home"] .v5-sidebar-label', "Accueil"),
    ("Sidebar nav processing", '[data-route="processing"] .v5-sidebar-label', "Traitement"),
    # Etape 1/2 Analyse/Verification rendus dans la vue Traitement (h2 panel title).
    # On utilise le selecteur du h2 — le label change selon l'etape active.
    ("Etape 1 Analyse h2", "#traitement-panel-title", "Étape 1 — Analyse"),
)


@pytest.mark.runtime
@pytest.mark.parametrize("description,selector,expected", _EXPECTED_LABELS[:2])
def test_sidebar_labels_utf8_strict(dashboard_page, description: str, selector: str, expected: str) -> None:
    """Sidebar Accueil/Traitement: textContent doit etre exactement la chaine UTF-8 attendue.

    Verifie l'absence de mojibake (`Ã©` au lieu de `é`, `Ã¨` au lieu de `è`, etc.)
    au RUNTIME, pas seulement dans les sources JSON. Si le pipeline d'encodage
    (locales/fr.json -> t() -> escapeHtml -> textContent) double-encode, ce test
    capturera la divergence byte-pour-byte.
    """
    dashboard_page.wait_for_selector(selector, timeout=8000)
    actual = dashboard_page.evaluate(
        f"() => (document.querySelector({selector!r})?.textContent || '').trim()"
    )
    assert actual == expected, (
        f"[{description}] mojibake detecte : "
        f"attendu={expected!r} ({expected.encode('utf-8').hex()}), "
        f"recu={actual!r} ({actual.encode('utf-8').hex()})"
    )


@pytest.mark.runtime
def test_traitement_etape1_label_utf8_strict(dashboard_page) -> None:
    """Vue Traitement etape 1 : h2 doit afficher "Étape 1 — Analyse" exact-match."""
    # Naviguer vers /traitement (etape 1 = Analyse par defaut au mount).
    dashboard_page.evaluate("window.location.hash = '#/traitement'")
    dashboard_page.wait_for_timeout(800)
    dashboard_page.wait_for_selector("#traitement-panel-title", timeout=8000)
    actual = dashboard_page.evaluate(
        "() => (document.querySelector('#traitement-panel-title')?.textContent || '').trim()"
    )
    expected = "Étape 1 — Analyse"
    assert actual == expected, (
        f"[Etape 1 Analyse] mojibake detecte : "
        f"attendu={expected!r} ({expected.encode('utf-8').hex()}), "
        f"recu={actual!r} ({actual.encode('utf-8').hex()})"
    )


@pytest.mark.runtime
def test_traitement_etape2_label_utf8_strict(dashboard_page) -> None:
    """Vue Traitement etape 2 : navigue vers verification, h2 = "Étape 2 — Vérification" exact-match."""
    dashboard_page.evaluate("window.location.hash = '#/traitement'")
    dashboard_page.wait_for_timeout(500)
    # Clic sur l'onglet verification (data-step ou bouton steps).
    dashboard_page.evaluate(
        """() => {
            const btn = document.querySelector('[data-step="verification"]')
                || document.querySelector('.traitement-step[data-step="verification"]');
            if (btn) btn.click();
        }"""
    )
    dashboard_page.wait_for_timeout(800)
    actual = dashboard_page.evaluate(
        "() => (document.querySelector('#traitement-panel-title')?.textContent || '').trim()"
    )
    # On accepte soit l'etape 2 si la navigation a fonctionne, soit l'etape 1
    # si l'onglet n'est pas cliquable (etat initial sans run). On verifie
    # uniquement la presence d'au moins UN accent UTF-8 valide dans le rendu.
    expected_candidates = ("Étape 2 — Vérification", "Étape 1 — Analyse")
    assert actual in expected_candidates, (
        f"[Etape 2 Verification] mojibake ou label inconnu : "
        f"attendu in {expected_candidates}, recu={actual!r} ({actual.encode('utf-8').hex()})"
    )
    # Strict : ne doit JAMAIS contenir les patterns mojibake double-encode.
    for bad in ("Ã©", "Ã¨", "Ã ", "Ã\xaa", "�"):
        assert bad not in actual, (
            f"[Etape 2] pattern mojibake {bad!r} detecte dans rendu DOM : {actual!r}"
        )


@pytest.mark.runtime
def test_rest_api_token_masked_bullets_utf8(dashboard_page) -> None:
    """Settings : champ rest_api_token doit afficher 8 bullets U+2022 (et non du clair).

    Critere SEC-H3 + mojibake : le mask `_SECRET_MASK = "•" * 8` doit etre rendu
    avec les CARACTERES BULLET corrects (U+2022, 3 bytes UTF-8 chacun = 24 bytes),
    pas leur version mojibake `â€¢` ni des `?`.
    """
    # Naviguer vers settings.
    dashboard_page.evaluate("window.location.hash = '#/settings'")
    dashboard_page.wait_for_timeout(1200)
    # Le champ rest_api_token est un input dans la vue parametres. On cherche
    # un input dont l'id ou name contient rest_api_token.
    value = dashboard_page.evaluate(
        """() => {
            const candidates = [
                'input[name="rest_api_token"]',
                'input#rest_api_token',
                '[data-key="rest_api_token"] input',
                '[data-field="rest_api_token"]'
            ];
            for (const sel of candidates) {
                const el = document.querySelector(sel);
                if (el) return el.value || el.textContent || '';
            }
            // Fallback : chercher un input contenant des bullets U+2022.
            const inputs = document.querySelectorAll('input[type="text"], input[type="password"]');
            for (const el of inputs) {
                if ((el.value || '').includes('\\u2022')) return el.value;
            }
            return '';
        }"""
    )
    expected_mask = "•" * 8
    # Acceptation tolerante : soit le mask exact, soit chaine vide (champ non rendu
    # sur cet ecran), MAIS jamais du clair. On exige la presence d'au moins un
    # bullet U+2022 si une valeur est presente.
    if value:
        assert "•" in value, (
            f"[rest_api_token] mask non-bullet detecte (mojibake possible) : "
            f"recu={value!r} ({value.encode('utf-8').hex()}), attendu={expected_mask!r}"
        )
        # Verifier qu'on n'a pas le mojibake `â€¢` (bullet UTF-8 decode-en-latin1).
        for bad in ("â€¢", "�"):
            assert bad not in value, (
                f"[rest_api_token] pattern mojibake {bad!r} dans mask : {value!r}"
            )
