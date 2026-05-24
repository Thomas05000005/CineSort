"""Tests Phase 5 : Historique completed (spec 09-historique.md).

Couvre les 12 deliverables : onglets detailles, page standalone /run/:id,
undo-apply cable, delete-run cable, scroll infini batch 30, filtres avances
(Undone/Undo/Custom/recherche film), banner retention, CSS.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HISTORIQUE_JS = _ROOT / "web" / "dashboard" / "views" / "historique.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FilmsTabDetailTests(unittest.TestCase):
    """Onglet Films : liste detaillee + lien /film/:id (spec 09 §3)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_calls_get_history_stats(self) -> None:
        self.assertIn("run/get_history_stats", self.js)

    def test_films_list_render(self) -> None:
        self.assertIn("_renderFilmsList", self.js)

    def test_films_status_labels(self) -> None:
        # 4 statuts : Approuve / Rejete / Doublon / Suppression.
        self.assertIn("Approuvé", self.js)
        self.assertIn("Rejeté", self.js)
        self.assertIn("Doublon", self.js)
        self.assertIn("Suppression", self.js)

    def test_films_link_to_film_detail(self) -> None:
        self.assertIn("#/film/", self.js)


class ApplyTabDetailTests(unittest.TestCase):
    """Onglet Apply : liste operations + compteurs par type."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_apply_ops_render(self) -> None:
        self.assertIn("_renderApplyOps", self.js)

    def test_apply_op_labels(self) -> None:
        # 4 types d'op : rename / move / quarantine / delete_mark.
        for term in ("Renommé", "Déplacé", "Quarantaine", "Marqué suppression"):
            self.assertIn(term, self.js, f"manque label op : {term}")

    def test_apply_counters(self) -> None:
        self.assertIn("historique-apply-counter", self.js)


class DoublonsTabDetailTests(unittest.TestCase):
    """Onglet Doublons : groupes decides + skipped."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_doublons_list_render(self) -> None:
        self.assertIn("_renderDoublonsList", self.js)

    def test_doublons_decided_skipped(self) -> None:
        self.assertIn("Décidés", self.js)
        self.assertIn("Ignorés", self.js)


class LogTabDetailTests(unittest.TestCase):
    """Onglet Log : viewer monospace + bouton recharger."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_log_viewer_render(self) -> None:
        self.assertIn("_renderLogViewer", self.js)
        self.assertIn("historique-log-viewer", self.js)

    def test_log_reload_action(self) -> None:
        self.assertIn('data-historique-action="reload-log"', self.js)


class StandalonePageTests(unittest.TestCase):
    """Page standalone /run/:id (Phase 5)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")
        cls.app = _APP_JS.read_text(encoding="utf-8")

    def test_exports_init_run_detail_page(self) -> None:
        self.assertIn("export async function initRunDetailPage(", self.js)

    def test_exports_unmount_run_detail_page(self) -> None:
        self.assertIn("export function unmountRunDetailPage(", self.js)

    def test_route_run_id_registered(self) -> None:
        self.assertIn('registerRoute("/run/:id"', self.app)
        line_start = self.app.find('registerRoute("/run/:id"')
        line_end = self.app.find("\n", line_start)
        snippet = self.app[line_start:line_end]
        self.assertIn("initRunDetailPage", snippet)

    def test_back_button_to_historique(self) -> None:
        self.assertIn("data-historique-back", self.js)
        self.assertIn('"/historique"', self.js)


class UndoApplyWiredTests(unittest.TestCase):
    """Action undo-apply : appel reel a undo_last_apply."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_undo_calls_backend(self) -> None:
        # PR #84 : undo_last_apply migre vers la facade run (run/undo_last_apply).
        self.assertIn('apiPost("run/undo_last_apply"', self.js)

    def test_undo_uses_danger_modal(self) -> None:
        # Verifie que undo-apply est dans un onConfirm callback de dangerConfirmModal.
        self.assertIn("dangerConfirmModal", self.js)
        self.assertIn("_doUndoApply", self.js)

    def test_undo_success_toast(self) -> None:
        self.assertIn("Apply annulé", self.js)


class DeleteRunWiredTests(unittest.TestCase):
    """Action delete-run : appel reel a run/delete_run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_delete_calls_backend(self) -> None:
        self.assertIn('apiPost("run/delete_run"', self.js)

    def test_delete_uses_danger_modal(self) -> None:
        self.assertIn("_doDeleteRun", self.js)

    def test_delete_removes_from_local_runs(self) -> None:
        # splice du tableau local sans refetch (perf : pas de fetch reseau).
        self.assertIn("_runs = _runs.filter", self.js)


class InfiniteScrollTests(unittest.TestCase):
    """Scroll infini batch 30 + IntersectionObserver."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_batch_size_constant(self) -> None:
        self.assertIn("BATCH_SIZE = 30", self.js)

    def test_intersection_observer_used(self) -> None:
        self.assertIn("IntersectionObserver", self.js)

    def test_visible_count_increments(self) -> None:
        self.assertIn("_visibleCount += BATCH_SIZE", self.js)

    def test_loading_more_indicator(self) -> None:
        self.assertIn("historique-loading-more", self.js)


class AdvancedFiltersTests(unittest.TestCase):
    """Filtres supplementaires : Undone, Undo, Custom date, recherche par film."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_status_undone_option(self) -> None:
        self.assertIn('value="undone"', self.js)

    def test_type_undo_option(self) -> None:
        self.assertIn('value="undo"', self.js)

    def test_custom_period_picker(self) -> None:
        self.assertIn('value="custom"', self.js)
        self.assertIn("data-historique-custom-from", self.js)
        self.assertIn("data-historique-custom-to", self.js)

    def test_search_matches_film_name(self) -> None:
        # _matchesSearchQuery doit explorer _filmsCacheByRun (recherche par titre).
        self.assertIn("_filmsCacheByRun", self.js)
        self.assertIn("nom de film", self.js)


class RetentionBannerTests(unittest.TestCase):
    """Banner retention 90j auto en haut de la vue (spec §5)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_renders_retention_banner(self) -> None:
        self.assertIn("_renderRetentionBanner", self.js)

    def test_banner_mentions_90_days(self) -> None:
        # rétention par defaut 90j (settable via history_retention_days).
        self.assertIn("rétention", self.js)
        self.assertIn("history_retention_days", self.js)


class CssCompleteTests(unittest.TestCase):
    """CSS Phase 5 : nouvelles classes obligatoires + balance accolades."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_standalone_page_class(self) -> None:
        self.assertIn(".historique-run-detail-page", self.css)

    def test_films_list_class(self) -> None:
        self.assertIn(".historique-films-list", self.css)

    def test_apply_ops_class(self) -> None:
        self.assertIn(".historique-apply-ops", self.css)

    def test_doublons_list_class(self) -> None:
        self.assertIn(".historique-doublons-list", self.css)

    def test_log_viewer_class(self) -> None:
        self.assertIn(".historique-log-viewer", self.css)

    def test_retention_banner_class(self) -> None:
        self.assertIn(".historique-retention-banner", self.css)

    def test_brace_balance(self) -> None:
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"CSS desequilibre : open={opens} close={closes}")


if __name__ == "__main__":
    unittest.main()
