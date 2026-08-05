"""Issue #894 — `get_library_filtered(page_size=50)` etait en O(bibliotheque).

Ce qui restait apres #853 (N+1 de connexions SQLite, fusionne) : l'I/O PAR ROW.
Pour rendre 50 lignes, l'endpoint payait, sur la bibliotheque ENTIERE :

  - un `os.scandir` par dossier distinct (`plan_row_fs_facts`, PR #862) ;
  - une resolution de jaquette par tmdb_id (`get_tmdb_posters`, qui frappe TMDb
    en HTTP pour tout id absent du cache local).

Loi mesuree sur le banc de l'issue, exacte a deux tailles de bibliotheque :
1,00 `scandir` et 1,00 resolution de jaquette PAR FILM, que la page fasse
50 lignes ou 5.

La grandeur mesuree ici est le NOMBRE D'APPELS SYSTEME et le NOMBRE D'IDS
soumis au batch jaquettes — deterministes et reproductibles. Aucune assertion
sur un temps d'horloge : ce depot a deja produit un test de perf flaky qui
bloquait la CI en comparant des durees.

Le correctif ne retire RIEN de la donnee apportee par #862 (date d'ajout et
taille reelles) : c'est le meme `scandir`, restreint aux rows reellement
rendues. Quand un tri ou un filtre lit `added_ts`/`size_bytes`, la valeur doit
etre reelle sur toute la bibliotheque et le mode complet est conserve.

`ResultIdentityTests` est le test central : une optimisation qui change un
resultat est un bug, pas un gain.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cinesort.ui.api import library_support
from cinesort.ui.api.film_support import TMDB_OVERLAY_DONE_KEY

_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Doubles de test — pas de MagicMock : un MagicMock CREE les attributs absents
# et masquerait exactement le genre de contrat rompu qu'on verrouille ici.
# ---------------------------------------------------------------------------


class _EmptyReports:
    def list_perceptual_reports(self, run_id=None):  # noqa: ANN001, ANN201
        return []

    def list_quality_reports(self, run_id=None):  # noqa: ANN001, ANN201
        return []


class _FilmModal:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def get_tmdb_override(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append(row_id)
        return None


class _FakeStore:
    def __init__(self) -> None:
        self.perceptual = _EmptyReports()
        self.quality = _EmptyReports()
        self.film_modal = _FilmModal()


class _CountingIntegrations:
    """Compte les ids reellement soumis au batch jaquettes."""

    def __init__(self) -> None:
        self.calls: List[List[int]] = []

    def get_tmdb_posters(self, tmdb_ids: List[int], size: str = "w92") -> Dict[str, Any]:
        self.calls.append(list(tmdb_ids))
        return {"ok": True, "posters": {str(i): f"https://img/{i}_{size}.jpg" for i in tmdb_ids}}

    @property
    def submitted_ids(self) -> List[int]:
        return [i for call in self.calls for i in call]


class _FakeApi:
    class _Settings:
        def get_settings(self) -> Dict[str, Any]:
            return {"state_dir": ""}

    class _Run:
        def __init__(self, rows: List[Dict[str, Any]]) -> None:
            self._rows = rows

        def get_plan(self, run_id: str) -> Dict[str, Any]:
            return {"ok": True, "rows": self._rows}

    def __init__(self, plan_rows: List[Dict[str, Any]]) -> None:
        self.settings = self._Settings()
        self.run = self._Run(plan_rows)
        self.store = _FakeStore()
        self.integrations = _CountingIntegrations()

    def _get_or_create_infra(self, state_dir):  # noqa: ANN001, ANN202
        return (self.store, None)


class _SyscallCounter:
    """Compte les `os.scandir` / `os.stat` emis SOUS la racine mesuree.

    Le filtre par racine evite de compter les acces incidents (tempfile,
    logging, import) : le compteur n'attribue au correctif que ses propres
    syscalls.
    """

    def __init__(self, root: Path) -> None:
        self._root = str(root)
        self.scandir_paths: List[str] = []
        self.stat_paths: List[str] = []
        self._real_scandir = os.scandir
        self._real_stat = os.stat

    def __enter__(self) -> "_SyscallCounter":
        real_scandir, real_stat, root = self._real_scandir, self._real_stat, self._root

        def scandir(path=".", *args, **kwargs):  # noqa: ANN001, ANN202
            if str(path).startswith(root):
                self.scandir_paths.append(str(path))
            return real_scandir(path, *args, **kwargs)

        def stat(path, *args, **kwargs):  # noqa: ANN001, ANN202
            if str(path).startswith(root):
                self.stat_paths.append(str(path))
            return real_stat(path, *args, **kwargs)

        os.scandir = scandir
        os.stat = stat
        return self

    def __exit__(self, *exc: Any) -> None:
        os.scandir = self._real_scandir
        os.stat = self._real_stat

    @property
    def total(self) -> int:
        return len(self.scandir_paths) + len(self.stat_paths)


# ---------------------------------------------------------------------------
# Bibliotheque REELLE sur disque : les faits filesystem doivent etre de vrais
# faits, sinon un correctif qui se contenterait de rendre (0.0, 0) passerait.
# ---------------------------------------------------------------------------


def _make_library(root: Path, n: int, *, shared_folder_rows: int = 0) -> List[Dict[str, Any]]:
    """N films dans N dossiers distincts, tailles et dates toutes differentes.

    `shared_folder_rows` rows supplementaires partagent UN dossier (kind
    "collection"), pour verifier que le cache par dossier tient aussi sur le
    lot restreint a la page.
    """
    rows: List[Dict[str, Any]] = []
    base_mtime = time.time() - 400 * 24 * 3600
    for i in range(n):
        folder = root / f"Film {i:05d} (20{i % 100:02d})"
        folder.mkdir(parents=True, exist_ok=True)
        video = f"Film.{i:05d}.1080p.BluRay.x264.mkv"
        (folder / video).write_bytes(b"x" * (1024 + i))
        os.utime(folder / video, (base_mtime + i * 3600, base_mtime + i * 3600))
        rows.append(
            {
                "row_id": f"r{i:05d}",
                "proposed_title": f"Film {i:05d}",
                "proposed_year": 2000 + (i % 25),
                "confidence": 90,
                "proposed_source": "nfo",
                "candidates": [],
                "folder": str(folder),
                "video": video,
                "kind": "single",
                "tmdb_id": 1000 + i,
                "display_title": f"Film {i:05d}",
                "auto_approvable": True,
                TMDB_OVERLAY_DONE_KEY: True,
            }
        )
    if shared_folder_rows:
        shared = root / "Collection Partagee (1999)"
        shared.mkdir(parents=True, exist_ok=True)
        for j in range(shared_folder_rows):
            video = f"Partie.{j}.mkv"
            (shared / video).write_bytes(b"y" * (2048 + j))
            rows.append(
                {
                    "row_id": f"c{j:05d}",
                    "proposed_title": f"AAA Collection {j:05d}",
                    "proposed_year": 1999,
                    "confidence": 90,
                    "proposed_source": "nfo",
                    "candidates": [],
                    "folder": str(shared),
                    "video": video,
                    "kind": "collection",
                    "tmdb_id": 90000 + j,
                    "display_title": f"AAA Collection {j:05d}",
                    "auto_approvable": True,
                    TMDB_OVERLAY_DONE_KEY: True,
                }
            )
    return rows


class _LibraryCase:
    """tempdir + plan + api, monte une fois par test."""

    def __init__(self, n: int, *, shared_folder_rows: int = 0) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.plan_rows = _make_library(self.root, n, shared_folder_rows=shared_folder_rows)
        self.api = _FakeApi(self.plan_rows)
        self.n = len(self.plan_rows)

    def close(self) -> None:
        self._tmp.cleanup()

    def call(self, **kwargs: Any) -> Tuple[Dict[str, Any], _SyscallCounter]:
        self.api.integrations.calls.clear()
        params: Dict[str, Any] = {"filters": {}, "sort": "title", "page": 1, "page_size": _PAGE_SIZE}
        params.update(kwargs)
        with _SyscallCounter(self.root) as counter:
            res = library_support.get_library_filtered(self.api, "run1", **params)
        self.assert_ok(res)
        return res, counter

    @staticmethod
    def assert_ok(res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            raise AssertionError(f"endpoint en echec : {res.get('error')} / {res.get('message')}")


# ---------------------------------------------------------------------------
# 1. Le cout d'une page ne depend plus de la taille de la bibliotheque
# ---------------------------------------------------------------------------


class PageScopedIoTests(unittest.TestCase):
    def test_default_page_pays_io_for_the_page_only(self) -> None:
        case = _LibraryCase(180)
        self.addCleanup(case.close)

        res, counter = case.call()

        # 50 lignes rendues => 50 dossiers visites, pas 180.
        self.assertEqual(len(res["rows"]), _PAGE_SIZE)
        self.assertEqual(counter.total, _PAGE_SIZE)
        self.assertEqual(len(counter.scandir_paths), _PAGE_SIZE)
        # Le batch jaquettes est borne a la page lui aussi.
        self.assertEqual(len(case.api.integrations.submitted_ids), _PAGE_SIZE)
        # NON-REGRESSION : `total` porte toujours sur la bibliotheque entiere.
        self.assertEqual(res["total"], 180)
        self.assertEqual(res["pages"], 4)

    def test_page_cost_is_constant_when_library_grows(self) -> None:
        """Loi d'echelle, mesuree — pas extrapolee : le cout d'une page est le
        MEME a 90 et a 270 films. C'est la disparition du O(N) elle-meme."""
        costs = {}
        for n in (90, 270):
            case = _LibraryCase(n)
            self.addCleanup(case.close)
            _, counter = case.call()
            costs[n] = (counter.total, len(case.api.integrations.submitted_ids))
        self.assertEqual(costs[90], (_PAGE_SIZE, _PAGE_SIZE))
        self.assertEqual(costs[270], (_PAGE_SIZE, _PAGE_SIZE))

    def test_second_page_pays_only_its_own_rows(self) -> None:
        case = _LibraryCase(180)
        self.addCleanup(case.close)

        res, counter = case.call(page=3)

        self.assertEqual(len(res["rows"]), _PAGE_SIZE)
        self.assertEqual(counter.total, _PAGE_SIZE)
        self.assertEqual(sorted(case.api.integrations.submitted_ids), [1100 + i for i in range(50)])

    def test_last_partial_page_pays_only_its_rows(self) -> None:
        case = _LibraryCase(120)
        self.addCleanup(case.close)

        res, counter = case.call(page=3)

        self.assertEqual(len(res["rows"]), 20)
        self.assertEqual(counter.total, 20)

    def test_shared_folder_still_costs_one_roundtrip(self) -> None:
        """Le cache par dossier de #862 tient aussi sur le lot de la page : 50
        rows d'un meme dossier `collection` = 1 aller-retour, pas 50."""
        case = _LibraryCase(10, shared_folder_rows=60)
        self.addCleanup(case.close)

        # Tri par titre : "AAA Collection ..." passe avant "Film ...".
        res, counter = case.call()

        self.assertEqual(len(res["rows"]), _PAGE_SIZE)
        self.assertTrue(all(r["title"].startswith("AAA Collection") for r in res["rows"]))
        self.assertEqual(counter.total, 1)


