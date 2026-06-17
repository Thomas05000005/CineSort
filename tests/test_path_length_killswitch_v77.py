"""VQ-3 : tests du kill-switch MAX_PATH Windows pour apply_single / apply_collection_item / apply_tv_episode.

Avant ce cablage la fonction `check_path_length` etait orpheline (3 tests
unitaires sur naming.py, ZERO caller production). Quand un dossier produisait
un path cible > 260 chars sur Windows, le rename/move generait un OSError
obscur "Le chemin specifie est introuvable" ou un rename partiel laissant
le FS dans un etat incoherent.

Apres VQ-3 :
- Nouvelle fonction `check_path_length_killswitch(target_path)` dans naming.py
  retourne un message d'erreur explicite si target_path > 259 chars.
- Nouveau `SKIP_REASON_PATH_TOO_LONG` ajoute dans domain/core.py.
- 3 callsites cables dans app/apply_core.py : apply_single, apply_collection_item,
  apply_tv_episode -> SKIP propre + log WARN + error_messages.

Backward compat ABSOLUE : tout path <= 259 chars passe sans changement.
Seuls les paths anormalement longs (cas pathologiques rare) sont skips.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.apply_core import apply_collection_item, apply_single, apply_tv_episode
from cinesort.domain.naming import check_path_length_killswitch


class _DummyConfig:
    """Minimal Config stand-in pour apply_* (les helpers reels exigent un Config)."""

    def __init__(self, root: Path):
        self.root = root
        # Template court pour reproduire des paths longs sans gonfler artificiellement
        self.naming_movie_template = "{title} ({year})"
        self.naming_tv_template = "{series} ({year})"
        self.enable_collection_folder = False
        self.collection_root_name = "_Collection"


class CheckPathLengthKillSwitchUnitTests(unittest.TestCase):
    """Tests unitaires de la fonction check_path_length_killswitch."""

    def test_short_path_returns_none(self):
        """Path normal : None (backward compat : aucun changement)."""
        result = check_path_length_killswitch("D:\\Films\\Inception (2010)\\Inception.mkv")
        self.assertIsNone(result)

    def test_path_exactly_259_chars_returns_none(self):
        """259 chars = limite OK (kill-switch declenche a 260+)."""
        # On construit un path exactement 259 chars
        path = "D:\\" + ("A" * 256)
        self.assertEqual(len(path), 259)
        result = check_path_length_killswitch(path)
        self.assertIsNone(result)

    def test_path_260_chars_triggers_killswitch(self):
        """260 chars = MAX_PATH Windows : kill-switch DOIT declencher."""
        path = "D:\\" + ("A" * 257)
        self.assertEqual(len(path), 260)
        result = check_path_length_killswitch(path)
        self.assertIsNotNone(result)
        self.assertIn("PATH_TOO_LONG", result)
        self.assertIn("260", result)

    def test_path_pathologique_500_chars_triggers_killswitch(self):
        """Path tres long (cas anime episode title pathologique)."""
        path = "D:\\Series\\" + ("X" * 500)
        result = check_path_length_killswitch(path)
        self.assertIsNotNone(result)
        self.assertIn("PATH_TOO_LONG", result)


class ApplySingleKillSwitchTests(unittest.TestCase):
    """Verifier que apply_single skip proprement quand le path cible > 259 chars."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_killswitch_single_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review = self.root / "_review"
        self.conflicts = self.review / "_conflicts"
        self.conflicts_sidecars = self.review / "_conflicts_sidecars"
        self.dup_identical = self.review / "_duplicates_identical"
        self.leftovers = self.review / "_leftovers"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, folder: Path, title: str, year: int):
        cfg = _DummyConfig(self.root)
        res = core.ApplyResult()
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

    def test_path_court_passe_normalement(self):
        """Backward compat : path court genere un rename comme avant."""
        folder = self.root / "OldName (2010)"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        res, _logs = self._run(folder, title="Inception", year=2010)

        # Le rename est compte (path court, aucun blocage)
        # Note : selon les autres garde-fous (NOOP conform), res.renames peut etre 0 ou 1
        # mais SURTOUT : aucun SKIP_REASON_PATH_TOO_LONG ne doit apparaitre
        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            0,
            f"Faux positif kill-switch sur path court: res={vars(res)}",
        )

    def test_path_trop_long_declenche_kill_switch(self):
        """Path cible > 259 chars : SKIP propre avec SKIP_REASON_PATH_TOO_LONG."""
        # On construit un title qui force un dst > 259 chars
        # root tmpdir fait deja ~50-70 chars, on ajoute 250 chars de title
        long_title = "A" * 250
        folder = self.root / "OldName"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        res, logs = self._run(folder, title=long_title, year=2010)

        # Le skip doit etre marque
        self.assertGreaterEqual(res.skipped, 1, f"Skip attendu absent: res={vars(res)}")
        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            1,
            f"SKIP_REASON_PATH_TOO_LONG attendu: res={vars(res)}",
        )
        # Aucun rename ne doit etre compte (kill-switch declenche avant)
        self.assertEqual(res.renames, 0, f"Rename indu malgre kill-switch: res={vars(res)}")
        # Le message d'erreur doit etre remonte a l'UI
        self.assertTrue(
            any("PATH_TOO_LONG" in str(m) for m in res.error_messages),
            f"error_messages doit contenir PATH_TOO_LONG: {res.error_messages}",
        )
        # Un log WARN doit avoir ete emis
        self.assertTrue(
            any(level == "WARN" and "PATH_TOO_LONG" in msg for level, msg in logs),
            f"Log WARN PATH_TOO_LONG attendu: {logs}",
        )


