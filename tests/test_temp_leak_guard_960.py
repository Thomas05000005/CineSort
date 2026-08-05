"""Tests du garde-fou anti-fuite de dossiers temporaires (issue #960).

Le garde-fou vit dans `tests/_temp_leak_guard.py`. On ne peut pas l'eprouver
depuis l'interieur de la session courante (ses fixtures sont deja installees),
donc chaque cas lance une session pytest FILLE sur un fichier de test jetable,
avec le garde-fou charge en plugin (`-p tests._temp_leak_guard`), et regarde le
code de sortie et le rapport.

Ce que ces tests verrouillent :
  - une session qui laisse des dossiers derriere elle devient ROUGE ;
  - une session propre reste VERTE (pas de faux positif) ;
  - les deux bornes (total et par famille de prefixe) mordent chacune ;
  - les DEFAUTS livres attrapent un fichier qui cesse de nettoyer ;
  - `CINESORT_TEMP_LEAK_GUARD=0` desactive vraiment tout ;
  - un `TemporaryDirectory` encore reference n'est PAS accuse (le GC force
    avant le comptage declenche son finalizer).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

from tests._temp_leak_guard import BOX_PREFIX, build_report, sweep_stale_boxes, verdict

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Un test qui cree 5 dossiers temporaires du MEME prefixe et n'en nettoie
# aucun : c'est la forme exacte d'une regression reelle (un fichier de tests
# qui oublie son nettoyage), et elle doit tomber sur la borne PAR FAMILLE.
_LEAKY = """
import tempfile

def test_leaks_five():
    for _ in range(5):
        tempfile.mkdtemp(prefix="leak960_")
    assert True
"""

# Le meme, mais propre : TemporaryDirectory refermee dans la foulee.
_CLEAN = """
import tempfile

def test_is_clean():
    for _ in range(5):
        with tempfile.TemporaryDirectory(prefix="clean960_"):
            pass
    assert True
"""

# Un TemporaryDirectory pris dans un CYCLE de references : plus aucune variable
# ne le designe a la fin du test, mais le comptage de references seul ne peut
# pas le liberer -- il faut passer le ramasse-miettes. Son finalizer nettoiera
# le dossier, ce n'est donc PAS une fuite : le garde-fou ne doit pas l'accuser.
# C'est exactement ce que verrouille le `gc.collect()` avant comptage.
_DEFERRED = """
import tempfile

def test_reference_cycles_are_collected():
    for _ in range(5):
        td = tempfile.TemporaryDirectory(prefix="defer960_")
        cycle = {"td": td}
        cycle["self"] = cycle
    assert True
"""


def _run_child(workdir: Path, body: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Lance une session pytest fille sur un fichier de test jetable."""
    target = workdir / "test_child_960.py"
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    env = dict(os.environ)
    # Le plugin est charge par son nom de module : le depot doit etre importable.
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_REPO_ROOT) + (os.pathsep + existing if existing else "")
    env.pop("CINESORT_TEMP_LEAK_GUARD", None)
    env.pop("CINESORT_TEMP_LEAK_MAX", None)
    env.pop("CINESORT_TEMP_LEAK_MAX_FAMILY", None)
    # %TEMP% dedie a la session fille, sous notre dossier de travail : sinon ce
    # qu'elle fait fuir volontairement (et son propre basetemp pytest) atterrit
    # dans le %TEMP% de la session MERE, qui l'accuserait a son tour.
    child_tmp = workdir / f"tmp{len(list(workdir.iterdir()))}"
    child_tmp.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR"):
        env[name] = str(child_tmp)
    env.update(env_extra or {})
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests._temp_leak_guard",
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _reported_count(output: str) -> int:
    """Extrait le nombre de dossiers annonce par le rapport.

    Assertion bornee : on lit l'entier, on ne cherche pas la sous-chaine "3"
    (qui matcherait aussi "15" ou "50").
    """
    match = re.search(r"Fuite de dossiers temporaires : (\d+) entree\(s\)", output)
    assert match is not None, f"rapport de fuite absent de la sortie :\n{output}"
    return int(match.group(1))


