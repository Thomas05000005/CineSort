"""#535 — play_count et last_played_date etaient captures, jamais restaures.

`snapshot_watched` capture trois champs (`played`, `play_count`,
`last_played_date`) ; `restore_watched` n'en re-emettait qu'un via
`mark_played`. Apres un apply qui deplace le dossier, Jellyfin ré-indexe un
item NEUF (ses items sont cles par chemin) : un film vu 17 fois le 15/01
revenait a « 1 lecture, il y a quelques secondes ». Perte de donnees
silencieuse — l'utilisateur ne voyait meme pas d'avertissement.

PIEGE EVITE — LE MOCK QUI FABRIQUE LA CONDITION TESTEE
------------------------------------------------------
Les clients de ce fichier sont de VRAIES classes, pas des `MagicMock`. Un
MagicMock cree l'attribut `update_played_state` a la volee et rend un objet
truthy : `_restore_counters` conclurait « historique restaure » sans qu'aucun
appel ne parte, et le test resterait vert meme avec le correctif retire. C'est
aussi le seul moyen de tester HONNETEMENT le cas du serveur ancien, ou la
methode est reellement absente.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from cinesort.app.jellyfin_sync import WatchedInfo, _normalize_path, restore_watched
from cinesort.infra.jellyfin_client import JellyfinClient, JellyfinError

_OLD_DIR = r"C:\Films\inception"
_NEW_DIR = r"C:\Films\Inception (2010)"
_VIDEO = "Inception.2010.1080p.BluRay.mkv"
_OLD_PATH = rf"{_OLD_DIR}\{_VIDEO}"
_NEW_PATH = rf"{_NEW_DIR}\{_VIDEO}"
# Format exact rendu par Jellyfin (UserData.LastPlayedDate).
_DATE = "2026-01-15T20:11:37.0000000Z"

_OPERATIONS = [
    {"op_type": "MKDIR", "src_path": "", "dst_path": _NEW_DIR, "undo_status": "PENDING"},
    {"op_type": "MOVE_DIR", "src_path": _OLD_DIR, "dst_path": _NEW_DIR, "undo_status": "PENDING"},
]


class _LegacyClient:
    """Client duck-type SANS `update_played_state` (serveur Jellyfin ancien)."""

    def __init__(self, movies: List[Dict[str, Any]]) -> None:
        self._movies = movies
        self.marked: List[Tuple[str, str]] = []
        self.list_calls = 0

    def get_all_movies_from_all_libraries(self, user_id: str) -> List[Dict[str, Any]]:
        self.list_calls += 1
        return [dict(m) for m in self._movies]

    def mark_played(self, user_id: str, item_id: str) -> bool:
        self.marked.append((user_id, item_id))
        return True


class _ModernClient(_LegacyClient):
    """Client duck-type AVEC l'endpoint UserData."""

    def __init__(self, movies: List[Dict[str, Any]], *, update_ok: bool = True) -> None:
        super().__init__(movies)
        self.updates: List[Tuple[str, str, int, str]] = []
        self._update_ok = update_ok

    def update_played_state(
        self,
        user_id: str,
        item_id: str,
        *,
        play_count: int,
        last_played_date: str,
    ) -> bool:
        self.updates.append((user_id, item_id, play_count, last_played_date))
        return self._update_ok


def _snapshot(play_count: int, last_played_date: str) -> Dict[str, WatchedInfo]:
    return {_normalize_path(_OLD_PATH): WatchedInfo(True, play_count, last_played_date)}


def _current(play_count: int = 0, last_played_date: str = "") -> List[Dict[str, Any]]:
    return [
        {
            "id": "jf-1",
            "path": _NEW_PATH,
            "played": False,
            "play_count": play_count,
            "last_played_date": last_played_date,
        }
    ]


def _restore(client: Any, snapshot: Dict[str, WatchedInfo], *, max_retries: int = 1) -> Any:
    return restore_watched(
        client,
        "uid",
        snapshot,
        _OPERATIONS,
        initial_delay_s=0,
        retry_delay_s=0,
        max_retries=max_retries,
    )