class ApplyCollectionItemKillSwitchTests(unittest.TestCase):
    """Verifier que apply_collection_item skip quand sub_dir/video.name > 259 chars."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_killswitch_coll_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review = self.root / "_review"
        self.conflicts = self.review / "_conflicts"
        self.conflicts_sidecars = self.review / "_conflicts_sidecars"
        self.dup_identical = self.review / "_duplicates_identical"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_collection_path_trop_long_skip(self):
        """Collection item avec title long : kill-switch declenche."""
        long_title = "B" * 250
        folder = self.root / "Saga"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        cfg = _DummyConfig(self.root)
        res = core.ApplyResult()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        apply_collection_item(
            cfg,
            folder,
            video_name="movie.mkv",
            title=long_title,
            year=2010,
            dry_run=True,
            log=log,
            res=res,
            conflicts_root=self.conflicts,
            conflicts_sidecars_root=self.conflicts_sidecars,
            duplicates_identical_root=self.dup_identical,
        )

        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            1,
            f"SKIP_REASON_PATH_TOO_LONG attendu en collection: res={vars(res)}",
        )
        self.assertTrue(
            any("PATH_TOO_LONG" in str(m) for m in res.error_messages),
            f"error_messages doit contenir PATH_TOO_LONG: {res.error_messages}",
        )

    def test_collection_path_court_passe(self):
        """Backward compat : path court collection passe sans kill-switch."""
        folder = self.root / "Saga"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        cfg = _DummyConfig(self.root)
        res = core.ApplyResult()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        apply_collection_item(
            cfg,
            folder,
            video_name="movie.mkv",
            title="Inception",
            year=2010,
            dry_run=True,
            log=log,
            res=res,
            conflicts_root=self.conflicts,
            conflicts_sidecars_root=self.conflicts_sidecars,
            duplicates_identical_root=self.dup_identical,
        )

        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            0,
            f"Faux positif kill-switch sur collection courte: res={vars(res)}",
        )


class ApplyTvEpisodeKillSwitchTests(unittest.TestCase):
    """Verifier que apply_tv_episode skip quand target_file > 259 chars."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_killswitch_tv_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_row(self, **overrides):
        """Construit un PlanRow minimal pour apply_tv_episode."""

        class _Row:
            video = "episode.mkv"
            proposed_title = "Series"
            proposed_year = 2020
            tv_season = 1
            tv_episode = 1
            tv_episode_title = ""
            tv_series_name = "Series"
            row_id = "test"

        row = _Row()
        for k, v in overrides.items():
            setattr(row, k, v)
        return row

    def test_tv_path_trop_long_skip(self):
        """Episode TV avec titre tres long : kill-switch declenche."""
        folder = self.root / "Series"
        folder.mkdir()
        (folder / "episode.mkv").write_bytes(b"x" * 2048)

        # Episode title tres long pour exploser MAX_PATH
        long_ep_title = "C" * 250

        cfg = _DummyConfig(self.root)
        res = core.ApplyResult()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        row = self._make_row(tv_episode_title=long_ep_title)
        apply_tv_episode(
            cfg,
            folder,
            row,
            dry_run=True,
            log=log,
            res=res,
            conflicts_root=self.root / "_review" / "_conflicts",
            conflicts_sidecars_root=self.root / "_review" / "_conflicts_sidecars",
            duplicates_identical_root=self.root / "_review" / "_duplicates_identical",
        )

        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            1,
            f"SKIP_REASON_PATH_TOO_LONG attendu en TV: res={vars(res)}",
        )
        self.assertEqual(res.moves, 0, f"Move indu malgre kill-switch TV: res={vars(res)}")
        self.assertTrue(
            any("PATH_TOO_LONG" in str(m) for m in res.error_messages),
            f"error_messages doit contenir PATH_TOO_LONG: {res.error_messages}",
        )

    def test_tv_path_court_passe(self):
        """Backward compat : episode TV court passe sans kill-switch."""
        folder = self.root / "Series"
        folder.mkdir()
        (folder / "episode.mkv").write_bytes(b"x" * 2048)

        cfg = _DummyConfig(self.root)
        res = core.ApplyResult()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        row = self._make_row(tv_episode_title="Pilot")
        apply_tv_episode(
            cfg,
            folder,
            row,
            dry_run=True,
            log=log,
            res=res,
            conflicts_root=self.root / "_review" / "_conflicts",
            conflicts_sidecars_root=self.root / "_review" / "_conflicts_sidecars",
            duplicates_identical_root=self.root / "_review" / "_duplicates_identical",
        )

        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            0,
            f"Faux positif kill-switch sur TV courte: res={vars(res)}",
        )


class SkipReasonLabelTests(unittest.TestCase):
    """Verifier que le label FR est exporte pour l'UI."""

    def test_skip_reason_constant_exists(self):
        self.assertTrue(hasattr(core, "SKIP_REASON_PATH_TOO_LONG"))
        self.assertEqual(core.SKIP_REASON_PATH_TOO_LONG, "skip_path_too_long")

    def test_skip_reason_label_fr_exists(self):
        self.assertIn(core.SKIP_REASON_PATH_TOO_LONG, core.SKIP_REASON_LABELS_FR)
        label = core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_PATH_TOO_LONG]
        self.assertIn("Chemin", label)


if __name__ == "__main__":
    unittest.main()
