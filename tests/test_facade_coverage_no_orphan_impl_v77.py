"""Vague M M-02 — Facade coverage / no-orphan-_impl regression test.

Filet de securite pour le refactor god class -> facades (issue #84) :

    - Detecte si une nouvelle methode `_X_impl` est ajoutee sur CineSortApi
      SANS qu'aucune facade ne l'expose (orphan _impl).
    - Detecte si une methode publique d'une facade est SUPPRIMEE (breaking
      change pour le frontend / REST dispatcher).

Le snapshot `tests/snapshots/facade_methods_v77.json` capture l'etat fige
des 6 facades + des methodes publiques residuelles de CineSortApi. Si une
modification est intentionnelle (nouvelle methode ajoutee a une facade,
ou methode retiree apres migration complete), regenerer via :

    python -c "from tests.test_facade_coverage_no_orphan_impl_v77 import regenerate_facade_snapshot; regenerate_facade_snapshot()"

Note : ce test est complementaire de `test_cinesort_api_snapshot.py` qui
capture la signature des methodes publiques residuelles. Celui-ci capture
le CONTRAT des facades (qui delegate vers quel `_impl`).
"""

from __future__ import annotations

import inspect
import json
import re
import unittest
from pathlib import Path
from typing import Dict, List, Set, Type

from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.facades.integrations_facade import IntegrationsFacade
from cinesort.ui.api.facades.library_facade import LibraryFacade
from cinesort.ui.api.facades.quality_facade import QualityFacade
from cinesort.ui.api.facades.run_facade import RunFacade
from cinesort.ui.api.facades.runtime_facade import RuntimeFacade
from cinesort.ui.api.facades.settings_facade import SettingsFacade

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "facade_methods_v77.json"

FACADES: Dict[str, Type] = {
    "library": LibraryFacade,
    "quality": QualityFacade,
    "run": RunFacade,
    "runtime": RuntimeFacade,
    "settings": SettingsFacade,
    "integrations": IntegrationsFacade,
}


def _public_methods(cls: Type) -> List[str]:
    """Retourne la liste triee des methodes publiques d'une facade."""
    return sorted(m for m in vars(cls) if not m.startswith("_") and callable(getattr(cls, m, None)))


def _current_facade_methods() -> Dict[str, List[str]]:
    return {name: _public_methods(cls) for name, cls in FACADES.items()}


def _referenced_impls() -> Set[str]:
    """Extrait tous les `_X_impl` referencees via self._api._..._impl dans les facades."""
    pattern = re.compile(r"self\._api\.(_\w+_impl)\b")
    referenced: Set[str] = set()
    for cls in FACADES.values():
        try:
            src = inspect.getsource(cls)
        except OSError:
            continue
        referenced.update(pattern.findall(src))
    return referenced


def _all_impls_on_api() -> Set[str]:
    api = CineSortApi()
    return {m for m in dir(api) if m.endswith("_impl") and not m.startswith("__") and callable(getattr(api, m, None))}


def _public_residual() -> List[str]:
    api = CineSortApi()
    return sorted(m for m in dir(api) if not m.startswith("_") and callable(getattr(api, m, None)))


def regenerate_facade_snapshot() -> None:
    """Helper pour regenerer le snapshot apres une modification intentionnelle.

    Usage :
        python -c "from tests.test_facade_coverage_no_orphan_impl_v77 import regenerate_facade_snapshot; regenerate_facade_snapshot()"
    """
    facades = _current_facade_methods()
    residual = _public_residual()
    impl_count = len(_all_impls_on_api())
    total_facade = sum(len(v) for v in facades.values())

    snapshot = {
        "_doc": (
            "Vague M M-02 : snapshot du contrat des facades CineSortApi. "
            "Regenere via regenerate_facade_snapshot(). "
            "Detecte ajout d'un _impl orphelin (sans facade) et retrait d'une "
            "methode publique d'une facade."
        ),
        "version": "1.5.2-beta",
        "generated_at_iso": "2026-06-01",
        "facades": facades,
        "public_residual_cinesort_api": residual,
        "total_impl_methods": impl_count,
        "total_facade_methods": total_facade,
        "total_methods": total_facade + len(residual),
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Snapshot facade regenere : {len(facades)} facades, "
        f"{total_facade} methodes facade, {impl_count} _impl, "
        f"{len(residual)} publiques residuelles."
    )


