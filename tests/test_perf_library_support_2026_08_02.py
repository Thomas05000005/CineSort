"""ULTRA AUDIT 2026-08-02 — points chauds de `_build_library_rows`.

Trois defauts de performance, tous dans cinesort/ui/api/library_support.py :

1. (HIGH, :231) l'overlay TMDb etait applique DEUX fois sur les memes dicts —
   une premiere fois par `api.run.get_plan` (history_support._enrich_plan_payload)
   puis une seconde ici. Chaque `get_tmdb_override` ouvre 2 connexions SQLite,
   donc la vue Bibliotheque payait 4N connexions par affichage au lieu de 2N.
2. (HIGH, :1325 et :1152) les compteurs de chips et le rollup scoring
   n'exposent AUCUNE jaquette mais declenchaient quand meme le batch
   `get_tmdb_posters` (reconstruction d'un TmdbClient + relecture integrale de
   tmdb_cache.json, et appels HTTP TMDb pour les ids pas encore en cache).
3. (LOW, :294) la dedup des tmdb_id du batch testait l'appartenance sur la
   LISTE en construction -> O(n^2).

Chaque test a ete vu ROUGE en cassant le correctif correspondant.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.ui.api import history_support, library_support
from cinesort.ui.api.film_support import TMDB_OVERLAY_DONE_KEY

# ---------------------------------------------------------------------------
# Doubles de test (pas de MagicMock : on compte les appels exactement)
# ---------------------------------------------------------------------------


class _EmptyReports:
    def list_perceptual_reports(self, run_id=None):  # noqa: ANN001, ANN201
        return []

    def list_quality_reports(self, run_id=None):  # noqa: ANN001, ANN201
        return []


class _CountingFilmModal:
    """Compte les lectures de film_tmdb_overrides (2 connexions SQLite reelles)."""

    def __init__(self, overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.overrides = overrides or {}
        self.calls: List[str] = []

    def get_tmdb_override(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append(f"{run_id}/{row_id}")
        return self.overrides.get(row_id)


class _FakeStore:
    def __init__(self, film_modal: _CountingFilmModal) -> None:
        self.perceptual = _EmptyReports()
        self.quality = _EmptyReports()
        self.film_modal = film_modal


class _CountingIntegrations:
    def __init__(self) -> None:
        self.calls: List[List[int]] = []

    def get_tmdb_posters(self, tmdb_ids: List[int], size: str = "w92") -> Dict[str, Any]:
        self.calls.append(list(tmdb_ids))
        return {"ok": True, "posters": {str(i): f"https://img/{i}_{size}.jpg" for i in tmdb_ids}}


class _FakeApi:
    """api minimal : settings, _get_or_create_infra, run.get_plan, integrations."""

    class _Settings:
        def __init__(self, state_dir: str) -> None:
            self._state_dir = state_dir

        def get_settings(self) -> Dict[str, Any]:
            return {"state_dir": self._state_dir}

    class _Run:
        def __init__(self, rows: List[Dict[str, Any]]) -> None:
            self._rows = rows

        def get_plan(self, run_id: str) -> Dict[str, Any]:
            return {"ok": True, "rows": self._rows}

    def __init__(
        self,
        plan_rows: List[Dict[str, Any]],
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        state_dir: str = "",
    ) -> None:
        self.settings = self._Settings(state_dir)
        self.run = self._Run(plan_rows)
        self.film_modal = _CountingFilmModal(overrides)
        self.store = _FakeStore(self.film_modal)
        self.integrations = _CountingIntegrations()

    def _get_or_create_infra(self, state_dir):  # noqa: ANN001, ANN202
        return (self.store, None)


def _plan_row(row_id: str, *, tmdb_id: int = 0, enriched: bool = False) -> Dict[str, Any]:
    """PlanRow serialisee. `enriched=True` simule le passage par get_plan reel :
    `display_title` + `auto_approvable` poses par _enrich_plan_payload, ET le
    marqueur d'overlay ABOUTI pose par overlay_tmdb_override lui-meme.

    Revue adversaire PR #849 : c'est ce marqueur, et lui seul, qui autorise
    _build_library_rows a sauter l'overlay. `display_title` est deliberement
    conserve ici pour verrouiller le fait qu'il ne suffit PLUS
    (cf. classe DisplayTitleIsNotAProofTests)."""
    row: Dict[str, Any] = {
        "row_id": row_id,
        "proposed_title": f"Film {row_id}",
        "proposed_year": 2000,
        "confidence": 90,
        "proposed_source": "nfo",
        "candidates": [],
    }
    if tmdb_id:
        row["tmdb_id"] = tmdb_id
    if enriched:
        row["display_title"] = f"Film {row_id}"
        row["auto_approvable"] = True
        row[TMDB_OVERLAY_DONE_KEY] = True
    return row


# ---------------------------------------------------------------------------
# 1. HIGH :231 — pas de second overlay quand get_plan a deja enrichi
# ---------------------------------------------------------------------------


class DoubleOverlayTests(unittest.TestCase):
    def test_no_second_override_read_when_plan_already_enriched(self) -> None:
        """Le chemin de PROD : get_plan renvoie des rows deja enrichies."""
        rows = [_plan_row(f"r{i}", tmdb_id=100 + i, enriched=True) for i in range(25)]
        api = _FakeApi(rows)

        out = library_support._build_library_rows(api, "run1")

        # Le correctif : zero relecture de film_tmdb_overrides (donc zero
        # connexion SQLite supplementaire) pour les rows deja enrichies.
        self.assertEqual(api.film_modal.calls, [])
        # NON-REGRESSION (vert des deux cotes du correctif) : les rows sont
        # construites normalement et portent bien le tmdb_id resolu.
        self.assertEqual(len(out), 25)
        self.assertEqual(out[0]["tmdb_id"], 100)
        self.assertEqual(out[0]["title"], "Film r0")

    def test_override_still_applied_when_plan_not_enriched(self) -> None:
        """Filet de securite : si get_plan n'enrichit pas (stub, enrichissement
        tombe en erreur), l'overlay DOIT toujours etre applique ici."""
        rows = [_plan_row("r0", tmdb_id=111), _plan_row("r1", tmdb_id=222)]
        api = _FakeApi(
            rows,
            overrides={
                "r0": {
                    "tmdb_id": 999,
                    "proposed_title": "Titre Choisi",
                    "proposed_year": 2021,
                    "new_confidence": 88,
                }
            },
        )

        out = library_support._build_library_rows(api, "run1")
        by_id = {r["row_id"]: r for r in out}

        self.assertEqual(len(api.film_modal.calls), 2)
        self.assertEqual(by_id["r0"]["tmdb_id"], 999)
        self.assertEqual(by_id["r0"]["title"], "Titre Choisi")
        self.assertEqual(by_id["r0"]["year"], 2021)
        # La row sans override reste sur son match auto.
        self.assertEqual(by_id["r1"]["tmdb_id"], 222)

    def test_mixed_rows_only_unenriched_are_overlaid(self) -> None:
        rows = [
            _plan_row("r0", tmdb_id=111, enriched=True),
            _plan_row("r1", tmdb_id=222, enriched=False),
        ]
        api = _FakeApi(rows)

        library_support._build_library_rows(api, "run1")

        self.assertEqual(api.film_modal.calls, ["run1/r1"])


