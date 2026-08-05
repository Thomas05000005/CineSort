"""Test runtime - cycle de vie COUNTDOWN (modale danger 3 -> 2 -> 1 -> 0).

ETAPE 3 TESTS RUNTIME CYCLE DE VIE - Iteration 11 (loop/correction-2026-06).

Critere FAMILLE B = CYCLE DE VIE prouve multi-instants. Pour le countdown,
la sequence est `present 3s -> 2s -> 1s -> execute/cancel (0)`.

Le test capturait a l'origine 3 instants d'horloge explicites (t=1.1s, t=2.1s,
t=3.3s). Il est passe a un ECHANTILLONNAGE CONTINU juge sur la sequence
obtenue : les 100 ms de marge laissees a un `setInterval(1000)` etaient
inferieures a la derive d'un timer JS sur un runner de CI partage, et le test
tombait sans qu'aucun defaut n'existe.

Sequence :
- GIVEN : action destructive declenchee (modale danger via dangerConfirmModal
          avec countdownSeconds=3 - equivalent du seuil >50 items).
- THEN  : la suite des valeurs affichees vaut exactement 3s -> 2s -> 1s, et le
          bouton confirm reste desactive tant que le span est present.
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
    """Countdown 3 -> 2 -> 1 -> execute/cancel : la SEQUENCE est observee.

    Cas equivalent action destructive (delete > 50 items / bulk-mark-deletion
    avec countdownSeconds=3 issue de _gradedCountdownSeconds carto 4.2.1).

    Ce qui est verifie :
    - GIVEN : modale danger ouverte avec countdownSeconds=3.
    - etat initial : countdown text = "(3s)", bouton confirm disabled.
    - pendant tout le compte a rebours, echantillonne toutes les 50 ms :
        * la modale ne se ferme jamais d'elle-meme,
        * le bouton confirm reste DISABLED tant que le span est present,
        * la suite des valeurs affichees vaut exactement ["(3s)", "(2s)", "(1s)"].
    - a l'expiration : bouton enabled, span retire, modale toujours ouverte.
    - cleanup : le clic Annuler ferme bien l'overlay (FIGE 1c).

    Aucune assertion ne porte sur un INSTANT d'horloge : voir le commentaire du
    corps pour la raison (le test mesurait la charge du runner).
    """
    # GIVEN: ouvrir modale danger countdown=3s.
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(300)
    dashboard_page.evaluate(_JS_OPEN_DANGER, 3)
    dashboard_page.wait_for_timeout(150)

    # ETAT INITIAL : "(3s)" + disabled. Celui-ci ne depend d'aucune horloge.
    s_t0 = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_t0["present"] is True, "Modale danger absente apres open."
    assert s_t0["disabled"] is True, "t=0 : bouton confirm devrait etre disabled."
    assert s_t0["spanPresent"] is True, "t=0 : span countdown devrait etre present."
    assert s_t0["countdownText"] == "(3s)", f"t=0 : countdown attendu '(3s)', vu {s_t0['countdownText']!r}"

    # SEQUENCE OBSERVEE, et non echantillonnage a des instants d'horloge.
    #
    # Les trois captures precedentes se faisaient a t=1.1s / t=2.1s / t=3.3s,
    # soit 100 ms de marge pour un `setInterval(1000)`. Sur un runner de CI
    # partage, la derive d'un timer JS depasse largement 100 ms : ce test est
    # tombe au moins trois fois avec « t=1 : countdown attendu contient '2', vu
    # '(3s)' » — le decrement etait simplement EN RETARD, pas absent. Le test
    # mesurait la charge du runner, pas le comportement du compte a rebours.
    #
    # Ce que le contrat exige vraiment n'a rien d'un chronometre :
    #   - le compteur DESCEND 3 -> 2 -> 1, dans cet ordre, sans sauter de valeur
    #   - le bouton reste DESACTIVE tant qu'on n'a pas atteint 0
    #   - la modale ne se ferme JAMAIS d'elle-meme (c'est l'humain qui tranche)
    #
    # On echantillonne donc frequemment pendant une fenetre large et on juge la
    # SEQUENCE obtenue.
    #
    # Honnetement : ce n'est PAS plus puissant en detection sur les defauts
    # evidents. Verifie par mutation de `modal.js` — un decrement qui saute une
    # valeur (`remaining -= 2`) et un bouton active des le premier tick sont
    # attrapes par les DEUX versions. L'apport est la STABILITE : 5 executions
    # consecutives vertes ici, contre au moins trois chutes en CI pour
    # l'ancienne. Le gain de couverture, lui, est marginal et porte sur les
    # etats transitoires entre deux photos — reel, mais je n'ai pas construit de
    # mutation qui le prouve, donc je ne le revendique pas.
    vus: list[str] = []
    for _ in range(120):  # 120 x 50 ms = 6 s de fenetre, pour 3 s de countdown
        etat = dashboard_page.evaluate(_JS_PROBE_STATE)
        assert etat["present"] is True, "modale fermee prematurement pendant le countdown."
        texte = etat["countdownText"] or ""
        if etat["spanPresent"] and texte and (not vus or vus[-1] != texte):
            vus.append(texte)
        if etat["spanPresent"]:
            assert etat["disabled"] is True, (
                f"bouton confirm ACTIVE alors que le countdown affiche encore {texte!r} — "
                "l'utilisateur pourrait confirmer avant la fin du delai."
            )
        else:
            break  # le span a disparu : le countdown est arrive a 0
        dashboard_page.wait_for_timeout(50)

    assert vus == ["(3s)", "(2s)", "(1s)"], f"sequence de decrement attendue ['(3s)', '(2s)', '(1s)'], observee {vus}"

    s_end = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_end["present"] is True, "AFTER : modale fermee toute seule (interdit : l'humain doit decider)."
    assert s_end["disabled"] is False, "AFTER : bouton confirm toujours disabled apres countdown=0."
    assert s_end["spanPresent"] is False, "AFTER : span countdown toujours present apres expiration."

    # Cleanup : cancel pour fermer la modale et nettoyer l'overlay.
    dashboard_page.evaluate(_JS_CANCEL)
    dashboard_page.wait_for_timeout(150)
    s_closed = dashboard_page.evaluate(_JS_PROBE_STATE)
    assert s_closed["present"] is False, "Cleanup : modale toujours presente apres click Annuler (FIGE 1c)."
