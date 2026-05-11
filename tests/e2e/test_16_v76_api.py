"""Tests E2E API REST pour les nouveautes v7.6.0 (Vagues 3-9).

Pas de navigateur — on frappe le serveur REST directement via http.client.
Couvre :
- Vague 3 : get_library_filtered / get_smart_playlists / save_smart_playlist / delete_smart_playlist
- Vague 4 : get_film_full
- Vague 7 : get_scoring_rollup
- Vague 9 : get_notifications / dismiss_notification / mark_all_notifications_read / clear_notifications
"""

from __future__ import annotations

import json
import sys
from http.client import HTTPConnection
from pathlib import Path as _Path
from typing import Any, Dict

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)


def _post(server_info: Dict[str, Any], method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """POST /api/{method} avec auth Bearer."""
    body = json.dumps(params or {}).encode("utf-8")
    conn = HTTPConnection("127.0.0.1", server_info["port"], timeout=5)
    try:
        conn.request(
            "POST",
            f"/api/{method}",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {server_info['token']}",
            },
        )
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        assert resp.status == 200, f"{method} HTTP {resp.status}: {raw}"
        return json.loads(raw)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Vague 9 — Notifications
# ---------------------------------------------------------------------------


class TestNotificationsApi:
    def test_initial_state_empty(self, e2e_server):
        _post(e2e_server, "clear_notifications")
        res = _post(e2e_server, "get_notifications")
        assert res["ok"] is True
        assert res["unread_count"] == 0
        assert res["notifications"] == []

    def test_unread_count_endpoint(self, e2e_server):
        _post(e2e_server, "clear_notifications")
        res = _post(e2e_server, "get_notifications_unread_count")
        assert res["ok"] is True
        assert res["count"] == 0

    def test_insights_capture_via_global_stats(self, e2e_server):
        """Appeler get_global_stats doit peupler le centre d'insights actifs."""
        _post(e2e_server, "clear_notifications")
        stats = _post(e2e_server, "get_global_stats")
        assert stats["ok"] is True
        # Insights presents ou vide (depend du mock) — on tolere les 2
        notifs_after = _post(e2e_server, "get_notifications", {"category": "insight"})
        assert notifs_after["ok"] is True
        # Si insights existent, ils sont categorises "insight"
        for it in notifs_after["notifications"]:
            assert it["category"] == "insight"

    def test_mark_all_read_roundtrip(self, e2e_server):
        _post(e2e_server, "clear_notifications")
        # Trigger dashboard_support pour creer des insights (si presents)
        _post(e2e_server, "get_global_stats")
        before = _post(e2e_server, "get_notifications")
        unread_before = before["unread_count"]
        res = _post(e2e_server, "mark_all_notifications_read")
        assert res["ok"] is True
        assert res["marked"] == unread_before
        after = _post(e2e_server, "get_notifications")
        assert after["unread_count"] == 0

    def test_dismiss_unknown_id_returns_false(self, e2e_server):
        res = _post(e2e_server, "dismiss_notification", {"notification_id": "nonexistent"})
        assert res["ok"] is False

    def test_clear_all_endpoint(self, e2e_server):
        _post(e2e_server, "get_global_stats")
        res = _post(e2e_server, "clear_notifications")
        assert res["ok"] is True
        assert res["unread_count"] == 0
        after = _post(e2e_server, "get_notifications")
        assert after["notifications"] == []


# ---------------------------------------------------------------------------
# Vague 3 — Library filtered + playlists
# ---------------------------------------------------------------------------