# ---------------------------------------------------------------------------
# 2. HIGH :1325 / :1152 — pas de batch jaquettes pour les surfaces sans jaquette
# ---------------------------------------------------------------------------


class PosterBatchScopeTests(unittest.TestCase):
    def _api(self) -> _FakeApi:
        rows = [_plan_row(f"r{i}", tmdb_id=500 + i, enriched=True) for i in range(10)]
        return _FakeApi(rows)

    def test_counters_by_chip_does_not_fetch_posters(self) -> None:
        api = self._api()
        res = library_support.get_library_counters_by_chip(api, filters={}, run_id="run1")

        self.assertEqual(api.integrations.calls, [])
        # NON-REGRESSION : les compteurs restent exacts.
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 10)
        self.assertEqual(res["counts"]["unknown"], 10)

    def test_scoring_rollup_does_not_fetch_posters(self) -> None:
        api = self._api()
        res = library_support.get_scoring_rollup(api, by="decade", run_id="run1")

        self.assertEqual(api.integrations.calls, [])
        self.assertTrue(res["ok"])
        self.assertTrue(res["groups"])

    def test_library_filtered_still_fetches_posters(self) -> None:
        """NON-REGRESSION : la grille de la Bibliotheque, elle, affiche les
        jaquettes — le batch doit rester (et rester UN seul appel batche)."""
        api = self._api()
        res = library_support.get_library_filtered(api, "run1", {}, "title_asc", 1, 50)

        self.assertEqual(len(api.integrations.calls), 1)
        self.assertEqual(api.integrations.calls[0], [500 + i for i in range(10)])
        self.assertEqual(res["rows"][0]["poster_url"], "https://img/500_w342.jpg")

    def test_rows_without_poster_batch_keep_tmdb_id(self) -> None:
        """Sauter le batch ne doit PAS priver les rows de leur tmdb_id resolu
        (le frontend passe par le proxy /api/poster avec cet id)."""
        api = self._api()
        rows = library_support._build_library_rows(api, "run1", with_posters=False)

        self.assertEqual(api.integrations.calls, [])
        self.assertEqual([r["tmdb_id"] for r in rows], [500 + i for i in range(10)])
        self.assertTrue(all(r["poster_url"] is None for r in rows))


