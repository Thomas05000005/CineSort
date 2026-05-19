"""V2-04 — verifie qu'aucune des 9 vues migrees ne reste sur Promise.all (audit ID-ROB-002)."""

from pathlib import Path
import unittest

# Migration B (PR1 #257 + PR2) : legacy frontend supprime.
# TODO Phase 2/3 : porter les invariants utiles vers de nouveaux tests dashboard
# une fois le Shell 3 zones + les 12 ecrans implementes.
if not (Path(__file__).resolve().parents[1] / "web" / "views" / "home.js").exists():
    raise unittest.SkipTest(
        "Legacy frontend removed (PR #257 + PR2 migration B). "
        "Tests rely on web/views/*.js files which were deleted "
        "(home.js, help.js, quality.js, settings.js, validation.js, etc.)."
    )


class PromiseAllSettledTests(unittest.TestCase):
    # V5C-01 : retire les vues v4 dashboard supprimees (quality/review/library/),
    # remplacees par les vues v5 (qij-v5, processing, library-v5).
    EXPECTED_MIGRATED = [
        "web/views/execution.js",
        "web/views/home.js",
        "web/views/qij-v5.js",
        "web/dashboard/views/jellyfin.js",
        "web/dashboard/views/logs.js",
    ]

    def test_no_promise_all_in_migrated_files(self):
        root = Path(__file__).resolve().parent.parent
        for rel in self.EXPECTED_MIGRATED:
            src = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn("Promise.all(", src, f"{rel} : encore Promise.all !")
            self.assertIn("Promise.allSettled", src, f"{rel} : pas de Promise.allSettled !")


if __name__ == "__main__":
    unittest.main()
