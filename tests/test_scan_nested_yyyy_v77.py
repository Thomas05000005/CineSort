"""GATE — fast-path dossier `(YYYY)` descend les releases imbriquees.

Bug (AUDIT REAL 2/2) : un dossier `Avatar (2009)/` matchant `(YYYY)` devenait
candidat SANS etre descendu. iter_videos (phase 2) etant non-recursif, un film
dans un sous-dossier release imbrique (`Avatar (2009)/Avatar.2009.1080p-GRP/
film.mkv`) etait silencieusement absent du plan.

Fix (Opus 2026-06-11) : decider en 1 scandir entre candidat-direct (video
posee directement) et descente (film imbrique), avec tri des bonus pour ne pas
planifier de featurettes comme films. Ces tests verrouillent les 3 invariants :
  1. film direct -> 1 seul candidat, AUCUN doublon ;
  2. film imbrique -> retrouve (candidat = le sous-dossier release) ;
  3. featurettes/extras imbriques -> JAMAIS candidats.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
import cinesort.domain.scan_helpers as sh


def _build(root: Path, files: list[str]) -> None:
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 4096)


def _rel_candidates(root: Path) -> list[str]:
    cfg = core.Config(root=root, enable_tmdb=False).normalized()
    cands = sh.discover_candidate_folders(cfg)
    return sorted(str(Path(c).resolve().relative_to(root.resolve())).replace("\\", "/") for c in cands)


class NestedYearFolderDiscoveryTests(unittest.TestCase):
    def test_direct_video_single_candidate_no_duplicate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yyyy_direct_") as tmp:
            root = Path(tmp)
            _build(root, ["Avatar (2009)/Avatar.2009.1080p.mkv"])
            cands = _rel_candidates(root)
            self.assertEqual(cands, ["Avatar (2009)"])
            # invariant anti-doublon : un seul candidat porte ce film
            self.assertEqual(len(cands), 1)

    def test_nested_release_film_is_found(self) -> None:
        # AVANT le fix : ce film etait absent (candidat = "Avatar (2009)" seul,
        # non descendu, iter_videos non-recursif -> rien).
        with tempfile.TemporaryDirectory(prefix="yyyy_nested_") as tmp:
            root = Path(tmp)
            _build(root, ["Avatar (2009)/Avatar.2009.1080p-GRP/Avatar.2009.1080p.mkv"])
            cands = _rel_candidates(root)
            self.assertEqual(cands, ["Avatar (2009)/Avatar.2009.1080p-GRP"])

    def test_nested_release_with_bonus_sibling_excludes_bonus(self) -> None:
        # La release imbriquee est trouvee ; le dossier bonus voisin ne doit PAS
        # devenir un film.
        with tempfile.TemporaryDirectory(prefix="yyyy_nested_bonus_") as tmp:
            root = Path(tmp)
            _build(
                root,
                [
                    "Avatar (2009)/Avatar.2009.1080p-GRP/Avatar.2009.1080p.mkv",
                    "Avatar (2009)/Extras/bonus.mkv",
                    "Avatar (2009)/Featurettes/making of.mkv",
                ],
            )
            cands = _rel_candidates(root)
            self.assertEqual(cands, ["Avatar (2009)/Avatar.2009.1080p-GRP"])
            self.assertNotIn("Avatar (2009)/Extras", cands)
            self.assertNotIn("Avatar (2009)/Featurettes", cands)

    def test_direct_video_plus_featurette_subdir_not_descended(self) -> None:
        # Film pose directement + un sous-dossier featurette : on reste sur le
        # fast-path candidat-direct (pas de descente), donc la featurette n'est
        # jamais planifiee.
        with tempfile.TemporaryDirectory(prefix="yyyy_direct_feat_") as tmp:
            root = Path(tmp)
            _build(
                root,
                [
                    "Avatar (2009)/Avatar.2009.1080p.mkv",
                    "Avatar (2009)/Featurettes/making-of.mkv",
                ],
            )
            cands = _rel_candidates(root)
            self.assertEqual(cands, ["Avatar (2009)"])

    def test_nested_subdir_also_has_year(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yyyy_double_") as tmp:
            root = Path(tmp)
            _build(root, ["Avatar (2009)/Avatar (2009) 1080p/film.mkv"])
            cands = _rel_candidates(root)
            self.assertEqual(cands, ["Avatar (2009)/Avatar (2009) 1080p"])

    def test_deep_category_tree_nested_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yyyy_deep_") as tmp:
            root = Path(tmp)
            _build(root, ["Films/Action/Avatar (2009)/Avatar.2009.1080p-GRP/film.mkv"])
            cands = _rel_candidates(root)
            self.assertEqual(cands, ["Films/Action/Avatar (2009)/Avatar.2009.1080p-GRP"])


class NestedYearPlanLibraryTests(unittest.TestCase):
    """GATE bout-en-bout : le plan contient bien le film imbrique (1 row), et
    aucun bonus n'est planifie."""

    def test_plan_library_includes_nested_film_and_excludes_bonus(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yyyy_plan_") as tmp:
            root = Path(tmp)
            _build(
                root,
                [
                    "Avatar (2009)/Avatar.2009.1080p-GRP/Avatar.2009.1080p.mkv",
                    "Avatar (2009)/Extras/bonus.mkv",
                ],
            )
            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                rows, _stats = plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda *_a: None,
                    progress=lambda *_a: None,
                )
            videos = sorted(Path(r.folder).name + "/" + r.video for r in rows)
            # Exactement 1 row : le film imbrique. Le bonus n'est PAS planifie.
            self.assertEqual(len(rows), 1, videos)
            self.assertEqual(rows[0].video, "Avatar.2009.1080p.mkv")
            self.assertNotIn("bonus.mkv", [r.video for r in rows])

    def test_plan_library_direct_film_single_row(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yyyy_plan_direct_") as tmp:
            root = Path(tmp)
            _build(root, ["Avatar (2009)/Avatar.2009.1080p.mkv"])
            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                rows, _stats = plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda *_a: None,
                    progress=lambda *_a: None,
                )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].video, "Avatar.2009.1080p.mkv")


if __name__ == "__main__":
    unittest.main(verbosity=2)
