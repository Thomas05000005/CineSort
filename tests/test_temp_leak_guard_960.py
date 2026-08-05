"""Tests du garde-fou anti-fuite de dossiers temporaires (issue #960).

Le garde-fou vit dans `tests/_temp_leak_guard.py`. On ne peut pas l'eprouver
depuis l'interieur de la session courante (ses fixtures sont deja installees),
donc chaque cas lance une session pytest FILLE sur un fichier de test jetable et
regarde son code de sortie et son rapport.

La session fille ne charge AUCUN plugin explicite : elle est armee par le meme
`tests/conftest.py` que la vraie suite. C'est deliberatement le CABLAGE qui est
teste, pas seulement le module — charge en `-p`, ces tests restaient tous verts
alors que le garde-fou etait totalement inerte (cf. `_run_child`).

Ce que ces tests verrouillent :
  - une session qui laisse des dossiers derriere elle devient ROUGE ;
  - une session propre reste VERTE (pas de faux positif) ;
  - les deux bornes (total et par famille de prefixe) mordent chacune ;
  - une fuite masquee par un `suffix=` est attrapee comme les autres ;
  - le garde-fou est bien ARME par `tests/conftest.py`, et le rester ;
  - un bac a sable herite d'une session morte (PID recycle) n'accuse personne ;
  - les DEFAUTS livres attrapent un fichier qui cesse de nettoyer ;
  - `CINESORT_TEMP_LEAK_GUARD=0` desactive vraiment tout ;
  - un `TemporaryDirectory` encore reference n'est PAS accuse (le GC force
    avant le comptage declenche son finalizer).
"""

from __future__ import annotations

import contextlib
import itertools
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
import unittest.mock
from pathlib import Path

