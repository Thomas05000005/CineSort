"""Test runtime - cycle de vie COUNTDOWN (modale danger 3 -> 2 -> 1 -> 0).

ETAPE 3 TESTS RUNTIME CYCLE DE VIE - Iteration 11 (loop/correction-2026-06).

Critere FAMILLE B = CYCLE DE VIE prouve multi-instants. Pour le countdown,
la sequence est `present 3s -> 2s -> 1s -> execute/cancel (0)`. Le test
capture 3 instants explicites (t=0, t=1, t=2) pour prouver le decrement
seconde-par-seconde, conformement a la specification mission.

Sequence :
- GIVEN : action destructive declenchee (modale danger via dangerConfirmModal
          avec countdownSeconds=3 - equivalent du seuil >50 items).
- THEN  : countdown visible 3 -> 2 -> 1 (3 instants captures t=0, t=1, t=2).
- AFTER : execute (bouton enable) ou cancel atteint 0.

NOTE : ce test est complementaire de test_runtime_famille_b_countdown.py qui
couvre les variantes (countdown=2, =5 cancel, =0 immediat, unmount cleanup).
Ici on cible specifiquement la sequence 3->2->1 demandee dans la mission.

Acquis preserves : FIGE 1c (clearInterval au close) prolonge, 5b3a62c (timers
demontage), aucune modification de modal.js.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime countdown lifecycle")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


_JS_OPEN_DANGER = """
async (countdownSeconds) => {
    const mod = await import("/dashboard/components/modal.js");
    mod.dangerConfirmModal({
        title: "Test runtime countdown 3->2->1",
        items: ["a.mkv", "b.mkv", "c.mkv"],
        consequence: "Equivalent action destructive >50 items.",
        countdownSeconds: countdownSeconds,
        confirmLabel: "Confirmer la suppression",
        cancelLabel: "Annuler",
        onConfirm: () => { window.__cdConfirmed = true; },
        onCancel: () => { window.__cdCancelled = true; },
    });
    window.__cdConfirmed = false;
    window.__cdCancelled = false;
    return true;
}
"""


_JS_PROBE_STATE = """
() => {
    const overlay = document.getElementById("dashDangerModal");
    if (!overlay) return { present: false };
    const confirmBtn = overlay.querySelector("[data-danger-confirm]");
    const span = overlay.querySelector("[data-danger-countdown]");
    return {
        present: true,
        disabled: confirmBtn ? confirmBtn.disabled === true : null,
        countdownText: span ? span.textContent : null,
        spanPresent: span !== null,
    };
}
"""


_JS_CANCEL = """
() => {
    const overlay = document.getElementById("dashDangerModal");
    if (!overlay) return false;
    const btn = overlay.querySelector("[data-danger-cancel]");
    if (!btn) return false;
    btn.click();
    return true;
}
"""


@pytest.mark.runtime
def test_countdown_3_2_1_lifecycle_three_instants(dashboard_page) -> None:
    """Countdown 3 -> 2 -> 1 -> execute/cancel : 3 instants captures.

    Cas equivalent action destructive (delete > 50 items / bulk-mark-deletion
    avec countdownSeconds=3 issue de _gradedCountdownSeconds carto 4.2.1).

    Sequence :
    - GIVEN  : modale danger ouverte avec countdownSeconds=3.
    - t=0    : countdown text = "(3s)", bouton confirm disabled.
    - t=1.1s : countdown text contient "2" (decrement 3 -> 2), disabled.
    - t=2.1s : countdown text contient "1" (decrement 2 -> 1), disabled.
    - t=3.3s : countdown atteint 0, bouton confirm enabled, span retire.
    """
    # GIVEN: ouvrir modale danger countdown=3s.
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(300)
    dashboard_page.evaluate(_JS_OPEN_DANGER, 3)
    dashboard_page.wait_for_timeout(150)

    # INSTANT t=0 (juste apres open) : "(3s)" + disabled.
    s_t0 = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_t0["present"] is True, "Modale danger absente apres open."
    assert s_t0["disabled"] is True, "t=0 : bouton confirm devrait etre disabled."
    assert s_t0["spanPresent"] is True, "t=0 : span countdown devrait etre present."
    assert s_t0["countdownText"] == "(3s)", f"t=0 : countdown attendu '(3s)', vu {s_t0['countdownText']!r}"

    # INSTANT t=1.1s : decrement vers "(2s)".
    dashboard_page.wait_for_timeout(1100)
    s_t1 = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_t1["present"] is True, "t=1 : modale fermee prematurement."
    assert s_t1["disabled"] is True, "t=1 : bouton confirm enabled trop tot."
    assert s_t1["spanPresent"] is True, "t=1 : span countdown disparu trop tot."
    assert "2" in (s_t1["countdownText"] or ""), f"t=1 : countdown attendu contient '2', vu {s_t1['countdownText']!r}"

    # INSTANT t=2.1s : decrement vers "(1s)".
    dashboard_page.wait_for_timeout(1000)
    s_t2 = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_t2["present"] is True, "t=2 : modale fermee prematurement."
    assert s_t2["disabled"] is True, "t=2 : bouton confirm enabled trop tot."
    assert s_t2["spanPresent"] is True, "t=2 : span countdown disparu trop tot."
    assert "1" in (s_t2["countdownText"] or ""), f"t=2 : countdown attendu contient '1', vu {s_t2['countdownText']!r}"

    # AFTER t=3.3s : countdown atteint 0, bouton enabled, span retire.
    dashboard_page.wait_for_timeout(1200)
    s_end = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_end["present"] is True, "AFTER : modale fermee toute seule (interdit : l'humain doit decider)."
    assert s_end["disabled"] is False, "AFTER : bouton confirm toujours disabled apres countdown=0."
    assert s_end["spanPresent"] is False, "AFTER : span countdown toujours present apres expiration."

    # Cleanup : cancel pour fermer la modale et nettoyer l'overlay.
    dashboard_page.evaluate(_JS_CANCEL)
    dashboard_page.wait_for_timeout(150)
    s_closed = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_closed["present"] is False, "Cleanup : modale toujours presente apres click Annuler (FIGE 1c)."