# ---------------------------------------------------------------------------
# 2. Les faits filesystem restent REELS — un correctif qui rendrait 0 partout
#    satisferait les compteurs ci-dessus.
# ---------------------------------------------------------------------------


class HydratedValuesAreRealTests(unittest.TestCase):
    def test_page_rows_carry_real_mtime_and_real_size(self) -> None:
        case = _LibraryCase(180)
        self.addCleanup(case.close)

        res, _ = case.call()

        for row in res["rows"]:
            with self.subTest(row_id=row["row_id"]):
                real = Path(row["path"])
                self.assertTrue(real.is_file())
                st = os.stat(real)
                self.assertEqual(row["size_bytes"], st.st_size)
                self.assertAlmostEqual(row["added_ts"], st.st_mtime, places=3)
                self.assertGreater(row["added_ts"], 0.0)

    def test_page_rows_carry_the_batch_poster(self) -> None:
        case = _LibraryCase(180)
        self.addCleanup(case.close)

        res, _ = case.call()

        for row in res["rows"]:
            self.assertEqual(row["poster_url"], f"https://img/{row['tmdb_id']}_w342.jpg")

    def test_unreadable_folder_degrades_exactly_like_the_full_mode(self) -> None:
        """Root debranche : (0.0, estimation), jamais d'exception — meme
        contrat que `plan_row_fs_facts`."""
        case = _LibraryCase(3)
        self.addCleanup(case.close)
        for row in case.plan_rows:
            row["folder"] = str(case.root / "dossier-absent")

        res, _ = case.call()

        self.assertEqual(len(res["rows"]), 3)
        for row in res["rows"]:
            self.assertEqual(row["added_ts"], 0.0)
            self.assertEqual(row["size_bytes"], 0)


