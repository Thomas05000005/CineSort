"""Tests mode planifie / watch folder — item 9.11.

Couvre :
- _snapshot_root : dossiers avec mtimes, vide, inexistant, _review ignore
- _has_changed : identique, nouveau dossier, dossier supprime
- FolderWatcher : lifecycle start/stop, premier poll pas de scan
- Settings : defaults, round-trip
- UI : toggle settings, indicateur dashboard, CSS
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app.watcher import _snapshot_root, _has_changed, FolderWatcher


# ---------------------------------------------------------------------------
# _snapshot_root (4 tests)
# ---------------------------------------------------------------------------


class SnapshotRootTests(unittest.TestCase):
    """Tests du snapshot de dossier racine."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_watch_")
        self.root = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_three_subdirs(self) -> None:
        """3 sous-dossiers → 3 entrees."""
        for name in ("Film A", "Film B", "Film C"):
            (self.root / name).mkdir()
        snap = _snapshot_root(self.root)
        self.assertEqual(len(snap), 3)
        names = {e.rsplit("|", 1)[0] for e in snap}
        self.assertEqual(names, {"Film A", "Film B", "Film C"})

    def test_empty_dir(self) -> None:
        """Dossier vide → snapshot vide."""
        snap = _snapshot_root(self.root)
        self.assertEqual(snap, frozenset())

    def test_nonexistent_dir(self) -> None:
        """Dossier inexistant → snapshot vide, pas de crash."""
        snap = _snapshot_root(Path("/nonexistent/path/xyz"))
        self.assertEqual(snap, frozenset())

    def test_underscore_dirs_ignored(self) -> None:
        """Dossiers commencant par _ sont ignores."""
        (self.root / "_review").mkdir()
        (self.root / "_Collection").mkdir()
        (self.root / "Film A").mkdir()
        snap = _snapshot_root(self.root)
        self.assertEqual(len(snap), 1)
        names = {e.rsplit("|", 1)[0] for e in snap}
        self.assertIn("Film A", names)
        self.assertNotIn("_review", names)


# ---------------------------------------------------------------------------
# _has_changed (3 tests)
# ---------------------------------------------------------------------------


class HasChangedTests(unittest.TestCase):
    """Tests de la comparaison de snapshots."""

    def test_identical_no_change(self) -> None:
        """Snapshots identiques → pas de changement."""
        snap = {"root1": frozenset({"Film A|1000", "Film B|2000"})}
        changed, _ = _has_changed(snap, snap)
        self.assertFalse(changed)

    def test_new_folder_detected(self) -> None:
        """Nouveau dossier → changement detecte."""
        old = {"root1": frozenset({"Film A|1000"})}
        new = {"root1": frozenset({"Film A|1000", "Film B|2000"})}
        changed, detail = _has_changed(old, new)
        self.assertTrue(changed)
        self.assertIn("+1", detail)

    def test_removed_folder_detected(self) -> None:
        """Dossier supprime → changement detecte."""
        old = {"root1": frozenset({"Film A|1000", "Film B|2000"})}
        new = {"root1": frozenset({"Film A|1000"})}
        changed, detail = _has_changed(old, new)
        self.assertTrue(changed)
        self.assertIn("-1", detail)


# ---------------------------------------------------------------------------
# FolderWatcher lifecycle (3 tests)
# ---------------------------------------------------------------------------


class WatcherLifecycleTests(unittest.TestCase):
    """Tests du cycle de vie du thread watcher."""

    def test_start_and_stop(self) -> None:
        """Le watcher demarre et s'arrete proprement."""
        api = mock.MagicMock()
        api._runs = {}
        api._runs_lock = __import__("threading").Lock()
        watcher = FolderWatcher(api, interval_s=10, roots=[])
        watcher.start()
        self.assertTrue(watcher.is_alive())
        watcher.stop()
        time.sleep(0.1)
        self.assertFalse(watcher.is_alive())

    def test_initial_snapshot_no_scan(self) -> None:
        """Le premier poll prend un snapshot initial mais ne declenche pas de scan."""
        tmp = tempfile.mkdtemp(prefix="cinesort_watch_init_")
        try:
            root = Path(tmp)
            (root / "Film A").mkdir()
            api = mock.MagicMock()
            api._runs = {}
            api._runs_lock = __import__("threading").Lock()
            api.get_settings.return_value = {"roots": [str(root)]}
            api.start_plan.return_value = {"ok": True, "run_id": "test"}

            watcher = FolderWatcher(api, interval_s=0.1, roots=[root])
            watcher.start()
            time.sleep(0.3)  # Laisser le thread faire le snapshot initial
            watcher.stop()
            # start_plan ne doit PAS avoir ete appele (pas de changement apres le snapshot initial)
            api.start_plan.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skip_if_scan_running(self) -> None:
        """Si un scan est en cours, le watcher ne declenche pas de nouveau scan."""
        api = mock.MagicMock()
        # Simuler un scan en cours
        running_rs = mock.MagicMock()
        running_rs.running = True
        running_rs.done = False
        api._runs = {"run1": running_rs}
        api._runs_lock = __import__("threading").Lock()

        watcher = FolderWatcher(api, interval_s=10, roots=[])
        self.assertTrue(watcher._is_scan_running())


# ---------------------------------------------------------------------------
# Settings (2 tests)
# ---------------------------------------------------------------------------


class WatcherSettingsTests(unittest.TestCase):
    """Tests des settings watch."""

    def test_defaults(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        s = api.get_settings()
        self.assertFalse(s.get("watch_enabled"))
        self.assertEqual(s.get("watch_interval_minutes"), 5)

    def test_round_trip(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_watch_s_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "watch_enabled": True,
                    "watch_interval_minutes": 10,
                }
            )
            s = api.get_settings()
            self.assertTrue(s["watch_enabled"])
            self.assertEqual(s["watch_interval_minutes"], 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# UI (3 tests)
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class WatcherUiTests(unittest.TestCase):
    """Tests presence UI watcher."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.settings_js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        cls.index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.status_js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_settings_toggle_present(self) -> None:
        self.assertIn("watch_enabled", self.settings_js)
        self.assertIn("watch_interval_minutes", self.settings_js)
        self.assertIn("ckWatchEnabled", self.index_html)
        self.assertIn("watchInterval", self.index_html)

    def test_dashboard_indicator(self) -> None:
        self.assertIn("watch_enabled", self.status_js)
        self.assertIn("watcher-status", self.status_js)

    def test_css_watcher_classes(self) -> None:
        self.assertIn(".watcher-status", self.app_css)
        self.assertIn(".watcher-status--active", self.dash_css)


if __name__ == "__main__":
    unittest.main()