# ---------------------------------------------------------------------------
# 3. LOW :294 — dedup des tmdb_id en O(n), pas O(n^2)
# ---------------------------------------------------------------------------


class DedupIdsTests(unittest.TestCase):
    def test_dedup_keeps_first_occurrence_order(self) -> None:
        """NON-REGRESSION : meme resultat que l'ancien `if x not in out`."""
        self.assertEqual(
            library_support._dedup_ids_preserving_order([7, 3, 7, 9, 3, 1]),
            [7, 3, 9, 1],
        )
        self.assertEqual(library_support._dedup_ids_preserving_order([]), [])

    def test_dedup_is_not_quadratic(self) -> None:
        """30 000 ids distincts : ~3 ms avec un set, ~2 500 ms avec un `in list`.

        Seuil a 1,0 s = 300x de marge cote lineaire, et la version quadratique
        depasse quand meme (mesure 2,47 s sur la machine de dev).
        """
        ids = list(range(30_000))
        started = time.perf_counter()
        out = library_support._dedup_ids_preserving_order(ids)
        elapsed = time.perf_counter() - started

        self.assertEqual(len(out), 30_000)
        self.assertLess(elapsed, 1.0, f"dedup quadratique suspectee ({elapsed:.3f} s)")

    def test_batch_ids_are_deduped_in_build(self) -> None:
        """NON-REGRESSION bout en bout : le batch recoit chaque id UNE fois,
        dans l'ordre de premiere apparition."""
        rows = [
            _plan_row("r0", tmdb_id=42, enriched=True),
            _plan_row("r1", tmdb_id=7, enriched=True),
            _plan_row("r2", tmdb_id=42, enriched=True),
            _plan_row("r3", tmdb_id=7, enriched=True),
        ]
        api = _FakeApi(rows)

        library_support._build_library_rows(api, "run1")

        self.assertEqual(api.integrations.calls, [[42, 7]])

    def _count_dedup_calls(self, *, with_posters: bool) -> int:
        """Compte les appels reels a la dedup pendant un `_build_library_rows`."""
        rows = [_plan_row(f"r{i}", tmdb_id=42 + (i % 3), enriched=True) for i in range(6)]
        api = _FakeApi(rows)
        real = library_support._dedup_ids_preserving_order
        calls: List[int] = []

        def _spy(ids: List[int]) -> List[int]:
            calls.append(len(ids))
            return real(ids)

        library_support._dedup_ids_preserving_order = _spy  # type: ignore[assignment]
        try:
            library_support._build_library_rows(api, "run1", with_posters=with_posters)
        finally:
            library_support._dedup_ids_preserving_order = real  # type: ignore[assignment]
        return len(calls)

    def test_dedup_is_skipped_when_no_poster_is_ever_exposed(self) -> None:
        """Revue Sourcery : la dedup ne sert QU'a l'argument du batch.

        `with_posters=False` est le chemin des deux appelants les plus chauds
        (rollup et compteurs de chips, ce dernier rejoue a chaque clic de chip /
        tri / filtre) : ils ne doivent pas payer une passe sur toute la
        bibliotheque pour un resultat jete.
        """
        self.assertEqual(self._count_dedup_calls(with_posters=False), 0)

    def test_dedup_still_runs_when_the_batch_is_fetched(self) -> None:
        """NON-REGRESSION : le batch, lui, recoit toujours des ids dedupliques."""
        self.assertEqual(self._count_dedup_calls(with_posters=True), 1)


