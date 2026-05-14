"""Cf issue #83 : interface abstraite pour subprocess runner.

Avant : les 8 modules de cinesort/domain/perceptual/ importaient directement
`cinesort.infra.subprocess_safety.tracked_run`, ce qui creait une violation
de couche (domain ne doit pas importer infra) — Dependency Inversion ignore.

Apres : domain definit l'interface abstraite (ce module) et infra
fournit l'implementation concrete (subprocess_safety.tracked_run), wire-ee
au boot de cinesort/__init__.py.

Pattern : Service Locator simplifie (pas DI complete pour eviter de toucher
les ~50 callers perceptual). Le module domain reste libre de toute
dependance concrete a infra ou app.

Tests : peuvent override le runner via set_runner() pour injecter un mock.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Signature compatible avec subprocess.run et cinesort.infra.subprocess_safety.tracked_run.
# Le concept : "fonction qui execute une commande et retourne CompletedProcess".
RunnerFn = Callable[..., subprocess.CompletedProcess]

_runner: Optional[RunnerFn] = None


def set_runner(fn: RunnerFn) -> None:
    """Configure le runner subprocess utilise par les modules perceptual.

    Appele au boot par cinesort/__init__.py (qui injecte tracked_run depuis
    cinesort.infra.subprocess_safety). Les tests peuvent override pour
    injecter un mock runner.
    """
    global _runner
    _runner = fn


def get_runner() -> RunnerFn:
    """Retourne le runner configure. Fallback : subprocess.run brut + warning.

    Le fallback est de la defense en profondeur : si pour une raison
    quelconque (test isole, import sans cinesort/__init__) le runner n'est
    pas configure, on utilise subprocess.run plutot que de crasher. Le warning
    permet de detecter le probleme en logs.
    """
    if _runner is None:
        logger.warning(
            "domain._runners: runner non configure, fallback subprocess.run. "
            "Verifier que cinesort/__init__.py est charge au boot."
        )
        return subprocess.run  # type: ignore[return-value]
    return _runner


def tracked_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """Alias retro-compat pour l'API historique (import drop-in).

    Permet aux 8 modules perceptual de faire :
        from cinesort.domain._runners import tracked_run
    au lieu de :
        from cinesort.infra.subprocess_safety import tracked_run

    Resolu au runtime via get_runner() — donc respecte tout override via
    set_runner().
    """
    return get_runner()(*args, **kwargs)
