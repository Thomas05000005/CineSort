"""Cycle de vie du drain timer de NotifyService (issues #543 et #616).

Les trois etats du cycle sont couverts, chacun par un test qui isole UNE garde :

1. `test_shutdown_pendant_replanification_ne_laisse_pas_de_timer_zombi`
   -> la garde de SORTIE de `_drain_tick` : l'etat d'arret est lu et le prochain
   timer publie dans la MEME section critique. Sans cette atomicite, shutdown()
   annule l'ancien timer pendant que le tick en publie un nouveau : le nouveau
   survit et refire APRES le teardown (#616, et le timer orphelin de #543).

2. `test_tick_deja_dispatche_ne_livre_rien_apres_shutdown`
   -> la garde d'ENTREE de `_drain_tick` : `threading.Timer.run()` appelle la
   callback puis seulement apres on peut la canceller ; une fois la callback
   entree, `cancel()` n'a plus d'effet. Le tick doit donc reverifier l'etat
   d'arret AVANT de livrer, sinon un `evaluate_js`/`show_balloon` part sur une
   fenetre pywebview deja detruite.

3. `test_shutdown_attend_la_livraison_en_cours_avant_cleanup`
   -> le join borne de `shutdown()` : detruire l'icone tray (`cleanup()`) pendant
   qu'un ballon s'affiche est la meme course, vue depuis l'autre bout.

Aucun mock ne fabrique la condition testee : l'etat d'arret est produit par le
vrai `shutdown()`, et la concurrence par de vrais threads. Seuls les puits d'I/O
(`show_balloon`, `cleanup`) sont remplaces, pour ne pas toucher au Win32 tray.
"""

from __future__ import annotations

import threading
import time

import pytest

from cinesort.app import notify_service
from cinesort.app.notify_service import EVENT_SCAN_DONE, NotifyService

# Intervalle de drain court : les tests doivent rester rapides mais laisser au
# timer zombi le temps de se manifester (on attend plusieurs intervalles).
_TICK_S = 0.05


@pytest.fixture
def svc(monkeypatch):
    """NotifyService avec les puits d'I/O neutralises et shutdown garanti."""
    monkeypatch.setattr(notify_service, "cleanup", lambda: None)
    monkeypatch.setattr(notify_service, "show_balloon", lambda *a, **k: True)
    service = NotifyService(window=None)
    service.update_settings({"desktop_notifications_enabled": True})
    try:
        yield service
    finally:
        service.shutdown()


def _enqueue_from_background(service: NotifyService, title: str = "t") -> None:
    """Poste une notification depuis un thread background (donc: mise en file)."""
    worker = threading.Thread(target=service.notify, args=(EVENT_SCAN_DONE, title, "body"), daemon=True)
    worker.start()
    worker.join(2.0)
    assert not worker.is_alive(), "le thread d'enqueue n'a pas termine"


