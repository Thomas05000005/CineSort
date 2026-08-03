"""Issue #796 — le pre-check espace disque doit etre RECURSIF comme l'apply.

`_row_estimated_size` ne sommait que la couche immediate d'un dossier, alors que
l'apply reel parcourt `src_dir.rglob("*")` (`merge_dir_safe`, apply_core.py:905)
et qu'un `folder.rename(dst)` emporte de toute facon l'arborescence complete.
Tout ce qui vivait dans un sous-dossier (extras, sous-titres, artwork) etait donc
absent de l'estimation : la garde autorisait un apply qui manquait de place, et
celui-ci se coupait a mi-parcours — exactement ce que le module dit prevenir.

Ce fichier couvre les trois gardes du correctif, separement :
  1. la RECURSION elle-meme (`_dir_tree_size`) ;
  2. le fait qu'une row a dossier DEDIE (`single`, ou kind inconnu) soit estimee
     sur tout son arbre et plus sur son seul fichier video ;
  3. l'exemption des kinds a dossier PARTAGE (`collection`/`tv_episode`/`extra`),
     qui preserve l'arbitrage "Fix R6-04" (pas de faux "espace insuffisant").

Et surtout : la reproduction passe par la facade de PRODUCTION avec un apply
REEL (`dry_run=False`), pas par une preview.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

sys.path.insert(0, ".")

import cinesort.domain.core as core
from cinesort.app.disk_space_check import (
    _MIN_FREE_BYTES,
    _row_estimated_size,
    check_disk_space_for_apply,
    estimate_apply_size,
)
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done

MB = 1024 * 1024


def _row(folder: Path, video: str, row_id: str = "r1", kind: str = "single") -> SimpleNamespace:
    return SimpleNamespace(folder=str(folder), video=video, row_id=row_id, kind=kind)


def _sized(path: Path, size: int) -> None:
    """Cree un fichier de `size` octets sans ecrire `size` octets (truncate)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


class RecursiveEstimateTests(unittest.TestCase):
    """Garde 1 et 2 : recursion, et granularite "dossier entier" pour un single."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_796_est_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_row_without_video_sums_subfolders_recursively(self) -> None:
        """GARDE 1 (recursion pure) : la row n'a pas de `video`, donc seul le
        parcours recursif est en jeu. Un `iterdir` ne verrait que les 1 000
        octets du premier niveau et raterait les 9 000 des sous-dossiers."""
        folder = self.tmp / "Sans video"
        _sized(folder / "surface.mkv", 1000)
        _sized(folder / "Extras" / "making_of.mkv", 6000)
        _sized(folder / "Subs" / "fr" / "film.srt", 3000)

        self.assertEqual(_row_estimated_size(_row(folder, "")), 10000)

    def test_single_row_sums_whole_tree_not_only_main_video(self) -> None:
        """GARDE 2 : `single` = dossier dedie, l'apply deplace TOUT le dossier.
        Estimer la seule video principale sous-estimait de 9 000 octets."""
        folder = self.tmp / "Film (2020)"
        _sized(folder / "film.mkv", 1000)
        _sized(folder / "Extras" / "bonus.mkv", 9000)

        self.assertEqual(_row_estimated_size(_row(folder, "film.mkv", kind="single")), 10000)

    def test_unknown_kind_falls_back_to_whole_tree(self) -> None:
        """Kind absent ou inconnu : on retombe sur la granularite la PLUS
        destructive (dossier entier), comme `_normalize_plan_kind` retombe sur
        "single". Sur un chemin destructif l'erreur doit rester restrictive."""
        folder = self.tmp / "Kind inconnu"
        _sized(folder / "film.mkv", 1000)
        _sized(folder / "Extras" / "bonus.mkv", 4000)

        for kind in ("", "n_importe_quoi"):
            with self.subTest(kind=kind):
                self.assertEqual(_row_estimated_size(_row(folder, "film.mkv", kind=kind)), 5000)

    def test_estimate_never_drops_below_main_video_when_tree_unreadable(self) -> None:
        """Plancher : si l'arborescence est illisible mais que la video se stat,
        on garde la taille de la video (jamais moins que l'ancienne estimation)."""
        folder = self.tmp / "Film illisible"
        _sized(folder / "film.mkv", 7777)

        with mock.patch.object(Path, "rglob", side_effect=PermissionError("acces refuse (mock)")):
            self.assertEqual(_row_estimated_size(_row(folder, "film.mkv")), 7777)

    def test_missing_folder_still_returns_zero(self) -> None:
        """Aucune information : on ne bloque pas un apply sur un edge case."""
        self.assertEqual(_row_estimated_size(_row(self.tmp / "fantome", "fantome.mkv")), 0)


