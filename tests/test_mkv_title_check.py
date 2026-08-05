# -*- coding: utf-8 -*-
"""Tests de `cinesort/domain/mkv_title_check.py` (#867).

Le module n'avait AUCUN test : c'est precisement ce qui a laisse survivre
`_is_scene_title` + `_SCENE_PATTERNS` + `_SCENE_THRESHOLD` sans appelant apres le
refactor R8-044 (F4), qui a remplace la classification « titre scene » par une
comparaison par TOKENS normalises. Ces trois symboles sont supprimes ; ce fichier
fige le comportement de la fonction VIVANTE du module, `check_container_title`,
pour que la suppression ait un filet.

`check_container_title` est cablee en production dans
`cinesort/ui/api/quality_report_support.py:489`.
"""

from __future__ import annotations

import unittest

from cinesort.domain.mkv_title_check import check_container_title

FLAG = "mkv_title_mismatch"


class CheckContainerTitleTests(unittest.TestCase):
    def test_scene_release_name_is_not_a_conflict(self) -> None:
        """Raison d'etre de R8-044 : un release-name a points n'est PAS un conflit.

        Avant R8-044 l'egalite exacte faisait mismatcher 88 % des release-names.
        """
        self.assertEqual(
            check_container_title("Inception.2010.1080p.BluRay.x264-SPARKS", "Inception"),
            [],
        )

    def test_unrelated_title_is_a_conflict(self) -> None:
        """Tokens disjoints = vrai conflit, c'est le seul cas qui doit flaguer."""
        self.assertEqual(
            check_container_title("Le Parrain", "Inception"),
            [FLAG],
        )

    def test_container_title_made_only_of_technical_noise_is_not_a_conflict(self) -> None:
        """Pin de `_TITLE_NOISE_RE` : un cote reduit a du bruit ne prouve rien.

        Sans le retrait du bruit, {1080p, x264, bluray} et {inception} seraient
        disjoints -> faux `mkv_title_mismatch`.
        """
        self.assertEqual(
            check_container_title("1080p.BluRay.x264", "Inception"),
            [],
        )

    def test_exact_and_empty_titles_are_never_conflicts(self) -> None:
        self.assertEqual(check_container_title("Inception", "Inception"), [])
        self.assertEqual(check_container_title("INCEPTION", "Inception"), [])
        self.assertEqual(check_container_title(None, "Inception"), [])
        self.assertEqual(check_container_title("   ", "Inception"), [])
        self.assertEqual(check_container_title("Inception", ""), [])


if __name__ == "__main__":
    unittest.main()
