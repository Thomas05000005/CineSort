"""Garde-fou regression : compte de lazy imports residuels du refactor #84.

Ce test, ajoute en M-03 (Vague M, refactor #84 etapes 2-4), borne le nombre
de lazy imports (import a l'interieur d'une fonction) qui subsistent dans le
code source `cinesort/`. Objectif : empecher qu'un dev re-introduise des
imports lazy sans documentation/justification.

Strategie :
- Issue #83 (mai 2026) avait converti 150 lazy imports sur ~165 au depart.
- M-03 (Vague M, juin 2026) a converti 4 lazy imports stdlib safes
  (settings_support.re/secrets, quality_simulator_support.re, migration_manager.Path).
- Reste 69 lazy imports volontaires, majoritairement :
  * dependances optionnelles (segno, onnxruntime, rapidfuzz, requests)
  * platform-specific (msvcrt vs fcntl dans single_instance)
  * cycles intentionnels documentes (apply_core <-> cleanup, runtime_support
    pour eviter d'importer settings_support au load module)

Si tu ajoutes un lazy import legitime, augmente la borne de SA couche dans
`MAX_LAZY_IMPORTS_BY_LAYER` et documente la raison dans
`docs/internal/REFACTOR_PLAN_84.md` section "Lazy imports residuels".

Si tu convertis des lazy imports en top-level, DIMINUE la borne correspondante
pour empecher la regression.

--- Reetalonnage 2026-08-03 (dette pre-existante, pas une regression) ---

La borne globale valait encore 69 alors que le paquet mesure en comptait 170 :
le cliquet n'avait pas ete re-etalonne apres l'eclatement de `cinesort/ui/api`
en facades (`*_support.py`), qui a deplace la majorite des imports differes
sans en supprimer. L'historique du depot ayant ete ecrase (squash public), il
est impossible d'attribuer commit par commit ; la borne etait donc morte : elle
rougissait en permanence et ne signalait plus rien.

Deux changements pour que le cliquet redevienne utile plutot que juste vert :

1. Le perimetre exclut `cinesort/tests/`. Le docstring parle du "code source" ;
   du code de test qui importe dans une methode de test n'est pas la dette que
   #84 traque, et son bruit polluait le compte (7 imports).
2. La borne globale unique est remplacee par une borne PAR COUCHE. Une borne
   globale laissait passer un echange silencieux (ajouter un import differe
   dans `domain` en en supprimant un dans `ui` gardait le total identique) ;
   or c'est justement dans les couches basses qu'un import differe trahit un
   cycle. Les bornes sont posees a la valeur EXACTE mesuree : tout ajout,
   dans n'importe quelle couche, fait rougir.

Ces bornes constatent une dette, elles ne l'absolvent pas : 116 des 170 imports
differes visent `cinesort.*` (donc des cycles internes, la cible reelle de #84).

--- Lot #554 / #595 / #779 (2026-08-05) : 172 -> 114 ---

Toutes les bornes ci-dessous ont ete RE-MESUREES apres conversion (walk AST du
paquet, meme code que ce test), jamais calculees de tete a partir de la valeur
precedente. Le 2026-08-05, deux PR avaient chacune derive leur chiffre de 113 :
elles ne concordaient que par chance.

Deux familles converties :

1. STDLIB (#554, #595) — 24 imports differes de la bibliotheque standard
   promus en tete. Un import differe de stdlib n'a jamais de justification par
   cycle : la stdlib ne remonte jamais vers le projet. 6 subsistent, tous
   justifies : `msvcrt`/`fcntl` (x4, specifiques a la plateforme : importer
   `msvcrt` sur Linux leve ImportError) et `ctypes` (x2, sous `except
   ImportError` explicite dans une detection best-effort du type de stockage —
   un import de tete transformerait une degradation en echec de chargement).

2. INTRA-`ui/api` (#779) — 34 imports differes internes convertis. Cartographie
   AST prealable : sur les 59 imports differes intra-`ui/api`, seuls 4 sont
   poses sur une VRAIE arete de retour de tete (`library_support` <->
   `library_actions_support` x3, `reset_support` -> `cinesort_api`). Les 55
   autres n'avaient aucun cycle a contourner. Le cout de demarrage invoque
   n'existait pas non plus : `cinesort_api.py` importe DEJA en tete 26 modules
   `*_support`, donc ils sont charges au boot de toute facon.

Non convertis deliberement, avec leur raison :
  * les sites dont le `try` englobant attrape `ImportError` en tete de tuple
    (`run_flow_support` x5, `quality_audit_support` x1) : l'import differe y est
    un contrat de degradation (post-scan best-effort), un import de tete le
    transformerait en echec de boot sur un build EXE ampute ;
  * `runtime_support._safe_read_settings_for_diag` : sa docstring invoque un
    cycle qui n'existe PAS (mesure : aucune arete de retour), mais la fonction
    est un DIAGNOSTIC entoure d'un `except Exception` — elle doit survivre a un
    `settings_support` casse. Conserve pour cette raison-la, pas pour la raison
    affichee ;
  * `film_support` <-> `history_support` : reference mutuelle reelle, une des
    deux directions doit rester differee ; arbitrer laquelle depasse ce lot.

Piege rencontre pendant ce lot (trouve par MUTATION, pas par relecture) : un
import differe `from X import f` ne se convertit PAS en
`from X import f` de tete quand `X` est un module `ui/api`. Un import de
symbole lie l'objet au chargement, donc un
`patch("cinesort.ui.api.library_support._get_store")` pose par un test ne
l'atteint plus. Premiere version de ce lot : `history_support` importait
`_get_store` par symbole -> `tests/test_get_plan_ignored_alerts_v77.py` rouge.
Corrige en MODULE-STYLE (`from cinesort.ui.api import library_support` +
`library_support._get_store(...)`), qui garde la resolution tardive. Les imports
par symbole ne restent que pour les helpers `domain.*` purs et les constantes.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

# Sous-arbres de `cinesort/` hors perimetre "code source".
EXCLUDED_DIRS = frozenset({"tests", "__pycache__"})

# Cliquet par couche — valeurs EXACTES mesurees le 2026-08-03 (zero marge).
# A diminuer des qu'on convertit ; a augmenter UNIQUEMENT avec doc dans
# REFACTOR_PLAN_84.md. `__root__` = modules a la racine du paquet.
MAX_LAZY_IMPORTS_BY_LAYER: dict[str, int] = {
    "__root__": 3,
    # 23 -> 25 (PR#852, +2). Les DEUX imports differes ont ete verifies un par
    # un, et ils ne sont pas du meme genre :
    #   - `cleanup` -> `apply_core._append_error_message` : VRAI CYCLE.
    #     `apply_core.py:15` importe deja `cinesort.app.cleanup`. Un import de
    #     tete casserait l'import du paquet.
    #   - `apply_batches_reconciliation` -> `apply_audit.read_apply_audit` : PAS
    #     de cycle. MAJ a la fusion avec main : `apply_audit` n'importe plus
    #     seulement la stdlib, il tire `infra.log_scrubber` (issue #414, scrub
    #     des secrets du journal JSONL) qui tire `infra.log_context`. Le verdict
    #     ne change pas — le contrat `infra_bounded` interdit a `infra` de
    #     remonter vers `app`, donc toujours aucun cycle a contourner. Le
    #     commentaire du code dit « eviter de charger au boot », mais la vraie
    #     raison est le `except ImportError` juste en dessous : sur un build EXE
    #     AMPUTE, un import de tete tuerait tout le module de reconciliation, la
    #     ou l'import local ne degrade que la lecture du marqueur. Cette raison
    #     se RENFORCE avec la chaine d'import allongee. Conserve pour elle, pas
    #     pour la raison affichee.
    #
    # 25 -> 19 (#554/#595, -6) : CONVERSIONS stdlib. `apply_core.sha1_quick`
    # portait `import time as _time_mod` alors que `time` est deja importe
    # ligne 7 — le commentaire « local pour eviter shadow du module time haut »
    # decrivait un shadow qui n'existe plus dans la fonction (verifie : aucun
    # parametre ni variable locale nommee `time`). Idem `json` dans
    # `apply_batches_reconciliation._close_batch` et `time` dans
    # `plan_support_core.wait_while_paused` : deja en tete, alias redondant.
    # Ajoutes en tete : `os` (plan_support_core), `contextlib`
    # (plan_support_replan), `concurrent.futures.ThreadPoolExecutor`
    # (_local_candidate).
    "app": 19,
    "data": 0,
    # 16 -> 15 (#554/#595, -1) : `lpips_compare._resolve_model_path` importait
    # `sys` dans la fonction pour lire `sys.frozen`.
    "domain": 15,
    # 17 -> 11 (#554/#595, -6) : `tools_manager` x2 (`import sys as _sys`,
    # les deux sites nommes par #554), `poster_proxy` x2 (`json`),
    # `rest_server` (`urllib.parse.parse_qs`, le module importe deja `urlsplit`
    # de la meme provenance en tete), `probe/service.__init__`
    # (`shutil.which`). Restent 6 imports differes stdlib dans `infra`, tous
    # justifies : `msvcrt`/`fcntl` x4 (specifiques a la plateforme) et
    # `ctypes` x1 (sous garde `except ImportError`).
    "infra": 11,
    # 110 -> 111 : +1 pour `history_support.get_plan_row`, importe tardivement
    # dans `film_support` (PR#853). Ce n'est pas un choix de confort : les deux
    # modules se referencent mutuellement, un import de tete cree un cycle a
    # l'import du paquet. Justification detaillee dans REFACTOR_PLAN_84.md.
    # A cette date-la le TOTAL restait a 170, `app` rendant le point que `ui`
    # prenait. Ce n'est plus vrai : PR#847 (+2 ici) et PR#852 (+2 sur `app`)
    # l'ont porte a 174. La compensation etait une coincidence, pas une regle —
    # seule la borne PAR COUCHE fait foi.
    # 111 -> 113 (PR#847, +2) : `quality_report_support` importe tardivement
    # `run_read_support.full_langs_from_embedded` et
    # `domain.subtitle_helpers._normalize_iso639`.
    #
    # Honnetement : je n'ai PAS pu etablir de cycle dur pour ces deux-la —
    # `run_read_support` n'importe pas `quality_report_support` en retour. Ils
    # suivent le motif deja etabli dans le module (`dashboard_support.py:300-309`
    # importe `run_read_support` tardivement a QUATRE endroits), donc les
    # convertir isolement n'aurait pas de sens : c'est le motif entier qui
    # demande un nettoyage, et il depasse le perimetre de cette PR.
    # A reprendre dans le chantier de conversion de la couche `ui`.
    #
    # 113 -> 111 (issue #599, -2) : CONVERSION, pas relevement.
    # `film_support._fetch_tmdb_extras` portait `from cinesort.infra.tmdb_client
    # import TmdbClient` et `import requests as _req` a l'interieur de la
    # fonction. Aucun cycle a contourner : `infra` ne remonte jamais vers `ui`
    # (contrat `infra_bounded`). L'import de `requests` a purement disparu avec
    # le GET direct, rapatrie sur `TmdbClient.get_movie_extras`.
    #
    # 111 -> 66 (#554/#595/#779, -45) : le « chantier de conversion de la couche
    # ui » que la note PR#847 ci-dessus renvoyait a plus tard.
    #   - 11 stdlib (#595) : `cinesort_api` (io, webbrowser, datetime,
    #     subprocess, sys), `perceptual_support` (base64 x3, io),
    #     `library_actions_support` (time, deja en tete), `run_flow_support`
    #     (threading, deja en tete).
    #   - 34 internes (#779), dont les 13 de `dashboard_support` et les 10 de
    #     `history_support` : ce sont les clusters 2 et 3 nommes par l'issue.
    #     Aucun n'etait pose sur une arete de retour de tete (mesure AST) et
    #     aucun ne coutait de temps de boot : `cinesort_api.py:60` importe deja
    #     en tete les 26 modules `*_support`.
    #     Ecrits en MODULE-STYLE (`from cinesort.ui.api import run_read_support`
    #     + `run_read_support.effective_flags(...)`) et NON en import de symbole,
    #     pour que les `patch("cinesort.ui.api.<mod>.<fn>")` des tests restent
    #     operants — cf. le piege decrit dans le docstring.
    #
    # 66 -> 63 (lot perf #448/#406/#467/#593, -3) : `library_audit_support`
    # construisait un TmdbClient DANS le corps de `_fetch_collection_parts`,
    # avec 3 imports differes (infra.state, infra.tmdb_client.TmdbClient,
    # settings_support.normalize_user_path). Le client est desormais construit
    # une seule fois par appel via `_build_tmdb_client_optional`, deja present
    # dans `library_actions_support` : les 3 imports remontent en tete, sans
    # cycle (lint-imports : 3 contrats KEPT).
    #
    # 63 est MESURE sur l'arbre fusionne, pas 66-3. Les deux conversions sont
    # arrivees en parallele et le 2026-08-05 deux PR ont deja calcule leur
    # valeur de tete a partir d'une base commune : elles concordaient PAR
    # CHANCE. Ici, la mesure d'abord, l'ecriture ensuite.
    #
    # 63 -> 56 (#779 vague 2, -7) : le reliquat intra-`ui/api` que la vague 1
    # (PR#930) avait laisse. Re-mesure du graphe avant de coder : l'issue annonce
    # 89 imports differes intra-`ui/api`, il en restait 31 statements. Sur ces 31,
    # 4 seulement sont poses sur une VRAIE arete de retour de tete
    # (`library_support` <-> `library_actions_support` x3, `reset_support` ->
    # `cinesort_api`). Parmi les 27 restants, 7 n'avaient NI cycle NI contrat de
    # degradation, et sont convertis ici :
    #   - `perceptual_support._build_tmdb_client` : `normalize_user_path` etait
    #     DEJA importe en tete du meme module — alias purement redondant ;
    #   - `library_actions_support._build_cfg_for_row` : `settings_support` etait
    #     deja une dependance de tete (`normalize_user_path`), differer un second
    #     symbole du meme module ne differait rien ;
    #   - `run_read_support` x2 (`library_support._get_store`) : le cluster n.2
    #     nomme par #779, sa « PR pilote » ;
    #   - `library_actions_support` + `tmdb_support` (`run_data_support`) : leur
    #     commentaire admettait avoir FUSIONNE deux imports en un statement pour
    #     ne pas faire monter ce cliquet — l'artefact disparait avec la cause ;
    #   - `facades/settings_facade.get_confidence_thresholds` : aucun garde.
    #
    # NON convertis, avec la raison mesuree :
    #   - `run_facade` x3 (`schemas`) et `apply_support` x2 : leur `try` attrape
    #     `ImportError` — l'import differe y est un contrat de degradation
    #     (pydantic absent, build EXE ampute), pas un contournement de cycle ;
    #   - `runtime_support` x3 : `except Exception` englobant, qui attrape
    #     `ImportError` lui aussi (dont `_safe_read_settings_for_diag`, un
    #     diagnostic qui doit survivre a un `settings_support` casse) ;
    #   - `film_support` <-> `history_support` et `library_support` <->
    #     `library_actions_support` : aretes de retour REELLES, une direction au
    #     moins doit rester differee.
    #
    # 56 est MESURE sur l'arbre final (walk AST, meme code que ce test), pas 63-7.
    "ui": 56,
}

# Borne globale = somme des bornes par couche (114 apres le lot #554/#595/#779).
# Gardee pour que le message d'erreur donne l'ordre de grandeur, jamais saisie
# a la main : c'est la somme qui suit les bornes, jamais l'inverse.
MAX_LAZY_IMPORTS = sum(MAX_LAZY_IMPORTS_BY_LAYER.values())


class _LazyImportCounter(ast.NodeVisitor):
    """Compte les `import` ou `from ... import` a l'interieur de fonctions."""

    def __init__(self) -> None:
        self.depth = 0
        self.count = 0
        self.locations: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        if self.depth > 0:
            self.count += 1
            names = ",".join(a.name for a in node.names)
            self.locations.append((node.lineno, f"import {names}"))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.depth > 0:
            self.count += 1
            mod = node.module or ""
            names = ",".join(a.name for a in node.names)
            self.locations.append((node.lineno, f"from {mod} import {names}"))


