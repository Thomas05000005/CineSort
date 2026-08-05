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


class _SidecarConfig(_DummyConfig):
    """`_DummyConfig` + le minimum requis par `classify_sidecars`."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.video_exts = {".mkv"}
        self.side_exts = {".srt", ".nfo"}
        self.generic_side_files = set()


class ApplyCollectionSidecarKillSwitchTests(unittest.TestCase):
    """Issue #661 — le kill-switch collection ignorait les SIDECARS.

    En collection les sidecars gardent leur nom source (`sub_dir/sidecar.name`) :
    une chaine de suffixes (.fr.forced.srt, .en.sdh.sup) produit couramment un
    chemin plus long que celui de la video. Le gate ne regardait que la video,
    donc l'item echouait EN COURS DE ROUTE (au premier move de sidecar) au lieu
    d'etre refuse en amont avec SKIP_PATH_TOO_LONG. La branche TV couvre ses
    sidecars depuis GATE 3 (TV-MAXPATH) : c'est cette asymetrie qu'on ferme.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_ks_coll_sc_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review = self.root / "_review"
        self.conflicts = self.review / "_conflicts"
        self.conflicts_sidecars = self.review / "_conflicts_sidecars"
        self.dup_identical = self.review / "_duplicates_identical"
        self.folder = self.root / "Saga"
        self.folder.mkdir()
        self.sub_dir = self.folder / "Inception (2010)"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _sidecar_name(self, target_len: int) -> str:
        """Nom de sidecar tel que `sub_dir/nom` fasse exactement `target_len`."""
        pad = target_len - (len(str(self.sub_dir)) + 1) - len("movie.") - len(".srt")
        self.assertGreater(pad, 0, "dossier temporaire trop long pour construire le cas")
        return "movie." + ("z" * pad) + ".srt"

    def _apply(self, *, dry_run: bool):
        res = core.ApplyResult()
        logs: list[tuple[str, str]] = []
        apply_collection_item(
            _SidecarConfig(self.root),
            self.folder,
            video_name="movie.mkv",
            title="Inception",
            year=2010,
            dry_run=dry_run,
            log=lambda level, msg: logs.append((level, msg)),
            res=res,
            conflicts_root=self.conflicts,
            conflicts_sidecars_root=self.conflicts_sidecars,
            duplicates_identical_root=self.dup_identical,
        )
        return res, logs

    def test_sidecar_trop_long_skip_avant_tout_deplacement(self):
        """Video courte + sidecar > 259 chars : skip propre, aucun move amorce."""
        video = self.folder / "movie.mkv"
        video.write_bytes(b"x" * 2048)
        sidecar_name = self._sidecar_name(265)
        sidecar = self.folder / sidecar_name
        sidecar.write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nbonjour\n")

        # Le cas doit isoler le sidecar : la video cible, elle, passe le gate.
        self.assertLessEqual(len(str(self.sub_dir / "movie.mkv")), 259, "la video ne doit PAS declencher le gate")
        self.assertGreater(len(str(self.sub_dir / sidecar_name)), 259, "le sidecar doit, lui, le declencher")

        res, logs = self._apply(dry_run=False)

        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            1,
            f"SKIP_REASON_PATH_TOO_LONG attendu pour un sidecar trop long: res={vars(res)}",
        )
        self.assertTrue(
            any("PATH_TOO_LONG" in str(m) for m in res.error_messages),
            f"error_messages doit porter PATH_TOO_LONG: {res.error_messages}",
        )
        self.assertTrue(
            any(level == "WARN" and "PATH_TOO_LONG" in msg for level, msg in logs),
            f"log WARN PATH_TOO_LONG attendu: {logs}",
        )
        # « proprement saute » : rien n'a bouge sur le disque.
        self.assertFalse(self.sub_dir.exists(), "le sous-dossier ne doit meme pas etre cree")
        self.assertTrue(video.exists(), "la video doit rester en source")
        self.assertTrue(sidecar.exists(), "le sidecar doit rester en source")
        self.assertEqual(res.moves, 0, "aucun deplacement ne doit avoir ete amorce")

    def test_sidecar_court_est_bien_deplace(self):
        """Non-regression : sidecar de longueur normale -> pas de gate, ET move reel.

        Le gate calcule desormais les cibles sidecars en amont et la boucle de
        move REUTILISE cette liste : ce test verifie qu'elle deplace toujours.
        """
        (self.folder / "movie.mkv").write_bytes(b"x" * 2048)
        (self.folder / "movie.fr.forced.srt").write_bytes(b"sous-titre")

        res, _logs = self._apply(dry_run=False)

        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0),
            0,
            f"faux positif du kill-switch sur un sidecar court: res={vars(res)}",
        )
        self.assertTrue((self.sub_dir / "movie.mkv").is_file(), "la video doit avoir ete deplacee")
        self.assertTrue(
            (self.sub_dir / "movie.fr.forced.srt").is_file(),
            f"le sidecar doit avoir ete deplace: {sorted(p.name for p in self.sub_dir.iterdir())}",
        )
        self.assertFalse((self.folder / "movie.fr.forced.srt").exists(), "plus rien en source")

    def test_video_trop_longue_skip_toujours(self):
        """Non-regression du gate historique (video seule) apres refonte."""
        (self.folder / "movie.mkv").write_bytes(b"x" * 2048)
        res = core.ApplyResult()
        apply_collection_item(
            _SidecarConfig(self.root),
            self.folder,
            video_name="movie.mkv",
            title="B" * 250,
            year=2010,
            dry_run=True,
            log=lambda _level, _msg: None,
            res=res,
            conflicts_root=self.conflicts,
            conflicts_sidecars_root=self.conflicts_sidecars,
            duplicates_identical_root=self.dup_identical,
        )
        self.assertEqual(res.skip_reasons.get(core.SKIP_REASON_PATH_TOO_LONG, 0), 1)


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
        """Serie au nom tres long : kill-switch declenche.

        Le levier etait le TITRE D'EPISODE tant que l'apply renommait le fichier
        en `SxxExx - Titre.ext`. Le fichier gardant desormais son nom source
        (regle inviolable n1), la longueur du chemin cible ne depend plus que du
        DOSSIER `Serie (annee)/Saison NN/` — c'est donc lui qu'on fait exploser.
        """
        folder = self.root / "Series"
        folder.mkdir()
        (folder / "episode.mkv").write_bytes(b"x" * 2048)

        # Nom de serie tres long pour exploser MAX_PATH sur le dossier cible.
        long_series = "C" * 250

        cfg = _DummyConfig(self.root)
        res = core.ApplyResult()
        logs = []

        def log(level, msg):
            logs.append((level, msg))

        row = self._make_row(tv_series_name=long_series, proposed_title=long_series)
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
