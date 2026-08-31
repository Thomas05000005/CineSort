"""Gardes sur `scripts/measure_codebase_health.py` — le mesureur lui-meme.

Motif du depot : *un mesureur qui ne peut pas echouer ne mesure rien*. Ce
fichier attaque trois endroits ou le script rendait un chiffre propre alors
qu'il n'avait rien mesure.

1. `count_test_skips` — la docstring annonce compter les `@unittest.skip` ET
   les `@pytest.mark.skip`. Le motif `@(unittest\\.)?skip(...)` exige que
   `skip` suive IMMEDIATEMENT `@` ou `@unittest.` : il ne peut structurellement
   pas voir `@pytest.mark.skip`. MESURE 2026-08-31 sur `tests/` : le motif rend
   **27** la ou 39 decorateurs de skip existent reellement (13 `@pytest.mark.*`
   invisibles), et l'un des 27 n'est pas un decorateur mais une **mention en
   commentaire** (`tests/test_naming_properties.py:24`). Le motif n'est ancre
   nulle part : il compte le texte, pas la decoration.

2. `run_ruff_select` — documente « Retourne -1 si erreur », et `format_report`
   sait afficher « erreur ruff » pour toute valeur < 0. Mais la panne la plus
   probable (ruff absent de l'interpreteur) ne produit jamais -1. MESURE
   2026-08-31 : `python -m <module absent>` rend **rc=1, stdout vide** ; or
   rc=1 est dans la liste des codes acceptes, et `json.loads("" or "[]")` rend
   `[]`. Le rapport annonce alors **0 violation** — indiscernable d'une
   codebase propre. La branche `except FileNotFoundError` est morte :
   `sys.executable` existe toujours.

3. `gather_duplicate_components` — sort par liste vide des que `web/components/`
   n'est pas un repertoire. MESURE 2026-08-31 : ce dossier **n'existe pas** dans
   l'arbre (`web/` contient `dashboard/` et `shared/`). Le detecteur ne peut
   donc rendre qu'UNE valeur, et le rapport imprime « 0 » — un compte, pas
   l'aveu d'une absence de mesure.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "measure_codebase_health.py"


def _load_script():
    """Charge le script de mesure comme module isole (il n'est pas importable)."""
    spec = importlib.util.spec_from_file_location("_measure_codebase_health_ut", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MCH = _load_script()


# --------------------------------------------------------------------------- #
# 1. count_test_skips : le motif doit voir ce que la docstring annonce         #
# --------------------------------------------------------------------------- #
class CompteDesSkipsTests(unittest.TestCase):
    """Le compteur de skips doit couvrir les familles qu'il annonce."""

    #: Un fichier de test synthetique portant UN decorateur de chaque famille
    #: reellement utilisee dans `tests/`, plus une mention en commentaire qui
    #: ne doit PAS etre comptee.
    FIXTURE = (
        "import pytest\n"
        "import unittest\n"
        "\n"
        "\n"
        '@pytest.mark.skip(reason="pas encore portee")\n'
        "def test_un():\n"
        "    pass\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(True, reason="windows seulement")\n'
        "def test_deux():\n"
        "    pass\n"
        "\n"
        "\n"
        '@unittest.skip("obsolete")\n'
        "def test_trois():\n"
        "    pass\n"
        "\n"
        "\n"
        '@unittest.skipUnless(False, "ffmpeg absent")\n'
        "def test_quatre():\n"
        "    pass\n"
        "\n"
        "\n"
        "# Les cas lourds sont skip via @unittest.skip — MENTION, pas decorateur.\n"
        "def test_cinq():\n"
        "    pass\n"
    )

    #: 4 decorateurs, la mention en commentaire exclue.
    ATTENDU = 4

    def _mesure(self):
        # Le repertoire temporaire doit vivre SOUS la racine du depot : le
        # compteur appelle `path.relative_to(REPO_ROOT)` pour indexer ses
        # resultats et leve ValueError ailleurs.
        with tempfile.TemporaryDirectory(dir=str(REPO_ROOT)) as tmp:
            root = Path(tmp)
            (root / "test_fixture_skips.py").write_text(self.FIXTURE, encoding="utf-8")
            return MCH.count_test_skips(root)

    def test_les_quatre_familles_de_skip_sont_comptees(self) -> None:
        resultat = self._mesure()
        self.assertEqual(
            resultat["total"],
            self.ATTENDU,
            "Le motif ne voit pas toutes les familles annoncees par la docstring "
            "(@pytest.mark.skip / @pytest.mark.skipif restent invisibles).",
        )

    def test_une_mention_en_commentaire_n_est_pas_un_skip(self) -> None:
        fixture = "# Les cas lourds sont skip via @unittest.skip — MENTION, pas decorateur.\ndef test_un():\n    pass\n"
        with tempfile.TemporaryDirectory(dir=str(REPO_ROOT)) as tmp:
            root = Path(tmp)
            (root / "test_fixture_mention.py").write_text(fixture, encoding="utf-8")
            resultat = MCH.count_test_skips(root)
        self.assertEqual(
            resultat["total"],
            0,
            "Une occurrence de `@unittest.skip` en commentaire est comptee comme "
            "un test desactive : le motif compte du texte, pas une decoration.",
        )

    def test_la_raison_du_skip_est_capturee_quel_que_soit_le_prefixe(self) -> None:
        fixture = 'import pytest\n\n\n@pytest.mark.skip(reason="binaire ffmpeg absent")\ndef test_un():\n    pass\n'
        with tempfile.TemporaryDirectory(dir=str(REPO_ROOT)) as tmp:
            root = Path(tmp)
            (root / "test_fixture_raison.py").write_text(fixture, encoding="utf-8")
            resultat = MCH.count_test_skips(root)
        self.assertIn(
            "binaire ffmpeg absent",
            resultat["by_reason_short"],
            "La raison d'un skip pytest n'est pas remontee : le tableau "
            "« Raisons de skip les plus frequentes » est aveugle a pytest.",
        )

    def test_le_libelle_du_rapport_nomme_ce_qui_est_compte(self) -> None:
        """Annonce vs fait : le libelle du rapport doit citer les familles vues."""
        rapport = MCH.format_report(_donnees_rapport_minimales())
        ligne = [l for l in rapport.splitlines() if "Tests skip" in l]
        self.assertTrue(ligne, "Ligne « Tests skip » absente du rapport.")
        self.assertIn(
            "pytest.mark.skip",
            ligne[0],
            "Le libelle du rapport n'annonce pas pytest.mark.skip alors que le "
            "compteur doit le compter — troisieme encodage divergent de la meme "
            "verite (docstring, motif, libelle).",
        )


# --------------------------------------------------------------------------- #
# 2. run_ruff_select : l'erreur la plus probable doit produire -1              #
# --------------------------------------------------------------------------- #
class RuffIndisponibleTests(unittest.TestCase):
    """Ruff absent doit rendre -1 (« erreur ruff »), jamais 0 violation."""

    @staticmethod
    def _proc(returncode: int, stdout: str, stderr: str = ""):
        return subprocess.CompletedProcess(
            args=["python", "-m", "ruff"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    def test_module_ruff_absent_rend_moins_un(self) -> None:
        # Sortie REELLE mesuree le 2026-08-31 avec un module inexistant :
        #   rc=1, stdout='', stderr="...: No module named ruff\n"
        faux = self._proc(1, "", f"{sys.executable}: No module named ruff\n")
        with mock.patch.object(MCH.subprocess, "run", return_value=faux):
            valeur = MCH.run_ruff_select("BLE001", [REPO_ROOT / "cinesort"])
        self.assertEqual(
            valeur,
            -1,
            "Ruff absent est rapporte comme 0 violation : le rapport annonce une "
            "codebase propre alors que rien n'a ete mesure.",
        )

    def test_sortie_vide_avec_code_zero_rend_moins_un(self) -> None:
        faux = self._proc(0, "   \n", "")
        with mock.patch.object(MCH.subprocess, "run", return_value=faux):
            self.assertEqual(MCH.run_ruff_select("C901", [REPO_ROOT / "cinesort"]), -1)

    def test_zero_violation_reel_reste_zero(self) -> None:
        """Non-regression : une vraie sortie vide de ruff est un vrai 0."""
        faux = self._proc(0, "[]", "")
        with mock.patch.object(MCH.subprocess, "run", return_value=faux):
            self.assertEqual(MCH.run_ruff_select("C901", [REPO_ROOT / "cinesort"]), 0)

    def test_violations_reelles_sont_comptees(self) -> None:
        faux = self._proc(1, '[{"code": "C901"}, {"code": "C901"}]', "")
        with mock.patch.object(MCH.subprocess, "run", return_value=faux):
            self.assertEqual(MCH.run_ruff_select("C901", [REPO_ROOT / "cinesort"]), 2)

    def test_binaire_introuvable_rend_moins_un(self) -> None:
        with mock.patch.object(MCH.subprocess, "run", side_effect=OSError("boom")):
            self.assertEqual(MCH.run_ruff_select("C901", [REPO_ROOT / "cinesort"]), -1)


# --------------------------------------------------------------------------- #
# 3. gather_duplicate_components : « pas mesurable » != « zero doublon »       #
# --------------------------------------------------------------------------- #
class DetecteurDeComposantsDupliquesTests(unittest.TestCase):
    """Un detecteur qui ne peut rendre qu'UNE valeur ne mesure rien."""

    @staticmethod
    def _arbre_sans_desktop(base: Path) -> Path:
        web = base / "web"
        (web / "dashboard" / "components").mkdir(parents=True)
        (web / "dashboard" / "components" / "toast.js").write_text("//", encoding="utf-8")
        return web

    @staticmethod
    def _arbre_complet_sans_doublon(base: Path) -> Path:
        web = base / "web"
        (web / "components").mkdir(parents=True)
        (web / "components" / "sidebar.js").write_text("//", encoding="utf-8")
        (web / "dashboard" / "components").mkdir(parents=True)
        (web / "dashboard" / "components" / "toast.js").write_text("//", encoding="utf-8")
        return web

    def test_absence_de_dossier_ne_se_confond_pas_avec_zero_doublon(self) -> None:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            non_mesurable = MCH.gather_duplicate_components(self._arbre_sans_desktop(Path(t1)))
            mesure_a_zero = MCH.gather_duplicate_components(self._arbre_complet_sans_doublon(Path(t2)))
        self.assertNotEqual(
            non_mesurable,
            mesure_a_zero,
            "« web/components/ absent » et « les deux dossiers existent, aucun nom "
            "commun » rendent la meme valeur : le detecteur est inerte et le "
            "rapport imprime 0 sans avoir rien regarde.",
        )

    def test_les_doublons_reels_sont_toujours_detectes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp) / "web"
            (web / "components").mkdir(parents=True)
            (web / "components" / "toast.js").write_text("//", encoding="utf-8")
            (web / "dashboard" / "components").mkdir(parents=True)
            (web / "dashboard" / "components" / "toast.js").write_text("//", encoding="utf-8")
            resultat = MCH.gather_duplicate_components(web)
        self.assertIn("toast.js", repr(resultat))

    def test_le_rapport_dit_non_mesure_et_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            non_mesurable = MCH.gather_duplicate_components(self._arbre_sans_desktop(Path(tmp)))
        donnees = _donnees_rapport_minimales()
        donnees["duplicate_components"] = non_mesurable
        ligne = [l for l in MCH.format_report(donnees).splitlines() if "dupliqu" in l and "|" in l]
        self.assertTrue(ligne, "Ligne « composants dupliques » absente du rapport.")
        self.assertNotIn(
            "| 0 |",
            ligne[0],
            "Le rapport imprime « 0 » pour une mesure qui n'a pas eu lieu.",
        )


# --------------------------------------------------------------------------- #
# Jeu de donnees minimal pour format_report                                    #
# --------------------------------------------------------------------------- #
def _donnees_rapport_minimales() -> dict:
    return {
        "timestamp": "2026-08-31 00:00:00",
        "git_branch": "test",
        "git_commit": "0000000",
        "python": {
            "file_count": 0,
            "total_loc": 0,
            "long_functions_100": [],
            "very_long_functions_150": [],
            "except_exception_sites": [],
            "param_heavy_functions": [],
            "large_files_500": [],
        },
        "js": {"file_count": 0, "total_loc": 0},
        "tests": {"test_function_count": 0, "skips": {"total": 0, "by_file": {}, "by_reason_short": {}}},
        "ruff": dict.fromkeys(("BLE001", "PLR2004", "PLR0913", "C901", "SIM105", "ARG001", "B007", "RUF100"), 0),
        "lazy_imports": 0,
        "console_logs": 0,
        "duplicate_components": MCH.gather_duplicate_components(REPO_ROOT / "web"),
        "migrations": [],
    }


if __name__ == "__main__":
    unittest.main()
