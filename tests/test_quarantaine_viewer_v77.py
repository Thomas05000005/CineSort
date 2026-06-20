"""VQ-2 QUARANTAINE-TTL v7.7.0 — tests viewer du bucket `_review`.

Couvre `list_review_bucket_files` :
- bucket absent : ok exists=False, files_count=0
- bucket vide : ok exists=True, files_count=0
- inventaire complet : count, total_size_bytes, by_subdir
- tri files par mtime DESC
- limit tronque la liste
- age_days calcule
- subdir detecte (_conflicts, _conflicts_sidecars, _duplicates_identical,
  _leftovers, _duplicates_user_decided, _top_quarantine pour fichier au top-level)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import json

from cinesort.app.quarantine_ttl import _TTL_MANIFEST_NAME, list_review_bucket_files


def _make_cfg(root: Path) -> SimpleNamespace:
    return SimpleNamespace(root=root)


def _set_mtime(p: Path, days_ago: float) -> None:
    ts = time.time() - (days_ago * 86400.0)
    os.utime(p, (ts, ts))


def _seed_arrival(root: Path, rel: str, days_ago: float) -> None:
    """Inscrit la date d'ENTREE en quarantaine dans le manifest (AUDIT 2026-06-10 :
    age_days et tri reposent desormais sur l'arrivee, plus sur le mtime)."""
    manifest_path = root / "_review" / _TTL_MANIFEST_NAME
    data = {}
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data[rel] = time.time() - (days_ago * 86400.0)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")


def _write_file(
    p: Path, content: bytes = b"x" * 100, days_ago: float = 0.0, *, root: Path = None
) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    if days_ago > 0:
        _set_mtime(p, days_ago)
        if root is not None:
            rel = p.relative_to(root / "_review").as_posix()
            _seed_arrival(root, rel, days_ago)
    return p


class ListReviewBucketFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_vq2_viewer_")
        self.root = Path(self._tmp)
        self.cfg = _make_cfg(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_bucket_returns_exists_false(self) -> None:
        res = list_review_bucket_files(self.cfg)
        self.assertTrue(res["ok"])
        self.assertFalse(res["exists"])
        self.assertEqual(res["files_count"], 0)
        self.assertEqual(res["total_size_bytes"], 0)
        self.assertEqual(res["files"], [])

    def test_empty_bucket(self) -> None:
        (self.root / "_review").mkdir()
        res = list_review_bucket_files(self.cfg)
        self.assertTrue(res["ok"])
        self.assertTrue(res["exists"])
        self.assertEqual(res["files_count"], 0)
        self.assertEqual(res["files"], [])

    def test_inventory_counts_and_sizes(self) -> None:
        _write_file(self.root / "_review" / "_conflicts" / "a.bin", content=b"x" * 100)
        _write_file(self.root / "_review" / "_conflicts" / "b.bin", content=b"x" * 200)
        _write_file(self.root / "_review" / "_leftovers" / "c.bin", content=b"x" * 50)
        res = list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 3)
        self.assertEqual(res["total_size_bytes"], 350)
        self.assertIn("_conflicts", res["by_subdir"])
        self.assertEqual(res["by_subdir"]["_conflicts"]["count"], 2)
        self.assertEqual(res["by_subdir"]["_conflicts"]["size"], 300)
        self.assertEqual(res["by_subdir"]["_leftovers"]["count"], 1)
        self.assertEqual(res["by_subdir"]["_leftovers"]["size"], 50)

    def test_files_sorted_by_arrival_desc(self) -> None:
        # Tri par date d'ENTREE en quarantaine DESC (recent en haut).
        _write_file(self.root / "_review" / "_conflicts" / "old.bin", days_ago=10, root=self.root)
        _write_file(self.root / "_review" / "_conflicts" / "mid.bin", days_ago=5, root=self.root)
        _write_file(self.root / "_review" / "_conflicts" / "new.bin", days_ago=1, root=self.root)
        res = list_review_bucket_files(self.cfg)
        # arrivee decroissante : new (1j) > mid (5j) > old (10j)
        self.assertEqual(res["files"][0]["rel"], "_conflicts/new.bin")
        self.assertEqual(res["files"][1]["rel"], "_conflicts/mid.bin")
        self.assertEqual(res["files"][2]["rel"], "_conflicts/old.bin")

    def test_limit_truncates_files_list(self) -> None:
        for i in range(10):
            _write_file(self.root / "_review" / "_conflicts" / f"f{i:02d}.bin")
        res = list_review_bucket_files(self.cfg, limit=3)
        self.assertEqual(res["files_count"], 10)  # total reel
        self.assertEqual(len(res["files"]), 3)  # tronque

    def test_age_days_computed(self) -> None:
        # age_days = temps EN QUARANTAINE (depuis l'arrivee), pas l'age du fichier.
        _write_file(self.root / "_review" / "_conflicts" / "x.bin", days_ago=15.0, root=self.root)
        res = list_review_bucket_files(self.cfg)
        self.assertEqual(len(res["files"]), 1)
        age = res["files"][0]["age_days"]
        # Marge de tolerance (le test s'execute donc fenetre entre lecture et stat)
        self.assertGreater(age, 14.5)
        self.assertLess(age, 16.0)

    def test_age_days_uses_arrival_not_mtime(self) -> None:
        # GATE AUDIT 2026-06-10 : un fichier au mtime tres ancien mais arrive a
        # l'instant affiche age_days ~ 0 (et non l'age du fichier).
        f = self.root / "_review" / "_conflicts" / "vieux.mkv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 100)
        _set_mtime(f, 400)  # mtime 400j, AUCUN seed d'arrivee
        res = list_review_bucket_files(self.cfg)
        self.assertEqual(len(res["files"]), 1)
        self.assertLess(res["files"][0]["age_days"], 1.0)

    def test_subdir_top_quarantine_for_top_level_file(self) -> None:
        # Un fichier directement sous `_review/` (rare mais possible).
        _write_file(self.root / "_review" / "orphan.bin")
        res = list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 1)
        self.assertEqual(res["files"][0]["subdir"], "_top_quarantine")
        self.assertIn("_top_quarantine", res["by_subdir"])

    def test_subdir_identified_for_nested_dirs(self) -> None:
        # `_review/MyFilm (2020)/movie.mkv` -> subdir="MyFilm (2020)"
        _write_file(self.root / "_review" / "MyFilm (2020)" / "movie.mkv")
        res = list_review_bucket_files(self.cfg)
        self.assertEqual(res["files_count"], 1)
        self.assertEqual(res["files"][0]["subdir"], "MyFilm (2020)")
        self.assertIn("MyFilm (2020)", res["by_subdir"])

    def test_all_known_subdirs_recognized(self) -> None:
        for sub in ("_conflicts", "_conflicts_sidecars", "_duplicates_identical",
                    "_duplicates_user_decided", "_leftovers"):
            _write_file(self.root / "_review" / sub / "f.bin")
        res = list_review_bucket_files(self.cfg)
        for sub in ("_conflicts", "_conflicts_sidecars", "_duplicates_identical",
                    "_duplicates_user_decided", "_leftovers"):
            self.assertIn(sub, res["by_subdir"])
            self.assertEqual(res["by_subdir"][sub]["count"], 1)

    def test_relative_path_format(self) -> None:
        _write_file(self.root / "_review" / "_conflicts" / "nested" / "deep.bin")
        res = list_review_bucket_files(self.cfg)
        # rel doit utiliser un separateur POSIX (`/`) meme sur Windows.
        self.assertEqual(res["files"][0]["rel"], "_conflicts/nested/deep.bin")


class SaveSectionAdvancedQuarantineTtlTests(unittest.TestCase):
    """VQ-2 : verifie que `quarantaine_ttl_days` passe par _save_section_advanced
    sans etre droppe silencieusement (regression cf fix audit 2026-05-24)."""

    def test_quarantaine_ttl_days_persisted(self) -> None:
        from cinesort.ui.api.settings_support import _save_section_advanced

        out = _save_section_advanced({"quarantaine_ttl_days": 45})
        self.assertEqual(out.get("quarantaine_ttl_days"), 45)

    def test_quarantaine_ttl_days_clamped_high(self) -> None:
        from cinesort.ui.api.settings_support import _save_section_advanced

        out = _save_section_advanced({"quarantaine_ttl_days": 99999})
        self.assertEqual(out.get("quarantaine_ttl_days"), 3650)

    def test_quarantaine_ttl_days_clamped_low(self) -> None:
        from cinesort.ui.api.settings_support import _save_section_advanced

        out = _save_section_advanced({"quarantaine_ttl_days": -10})
        self.assertEqual(out.get("quarantaine_ttl_days"), 0)

    def test_quarantaine_ttl_days_zero_means_disabled(self) -> None:
        from cinesort.ui.api.settings_support import _save_section_advanced

        out = _save_section_advanced({"quarantaine_ttl_days": 0})
        self.assertEqual(out.get("quarantaine_ttl_days"), 0)

    def test_quarantaine_ttl_days_not_in_payload(self) -> None:
        """Si pas dans payload, ne doit pas apparaitre dans out."""
        from cinesort.ui.api.settings_support import _save_section_advanced

        out = _save_section_advanced({})
        self.assertNotIn("quarantaine_ttl_days", out)


if __name__ == "__main__":
    unittest.main()
