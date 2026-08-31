# -*- coding: utf-8 -*-
"""Le SAST du depot ne scannait pas le fichier le plus sensible du depot.

Le defaut
---------
`bandit.yml` lancait `bandit -r cinesort/`. `app.py` — 1200 lignes, le point
d'entree de l'application, qui porte le boot desktop ET le passage du jeton REST
sous `?ntoken=` — n'etait donc PAS scanne.

Et pas seulement par bandit. Mesure du 2026-08-31 : `app.py` echappait a SIX
controles statiques a la fois, tous bornes a `cinesort/`. LES SIX SONT
DESORMAIS FERMES — cette liste est tenue a jour parce qu'un recensement qui
reste fige devient un document qui ment :

    bandit                  .github/workflows/bandit.yml              #1190
    mypy                    .github/workflows/mypy.yml                #1191
    budget de taille        tests/test_function_size_budget.py        ferme
    cliquet except OSError  tests/test_sqlite_error_hors_...py        ferme
    cliquet imports lazy    tests/test_refactor_84_progress_v77.py    ferme
    contrat symboles morts  tests/test_contract_dead_symbols.py       ferme

Ce que les quatre derniers ont revele, chacun mesure :

  - budget de taille : 13 fonctions au-dessus du seuil hors `cinesort/`, dont
    `app.py::main` a 525 lignes et `scripts/observe.py::observe_dashboard` a
    524. Entrees a leur taille exacte, marge zero.
  - cliquet except OSError : ZERO site nouveau. Un elargissement gratuit se
    fait pendant qu'il est gratuit ; sinon il ne se fait jamais.
  - imports lazy : 42 dans le seul `app.py`, soit 41 % de plus que tout
    `cinesort/`, et aucun n'etait compte. L'elargissement a aussi revele que
    ce cliquet n'echouait qu'a la HAUSSE, et qu'une de ses bornes etait deja
    PERIMEE (couche `app` : 19 pour 18 sites reels).
  - symboles morts : ZERO mort nouveau dans `app.py`. `scripts/` est reste
    dehors pour une raison MESUREE, ecrite dans ce fichier-la : ce contrat
    compare des NOMS, et un homonyme dans un script RESSUSCITE un symbole
    reellement mort.

Ce que l'elargissement a revele
-------------------------------
Huit findings jamais vus, dont un **B602 HIGH/HIGH** (`shell=True`) dans
`scripts/run_lighthouse.py:95`. Aucun n'est une surprise une fois lu — les
`0.0.0.0` d'`app.py` sont gouvernes par un reglage — mais aucun n'etait COMPTE,
donc rien n'aurait signale un neuvieme.

Pourquoi un test, et pas seulement la ligne corrigee
----------------------------------------------------
Un perimetre est une valeur dans un fichier de configuration : il se retrecit
d'un coup d'editeur, sans erreur et sans bruit. Ce test derive la liste du
DEPOT — tout repertoire portant du Python doit etre soit scanne, soit
explicitement exclu avec sa raison. Un repertoire cree demain sera signale.
"""

from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

import yaml

_RACINE = Path(__file__).resolve().parents[1]
_WORKFLOW = _RACINE / ".github" / "workflows" / "bandit.yml"

#: Repertoires portant du Python que bandit ne scanne PAS, et pourquoi.
#: Une exclusion sans raison ecrite est une exclusion qu'on ne peut pas relire.
_EXCLUSIONS_JUSTIFIEES = {
    "tests": (
        "les tests sont pleins d'asserts nus (B101) et de fixtures qui IMITENT "
        "des secrets — c'est leur role. Le depot skippe deja B101 ; scanner "
        "tests/ noierait le signal dans ses propres doublures."
    ),
    "docs": (
        "captures de sortie et scripts de diagnostic archives d'anciennes "
        "campagnes : ils ne sont ni livres, ni executes par un workflow."
    ),
    "runtime_hooks": ("un seul hook PyInstaller, execute AVANT l'interpreteur applicatif. A reevaluer s'il grossit."),
}


def _perimetre_declare() -> set:
    """Les cibles passees a `bandit -r` dans le workflow."""
    texte = io.open(_WORKFLOW, encoding="utf-8").read()
    m = re.search(r"bandit\s+-r\s+([^\n\\]+)", texte)
    assert m, "aucune invocation `bandit -r` trouvee dans le workflow"
    return {c.strip().rstrip("/") for c in m.group(1).split() if c.strip()}