# ---------------------------------------------------------------------------
# 3. Chaque garde separement : un tri / un filtre qui LIT `added_ts` ou
#    `size_bytes` doit repasser en mode complet.
# ---------------------------------------------------------------------------


class FullFsFactsGuardTests(unittest.TestCase):
    """Un test par garde : muter une seule entree des listes doit rougir ICI,
    et seulement ici."""

    def setUp(self) -> None:
        self.case = _LibraryCase(120)
        self.addCleanup(self.case.close)

    def _assert_full_scan(self, **kwargs: Any) -> None:
        _, counter = self.case.call(**kwargs)
        self.assertEqual(counter.total, 120)

    def test_sort_added_desc_scans_the_whole_library(self) -> None:
        self._assert_full_scan(sort="added_desc")

    def test_sort_added_asc_scans_the_whole_library(self) -> None:
        self._assert_full_scan(sort="added_asc")

    def test_sort_size_desc_scans_the_whole_library(self) -> None:
        self._assert_full_scan(sort="size_desc")

    def test_sort_size_asc_scans_the_whole_library(self) -> None:
        self._assert_full_scan(sort="size_asc")

    def test_filter_size_min_scans_the_whole_library(self) -> None:
        self._assert_full_scan(filters={"size_min": 1030})

    def test_filter_size_max_scans_the_whole_library(self) -> None:
        self._assert_full_scan(filters={"size_max": 1100})

    def test_filter_added_after_scans_the_whole_library(self) -> None:
        self._assert_full_scan(filters={"added_after": 1.0})

    def test_filter_added_before_scans_the_whole_library(self) -> None:
        self._assert_full_scan(filters={"added_before": 4.0e9})

    def test_chip_recently_modified_scans_the_whole_library(self) -> None:
        self._assert_full_scan(filters={"chips": ["recently_modified"]})

    def test_falsy_but_present_key_still_scans_everything(self) -> None:
        """Sens RESTRICTIF : la presence de la clef suffit, meme si
        `_row_matches` ignorerait la valeur. Se tromper de ce cote coute une
        passe d'I/O ; se tromper de l'autre rend un resultat faux."""
        self._assert_full_scan(filters={"size_min": 0})
        self.case.api.integrations.calls.clear()
        self._assert_full_scan(filters={"added_after": None})

    def test_non_dict_filters_still_scans_everything(self) -> None:
        self.assertTrue(library_support._needs_full_fs_facts(["size_min"], "title"))
        self.assertTrue(library_support._needs_full_fs_facts(None, "title"))

    def test_non_iterable_chips_still_scans_everything(self) -> None:
        self.assertTrue(library_support._needs_full_fs_facts({"chips": "recently_modified"}, "title"))

    def test_neutral_request_does_not_scan_everything(self) -> None:
        """Contre-epreuve : sans le moindre tri/filtre sensible, on differe.
        Sans elle, une garde qui rendrait TOUJOURS True passerait les 12 tests
        ci-dessus sans rien optimiser."""
        _, counter = self.case.call(sort="title", filters={"search": "Film"})
        self.assertEqual(counter.total, _PAGE_SIZE)


