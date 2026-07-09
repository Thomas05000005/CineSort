"""Tests Phase 5 : Bibliotheque complete (spec 07-bibliotheque.md a 100%).

Couvre :
- 5 chips non-tier (subs_missing_fr, unidentified, recently_modified,
  in_duplicates, sagas_incomplete) avec compteurs.
- Drawer Avance exporte (library-advanced-drawer.js, 10 filtres).
- Scroll infini (IntersectionObserver + sentinel).
- Bulk actions cablees sur les bons endpoints (mark_for_deletion_bulk,
  rescan_rows_bulk, export_films, analyze_perceptual_batch).
- Backend : filtres avances + chips + tris size/added dans library_support.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BIBLIOTHEQUE_JS = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_DRAWER_JS = _ROOT / "web" / "dashboard" / "components" / "library-advanced-drawer.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"
_LIBRARY_SUPPORT = _ROOT / "cinesort" / "ui" / "api" / "library_support.py"


# ---------------------------------------------------------------------------
# 1. 5 chips non-tier
# ---------------------------------------------------------------------------


class NonTierChipsTests(unittest.TestCase):
    """Spec 07 §2 Groupes 2 et 3 : 5 chips non-tier combinables."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_5_chips_keys_present(self) -> None:
        for key in (
            "subs_missing_fr",
            "unidentified",
            "recently_modified",
            "in_duplicates",
            "sagas_incomplete",
        ):
            self.assertIn(key, self.js, f"chip key '{key}' manquante")

    def test_5_chips_labels_present(self) -> None:
        for label in (
            "Sans subs FR",
            "Non identifi",  # "Non identifies" en encodage UTF-8 sans accent strict
            "Modifi",  # "Modifies recemment"
            "Dans doublons",
            "Sagas",
        ):
            self.assertIn(label, self.js, f"label '{label}' manquant")

    def test_chip_data_attribute(self) -> None:
        self.assertIn("data-bibliotheque-chip", self.js)

    def test_counters_endpoint_called(self) -> None:
        self.assertIn("library/get_library_counters_by_chip", self.js)

    def test_counters_used_for_chip_count(self) -> None:
        self.assertIn("function _chipCount(key)", self.js)


# ---------------------------------------------------------------------------
# 2. Drawer Avance
# ---------------------------------------------------------------------------


class AdvancedDrawerTests(unittest.TestCase):
    """Spec 07 §2 "+ Avance" : drawer 10 filtres detailles."""

    def test_drawer_file_exists(self) -> None:
        self.assertTrue(_DRAWER_JS.is_file(), "library-advanced-drawer.js doit exister")

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DRAWER_JS.read_text(encoding="utf-8") if _DRAWER_JS.is_file() else ""
        cls.view = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_drawer_exports(self) -> None:
        self.assertIn("export function openLibraryAdvancedDrawer", self.js)
        self.assertIn("export function closeLibraryAdvancedDrawer", self.js)
        self.assertIn("export const ADVANCED_DRAWER_DEFAULTS", self.js)

    def test_drawer_10_filters_present(self) -> None:
        # Year, duration, size, resolution, codec, source, audio_lang, sub_lang,
        # confidence, added date
        for name in (
            "year_min",
            "year_max",
            "duration_min",
            "duration_max",
            "size_min_gb",
            "size_max_gb",
            "resolution",
            "codec",
            "source",
            "audio_languages",
            "subtitle_languages",
            "confidence_min",
            "added_after",
            "added_before",
        ):
            self.assertIn(name, self.js, f"filter '{name}' manquant dans drawer")

    def test_drawer_apply_and_reset_buttons(self) -> None:
        self.assertIn('data-drawer-action="apply"', self.js)
        self.assertIn('data-drawer-action="reset"', self.js)

    def test_drawer_imported_in_view(self) -> None:
        self.assertIn("openLibraryAdvancedDrawer", self.view)
        self.assertIn("library-advanced-drawer.js", self.view)


# ---------------------------------------------------------------------------
# 3. Tri complet (12 options : 6 criteres x 2 directions)
# ---------------------------------------------------------------------------