# ---------------------------------------------------------------------------
# 4. REVUE ADVERSAIRE PR #849 — le marqueur d'overlay ABOUTI
#
# Le guard perf de _build_library_rows inferait « l'overlay a reussi » de la
# presence de `display_title`. Or _enrich_plan_payload pose `display_title`
# INCONDITIONNELLEMENT (row.setdefault) APRES un `contextlib.suppress(Exception)`
# autour de l'overlay : un store indisponible ou une base verrouillee laissaient
# donc la Bibliotheque sauter le rattrapage et le choix TMDb manuel de
# l'utilisateur DISPARAISSAIT en silence (bug R7-3 re-ouvert).
# Le signal est desormais pose par l'overlay lui-meme, sur son seul chemin de
# succes (film_support.TMDB_OVERLAY_DONE_KEY).
# ---------------------------------------------------------------------------


class _RaisingFilmModal:
    """film_modal dont la lecture leve — base verrouillee, table absente..."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    def get_tmdb_override(self, *, run_id: str, row_id: str):  # noqa: ANN201
        self.calls += 1
        raise self.exc


class OverlayMarkerContractTests(unittest.TestCase):
    """Contrat du marqueur : pose SEULEMENT si la table a ete lue avec succes."""

    def test_marker_set_when_read_succeeds_without_override(self) -> None:
        """Lecture aboutie mais aucun override : c'est un SUCCES (rien a
        appliquer) -> marqueur pose, l'aval n'a pas a relire."""
        from cinesort.ui.api.film_support import overlay_tmdb_override

        store = _FakeStore(_CountingFilmModal({}))
        row = {"row_id": "r0", "proposed_title": "Auto"}

        self.assertFalse(overlay_tmdb_override(store, "R1", row))
        self.assertTrue(row.get(TMDB_OVERLAY_DONE_KEY))

    def test_no_marker_when_store_is_none(self) -> None:
        """Chemin 1 du relecteur : _get_store a renvoye None -> no-op complet."""
        from cinesort.ui.api.film_support import overlay_tmdb_override

        row = {"row_id": "r0", "proposed_title": "Auto"}

        self.assertFalse(overlay_tmdb_override(None, "R1", row))
        self.assertNotIn(TMDB_OVERLAY_DONE_KEY, row)

    def test_no_marker_when_row_id_missing(self) -> None:
        from cinesort.ui.api.film_support import overlay_tmdb_override

        store = _FakeStore(_CountingFilmModal({}))
        row = {"proposed_title": "Auto"}

        self.assertFalse(overlay_tmdb_override(store, "R1", row))
        self.assertNotIn(TMDB_OVERLAY_DONE_KEY, row)

    def test_no_marker_when_read_raises_sqlite_error(self) -> None:
        """Chemin 2 du relecteur : base verrouillee -> aucun etat fiable."""
        from cinesort.ui.api.film_support import overlay_tmdb_override

        modal = _RaisingFilmModal(sqlite3.OperationalError("database is locked"))
        store = _FakeStore(modal)  # type: ignore[arg-type]
        row = {"row_id": "r0", "proposed_title": "Auto"}

        self.assertFalse(overlay_tmdb_override(store, "R1", row))
        self.assertNotIn(TMDB_OVERLAY_DONE_KEY, row)

    def test_sqlite_error_is_caught_not_propagated(self) -> None:
        """Objection 3 : sqlite3.Error n'herite PAS d'OSError (regle 4 du
        CLAUDE.md). Sans lui dans le tuple, une base verrouillee remontait en
        exception nue et faisait tomber TOUTE la vue Bibliotheque."""
        from cinesort.ui.api.film_support import overlay_tmdb_override

        for exc in (
            sqlite3.OperationalError("database is locked"),
            sqlite3.DatabaseError("file is not a database"),
        ):
            with self.subTest(exc=type(exc).__name__):
                store = _FakeStore(_RaisingFilmModal(exc))  # type: ignore[arg-type]
                row = {"row_id": "r0", "proposed_title": "Auto"}
                self.assertFalse(overlay_tmdb_override(store, "R1", row))

    def test_sqlite_error_does_not_break_the_library_view(self) -> None:
        """Meme chose vue de la Bibliotheque : la vue se construit encore."""
        rows = [_plan_row("r0", tmdb_id=111), _plan_row("r1", tmdb_id=222)]
        api = _FakeApi(rows)
        api.store.film_modal = _RaisingFilmModal(sqlite3.OperationalError("database is locked"))

        out = library_support._build_library_rows(api, "run1")

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["tmdb_id"], 111)


class DisplayTitleIsNotAProofTests(unittest.TestCase):
    """`display_title` seul ne doit PLUS suffire a sauter l'overlay."""

    def test_display_title_without_marker_is_still_overlaid(self) -> None:
        """La row a traverse _enrich_plan_payload (display_title pose) mais son
        overlay a echoue (pas de marqueur) : la Bibliotheque DOIT rattraper."""
        row = _plan_row("r0", tmdb_id=111)
        row["display_title"] = "Auto r0"  # pose par setdefault, overlay echoue
        row["auto_approvable"] = True
        api = _FakeApi(
            [row],
            overrides={
                "r0": {
                    "tmdb_id": 999,
                    "proposed_title": "Choix Manuel",
                    "proposed_year": 2021,
                    "new_confidence": 88,
                }
            },
        )

        out = library_support._build_library_rows(api, "run1")

        self.assertEqual(api.film_modal.calls, ["run1/r0"])
        self.assertEqual(out[0]["tmdb_id"], 999)
        self.assertEqual(out[0]["title"], "Choix Manuel")


