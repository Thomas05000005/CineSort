# -*- coding: utf-8 -*-
"""Contrat #770 : aucune porte d'entree fusion ne contourne CINESORT_FUSION_DOUBLONS.

Pourquoi ce test existe
-----------------------
`cinesort/app/duplicate_pipeline.py` annonce en tete de module une backward
compat ABSOLUE : tant que le flag `CINESORT_FUSION_DOUBLONS` est OFF (defaut),
AUCUN calcul fusion ne tourne — ni ffmpeg (extraction de vignettes pour le
videohash), ni Chromaprint. `compute_fusion_for_groups` respecte cet invariant
(`if not is_fusion_enabled(): return []`).

`compute_fusion_for_pair` ne le respectait pas : elle appelait directement
`extract_video_thumbnails` et `compare_audio_fingerprints` sans jamais consulter
le flag. Elle n'avait aucun appelant, donc l'invariant n'a jamais ete viole EN
EXECUTION — mais rien n'empechait un cablage ulterieur de le violer en silence.
Elle a ete supprimee ; ce contrat prend le relais pour que la prochaine porte
d'entree n'oublie pas la garde.

Comment ca marche
-----------------
Analyse AST du module, sans l'importer ni l'executer : pour chaque fonction
declaree au niveau MODULE, on regarde les noms references dans TOUT son
sous-arbre (fonctions imbriquees incluses). Si elle touche un des symboles
COUTEUX, elle doit aussi referencer `is_fusion_enabled`.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = REPO_ROOT / "cinesort" / "app" / "duplicate_pipeline.py"

# Symboles dont l'appel declenche un travail lourd (sous-processus ffmpeg,
# comparaison de fingerprints) : ils sont exactement ce que le flag protege.
COSTLY_SYMBOLS = frozenset(
    {
        "extract_video_thumbnails",
        "compute_phash_per_frame",
        "compare_audio_fingerprints",
    }
)
FLAG_GUARD = "is_fusion_enabled"


def _referenced_names(node: ast.AST) -> Set[str]:
    """Tous les identifiants lus dans le sous-arbre (Name + attributs)."""
    names: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _module_level_functions(tree: ast.Module) -> List[ast.FunctionDef]:
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


class FusionFlagGuardContractTests(unittest.TestCase):
    """Toute fonction du pipeline fusion qui coute cher passe par le flag."""

    tree: ast.Module

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(MODULE.read_text(encoding="utf-8"))

    def test_extraction_is_sane(self) -> None:
        """Garde anti-silence : un extracteur casse rendrait le test vert a tort."""
        funcs = _module_level_functions(self.tree)
        self.assertGreaterEqual(
            len(funcs),
            3,
            msg=f"Seulement {len(funcs)} fonction(s) module-level trouvee(s) dans {MODULE.name}.",
        )
        # Au moins une fonction DOIT toucher les symboles couteux, sinon le test
        # ne verifie rien (cas du module vide ou renomme).
        touching = [f.name for f in funcs if _referenced_names(f) & COSTLY_SYMBOLS]
        self.assertTrue(
            touching,
            msg=(
                f"Aucune fonction de {MODULE.name} ne reference {sorted(COSTLY_SYMBOLS)} : "
                "les symboles ont-ils ete renommes ? Ce contrat ne verifierait plus rien."
            ),
        )

    def test_no_costly_entry_point_bypasses_the_feature_flag(self) -> None:
        violations = []
        for func in _module_level_functions(self.tree):
            names = _referenced_names(func)
            costly = sorted(names & COSTLY_SYMBOLS)
            if not costly:
                continue
            if FLAG_GUARD in names:
                continue
            violations.append(f"  - {func.name}() (ligne {func.lineno}) appelle {costly} sans consulter {FLAG_GUARD}()")
        self.assertEqual(
            violations,
            [],
            msg=(
                f"{len(violations)} porte(s) d'entree fusion contourne(nt) le flag "
                "CINESORT_FUSION_DOUBLONS :\n"
                + "\n".join(violations)
                + "\n\nLe flag est OFF par defaut et sa raison d'etre est la backward compat "
                "ABSOLUE : flag OFF = zero ffmpeg, zero Chromaprint. Ajouter "
                "`if not is_fusion_enabled(): return ...` en tete de la fonction (cf "
                "compute_fusion_for_groups), ou supprimer la fonction si elle n'a pas "
                "d'appelant (cas de compute_fusion_for_pair, #770)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
