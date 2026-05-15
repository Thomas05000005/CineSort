"""V2-06 — Tests tmdb_support wrapper module (get_tmdb_posters)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.ui.api import tmdb_support


def _make_api(api_key: str = "fake_key", state_dir: str = "/tmp/state", timeout_s: float = 10.0) -> MagicMock:
    """Construit un faux objet api compatible avec get_tmdb_posters."""
    api = MagicMock()
    api.settings.get_settings.return_value = {
        "tmdb_api_key": api_key,
        "state_dir": state_dir,
        "tmdb_timeout_s": timeout_s,
    }
    api._normalize_user_path.return_value = Path(state_dir)
    return api


class TestGetTmdbPostersValidation(unittest.TestCase):
    """Validation de l'entree tmdb_ids et cas triviaux."""

    def test_tmdb_ids_not_a_list_returns_error(self):
        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids="not-a-list")  # type: ignore[arg-type]
        self.assertFalse(result["ok"])
        self.assertIn("Payload invalide", result["message"])

    def test_tmdb_ids_dict_returns_error(self):
        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids={"a": 1})  # type: ignore[arg-type]
        self.assertFalse(result["ok"])
        self.assertIn("liste", result["message"])

    def test_tmdb_ids_empty_list_returns_empty_posters(self):
        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {})
        # Aucun appel a get_settings (court-circuit avant) - PR 10 #84 : path facade
        api.settings.get_settings.assert_not_called()

    def test_tmdb_ids_only_invalid_items_returns_empty_posters(self):
        api = _make_api()
        # Aucun ID valide : strings non numeriques, None, valeurs <= 0
        result = tmdb_support.get_tmdb_posters(
            api,
            tmdb_ids=["abc", None, -1, 0, "xx"],  # type: ignore[list-item]
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {})

    def test_tmdb_ids_none_in_list_is_skipped(self):
        api = _make_api()
        # None doit etre ignore mais 42 doit etre conserve
        with patch("cinesort.ui.api.tmdb_support.TmdbClient") as mock_client_cls:
            client = MagicMock()
            client.get_movie_poster_thumb_url.return_value = "https://img/42.jpg"
            mock_client_cls.return_value = client
            result = tmdb_support.get_tmdb_posters(
                api,
                tmdb_ids=[None, 42],  # type: ignore[list-item]
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {"42": "https://img/42.jpg"})


class TestGetTmdbPostersNoApiKey(unittest.TestCase):
    """Cas ou la cle API est manquante ou vide."""

    def test_empty_api_key_returns_empty_posters(self):
        api = _make_api(api_key="")
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1, 2])
        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {})

    def test_whitespace_api_key_treated_as_empty(self):
        api = _make_api(api_key="   ")
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1, 2])
        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {})

    def test_none_api_key_returns_empty_posters(self):
        api = MagicMock()
        api.settings.get_settings.return_value = {"tmdb_api_key": None, "state_dir": "/tmp", "tmdb_timeout_s": 10}
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])
        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {})


