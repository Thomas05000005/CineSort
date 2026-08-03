from __future__ import annotations

# Cf issue #83 : wiring du runner subprocess pour les modules perceptual.
# domain._runners definit l'interface abstraite (Service Locator), infra
# fournit l'implementation concrete (tracked_run avec cleanup garanti).
# Ce wiring DOIT se faire ici car cinesort/__init__.py est garanti d'etre
# charge AVANT tout sous-module de cinesort.* (semantique Python).


def _wire_runtime_dependencies() -> None:
    """Injecte les implementations concretes dans les ports domain.

    Idempotent : peut etre rappele plusieurs fois sans effet de bord.
    """
    try:
        from cinesort.domain._runners import set_popen_runner, set_runner
        from cinesort.infra.subprocess_safety import (
            tracked_popen as _tracked_popen,
        )
        from cinesort.infra.subprocess_safety import tracked_run as _tracked_run

        set_runner(_tracked_run)
        set_popen_runner(_tracked_popen)
    except ImportError:
        # Cas extreme : infra pas dispo (env test minimal). Le fallback
        # subprocess.run / Popen brut dans get_runner() / tracked_popen
        # prendra le relais.
        pass


_wire_runtime_dependencies()