def _count_lazy_imports(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Compte les imports differes de `root`, par couche et par fichier."""
    by_layer: dict[str, int] = dict.fromkeys(MAX_LAZY_IMPORTS_BY_LAYER, 0)
    by_file: dict[str, int] = {}
    for dirpath, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for fname in fnames:
            if not fname.endswith(".py"):
                continue
            path = Path(dirpath) / fname
            try:
                src = path.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            visitor = _LazyImportCounter()
            visitor.visit(tree)
            if visitor.count <= 0:
                continue
            rel_in_pkg = path.relative_to(root).as_posix()
            layer = rel_in_pkg.split("/")[0] if "/" in rel_in_pkg else "__root__"
            by_layer[layer] = by_layer.get(layer, 0) + visitor.count
            by_file[str(path.relative_to(root.parent)).replace("\\", "/")] = visitor.count
    return by_layer, by_file


class TestRefactor84LazyImportProgress(unittest.TestCase):
    """Borne le nombre de lazy imports residuels apres M-03 / refactor #84."""

    def test_lazy_imports_bounded(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        cinesort_dir = repo_root / "cinesort"
        by_layer, by_file = _count_lazy_imports(cinesort_dir)

        top_files = "\n".join(f"  {c:3d}  {p}" for p, c in sorted(by_file.items(), key=lambda x: -x[1])[:15])
        over = {
            layer: (count, MAX_LAZY_IMPORTS_BY_LAYER.get(layer, 0))
            for layer, count in by_layer.items()
            if count > MAX_LAZY_IMPORTS_BY_LAYER.get(layer, 0)
        }
        self.assertEqual(
            over,
            {},
            msg=(
                "Imports differes en hausse (couche: mesure > borne) : "
                + ", ".join(f"{k}: {c} > {b}" for k, (c, b) in sorted(over.items()))
                + f"\nTotal mesure = {sum(by_layer.values())} (borne globale {MAX_LAZY_IMPORTS}).\n"
                "Soit on a regresse (ajout d'un import differe), soit on a converti et il "
                "faut BAISSER la borne de la couche dans MAX_LAZY_IMPORTS_BY_LAYER.\n\n"
                f"Top fichiers :\n{top_files}"
            ),
        )

    def test_known_converted_in_m03_stay_top_level(self) -> None:
        """Verifie que les 4 conversions M-03 ne sont pas regressees.

        Si quelqu'un re-introduit `import secrets as _secrets` localement
        dans settings_support.apply_settings_defaults, ce test catch.
        """
        repo_root = Path(__file__).resolve().parent.parent
        # Les 4 fichiers convertis en M-03
        files_and_imports_top = [
            ("cinesort/ui/api/settings_support.py", ["import secrets", "import re"]),
            ("cinesort/ui/api/quality_simulator_support.py", ["import re"]),
        ]
        for relpath, expected_top in files_and_imports_top:
            path = repo_root / relpath
            src = path.read_text(encoding="utf-8")
            for imp in expected_top:
                self.assertIn(
                    imp,
                    src.split("\n\ndef ")[0],  # header avant le 1er def
                    msg=f"{relpath}: {imp!r} doit etre top-level (M-03 conversion)",
                )


if __name__ == "__main__":
    unittest.main()
