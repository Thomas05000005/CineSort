# -*- coding: utf-8 -*-
"""Garde-fou de syntaxe du front — le vrai, celui qui peut rougir.

CE QUI A ETE MESURE (2026-08-03, Node v24.14.1, depot sans package.json)
=======================================================================

`node --check` etait cite dans une vingtaine de bilans internes du depot comme
preuve que le JS du dashboard etait valide. Reproduction :

    $ printf '\\nconst BROKEN = ;\\n' >> web/dashboard/core/format.js
    $ node --check web/dashboard/core/format.js ; echo $?
    0

Balayage des 48 `.js` de `web/dashboard/`, meme erreur injectee a chaque fois :

    47 fichiers  -> exit 0  (FAUX VERT)
     1 fichier   -> exit 1  (web/dashboard/bootstrap-debug.js)

Cause isolee sur repro minimale : un `.js` SANS import/export est analyse en
CommonJS et l'erreur remonte ; un `.js` AVEC import/export declenche la
detection de syntaxe de module de Node, qui fait sortir le processus en 0 sans
jamais reverifier la source dans le goal « module ». `bootstrap-debug.js` est le
seul fichier charge par `<script src>` sans `type="module"` — une IIFE sans
import ni export, donc le seul reellement verifie.

CE QUE CE FICHIER VERROUILLE
============================

1. `scripts/check_js_syntax.mjs` est vert sur l'arbre reel et couvre les 49
   `.js` du dashboard (+ le `.mjs` de `web/dashboard/tests/`).
2. Le goal d'analyse de CHAQUE fichier est celui de son chargement reel.
3. MUTATION : une erreur de syntaxe injectee dans n'importe lequel des 50
   fichiers fait rougir le verificateur — les 50 sont testes.
4. MUTATION : le contrat de chargement de `bootstrap-debug.js` (script
   classique, pas de module) est verifie lui aussi.
5. MUTATION : les canaris d'auto-test du verificateur sont vivants — neutralises,
   l'outil refuse de conclure (code 2) au lieu de repasser au vert.
6. Un inventaire vide, ou un `<script src>` pointant dans le vide, sont des
   ECHECS, pas des succes silencieux.
7. `package.json` declare `"type": "module"` : la commande reflexe
   `node --check <fichier>` dit desormais la verite, elle aussi.
8. La CI lance le verificateur.

AUCUN SKIP ICI. Si `node` est absent, ces tests ECHOUENT. Un garde-fou front qui
s'evapore quand l'outil manque est exactement le mecanisme qui a produit vingt
preuves nulles ; il n'est pas reconduit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / "scripts" / "check_js_syntax.mjs"
PACKAGE_JSON = REPO / "package.json"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
DASHBOARD = REPO / "web" / "dashboard"

#: Erreur de syntaxe indiscutable, valide dans aucun goal, aucun dialecte.
MUTATION = "\nconst __MUTATION_SYNTAXE__ = ;\n"

#: Le fichier charge en `<script>` classique (sans type=module).
CLASSIC_SCRIPT = "web/dashboard/bootstrap-debug.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node est introuvable sur le PATH. C'est un ECHEC, pas un skip : sans lui, "
            "le seul garde-fou de syntaxe du front n'existe plus. Node >= 20 est requis "
            "(cf. le champ `engines` de package.json) et est preinstalle sur les runners GitHub."
        )
    return node


def _run_checker(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CHECKER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        cwd=str(cwd) if cwd else None,
    )


class OutillagePresentTests(unittest.TestCase):
    def test_node_est_disponible(self) -> None:
        """Sans node, pas de garde-fou : on echoue au lieu de se taire."""
        self.assertTrue(Path(_node()).exists())

    def test_le_verificateur_existe(self) -> None:
        self.assertTrue(CHECKER.is_file(), f"{CHECKER} manque : le garde-fou front n'a plus de moteur")

    def test_package_json_declare_type_module(self) -> None:
        """Repare aussi la commande reflexe `node --check <fichier>`.

        Sans ce manifeste, Node analyse les `.js` du depot en CommonJS et sort en
        0 sur les erreurs de syntaxe des 47 modules ESM du dashboard. Le
        verificateur, lui, ne depend pas de ce fichier (il impose `--input-type`)
        — mais toute personne qui tape `node --check` a la main en depend.
        """
        self.assertTrue(PACKAGE_JSON.is_file(), "package.json manquant a la racine")
        data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        self.assertEqual(
            data.get("type"),
            "module",
            'package.json doit declarer "type": "module" : les 49 .js de web/dashboard/ sont des '
            "modules ESM, et sans cette declaration `node --check` sort en 0 sur une erreur averee.",
        )


class VerificateurSurArbreReelTests(unittest.TestCase):
    def test_le_verificateur_est_vert_sur_le_depot(self) -> None:
        proc = _run_checker("--json")
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], f"le front a une erreur de syntaxe :\n{proc.stdout}\n{proc.stderr}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(payload["failures"], [])
        self.assertEqual(payload["problems"], [])

    def test_les_49_js_du_dashboard_sont_couverts(self) -> None:
        """L'inventaire doit couvrir TOUS les .js reellement presents.

        Le compte exact est une ANCRE : il attrape un `rglob` devenu muet, un
        deplacement de `web/dashboard/`, ou un module ajoute sans que personne
        ne verifie qu'il entre bien dans le perimetre du gate. Il passe de 48 a
        49 avec `web/dashboard/core/run-status.js` (derivation de statut de run
        partagee par /accueil et /historique) : ajouter un module du dashboard
        se declare ici, ce n'est pas un effet de bord silencieux.
        """
        proc = _run_checker("--plan", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(proc.stdout)
        couverts = {f["path"] for f in plan["files"]}

        attendus = {
            p.relative_to(REPO).as_posix() for p in sorted(DASHBOARD.rglob("*.js")) if "node_modules" not in p.parts
        }
        self.assertEqual(len(attendus), 49, f"le dashboard ne contient plus 49 .js mais {len(attendus)}")
        self.assertEqual(
            attendus - couverts,
            set(),
            "des .js du dashboard echappent au verificateur",
        )

    def test_le_goal_de_chaque_fichier_suit_son_chargement_reel(self) -> None:
        """`bootstrap-debug.js` est un script classique ; tout le reste, des modules."""
        proc = _run_checker("--plan", "--json")
        plan = json.loads(proc.stdout)
        goals = {f["path"]: f["goal"] for f in plan["files"]}

        self.assertEqual(
            goals.get(CLASSIC_SCRIPT),
            "commonjs",
            f"{CLASSIC_SCRIPT} est charge par <script src> sans type=module : "
            "l'analyser en module masquerait un import interdit dans ce fichier",
        )
        autres = {p: g for p, g in goals.items() if p != CLASSIC_SCRIPT}
        self.assertEqual(
            sorted({g for g in autres.values()}),
            ["module"],
            "tous les autres fichiers de web/ sont des modules ESM",
        )

    def test_les_canaris_du_verificateur_sont_conformes(self) -> None:
        proc = _run_checker("--self-test", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        canaries = json.loads(proc.stdout)["canaries"]
        self.assertGreaterEqual(len(canaries), 5)
        for canari in canaries:
            self.assertTrue(canari["passed"], f"canari {canari['name']} non conforme : {canari}")


class _ArbreTemporaireMixin(unittest.TestCase):
    """Copie `web/` + `scripts/` + `package.json` dans un dossier jetable.

    Les mutations se font sur la copie : l'arbre de travail n'est jamais touche.
    """

    tmp: Path
    _tmpdir: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="cinesort_jsgate_")
        cls.tmp = Path(cls._tmpdir.name)
        shutil.copytree(REPO / "web", cls.tmp / "web")
        (cls.tmp / "scripts").mkdir()
        shutil.copy2(CHECKER, cls.tmp / "scripts" / CHECKER.name)
        shutil.copy2(PACKAGE_JSON, cls.tmp / "package.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def _checker_tmp(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [_node(), str(self.tmp / "scripts" / CHECKER.name), "--root", str(self.tmp), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )

    def _fichiers_du_plan(self) -> list[str]:
        proc = self._checker_tmp("--plan", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [f["path"] for f in json.loads(proc.stdout)["files"]]


class MutationTests(_ArbreTemporaireMixin):
    """La preuve : sans erreur le verificateur est vert, avec erreur il rougit."""

    def test_une_erreur_dans_n_importe_lequel_des_50_fichiers_est_detectee(self) -> None:
        """Chaque fichier est casse a son tour, puis restaure.

        C'est la mesure qui manquait : `node --check` sortait en 0 sur 47 des 48
        `.js` du dashboard mesures le 2026-08-03. Ici, tous les fichiers du plan
        (50 aujourd'hui) doivent rougir, un par un.

        La restauration est verifiee par egalite d'octets (plus strict que « ca
        reparse »), et le vert global est reconstate une fois a la fin : si une
        restauration avait derape, la verification complete le dirait.
        """
        fichiers = self._fichiers_du_plan()
        self.assertGreaterEqual(len(fichiers), 50, f"inventaire trop maigre : {len(fichiers)}")

        depart = self._checker_tmp()
        self.assertEqual(depart.returncode, 0, f"l'arbre copie doit partir vert:\n{depart.stderr}")

        for rel in fichiers:
            with self.subTest(fichier=rel):
                cible = self.tmp / rel
                original = cible.read_bytes()
                try:
                    cible.write_bytes(original + MUTATION.encode("utf-8"))
                    # Compteur d'occurrences : la mutation est bien la, une seule fois.
                    self.assertEqual(
                        cible.read_text(encoding="utf-8").count("const __MUTATION_SYNTAXE__ = ;"),
                        1,
                        f"la mutation n'a pas ete appliquee proprement a {rel}",
                    )
                    rouge = self._checker_tmp("--only", rel)
                    self.assertEqual(
                        rouge.returncode,
                        1,
                        f"FAUX VERT : {rel} contient une erreur de syntaxe et le verificateur "
                        f"sort en {rouge.returncode}.\n{rouge.stdout}\n{rouge.stderr}",
                    )
                    self.assertIn(rel, rouge.stderr, "le rapport doit nommer le fichier fautif")
                finally:
                    cible.write_bytes(original)
                self.assertEqual(cible.read_bytes(), original, f"{rel} n'a pas ete restaure a l'octet pres")

        retour = self._checker_tmp()
        self.assertEqual(
            retour.returncode, 0, f"apres les {len(fichiers)} restaurations le gate doit reverdir:\n{retour.stderr}"
        )

    def test_une_seule_erreur_fait_rougir_la_verification_complete(self) -> None:
        """Bout en bout : le gate global, pas seulement le mode --only."""
        cible = self.tmp / "web" / "dashboard" / "views" / "traitement.js"
        original = cible.read_bytes()

        avant = self._checker_tmp()
        self.assertEqual(avant.returncode, 0, f"l'arbre copie doit partir vert:\n{avant.stderr}")

        try:
            cible.write_bytes(original + MUTATION.encode("utf-8"))
            rouge = self._checker_tmp()
            self.assertEqual(rouge.returncode, 1, f"un fichier casse doit faire echouer tout le gate:\n{rouge.stdout}")
            self.assertIn("web/dashboard/views/traitement.js", rouge.stderr)
        finally:
            cible.write_bytes(original)

        apres = self._checker_tmp()
        self.assertEqual(apres.returncode, 0, f"apres restauration le gate doit reverdir:\n{apres.stderr}")

    def test_le_contrat_de_chargement_du_script_classique_est_verifie(self) -> None:
        """Garde muee separement : `bootstrap-debug.js` ne doit pas devenir un module.

        Il est charge par `<script src>` sans `type="module"` : un `import` dans
        ce fichier planterait le boot du dashboard. Analyse en goal script, cette
        faute est vue ; analysee en goal module, elle passerait inapercue.
        """
        cible = self.tmp / CLASSIC_SCRIPT
        original = cible.read_bytes()
        try:
            cible.write_bytes(b'import { noop } from "./core/dom.js";\n' + original)
            rouge = self._checker_tmp("--only", CLASSIC_SCRIPT)
            self.assertEqual(
                rouge.returncode,
                1,
                f"un import dans un script classique doit etre refuse:\n{rouge.stdout}\n{rouge.stderr}",
            )
            self.assertIn("Cannot use import statement outside a module", rouge.stderr)
        finally:
            cible.write_bytes(original)
        vert = self._checker_tmp("--only", CLASSIC_SCRIPT)
        self.assertEqual(vert.returncode, 0, vert.stderr)

    def test_les_canaris_neutralises_font_refuser_de_conclure(self) -> None:
        """Garde muee separement : l'auto-test du verificateur est vivant.

        On rend valide le canari cense etre casse. Le verificateur constate alors
        que son propre detecteur ne detecte plus rien et sort en 2 — au lieu de
        declarer l'arbre sain, ce qui serait le faux vert d'origine reconstitue.
        """
        script = self.tmp / "scripts" / CHECKER.name
        original = script.read_text(encoding="utf-8")
        cassure = "export const BROKEN = ;"
        self.assertEqual(original.count(cassure), 1, "le canari module-syntaxe-cassee a change de forme")
        try:
            script.write_text(original.replace(cassure, "export const BROKEN = 1;"), encoding="utf-8")
            proc = self._checker_tmp()
            self.assertEqual(
                proc.returncode,
                2,
                f"canari neutralise : le verificateur doit refuser de conclure, pas verdir.\n{proc.stdout}",
            )
            self.assertIn("VERIFICATEUR NON FIABLE", proc.stderr)
        finally:
            script.write_text(original, encoding="utf-8")
        self.assertEqual(script.read_text(encoding="utf-8"), original)
        self.assertEqual(self._checker_tmp().returncode, 0)


class EchecsSilencieuxTests(_ArbreTemporaireMixin):
    """Un echec ne devient jamais un succes silencieux."""

    def test_un_inventaire_vide_est_un_echec(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_jsgate_vide_") as vide:
            proc = subprocess.run(
                [_node(), str(CHECKER), "--root", vide],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        self.assertEqual(proc.returncode, 1, "zero fichier verifie n'est pas un succes")
        self.assertIn("aucun fichier JS", proc.stderr)

    def test_un_script_src_pointant_dans_le_vide_est_un_echec(self) -> None:
        index = self.tmp / "web" / "dashboard" / "index.html"
        original = index.read_text(encoding="utf-8")
        marqueur = '<script src="./bootstrap-debug.js"></script>'
        self.assertEqual(original.count(marqueur), 1, "la balise de reference a change de forme")
        try:
            index.write_text(
                original.replace(marqueur, '<script src="./fichier-absent.js"></script>'),
                encoding="utf-8",
            )
            proc = self._checker_tmp()
            self.assertEqual(proc.returncode, 1, f"un <script src> casse doit faire echouer le gate:\n{proc.stdout}")
            self.assertIn("fichier-absent.js", proc.stderr)
        finally:
            index.write_text(original, encoding="utf-8")
        self.assertEqual(self._checker_tmp().returncode, 0)

    def test_un_fichier_inconnu_en_mode_only_est_un_echec(self) -> None:
        proc = self._checker_tmp("--only", "web/dashboard/inexistant.js")
        self.assertEqual(proc.returncode, 1, "cibler un fichier absent ne doit pas passer pour un succes")


class ContratOutillageTests(_ArbreTemporaireMixin):
    """Le verificateur ne doit pas retomber dans le piege qu'il repare."""

    def test_il_reste_juste_meme_sans_package_json(self) -> None:
        """Le test qui distingue les deux implementations possibles.

        `package.json` rend honnete la commande reflexe `node --check <chemin>`,
        mais s'y ADOSSER serait fragile : le jour ou quelqu'un retire
        `"type": "module"`, tout le garde-fou redeviendrait le faux vert
        d'origine, en silence. Le verificateur impose donc `--input-type` et
        pousse la source sur stdin, ce qui le rend independant du manifeste.

        Ici on supprime `package.json` de la copie, on casse un module ESM, et le
        verificateur doit TOUJOURS rougir. Une implementation qui se contenterait
        de `node --check <chemin>` sortirait en 0 — c'est exactement la mesure
        qui a ouvert ce lot.

        Verification par le comportement, pas par une chaine de code source :
        un test qui grepperait `--input-type` dans le script tomberait au moindre
        refactor et ne detecterait rien de reel.
        """
        manifest = self.tmp / "package.json"
        sauvegarde = manifest.read_bytes()
        cible = self.tmp / "web" / "dashboard" / "core" / "format.js"
        original = cible.read_bytes()
        try:
            manifest.unlink()
            self.assertFalse(manifest.exists())
            cible.write_bytes(original + MUTATION.encode("utf-8"))
            proc = self._checker_tmp("--only", "web/dashboard/core/format.js")
            self.assertEqual(
                proc.returncode,
                1,
                "sans package.json le verificateur doit rester juste : c'est ce qui le "
                f"distingue de `node --check <chemin>`.\n{proc.stdout}\n{proc.stderr}",
            )
        finally:
            cible.write_bytes(original)
            manifest.write_bytes(sauvegarde)
        self.assertEqual(self._checker_tmp("--only", "web/dashboard/core/format.js").returncode, 0)

    def test_la_ci_lance_le_verificateur(self) -> None:
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        # assertTrue plutot qu'assertIn : sur echec, assertIn deverse les 260
        # lignes du workflow dans le rapport et noie le message utile.
        self.assertTrue(
            "run: node scripts/check_js_syntax.mjs" in workflow,
            "ci.yml ne lance plus scripts/check_js_syntax.mjs : le verificateur ne garde plus rien",
        )


if __name__ == "__main__":
    unittest.main()
