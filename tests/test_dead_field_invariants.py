"""Invariants anti « fonctionnalite silencieusement morte » (issues #441/#447/#729/#730).

La famille de bugs visee :

    du code lit un attribut ou une clef qui N'EXISTE PAS, un fallback falsy
    (`getattr(x, "y", None)`, `r.get("z") or 0`) masque le contrat rompu, donc
    aucune exception n'est levee, aucun log n'est emis, et la fonctionnalite
    est morte pour toujours.

Elle a survecu si longtemps parce que les tests etaient VERTS : les mocks
(`api._store = MagicMock()`) CREENT l'attribut que la production n'a jamais
eu. Les deux verrous ci-dessous suppriment cette echappatoire :

1. `PlanRowKeyContractTests` : passe de vraies PlanRow serialisees a
   `_build_library_rows`, encapsulees dans un dict qui LEVE des qu'on lit une
   clef absente du dataclass `PlanRow` et hors de la liste — courte et
   documentee — des clefs d'enrichissement reellement posees en production.
2. `ApiAttributeContractTests` : enumere par AST toutes les lectures
   d'attribut sur `api` dans `cinesort/ui/api/` — forme `getattr`/`hasattr`
   ET forme `api._x` directe — et exige que le nom existe reellement sur
   `CineSortApi` (introspection + `self._x = ...` du corps de la classe +
   `api._x = ...` pose en lazy-init par un module *_support).
"""

from __future__ import annotations

import ast
import pathlib
import tempfile
import unittest
from dataclasses import asdict, fields
from typing import Any, Dict, List, Set, Tuple

from cinesort.domain.core import PlanRow
from cinesort.ui.api import library_support
from cinesort.ui.api.cinesort_api import CineSortApi

_REPO_ROOT = pathlib.Path(library_support.__file__).resolve().parents[3]
_PKG_ROOT = _REPO_ROOT / "cinesort"
_UI_API_ROOT = _PKG_ROOT / "ui" / "api"

# Clefs ABSENTES de PlanRow mais reellement posees sur le payload avant qu'il
# n'atteigne les consommateurs. Toute autre clef lue est un bug.
_ENRICHMENT_KEYS = {
    # film_support.overlay_tmdb_override (choix manuel de candidat TMDb)
    "tmdb_id",
    "chosen_tmdb_id",
    # history_support._enrich_plan_payload
    "display_title",
    "auto_approvable",
    # DETTE CONNUE : `nfo_title` n'existe sur aucun contrat (ni PlanRow ni
    # enrichissement). Il n'est lu qu'en 2e terme d'un `or` dont le 1er
    # (`proposed_title`) est toujours present, donc l'effet est nul — mais le
    # meme idiome est copie dans 5 modules ui/api + le frontend. A traiter en
    # une passe dediee, pas en rustine locale.
    "nfo_title",
}

_PLAN_ROW_FIELDS = {f.name for f in fields(PlanRow)}
_ALLOWED_PLAN_ROW_KEYS = _PLAN_ROW_FIELDS | _ENRICHMENT_KEYS

# Modules dont ce test exige ZERO attribut fantome (perimetre du correctif).
_OWNED_MODULES = {"library_support.py", "quality_simulator_support.py"}

# Ratchet : attributs fantomes deja presents ailleurs dans ui/api, chacun
# rattache a une issue ouverte. Un NOUVEAU nom fait echouer le test. On teste
# l'inclusion (et non l'egalite) pour qu'une correction concurrente sur une
# autre branche ne casse pas ce test au merge.
_KNOWN_PHANTOM_ATTRS = {
    "_tmdb_client",  # issues #760 / #801 — library_audit_support, quality_report_support
    "_close_infra",  # reset_support.py:472 — hasattr toujours False
}


# ---------------------------------------------------------------------------
# 1. Contrat de clefs des PlanRow serialisees
# ---------------------------------------------------------------------------


class _PhantomKeyError(AssertionError):
    pass


class _PlanRowCanary(dict):
    """PlanRow serialisee qui refuse d'etre interrogee sur une clef fantome.

    En production ces lectures renvoient `None` en silence ; ici elles levent.
    """

    def __init__(self, data: Dict[str, Any], seen: Set[str]):
        super().__init__(data)
        self._seen = seen

    def _check(self, key: Any) -> None:
        self._seen.add(str(key))
        if key not in _ALLOWED_PLAN_ROW_KEYS:
            raise _PhantomKeyError(
                f"lecture de la clef fantome {key!r} sur une PlanRow serialisee. "
                f"PlanRow ne declare pas ce champ et aucun enrichissement ne le pose : "
                f"la valeur vaudra None EN PERMANENCE et le fallback falsy la rendra "
                f"invisible. Champs disponibles : {sorted(_PLAN_ROW_FIELDS)}"
            )

    def get(self, key, default=None):  # type: ignore[override]
        self._check(key)
        return super().get(key, default)

    def __getitem__(self, key):  # type: ignore[override]
        self._check(key)
        return super().__getitem__(key)


class _FakeRepo:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def list_perceptual_reports(self, run_id=None):
        return list(self._rows)

    def list_quality_reports(self, run_id=None):
        return list(self._rows)