from tests import _temp_leak_guard as guard_module
from tests._temp_leak_guard import (
    BOX_PREFIX,
    _bac_vide,
    build_report,
    count_families,
    est_un_bac,
    sweep_stale_boxes,
    verdict,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Racine des sessions filles. Le `.` initial la met hors de la collecte
#: normale (`norecursedirs` couvre `.*`) tout en la laissant sous `tests/`,
#: donc sous la portee de `tests/conftest.py` — c'est precisement ce qu'on veut
#: eprouver. Elle est ignoree par git.
_SESSIONS_FILLES = _REPO_ROOT / "tests" / ".sessions_filles"
#: Un dossier de session fille plus vieux que ca vient d'une execution tuee.
_AGE_ABANDON_S = 3 * 3600.0
_compteur = itertools.count()


def _make_workdir() -> Path:
    """Dossier de travail d'une session fille, sous le depot et jamais collecte.

    Balaie au passage les restes d'executions interrompues : ce fichier ne doit
    surtout pas laisser dans le depot ce qu'il denonce dans `%TEMP%`.
    """
    _SESSIONS_FILLES.mkdir(parents=True, exist_ok=True)
    limite = time.time() - _AGE_ABANDON_S
    with contextlib.suppress(OSError):
        for reste in _SESSIONS_FILLES.iterdir():
            with contextlib.suppress(OSError):
                if reste.stat().st_mtime < limite:
                    shutil.rmtree(reste, ignore_errors=True)
    work = _SESSIONS_FILLES / f"s{os.getpid()}_{next(_compteur)}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    return work


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

# Le meme, sauf que `suffix=` deplace le bloc aleatoire au MILIEU du nom. Une
# regle de famille qui suppose l'aleatoire en fin de nom ne voit plus rien.
_LEAKY_SUFFIXED = """
import tempfile

def test_leaks_five_with_a_suffix():
    for _ in range(5):
        tempfile.mkdtemp(prefix="leak960_", suffix="_fin")
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


#: Conftest depose DANS la session fille. Il s'execute a l'import, donc AVANT
#: la fixture de session du garde-fou : il peut ainsi planter un bac a sable
#: homonyme, exactement comme le ferait une session precedente tuee dont le PID
#: a ete recycle. C'est la seule facon d'eprouver le SITE D'APPEL de `_bac_vide`
#: — un test qui n'appelle que la fonction laisse survivre la mutation qui
#: retire son appel.
_CONFTEST_BAC_HERITE = """
import os, tempfile
from pathlib import Path

herite = Path(tempfile.gettempdir()) / f"cslb{os.getpid()}"
herite.mkdir(parents=True, exist_ok=True)
for i in range(4):
    (herite / f"cinesort_atomic_e2e_{i:08d}").mkdir(exist_ok=True)
"""


def _run_child(
    workdir: Path,
    body: str,
    env_extra: dict[str, str] | None = None,
    *,
    conftest_body: str = "",
) -> subprocess.CompletedProcess:
    """Lance une session pytest fille sur un fichier de test jetable.

    Le fichier est ecrit SOUS LE DEPOT, dans `tests/.sessions_filles/`, et la
    session fille ne charge AUCUN plugin explicite. Les deux choix comptent.

    **Pourquoi sous le depot.** Le fichier vivait dans un `mkdtemp`, donc dans
    `%TEMP%`. La session fille devait alors parcourir `%TEMP%` pour se situer,
    et si une entree voisine disparaissait pendant ce parcours elle mourait en
    `FileNotFoundError [WinError 2]` / `Interrupted: 1 error during collection`.
    MESURE : 0 collecte en echec sur 12 sans churn de `%TEMP%`, 12 sur 12 avec ;
    sur ce fichier, 4 sessions sur 4 rouges sous un churn de ~10 op/s — l'ordre
    de grandeur d'UNE autre session pytest. Observe deux fois sans rien
    provoquer, dont une fois comme SEUL echec d'une execution de 8 421 tests.
    Cout accessoire : 2,4 s de collecte depuis `%TEMP%` contre 0,8 s depuis le
    depot, soit ~+13 s par execution — et ce cout croit avec le nombre
    d'entrees de `%TEMP%`, la grandeur meme que ce PR reduit.

    **Pourquoi sans `-p`.** Charger `-p tests._temp_leak_guard` eprouvait le
    module mais jamais son CABLAGE. MESURE : en commentant l'import de
    `tests/conftest.py` — le seul point qui active les deux fixtures autouse
    pour la vraie suite — ces tests restaient tous VERTS pendant que 50 dossiers
    fuyaient sans le moindre signal. Un dossier prefixe `.` n'est pas explore
    par la collecte normale (`norecursedirs` couvre `.*`), mais un chemin
    explicite l'atteint, et `tests/conftest.py` s'y applique comme partout
    ailleurs sous `tests/`. La session fille est donc armee par le meme chemin
    que la vraie suite : si ce chemin casse, ces tests rougissent.
    """
    target = workdir / "test_child_960.py"
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    if conftest_body:
        (workdir / "conftest.py").write_text(textwrap.dedent(conftest_body), encoding="utf-8")
    env = dict(os.environ)
    # `tests/conftest.py` fait `from tests._temp_leak_guard import ...` : sans
    # `tests/__init__.py`, c'est la racine du depot sur le PYTHONPATH qui rend
    # le paquet importable.
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_REPO_ROOT) + (os.pathsep + existing if existing else "")
    env.pop("CINESORT_TEMP_LEAK_GUARD", None)
    env.pop("CINESORT_TEMP_LEAK_MAX", None)
    env.pop("CINESORT_TEMP_LEAK_MAX_FAMILY", None)
    # %TEMP% dedie a la session fille : sinon ce qu'elle fait fuir volontairement
    # (et son propre basetemp pytest) atterrit dans le %TEMP% de la session
    # MERE, qui l'accuserait a son tour.
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
        self.work = _make_workdir()
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

    def test_the_guard_is_armed_by_the_repository_conftest_alone(self) -> None:
        """Le CABLAGE, et non le module : rien n'est charge explicitement ici.

        La session fille ne recoit aucun `-p` : si l'import de
        `tests/conftest.py` disparait — un refactor, ou un `ruff --fix` qui
        supprime ses `# noqa: F401`, piege que le CLAUDE.md du depot documente
        deja — alors plus rien n'arme les deux fixtures autouse, et ce test
        rougit. Sans lui, la mutation restait VERTE pendant que 50 dossiers
        fuyaient en silence.
        """
        proc = _run_child(self.work, _LEAKY)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(
            proc.returncode,
            0,
            "le garde-fou n'est plus arme par tests/conftest.py — verifier que "
            f"l'import des deux fixtures autouse y est toujours present :\n{out}",
        )
        self.assertIn("Fuite de dossiers temporaires", out)

    def test_an_inherited_sandbox_does_not_accuse_an_innocent_session(self) -> None:
        """Le SITE D'APPEL de `_bac_vide`, pas seulement la fonction.

        Le conftest de la session fille plante `cslb<son pid>` avec 4 restes
        d'une meme famille avant que la fixture ne s'installe — le scenario
        exact du PID recycle apres une session tuee. La session fille ne fuit
        rien : elle doit rester VERTE. Sans le vidage, elle heritait des 4
        restes et rougissait sur « famille cinesort_atomic_e2e_* : 4 > 3 »,
        avec « 4 <inconnu> » comme seuls coupables.
        """
        proc = _run_child(self.work, _CLEAN, conftest_body=_CONFTEST_BAC_HERITE)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"une session innocente a ete accusee des restes d'une autre :\n{out}")
        self.assertNotIn("Fuite de dossiers temporaires", out)

    def test_a_leak_hidden_behind_a_suffix_is_still_caught(self) -> None:
        """La borne par famille ne doit pas tomber sur un simple `suffix=`.

        `mkdtemp(prefix=P, suffix=S)` place l'aleatoire au MILIEU. La regle qui
        retirait les 8 derniers caracteres donnait alors une famille par
        dossier : 10 fuites du meme prefixe, et silence total.
        """
        proc = _run_child(self.work, _LEAKY_SUFFIXED)
        out = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, f"une fuite masquee par un suffixe doit mordre :\n{out}")
        self.assertIn("famille ", out)


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


class BacHeriteTests(unittest.TestCase):
    """Un bac laisse par une session morte ne doit accuser personne.

    Le nom du bac contient le PID, et Windows les recycle (2 sur 300 mesures).
    Une session tuee laisse son bac ; `sweep_stale_boxes` ne le ramasse qu'au
    bout de 3 h. Entre les deux, la session qui herite du PID adoptait les
    restes : « 20 entree(s) laissee(s) par cette session », « 20 <inconnu> ».
    """

    def setUp(self) -> None:
        import tempfile

        self.temp = Path(tempfile.mkdtemp(prefix="bac960_"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def test_an_inherited_box_is_emptied_not_adopted(self) -> None:
        souhaite = self.temp / f"{BOX_PREFIX}4242"
        souhaite.mkdir()
        for i in range(4):
            (souhaite / f"cinesort_atomic_e2e_{i:08d}").mkdir()

        box = _bac_vide(souhaite)

        self.assertEqual(box, souhaite, "un bac vidable garde son nom")
        self.assertEqual(sorted(p.name for p in box.iterdir()), [], "les restes herites font accuser une innocente")

    def test_a_fresh_box_is_created_when_absent(self) -> None:
        souhaite = self.temp / f"{BOX_PREFIX}77"
        box = _bac_vide(souhaite)
        self.assertTrue(box.is_dir())
        self.assertEqual(box, souhaite)

    def test_a_box_that_resists_emptying_yields_a_neighbouring_name(self) -> None:
        """Plutot compter juste sous un autre nom que compter les restes d'autrui."""
        souhaite = self.temp / f"{BOX_PREFIX}999"
        souhaite.mkdir()
        (souhaite / "residu_tenace").mkdir()
        vrai_rmtree = shutil.rmtree

        def _rmtree_qui_echoue(path, *a, **kw):
            if Path(path) == souhaite:
                return None  # exactement ce que fait ignore_errors sur un verrou
            return vrai_rmtree(path, *a, **kw)

        with unittest.mock.patch.object(guard_module.shutil, "rmtree", _rmtree_qui_echoue):
            box = _bac_vide(souhaite)

        self.assertNotEqual(box, souhaite, "un bac non vidable ne doit pas etre adopte")
        self.assertEqual(sorted(p.name for p in box.iterdir()), [])

    def test_only_our_own_boxes_are_recognised(self) -> None:
        self.assertTrue(est_un_bac(f"{BOX_PREFIX}1234"))
        self.assertTrue(est_un_bac(f"{BOX_PREFIX}1234x2"), "le nom de repli reste un bac a nous")
        # Un dossier tiers qui commence par le meme prefixe : le balayage
        # supprime, il doit se tromper dans le sens conservateur.
        self.assertFalse(est_un_bac(f"{BOX_PREFIX}abc"))
        self.assertFalse(est_un_bac(f"{BOX_PREFIX}ackup"))
        self.assertFalse(est_un_bac(BOX_PREFIX))
        self.assertFalse(est_un_bac("autre_outil_333"))


class CountFamiliesTests(unittest.TestCase):
    """Le regroupement par famille ne doit pas dependre de la POSITION du hasard."""

    def test_random_block_at_the_end_groups(self) -> None:
        noms = [f"probe_test_{i:08d}" for i in range(4)]
        self.assertEqual(count_families(noms).most_common(1), [("probe_test_", 4)])

    def test_random_block_in_the_middle_also_groups(self) -> None:
        """`mkdtemp(prefix=..., suffix=...)` : le hasard n'est plus en fin de nom."""
        noms = [f"probe_test_{i:08d}_fin" for i in range(4)]
        worst = count_families(noms).most_common(1)[0]
        self.assertEqual(worst[1], 4, f"les 4 dossiers du meme prefixe ont ete eclates : {count_families(noms)}")

    def test_distinct_prefixes_do_not_merge(self) -> None:
        """Fusionner des familles distinctes ferait des rouges a tort."""
        noms = [f"cinesort_atomic_e2e_{i:08d}" for i in range(2)]
        noms += [f"cinesort_concurrency_{i:08d}" for i in range(2)]
        noms += [f"cinesort_lot3_{i:08d}" for i in range(1)]
        self.assertEqual(count_families(noms).most_common(1)[0][1], 2, count_families(noms))

    def test_a_mixed_suffix_leak_is_reported_as_one_family(self) -> None:
        noms = [f"leak960_{i:08d}_fin" for i in range(5)] + ["cinesort_lot3_aaaaaaaa"]
        self.assertEqual(count_families(noms).most_common(1)[0][1], 5)


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
