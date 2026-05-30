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
import unicodedata
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

    def _run_apply_single(self, folder: Path, title: str, year: int):
        """Helper : execute apply_single en dry_run sur un dossier et retourne
        (res, logs). Pas de mock du conformance check : on teste le vrai code.
        """
        cfg = _DummyConfig(self.root)
        res = self._make_apply_result()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        apply_single(
            cfg,
            folder,
            title=title,
            year=year,
            dry_run=True,
            log=log,
            res=res,
            conflicts_root=self.conflicts,
            conflicts_sidecars_root=self.conflicts_sidecars,
            duplicates_identical_root=self.dup_identical,
            leftovers_root=self.leftovers,
        )
        return res, logs

    def test_skip_when_src_equals_dst_strict(self):
        """Cas critique : folder == dst (chemins strictement identiques).
        Apres fix (Couches 1+2+3), le vrai code doit detecter src==dst et skipper
        SANS mock du conformance check.
        """
        folder_name = "12 Hommes en colere (1957)"
        folder = self.root / folder_name
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        res, logs = self._run_apply_single(folder, title="12 Hommes en colere", year=1957)

        # AUCUN rename ne doit etre comptabilise
        self.assertEqual(res.renames, 0, f"Rename inutile compte: logs={logs}")
        # Le folder doit etre marque skip (NOOP / deja conforme)
        self.assertGreaterEqual(res.skipped, 1, f"Skip attendu absent: res={vars(res)}")

    def test_skip_when_src_dst_differ_only_in_case(self):
        """Folder='12 Hommes en colere (1957)' / title='12 hommes en colere'.
        Sur Windows/SMB le filesystem est case-insensitive : le rename serait
        un noop physique. Le code doit le detecter et skipper.
        """
        folder_name = "12 Hommes en colere (1957)"
        folder = self.root / folder_name
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        # Title en minuscules -> dst calcule = "12 hommes en colere (1957)"
        # qui ne differe de src que par la casse.
        res, logs = self._run_apply_single(folder, title="12 hommes en colere", year=1957)

        self.assertEqual(
            res.renames,
            0,
            f"Rename case-only inutile compte: logs={logs}, res={vars(res)}",
        )
        self.assertGreaterEqual(res.skipped, 1, f"Skip attendu absent: res={vars(res)}")

    def test_skip_when_src_dst_differ_only_in_nfc_nfd(self):
        """Folder avec 'colere' en NFD (decomposed : e + combining grave)
        vs title 'colere' en NFC (precomposed). Equivalents sur FS, doit skipper.
        """
        # Forme NFC : "colere" avec e accentue precompose (U+00E8)
        title_nfc = unicodedata.normalize("NFC", "12 Hommes en colère")
        # Forme NFD : e + combining grave (U+0065 U+0300)
        folder_name_nfd = unicodedata.normalize(
            "NFD", "12 Hommes en colère (1957)"
        )
        # Verifications de pre-condition : les deux formes sont bien differentes
        # byte-a-byte mais equivalentes apres NFC.
        self.assertNotEqual(folder_name_nfd, "12 Hommes en colère (1957)")
        self.assertEqual(
            unicodedata.normalize("NFC", folder_name_nfd),
            "12 Hommes en colère (1957)",
        )

        folder = self.root / folder_name_nfd
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        res, logs = self._run_apply_single(folder, title=title_nfc, year=1957)

        self.assertEqual(
            res.renames,
            0,
            f"Rename NFC/NFD inutile compte: logs={logs}, res={vars(res)}",
        )
        self.assertGreaterEqual(res.skipped, 1, f"Skip attendu absent: res={vars(res)}")

    def test_skip_when_src_dst_differ_only_in_nbsp(self):
        """Folder avec U+00A0 (NBSP) vs title avec U+0020 (espace normal).
        Difference invisible pour l'oeil, equivalente apres normalisation
        whitespace. Doit skipper.
        """
        # Folder contient un NBSP entre "Hommes" et "en"
        folder_name = "12 Hommes en colere (1957)"
        title_with_space = "12 Hommes en colere"

        folder = self.root / folder_name
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        res, logs = self._run_apply_single(folder, title=title_with_space, year=1957)

        self.assertEqual(
            res.renames,
            0,
            f"Rename NBSP/space inutile compte: logs={logs}, res={vars(res)}",
        )
        self.assertGreaterEqual(res.skipped, 1, f"Skip attendu absent: res={vars(res)}")


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