# ---------------------------------------------------------------------------
# 4. LE test central : la sortie ne change pas. Le mode complet EST le chemin
#    d'avant le correctif.
# ---------------------------------------------------------------------------


_FILTER_BATTERY: Tuple[Dict[str, Any], ...] = (
    {},
    {"search": "Film 001"},
    {"search": "collection"},
    {"tier_v2": ["unknown"]},
    {"size_min": 1030},
    {"size_max": 1100},
    {"added_after": 1.0},
    {"added_before": 4.0e9},
    {"chips": ["recently_modified"]},
    {"chips": ["unidentified"]},
    {"chips": ["in_duplicates"]},
    {"chips": ["sagas_incomplete"]},
    {"year_min": 2005, "year_max": 2015},
    {"decades": ["2000"]},
    {"resolution": ["1080p"]},
    {"source": ["bluray"]},
    {"confidence_min": 10, "confidence_max": 100},
    {"duration_min": 1},
    {"size_min": 0},
    {"added_after": None},
)


class ResultIdentityTests(unittest.TestCase):
    """AVANT/APRES sur la meme bibliotheque reelle, reponse ENTIERE comparee.

    Le balayage couvre TOUS les noms de `_SORT_KEY` (donc il attrape un tri
    sensible aux faits filesystem qu'on aurait oublie d'inscrire dans
    `_FS_DEPENDENT_SORTS`), plus `title_desc` et un tri inconnu.
    """

    @staticmethod
    def _forced(case: _LibraryCase, full: bool, **kwargs: Any) -> Dict[str, Any]:
        real = library_support._needs_full_fs_facts
        try:
            if full:
                library_support._needs_full_fs_facts = lambda *a, **k: True
            params: Dict[str, Any] = {
                "filters": {},
                "sort": "title",
                "page": 1,
                "page_size": _PAGE_SIZE,
            }
            params.update(kwargs)
            case.api.integrations.calls.clear()
            return library_support.get_library_filtered(case.api, "run1", **params)
        finally:
            library_support._needs_full_fs_facts = real

    def test_every_sort_and_filter_gives_the_identical_response(self) -> None:
        case = _LibraryCase(107, shared_folder_rows=11)
        self.addCleanup(case.close)

        sorts = sorted(library_support._SORT_KEY) + ["title_desc", "sort_inconnu", ""]
        compared = 0
        for sort in sorts:
            for filters in _FILTER_BATTERY:
                for page in (1, 2, 3):
                    with self.subTest(sort=sort, filters=filters, page=page):
                        ref = self._forced(case, True, sort=sort, filters=dict(filters), page=page)
                        got = self._forced(case, False, sort=sort, filters=dict(filters), page=page)
                        _LibraryCase.assert_ok(ref)
                        _LibraryCase.assert_ok(got)
                        self.assertEqual(ref, got)
                        compared += 1
        # Le balayage doit avoir REELLEMENT tourne (piege du test vacant).
        self.assertEqual(compared, len(sorts) * len(_FILTER_BATTERY) * 3)
        self.assertGreaterEqual(compared, 700)


