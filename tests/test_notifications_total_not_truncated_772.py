"""#772 — `total` etait le nombre RAPATRIE, pas le nombre existant.

`get_notifications` renvoyait `"total": len(items)` alors que
`NotificationStore.list` tronque des `len(out) >= limit`. Au-dela de la limite,
un front qui affiche `total` comme « nombre total » affiche donc la limite.

Le correctif ne SUPPRIME PAS la limite — elle borne la memoire du payload — il
rend le comptage independant d'elle (`NotificationStore.count`), et nomme
explicitement `returned` ce qui est effectivement retourne.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.notifications_support import NotificationStore, get_notifications


class _Api:
    """Porteur minimal du store (pas un MagicMock : `_get_or_create_store`
    ferait un `isinstance` sur un mock et creerait un store parallele)."""


def _api_with(count: int, *, category: str = "event") -> _Api:
    api = _Api()
    store = NotificationStore()
    for i in range(count):
        store.add("scan_done", f"notif {i}", category=category)
    api._notification_store = store
    return api


class TotalIsNotTruncatedTests(unittest.TestCase):
    def test_total_counts_beyond_the_limit(self) -> None:
        api = _api_with(150)

        res = get_notifications(api, limit=10)

        self.assertEqual(len(res["notifications"]), 10, "la limite protege toujours le payload")
        self.assertEqual(res["returned"], 10)
        self.assertEqual(res["total"], 150)

    def test_total_respects_the_category_filter(self) -> None:
        api = _api_with(5, category="event")
        store = api._notification_store
        for i in range(3):
            store.add("insight", f"insight {i}", category="insight")

        res = get_notifications(api, limit=2, category="insight")

        self.assertEqual(res["returned"], 2)
        self.assertEqual(res["total"], 3, "le total doit filtrer comme la liste, sans tronquer")

    def test_total_respects_unread_only(self) -> None:
        api = _api_with(20)
        api._notification_store.mark_all_read()
        for i in range(7):
            api._notification_store.add("scan_done", f"neuve {i}")

        res = get_notifications(api, unread_only=True, limit=3)

        self.assertEqual(res["returned"], 3)
        self.assertEqual(res["total"], 7)

    def test_dismissed_are_excluded_from_the_total(self) -> None:
        api = _api_with(4)
        store = api._notification_store
        victim = store.list(limit=0)[0]["id"]
        store.dismiss(victim)

        res = get_notifications(api, limit=100)

        self.assertEqual(res["total"], 3)
        self.assertEqual(res["returned"], 3)


class CountAndListShareTheSameFilterTests(unittest.TestCase):
    """`count` doit compter EXACTEMENT ce que `list` retiendrait sans limite."""

    def _mixed_store(self) -> NotificationStore:
        store = NotificationStore()
        for i in range(12):
            store.add("scan_done", f"e{i}", category="event")
        for i in range(5):
            store.add("insight", f"i{i}", category="insight")
        store.mark_read(store.list(limit=0)[0]["id"])
        store.dismiss(store.list(limit=0)[1]["id"])
        return store

    def test_count_equals_unlimited_list_for_every_filter(self) -> None:
        store = self._mixed_store()
        for unread_only in (False, True):
            for category in (None, "event", "insight", "system"):
                with self.subTest(unread_only=unread_only, category=category):
                    self.assertEqual(
                        store.count(unread_only=unread_only, category=category),
                        len(store.list(unread_only=unread_only, limit=0, category=category)),
                    )

    def test_count_is_unaffected_by_the_list_limit(self) -> None:
        store = self._mixed_store()
        self.assertEqual(len(store.list(limit=2)), 2)
        self.assertEqual(store.count(), 16)


if __name__ == "__main__":
    unittest.main()