# ---------------------------------------------------------------------------
# 4bis. Chaine REELLE : _enrich_plan_payload -> _build_library_rows
#       Aucun stub de get_plan, aucun pre-tamponnage : c'est le vrai
#       _enrich_plan_payload qui produit (ou non) le marqueur, sur un VRAI
#       SQLiteStore.
# ---------------------------------------------------------------------------


class _FlakyFilmModal:
    """Enveloppe le VRAI FilmModalRepository ; les `fail_first` premieres
    lectures PAR ROW levent, et les `fail_bulk_first` premieres lectures
    GROUPEES aussi (verrou SQLite transitoire : contention avec un ecrivain,
    resolue quelques ms plus tard).

    FUSION #853 x #849 : `_enrich_plan_payload` ne lit plus les overrides par
    row mais en UN SELECT (`film_support.list_tmdb_overrides_bulk`, qui passe
    par `_ensure_tables` + `_managed_conn`). Un double qui ne sait faire echouer
    que `get_tmdb_override` ne peut donc PLUS produire la panne que ces tests
    pretendent prouver : il resterait vert quoi qu'il arrive. On instrumente les
    DEUX chemins.
    """

    def __init__(self, inner: Any, fail_first: int = 0, fail_bulk_first: int = 0) -> None:
        self._inner = inner
        self.fail_first = fail_first
        self.fail_bulk_first = fail_bulk_first
        self.calls: List[str] = []
        self.bulk_calls = 0

    def get_tmdb_override(self, *, run_id: str, row_id: str):  # noqa: ANN201
        self.calls.append(f"{run_id}/{row_id}")
        if len(self.calls) <= self.fail_first:
            raise sqlite3.OperationalError("database is locked")
        return self._inner.get_tmdb_override(run_id=run_id, row_id=row_id)

    def _ensure_tables(self) -> None:
        """Premier appel de la lecture GROUPEE : c'est ici qu'on la fait echouer."""
        self.bulk_calls += 1
        if self.bulk_calls <= self.fail_bulk_first:
            raise sqlite3.OperationalError("database is locked")
        self._inner._ensure_tables()  # noqa: SLF001

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _RealChainApi:
    """api cable sur la VRAIE chaine : run.get_plan appelle le vrai
    history_support._enrich_plan_payload, qui appelle le vrai
    overlay_tmdb_override sur un vrai SQLiteStore."""

    class _Settings:
        def __init__(self, state_dir: str) -> None:
            self._state_dir = state_dir

        def get_settings(self) -> Dict[str, Any]:
            return {"state_dir": self._state_dir}

    class _Run:
        def __init__(self, outer: "_RealChainApi") -> None:
            self._outer = outer

        def get_plan(self, run_id: str) -> Dict[str, Any]:
            # get_plan re-serialise les rows a chaque appel (_serialize_rows_for_payload)
            rows = [dict(r) for r in self._outer.raw_rows]
            enriched = history_support._enrich_plan_payload(self._outer, run_id, rows)
            self._outer.calls_after_enrich = len(self._outer.film_modal.calls)
            return {"ok": True, "rows": enriched}

    def __init__(self, store: Any, state_dir: str, raw_rows: List[Dict[str, Any]]) -> None:
        self.settings = self._Settings(state_dir)
        self.run = self._Run(self)
        self.store = store
        self.raw_rows = raw_rows
        self.integrations = _CountingIntegrations()
        self.calls_after_enrich = 0

    @property
    def film_modal(self) -> Any:
        return self.store.film_modal

    def _get_or_create_infra(self, state_dir):  # noqa: ANN001, ANN202
        return (self.store, None)

    def _get_settings_impl(self) -> Dict[str, Any]:
        return {"auto_approve_threshold": 85}


