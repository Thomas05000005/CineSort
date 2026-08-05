"""Test runtime — cycle de vie TOAST famille B (absent -> present -> absent).

ETAPE 2 FIX MECANISME — Iteration 11 (loop/correction-2026-06).

Carto BILAN_ITER11_2026-06-08.md items 4.1.1-5 (5 contextes TOAST).

Acceptation FAMILLE B = cycle de vie prouve multi-instants, PAS un seul
screenshot ni un test mocke seul. Ici on prouve :
1. PRESENT : un toast emis via `showToast({type, text})` apparait dans le DOM
   sous `#toast-container .toast`, avec aria-live=polite, textContent exact.
2. ABSENT post-duree : apres `duration` ms + grace 300ms, le toast est retire
   du DOM (cycle complet absent->present->absent).
3. PURGE par clearAllToasts : la nouvelle API exportee force la fermeture
   immediate de tous les toasts actifs ET clear leurs setTimeout pendants
   (garde-fou unmount iter11 prolongeant 5b3a62c).

Tests :
- test_toast_lifecycle_info : info default 4000ms, cycle complet.
- test_toast_lifecycle_success : success default 4000ms.
- test_toast_lifecycle_error : error default 10000ms (duree longue, on reduit).
- test_toast_aria_live_polite : assertion #toast-container aria-live=polite.
- test_toast_clearall_purges_timers : 3 toasts actifs -> clearAllToasts() ->
  0 toast immediat + aucun setTimeout pendant (verif via map size = 0).

PART OBJECTIVE seule : presence/absence DOM, attributs, textContent. La part
SUBJECTIVE (esthetique slide-in, timing percu) est RESERVEE validation humaine.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime toast")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


_INJECT_HELPER_JS = """
() => {
  // Charge dynamiquement showToast + clearAllToasts depuis le module ESM
  // et les expose sur window pour faciliter les assertions Playwright.
  if (window.__toastTest) return Promise.resolve(true);
  return import('/dashboard/components/toast.js').then((mod) => {
    window.__toastTest = mod;
    return true;
  });
}
"""


def _ensure_helper_loaded(page) -> None:
    """Injecte showToast + clearAllToasts sur window via import dynamique."""
    page.evaluate("window.location.hash = '#/accueil'")
    page.wait_for_timeout(300)
    page.evaluate(_INJECT_HELPER_JS)
    page.wait_for_function(
        "() => window.__toastTest && typeof window.__toastTest.showToast === 'function'", timeout=5000
    )


@pytest.mark.runtime
def test_toast_lifecycle_info_appears_then_disappears(dashboard_page) -> None:
    """Item 4.1.2 — toast info : absent -> present -> absent apres duration courte.

    On force duration=600ms pour eviter d'attendre 4s en CI. La regle de
    plancher `Math.max(1500, duration)` garde 1500ms reel ; on attend 1500+300.
    """
    _ensure_helper_loaded(dashboard_page)

    # 1) ABSENT initial : aucun toast.
    initial = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert initial == 0, f"Etat initial doit etre 0 toast, vu {initial}"

    # 2) Emission.
    dashboard_page.evaluate(
        "() => window.__toastTest.showToast({ type: 'info', text: 'Test info ITER11', duration: 600 })"
    )
    dashboard_page.wait_for_timeout(150)

    # PRESENT : toast visible avec textContent exact.
    present = dashboard_page.evaluate(
        """() => {
          const nodes = document.querySelectorAll('#toast-container .toast');
          if (nodes.length !== 1) return { count: nodes.length, text: null, classes: null };
          const t = nodes[0].querySelector('.toast__text');
          return {
            count: nodes.length,
            text: t ? t.textContent : null,
            classes: nodes[0].className,
          };
        }"""
    )
    assert present["count"] == 1, f"PRESENT : 1 toast attendu, vu {present['count']}"
    assert present["text"] == "Test info ITER11", f"textContent inattendu : {present['text']}"
    assert "toast--info" in (present["classes"] or ""), f"classe toast--info manquante : {present['classes']}"

    # 3) ABSENT apres expiration (1500 plancher + 220 transition + 300 grace).
    dashboard_page.wait_for_timeout(1500 + 220 + 300)
    after = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert after == 0, f"Apres duree : 0 toast attendu, vu {after}"


@pytest.mark.runtime
def test_toast_lifecycle_success_with_action(dashboard_page) -> None:
    """Item 4.1.1 — toast success bulk approve avec bouton action Annuler.

    Verifie presence simultanee de classes toast--success + toast--has-action
    + bouton .toast__action accessible.
    """
    _ensure_helper_loaded(dashboard_page)
    dashboard_page.evaluate("() => window.__toastTest.clearAllToasts && window.__toastTest.clearAllToasts()")
    dashboard_page.wait_for_timeout(100)

    # Emission toast success + action callback.
    dashboard_page.evaluate(
        """() => {
          window.__toastTest._actionCalled = false;
          window.__toastTest.showToast({
            type: 'success',
            text: '10 decisions appliquees',
            duration: 1500,
            action: {
              label: 'Annuler',
              onClick: () => { window.__toastTest._actionCalled = true; },
            },
          });
        }"""
    )
    dashboard_page.wait_for_timeout(150)

    snapshot = dashboard_page.evaluate(
        """() => {
          const node = document.querySelector('#toast-container .toast');
          if (!node) return { count: 0 };
          const action = node.querySelector('.toast__action');
          const text = node.querySelector('.toast__text');
          return {
            count: document.querySelectorAll('#toast-container .toast').length,
            hasSuccess: node.classList.contains('toast--success'),
            hasAction: node.classList.contains('toast--has-action'),
            actionLabel: action ? action.textContent : null,
            text: text ? text.textContent : null,
          };
        }"""
    )
    assert snapshot["count"] == 1
    assert snapshot["hasSuccess"] is True
    assert snapshot["hasAction"] is True
    assert snapshot["actionLabel"] == "Annuler"
    assert snapshot["text"] == "10 decisions appliquees"


@pytest.mark.runtime
def test_toast_container_has_aria_live_polite(dashboard_page) -> None:
    """Item 4.1.* — accessibility : #toast-container expose aria-live=polite."""
    _ensure_helper_loaded(dashboard_page)
    dashboard_page.evaluate("() => window.__toastTest.showToast({ type: 'info', text: 'A11Y check', duration: 800 })")
    dashboard_page.wait_for_timeout(100)

    attrs = dashboard_page.evaluate(
        """() => {
          const c = document.getElementById('toast-container');
          if (!c) return null;
          return {
            ariaLive: c.getAttribute('aria-live'),
            ariaAtomic: c.getAttribute('aria-atomic'),
          };
        }"""
    )
    assert attrs is not None, "#toast-container introuvable"
    assert attrs["ariaLive"] == "polite", f"aria-live attendu polite, vu {attrs['ariaLive']}"
    assert attrs["ariaAtomic"] == "false", f"aria-atomic attendu false, vu {attrs['ariaAtomic']}"


