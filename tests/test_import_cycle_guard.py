"""Phase 10 v7.8.0 - guard rail anti-regression sur le cycle domain<->app.

CONTEXTE
--------
`cinesort/domain/core.py` importe eagerly `cinesort.app.*` (apply_core,
cleanup, plan_support, duplicate_support) pour fournir des re-exports
de compatibilite. C'est documente par le commentaire :

    # M10 : reduction du couplage domain->infra/app.
    # Les imports ci-dessous existent uniquement pour fournir des
    # re-exports de compatibilite [...] Un refactoring majeur devra
    # les supprimer.

Le decouplage reel demande de remonter ces helpers HORS du module
domain, ce qui est un chantier dedie. En v7.8.0 on installe juste
**un cliquet anti-regression** : si quelqu'un ajoute un NOUVEL eager
import depuis domain.core vers app/ui, le test fail.

Mesure snapshot (2026-05-11) :
- importing cinesort.domain.core charge 6 cinesort.app.* modules
- importing cinesort.domain.core charge 0 cinesort.ui.* modules
- importing cinesort.domain.core charge 0 cinesort.infra.* modules
  (sauf TmdbClient via TYPE_CHECKING qui n'est pas reellement importe)

Toute deviation a la hausse = regression a investiguer.
"""

from __future__ import annotations

import importlib
import sys
import unittest


# Snapshot 2026-05-11 v7.8.0 : 6 modules app charges au temps d'import
# cinesort.domain.core. Si la liste change : (a) une convergence (moins
# de modules) -> mettre a jour, (b) une regression (plus) -> investiguer.
_BASELINE_APP_MODULES_LOADED = 6
_BASELINE_UI_MODULES_LOADED = 0


def _fresh_import_domain_core() -> tuple[int, int, int]:
    """Importe cinesort.domain.core depuis zero, retourne (n_app, n_ui, n_infra).

    Snapshot/restore complete de sys.modules pour ne PAS polluer l'etat global
    des autres tests qui reposent sur des singletons de module (e.g.,
    log_scrubber._ROTATING_INSTALLED).
    """
    saved = dict(sys.modules)
    try:
        # Purge les modules cinesort.X pour forcer un re-import "frais"
        for m in [m for m in list(sys.modules) if m.startswith("cinesort.")]:
            del sys.modules[m]
        importlib.import_module("cinesort.domain.core")
        loaded = list(sys.modules)
        n_app = sum(1 for m in loaded if m.startswith("cinesort.app"))
        n_ui = sum(1 for m in loaded if m.startswith("cinesort.ui"))
        n_infra = sum(1 for m in loaded if m.startswith("cinesort.infra"))
        return n_app, n_ui, n_infra
    finally:
        # Restaure les modules pour ne pas reset les globals des modules
        # singletons (log_scrubber, NotifyService, etc.) que d'autres tests
        # utilisent.
        for m in [m for m in list(sys.modules) if m.startswith("cinesort.") and m not in saved]:
            del sys.modules[m]
        for m, mod in saved.items():
            if m.startswith("cinesort."):
                sys.modules[m] = mod


class ImportCycleGuardTests(unittest.TestCase):
    def test_domain_core_app_imports_not_growing(self) -> None:
        n_app, _, _ = _fresh_import_domain_core()
        self.assertLessEqual(
            n_app,
            _BASELINE_APP_MODULES_LOADED,
            f"Regression: cinesort.domain.core declenche {n_app} imports "
            f"cinesort.app.X (baseline {_BASELINE_APP_MODULES_LOADED}). "
            f"Verifier si un nouveau cycle a ete introduit ou actualiser "
            f"_BASELINE_APP_MODULES_LOADED si la convergence l'a fait baisser.",
        )

    def test_domain_core_does_not_import_ui_layer(self) -> None:
        _, n_ui, _ = _fresh_import_domain_core()
        self.assertEqual(
            n_ui,
            _BASELINE_UI_MODULES_LOADED,
            f"Domain importe la couche UI ({n_ui} modules cinesort.ui.X) - "
            f"violation grave de l'architecture en couches.",
        )

    def test_domain_core_loads_within_reasonable_time(self) -> None:
        """Sanity : l'import ne doit pas crasher et reste raisonnable."""
        import time

        saved = dict(sys.modules)
        try:
            for m in [m for m in list(sys.modules) if m.startswith("cinesort.")]:
                del sys.modules[m]
            t0 = time.time()
            importlib.import_module("cinesort.domain.core")
            dt_ms = (time.time() - t0) * 1000
            # 5 s est volontairement laxiste — c'est juste un crash-detector.
            self.assertLess(dt_ms, 5000, f"import cinesort.domain.core trop lent: {dt_ms:.0f}ms")
        finally:
            for m in [m for m in list(sys.modules) if m.startswith("cinesort.") and m not in saved]:
                del sys.modules[m]
            for m, mod in saved.items():
                if m.startswith("cinesort."):
                    sys.modules[m] = mod


if __name__ == "__main__":
    unittest.main()
