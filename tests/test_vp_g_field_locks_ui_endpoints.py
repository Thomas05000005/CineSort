"""Vague P / VP-G : tests cablage UI -> backend field_locks.

Cf docs/internal/AUDIT_VP_G_LIB_VALIDATION_V5_LEGACY.md.

Le fichier `web/dashboard/views/library/lib-validation.js` appelle 3
endpoints qui n'existaient pas avant VP-G :
- `library/set_field_lock`
- `library/clear_field_lock`
- `library/list_field_locks`

Ces tests valident :
1. La presence des methodes sur `LibraryFacade` (rest_server pass 2
   les expose automatiquement sous `/api/library/{method}`).
2. Le bon delegate vers `library_support.{set,clear,list}_field_lock(s)`.
3. Le bon delegate vers `FieldLocksRepository.{set,clear,list}_lock(s)`.
4. Backward compat : les routes existantes ne sont pas modifiees.
"""

from __future__ import annotations

import inspect
import sys
import unittest

sys.path.insert(0, ".")

from cinesort.ui.api import library_support
from cinesort.ui.api.facades.library_facade import LibraryFacade


class _FakeRepo:
    """Stub FieldLocksRepository — enregistre les appels pour assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self._locks: dict[tuple[str, str], dict] = {}

    def set_lock(self, film_id, field_name, locked_value, *, run_id="", row_id="", source="ui_lock"):
        self.calls.append(
            (
                "set_lock",
                (film_id, field_name, locked_value),
                {
                    "run_id": run_id,
                    "row_id": row_id,
                    "source": source,
                },
            )
        )
        self._locks[(film_id, field_name)] = {
            "locked_value": locked_value,
            "source": source,
            "locked_at": 1700000000.0,
        }
        return {"ok": True, "locked_at": 1700000000.0}

    def clear_lock(self, film_id, field_name):
        self.calls.append(("clear_lock", (film_id, field_name), {}))
        existed = self._locks.pop((film_id, field_name), None)
        return {"ok": True, "removed": bool(existed)}

    def list_locks(self, film_id):
        self.calls.append(("list_locks", (film_id,), {}))
        out = []
        for (fid, fname), entry in self._locks.items():
            if fid == film_id:
                out.append({**entry, "field_name": fname, "run_id": "", "row_id": ""})
        return out


class _FakeStore:
    def __init__(self) -> None:
        self.field_locks = _FakeRepo()


class _FakeSettingsFacade:
    def get_settings(self):
        return {"state_dir": "/tmp/cinesort_vpg_fake_state"}


class _FakeApi:
    """Stub CineSortApi pour test endpoints VP-G."""

    def __init__(self) -> None:
        self._store = _FakeStore()
        self.settings = _FakeSettingsFacade()

    def _get_or_create_infra(self, _state_dir):  # noqa: ARG002
        return self._store, None


class _NoStoreApi:
    """Stub CineSortApi qui leve sur _get_or_create_infra (store HS)."""

    def __init__(self) -> None:
        self.settings = _FakeSettingsFacade()

    def _get_or_create_infra(self, _state_dir):  # noqa: ARG002
        raise OSError("infra HS")


# ---------------------------------------------------------------------------
# Section 1 : presence des methodes sur LibraryFacade (route auto-exposee).
# ---------------------------------------------------------------------------


class LibraryFacadeFieldLockMethodsTests(unittest.TestCase):
    """VP-G : routes attendues exposees par introspection rest_server."""

    def test_set_field_lock_exposed(self):
        self.assertTrue(
            hasattr(LibraryFacade, "set_field_lock"),
            "LibraryFacade.set_field_lock requis pour /api/library/set_field_lock",
        )
        self.assertTrue(callable(getattr(LibraryFacade, "set_field_lock")))

    def test_clear_field_lock_exposed(self):
        self.assertTrue(
            hasattr(LibraryFacade, "clear_field_lock"),
            "LibraryFacade.clear_field_lock requis pour /api/library/clear_field_lock",
        )
        self.assertTrue(callable(getattr(LibraryFacade, "clear_field_lock")))

    def test_list_field_locks_exposed(self):
        self.assertTrue(
            hasattr(LibraryFacade, "list_field_locks"),
            "LibraryFacade.list_field_locks requis pour /api/library/list_field_locks",
        )
        self.assertTrue(callable(getattr(LibraryFacade, "list_field_locks")))

    def test_set_field_lock_signature_matches_frontend_payload(self):
        """lib-validation.js#setFieldLock envoie : film_id, field_name,
        locked_value, source. La methode facade doit accepter ces kwargs."""
        sig = inspect.signature(LibraryFacade.set_field_lock)
        params = set(sig.parameters.keys())
        self.assertIn("film_id", params)
        self.assertIn("field_name", params)
        self.assertIn("locked_value", params)
        self.assertIn("source", params)


# ---------------------------------------------------------------------------
# Section 2 : library_support delegate correctement vers FieldLocksRepository.
# ---------------------------------------------------------------------------


class LibrarySupportSetFieldLockTests(unittest.TestCase):
    def test_set_field_lock_ok_path(self):
        api = _FakeApi()
        res = library_support.set_field_lock(
            api,
            film_id="tmdb:603",
            field_name="title",
            locked_value="The Matrix",
            source="ui_lock",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["film_id"], "tmdb:603")
        self.assertEqual(res["field_name"], "title")
        self.assertEqual(res["source"], "ui_lock")
        self.assertGreater(res["locked_at"], 0)
        # Verifier delegation au repo
        repo: _FakeRepo = api._store.field_locks
        self.assertEqual(len(repo.calls), 1)
        self.assertEqual(repo.calls[0][0], "set_lock")
        self.assertEqual(repo.calls[0][1], ("tmdb:603", "title", "The Matrix"))

    def test_set_field_lock_rejects_empty_film_id(self):
        api = _FakeApi()
        res = library_support.set_field_lock(api, film_id="", field_name="title")
        self.assertFalse(res["ok"])
        self.assertEqual(len(api._store.field_locks.calls), 0)

    def test_set_field_lock_rejects_empty_field_name(self):
        api = _FakeApi()
        res = library_support.set_field_lock(api, film_id="tmdb:1", field_name="")
        self.assertFalse(res["ok"])
        self.assertEqual(len(api._store.field_locks.calls), 0)

    def test_set_field_lock_normalizes_invalid_source(self):
        """Source inconnue (ex. 'evil_script') doit retomber sur 'ui_lock'."""
        api = _FakeApi()
        res = library_support.set_field_lock(
            api,
            film_id="tmdb:1",
            field_name="title",
            locked_value="x",
            source="evil_script",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["source"], "ui_lock")

    def test_set_field_lock_handles_store_unavailable(self):
        """Si _get_or_create_infra leve, on retourne err runtime, pas crash."""
        api = _NoStoreApi()
        res = library_support.set_field_lock(api, film_id="tmdb:1", field_name="title")
        self.assertFalse(res["ok"])


class LibrarySupportClearFieldLockTests(unittest.TestCase):
    def test_clear_field_lock_idempotent_no_lock(self):
        api = _FakeApi()
        res = library_support.clear_field_lock(api, "tmdb:999", "title")
        self.assertTrue(res["ok"])
        self.assertFalse(res["removed"])

    def test_clear_field_lock_removes_existing(self):
        api = _FakeApi()
        library_support.set_field_lock(api, film_id="tmdb:1", field_name="title", locked_value="x")
        res = library_support.clear_field_lock(api, "tmdb:1", "title")
        self.assertTrue(res["ok"])
        self.assertTrue(res["removed"])

    def test_clear_field_lock_rejects_empty(self):
        api = _FakeApi()
        self.assertFalse(library_support.clear_field_lock(api, "", "title")["ok"])
        self.assertFalse(library_support.clear_field_lock(api, "tmdb:1", "")["ok"])


class LibrarySupportListFieldLocksTests(unittest.TestCase):
    def test_list_field_locks_empty(self):
        api = _FakeApi()
        res = library_support.list_field_locks(api, "tmdb:42")
        self.assertTrue(res["ok"])
        self.assertEqual(res["film_id"], "tmdb:42")
        self.assertEqual(res["locks"], [])

    def test_list_field_locks_returns_all(self):
        api = _FakeApi()
        library_support.set_field_lock(api, film_id="tmdb:42", field_name="title", locked_value="Star Wars")
        library_support.set_field_lock(api, film_id="tmdb:42", field_name="year", locked_value=1977)
        # Autre film -> ne doit pas apparaitre
        library_support.set_field_lock(api, film_id="tmdb:43", field_name="title", locked_value="Other")

        res = library_support.list_field_locks(api, "tmdb:42")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["locks"]), 2)
        field_names = {lk["field_name"] for lk in res["locks"]}
        self.assertEqual(field_names, {"title", "year"})

    def test_list_field_locks_empty_film_id_rejects(self):
        api = _FakeApi()
        res = library_support.list_field_locks(api, "")
        self.assertFalse(res["ok"])

    def test_list_field_locks_store_unavailable_returns_empty_ok(self):
        """Best-effort : store HS -> ok=True, locks=[] (UI continue de fonctionner)."""
        api = _NoStoreApi()
        res = library_support.list_field_locks(api, "tmdb:1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["locks"], [])


# ---------------------------------------------------------------------------
# Section 3 : LibraryFacade delegate correctement vers library_support.
# ---------------------------------------------------------------------------


class LibraryFacadeDelegationTests(unittest.TestCase):
    def _make_facade(self) -> tuple[LibraryFacade, _FakeApi]:
        api = _FakeApi()
        facade = LibraryFacade(api)
        return facade, api

    def test_facade_set_field_lock_delegates(self):
        facade, api = self._make_facade()
        res = facade.set_field_lock(
            film_id="tmdb:603",
            field_name="title",
            locked_value="Matrix",
            source="ui_lock",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(len(api._store.field_locks.calls), 1)

    def test_facade_clear_field_lock_delegates(self):
        facade, api = self._make_facade()
        facade.set_field_lock(film_id="tmdb:1", field_name="title", locked_value="x")
        res = facade.clear_field_lock(film_id="tmdb:1", field_name="title")
        self.assertTrue(res["ok"])
        self.assertTrue(res["removed"])

    def test_facade_list_field_locks_delegates(self):
        facade, api = self._make_facade()
        facade.set_field_lock(film_id="tmdb:42", field_name="title", locked_value="SW")
        res = facade.list_field_locks(film_id="tmdb:42")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["locks"]), 1)


# ---------------------------------------------------------------------------
# Section 4 : backward compat — routes existantes preservees.
# ---------------------------------------------------------------------------


class BackwardCompatExistingRoutesTests(unittest.TestCase):
    """VP-G AC backward compat ABSOLUE : aucune methode existante n'est cassee."""

    def test_existing_routes_still_exposed(self):
        for method_name in [
            "get_library_filtered",
            "get_smart_playlists",
            "save_smart_playlist",
            "delete_smart_playlist",
            "get_scoring_rollup",
            "set_film_tmdb_candidate",
            "search_tmdb",
            "mark_for_deletion",
            "mark_alert_ignored",
            "get_film_full",
            "get_film_history",
            "list_films_with_history",
            "export_full_library",
            "get_library_podiums",
            "get_library_timeline",
            "get_library_counters_by_chip",
            "mark_for_deletion_bulk",
            "export_films",
            "get_films_by_decade",
            "get_incomplete_sagas",
        ]:
            self.assertTrue(
                hasattr(LibraryFacade, method_name),
                f"Backward compat : LibraryFacade.{method_name} disparue",
            )


if __name__ == "__main__":
    unittest.main()
