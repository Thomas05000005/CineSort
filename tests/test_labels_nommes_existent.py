# -*- coding: utf-8 -*-
"""Un label nomme dans `.github/` qui n'existe pas est une garde qui ne mord pas.

Le defaut
---------
`stale.yml` declarait `exempt-pr-labels: "pinned,security,wip,work-in-progress,
blocked"`. Mesure du 2026-08-31 sur les 33 labels reels : **trois des cinq
etaient FANTOMES** (`pinned`, `wip`, `work-in-progress`). Ils ne pouvaient
STRUCTURELLEMENT jamais s'appliquer — le bot ferme donc des PR que la
configuration croit proteger, et `delete-branch: true` supprime leur branche.

Le meme balayage a trouve trois autres fantomes que la revue n'avait pas vus :

- `good-first-issue` dans `exempt-issue-labels` : le vrai nom porte des ESPACES
  (`good first issue`). Un tiret suffit a rendre la garde muette.
- `python` et `github-actions` dans `dependabot.yml` : aucune PR dependabot ne
  les portait. Un label inexistant est ignore en silence.

C'est le motif de la « regle absolue impossible » (#1096), applique a une garde :
la configuration est lisible, plausible, et sans effet.

Pourquoi la liste est VENDOREE
------------------------------
Interroger l'API GitHub rendrait ce test dependant du reseau et d'un jeton — il
tomberait en vert (ou en erreur) pour des raisons etrangeres a ce qu'il mesure.
La liste ci-dessous est donc figee, datee, et regenerable par une commande
qu'elle porte elle-meme. Ajouter un label au depot sans l'ajouter ici fait
echouer ce test : c'est voulu, la friction est le rappel.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

import yaml

_RACINE = Path(__file__).resolve().parents[1]

#: Labels reellement definis sur le depot.
#: Mesure : 2026-08-31, 35 labels.
#: Regenerer avec :  gh label list --limit 200 --json name -q '.[].name' | sort
_LABELS_REELS = frozenset(
    {
        "architecture",
        "audit-2026-05-12",
        "backend",
        "blocked",
        "bug",
        "build",
        "ci",
        "critical",
        "database",
        "dependencies",
        "documentation",
        "duplicate",
        "enhancement",
        "frontend",
        "github-actions",
        "good first issue",
        "help wanted",
        "help-wanted",
        "high-priority",
        "i18n",
        "invalid",
        "needs-review",
        "perceptual",
        "performance",
        "python",
        "python:uv",
        "question",
        "reliability",
        "security",
        "settings",
        "stale",
        "testing",
        "tests",
        "ux",
        "wontfix",
    }
)

#: Cles de `actions/stale` dont la valeur est une liste de labels.
_CLES_LISTE = ("exempt-issue-labels", "exempt-pr-labels")
#: Cles dont la valeur est UN label — celui que le bot POSE, donc il doit exister
#: aussi, sinon le bot echoue a marquer et ne ferme jamais rien.
_CLES_SIMPLE = ("stale-issue-label", "stale-pr-label")


def _lire(chemin: Path):
    return yaml.safe_load(io.open(chemin, encoding="utf-8").read())


def _labels_de_stale() -> dict[str, str]:
    """`{label: origine}` pour tout label nomme dans stale.yml."""
    trouves: dict[str, str] = {}
    conf = _lire(_RACINE / ".github" / "workflows" / "stale.yml")
    for job in (conf.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            avec = step.get("with") or {}
            for cle in _CLES_LISTE:
                for brut in str(avec.get(cle) or "").split(","):
                    if brut.strip():
                        trouves[brut.strip()] = f"stale.yml:{cle}"
            for cle in _CLES_SIMPLE:
                if str(avec.get(cle) or "").strip():
                    trouves[str(avec[cle]).strip()] = f"stale.yml:{cle}"
    return trouves


def _labels_de_dependabot() -> dict[str, str]:
    trouves: dict[str, str] = {}
    conf = _lire(_RACINE / ".github" / "dependabot.yml")
    for bloc in conf.get("updates") or []:
        eco = bloc.get("package-ecosystem")
        for label in bloc.get("labels") or []:
            trouves[str(label)] = f"dependabot.yml:{eco}"
    return trouves


def _labels_de_labeler() -> dict[str, str]:
    conf = _lire(_RACINE / ".github" / "labeler.yml") or {}
    return {str(label): "labeler.yml" for label in conf}


class LesLabelsNommesExistentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nommes: dict[str, str] = {}
        for source in (_labels_de_labeler, _labels_de_dependabot, _labels_de_stale):
            self.nommes.update(source())

    def test_le_corpus_n_est_pas_VIDE(self) -> None:
        """Garde anti-silence : un parseur qui ne trouve plus rien ferait passer
        les assertions suivantes sur un ensemble vide."""
        self.assertGreater(len(self.nommes), 10, "aucun label lu dans .github/")

    def test_stale_ne_nomme_que_des_labels_REELS(self) -> None:
        """Le cas qui a mordu : trois exemptions PR sur cinq etaient fantomes."""
        fantomes = {label: origine for label, origine in _labels_de_stale().items() if label not in _LABELS_REELS}
        self.assertEqual(
            fantomes,
            {},
            "labels nommes par stale.yml mais inexistants — ces exemptions ne "
            "peuvent JAMAIS s'appliquer, et `delete-branch: true` supprime la "
            "branche des PR qu'elles croyaient proteger",
        )

    def test_AUCUN_fichier_de_github_ne_nomme_un_label_fantome(self) -> None:
        """Elargi a `dependabot.yml` et `labeler.yml` : le meme piege les
        touchait, et un label dependabot inexistant est ignore EN SILENCE."""
        fantomes = {l: o for l, o in self.nommes.items() if l not in _LABELS_REELS}
        self.assertEqual(fantomes, {}, "labels nommes dans .github/ mais inexistants")

    def test_le_BROUILLON_est_exempte_sans_passer_par_un_label(self) -> None:
        """`wip` / `work-in-progress` visaient les travaux en cours et etaient
        fantomes tous les deux. `exempt-draft-pr` est l'option NATIVE : elle ne
        depend d'aucun label, donc elle ne peut pas le devenir."""
        conf = _lire(_RACINE / ".github" / "workflows" / "stale.yml")
        avec = conf["jobs"]["stale"]["steps"][0]["with"]
        self.assertIs(avec.get("exempt-draft-pr"), True)


if __name__ == "__main__":
    unittest.main()
