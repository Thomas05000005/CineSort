"""Tests Vague H (v1.5.3) - 3 bugs critiques clients API externes.

Couvre les fixes Vague H :

1. `jellyfin_client.validate_connection` : ne doit JAMAIS appeler requests.get
   directement sans timeout. L'appel passe par self._get() qui transmet
   timeout=self.timeout_s a requests. On verifie que le kwarg `timeout` est
   bien transmis a la couche reseau.

2. `plex_client.get_movies_count` : X-Plex-Container-Size est un header
   HTTP, pas un query param. Le bug initial le passait dans `params={}`
   donc Plex l'ignorait silencieusement. On verifie que le header est
   bien envoye.

3. `omdb_client._save_cache_atomic` : pattern atomic safe. Si l'ecriture
   du tmp echoue (fsync raise / fichier vide), le cache original sur
   disque doit etre preserve.

Fix audit 2026-05-25 (v1.5.3) Vague H.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class JellyfinValidateTimeoutTests(unittest.TestCase):
    """Vague H #1 : validate_connection n'autorise pas d'appel reseau sans timeout."""

    def test_jellyfin_validate_has_timeout(self) -> None:
        from cinesort.infra.jellyfin_client import JellyfinClient

        client = JellyfinClient("http://jelly.local", "api-key-test", timeout_s=7.0)

        captured: dict = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b'{"ServerName":"Test","Version":"10.0"}'
            resp.json.return_value = {"ServerName": "Test", "Version": "10.0"}
            resp.raise_for_status.return_value = None
            return resp

        def fake_get_users(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b'[{"Id":"u1","Name":"admin","Policy":{"IsAdministrator":true}}]'
            resp.json.return_value = [
                {"Id": "u1", "Name": "admin", "Policy": {"IsAdministrator": True}}
            ]
            resp.raise_for_status.return_value = None
            return resp

        # Premier appel /System/Info/Public, second /Users
        with patch.object(client._session, "get", side_effect=[fake_get("u", **{}), fake_get_users("u", **{})]) as mock_get:
            res = client.validate_connection()

        self.assertTrue(res.get("ok"), f"validate_connection echoue: {res}")
        # Sur tous les appels reseau realises pendant validate_connection,
        # `timeout` doit etre passe en kwarg.
        self.assertGreaterEqual(mock_get.call_count, 1)
        for call in mock_get.call_args_list:
            kwargs = call.kwargs
            self.assertIn("timeout", kwargs, f"Appel reseau sans timeout : {call}")
            self.assertGreater(kwargs["timeout"], 0)
            self.assertLessEqual(kwargs["timeout"], 60.0)


class PlexCountHeaderTests(unittest.TestCase):
    """Vague H #2 : get_movies_count passe X-Plex-Container-Size en header."""

    def test_plex_count_uses_header(self) -> None:
        from cinesort.infra.plex_client import PlexClient

        client = PlexClient("http://plex.local:32400", "token-test", timeout_s=5.0)

        captured: dict = {}

        def fake_session_get(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b'{"MediaContainer":{"totalSize":42}}'
            resp.json.return_value = {"MediaContainer": {"totalSize": 42}}
            resp.raise_for_status.return_value = None
            return resp

        with patch.object(client._session, "get", side_effect=fake_session_get):
            count = client.get_movies_count("4")

        self.assertEqual(count, 42)
        # Le header X-Plex-Container-Size doit etre passe dans kwargs["headers"]
        # et ne PAS apparaitre dans kwargs["params"].
        kwargs = captured.get("kwargs", {})
        headers = kwargs.get("headers") or {}
        params = kwargs.get("params") or {}
        self.assertIn(
            "X-Plex-Container-Size",
            headers,
            f"X-Plex-Container-Size manquant dans headers, kwargs={kwargs}",
        )
        self.assertEqual(headers["X-Plex-Container-Size"], "0")
        self.assertNotIn(
            "X-Plex-Container-Size",
            params,
            f"X-Plex-Container-Size en params (bug Vague H), kwargs={kwargs}",
        )

    def test_plex_validate_guard_on_non_dict_response(self) -> None:
        """Guard ajoute Vague H : si /identity ne retourne pas un dict
        exploitable, on retourne {ok:False, error:...} au lieu de
        KeyError."""
        from cinesort.infra.plex_client import PlexClient

        client = PlexClient("http://plex.local:32400", "token-test", timeout_s=5.0)

        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'["not", "a", "dict"]'
        resp.json.return_value = ["not", "a", "dict"]
        resp.raise_for_status.return_value = None

        with patch.object(client._session, "get", return_value=resp):
            res = client.validate_connection()

        self.assertFalse(res.get("ok"))
        self.assertIn("error", res)


class OmdbCacheAtomicTests(unittest.TestCase):
    """Vague H #3 : _save_cache_atomic preserve le cache existant en cas de
    write partielle (fsync raise, tmp vide)."""

    def test_omdb_cache_atomic_safe(self) -> None:
        from cinesort.infra.omdb_client import OmdbClient

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "omdb_cache.json"
            # Cache original non-vide pre-existant sur disque
            original_payload = {"imdb|tt0111161": {"_ts": 1700000000.0, "data": {"Title": "Original"}}}
            cache_path.write_text(json.dumps(original_payload), encoding="utf-8")
            original_bytes = cache_path.read_bytes()

            client = OmdbClient(api_key="dummy", cache_path=cache_path)
            # Simuler une nouvelle entree en RAM
            client._cache["imdb|tt9999999"] = {"_ts": 1800000000.0, "data": {"Title": "New"}}

            # Patcher os.fsync pour qu'il leve, simulant une write partielle
            # (la donnee n'a pas atteint le disque -> tmp vide ou corrompu).
            with patch("cinesort.infra.omdb_client.os.fsync", side_effect=OSError("disk full")):
                client._save_cache_atomic()

            # Le cache sur disque DOIT etre intact (pattern atomic safe).
            self.assertTrue(cache_path.exists(), "cache disparu apres write echouee")
            self.assertEqual(
                cache_path.read_bytes(),
                original_bytes,
                "cache corrompu par une write partielle (bug Vague H)",
            )
            # Et le .tmp doit avoir ete nettoye (pas d'orphelin).
            tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            self.assertFalse(tmp_path.exists(), f"tmp orphelin laisse sur disque: {tmp_path}")

    def test_omdb_cache_normal_write_succeeds(self) -> None:
        """Sanity : en mode normal, l'ecriture doit reussir et persister la
        nouvelle entree."""
        from cinesort.infra.omdb_client import OmdbClient

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "omdb_cache.json"
            client = OmdbClient(api_key="dummy", cache_path=cache_path)
            client._cache["imdb|tt1"] = {"_ts": 1.0, "data": {"Title": "X"}}
            client._save_cache_atomic()

            self.assertTrue(cache_path.exists())
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertIn("imdb|tt1", saved)

    def test_omdb_cache_empty_tmp_discarded(self) -> None:
        """Si le tmp finit a taille 0 (cas pathologique), le cache original
        doit etre preserve."""
        from cinesort.infra.omdb_client import OmdbClient

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "omdb_cache.json"
            original = {"k": "v"}
            cache_path.write_text(json.dumps(original), encoding="utf-8")
            original_bytes = cache_path.read_bytes()

            client = OmdbClient(api_key="dummy", cache_path=cache_path)
            client._cache["new"] = {"_ts": 1.0, "data": {}}

            # Patch open pour simuler une ecriture qui ne produit rien (le
            # fichier reste a taille 0). Patcher open + stat pour forcer la
            # branche "tmp vide -> discard".
            real_open = open

            def fake_open(p, *args, **kwargs):
                # Cree juste le fichier vide sans rien ecrire
                if str(p).endswith(".tmp"):
                    # Touch le fichier
                    Path(p).write_bytes(b"")
                    # Retourne un objet qui simule un fichier ouvert mais
                    # ignore write/flush/fileno via MagicMock
                    m = MagicMock()
                    m.__enter__ = lambda self_: m
                    m.__exit__ = lambda *a: None
                    m.write = lambda data: None
                    m.flush = lambda: None
                    m.fileno = lambda: 0
                    return m
                return real_open(p, *args, **kwargs)

            with patch("cinesort.infra.omdb_client.open", side_effect=fake_open):
                with patch("cinesort.infra.omdb_client.os.fsync", return_value=None):
                    client._save_cache_atomic()

            # Cache original intact
            self.assertEqual(cache_path.read_bytes(), original_bytes)
            tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            self.assertFalse(tmp_path.exists(), "tmp vide laisse sur disque")


if __name__ == "__main__":
    unittest.main()
