"""V2-04 — verifie qu'aucune des 9 vues migrees ne reste sur Promise.all (audit ID-ROB-002)."""

from pathlib import Path
import unittest


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