class SortOptionsTests(unittest.TestCase):
    """Spec 07 §3 : 6 criteres x 2 directions = 12 options."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_new_sort_size(self) -> None:
        self.assertIn('"size_desc"', self.js)
        self.assertIn('"size_asc"', self.js)

    def test_new_sort_added(self) -> None:
        self.assertIn('"added_desc"', self.js)
        self.assertIn('"added_asc"', self.js)

    def test_label_taille_fichier(self) -> None:
        self.assertIn("Taille fichier", self.js)

    def test_label_date_ajout(self) -> None:
        self.assertIn("Date d'ajout", self.js)


# ---------------------------------------------------------------------------
# 4. Vue tableau dense complete
# ---------------------------------------------------------------------------


class DenseTableTests(unittest.TestCase):
    """Spec 07 §4 : colonnes Confiance / Taille / Source + headers triables."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_columns_present(self) -> None:
        self.assertIn("Confiance", self.js)
        self.assertIn("Taille", self.js)
        self.assertIn("Source", self.js)

    def test_headers_sortable(self) -> None:
        self.assertIn("data-bibliotheque-thsort", self.js)
        self.assertIn("TABLE_HEADER_SORTS", self.js)

    def test_aria_sort_attribute(self) -> None:
        self.assertIn("aria-sort=", self.js)

    def test_sortable_table_class(self) -> None:
        self.assertIn("bibliotheque-table-sortable", self.js)


# ---------------------------------------------------------------------------
# 5. Scroll infini
# ---------------------------------------------------------------------------


class InfiniteScrollTests(unittest.TestCase):
    """Spec 07 §8 : scroll infini via IntersectionObserver, batch 200."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_intersection_observer(self) -> None:
        self.assertIn("IntersectionObserver", self.js)
        self.assertIn("_setupScrollObserver", self.js)

    def test_sentinel(self) -> None:
        self.assertIn("data-bibliotheque-sentinel", self.js)

    def test_batch_size_200(self) -> None:
        self.assertIn("PAGE_SIZE = 200", self.js)

    def test_local_cache_rowsByPage(self) -> None:
        self.assertIn("rowsByPage", self.js)
        self.assertIn("new Map()", self.js)

    def test_loading_indicator(self) -> None:
        self.assertIn("Chargement", self.js)
        self.assertIn("loadingMore", self.js)

    def test_lazy_loading_posters(self) -> None:
        self.assertIn('loading="lazy"', self.js)


# ---------------------------------------------------------------------------
# 6. Inspecteur droit
# ---------------------------------------------------------------------------


class RightInspectorTests(unittest.TestCase):
    """Spec 07 §6 : inspecteur droit reutilise spec 06 mode A."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_right_panel_imported(self) -> None:
        self.assertIn("right-panel.js", self.js)
        self.assertIn("rightPanel", self.js)

    def test_update_inspector_function(self) -> None:
        self.assertIn("_updateInspector", self.js)

    def test_multi_select_aggregates(self) -> None:
        # Quand selection > 1 : recap films selectionnes + agregats
        self.assertIn("films sélectionnés", self.js)
        self.assertIn("Distribution Tier", self.js)


# ---------------------------------------------------------------------------
# 7. Double-clic mode C
# ---------------------------------------------------------------------------


