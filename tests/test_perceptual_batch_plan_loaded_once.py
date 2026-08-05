"""`analyze_perceptual_batch` ne doit relire plan.jsonl qu'UNE fois par batch.

Ultra-audit 2026-08 (N24) : `api._runs` n'est peuple que par `start_plan`
(run_flow_support.py). Sur un run anterieur au process courant — cas de
« Recalculer tous les scores » apres un redemarrage — `_get_run` rend None et
`_validate_and_load_context` relisait INTEGRALEMENT plan.jsonl pour CHAQUE
film. Mesure adversaire sur le plan reel de l'utilisateur : 1027 relectures,
1.45 Go relus, +33 s, plus ~19 Mo de PlanRow par chargement multiplies par le
nombre de workers.

Les tests utilisent de vrais `PlanRow` et comptent les chargements reels.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, ".")

from cinesort.domain.core import PlanRow
from cinesort.ui.api import perceptual_support


def _plan_row(rid: str) -> PlanRow:
    return PlanRow(
        row_id=rid,
        kind="single",
        folder=f"D:/Films/Film {rid}",
        video=f"Film.{rid}.mkv",
        proposed_title=f"Film {rid}",
        proposed_year=2020,
        proposed_source="name",
        confidence=90,
        confidence_label="high",
        candidates=[],
    )


class _FakePerceptualRepo:
    def get_perceptual_report(self, *, run_id: str, row_id: str):
        return None  # jamais de cache -> on va bien jusqu'au chargement du plan


class _FakeStore:
    def __init__(self) -> None:
        self.perceptual = _FakePerceptualRepo()


class _FakeSettings:
    def get_settings(self) -> Dict[str, Any]:
        return {
            "perceptual_enabled": True,
            "ffprobe_path": "ffprobe",
            "perceptual_parallelism_enabled": False,  # deterministe
        }


class _FakeApi:
    """Stub d'API : le run n'est PAS en memoire (cas post-redemarrage)."""

    def __init__(self, rows: List[PlanRow]) -> None:
        self._state_dir = Path(".")
        self._rows = rows
        self.settings = _FakeSettings()
        self.load_calls = 0

    def _find_run_row(self, run_id: str):
        return ({"run_id": run_id, "state_dir": "."}, _FakeStore())

    def _get_run(self, run_id: str) -> Optional[Any]:
        return None

    def _run_paths_for(self, state_dir: Any, run_id: str, ensure_exists: bool = True):
        return {"run_dir": "."}

    def _load_rows_from_plan_jsonl(self, run_paths: Any) -> List[PlanRow]:
        self.load_calls += 1
        return list(self._rows)

    def _cfg_from_run_row(self, run_row: Any):
        return object()

    def _resolve_media_path_for_row(self, cfg: Any, row: Any):
        # On s'arrete ici : pas de ffmpeg lance, le film est signale introuvable.
        return None


class PerceptualBatchPlanLoadTests(unittest.TestCase):
    RUN_ID = "run_n24"

    def setUp(self) -> None:
        self.rows = [_plan_row(f"R{i}") for i in range(25)]
        self.api = _FakeApi(self.rows)
        # Neutralise la resolution de ffmpeg (aucun binaire requis).
        self._orig_resolve = perceptual_support.resolve_ffmpeg_path
        perceptual_support.resolve_ffmpeg_path = lambda _p: "C:/fake/ffmpeg.exe"
        self.addCleanup(setattr, perceptual_support, "resolve_ffmpeg_path", self._orig_resolve)

    def _row_ids(self) -> List[str]:
        return [r.row_id for r in self.rows]

    def test_plan_is_loaded_once_for_the_whole_batch(self) -> None:
        out = perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, self._row_ids())
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["total"], 25)
        self.assertEqual(
            self.api.load_calls,
            1,
            f"plan.jsonl relu {self.api.load_calls} fois pour 25 films (regression N24)",
        )

    def test_load_count_does_not_grow_with_the_batch(self) -> None:
        """Le cout de chargement doit etre CONSTANT, pas proportionnel."""
        perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, self._row_ids()[:5])
        small = self.api.load_calls
        self.api.load_calls = 0
        perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, self._row_ids())
        big = self.api.load_calls
        self.assertEqual(big, small, f"{small} chargements a 5 films, {big} a 25 films")

    def test_every_film_is_still_resolved_from_the_shared_index(self) -> None:
        """Le prechargement ne doit perdre AUCUN film (sinon 'introuvable dans ce plan')."""
        out = perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, self._row_ids())
        messages = [str(e.get("message") or "") for e in out["errors"]]
        self.assertEqual(len(messages), 25, out)
        for msg in messages:
            self.assertNotIn(
                "introuvable dans ce plan",
                msg,
                "un film present dans plan.jsonl n'a pas ete retrouve via l'index partage",
            )
            self.assertIn("media introuvable", msg.lower())

    def test_unknown_row_id_is_still_reported_as_missing(self) -> None:
        """L'index ne doit pas inventer de films : un row_id absent reste une erreur."""
        out = perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, ["R0", "R_INEXISTANT"])
        messages = " | ".join(str(e.get("message") or "") for e in out["errors"])
        self.assertIn("introuvable dans ce plan", messages)

    def test_single_film_batch_keeps_the_historical_path(self) -> None:
        """Un batch d'un seul film ne precharge rien (aucun gain, aucun risque)."""
        out = perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, ["R0"])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self.api.load_calls, 1)

    def test_in_memory_run_is_never_reloaded(self) -> None:
        """Chemin deja immunise (perceptual_auto_on_scan) : zero lecture disque."""

        class _RunState:
            def __init__(self, rows: List[PlanRow]) -> None:
                self.rows = rows
                self.cfg = object()

        rs = _RunState(self.rows)
        self.api._get_run = lambda run_id: rs  # type: ignore[method-assign]
        out = perceptual_support.analyze_perceptual_batch(self.api, self.RUN_ID, self._row_ids())
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self.api.load_calls, 0, "le run est en memoire : plan.jsonl ne doit pas etre lu")


if __name__ == "__main__":
    unittest.main()