@patch("cinesort.app.jellyfin_sync.time.sleep")
class RestoreCountersTests(unittest.TestCase):
    def test_play_count_and_date_are_reemitted(self, _sleep: Any) -> None:
        """Le coeur de #535 : 17 lectures du 15/01 doivent revenir a l'identique."""
        client = _ModernClient(_current())
        result = _restore(client, _snapshot(17, _DATE))

        self.assertEqual(client.updates, [("uid", "jf-1", 17, _DATE)])
        # La date est re-emise TELLE QUELLE : aucune reecriture de format.
        self.assertEqual(client.updates[0][3], _DATE)
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.counters_restored, 1)
        self.assertEqual(result.counters_lost, 0)
        self.assertEqual(result.details[0]["counters"], "restored")

    def test_server_without_userdata_endpoint_is_not_a_silent_success(self, _sleep: Any) -> None:
        """Client sans la methode : l'historique EST perdu, il doit etre compte."""
        client = _LegacyClient(_current())
        result = _restore(client, _snapshot(17, _DATE))

        self.assertEqual(result.restored, 1, "le statut vu reste restaure")
        self.assertEqual(result.counters_restored, 0)
        self.assertEqual(result.counters_lost, 1)
        self.assertEqual(result.details[0]["counters"], "lost")

    def test_update_returning_false_is_not_a_silent_success(self, _sleep: Any) -> None:
        """L'endpoint repond en echec (404 sur serveur ancien, 500...)."""
        client = _ModernClient(_current(), update_ok=False)
        result = _restore(client, _snapshot(17, _DATE))

        self.assertEqual(len(client.updates), 1)
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.counters_restored, 0)
        self.assertEqual(result.counters_lost, 1)
        self.assertEqual(result.details[0]["counters"], "lost")

    def test_lost_play_count_alone_triggers_the_restore(self, _sleep: Any) -> None:
        """MOTIF 1 de la garde, ISOLE : seul le compteur a recule (date identique).

        Sans ce cas, mettre le motif « compteur » hors circuit resterait VERT
        (le motif « date » couvrirait le test principal) — mutant survivant.
        """
        client = _ModernClient(_current(play_count=0, last_played_date=_DATE))
        result = _restore(client, _snapshot(17, _DATE))

        self.assertEqual(client.updates, [("uid", "jf-1", 17, _DATE)])
        self.assertEqual(result.counters_restored, 1)

    def test_lost_date_alone_triggers_the_restore(self, _sleep: Any) -> None:
        """MOTIF 2 de la garde, ISOLE : seule la date a disparu (compteur egal).

        Cas reel : un film marque vu a la main, sans lecture comptabilisee, mais
        dont Jellyfin portait une date de derniere lecture.
        """
        client = _ModernClient(_current(play_count=0, last_played_date=""))
        result = _restore(client, _snapshot(0, _DATE))

        self.assertEqual(client.updates, [("uid", "jf-1", 0, _DATE)])
        self.assertEqual(result.counters_restored, 1)

    def test_nothing_to_restore_emits_no_extra_call(self, _sleep: Any) -> None:
        """Un film vu sans lecture ni date est decrit par mark_played seul."""
        client = _ModernClient(_current())
        result = _restore(client, _snapshot(0, ""))

        self.assertEqual(client.updates, [])
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.counters_restored, 0)
        self.assertEqual(result.counters_lost, 0)
        self.assertEqual(result.details[0]["counters"], "not_needed")

    def test_history_preserved_by_jellyfin_is_not_rewritten(self, _sleep: Any) -> None:
        """L'item a garde son historique : ne PAS reecrire son UserData.

        Cas reel du renommage de casse seule : Jellyfin conserve l'item. Le
        re-ecrire n'apporterait rien et exposerait le reste de son UserData
        (favori, note) a un ecrasement par un corps partiel.
        """
        client = _ModernClient(_current(play_count=17, last_played_date=_DATE))
        result = _restore(client, _snapshot(17, _DATE))

        self.assertEqual(client.updates, [])
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.counters_lost, 0)
        self.assertEqual(result.details[0]["counters"], "not_needed")

    def test_counter_failure_does_not_keep_the_path_pending(self, _sleep: Any) -> None:
        """Un historique perdu ne relance pas 5 tentatives (135 s) pour rien.

        Le statut vu — l'essentiel — est restaure des la 1re tentative : le
        chemin sort de `pending`, et il n'est compte ni en `errors` ni en
        `not_found`.
        """
        client = _ModernClient(_current(), update_ok=False)
        result = _restore(client, _snapshot(17, _DATE), max_retries=5)

        self.assertEqual(client.list_calls, 1)
        self.assertEqual(len(client.marked), 1)
        self.assertEqual(result.errors, 0)
        self.assertEqual(result.not_found, 0)
        self.assertEqual(result.counters_lost, 1)

    def test_to_dict_exposes_the_counter_tally(self, _sleep: Any) -> None:
        client = _ModernClient(_current())
        payload = _restore(client, _snapshot(17, _DATE)).to_dict()

        self.assertEqual(payload["counters_restored"], 1)
        self.assertEqual(payload["counters_lost"], 0)