# ---------------------------------------------------------------------------
# 5. La clef privee ne doit jamais partir au frontend
# ---------------------------------------------------------------------------


class NoPrivateKeyLeakTests(unittest.TestCase):
    def test_response_carries_no_deferred_marker_and_is_serialisable(self) -> None:
        case = _LibraryCase(180)
        self.addCleanup(case.close)

        res, _ = case.call()

        for row in res["rows"]:
            self.assertNotIn(library_support._DEFERRED_IO_KEY, row)
        # La reponse part telle quelle au frontend : elle doit etre serialisable.
        payload = json.dumps(res)
        self.assertNotIn(library_support._DEFERRED_IO_KEY, payload)

    def test_hydrate_is_idempotent_and_noop_on_plain_rows(self) -> None:
        case = _LibraryCase(4)
        self.addCleanup(case.close)

        rows = library_support._build_library_rows(case.api, "run1", defer_row_io=True)
        library_support._hydrate_deferred_row_io(case.api, rows)
        first = [dict(r) for r in rows]
        case.api.integrations.calls.clear()
        library_support._hydrate_deferred_row_io(case.api, rows)

        self.assertEqual([dict(r) for r in rows], first)
        self.assertEqual(case.api.integrations.calls, [])


# ---------------------------------------------------------------------------
# 6. Les 8 autres appelants de `_build_library_rows` ne bougent pas
# ---------------------------------------------------------------------------


