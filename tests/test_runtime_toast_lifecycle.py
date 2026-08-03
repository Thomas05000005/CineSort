"""Test runtime - cycle de vie TOAST (absent -> present -> absent).

ETAPE 3 TESTS RUNTIME CYCLE DE VIE - Iteration 11 (loop/correction-2026-06).

Critere FAMILLE B = CYCLE DE VIE prouve multi-instants (absent -> present -> absent),
PAS un seul screenshot ni test mocke seul.

Sequence :
- GIVEN : page chargee, aucun toast visible (DOM check t=0).
- WHEN  : declencher action (showToast equivalent du save settings : type info).
- THEN  : toast visible avec texte attendu (DOM check + textContent).
- WHEN  : attendre la duree (plancher 1500ms + transition 220ms + grace).
- THEN  : toast disparu (DOM check post-expiration).

PART OBJECTIVE seule (DOM mesurable). La PART SUBJECTIVE (animation slide-in/out,
timing ressenti, esthetique) est RESERVEE validation humaine.

Acquis preserves : 5b3a62c (unmount cleanup NE PAS ROUVRIR) - aucun timer ajoute
dans ce test sans cleanup (showToast self-cleanup via setTimeout interne 220ms post-out).
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime toast lifecycle")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


_INJECT_TOAST_HELPER = """
() => {
  if (window.__toastLifecycle) return Promise.resolve(true);
  return import('/dashboard/components/toast.js').then((mod) => {
    window.__toastLifecycle = mod;
    return true;
  });
}
"""


def _ensure_toast_loaded(page) -> None:
    """Charge le module toast.js dynamiquement et l'expose sur window."""
    page.evaluate("window.location.hash = '#/accueil'")
    page.wait_for_timeout(300)
    page.evaluate(_INJECT_TOAST_HELPER)
    page.wait_for_function(
        "() => window.__toastLifecycle && typeof window.__toastLifecycle.showToast === 'function'",
        timeout=5000,
    )


@pytest.mark.runtime
def test_toast_save_settings_lifecycle_absent_present_absent(dashboard_page) -> None:
    """Toast save_settings: cycle complet absent -> present -> absent.

    Cas equivalent au feedback de sauvegarde des reglages (parametres.js:1785).
    On force duration=600ms ; le plancher Math.max(1500, duration) reste 1500ms.

    Sequence prouvee :
    - t=0      : aucun toast (#toast-container vide).
    - t=150ms  : 1 toast .toast--success present + textContent exact attendu.
    - t=5000ms : 0 toast (apres plancher 1500 + transition 220 + grace).
    """
    _ensure_toast_loaded(dashboard_page)

    # GIVEN : aucun toast initial.
    dashboard_page.evaluate("() => window.__toastLifecycle.clearAllToasts && window.__toastLifecycle.clearAllToasts()")
    dashboard_page.wait_for_timeout(150)

    initial_count = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert initial_count == 0, f"GIVEN: 0 toast initial attendu, vu {initial_count}"

    # WHEN : declencher l'action (equivalent save settings OK).
    dashboard_page.evaluate(
        """() => {
          window.__toastLifecycle.showToast({
            type: 'success',
            text: 'Réglages sauvegardés',
            duration: 600,
          });
        }"""
    )
    dashboard_page.wait_for_timeout(150)

    # THEN (PRESENT) : toast visible avec textContent attendu.
    present_snapshot = dashboard_page.evaluate(
        """() => {
          const nodes = document.querySelectorAll('#toast-container .toast');
          if (nodes.length === 0) return { count: 0, text: null, classes: null };
          const t = nodes[0].querySelector('.toast__text');
          return {
            count: nodes.length,
            text: t ? t.textContent : null,
            classes: nodes[0].className,
          };
        }"""
    )
    assert present_snapshot["count"] == 1, f"PRESENT: 1 toast attendu, vu {present_snapshot['count']}"
    assert present_snapshot["text"] == "Réglages sauvegardés", (
        f"PRESENT: textContent inattendu : {present_snapshot['text']!r}"
    )
    assert "toast--success" in (present_snapshot["classes"] or ""), (
        f"PRESENT: classe toast--success manquante : {present_snapshot['classes']}"
    )

    # WHEN : attendre disparition (plancher 1500 + transition 220 + grace 300).
    # NOTE: la consigne de mission decrit "attendre 5s" mais le toast par defaut
    # disparait avant. On reste defensif a 5000ms qui couvre largement.
    dashboard_page.wait_for_timeout(5000)

    # THEN (ABSENT) : toast disparu (cycle complet).
    after_count = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert after_count == 0, f"ABSENT: 0 toast attendu apres expiration, vu {after_count}"


@pytest.mark.runtime
def test_toast_error_lifecycle_long_duration_then_absent(dashboard_page) -> None:
    """Toast error: meme cycle pour un message d'echec save (item 4.1.3 carto).

    Garantit que le textContent FR exact-match est respecte pour les erreurs,
    et que le cycle absent->present->absent fonctionne avec duration courte.
    """
    _ensure_toast_loaded(dashboard_page)
    dashboard_page.evaluate("() => window.__toastLifecycle.clearAllToasts && window.__toastLifecycle.clearAllToasts()")
    dashboard_page.wait_for_timeout(150)

    # GIVEN : aucun toast initial.
    assert dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length") == 0

    # WHEN : emettre toast erreur (duration 600ms pour eviter d'attendre 10s).
    dashboard_page.evaluate(
        """() => window.__toastLifecycle.showToast({
            type: 'error',
            text: 'Echec de la sauvegarde des decisions.',
            duration: 600,
        })"""
    )
    dashboard_page.wait_for_timeout(150)

    snap = dashboard_page.evaluate(
        """() => {
          const node = document.querySelector('#toast-container .toast');
          if (!node) return { count: 0 };
          const text = node.querySelector('.toast__text');
          return {
            count: document.querySelectorAll('#toast-container .toast').length,
            hasError: node.classList.contains('toast--error'),
            text: text ? text.textContent : null,
          };
        }"""
    )
    assert snap["count"] == 1
    assert snap["hasError"] is True, "Classe toast--error attendue"
    assert snap["text"] == "Echec de la sauvegarde des decisions."

    # WHEN : attendre 5s.
    dashboard_page.wait_for_timeout(5000)

    # THEN : disparu.
    after = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert after == 0, f"Apres 5s : 0 toast attendu, vu {after}"