class _FakeFilmModalRepo:
    def get_tmdb_override(self, run_id=None, row_id=None):
        return None


class _FakeStore:
    def __init__(self):
        self.perceptual = _FakeRepo([])
        self.quality = _FakeRepo([])
        self.film_modal = _FakeFilmModalRepo()


class _FakeSettingsFacade:
    def __init__(self, state_dir: str):
        self._state_dir = state_dir

    def get_settings(self):
        return {"state_dir": self._state_dir}


class _FakeRunFacade:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def get_plan(self, run_id):
        return {"ok": True, "rows": self._rows}


class _FakeIntegrationsFacade:
    def get_tmdb_posters(self, tmdb_ids, size):
        return {"ok": True, "posters": {}}


class _FakeApi:
    """Surface REELLE de CineSortApi utilisee par `_build_library_rows`.

    Deliberement pas un MagicMock : un MagicMock cree a la volee l'attribut
    manquant, ce qui est precisement l'angle mort qui a laisse vivre #441.
    """

    def __init__(self, rows: List[Dict[str, Any]], state_dir: str):
        self.settings = _FakeSettingsFacade(state_dir)
        self.run = _FakeRunFacade(rows)
        self.integrations = _FakeIntegrationsFacade()
        self.store = _FakeStore()

    def _get_or_create_infra(self, state_dir):
        return (self.store, None)


def _make_plan_row(folder: str, video: str) -> Dict[str, Any]:
    row = PlanRow(
        row_id="ROW1",
        kind="single",
        folder=folder,
        video=video,
        proposed_title="Blade Runner 2049",
        proposed_year=2017,
        proposed_source="nfo",
        confidence=95,
        confidence_label="high",
        candidates=[],
    )
    return asdict(row)


class PlanRowKeyContractTests(unittest.TestCase):
    """#447 / #730 : `_build_library_rows` ne doit lire QUE des champs reels."""

    def _build(self, tmp: pathlib.Path) -> Tuple[List[Dict[str, Any]], Set[str]]:
        folder = tmp / "Blade Runner 2049 (2017)"
        folder.mkdir(parents=True, exist_ok=True)
        video = folder / "Blade.Runner.2049.2017.1080p.BluRay.x264-GRP.mkv"
        video.write_bytes(b"x" * 4096)

        seen: Set[str] = set()
        payload = _PlanRowCanary(_make_plan_row(str(folder), video.name), seen)
        api = _FakeApi([payload], str(tmp))
        rows = library_support._build_library_rows(api, "RUN1")
        return rows, seen

    def test_no_phantom_key_is_read_on_plan_rows(self):
        """ROUGE avant le correctif : `mtime`, `source_path` et `size_bytes`.

        Aucune des trois n'est un champ de PlanRow ; elles renvoyaient None,
        `or 0` / `or ""` les avalait, et `added_ts`/`path`/`size_bytes`
        etaient donc morts pour tous les films.
        """
        with tempfile.TemporaryDirectory() as td:
            rows, seen = self._build(pathlib.Path(td))
        self.assertEqual(len(rows), 1)
        # Le canari LEVE des la 1re clef fantome, donc arriver ici suffit
        # deja. On verifie en plus qu'il a bien ete SOLLICITE : un canari que
        # `_build_library_rows` n'interrogerait plus (payload remplace,
        # court-circuit...) passerait sinon en silence, ce qui serait le meme
        # faux vert que celui qu'on corrige.
        self.assertTrue({"folder", "video", "row_id"} <= seen, f"canari non sollicite : {sorted(seen)}")
        phantom = sorted(k for k in seen if k not in _ALLOWED_PLAN_ROW_KEYS)
        self.assertEqual(phantom, [], f"clefs fantomes lues : {phantom}")

    def test_path_added_ts_and_size_are_derived_from_folder_and_video(self):
        """Le correctif doit produire des valeurs REELLES, pas juste ne pas lever."""
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            rows, _ = self._build(tmp)
            row = rows[0]
            video = tmp / "Blade Runner 2049 (2017)" / "Blade.Runner.2049.2017.1080p.BluRay.x264-GRP.mkv"

            self.assertEqual(row["path"], str(video))
            self.assertEqual(row["size_bytes"], 4096)
            self.assertAlmostEqual(row["added_ts"], video.stat().st_mtime, places=3)
            # Non-regression : la date reelle rend le chip "recemment modifie"
            # a nouveau capable de repondre True (il etait fige a False).
            self.assertTrue(library_support._row_recently_modified(row, video.stat().st_mtime, 60.0))

    def test_missing_media_degrades_without_raising(self):
        """Root debranche / dossier deplace : (0.0, 0), jamais d'exception."""
        row = {"folder": r"Z:\introuvable", "video": "absent.mkv"}
        self.assertEqual(library_support.plan_row_fs_facts(row, {}), (0.0, 0))
        self.assertTrue(library_support.plan_row_media_path(row).endswith("absent.mkv"))

    def test_media_path_falls_back_to_folder_when_video_unknown(self):
        self.assertEqual(library_support.plan_row_media_path({"folder": "/a/b", "video": ""}), "/a/b")
        self.assertEqual(library_support.plan_row_media_path({"folder": "", "video": ""}), "")