class OtherCallersUnchangedTests(unittest.TestCase):
    """Podiums, timeline, export, audits... appellent sans `defer_row_io` et
    lisent `path`/`added_ts`/`size_bytes` sur TOUTES les rows. Le defaut doit
    donc rester le mode complet."""

    def test_default_call_still_pays_full_fs_and_full_poster_batch(self) -> None:
        case = _LibraryCase(60)
        self.addCleanup(case.close)

        with _SyscallCounter(case.root) as counter:
            rows = library_support._build_library_rows(case.api, "run1")

        self.assertEqual(len(rows), 60)
        self.assertEqual(counter.total, 60)
        self.assertEqual(len(case.api.integrations.submitted_ids), 60)
        self.assertTrue(all(r["added_ts"] > 0.0 for r in rows))
        self.assertTrue(all(library_support._DEFERRED_IO_KEY not in r for r in rows))

    def test_with_posters_false_defers_no_poster_id(self) -> None:
        """`with_posters=False` + mode differe ne doit PAS ressusciter le batch
        a l'hydratation (compteurs de chips, rollup scoring)."""
        case = _LibraryCase(5)
        self.addCleanup(case.close)

        rows = library_support._build_library_rows(case.api, "run1", with_posters=False, defer_row_io=True)
        library_support._hydrate_deferred_row_io(case.api, rows)

        self.assertEqual(case.api.integrations.calls, [])
        self.assertTrue(all(r["poster_url"] is None for r in rows))
        self.assertTrue(all(r["added_ts"] > 0.0 for r in rows))


# ---------------------------------------------------------------------------
# 7. Le batch jaquettes degrade, il ne remonte pas
# ---------------------------------------------------------------------------


class _BrokenIntegrations:
    """Reponse mal formee : `.get("ok")` leve AttributeError."""

    def __init__(self) -> None:
        self.calls: List[List[int]] = []

    def get_tmdb_posters(self, tmdb_ids: List[int], size: str = "w92") -> Any:
        self.calls.append(list(tmdb_ids))
        return ["reponse", "mal", "formee"]


class PosterBatchDegradesTests(unittest.TestCase):
    """Le `try` du batch couvre la LECTURE de la reponse, pas seulement l'appel.

    Une reponse mal formee doit rendre une vue sans jaquettes, jamais une
    exception : la Bibliotheque reste affichable. Le retrecir au seul appel
    transformerait cette degradation en HTTP 500 pour les appelants qui n'ont
    pas de garde de bord (podiums, timeline, export).
    """

    def test_malformed_response_degrades_to_no_poster(self) -> None:
        case = _LibraryCase(60)
        self.addCleanup(case.close)
        case.api.integrations = _BrokenIntegrations()

        self.assertEqual(library_support._fetch_posters_batch(case.api, [1, 2, 3]), {})

        res, _ = case.call()
        self.assertEqual(len(res["rows"]), _PAGE_SIZE)
        self.assertTrue(all(r["poster_url"] is None for r in res["rows"]))
        # La page reste hydratee : c'est le batch qui degrade, pas le scandir.
        self.assertTrue(all(r["added_ts"] > 0.0 for r in res["rows"]))

    def test_malformed_response_degrades_in_full_mode_too(self) -> None:
        case = _LibraryCase(60)
        self.addCleanup(case.close)
        case.api.integrations = _BrokenIntegrations()

        rows = library_support._build_library_rows(case.api, "run1")

        self.assertEqual(len(rows), 60)
        self.assertTrue(all(r["poster_url"] is None for r in rows))


if __name__ == "__main__":
    unittest.main()