class FacadeCoverageNoOrphanImplTests(unittest.TestCase):
    """Vague M M-02 — Filet anti-regression facade coverage."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        cls.current_facades = _current_facade_methods()
        cls.referenced_impls = _referenced_impls()
        cls.all_impls = _all_impls_on_api()
        cls.current_residual = _public_residual()

    # ---------- Snapshot integrity ----------

    def test_snapshot_exists_and_has_6_facades(self) -> None:
        self.assertTrue(SNAPSHOT_PATH.is_file(), f"Snapshot manquant : {SNAPSHOT_PATH}")
        self.assertEqual(
            sorted(self.snapshot["facades"].keys()),
            ["integrations", "library", "quality", "run", "runtime", "settings"],
            "Le snapshot doit contenir exactement les 6 facades de l'architecture #84.",
        )

    def test_snapshot_baseline_counts(self) -> None:
        """Sanity check sur les ordres de grandeur (~110 _impl, ~7 residuelles)."""
        self.assertGreaterEqual(self.snapshot["total_impl_methods"], 100)
        self.assertLessEqual(self.snapshot["total_impl_methods"], 200)
        self.assertGreaterEqual(self.snapshot["total_facade_methods"], 100)
        self.assertLessEqual(self.snapshot["total_facade_methods"], 200)
        self.assertLessEqual(
            len(self.snapshot["public_residual_cinesort_api"]),
            10,
            "Plus de 10 methodes publiques residuelles : la migration vers facades regresse.",
        )

    # ---------- ARCH-02 : detection de _impl orphelins ----------

    def test_no_orphan_impl_method(self) -> None:
        """Aucun `_X_impl` sur CineSortApi ne doit etre sans facade qui le delegate.

        Si ce test fail : tu as ajoute une methode `_foo_impl` sur CineSortApi
        sans creer la methode publique correspondante sur une facade. Ajoute-la
        a la facade du bon bounded context (library / quality / run / runtime /
        settings / integrations) puis regenere le snapshot.
        """
        orphans = self.all_impls - self.referenced_impls
        self.assertEqual(
            orphans,
            set(),
            f"_impl orphelins detectes (aucune facade ne les expose) : {sorted(orphans)}. "
            f"Ajoute la methode publique correspondante sur la facade du bounded context, "
            f"puis regenere le snapshot via regenerate_facade_snapshot().",
        )

    # ---------- ARCH-01 : detection de regression facade ----------

    def test_no_facade_method_removed(self) -> None:
        """Aucune methode publique du snapshot ne doit avoir disparu d'une facade.

        Une suppression = breaking change pour le frontend (api.X.foo()) et le
        dispatcher REST. Si intentionnel (apres migration complete des callers),
        regenerer le snapshot via regenerate_facade_snapshot().
        """
        removed: Dict[str, List[str]] = {}
        for name, expected in self.snapshot["facades"].items():
            current = set(self.current_facades.get(name, []))
            missing = sorted(set(expected) - current)
            if missing:
                removed[name] = missing
        self.assertEqual(
            removed,
            {},
            f"Methodes publiques supprimees de facades : {removed}. "
            f"Si intentionnel, regenerer le snapshot via regenerate_facade_snapshot().",
        )

    def test_no_residual_method_removed(self) -> None:
        """Aucune des methodes publiques residuelles de CineSortApi ne doit disparaitre."""
        expected = set(self.snapshot["public_residual_cinesort_api"])
        current = set(self.current_residual)
        missing = sorted(expected - current)
        self.assertEqual(
            missing,
            [],
            f"Methodes publiques residuelles supprimees de CineSortApi : {missing}. "
            f"Si intentionnel (migration), regenerer le snapshot.",
        )

    # ---------- Discipline : pas de fuite de methodes _internal ----------

    def test_no_internal_method_exposed_via_facade(self) -> None:
        """Une facade ne doit JAMAIS exposer publiquement une methode commencant par `_`."""
        leaks: Dict[str, List[str]] = {}
        for name, cls in FACADES.items():
            # vars() inclut tout, on filtre sur les methodes publiques pretes a l'emploi
            publics = [m for m in vars(cls) if not m.startswith("_") and callable(getattr(cls, m, None))]
            internal_like = [m for m in publics if m.startswith("internal_") or m.endswith("_internal")]
            if internal_like:
                leaks[name] = internal_like
        self.assertEqual(
            leaks,
            {},
            f"Methodes nommees comme internes mais exposees publiquement par facade : {leaks}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