# ---------------------------------------------------------------------------
# 2. Contrat d'attributs de CineSortApi
# ---------------------------------------------------------------------------


def _collect_api_attr_reads() -> List[Tuple[str, int, str]]:
    """Retourne [(fichier, ligne, nom)] pour toute LECTURE d'attribut sur `api`.

    Deux formes, parce que le bug #441 les utilisait toutes les deux :
      - `getattr(api, "_x", ...)` / `hasattr(api, "_x")` — la forme qui masque
        activement l'absence derriere un defaut falsy ;
      - `api._x` en lecture directe — la forme qui leverait AttributeError...
        si un `except` trop large ne l'avalait pas (c'etait le cas de
        `_resolve_latest_run_id`).
    Les ECRITURES (`api._x = ...`) sont exclues : ce sont elles qui definissent
    legitimement les attributs poses en lazy-init.
    """
    found: List[Tuple[str, int, str]] = []
    for path in sorted(_UI_API_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and len(node.args) >= 2:
                fn = node.func
                obj, name = node.args[0], node.args[1]
                if (
                    isinstance(fn, ast.Name)
                    and fn.id in {"getattr", "hasattr"}
                    and isinstance(obj, ast.Name)
                    and obj.id == "api"
                    and isinstance(name, ast.Constant)
                    and isinstance(name.value, str)
                ):
                    found.append((path.name, node.lineno, name.value))
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
                and node.value.id == "api"
            ):
                found.append((path.name, node.lineno, node.attr))
    return found


def _assign_targets(node: ast.AST) -> List[Any]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target]
    return []


def _collect_defined_api_attrs() -> Set[str]:
    """Noms d'attributs qu'un objet `api` porte reellement.

    Trois sources, et TROIS SEULEMENT — c'est la precision de cet ensemble
    qui fait la valeur du test. Le tentant `tout `x.<nom> = ...` dans
    cinesort/` serait bien trop large : `_store` serait declare « existant »
    parce que `JobRunner.__init__` fait `self._store = store`, et le bug
    #441 repasserait au vert.
      1. l'introspection de la classe `CineSortApi` ;
      2. les `self.<nom> = ...` du corps de la classe `CineSortApi` ;
      3. les `api.<nom> = ...` de `cinesort/` (attributs poses en lazy-init
         sur l'objet api par un module *_support, ex.
         `api._perceptual_cancel_event`).
    """
    names: Set[str] = set(dir(CineSortApi))

    api_module = ast.parse((_UI_API_ROOT / "cinesort_api.py").read_text(encoding="utf-8"))
    class_nodes = [n for n in ast.walk(api_module) if isinstance(n, ast.ClassDef) and n.name == "CineSortApi"]
    assert class_nodes, "classe CineSortApi introuvable — collecteur casse"
    for node in ast.walk(class_nodes[0]):
        for target in _assign_targets(node):
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                names.add(target.attr)

    for path in sorted(_PKG_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for target in _assign_targets(node):
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "api"
                ):
                    names.add(target.attr)
    return names


class ApiAttributeContractTests(unittest.TestCase):
    """#441 / #729 : un `getattr(api, "_x")` dont `_x` n'existe pas est un bug."""

    @classmethod
    def setUpClass(cls):
        cls.reads = _collect_api_attr_reads()
        cls.defined = _collect_defined_api_attrs()

    def _offenders(self) -> List[Tuple[str, int, str]]:
        return [site for site in self.reads if site[2] not in self.defined]

    def test_scan_is_not_empty(self):
        """Garde-fou du garde-fou : un collecteur casse rendrait tout vert."""
        self.assertGreater(len(self.reads), 10)
        names = {name for _, _, name in self.reads}
        # forme getattr(api, "...") ...
        self.assertIn("_state_dir", names)
        # ... et forme `api.<attr>` en lecture directe.
        self.assertIn("_get_or_create_infra", names)

    def test_owned_modules_have_no_phantom_api_attribute(self):
        """ROUGE avant le correctif : quality_simulator_support.py `_store`."""
        bad = [site for site in self._offenders() if site[0] in _OWNED_MODULES]
        self.assertEqual(bad, [], f"attributs fantomes sur api : {bad}")

    def test_store_is_never_read_on_the_api_object(self):
        """`api._store` n'a jamais existe : les stores vivent dans `_infra_by_state_dir`."""
        self.assertNotIn("_store", dir(CineSortApi))
        sites = [site for site in self.reads if site[2] == "_store"]
        self.assertEqual(sites, [], f"api._store lu en {sites}")

    def test_no_new_phantom_api_attribute_anywhere_in_ui_api(self):
        """Ratchet : la famille ne doit pas se reconstituer dans un autre module."""
        new = sorted({name for _, _, name in self._offenders() if name not in _KNOWN_PHANTOM_ATTRS})
        self.assertEqual(new, [], f"nouveaux attributs fantomes sur api : {new}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
