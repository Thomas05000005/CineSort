"""R8 F5 — DIFFÉRENTIEL R8-069 : le toast desktop respecte desktop_notifications_enabled.

AVANT : NotifyService.enabled lisait notifications_enabled (toggle « notifications
applicatives ») -> le toggle UI « Activer les notifications desktop »
(desktop_notifications_enabled) était un FANTÔME. APRÈS : enabled lit
desktop_notifications_enabled -> ON émet le toast (show_balloon), OFF non.

NB : show_balloon est OS-dépendant (Windows) -> on prouve le GATE _is_event_enabled
(qui décide d'appeler ou non _deliver/show_balloon). Rendu OS à vérifier sur desktop.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f5_desktop_notif_diff.py
"""

from cinesort.app.notify_service import EVENT_SCAN_DONE, NotifyService


def gate(desktop_on, notifications_on):
    svc = NotifyService(window=None)
    svc.update_settings(
        {
            "desktop_notifications_enabled": desktop_on,
            "notifications_enabled": notifications_on,
            "notifications_scan_done": True,
        }
    )
    # _is_event_enabled gouverne l'émission du toast (appelé par _should_notify/_deliver).
    return svc._is_event_enabled(EVENT_SCAN_DONE)


# AVANT (réplique) : gate = notifications_enabled, ignore desktop
def gate_avant(desktop_on, notifications_on):
    return bool(notifications_on)  # ancienne logique


print("=== Toast desktop émis (gate _is_event_enabled) pour scan_done ===")
print(f"  {'desktop':>8} {'applicatif':>10} | {'AVANT':>6} {'APRÈS':>6}")
rows = [(True, False), (False, True), (True, True), (False, False)]
ok = True
for d, n in rows:
    av = gate_avant(d, n)
    ap = gate(d, n)
    print(f"  {str(d):>8} {str(n):>10} | {str(av):>6} {str(ap):>6}")
# APRÈS : suit desktop_notifications_enabled ; AVANT : suivait notifications_enabled
ap_on = gate(True, False)
ap_off = gate(False, True)
print(f"\n  APRÈS : desktop ON (appli OFF) -> toast={ap_on} ; desktop OFF (appli ON) -> toast={ap_off}")
print(f"  R8-069 CÂBLÉ : {ap_on is True and ap_off is False} (ON!=OFF piloté par le bon toggle)")
print("  (rendu OS show_balloon à vérifier sur desktop Windows réel)")
