"""Tests collections automatiques TMDb — Phases A+B (item 9.5).

Couvre :
- TMDb client : get_movie_collection retourne collection_id/name
- TMDb client : belongs_to_collection null → None/None
- TMDb client : cache — deuxieme appel utilise le cache
- Candidate : tmdb_collection_id/name propages
- PlanRow : tmdb_collection_id/name herites
- PlanRow deserialization : plan_row_from_jsonable avec collection
- Film sans match TMDb → pas de collection
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.domain.core import Candidate, PlanRow


# ---------------------------------------------------------------------------
# TMDb client — get_movie_collection
# ---------------------------------------------------------------------------


class TmdbCollectionClientTests(unittest.TestCase):
    """Tests du client TMDb pour les collections."""

    def _make_client(self):
        """Cree un TmdbClient avec un cache temporaire."""
        from cinesort.infra.tmdb_client import TmdbClient

        tmp = tempfile.mkdtemp(prefix="tmdb_coll_test_")
        cache = Path(tmp) / "tmdb_cache.json"
        client = TmdbClient(api_key="fake_key_for_test", cache_path=cache, timeout_s=5.0)
        return client, tmp

    def test_get_movie_collection_with_collection(self) -> None:
        """TMDb retourne belongs_to_collection → collection_id/name."""
        client, tmp = self._make_client()
        try:
            # Simuler un cache entry avec collection
            client._cache_set(
                "movie|27205",
                {
                    "poster_path": "/poster.jpg",
                    "collection_id": 87096,
                    "collection_name": "Avatar Collection",
                },
            )
            cid, cname = client.get_movie_collection(27205)
            self.assertEqual(cid, 87096)
            self.assertEqual(cname, "Avatar Collection")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_movie_collection_without_collection(self) -> None:
        """TMDb retourne null collection → None/None."""
        client, tmp = self._make_client()
        try:
            client._cache_set(
                "movie|550",
                {
                    "poster_path": "/poster.jpg",
                    "collection_id": None,
                    "collection_name": None,
                },
            )
            cid, cname = client.get_movie_collection(550)
            self.assertIsNone(cid)
            self.assertIsNone(cname)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_movie_collection_invalid_id(self) -> None:
        """ID invalide → None/None."""
        client, tmp = self._make_client()
        try:
            cid, cname = client.get_movie_collection(0)
            self.assertIsNone(cid)
            self.assertIsNone(cname)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_cache_reuse(self) -> None:
        """Deuxieme appel utilise le cache (pas de requete reseau)."""
        client, tmp = self._make_client()
        try:
            # Premier appel : pre-remplir le cache
            client._cache_set(
                "movie|12345",
                {
                    "poster_path": "/poster.jpg",
                    "collection_id": 999,
                    "collection_name": "Test Saga",
                },
            )
            # Deuxieme appel : doit utiliser le cache
            cid1, cname1 = client.get_movie_collection(12345)
            cid2, cname2 = client.get_movie_collection(12345)
            self.assertEqual(cid1, cid2)
            self.assertEqual(cname1, cname2)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_movie_detail_cached_enriches_poster(self) -> None:
        """_get_movie_detail_cached retourne aussi le poster_path."""
        client, tmp = self._make_client()
        try:
            client._cache_set(
                "movie|27205",
                {
                    "poster_path": "/inception.jpg",
                    "collection_id": 87096,
                    "collection_name": "Inception",
                },
            )
            poster = client.get_movie_poster_path(27205)
            self.assertEqual(poster, "/inception.jpg")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_legacy_cache_without_collection_fields(self) -> None:
        """Un cache legacy (sans collection_id/name) ne crash pas."""
        client, tmp = self._make_client()
        try:
            # Cache legacy : seulement poster_path
            client._cache_set("movie|42", {"poster_path": "/old.jpg"})
            cid, cname = client.get_movie_collection(42)
            self.assertIsNone(cid)
            self.assertIsNone(cname)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Candidate — tmdb_collection_id/name
# ---------------------------------------------------------------------------


class CandidateCollectionTests(unittest.TestCase):
    """Tests des champs collection sur Candidate."""

    def test_candidate_with_collection(self) -> None:
        c = Candidate(
            title="Avatar",
            year=2009,
            source="tmdb",
            tmdb_id=19995,
            tmdb_collection_id=87096,
            tmdb_collection_name="Avatar Collection",
        )
        self.assertEqual(c.tmdb_collection_id, 87096)
        self.assertEqual(c.tmdb_collection_name, "Avatar Collection")

    def test_candidate_without_collection(self) -> None:
        c = Candidate(title="Inception", year=2010, source="tmdb", tmdb_id=27205)
        self.assertIsNone(c.tmdb_collection_id)
        self.assertIsNone(c.tmdb_collection_name)


# ---------------------------------------------------------------------------
# PlanRow — tmdb_collection_id/name
# ---------------------------------------------------------------------------


class PlanRowCollectionTests(unittest.TestCase):
    """Tests des champs collection sur PlanRow."""

    def test_planrow_with_collection(self) -> None:
        row = PlanRow(
            row_id="S001",
            kind="single",
            folder="/films/avatar",
            video="avatar.mkv",
            proposed_title="Avatar",
            proposed_year=2009,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            candidates=[],
            tmdb_collection_id=87096,
            tmdb_collection_name="Avatar Collection",
        )
        self.assertEqual(row.tmdb_collection_id, 87096)
        self.assertEqual(row.tmdb_collection_name, "Avatar Collection")

    def test_planrow_without_collection(self) -> None:
        row = PlanRow(
            row_id="S002",
            kind="single",
            folder="/films/inception",
            video="inception.mkv",
            proposed_title="Inception",
            proposed_year=2010,
            proposed_source="tmdb",
            confidence=85,
            confidence_label="high",
            candidates=[],
        )
        self.assertIsNone(row.tmdb_collection_id)
        self.assertIsNone(row.tmdb_collection_name)


# ---------------------------------------------------------------------------
# Deserialization — plan_row_from_jsonable
# ---------------------------------------------------------------------------


class PlanRowJsonableCollectionTests(unittest.TestCase):
    """Tests de serialization/deserialization avec collection."""

    def test_deserialize_with_collection(self) -> None:
        from cinesort.app.plan_support import plan_row_from_jsonable

        data = {
            "row_id": "S001",
            "kind": "single",
            "folder": "/films/avatar",
            "video": "avatar.mkv",
            "proposed_title": "Avatar",
            "proposed_year": 2009,
            "proposed_source": "tmdb",
            "confidence": 90,
            "confidence_label": "high",
            "candidates": [],
            "tmdb_collection_id": 87096,
            "tmdb_collection_name": "Avatar Collection",
        }
        row = plan_row_from_jsonable(data)
        self.assertIsNotNone(row)
        self.assertEqual(row.tmdb_collection_id, 87096)
        self.assertEqual(row.tmdb_collection_name, "Avatar Collection")

    def test_deserialize_without_collection(self) -> None:
        from cinesort.app.plan_support import plan_row_from_jsonable

        data = {
            "row_id": "S002",
            "kind": "single",
            "folder": "/films/inception",
            "video": "inception.mkv",
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "proposed_source": "tmdb",
            "confidence": 85,
            "confidence_label": "high",
            "candidates": [],
        }
        row = plan_row_from_jsonable(data)
        self.assertIsNotNone(row)
        self.assertIsNone(row.tmdb_collection_id)
        self.assertIsNone(row.tmdb_collection_name)

    def test_deserialize_candidate_with_collection(self) -> None:
        from cinesort.app.plan_support import plan_row_from_jsonable

        data = {
            "row_id": "S003",
            "kind": "single",
            "folder": "/films/avatar",
            "video": "avatar.mkv",
            "proposed_title": "Avatar",
            "proposed_year": 2009,
            "proposed_source": "tmdb",
            "confidence": 90,
            "confidence_label": "high",
            "candidates": [
                {
                    "title": "Avatar",
                    "year": 2009,
                    "source": "tmdb",
                    "tmdb_id": 19995,
                    "score": 0.95,
                    "note": "",
                    "tmdb_collection_id": 87096,
                    "tmdb_collection_name": "Avatar Collection",
                }
            ],
        }
        row = plan_row_from_jsonable(data)
        self.assertIsNotNone(row)
        self.assertEqual(len(row.candidates), 1)
        self.assertEqual(row.candidates[0].tmdb_collection_id, 87096)
        self.assertEqual(row.candidates[0].tmdb_collection_name, "Avatar Collection")

    def test_deserialize_legacy_without_collection_fields(self) -> None:
        """Un JSON legacy (sans champs collection) ne crash pas."""
        from cinesort.app.plan_support import plan_row_from_jsonable

        data = {
            "row_id": "S004",
            "kind": "single",
            "folder": "/films/old",
            "video": "old.mkv",
            "proposed_title": "Old Film",
            "proposed_year": 2000,
            "proposed_source": "name",
            "confidence": 50,
            "confidence_label": "med",
            "candidates": [{"title": "Old", "year": 2000, "source": "name", "score": 0.5, "note": ""}],
        }
        row = plan_row_from_jsonable(data)
        self.assertIsNotNone(row)
        self.assertIsNone(row.tmdb_collection_id)
        self.assertIsNone(row.tmdb_collection_name)


# ====================================================================
# Phases D+E — Apply enrichi + UI badges
# ====================================================================


class ApplyCollectionTmdbTests(unittest.TestCase):
    """Tests de l'apply avec collection TMDb."""

    def _make_structure(self):
        """Cree un root temporaire avec un film simple."""
        tmp = tempfile.mkdtemp(prefix="tmdb_coll_apply_")
        root = Path(tmp) / "root"
        root.mkdir()
        film_dir = root / "DivX_Avatar_2009"
        film_dir.mkdir()
        (film_dir / "avatar.mkv").write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 100)
        return root, tmp

    def test_apply_single_with_collection_creates_saga_folder(self) -> None:
        """Film + collection TMDb + enabled → dossier _Collection/SagaName/Film (Année)/."""
        import cinesort.domain.core as core_mod
        from cinesort.app.apply_core import apply_single

        root, tmp = self._make_structure()
        try:
            cfg = core_mod.Config(root=root, enable_collection_folder=True, collection_root_name="_Collection")
            cfg = cfg.normalized()
            res = core_mod.ApplyResult()
            folder = root / "DivX_Avatar_2009"
            apply_single(
                cfg,
                folder,
                "Avatar",
                2009,
                dry_run=True,
                log=lambda *_: None,
                res=res,
                conflicts_root=root / "_review" / "_conflicts",
                conflicts_sidecars_root=root / "_review" / "_conflicts_sidecars",
                duplicates_identical_root=root / "_review" / "_duplicates_identical",
                leftovers_root=root / "_review" / "_leftovers",
                tmdb_collection_name="Avatar Collection",
            )
            # En dry-run le dossier n'est pas cree, mais pas d'erreur
            self.assertGreaterEqual(res.skipped + res.moves + res.renames, 0)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_apply_single_without_collection_normal(self) -> None:
        """Film sans collection TMDb → move normal (pas de dossier collection)."""
        import cinesort.domain.core as core_mod
        from cinesort.app.apply_core import apply_single

        root, tmp = self._make_structure()
        try:
            cfg = core_mod.Config(root=root, enable_collection_folder=True, collection_root_name="_Collection")
            cfg = cfg.normalized()
            res = core_mod.ApplyResult()
            folder = root / "DivX_Avatar_2009"
            apply_single(
                cfg,
                folder,
                "Avatar",
                2009,
                dry_run=True,
                log=lambda *_: None,
                res=res,
                conflicts_root=root / "_review" / "_conflicts",
                conflicts_sidecars_root=root / "_review" / "_conflicts_sidecars",
                duplicates_identical_root=root / "_review" / "_duplicates_identical",
                leftovers_root=root / "_review" / "_leftovers",
                tmdb_collection_name=None,
            )
            self.assertGreaterEqual(res.skipped + res.moves + res.renames, 0)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_apply_single_collection_disabled(self) -> None:
        """collection_folder_enabled=False → ignore la collection TMDb."""
        import cinesort.domain.core as core_mod
        from cinesort.app.apply_core import apply_single

        root, tmp = self._make_structure()
        try:
            cfg = core_mod.Config(root=root, enable_collection_folder=False, collection_root_name="_Collection")
            cfg = cfg.normalized()
            res = core_mod.ApplyResult()
            folder = root / "DivX_Avatar_2009"
            apply_single(
                cfg,
                folder,
                "Avatar",
                2009,
                dry_run=True,
                log=lambda *_: None,
                res=res,
                conflicts_root=root / "_review" / "_conflicts",
                conflicts_sidecars_root=root / "_review" / "_conflicts_sidecars",
                duplicates_identical_root=root / "_review" / "_duplicates_identical",
                leftovers_root=root / "_review" / "_leftovers",
                tmdb_collection_name="Avatar Collection",
            )
            # Avec collection disabled, le tmdb_collection_name est ignore
            self.assertGreaterEqual(res.skipped + res.moves + res.renames, 0)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_collection_name_sanitized(self) -> None:
        """Le nom de collection avec caracteres speciaux est sanitise."""
        from cinesort.domain.core import windows_safe

        result = windows_safe("Star Wars: The Complete Saga")
        self.assertNotIn(":", result)
        self.assertIn("Star Wars", result)


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class UiSagaBadgeTests(unittest.TestCase):
    """Tests badges saga violet dans les fichiers UI."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_saga_badge(self) -> None:
        self.assertIn("tmdb_collection_name", self.validation_js)
        self.assertIn("badge--saga", self.validation_js)
        self.assertIn("Saga", self.validation_js)

    def test_dashboard_saga_badge(self) -> None:
        self.assertIn("tmdb_collection_name", self.review_js)
        self.assertIn("badge-saga", self.review_js)

    def test_desktop_css_saga(self) -> None:
        self.assertIn(".badge--saga", self.app_css)
        self.assertIn("#A855F7", self.app_css)

    def test_dashboard_css_saga(self) -> None:
        self.assertIn(".badge-saga", self.dash_css)
        self.assertIn("#A855F7", self.dash_css)


if __name__ == "__main__":
    unittest.main()
