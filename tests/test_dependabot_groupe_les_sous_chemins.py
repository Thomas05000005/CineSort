# -*- coding: utf-8 -*-
"""Une action decoupee en SOUS-CHEMINS doit monter en UNE SEULE PR.

Le defaut
---------
`github/codeql-action` est utilisee sous trois chemins — `init`, `analyze` et
`upload-sarif`. Dependabot traite chacun comme une dependance INDEPENDANTE :
sans bloc `groups:`, il ouvre une PR par sous-chemin, vers le meme SHA.

Or ces versions doivent bouger ENSEMBLE. Prise seule, chaque PR rend rouges les
deux checks CodeQL requis, avec des erreurs symetriques :

    Loaded a configuration file for version '4.37.6', but running version '4.37.8'

et l'inverse dans l'autre PR. Aucune des deux ne peut donc etre fusionnee, et
elles gelent deux des cinq creneaux `open-pull-requests-limit` — a vie, puisque
rien ne les debloque. Mesure du 2026-08-24 : #1145 et #1142, exactement ce cas.

Pourquoi ce test est GENERIQUE
------------------------------
Corriger le seul couple connu laisserait le piege intact pour la prochaine
action decoupee, et pour le troisieme sous-chemin (`upload-sarif`) que la revue
n'avait pas compte. Le test derive donc la liste des familles DEPUIS les
workflows : ce qui est mesure, c'est l'accord entre ce que le depot utilise
reellement et ce que dependabot groupe.

Le second controle est moins evident que le premier. Un groupe qui restreint
`update-types` a `minor`/`patch` laisse un bump MAJEUR se redecouper en PR
separees — le groupe existerait alors sans proteger le cas ou la casse est la
plus probable.
"""

from __future__ import annotations

import collections
import re
import unittest
from fnmatch import fnmatch
from pathlib import Path

import yaml

_RACINE = Path(__file__).resolve().parents[1]
_WORKFLOWS = _RACINE / ".github" / "workflows"
_DEPENDABOT = _RACINE / ".github" / "dependabot.yml"

#: `uses: proprietaire/depot[/sous/chemin]@ref`
_USES = re.compile(r"uses:\s*([A-Za-z0-9._-]+/[A-Za-z0-9._/-]+)@")


def _familles_utilisees() -> dict[str, set[str]]:
    """`{"github/codeql-action": {"github/codeql-action/init", ...}}`."""
    familles: dict[str, set[str]] = collections.defaultdict(set)
    for fichier in sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml")):
        for m in _USES.finditer(fichier.read_text(encoding="utf-8")):
            ref = m.group(1)
            familles["/".join(ref.split("/")[:2])].add(ref)
    return familles


def _ecosysteme_actions() -> dict:
    conf = yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))
    for bloc in conf.get("updates") or []:
        if bloc.get("package-ecosystem") == "github-actions":
            return bloc
    raise AssertionError("aucun ecosysteme `github-actions` dans dependabot.yml")


class LesSousCheminsMontentEnsembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.familles = _familles_utilisees()
        self.bloc = _ecosysteme_actions()
        self.groupes = self.bloc.get("groups") or {}

    def test_le_corpus_n_est_pas_VIDE(self) -> None:
        """Garde anti-silence. Si le parseur ne trouve plus aucune action —
        renommage de dossier, changement de syntaxe — les assertions suivantes
        porteraient sur un ensemble vide et passeraient sans rien mesurer."""
        self.assertGreater(len(self.familles), 5, "aucune action lue dans les workflows")
        self.assertIn("github/codeql-action", self.familles, "le cas connu a disparu du corpus")

    def test_toute_famille_a_SOUS_CHEMINS_est_groupee(self) -> None:
        multi = {f: r for f, r in self.familles.items() if len(r) > 1}
        self.assertTrue(multi, "corpus sans famille multi-chemins : le test ne mesure rien")

        for famille, refs in sorted(multi.items()):
            with self.subTest(famille=famille):
                couvrants = [
                    nom
                    for nom, g in self.groupes.items()
                    if any(fnmatch(famille, str(p)) for p in (g.get("patterns") or []))
                ]
                self.assertTrue(
                    couvrants,
                    f"`{famille}` est utilisee sous {len(refs)} chemins "
                    f"({', '.join(sorted(refs))}) mais aucun groupe dependabot ne la couvre : "
                    "chaque sous-chemin montera dans sa propre PR, vers le meme SHA, "
                    "et chacune rendra rouges les checks de l'autre",
                )

    def test_le_groupe_couvrant_n_exclut_PAS_les_majeurs(self) -> None:
        """Un groupe restreint a `minor`/`patch` laisse un bump MAJEUR se
        redecouper — precisement le cas ou la desynchronisation casse le plus."""
        multi = {f: r for f, r in self.familles.items() if len(r) > 1}
        for famille in sorted(multi):
            for nom, g in self.groupes.items():
                if not any(fnmatch(famille, str(p)) for p in (g.get("patterns") or [])):
                    continue
                with self.subTest(famille=famille, groupe=nom):
                    types = g.get("update-types")
                    if types is None:
                        continue  # non restreint : tous les types, c'est ce qu'on veut
                    self.assertIn(
                        "major",
                        [str(t) for t in types],
                        f"le groupe `{nom}` couvre `{famille}` mais exclut les majeurs : "
                        "un bump major se redecoupera en PR separees",
                    )


if __name__ == "__main__":
    unittest.main()