class DoubleClickModeCTests(unittest.TestCase):
    """Spec 07 §9 : double-clic poster -> Modal Detail Film mode C."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_dblclick_handler(self) -> None:
        self.assertIn('addEventListener("dblclick"', self.js)

    def test_open_film_detail_modal(self) -> None:
        # Spec 07 Fix 100% : le double-clic appelle directement renderFilmDetail
        # mode C (overlay) au lieu de passer par _openFilmDetailModal qui faisait
        # un navigateTo /film/:id (function non importee, ReferenceError au runtime).
        self.assertRegex(
            self.js,
            r"renderFilmDetail\(\s*\{\s*mode\s*:\s*[\"\']C[\"\']",
        )


# ---------------------------------------------------------------------------
# 8. Bulk actions cablees aux bons endpoints
# ---------------------------------------------------------------------------


class BulkActionsWiringTests(unittest.TestCase):
    """Spec 07 §5 : 4 actions bulk cablees aux 4 endpoints PR #299/#306."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_endpoint_mark_for_deletion_bulk(self) -> None:
        self.assertIn("library/mark_for_deletion_bulk", self.js)

    def test_endpoint_rescan_rows_bulk(self) -> None:
        self.assertIn("run/rescan_rows_bulk", self.js)

    def test_endpoint_export_films(self) -> None:
        self.assertIn("library/export_films", self.js)

    def test_endpoint_perceptual_batch(self) -> None:
        # AUDIT 2026-06-13 (R5-D) : l'action 'Analyser perceptuel' utilise
        # desormais la variante ASYNC quality/queue_perceptual_batch (job_id +
        # progression done/total via get_perceptual_job_status), au lieu de
        # l'ancien appel BLOQUANT analyze_perceptual_batch.
        self.assertIn(
            "quality/queue_perceptual_batch", self.js,
            "L'action 'Analyser perceptuel' doit appeler quality/queue_perceptual_batch (async).",
        )
        self.assertIn(
            "quality/get_perceptual_job_status", self.js,
            "Le bulk perceptuel doit poller le statut du job (progression).",
        )

    def test_danger_confirm_modal_for_deletion(self) -> None:
        # dangerConfirmModal (PR #297), pas window.confirm
        self.assertIn("dangerConfirmModal", self.js)
        self.assertNotIn("window.confirm(", self.js)

    def test_countdown_3s_if_over_50(self) -> None:
        # Phase 5 spec 07 : N > 50 -> countdown anti-clic-reflexe 3s
        self.assertIn("countdownSeconds: n > 50 ? 3 : 0", self.js)


# ---------------------------------------------------------------------------
# 9. CSS
# ---------------------------------------------------------------------------


class CssAdditionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_balance_braces(self) -> None:
        # Spec : verifier balance accolades (regression Phase 4 #296)
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"Accolades CSS desequilibrees : {opens} {{ vs {closes} }}")

    def test_drawer_advanced_class(self) -> None:
        self.assertIn(".bibliotheque-drawer-advanced", self.css)
        self.assertIn(".bibliotheque-drawer-backdrop", self.css)

    def test_slider_class(self) -> None:
        self.assertIn(".bibliotheque-slider", self.css)

    def test_table_sortable_class(self) -> None:
        self.assertIn(".bibliotheque-table-sortable", self.css)

    def test_infinite_scroll_class(self) -> None:
        self.assertIn(".bibliotheque-infinite-sentinel", self.css)

    def test_inspector_classes(self) -> None:
        self.assertIn(".bibliotheque-inspector-meta", self.css)
        self.assertIn(".bibliotheque-inspector-aggregates", self.css)

    def test_nontier_chip_class(self) -> None:
        self.assertIn(".bibliotheque-chip--nontier", self.css)


# ---------------------------------------------------------------------------
# 10. Backend : extensions library_support
# ---------------------------------------------------------------------------


class BackendExtensionsTests(unittest.TestCase):
    """Verifie que _row_matches et _SORT_KEY supportent les nouveaux filtres
    et tris definis par la Phase 5."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.py = _LIBRARY_SUPPORT.read_text(encoding="utf-8")

    def test_size_filters_in_row_matches(self) -> None:
        self.assertIn("size_min", self.py)
        self.assertIn("size_max", self.py)

    def test_confidence_filters_in_row_matches(self) -> None:
        self.assertIn("confidence_min", self.py)
        self.assertIn("confidence_max", self.py)

    def test_added_date_range_filters(self) -> None:
        self.assertIn("added_after", self.py)
        self.assertIn("added_before", self.py)

    def test_source_and_languages_filters(self) -> None:
        self.assertIn('filters.get("source")', self.py)
        self.assertIn('filters.get("audio_languages")', self.py)
        self.assertIn('filters.get("subtitle_languages")', self.py)

    def test_chips_filter_supported(self) -> None:
        self.assertIn('filters.get("chips")', self.py)

    def test_sort_size(self) -> None:
        self.assertIn('"size_desc"', self.py)
        self.assertIn('"size_asc"', self.py)


if __name__ == "__main__":
    unittest.main()