class TestGetTmdbPostersSuccess(unittest.TestCase):
    """Cas nominal : ids valides + api_key + TmdbClient retourne des urls."""

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_success_returns_posters_dict(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.side_effect = lambda mid, size: f"https://img/{mid}_{size}.jpg"
        mock_client_cls.return_value = client

        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1, 2, 3])

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["posters"],
            {
                "1": "https://img/1_w92.jpg",
                "2": "https://img/2_w92.jpg",
                "3": "https://img/3_w92.jpg",
            },
        )
        client.flush.assert_called_once()

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_size_parameter_propagated(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://img/x.jpg"
        mock_client_cls.return_value = client

        api = _make_api()
        tmdb_support.get_tmdb_posters(api, tmdb_ids=[7], size="w185")

        client.get_movie_poster_thumb_url.assert_called_once_with(7, size="w185")

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_empty_size_falls_back_to_w92(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://img/x.jpg"
        mock_client_cls.return_value = client

        api = _make_api()
        tmdb_support.get_tmdb_posters(api, tmdb_ids=[7], size="")

        client.get_movie_poster_thumb_url.assert_called_once_with(7, size="w92")

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_client_returns_no_url_omits_entry(self, mock_client_cls):
        client = MagicMock()
        # id 1 → url valide, id 2 → None (omis), id 3 → "" (omis)
        client.get_movie_poster_thumb_url.side_effect = [
            "https://img/1.jpg",
            None,
            "",
        ]
        mock_client_cls.return_value = client

        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1, 2, 3])

        self.assertTrue(result["ok"])
        self.assertEqual(result["posters"], {"1": "https://img/1.jpg"})

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_ids_deduplicated_and_sorted(self, mock_client_cls):
        captured_ids: list[int] = []
        client = MagicMock()
        client.get_movie_poster_thumb_url.side_effect = lambda mid, size: (
            captured_ids.append(mid) or f"https://img/{mid}.jpg"
        )
        mock_client_cls.return_value = client

        api = _make_api()
        tmdb_support.get_tmdb_posters(api, tmdb_ids=[3, 1, 2, 1, 3, 2])

        # Dedup et tri
        self.assertEqual(captured_ids, [1, 2, 3])

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_ids_capped_at_20(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://img/x.jpg"
        mock_client_cls.return_value = client

        api = _make_api()
        big_list = list(range(1, 100))  # 99 ids
        tmdb_support.get_tmdb_posters(api, tmdb_ids=big_list)

        # Cap a 20 => 20 appels
        self.assertEqual(client.get_movie_poster_thumb_url.call_count, 20)

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_string_numeric_ids_converted_to_int(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://img/x.jpg"
        mock_client_cls.return_value = client

        api = _make_api()
        result = tmdb_support.get_tmdb_posters(
            api,
            tmdb_ids=["5", "10", "abc"],  # type: ignore[list-item]
        )

        self.assertTrue(result["ok"])
        # "abc" rejete, "5" et "10" convertis
        self.assertEqual(set(result["posters"].keys()), {"5", "10"})

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_tmdb_client_constructed_with_settings(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://img/x.jpg"
        mock_client_cls.return_value = client

        api = _make_api(api_key="my_key", state_dir="/var/cache", timeout_s=15.0)
        tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])

        # Verifie que TmdbClient a recu les bons arguments
        mock_client_cls.assert_called_once()
        kwargs = mock_client_cls.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "my_key")
        self.assertEqual(kwargs["timeout_s"], 15.0)
        self.assertEqual(kwargs["cache_path"], Path("/var/cache") / "tmdb_cache.json")

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_default_timeout_when_settings_missing(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://img/x.jpg"
        mock_client_cls.return_value = client

        api = MagicMock()
        api.settings.get_settings.return_value = {
            "tmdb_api_key": "k",
            "state_dir": "/tmp",
            # tmdb_timeout_s absent
        }
        api._normalize_user_path.return_value = Path("/tmp")
        tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])

        kwargs = mock_client_cls.call_args.kwargs
        self.assertEqual(kwargs["timeout_s"], 10.0)


class TestGetTmdbPostersErrors(unittest.TestCase):
    """Erreurs runtime capturees par le bloc except."""

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_oserror_during_fetch_returns_error(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.side_effect = OSError("disk fail")
        mock_client_cls.return_value = client

        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])

        self.assertFalse(result["ok"])
        self.assertIn("disk fail", result["message"])

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_valueerror_during_fetch_returns_error(self, mock_client_cls):
        client = MagicMock()
        client.get_movie_poster_thumb_url.side_effect = ValueError("bad payload")
        mock_client_cls.return_value = client

        api = _make_api()
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])

        self.assertFalse(result["ok"])
        self.assertIn("bad payload", result["message"])

    def test_get_settings_raises_keyerror_returns_error(self):
        api = MagicMock()
        api.settings.get_settings.side_effect = KeyError("settings missing")
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])

        self.assertFalse(result["ok"])
        self.assertIn("settings missing", result["message"])

    def test_get_settings_raises_typeerror_returns_error(self):
        api = MagicMock()
        api.settings.get_settings.side_effect = TypeError("api broken")
        result = tmdb_support.get_tmdb_posters(api, tmdb_ids=[1])

        self.assertFalse(result["ok"])
        self.assertIn("api broken", result["message"])


if __name__ == "__main__":
    unittest.main()
