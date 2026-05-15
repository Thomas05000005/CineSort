"""Snapshot test des signatures publiques CineSortApi (issue #84 refactor safety).

Filet de securite pendant le refactor god class -> facades :
- Capture la signature de chaque methode publique (104 au baseline 2026-05-14)
- Detecte toute regression accidentelle (methode supprimee, signature changee)
- Pendant le refactor : nouvelles facades ajoutees sont OK, mais les anciennes
  methodes directes ne doivent JAMAIS disparaitre (backward-compat).

Strategie :
- Snapshot json a tests/snapshots/api_methods_v1.json (commited)
- Test verifie que toutes les methodes du snapshot sont toujours presentes
  avec la meme signature
- Si un caller frontend JS ou REST appelle une methode qui a ete supprimee
  par erreur, ce test fail AVANT le merge

Mise a jour intentionnelle :
- Quand on ajoute une nouvelle methode publique : OK, le test ne fail pas
- Quand on supprime VOLONTAIREMENT une methode (apres migration complete des
  callers) : regenerer le snapshot via :
    python -c "from tests.test_cinesort_api_snapshot import regenerate_snapshot; regenerate_snapshot()"
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "api_methods_v1.json"


def _current_methods_signatures() -> dict[str, str]:
    """Capture les signatures actuelles des methodes publiques de CineSortApi."""
    api = CineSortApi()
    methods: dict[str, str] = {}
    for name in sorted(dir(api)):
        if name.startswith("_"):
            continue
        attr = getattr(api, name)
        if not callable(attr):
            continue
        try:
            sig = str(inspect.signature(attr))
        except (TypeError, ValueError):
            sig = "?"
        methods[name] = sig
    return methods


def regenerate_snapshot() -> None:
    """Helper pour regenerer le snapshot APRES suppression intentionnelle.

    Usage :
        python -c "from tests.test_cinesort_api_snapshot import regenerate_snapshot; regenerate_snapshot()"
    """
    methods = _current_methods_signatures()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(methods, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Snapshot regenerated: {len(methods)} methods")


class CineSortApiSnapshotTests(unittest.TestCase):
    """Issue #84 : snapshot des signatures pour refactor safety."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        cls.current = _current_methods_signatures()

    def test_snapshot_file_exists(self) -> None:
        self.assertTrue(SNAPSHOT_PATH.is_file(), f"Snapshot manquant: {SNAPSHOT_PATH}")
        # Apres PR 10 du #84, le baseline est ~50 methodes publiques sur
        # CineSortApi (54 ont ete privatisees -> migrees sur les 5 facades).
        # Le seuil de "suspectement petit" devient 40.
        self.assertGreater(len(self.snapshot), 40, "Snapshot suspectement petit")

    def test_no_method_removed(self) -> None:
        """Aucune methode du snapshot ne doit avoir disparu.

        Si ce test fail apres un refactor : soit (a) la methode a ete supprimee
        intentionnellement (apres migration complete des callers), regenerer
        le snapshot via regenerate_snapshot(), soit (b) c'est une regression
        accidentelle, restaurer la methode.
        """
        snapshot_methods = set(self.snapshot.keys())
        current_methods = set(self.current.keys())
        removed = snapshot_methods - current_methods
        self.assertEqual(
            removed,
            set(),
            f"Methodes supprimees du CineSortApi : {sorted(removed)}. "
            f"Si intentionnel, regenerer le snapshot via regenerate_snapshot().",
        )

    def test_signatures_preserved(self) -> None:
        """Les signatures des methodes du snapshot doivent etre preservees.

        Un changement de signature = breaking change pour le frontend / REST.
        Si intentionnel, regenerer le snapshot.
        """
        diverged: list[str] = []
        for name, expected_sig in self.snapshot.items():
            current_sig = self.current.get(name)
            if current_sig is None:
                continue  # capture par test_no_method_removed
            if current_sig != expected_sig:
                diverged.append(f"{name}: expected={expected_sig} current={current_sig}")
        self.assertEqual(
            diverged,
            [],
            "Signatures divergentes :\n  " + "\n  ".join(diverged),
        )

    def test_baseline_50_methods(self) -> None:
        """Sanity check sur le nombre baseline.

        Pre PR 10 #84 : 104 methodes publiques sur CineSortApi (god class).
        Post PR 10 #84 : ~50 methodes publiques (les 54 facade-isees ont
        ete privatisees). Si ce nombre change beaucoup (< 40 ou > 70),
        investiguer.
        """
        self.assertGreaterEqual(len(self.snapshot), 40)
        self.assertLessEqual(len(self.snapshot), 70)


if __name__ == "__main__":
    unittest.main(verbosity=2)