class SharedFolderKindTests(unittest.TestCase):
    """Garde 3 : les kinds a dossier PARTAGE ne comptent que leur propre video.

    Sans cette exemption, un dossier de collection de N films serait compte N
    fois — un faux "espace disque insuffisant" du meme ordre que celui que le
    Fix R6-04 (apply_support.py) a supprime en ne sommant que les approuves.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_796_shared_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_collection_rows_do_not_multiply_their_shared_folder(self) -> None:
        folder = self.tmp / "Trilogie"
        _sized(folder / "un.mkv", 1000)
        _sized(folder / "deux.mkv", 2000)
        _sized(folder / "trois.mkv", 3000)
        _sized(folder / "Bonus" / "lourd.bin", 100000)

        rows = [
            _row(folder, "un.mkv", row_id="c1", kind="collection"),
            _row(folder, "deux.mkv", row_id="c2", kind="collection"),
            _row(folder, "trois.mkv", row_id="c3", kind="collection"),
        ]
        total = estimate_apply_size(rows, approved_keys={"c1", "c2", "c3"})
        self.assertEqual(total, 6000)

    def test_tv_episode_and_extra_share_the_same_rule(self) -> None:
        folder = self.tmp / "Dossier partage"
        _sized(folder / "episode.mkv", 4000)
        _sized(folder / "Sous-dossier" / "lourd.bin", 500000)

        for kind in ("tv_episode", "extra"):
            with self.subTest(kind=kind):
                self.assertEqual(_row_estimated_size(_row(folder, "episode.mkv", kind=kind)), 4000)


class UnapprovedRowsNotCountedTests(unittest.TestCase):
    """La quarantaine ne se facture pas : les rows non approuvees partent sous
    `<root>/_review/`, donc sur le volume que l'on mesure deja. Les compter
    reviendrait a facturer deux fois le meme volume et ferait revivre le faux
    "espace insuffisant" du Fix R6-04. La recursion ne doit pas contourner ce
    filtre."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_796_unappr_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_deep_tree_of_unapproved_row_is_ignored(self) -> None:
        folder = self.tmp / "Refuse"
        _sized(folder / "film.mkv", 5000)
        _sized(folder / "Extras" / "enorme.bin", 900000)

        rows = [_row(folder, "film.mkv", row_id="r1")]
        self.assertEqual(estimate_apply_size(rows, approved_keys=set()), 0)
        self.assertEqual(estimate_apply_size(rows, approved_keys={"autre"}), 0)
        self.assertEqual(estimate_apply_size(rows, approved_keys={"r1"}), 905000)