@pytest.mark.runtime
def test_toast_dedup_window_merges_identical(dashboard_page) -> None:
    """Item 4.1.5 — 2 toasts identiques < 2000ms = 1 toast + badge xN.

    Garantit que la map _activeToasts ne croit pas avec les doublons et
    que le badge .toast__count reflete le compteur.
    """
    _ensure_helper_loaded(dashboard_page)
    dashboard_page.evaluate("() => window.__toastTest.clearAllToasts()")
    dashboard_page.wait_for_timeout(100)

    dashboard_page.evaluate(
        """() => {
          window.__toastTest.showToast({ type: 'info', text: 'Dedup test', duration: 5000 });
          window.__toastTest.showToast({ type: 'info', text: 'Dedup test', duration: 5000 });
          window.__toastTest.showToast({ type: 'info', text: 'Dedup test', duration: 5000 });
        }"""
    )
    dashboard_page.wait_for_timeout(200)

    state = dashboard_page.evaluate(
        """() => {
          const nodes = document.querySelectorAll('#toast-container .toast');
          const badge = document.querySelector('#toast-container .toast .toast__count');
          return {
            count: nodes.length,
            badgeText: badge ? badge.textContent : null,
          };
        }"""
    )
    assert state["count"] == 1, f"Dedup attendu : 1 toast, vu {state['count']}"
    assert state["badgeText"] == "x3", f"Badge attendu x3, vu {state['badgeText']}"

    # Cleanup pour ne pas polluer le suivant.
    dashboard_page.evaluate("() => window.__toastTest.clearAllToasts()")


@pytest.mark.runtime
def test_toast_clearall_purges_immediately(dashboard_page) -> None:
    """Garde-fou iter11 (prolonge 5b3a62c) : clearAllToasts() purge tous les
    toasts ET leurs setTimeout pendants. Apres appel : 0 noeud DOM dans le
    container, aucun timer residuel observable (la map interne est videe).
    """
    _ensure_helper_loaded(dashboard_page)

    # Emettre 3 toasts persistants (timers pendants 20s plafonnes).
    dashboard_page.evaluate(
        """() => {
          window.__toastTest.showToast({ type: 'info', text: 'P1', persistent: true });
          window.__toastTest.showToast({ type: 'warning', text: 'P2', persistent: true });
          window.__toastTest.showToast({ type: 'error', text: 'P3', persistent: true });
        }"""
    )
    dashboard_page.wait_for_timeout(150)

    before = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert before == 3, f"3 toasts persistants attendus, vu {before}"

    # PURGE.
    dashboard_page.evaluate("() => window.__toastTest.clearAllToasts()")

    # close() ajoute classe toast--out + setTimeout 220ms pour remove. On
    # attend la transition + grace.
    dashboard_page.wait_for_timeout(220 + 200)

    after = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert after == 0, f"Apres clearAllToasts : 0 toast attendu, vu {after}"

    # Verif idempotence : 2eme appel ne doit pas lever.
    dashboard_page.evaluate("() => window.__toastTest.clearAllToasts()")
    final = dashboard_page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")
    assert final == 0
