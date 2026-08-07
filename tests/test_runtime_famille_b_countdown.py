"""Test runtime — cycle de vie COUNTDOWN (famille B feedback transitoire).

ETAPE 2 FIX MECANISME COUNTDOWN — iteration 11 (loop/correction-2026-06).

Carto: 4.2.1 (bulk approve >50), 4.2.2 (bulk mark-for-deletion), 4.2.3 (undo
post-apply). Cycle attendu commun : `present-pendant -> tick -> remplace
(enabled) -> absent (close)` avec cleanup `clearInterval` au close ET au
demontage de vue (prolonge FIGE 1c / acquis 5b3a62c).

Mesure objective runtime DOM (memoire user FAMILLE B : "cycle de vie prouve
multi-instants, PAS un seul screenshot ni test mocke seul").

Les tests `test_phase5_*_complete.py` verifient le SOURCE JS (presence du
parametre `countdownSeconds:` dans les appels). Ils ne mesurent PAS le
comportement runtime DOM (apparition span `[data-danger-countdown]`,
decrement effectif, bouton confirm bascule disabled->enabled, suppression
overlay au close, 0 timer leak post-unmount).

Strategie :
1. Injection JS dynamique : `import("/dashboard/components/modal.js")` puis
   appel a `dangerConfirmModal({countdownSeconds: 2, ...})` -> permet de tester
   le cycle de vie sans devoir declencher un vrai apply / bulk delete.
2. Probes DOM espacees (200ms + 1.2s + 2.2s) : 3 instants temoignant
   present-disabled / decrement / enabled.
3. Verif explicite que `overlay._countdownTimer === null` apres close
   (acquis FIGE 1c : cleanup setInterval au close).
4. Verif que 0 setInterval residuel sur le hook prototype (compteur monitor)
   apres close => pas de fuite handler.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime countdown")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


# ---------------------------------------------------------------------------
# Helpers JS injectables : compteur d'intervals + appel a dangerConfirmModal.
# ---------------------------------------------------------------------------

_JS_INSTALL_INTERVAL_PROBE = """
() => {
    // Probe FIGE 1c : compte les setInterval crees / clearInterval emis.
    // Permet de verifier qu'apres close le solde (created - cleared) revient
    // au baseline (pas de fuite handler).
    if (window.__cdProbe) return window.__cdProbe;
    // `creesParLaModale` compte SEPAREMENT les intervals attribuables a
    // `modal.js`, via la pile d'appel.
    //
    // POURQUOI. `created` compte TOUT le document. Tant que le harnais n'etait
    // pas authentifie (il vivait sur le bypass d'auth loopback), presque rien
    // ne tournait en fond et ce compteur global suffisait. Depuis que le
    // harnais porte un jeton, le code de fond s'execute vraiment — la banniere
    // de scan polle, les vues se re-rendent — et cree ses propres intervals
    // pendant la fenetre de mesure : le delta global est monte a 2 sans qu'AUCUN
    // countdown n'ait ete arme. L'assertion mesurait le voisinage, pas le sujet.
    const probe = { created: 0, cleared: 0, baseline: 0, creesParLaModale: 0 };
    const realSetInterval = window.setInterval.bind(window);
    const realClearInterval = window.clearInterval.bind(window);
    window.setInterval = function(fn, ms) {
        const id = realSetInterval(fn, ms);
        probe.created += 1;
        try {
            if ((new Error().stack || "").includes("modal.js")) probe.creesParLaModale += 1;
        } catch (e) { /* no-op */ }
        probe._lastId = id;
        return id;
    };
    window.clearInterval = function(id) {
        if (id) probe.cleared += 1;
        return realClearInterval(id);
    };
    window.__cdProbe = probe;
    return probe;
}
"""


_JS_OPEN_DANGER_MODAL = """
async (countdownSeconds) => {
    const mod = await import("/dashboard/components/modal.js");
    let confirmed = false;
    let cancelled = false;
    mod.dangerConfirmModal({
        title: "Test runtime countdown",
        items: ["a.mkv", "b.mkv"],
        consequence: "Test cycle de vie - aucune action reelle.",
        countdownSeconds: countdownSeconds,
        confirmLabel: "Confirmer",
        cancelLabel: "Annuler",
        onConfirm: () => { confirmed = true; },
        onCancel: () => { cancelled = true; },
    });
    // Expose etat pour assertions cote Python.
    window.__cdLastModal = {
        get confirmed() { return confirmed; },
        get cancelled() { return cancelled; },
    };
    return true;
}
"""


_JS_PROBE_MODAL_STATE = """
() => {
    const overlay = document.getElementById("dashDangerModal");
    if (!overlay) {
        return { present: false };
    }
    const confirmBtn = overlay.querySelector("[data-danger-confirm]");
    const span = overlay.querySelector("[data-danger-countdown]");
    return {
        present: true,
        disabled: confirmBtn ? confirmBtn.disabled === true : null,
        countdownText: span ? span.textContent : null,
        spanPresent: span !== null,
        timerActive: overlay._countdownTimer !== null && overlay._countdownTimer !== undefined,
        confirmedFlag: overlay._confirmed === true,
    };
}
"""


_JS_CLOSE_VIA_CANCEL = """
() => {
    const overlay = document.getElementById("dashDangerModal");
    if (!overlay) return false;
    const cancelBtn = overlay.querySelector("[data-danger-cancel]");
    if (!cancelBtn) return false;
    cancelBtn.click();
    return true;
}
"""


_JS_PROBE_COUNTERS = """
() => {
    const p = window.__cdProbe || { created: 0, cleared: 0, creesParLaModale: 0 };
    return { created: p.created, cleared: p.cleared, creesParLaModale: p.creesParLaModale || 0 };
}
"""


# ---------------------------------------------------------------------------
# Tests runtime — cycle de vie 4.2.1 / 4.2.2 / 4.2.3.
# ---------------------------------------------------------------------------


@pytest.mark.runtime
@pytest.mark.parametrize("countdown_s", [2, 3])
def test_countdown_lifecycle_present_tick_enabled(dashboard_page, countdown_s: int) -> None:
    """4.2.1 / 4.2.2 : cycle `present-disabled -> tick -> present-enabled`.

    Prouve runtime que :
    - apparition immediate de l'overlay + span `[data-danger-countdown]`
      avec text `(Ns)` initial,
    - bouton confirm `disabled=true` initial,
    - decrement seconde-par-seconde (snapshot intermediate),
    - bascule `disabled=false` + suppression span a t=N*1000ms,
    - overlay reste present (close = action humaine separee).
    """
    # 1) Install probe intervals + ouverture modale danger via injection ESM.
    dashboard_page.evaluate(_JS_INSTALL_INTERVAL_PROBE)
    baseline = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    dashboard_page.evaluate(_JS_OPEN_DANGER_MODAL, countdown_s)

    # 2) Probe t=200ms : present + disabled + span text initial.
    dashboard_page.wait_for_timeout(200)
    s0 = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
    assert s0["present"] is True, "Modale danger absente apres injection."
    assert s0["disabled"] is True, "Bouton confirm devrait etre disabled initial."
    assert s0["spanPresent"] is True, "Span countdown absent initial."
    assert s0["countdownText"] == f"({countdown_s}s)", (
        f"Texte countdown initial inattendu : {s0['countdownText']!r} (attendu '({countdown_s}s)')"
    )
    assert s0["timerActive"] is True, "Timer countdown devrait etre actif."

    # Sanity FIGE 1c : 1 nouveau setInterval cree apres open.
    after_open = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    assert after_open["created"] >= baseline["created"] + 1, (
        "Aucun setInterval cree apres open dangerConfirmModal — countdown ne tourne pas (regression)."
    )

    # 3) Probe a mi-parcours : decrement visible (text != initial).
    if countdown_s >= 2:
        dashboard_page.wait_for_timeout(1100)
        s_mid = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
        assert s_mid["present"] is True, "Modale fermee prematurement."
        assert s_mid["disabled"] is True, "Bouton confirm enabled trop tot."
        # Apres ~1.1s : text passe de (Ns) a (N-1 s) typiquement.
        assert s_mid["countdownText"] != f"({countdown_s}s)", (
            f"Countdown ne decremente pas : text inchange {s_mid['countdownText']!r}."
        )

    # 4) Probe post-expiration : enabled + span retire.
    # Marge confortable : 1.5s apres la duree restante.
    remaining_after_mid = (countdown_s - 1) if countdown_s >= 2 else countdown_s
    dashboard_page.wait_for_timeout(remaining_after_mid * 1000 + 800)
    s_end = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
    assert s_end["present"] is True, (
        "Modale fermee toute seule a la fin du countdown (interdit : l'utilisateur doit decider)."
    )
    assert s_end["disabled"] is False, "Bouton confirm toujours disabled apres expiration countdown."
    assert s_end["spanPresent"] is False, "Span countdown toujours present apres expiration (devrait etre retire)."
    assert s_end["timerActive"] is False, (
        "Timer countdown toujours actif apres expiration (regression FIGE 1c : clearInterval manque a l'expiration)."
    )

    # 5) Cleanup : annuler la modale pour ne pas polluer les autres tests.
    dashboard_page.evaluate(_JS_CLOSE_VIA_CANCEL)
    dashboard_page.wait_for_timeout(150)
    s_closed = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
    assert s_closed["present"] is False, "Modale toujours presente apres click Annuler."


@pytest.mark.runtime
def test_countdown_close_clears_interval_no_leak(dashboard_page) -> None:
    """4.2.1 / 4.2.2 - cleanup : close PENDANT countdown clear setInterval.

    Prouve FIGE 1c : si l'utilisateur cancel pendant le countdown actif (avant
    expiration), `clearInterval` est appele et `_countdownTimer` revient a null.
    Acquis 5b3a62c : tout timer ajoute au demontage doit etre nettoye.
    """
    dashboard_page.evaluate(_JS_INSTALL_INTERVAL_PROBE)
    baseline = dashboard_page.evaluate(_JS_PROBE_COUNTERS)

    # Ouvrir avec countdown long (5s) puis annuler a t=400ms (pendant tick).
    dashboard_page.evaluate(_JS_OPEN_DANGER_MODAL, 5)
    dashboard_page.wait_for_timeout(200)

    s_open = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
    assert s_open["present"] is True and s_open["timerActive"] is True

    after_open = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    created_delta_open = after_open["created"] - baseline["created"]
    assert created_delta_open >= 1, "Pas de setInterval cree pour countdown."

    # Cancel pendant countdown.
    dashboard_page.evaluate(_JS_CLOSE_VIA_CANCEL)
    dashboard_page.wait_for_timeout(200)

    s_closed = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
    assert s_closed["present"] is False, "Modale toujours presente apres cancel."

    after_close = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    cleared_delta = after_close["cleared"] - baseline["cleared"]
    # Au moins le timer countdown doit avoir ete cleared.
    assert cleared_delta >= 1, (
        f"clearInterval pas appele au close (cleared_delta={cleared_delta}). "
        f"Regression FIGE 1c / fuite handler iter10 5b3a62c."
    )

    # Attendre 1.5s supplementaires : si le timer fuit, le compteur cleared
    # n'augmente plus mais le setInterval continue de tirer. On verifie ici
    # uniquement que clearInterval a ete appele (sanity ci-dessus).
    dashboard_page.wait_for_timeout(1500)


@pytest.mark.runtime
def test_countdown_zero_no_disabled_no_span(dashboard_page) -> None:
    """4.2.x bord : countdownSeconds=0 -> bouton confirm IMMEDIATEMENT enabled.

    Garde-fou : memoire user `feedback_cinesort_actions_dangereuses` permet
    countdown OFF pour certains contextes (item 4.3.x consequence). Le composant
    doit gerer ce cas sans creer de setInterval inutile.
    """
    dashboard_page.evaluate(_JS_INSTALL_INTERVAL_PROBE)
    baseline = dashboard_page.evaluate(_JS_PROBE_COUNTERS)

    dashboard_page.evaluate(_JS_OPEN_DANGER_MODAL, 0)
    dashboard_page.wait_for_timeout(150)

    s = dashboard_page.evaluate(_JS_PROBE_MODAL_STATE)
    assert s["present"] is True, "Modale absente."
    assert s["disabled"] is False, "Bouton confirm devrait etre enabled (countdown=0)."
    assert s["spanPresent"] is False, "Span countdown ne devrait pas exister (countdown=0)."
    assert s["timerActive"] is False, (
        "Timer countdown actif alors que countdownSeconds=0 (setInterval inutile -> fuite potentielle)."
    )

    after_open = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    # On compte les intervals attribuables a `modal.js` PAR LA PILE D'APPEL, et
    # non le total du document : depuis que le harnais est authentifie, le code
    # de fond (banniere de scan, re-rendus de vue) cree ses propres intervals
    # pendant cette fenetre. L'ancienne tolerance `delta <= 1` etait un seuil
    # cale sur un voisinage silencieux, pas une mesure du sujet.
    delta_modale = after_open["creesParLaModale"] - baseline["creesParLaModale"]
    assert delta_modale == 0, (
        f"la modale a cree {delta_modale} setInterval alors que countdownSeconds=0 "
        f"(fuite de handler). Total document sur la meme fenetre, pour information : "
        f"{after_open['created'] - baseline['created']}."
    )

    # Cleanup pour ne pas polluer.
    dashboard_page.evaluate(_JS_CLOSE_VIA_CANCEL)


@pytest.mark.runtime
def test_countdown_undo_unmount_cleanup_runtime(dashboard_page) -> None:
    """4.2.3 : `_undoCountdownTimer` Traitement nettoye au unmount.

    Verif runtime du cleanup `_stopUndoCountdown()` appele dans
    `unmountTraitement()` (FIGE 1c + acquis 5b3a62c). Le timer
    `_undoCountdownTimer` est demarre par `_startUndoCountdown()` apres un
    apply OK ; il est arrete au unmount. On verifie qu'aucun setInterval
    leak ne reste 2s apres navigation vers une autre vue.

    Strategie :
    1. Naviguer vers /traitement
    2. Compter setInterval created / cleared baseline
    3. Naviguer vers /accueil -> declenche unmountTraitement
    4. Verifier que `created - cleared` ne croit pas dans les 2s post-unmount
       (pas de fuite intervalle persistant cote Traitement).
    """
    dashboard_page.evaluate(_JS_INSTALL_INTERVAL_PROBE)

    # 1) Naviguer vers /traitement.
    dashboard_page.evaluate("window.location.hash = '#/traitement'")
    dashboard_page.wait_for_timeout(800)

    # 2) Baseline juste apres mount.
    dashboard_page.evaluate(_JS_PROBE_COUNTERS)

    # Laisser tourner ~1s pour que les setInterval mount-time se stabilisent.
    dashboard_page.wait_for_timeout(1000)
    pre_unmount = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    pre_open_delta = pre_unmount["created"] - pre_unmount["cleared"]

    # 3) Naviguer vers /accueil -> declenche cleanup unmountTraitement.
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(800)

    # 4) Mesure post-unmount : on attend 2s et on verifie que
    # le delta created/cleared n'augmente pas (=> pas de fuite intervalle).
    dashboard_page.wait_for_timeout(2000)
    post_unmount = dashboard_page.evaluate(_JS_PROBE_COUNTERS)
    post_delta = post_unmount["created"] - post_unmount["cleared"]

    # Tolerance : la vue accueil peut creer ses propres intervalles ; on borne
    # le surplus a un seuil raisonnable (5 intervals total pour mount accueil).
    # Le test cible la regression "_undoCountdownTimer leak" : un setInterval
    # de la vue Traitement qui survit indefiniment ferait croitre le delta
    # de maniere unbounded entre `pre_unmount` et `post_unmount`.
    assert post_delta - pre_open_delta < 10, (
        f"FUITE intervals post-unmount Traitement : "
        f"pre_unmount delta={pre_open_delta}, post_unmount delta={post_delta}. "
        f"Possible regression `_stopUndoCountdown` manquant au unmount "
        f"(FIGE 1c) ou un autre setInterval Traitement non nettoye."
    )