class DiskGuardWiringTests(unittest.TestCase):
    """La somme recursive doit remonter jusqu'au verdict de la garde."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_796_guard_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_guard_refuses_when_only_subfolders_make_it_overflow(self) -> None:
        """Le fichier de surface tient dans l'espace libre, l'arbre complet non."""
        folder = self.tmp / "Film.2020"
        _sized(folder / "film.mkv", 80 * MB)
        _sized(folder / "Extras" / "bonus.bin", 80 * MB)

        cfg = SimpleNamespace(root=self.tmp)
        free = 120 * MB
        self.assertGreater(free, _MIN_FREE_BYTES)  # sinon le minimum absolu masquerait le test
        fake_usage = SimpleNamespace(total=10**12, used=10**12 - free, free=free)

        with mock.patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            ok, info = check_disk_space_for_apply(cfg, [_row(folder, "film.mkv")], {"r1"})

        self.assertFalse(ok, info)
        self.assertEqual(info["estimated_bytes"], 160 * MB)
        self.assertIn("Espace disque insuffisant", info["message"])


class RealApplyDiskGuardTests(unittest.TestCase):
    """Reproduction #796 par la facade de PRODUCTION, en apply REEL.

    `api._apply_impl(..., dry_run=False, ...)` est l'entree qu'utilise l'UI.
    Avant le correctif, l'estimation valait 80 Mo (la seule video) pour un
    dossier de 160 Mo : avec 120 Mo libres la garde disait OK et le dossier
    partait vraiment sur disque.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_796_e2e_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plan(self, api: CineSortApi) -> str:
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": False,
                # Le recalcul qualite de fin de scan tourne dans un thread daemon
                # qui OUVRE les .mkv (run_flow_support.py:535). Sur Windows il
                # tient encore un handle quand l'apply veut deplacer le fichier
                # -> WinError 32 sans rapport avec la garde testee ici.
                "auto_recompute_quality_on_scan": False,
                "perceptual_auto_on_scan": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        _wait_done(api, run_id)
        return run_id

    @staticmethod
    def _decisions(api: CineSortApi, run_id: str, approve: Any = True) -> dict:
        rows = (api.run.get_plan(run_id) or {}).get("rows", [])
        out = {}
        for row in rows:
            ok = approve(row) if callable(approve) else bool(approve)
            out[row["row_id"]] = {
                "ok": ok,
                "title": row.get("proposed_title") or "",
                "year": row.get("proposed_year") or 0,
            }
        return out

    def test_real_apply_is_refused_when_subfolder_does_not_fit(self) -> None:
        folder = self.root / "Film.2020.1080p"
        _sized(folder / "Film.2020.1080p.mkv", 80 * MB)
        _sized(folder / "Extras" / "making_of.bin", 80 * MB)

        api = CineSortApi()
        run_id = self._plan(api)
        decisions = self._decisions(api, run_id)
        self.assertEqual(len(decisions), 1, decisions)

        free = 120 * MB
        fake_usage = SimpleNamespace(total=10**12, used=10**12 - free, free=free)
        with mock.patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            result = api._apply_impl(run_id, decisions, False, False)

        self.assertFalse(result.get("ok"), result)
        self.assertIn("Espace disque insuffisant", str(result.get("message")))
        self.assertEqual(result["disk_check"]["estimated_bytes"], 160 * MB)
        # Un echec ne devient jamais un succes silencieux : RIEN n'a bouge.
        self.assertTrue((folder / "Film.2020.1080p.mkv").is_file())
        self.assertTrue((folder / "Extras" / "making_of.bin").is_file())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["Film.2020.1080p"])

    def test_real_apply_proceeds_when_whole_tree_fits(self) -> None:
        """Contre-epreuve : la garde ne devient pas un refus systematique."""
        folder = self.root / "Film.2021.1080p"
        _sized(folder / "Film.2021.1080p.mkv", 80 * MB)
        _sized(folder / "Extras" / "making_of.bin", 80 * MB)

        api = CineSortApi()
        run_id = self._plan(api)
        decisions = self._decisions(api, run_id)

        free = 400 * MB
        fake_usage = SimpleNamespace(total=10**12, used=10**12 - free, free=free)
        with mock.patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            result = api._apply_impl(run_id, decisions, False, False)

        self.assertTrue(result.get("ok"), result)
        self.assertFalse(folder.exists(), "le dossier source aurait du etre renomme")

    def test_root_level_films_are_estimated_without_walking_the_whole_library(self) -> None:
        """Un film pose DIRECTEMENT a la racine est planifie en `collection`
        avec `folder` = LA RACINE (plan_support_core.py force la logique
        collection a la racine, cf. GATE R5-P2). Estimer ces rows sur leur
        arborescence reviendrait a sommer TOUTE la bibliotheque, une fois par
        film pose a la racine : faux "espace insuffisant" garanti, et un rglob
        complet de la racine par row. Ici : 3 films, dont 2 a la racine ; la
        somme attendue est celle des 3 videos, pas 2x la racine.

        L'espace libre est mis a 0 pour que la garde refuse et expose
        `disk_check.estimated_bytes` — c'est cette valeur qu'on verifie."""
        _sized(self.root / "Inception 2010.mkv", 4096)
        _sized(self.root / "Matrix 1999.mkv", 8192)
        _sized(self.root / "Autre Film" / "Autre.Film.2005.mkv", 2048)

        api = CineSortApi()
        run_id = self._plan(api)
        rows = (api.run.get_plan(run_id) or {}).get("rows", [])
        self.assertEqual(sorted(str(row.get("kind")) for row in rows), ["collection", "collection", "single"], rows)
        decisions = self._decisions(api, run_id)

        fake_usage = SimpleNamespace(total=10**12, used=10**12, free=0)
        with mock.patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            result = api._apply_impl(run_id, decisions, False, False)

        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result["disk_check"]["estimated_bytes"], 4096 + 8192 + 2048)
        self.assertTrue((self.root / "Inception 2010.mkv").is_file())
        self.assertTrue((self.root / "Matrix 1999.mkv").is_file())

    def test_real_apply_of_a_collection_is_not_falsely_refused(self) -> None:
        """Les rows d'une collection PARTAGENT leur dossier et ne deplacent que
        leur propre video, vers un sous-dossier du meme dossier. Les estimer sur
        l'arbre entier compterait ce dossier une fois par film et produirait un
        faux "espace insuffisant" — la meme famille de regression que le Fix
        R6-04. Ici : 3 films de 50 Mo, 200 Mo libres. Vrai besoin ~165 Mo ;
        besoin errone (dossier compte 3 fois) ~495 Mo."""
        pack = self.root / "Trilogie Pack"
        _sized(pack / "Le.Film.Un.2001.1080p.mkv", 50 * MB)
        _sized(pack / "Le.Film.Deux.2002.1080p.mkv", 50 * MB)
        _sized(pack / "Le.Film.Trois.2003.1080p.mkv", 50 * MB)

        api = CineSortApi()
        run_id = self._plan(api)
        rows = (api.run.get_plan(run_id) or {}).get("rows", [])
        self.assertEqual(sorted({row.get("kind") for row in rows}), ["collection"], rows)
        decisions = self._decisions(api, run_id)
        self.assertEqual(len(decisions), 3, decisions)

        free = 200 * MB
        fake_usage = SimpleNamespace(total=10**12, used=10**12 - free, free=free)
        with mock.patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            result = api._apply_impl(run_id, decisions, False, False)

        self.assertTrue(result.get("ok"), result)
        # Chaque film est descendu dans son propre sous-dossier du meme dossier.
        self.assertEqual([p for p in pack.iterdir() if p.suffix == ".mkv"], [])
        subdirs = sorted(p for p in pack.iterdir() if p.is_dir())
        self.assertEqual(len(subdirs), 3, subdirs)
        for subdir in subdirs:
            self.assertEqual(len([p for p in subdir.iterdir() if p.suffix == ".mkv"]), 1, subdir)

    def test_quarantine_of_unapproved_rows_does_not_inflate_the_estimate(self) -> None:
        """Arbitrage Fix R6-04 verrouille en apply REEL : un gros film REFUSE
        (donc mis en quarantaine sous `<root>/_review/`, meme volume) ne doit
        pas faire refuser l'apply du petit film approuve."""
        approved = self.root / "Petit.2020.1080p"
        _sized(approved / "Petit.2020.1080p.mkv", 60 * MB)
        _sized(approved / "Extras" / "bonus.bin", 60 * MB)
        refused = self.root / "Enorme.2019.1080p"
        _sized(refused / "Enorme.2019.1080p.mkv", 150 * MB)

        api = CineSortApi()
        run_id = self._plan(api)
        decisions = self._decisions(api, run_id, approve=lambda row: "Petit" in str(row.get("folder") or ""))
        self.assertEqual(sum(1 for d in decisions.values() if d["ok"]), 1, decisions)
        self.assertEqual(sum(1 for d in decisions.values() if not d["ok"]), 1, decisions)

        free = 200 * MB  # < 297 Mo (si la row refusee etait comptee) mais > 132 Mo
        fake_usage = SimpleNamespace(total=10**12, used=10**12 - free, free=free)
        with mock.patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            result = api._apply_impl(run_id, decisions, False, True)

        self.assertTrue(result.get("ok"), result)
        self.assertFalse(approved.exists(), "le film approuve aurait du etre renomme")
        self.assertTrue((self.root / "_review").is_dir(), "le film refuse aurait du partir en quarantaine")


if __name__ == "__main__":
    unittest.main()
