"""Fix audit 2026-05-25 (v1.5.5) Vague J : verifier que apply_single skip
le rename quand src == dst caractere par caractere.

Cas d'usage reel rapporte par l'utilisateur :

    Dossier renomme : \\\\OMV\\Media\\Films\\12 Hommes en colere (1957)
                  -> 12 Hommes en colere (1957)

Les 2 chemins sont strictement identiques mais le compteur "renames" et la
preview UI affichaient quand meme un "rename". Causes possibles :
  - normalisation Unicode (NFC vs NFD)
  - espaces speciaux (U+00A0 nbsp vs ' ')
  - template avec edition="" qui produit un nom different
  - _single_folder_is_conform qui retourne False sur un cas limite

Le fix : ajouter un guard explicite `if str(folder) == str(dst): skip` dans
apply_single, avant le bloc rename. Ce test verifie le comportement attendu.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
import cinesort.app.apply_core as apply_core
from cinesort.app.apply_core import apply_single
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done


class _DummyConfig:
    """Minimal Config stand-in pour apply_single (les helpers reels exigent un Config)."""

    def __init__(self, root: Path):
        self.root = root
        self.naming_movie_template = ""
        self.enable_collection_folder = False
        self.collection_root_name = "_Collection"


class ApplySkipIdenticalRenameTests(unittest.TestCase):
    """Test unitaire direct : apply_single ne doit jamais generer un rename
    quand source et destination sont strictement identiques."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_skip_ident_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review = self.root / "_review"
        self.conflicts = self.review / "_conflicts"
        self.conflicts_sidecars = self.review / "_conflicts_sidecars"
        self.dup_identical = self.review / "_duplicates_identical"
        self.leftovers = self.review / "_leftovers"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_apply_result(self):
        return core.ApplyResult()

    def test_skip_when_src_equals_dst_strict(self):
        """Cas critique : folder == dst (chemins strictement identiques)
        + _single_folder_is_conform forcee a False (simule un bug Unicode/template).
        Sans le fix Vague J, apply_single ferait quand meme un rename.
        """
        folder_name = "12 Hommes en colere (1957)"
        folder = self.root / folder_name
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        cfg = _DummyConfig(self.root)
        res = self._make_apply_result()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        # Force _single_folder_is_conform a retourner False pour reproduire
        # le cas du bug (Unicode/template subtil). apply_single doit malgre
        # tout detecter src==dst et skipper.
        with mock.patch.object(core, "_single_folder_is_conform", return_value=False):
            apply_single(
                cfg,
                folder,
                title="12 Hommes en colere",
                year=1957,
                dry_run=True,
                log=log,
                res=res,
                conflicts_root=self.conflicts,
                conflicts_sidecars_root=self.conflicts_sidecars,
                duplicates_identical_root=self.dup_identical,
                leftovers_root=self.leftovers,
            )

        # AUCUN rename ne doit etre comptabilise
        self.assertEqual(res.renames, 0, f"Rename inutile compte: logs={logs}")
        # Le folder doit etre marque skip (NOOP)
        self.assertGreaterEqual(res.skipped, 1, f"Skip attendu absent: res={vars(res)}")
        # Log de diagnostic NOOP present
        noop_logs = [m for _lvl, m in logs if "NOOP rename" in m]
        self.assertTrue(noop_logs, f"Log NOOP attendu manquant: {logs}")


class BuildPreviewSkipIdenticalRenameTests(unittest.TestCase):
    """Test end-to-end via build_apply_preview : 3 rows dont 2 avec src==dst
    -> totals.renames doit refleter UNIQUEMENT les vrais renommages."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_preview_skip_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_preview_does_not_count_rename_when_src_equals_dst(self):
        """3 films : 2 deja conformes (Title (Year)) + 1 a renommer.
        La preview ne doit signaler qu'1 seul rename, pas 3.
        """
        # Films deja au format conforme "Title (Year)"
        conformes = [
            ("Film Alpha (2010)", "Film Alpha", 2010),
            ("Film Beta (2011)", "Film Beta", 2011),
        ]
        # Film a renommer
        to_rename = ("Gamma.2012.1080p.BluRay", "Film Gamma", 2012)

        for folder_name, _t, _y in conformes:
            f = self.root / folder_name
            f.mkdir()
            (f / f"{folder_name}.mkv").write_bytes(b"x" * 2048)
        folder = self.root / to_rename[0]
        folder.mkdir()
        (folder / f"{to_rename[0]}.mkv").write_bytes(b"x" * 2048)

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"))
        run_id = start["run_id"]
        _wait_done(api, run_id)
        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), 3, f"Attendu 3 rows, eu {len(rows)}")

        # Decisions : on remappe chaque row sur son title/year cible pour
        # forcer la detection conform sur les 2 deja bien nommes.
        title_year_by_folder = {
            folder_name: (t, y) for folder_name, t, y in (*conformes, to_rename)
        }
        decisions = {}
        for r in rows:
            folder_name = Path(r["folder"]).name
            t, y = title_year_by_folder.get(folder_name, (r["proposed_title"], r["proposed_year"]))
            decisions[r["row_id"]] = {"ok": True, "title": t, "year": y}

        preview = api.run.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"), preview)

        totals = preview.get("totals", {})
        # Au plus 1 rename (le Gamma -> Film Gamma (2012)). Les 2 conformes
        # ne doivent PAS compter.
        self.assertLessEqual(
            int(totals.get("renames", 0)),
            1,
            f"Trop de renames comptes: totals={totals}",
        )

    def test_preview_skip_when_target_exactly_matches_source(self):
        """Cas extreme : un film deja nomme exactement comme la cible
        (Title (Year)). Apply_single doit detecter conform OU src==dst
        et skipper. Aucun rename comptabilise.
        """
        folder_name = "Inception (2010)"
        folder = self.root / folder_name
        folder.mkdir()
        (folder / "Inception.mkv").write_bytes(b"x" * 2048)

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"))
        run_id = start["run_id"]
        _wait_done(api, run_id)
        rows = api.run.get_plan(run_id).get("rows", [])
        self.assertTrue(rows)
        decisions = {
            r["row_id"]: {"ok": True, "title": "Inception", "year": 2010}
            for r in rows
        }
        preview = api.run.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"))
        self.assertEqual(
            int(preview.get("totals", {}).get("renames", 0)),
            0,
            f"Rename inutile sur dossier deja conforme: totals={preview.get('totals')}",
        )


if __name__ == "__main__":
    unittest.main()
