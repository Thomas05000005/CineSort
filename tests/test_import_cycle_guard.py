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

v1.0.0-beta : on utilise **subprocess** au lieu de manipuler `sys.modules`
directement. Manipuler sys.modules dans un test pollue les caches
module-level (lru_cache, dict globals) utilises par les tests suivants
(decouvert via bisection : issue GitHub #4).
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

# Snapshot 2026-05-11 v7.8.0 : 6 modules app charges au temps d'import
# cinesort.domain.core. Si la liste change : (a) une convergence (moins
# de modules) -> mettre a jour, (b) une regression (plus) -> investiguer.
_BASELINE_APP_MODULES_LOADED = 6
_BASELINE_UI_MODULES_LOADED = 0

REPO_ROOT = Path(__file__).resolve().parent.parent


def _count_imports_in_subprocess() -> dict[str, int]:
    """Lance un sous-process Python qui importe cinesort.domain.core et
    rapporte combien de modules cinesort.app/ui/infra sont charges.

    Utilise subprocess (pas manipulation de sys.modules) pour eviter de
    polluer les caches module-level des tests suivants.

    Cf issue #83 v7.8.0 : on track AUSSI les imports declenches par
    cinesort.domain.perceptual (8 modules qui importaient infra directement
    avant le fix Option C / Service Locator).
    """
    script = (
        "import sys; "
        "import cinesort.domain.core; "
        "import cinesort.domain.perceptual.audio_fingerprint; "
        "import cinesort.domain.perceptual.av1_grain_metadata; "
        "import cinesort.domain.perceptual.ffmpeg_runner; "
        "import cinesort.domain.perceptual.hdr_analysis; "
        "import cinesort.domain.perceptual.metadata_analysis; "
        "import cinesort.domain.perceptual.scene_detection; "
        "import cinesort.domain.perceptual.spectral_analysis; "
        "import cinesort.domain.perceptual.ssim_self_ref; "
        "loaded = list(sys.modules); "
        "n_app = sum(1 for m in loaded if m.startswith('cinesort.app')); "
        "n_ui = sum(1 for m in loaded if m.startswith('cinesort.ui')); "
        "n_infra = sum(1 for m in loaded if m.startswith('cinesort.infra')); "
        "print(f'{n_app},{n_ui},{n_infra}')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    output = result.stdout.strip().splitlines()[-1]  # derniere ligne (ignore warnings)
    parts = output.split(",")
    return {"app": int(parts[0]), "ui": int(parts[1]), "infra": int(parts[2])}


class DomainPerceptualNoInfraImportTests(unittest.TestCase):
    """Cf issue #83 : domain/perceptual/* ne doit plus importer infra/* directement.

    Avant le fix Option C (Service Locator), les 8 fichiers de
    domain/perceptual/ importaient `cinesort.infra.subprocess_safety.tracked_run`
    en top-level — violation de couche.

    Apres : ils importent `cinesort.domain._runners.tracked_run` qui resoud
    au runtime via get_runner(). L'implementation concrete est injectee
    par cinesort/__init__.py au boot.

    Ce test garantit qu'on ne regresse pas — inspection statique sur les
    sources, indep du runtime.
    """

    _PERCEPTUAL_FILES = [
        "audio_fingerprint.py",
        "av1_grain_metadata.py",
        "ffmpeg_runner.py",
        "hdr_analysis.py",
        "metadata_analysis.py",
        "scene_detection.py",
        "spectral_analysis.py",
        "ssim_self_ref.py",
    ]

    def test_no_direct_import_from_infra(self) -> None:
        perceptual_dir = REPO_ROOT / "cinesort" / "domain" / "perceptual"
        violations: list[str] = []
        for fname in self._PERCEPTUAL_FILES:
            src = (perceptual_dir / fname).read_text(encoding="utf-8")
            for line_no, line in enumerate(src.splitlines(), start=1):
                stripped = line.strip()
                # Imports top-level (pas dans une fonction) qui ciblent cinesort.infra.*
                if stripped.startswith("from cinesort.infra") or stripped.startswith("import cinesort.infra"):
                    # Acceptable : imports lazy dans une fonction (indented > 0)
                    if line.startswith("from ") or line.startswith("import "):
                        violations.append(f"{fname}:{line_no} : {stripped}")
        self.assertEqual(
            violations,
            [],
            "domain/perceptual/* ne doit pas importer infra directement (Service Locator via "
            "domain._runners requis). Violations:\n  " + "\n  ".join(violations),
        )

    def test_runners_module_provides_tracked_run(self) -> None:
        """Le module _runners expose tracked_run + set_runner + get_runner."""
        runners_src = (REPO_ROOT / "cinesort" / "domain" / "_runners.py").read_text(encoding="utf-8")
        self.assertIn("def tracked_run", runners_src)
        self.assertIn("def set_runner", runners_src)
        self.assertIn("def get_runner", runners_src)


class ImportCycleGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 1 seul subprocess pour les 3 tests (couts d'init Python ~200ms)
        cls.counts = _count_imports_in_subprocess()

    def test_domain_core_app_imports_not_growing(self) -> None:
        n_app = self.counts["app"]
        self.assertLessEqual(
            n_app,
            _BASELINE_APP_MODULES_LOADED,
            f"Regression: cinesort.domain.core declenche {n_app} imports "
            f"cinesort.app.X (baseline {_BASELINE_APP_MODULES_LOADED}). "
            f"Verifier si un nouveau cycle a ete introduit ou actualiser "
            f"_BASELINE_APP_MODULES_LOADED si la convergence l'a fait baisser.",
        )

    def test_domain_core_does_not_import_ui_layer(self) -> None:
        n_ui = self.counts["ui"]
        self.assertEqual(
            n_ui,
            _BASELINE_UI_MODULES_LOADED,
            f"Domain importe la couche UI ({n_ui} modules cinesort.ui.X) - "
            f"violation grave de l'architecture en couches.",
        )

    def test_domain_core_loads_within_reasonable_time(self) -> None:
        """Sanity : l'import ne doit pas crasher."""
        # Si _count_imports_in_subprocess() a renvoye sans exception, l'import
        # a deja ete valide (subprocess.run avec check=True).
        self.assertGreaterEqual(self.counts["app"], 0)


if __name__ == "__main__":
    unittest.main()