class RealChainOverlayIntegrationTests(unittest.TestCase):
    """Demande 2 du relecteur : un test sur la chaine REELLE, qui rougit quand
    l'overlay de l'enrichissement echoue en silence."""

    def setUp(self) -> None:
        from cinesort.infra.db.sqlite_store import SQLiteStore

        self._tmp = tempfile.mkdtemp(prefix="perf849_")
        self.store = SQLiteStore(Path(self._tmp) / "t.sqlite")
        self.store.initialize()
        self.store.film_modal.upsert_tmdb_override(
            run_id="run1",
            row_id="r0",
            tmdb_id=999,
            new_confidence=88,
            proposed_title="Choix Manuel",
            proposed_year=2021,
        )
        self.raw_rows = [
            {
                "row_id": "r0",
                "proposed_title": "Auto r0",
                "proposed_year": 1999,
                "confidence": 50,
                "tmdb_id": 111,
                "proposed_source": "nfo",
                "candidates": [],
            }
        ]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _api(self, fail_first: int = 0, fail_bulk_first: int = 0) -> _RealChainApi:
        self.store.film_modal = _FlakyFilmModal(
            self.store.film_modal, fail_first=fail_first, fail_bulk_first=fail_bulk_first
        )
        return _RealChainApi(self.store, self._tmp, self.raw_rows)

    def test_manual_override_visible_and_read_once(self) -> None:
        """Cas nominal : le choix manuel est affiche, et _build_library_rows
        n'ajoute AUCUNE relecture par-dessus celle de l'enrichissement (c'est
        tout le gain de perf de la PR, mesure ici sur la vraie chaine)."""
        api = self._api()

        out = library_support._build_library_rows(api, "run1")

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Choix Manuel")
        self.assertEqual(out[0]["tmdb_id"], 999)
        self.assertEqual(out[0]["year"], 2021)
        # FUSION #853 : l'enrichissement lit desormais les overrides du run en
        # UNE fois -> plus AUCUNE lecture par row, ni pendant l'enrichissement
        # ni apres. Retirer le guard du marqueur dans _build_library_rows
        # repeuple immediatement `calls` : le pouvoir de detection est intact.
        self.assertEqual(api.film_modal.calls, [])
        self.assertEqual(api.film_modal.bulk_calls, 1)
        self.assertEqual(len(api.film_modal.calls) - api.calls_after_enrich, 0)

    def test_manual_override_survives_a_failed_enrichment_overlay(self) -> None:
        """LE test qui manquait. L'overlay de _enrich_plan_payload echoue (verrou
        SQLite transitoire, avale par son contextlib.suppress) mais il pose quand
        meme display_title. Sans marqueur explicite, la Bibliotheque sautait le
        rattrapage et le choix manuel disparaissait -> 'Auto r0' / 111.

        FUSION #853 : l'enrichissement a maintenant DEUX chemins d'overlay (le
        SELECT groupe, puis le repli par row). Le verrou doit les faire echouer
        tous les deux pour reproduire la panne — sinon le repli sauve la row et
        le test ne teste plus rien."""
        api = self._api(fail_first=1, fail_bulk_first=1)

        out = library_support._build_library_rows(api, "run1")

        # L'enrichissement a bien pose display_title malgre l'overlay echoue :
        # c'est exactement ce qui rendait l'ancien guard faux.
        self.assertEqual(api.calls_after_enrich, 1)
        self.assertEqual(len(api.film_modal.calls), 2)
        self.assertEqual(out[0]["title"], "Choix Manuel")
        self.assertEqual(out[0]["tmdb_id"], 999)
        self.assertEqual(out[0]["year"], 2021)

    def test_manual_override_survives_a_failed_bulk_read_alone(self) -> None:
        """FUSION #853 x #849 : la seule lecture groupee tombe, le repli par row
        de l'enrichissement aboutit. La row est alors marquee par
        `overlay_tmdb_override` et la Bibliotheque n'a RIEN a relire."""
        api = self._api(fail_bulk_first=1)

        out = library_support._build_library_rows(api, "run1")

        self.assertEqual(api.film_modal.calls, ["run1/r0"])  # repli par row, 1 seule fois
        self.assertEqual(api.calls_after_enrich, 1)  # aucune relecture cote Bibliotheque
        self.assertEqual(out[0]["title"], "Choix Manuel")
        self.assertEqual(out[0]["tmdb_id"], 999)
        self.assertEqual(out[0]["year"], 2021)

    def test_enrichment_stamps_display_title_even_when_overlay_fails(self) -> None:
        """Preuve directe de l'objection : `display_title` est pose meme quand
        l'overlay vient d'echouer -> il ne prouve rien sur l'overlay."""
        api = self._api(fail_first=1, fail_bulk_first=1)

        rows = api.run.get_plan("run1")["rows"]

        self.assertEqual(rows[0]["display_title"], "Auto r0")
        self.assertNotIn(TMDB_OVERLAY_DONE_KEY, rows[0])

    def test_enrichment_stamps_marker_on_success(self) -> None:
        """Non-regression du gain de perf : sur le chemin nominal le marqueur EST
        pose par la vraie chaine (sinon la Bibliotheque relirait toujours).

        FUSION #853 : c'est desormais la lecture GROUPEE qui doit le poser
        (`apply_tmdb_overrides_bulk`), sans quoi le N+1 supprime par #853
        reviendrait par la Bibliotheque, fail-closed sur ce marqueur."""
        api = self._api()

        rows = api.run.get_plan("run1")["rows"]

        self.assertTrue(rows[0][TMDB_OVERLAY_DONE_KEY])
        self.assertEqual(rows[0]["proposed_title"], "Choix Manuel")
        self.assertEqual(api.film_modal.calls, [])


if __name__ == "__main__":
    unittest.main()