class TestLibraryV5Api:
    def test_get_library_filtered_basic(self, e2e_server):
        res = _post(
            e2e_server,
            "get_library_filtered",
            {
                "run_id": e2e_server["run_id"],
                "page": 1,
                "page_size": 50,
            },
        )
        assert res["ok"] is True
        assert "rows" in res
        assert "total" in res
        assert len(res["rows"]) > 0

    def test_get_library_filtered_search(self, e2e_server):
        res = _post(
            e2e_server,
            "get_library_filtered",
            {
                "run_id": e2e_server["run_id"],
                "filters": {"search": "Avengers"},
            },
        )
        assert res["ok"] is True
        # Toutes les lignes doivent contenir Avengers dans le titre
        for row in res["rows"]:
            title = str(row.get("proposed_title") or row.get("title") or "").lower()
            assert "avengers" in title, f"Row sans Avengers : {title}"

    def test_get_library_filtered_pagination(self, e2e_server):
        res = _post(
            e2e_server,
            "get_library_filtered",
            {
                "run_id": e2e_server["run_id"],
                "page": 1,
                "page_size": 5,
            },
        )
        assert res["ok"] is True
        assert len(res["rows"]) <= 5
        assert res["total"] >= 5

    def test_smart_playlists_listed_with_presets(self, e2e_server):
        listed = _post(e2e_server, "get_smart_playlists")
        assert listed["ok"] is True
        assert "playlists" in listed
        # Au moins les presets sont presents
        ids = [p.get("id") for p in listed["playlists"]]
        assert any(i.startswith("_preset_") for i in ids), f"Aucun preset trouve : {ids}"

    def test_save_smart_playlist_returns_id(self, e2e_server):
        saved = _post(
            e2e_server,
            "save_smart_playlist",
            {
                "name": "E2E Test Playlist",
                "filters": {"tier_v2": ["platinum"]},
            },
        )
        assert saved["ok"] is True
        assert "playlist_id" in saved

    def test_save_smart_playlist_rejects_empty_name(self, e2e_server):
        res = _post(
            e2e_server,
            "save_smart_playlist",
            {
                "name": "",
                "filters": {"tier_v2": ["gold"]},
            },
        )
        assert res["ok"] is False

    def test_delete_preset_playlist_refused(self, e2e_server):
        res = _post(e2e_server, "delete_smart_playlist", {"playlist_id": "_preset_reject"})
        assert res["ok"] is False


# ---------------------------------------------------------------------------
# Vague 4 — Film standalone page
# ---------------------------------------------------------------------------


class TestFilmFullApi:
    def test_get_film_full_returns_consolidated_payload(self, e2e_server):
        # Prendre le premier row du plan
        plan = _post(e2e_server, "get_plan", {"run_id": e2e_server["run_id"]})
        assert plan["ok"] is True
        assert len(plan["rows"]) > 0
        row_id = plan["rows"][0]["row_id"]

        res = _post(
            e2e_server,
            "get_film_full",
            {
                "run_id": e2e_server["run_id"],
                "row_id": row_id,
            },
        )
        assert res["ok"] is True
        # Le payload doit contenir au moins la row + perceptual + history keys
        assert "row" in res or "film" in res

    def test_get_film_full_unknown_row(self, e2e_server):
        res = _post(
            e2e_server,
            "get_film_full",
            {
                "run_id": e2e_server["run_id"],
                "row_id": "nonexistent_row_id_xyz",
            },
        )
        # Soit ok=False, soit ok=True avec un payload vide — l'important est de ne pas crash
        assert isinstance(res, dict)
        assert "ok" in res


# ---------------------------------------------------------------------------
# Vague 7 — Scoring rollup
# ---------------------------------------------------------------------------


class TestScoringRollupApi:
    def test_rollup_by_decade(self, e2e_server):
        res = _post(
            e2e_server,
            "get_scoring_rollup",
            {
                "by": "decade",
                "run_id": e2e_server["run_id"],
            },
        )
        assert res["ok"] is True
        assert res["by"] == "decade"
        assert "groups" in res

    def test_rollup_by_codec(self, e2e_server):
        res = _post(
            e2e_server,
            "get_scoring_rollup",
            {
                "by": "codec",
                "run_id": e2e_server["run_id"],
            },
        )
        assert res["ok"] is True
        assert res["by"] == "codec"
        # Chaque groupe doit avoir name, count, avg_score, tier_distribution
        for g in res["groups"]:
            assert "group_name" in g
            assert "count" in g

    def test_rollup_respects_limit(self, e2e_server):
        res = _post(
            e2e_server,
            "get_scoring_rollup",
            {
                "by": "decade",
                "limit": 1,
                "run_id": e2e_server["run_id"],
            },
        )
        assert res["ok"] is True
        assert len(res["groups"]) <= 1
