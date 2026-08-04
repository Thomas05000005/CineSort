"""`get_tmdb_posters` : le cap defensif ne doit pas biaiser QUELS films perdent
leur jaquette.

Ultra-audit 2026-08 (N20) : le cap s'ecrivait `sorted(set(ids))[:2000]`, donc il
conservait les 2000 PLUS PETITS tmdb_id. Les identifiants TMDb croissent avec le
temps : au-dela de 2000 films, les jaquettes silencieusement perdues etaient
donc systematiquement celles des films les plus RECENTS. `_build_library_rows`
collecte les ids AVANT pagination (library_support.py:288-306), donc une
bibliotheque de 3000 films exposait le defaut sur toutes les pages, a chaque
appel, de facon stable.

Ces tests n'ouvrent aucun reseau : `TmdbClient` est remplace par un double qui
enregistre les ids reellement demandes. On observe le COMPORTEMENT (quels ids
sont resolus, ce que la reponse annonce), jamais le texte du code source.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

sys.path.insert(0, ".")

from cinesort.ui.api import tmdb_support


class _RecordingTmdbClient:
    """Double de `TmdbClient` : n'ouvre rien, note les ids demandes."""

    last_instance: "_RecordingTmdbClient | None" = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requested: List[int] = []
        self.flushed = 0
        _RecordingTmdbClient.last_instance = self

    def get_movie_poster_thumb_url(self, movie_id: int, size: str = "w92", force_refresh: bool = False) -> str:
        self.requested.append(int(movie_id))
        return f"https://image.tmdb.org/t/p/{size}/p{movie_id}.jpg"

    def flush(self) -> None:
        self.flushed += 1


class _FakeApi:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def _internal_settings(self) -> Dict[str, Any]:
        return {"tmdb_api_key": "cle-de-test", "state_dir": str(self._state_dir)}


class TmdbPostersCapOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.api = _FakeApi(Path(self._tmp.name))
        _RecordingTmdbClient.last_instance = None

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(self, ids: List[int], **kwargs: Any) -> Dict[str, Any]:
        with mock.patch.object(tmdb_support, "TmdbClient", _RecordingTmdbClient):
            return tmdb_support.get_tmdb_posters(self.api, ids, **kwargs)

    @property
    def _requested(self) -> List[int]:
        inst = _RecordingTmdbClient.last_instance
        assert inst is not None, "le client TMDb n'a jamais ete construit"
        return inst.requested

    # -- 1) le cap tronque la QUEUE de l'appelant, pas les plus grands ids ---

    def test_cap_keeps_the_callers_first_ids_not_the_smallest(self) -> None:
        """Une bibliotheque triee par date : les films recents (gros ids) d'abord.

        Avec l'ancien `sorted(...)`, aucun d'eux n'etait servi.
        """
        cap = tmdb_support._POSTERS_MAX_IDS
        # L'appelant envoie d'abord les recents (ids eleves), puis les vieux.
        recents = list(range(900_000, 900_000 + cap))
        vieux = list(range(1, 501))
        out = self._call(recents + vieux)

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._requested, recents, "le cap n'a pas respecte l'ordre de l'appelant")
        # Le defaut historique : pas un seul film recent servi.
        self.assertEqual(
            [i for i in self._requested if i >= 900_000],
            recents,
            "les films recents (gros tmdb_id) ont ete sacrifies par le cap",
        )
        self.assertEqual(len(out["posters"]), cap)
        self.assertIn("900000", out["posters"])

    def test_small_ids_are_not_privileged_over_the_caller_order(self) -> None:
        """Cas minimal et lisible du meme biais, sans dependre du cap reel."""
        with mock.patch.object(tmdb_support, "_POSTERS_MAX_IDS", 2):
            out = self._call([999_999, 800_000, 3, 7])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._requested, [999_999, 800_000])
        self.assertEqual(sorted(out["posters"].keys()), ["800000", "999999"])

    # -- 2) la troncature est ANNONCEE --------------------------------------

    def test_truncation_is_reported_to_the_caller(self) -> None:
        with mock.patch.object(tmdb_support, "_POSTERS_MAX_IDS", 3):
            out = self._call([10, 20, 30, 40, 50])
        self.assertEqual(out.get("truncated"), 2, "la troncature doit etre annoncee, pas silencieuse")
        self.assertEqual(len(out["posters"]), 3)

    def test_no_truncation_field_when_nothing_is_dropped(self) -> None:
        """Cas courant : la reponse ne change pas de forme."""
        out = self._call([10, 20, 30])
        self.assertEqual(out.get("ok"), True)
        self.assertNotIn("truncated", out, "champ parasite sur le cas nominal")
        self.assertEqual(len(out["posters"]), 3)

    # -- 3) invariants preexistants non regresses ---------------------------

    def test_duplicates_are_collapsed_keeping_first_occurrence(self) -> None:
        out = self._call([42, 7, 42, 7, 42])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._requested, [42, 7], "dedoublonnage casse")
        self.assertEqual(len(out["posters"]), 2)

    def test_invalid_and_non_positive_ids_are_dropped(self) -> None:
        out = self._call([0, -5, "abc", None, 12, "34"])  # type: ignore[list-item]
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._requested, [12, 34])

    def test_empty_after_filtering_returns_no_posters(self) -> None:
        out = self._call([0, -1, "zzz"])  # type: ignore[list-item]
        self.assertEqual(out, {"ok": True, "posters": {}})
        self.assertIsNone(_RecordingTmdbClient.last_instance, "aucun client ne doit etre construit pour rien")

    def test_not_a_list_is_a_validation_error(self) -> None:
        out = tmdb_support.get_tmdb_posters(self.api, "42")  # type: ignore[arg-type]
        self.assertFalse(out.get("ok"), out)


if __name__ == "__main__":
    unittest.main()