def _responsible_section(output: str) -> str:
    """Isole la section « Tests responsables » du rapport.

    Chercher le nom du test coupable dans TOUTE la sortie ne prouve rien : le
    resume `short test summary info` de pytest le contient deja. La mutation
    qui desactive l'attribution restait donc verte. On borne la recherche a la
    section qui est censee le nommer.
    """
    start = output.find("Tests responsables")
    assert start != -1, f"section « Tests responsables » absente :\n{output}"
    end = output.find("Correctif :", start)
    return output[start : end if end != -1 else len(output)]


class TempLeakGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        # tmp_path de pytest n'est pas accessible ici : on cree le dossier de
        # travail nous-memes, et on le nettoie via addCleanup (ce fichier ne
        # doit surtout pas faire fuir ce qu'il denonce).
        import shutil
        import tempfile

        self.work = Path(tempfile.mkdtemp(prefix="guard960_"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_leaking_session_turns_red(self) -> None:
        proc = _run_child(self.work, _LEAKY)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, f"la session fuyante aurait du echouer :\n{out}")
        self.assertEqual(_reported_count(out), 5, out)
        self.assertIn("leak960_*", out)
        # Le rapport doit NOMMER le test coupable, pas seulement donner un total
        # — et le nommer dans SA section, pas ailleurs dans la sortie pytest.
        section = _responsible_section(out)
        self.assertIn("test_leaks_five", section)
        self.assertNotIn("<inconnu>", section)

    def test_clean_session_stays_green(self) -> None:
        proc = _run_child(self.work, _CLEAN)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"une session propre ne doit pas echouer :\n{out}")
        self.assertNotIn("Fuite de dossiers temporaires", out)

    def test_temporarydirectory_in_reference_cycle_is_not_accused(self) -> None:
        proc = _run_child(self.work, _DEFERRED)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"un TemporaryDirectory dans un cycle n'est pas une fuite :\n{out}")

    def test_guard_can_be_disabled(self) -> None:
        proc = _run_child(self.work, _LEAKY, {"CINESORT_TEMP_LEAK_GUARD": "0"})
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertNotIn("Fuite de dossiers temporaires", out)

    def test_bounds_tolerate_exactly_the_limit(self) -> None:
        env = {"CINESORT_TEMP_LEAK_MAX": "5", "CINESORT_TEMP_LEAK_MAX_FAMILY": "5"}
        proc = _run_child(self.work, _LEAKY, env)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"5 fuites avec des bornes de 5 doivent passer :\n{out}")

    def test_total_bound_fires_one_over_the_limit(self) -> None:
        env = {"CINESORT_TEMP_LEAK_MAX": "4", "CINESORT_TEMP_LEAK_MAX_FAMILY": "99"}
        proc = _run_child(self.work, _LEAKY, env)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, f"5 fuites avec un total de 4 doivent echouer :\n{out}")
        self.assertEqual(_reported_count(out), 5, out)
        # Les bornes annoncees sont bien celles demandees, et pas les defauts.
        self.assertIn("(bornes : total 4, par famille 99)", out)
        self.assertIn("total 5 > 4", out)

    def test_family_bound_fires_even_when_the_total_is_fine(self) -> None:
        """Le cas qui compte : 5 dossiers d'un meme prefixe sous un total large.

        C'est la forme d'une regression reelle. Sans borne par famille, un total
        genereux (12) laisserait repasser les 15 dossiers de `omdb_test_` ou les
        14 de `probe_test_`.
        """
        env = {"CINESORT_TEMP_LEAK_MAX": "99", "CINESORT_TEMP_LEAK_MAX_FAMILY": "4"}
        proc = _run_child(self.work, _LEAKY, env)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, f"5 dossiers d'une meme famille > 4 doivent echouer :\n{out}")
        self.assertIn("famille leak960_* : 5 > 4", out)

    def test_default_bounds_catch_a_file_that_stops_cleaning_up(self) -> None:
        """Sans reglage, les DEFAUTS livres doivent attraper la regression."""
        proc = _run_child(self.work, _LEAKY)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, f"les bornes par defaut doivent mordre :\n{out}")