def test_shutdown_pendant_replanification_ne_laisse_pas_de_timer_zombi(svc, monkeypatch):
    """shutdown() concurrent d'une replanification ne doit laisser aucun timer arme.

    Le scenario de #616 exige que shutdown() s'intercale entre « le tick lit
    _drain_active » et « le tick publie le nouveau timer ». On le rend
    deterministe en ralentissant la CREATION du timer : la fabrique se signale,
    puis attend (borne) que shutdown() ait fini.

    - Code correct : shutdown() reste bloque sur le verrou pendant toute la
      sequence, donc il voit le timer publie et l'annule -> plus aucun tick.
    - Code sans atomicite : shutdown() passe devant, annule l'ANCIEN timer, et
      le tick publie ensuite un timer que plus personne n'annulera -> un tick
      supplementaire est observe apres shutdown().
    """
    ticks: list[float] = []
    real_tick = svc._drain_tick

    def counting_tick() -> None:
        ticks.append(time.monotonic())
        real_tick()

    # Attribut d'instance : masque la methode, sans toucher a la classe.
    svc._drain_tick = counting_tick  # type: ignore[method-assign]

    in_schedule = threading.Event()
    shutdown_done = threading.Event()
    real_timer_cls = threading.Timer
    creations = {"n": 0}

    def gated_timer(interval, function, *args, **kwargs):
        # Ne freiner QUE la replanification du drain (pas les Timer d'autrui,
        # ni la toute premiere creation faite par start_drain_timer).
        if function is svc._drain_tick:
            creations["n"] += 1
            if creations["n"] >= 2:
                in_schedule.set()
                shutdown_done.wait(0.4)
        return real_timer_cls(interval, function, *args, **kwargs)

    monkeypatch.setattr(threading, "Timer", gated_timer)

    svc.start_drain_timer(_TICK_S)
    assert in_schedule.wait(3.0), "le tick n'a jamais atteint la replanification"

    svc.shutdown()
    shutdown_done.set()
    ticks_at_shutdown = len(ticks)

    # Largement plus qu'un intervalle : un timer zombi aurait le temps de firer.
    time.sleep(_TICK_S * 6)

    assert len(ticks) == ticks_at_shutdown, (
        f"un timer a survecu a shutdown() : {len(ticks)} ticks au total "
        f"contre {ticks_at_shutdown} au moment du shutdown"
    )
    assert svc._drain_timer is None
    assert svc._drain_active is False


def test_tick_deja_dispatche_ne_livre_rien_apres_shutdown(svc, monkeypatch):
    """Un tick dont la callback a deja demarre ne doit plus rien livrer.

    `threading.Timer.cancel()` est sans effet une fois la callback entree : la
    seule protection est que `_drain_tick` reverifie l'etat d'arret avant de
    drainer. Ici l'appel direct a `_drain_tick()` apres `shutdown()` reproduit
    exactement la queue de cette course.
    """
    shown: list[str] = []
    monkeypatch.setattr(notify_service, "show_balloon", lambda title, body, level: shown.append(title) or True)

    _enqueue_from_background(svc, "apres-teardown")
    assert not svc._queue.empty(), "la notification devait etre mise en file"

    svc.shutdown()
    svc._drain_tick()

    assert shown == [], f"livraison apres shutdown : {shown}"
    assert svc._drain_timer is None


def test_shutdown_attend_la_livraison_en_cours_avant_cleanup(svc, monkeypatch):
    """cleanup() ne doit pas detruire l'icone tray pendant qu'un ballon s'affiche."""
    order: list[str] = []
    delivering = threading.Event()
    release = threading.Event()

    def blocking_balloon(title, body, level):
        order.append("livraison-debut")
        delivering.set()
        release.wait(3.0)
        order.append("livraison-fin")
        return True

    monkeypatch.setattr(notify_service, "show_balloon", blocking_balloon)
    monkeypatch.setattr(notify_service, "cleanup", lambda: order.append("cleanup"))

    _enqueue_from_background(svc, "en-cours")
    svc.start_drain_timer(_TICK_S)
    assert delivering.wait(3.0), "la livraison n'a jamais demarre"

    releaser = threading.Timer(0.15, release.set)
    releaser.daemon = True
    releaser.start()
    try:
        svc.shutdown()
    finally:
        releaser.cancel()

    assert order == ["livraison-debut", "livraison-fin", "cleanup"], (
        f"cleanup() n'a pas attendu la livraison en cours : {order}"
    )


def test_shutdown_est_idempotent_et_le_drain_reste_relancable(svc):
    """Deux shutdown() de suite ne doivent pas lever, et un restart reste possible."""
    svc.start_drain_timer(_TICK_S)
    svc.shutdown()
    svc.shutdown()
    assert svc._drain_active is False
    assert svc._drain_timer is None

    svc.start_drain_timer(_TICK_S)
    assert svc._drain_active is True
    assert svc._drain_timer is not None