class UpdatePlayedStateClientTests(unittest.TestCase):
    """Contrat HTTP de `JellyfinClient.update_played_state`."""

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_posts_userdata_with_count_and_date(self, mock_post: Any) -> None:
        mock_post.return_value = MagicMock(status_code=204)
        client = JellyfinClient("http://host", "key")

        self.assertTrue(client.update_played_state("uid", "item-1", play_count=17, last_played_date=_DATE))
        path, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertEqual(path, "/Users/uid/Items/item-1/UserData")
        self.assertEqual(kwargs["json"], {"Played": True, "PlayCount": 17, "LastPlayedDate": _DATE})

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_empty_date_is_not_emitted(self, mock_post: Any) -> None:
        """Une date vide n'est pas une date : la clef ne part pas."""
        mock_post.return_value = MagicMock(status_code=204)
        client = JellyfinClient("http://host", "key")

        client.update_played_state("uid", "item-1", play_count=3, last_played_date="")
        self.assertEqual(mock_post.call_args[1]["json"], {"Played": True, "PlayCount": 3})

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_http_failure_returns_false(self, mock_post: Any) -> None:
        mock_post.side_effect = JellyfinError("Erreur HTTP 404 sur /UserData")
        client = JellyfinClient("http://host", "key")

        self.assertFalse(client.update_played_state("uid", "item-1", play_count=17, last_played_date=_DATE))


class _RaisingClient(_LegacyClient):
    """Client dont l'endpoint UserData leve au lieu de rendre False."""

    def update_played_state(self, user_id: str, item_id: str, **_kwargs: Any) -> bool:
        raise JellyfinError("Erreur HTTP 500 sur /UserData")


@patch("cinesort.app.jellyfin_sync.time.sleep")
class RestoreCountersErrorIsolationTests(unittest.TestCase):
    def test_jellyfin_error_does_not_abort_the_whole_restore(self, _sleep: Any) -> None:
        """Une exception du rattrapage ne doit pas emporter la restauration."""
        client = _RaisingClient(_current())
        result = _restore(client, _snapshot(17, _DATE))

        self.assertEqual(result.restored, 1)
        self.assertEqual(result.counters_lost, 1)


class RestoreReportingTests(unittest.TestCase):
    """La perte d'historique doit REMONTER : sinon elle reste silencieuse."""

    def test_lost_history_is_reported_to_the_user(self) -> None:
        from cinesort.app.jellyfin_sync import RestoreResult
        from cinesort.ui.api import apply_support

        logs: List[Tuple[str, str]] = []
        result = RestoreResult(restored=3, counters_restored=1, counters_lost=2)
        store = MagicMock()
        store.apply.list_apply_operations.return_value = []

        with (
            patch.object(apply_support, "_make_jellyfin_client", return_value=object()),
            patch.object(apply_support, "restore_watched", return_value=result),
        ):
            apply_support._restore_jellyfin_watched(
                MagicMock(),
                lambda level, msg: logs.append((level, msg)),
                {
                    "snapshot": {_normalize_path(_OLD_PATH): WatchedInfo(True, 17, _DATE)},
                    "user_id": "uid",
                    "settings": {"jellyfin_url": "http://host"},
                },
                store,
                "batch-1",
            )

        warns = [msg for level, msg in logs if level == "WARN"]
        self.assertTrue(
            any("2" in msg and "historique" in msg.lower() for msg in warns),
            f"la perte d'historique doit etre signalee, logs={logs}",
        )


class SnapshotFidelityTests(unittest.TestCase):
    """Le snapshot doit porter la date SANS la reformater (rien a restaurer sinon)."""

    def test_last_played_date_is_captured_verbatim(self) -> None:
        from cinesort.app.jellyfin_sync import snapshot_watched

        client: Optional[Any] = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"path": _OLD_PATH, "played": True, "play_count": 17, "last_played_date": _DATE},
        ]
        snap = snapshot_watched(client, "uid")

        info = snap[_normalize_path(_OLD_PATH)]
        self.assertEqual(info.play_count, 17)
        self.assertEqual(info.last_played_date, _DATE)


if __name__ == "__main__":
    unittest.main()