class SweepStaleBoxesTests(unittest.TestCase):
    """Le balayage de demarrage recupere les bacs a sable des sessions mortes.

    Quelques dossiers resistent a la suppression de fin de session : leur handle
    n'est relache qu'a la mort du processus pytest. Sans ce balayage, la derive
    reprendrait — plus lentement, mais elle reprendrait.
    """

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.temp = Path(tempfile.mkdtemp(prefix="sweep960_"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def _box(self, name: str, age_s: float) -> Path:
        box = self.temp / name
        box.mkdir()
        (box / "residu").mkdir()
        stamp = time.time() - age_s
        os.utime(box, (stamp, stamp))
        return box

    def test_removes_only_old_boxes_of_our_own_prefix(self) -> None:
        old = self._box(f"{BOX_PREFIX}111", age_s=10_000.0)
        fresh = self._box(f"{BOX_PREFIX}222", age_s=1.0)
        # Meme age que `old`, mais ce n'est pas un bac a sable a nous : un
        # balayage qui l'emporterait detruirait les donnees d'un autre outil.
        foreign = self._box("autre_outil_333", age_s=10_000.0)
        # Prefixe correct mais suffixe non numerique : ce n'est pas un PID.
        not_a_pid = self._box(f"{BOX_PREFIX}abc", age_s=10_000.0)

        removed = sweep_stale_boxes(self.temp, max_age_s=3600.0)

        self.assertEqual(removed, 1)
        self.assertFalse(old.exists(), "le bac perime devait etre supprime")
        self.assertTrue(fresh.exists(), "une session vivante ne doit pas etre balayee")
        self.assertTrue(foreign.exists(), "un dossier tiers ne doit JAMAIS etre touche")
        self.assertTrue(not_a_pid.exists(), "suffixe non numerique = pas un bac a nous")

    def test_missing_temp_dir_is_not_an_error(self) -> None:
        self.assertEqual(sweep_stale_boxes(self.temp / "inexistant"), 0)


class VerdictTests(unittest.TestCase):
    """Table de decision des deux bornes, sans lancer de session pytest."""

    def test_empty_session_is_accepted(self) -> None:
        self.assertEqual(verdict([], 12, 3), "")

    def test_residual_below_both_bounds_is_accepted(self) -> None:
        leftovers = ["cinesort_atomic_e2e_aaaaaaaa", "cinesort_atomic_e2e_bbbbbbbb", "cinesort_lot3_cccccccc"]
        self.assertEqual(verdict(leftovers, 12, 3), "")

    def test_total_bound_is_exclusive(self) -> None:
        leftovers = [f"a_{i:08d}" for i in range(13)]
        self.assertEqual(verdict(leftovers[:12], 12, 99), "")
        self.assertEqual(verdict(leftovers, 12, 99), "total 13 > 12")

    def test_family_bound_catches_a_single_prefix_under_the_total(self) -> None:
        leftovers = [f"omdb_test_{i:08d}" for i in range(10)]
        self.assertEqual(verdict(leftovers, 12, 3), "famille omdb_test_* : 10 > 3")


class BuildReportTests(unittest.TestCase):
    """Le rapport regroupe par famille de prefixe, suffixe aleatoire retire."""

    def test_groups_by_prefix_family(self) -> None:
        leftovers = ["probe_test_aaaaaaaa", "probe_test_bbbbbbbb", "omdb_test_cccccccc"]
        owners = {"probe_test_aaaaaaaa": "tests/x.py::A::t1"}
        report = build_report(leftovers, 0, owners)
        self.assertIn("    2  probe_test_*", report)
        self.assertIn("    1  omdb_test_*", report)
        self.assertIn("tests/x.py::A::t1", report)
        self.assertIn("<inconnu>", report)


if __name__ == "__main__":
    unittest.main()
