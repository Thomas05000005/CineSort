"""Tests Fix audit 2026-05-24 (v1.5.2) — Enforcement backend du delai 24h.

La promesse "Annulation possible pendant 24h" (Spec 08 §3.5, PR #394)
etait cosmetique avant ces tests : la carte UI affichait un countdown
24h mais le backend acceptait toujours l'undo. On verifie maintenant que :

- `undo_last_apply` refuse avec HTTP 410 Gone une fois passe le delai
  de 24h (mockage de time.time pour simuler T+25h).
- `undo_last_apply_preview` expose un champ `expired: bool` calcule sur
  la meme regle 24h, consomme par la carte UI Traitement.

Le dry_run reste autorise meme apres expiration : la preview doit
rester consultable (mais le frontend retire le bouton "Executer" dans
le modal).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class UndoDeadline24hEnforcementTests(unittest.TestCase):
    """Spec 08 §3.5 + audit 2026-05-24 v1.5.2 : enforcement backend du
    delai 24h sur l'annulation post-apply."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_undo24h_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min.start()
        self.addCleanup(_p_min.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_run_and_apply(self, api: CineSortApi) -> str:
        src_folder = self.root / "Old.Name.2010.1080p"
        _create_file(src_folder / "Old.Name.2010.1080p.mkv")
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }
        applied = api._apply_impl(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)
        return run_id

    def test_undo_blocked_after_24h(self) -> None:
        """Apres 24h, undo_last_apply doit refuser avec HTTP 410 Gone."""
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        # On force le temps a +25h pour simuler un depassement de delai.
        # Le mock doit cibler `time.time` dans apply_support qui est l'endroit
        # ou la regle est evaluee au moment de l'execution.
        import time as _stdlib_time

        future = _stdlib_time.time() + 25 * 3600
        with mock.patch("cinesort.ui.api.apply_support.time.time", return_value=future):
            result = api._undo_last_apply_impl(run_id, dry_run=False)

        self.assertFalse(result.get("ok"), result)
        # http_status 410 Gone signale aux clients REST qu'on refuse
        # definitivement (pas un 404 / 409 transient).
        self.assertEqual(int(result.get("http_status") or 0), 410, result)
        msg = str(result.get("message") or "")
        self.assertIn("24h", msg)

    def test_undo_allowed_within_24h(self) -> None:
        """Sanity check : undo passe normalement quand apply_ts est recent."""
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        # Pas de mock temps -> apply tout juste fait -> doit passer.
        result = api._undo_last_apply_impl(run_id, dry_run=False)
        self.assertTrue(result.get("ok"), result)
        # Le code ne doit PAS contenir http_status 410.
        self.assertNotEqual(int(result.get("http_status") or 0), 410)

    def test_undo_dry_run_still_allowed_after_24h(self) -> None:
        """Apres 24h, la preview (dry_run=True) reste consultable.

        Le frontend retire le bouton "Executer" si expired=True, mais
        l'utilisateur doit pouvoir consulter le detail de ce qui aurait
        ete annule.
        """
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        import time as _stdlib_time

        future = _stdlib_time.time() + 25 * 3600
        with mock.patch("cinesort.ui.api.apply_support.time.time", return_value=future):
            result = api._undo_last_apply_impl(run_id, dry_run=True)

        # dry_run=True doit retourner ok=True, status=PREVIEW_ONLY.
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "PREVIEW_ONLY", result)

    def test_undo_preview_marks_expired_after_24h(self) -> None:
        """La preview undo expose `expired: True` apres 24h.

        Permet a la carte UI Traitement de neutraliser le bouton "Executer
        annulation" du modal sans aller-retour reseau.
        """
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        # Premier appel : encore dans le delai -> expired=False.
        preview_now = api._undo_last_apply_preview_impl(run_id)
        self.assertTrue(preview_now.get("ok"), preview_now)
        self.assertIn("expired", preview_now, "preview doit exposer `expired`")
        self.assertFalse(preview_now.get("expired"), preview_now)

        # Deuxieme appel : T+25h -> expired=True.
        import time as _stdlib_time

        future = _stdlib_time.time() + 25 * 3600
        with mock.patch("cinesort.ui.api.apply_support.time.time", return_value=future):
            preview_late = api._undo_last_apply_preview_impl(run_id)

        self.assertTrue(preview_late.get("ok"), preview_late)
        self.assertTrue(preview_late.get("expired"), preview_late)
        # apply_ts reste expose pour cohérence avec le front (countdown).
        self.assertGreater(float(preview_late.get("apply_ts") or 0), 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