def _sources_python_de_premier_niveau() -> set:
    """Repertoires et fichiers `.py` de premier niveau, hors caches et venv."""
    trouves = set()
    for entree in _RACINE.iterdir():
        nom = entree.name
        if nom.startswith(".") or nom in {"__pycache__", "build", "dist"}:
            continue
        if nom.startswith("venv") or nom.startswith(".venv"):
            continue
        if entree.is_file() and entree.suffix == ".py":
            trouves.add(nom)
        elif entree.is_dir() and any(entree.rglob("*.py")):
            trouves.add(nom)
    return trouves


class LeSASTCouvreLeCodeQuIlPRETENDCouvrirTests(unittest.TestCase):
    def setUp(self) -> None:
        self.perimetre = _perimetre_declare()
        self.sources = _sources_python_de_premier_niveau()

    def test_le_balayage_TROUVE_quelque_chose(self) -> None:
        """Garde anti-silence. Un `iterdir` qui ne rend plus rien — renommage,
        execution depuis un autre repertoire — ferait passer les assertions
        suivantes sur des ensembles vides."""
        self.assertGreaterEqual(len(self.sources), 4, f"balayage vide : {self.sources}")
        self.assertIn("cinesort", self.sources)
        self.assertIn("app.py", self.sources, "le fichier au coeur du defaut a disparu du balayage")
        self.assertGreaterEqual(len(self.perimetre), 1, "perimetre bandit illisible")

    def test_app_py_est_SCANNE(self) -> None:
        """Le cas qui a mordu : 1200 lignes, le boot et le jeton REST, hors SAST."""
        self.assertIn(
            "app.py",
            self.perimetre,
            "`app.py` porte le boot desktop et le passage du jeton REST, et "
            "n'etait scanne par AUCUN des six controles statiques du depot",
        )

    def test_tout_repertoire_python_est_SCANNE_ou_EXCLU_avec_sa_raison(self) -> None:
        """Un repertoire cree demain ne doit pas entrer dans un angle mort."""
        non_traites = sorted(
            nom for nom in self.sources if nom not in self.perimetre and nom not in _EXCLUSIONS_JUSTIFIEES
        )
        self.assertEqual(
            non_traites,
            [],
            f"repertoire(s) portant du Python ni scannes ni exclus : {non_traites}. "
            "Les ajouter a `bandit -r` dans le workflow (et remesurer le PLAFOND), "
            "ou les inscrire dans _EXCLUSIONS_JUSTIFIEES avec la raison.",
        )

    def test_les_exclusions_PORTENT_une_raison(self) -> None:
        """Contre-epreuve : sans ce controle, il suffirait d'ajouter un nom a la
        liste pour faire taire le test precedent. Une exclusion muette est une
        exclusion qu'on ne peut pas relire dans six mois."""
        for nom, raison in _EXCLUSIONS_JUSTIFIEES.items():
            with self.subTest(exclusion=nom):
                self.assertGreater(len(raison.strip()), 40, f"l'exclusion de `{nom}` n'explique rien")

    def test_le_PLAFOND_du_cliquet_est_lisible_et_borne(self) -> None:
        """Elargir le perimetre sans remesurer le plafond ferait echouer la CI —
        et le laisser a une valeur enorme le rendrait decoratif."""
        texte = io.open(_WORKFLOW, encoding="utf-8").read()
        m = re.search(r"^\s*PLAFOND\s*=\s*(\d+)", texte, re.MULTILINE)
        self.assertIsNotNone(m, "PLAFOND introuvable dans le workflow")
        plafond = int(m.group(1))
        self.assertGreater(plafond, 0)
        self.assertLess(plafond, 200, "un plafond aussi haut ne borne plus rien")

    def test_le_workflow_reste_du_YAML_VALIDE(self) -> None:
        """L'elargissement passe par une ligne de commande multi-lignes : une
        continuation cassee rendrait le workflow inexecutable, ce qu'aucune des
        assertions textuelles ci-dessus ne verrait.

        On ne suppose PAS le nom du job — une premiere version attendait `scan`,
        alors qu'il s'appelle `bandit` : le test rougissait sur son propre
        prejuge, pas sur un defaut. On verifie ce qui compte : le YAML se parse,
        un job existe, et l'invocation elargie survit au parsing."""
        conf = yaml.safe_load(io.open(_WORKFLOW, encoding="utf-8").read())
        self.assertIn("jobs", conf)
        self.assertTrue(conf["jobs"], "aucun job dans le workflow")

        commandes = [str(etape.get("run") or "") for job in conf["jobs"].values() for etape in (job.get("steps") or [])]
        invocations = [c for c in commandes if "bandit -r" in c]
        self.assertEqual(len(invocations), 1, "il doit y avoir exactement une invocation bandit")
        for cible in ("cinesort/", "app.py", "scripts/"):
            with self.subTest(cible=cible):
                self.assertIn(cible, invocations[0])


if __name__ == "__main__":
    unittest.main()
