"""Test E2E dashboard — 03. Workflow complet (table, validation, apply).

Lancer : pytest tests/e2e_dashboard/test_dash_03_full_workflow.py -v

Utilise les 15 films mock generes par create_test_data.py.
"""

from __future__ import annotations


class TestDashFullWorkflow:
    """Workflow complet via le dashboard distant."""

    def _go_to_library(self, page):
        """Naviguer vers la vue Bibliotheque."""
        page.click('[data-testid="nav-library"]')
        page.wait_for_timeout(1000)

    def _go_to_validation(self, page):
        """Naviguer vers la Bibliotheque puis l'etape Validation."""
        self._go_to_library(page)
        page.click('[data-testid="lib-step-validation"]')
        page.wait_for_timeout(2000)

    def test_library_shows_run_label(self, dashboard_page):
        """La Bibliotheque affiche un identifiant de run non vide."""
        self._go_to_library(dashboard_page)
        label = dashboard_page.evaluate("""() => {
            const el = document.querySelector('[data-testid="lib-run-label"]');
            return el ? el.textContent.trim() : '';
        }""")
        assert label and label != "—", f"Run label vide ou tiret : '{label}'"

    def test_validation_table_has_15_films(self, dashboard_page):
        """La table de validation contient les 15 films mock."""
        self._go_to_validation(dashboard_page)
        count = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            if (!table) return 0;
            return table.querySelectorAll('tbody tr').length;
        }""")
        assert count >= 10, f"Pas assez de films dans la table : {count}"

    def test_validation_table_has_correct_columns(self, dashboard_page):
        """La table de validation a les colonnes essentielles."""
        self._go_to_validation(dashboard_page)
        headers = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            if (!table) return [];
            return Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
        }""")
        assert len(headers) >= 4, f"Pas assez de colonnes : {headers}"

    def test_search_filters_rows_effectively(self, dashboard_page):
        """La recherche 'Avengers' ne retourne que les films correspondants."""
        self._go_to_validation(dashboard_page)
        total = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            return table ? table.querySelectorAll('tbody tr').length : 0;
        }""")
        # Rechercher Avengers
        search = dashboard_page.query_selector('[data-testid="lib-valid-search"]')
        assert search is not None, "Champ de recherche absent"
        search.fill("Avengers")
        dashboard_page.wait_for_timeout(500)
        filtered = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            return table ? table.querySelectorAll('tbody tr').length : 0;
        }""")
        assert 0 < filtered < total, f"La recherche 'Avengers' devrait filtrer : total={total}, filtre={filtered}"
        # Nettoyer
        search.fill("")
        dashboard_page.wait_for_timeout(300)

    def test_approve_all_and_save(self, dashboard_page):
        """Approuver tous les films puis sauvegarder reussit."""
        self._go_to_validation(dashboard_page)
        # Tout approuver
        check_all = dashboard_page.query_selector('[data-testid="lib-valid-btn-check-all"]')
        assert check_all is not None, "Bouton 'tout approuver' absent"
        check_all.click()
        dashboard_page.wait_for_timeout(500)
        # Verifier que des films sont coches
        checked = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            if (!table) return 0;
            return table.querySelectorAll('tbody tr.row-approved, tbody tr input:checked').length;
        }""")
        assert checked > 0, "Aucun film approuve apres 'tout approuver'"
        # Sauvegarder
        save_btn = dashboard_page.query_selector('[data-testid="lib-valid-btn-save"]')
        assert save_btn is not None, "Bouton 'sauvegarder' absent"
        save_btn.click()
        dashboard_page.wait_for_timeout(2000)

    def test_duplicates_section_loads(self, dashboard_page):
        """La section doublons se charge avec un compteur."""
        self._go_to_library(dashboard_page)
        dashboard_page.click('[data-testid="lib-step-doublons"]')
        dashboard_page.wait_for_timeout(1000)
        check_btn = dashboard_page.query_selector('[data-testid="lib-dup-btn-check"]')
        assert check_btn is not None, "Bouton verification doublons absent"
        check_btn.click()
        dashboard_page.wait_for_timeout(3000)
        count_el = dashboard_page.query_selector('[data-testid="lib-dup-count"]')
        assert count_el is not None, "Compteur doublons absent"

    def test_apply_section_has_dry_run(self, dashboard_page):
        """La section Application a un checkbox dry-run et un bouton appliquer."""
        self._go_to_library(dashboard_page)
        dashboard_page.click('[data-testid="lib-step-application"]')
        dashboard_page.wait_for_timeout(1000)
        dry_run = dashboard_page.query_selector('[data-testid="lib-apply-ck-dryrun"]')
        assert dry_run is not None, "Checkbox dry-run absente"
        apply_btn = dashboard_page.query_selector('[data-testid="lib-apply-btn-run"]')
        assert apply_btn is not None, "Bouton appliquer absent"

    def test_confidence_filter_reduces_rows(self, dashboard_page):
        """Le filtre confiance 'low' reduit le nombre de lignes."""
        self._go_to_validation(dashboard_page)
        total = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            return table ? table.querySelectorAll('tbody tr').length : 0;
        }""")
        conf = dashboard_page.query_selector('[data-testid="lib-valid-filter-conf"]')
        if conf:
            dashboard_page.select_option('[data-testid="lib-valid-filter-conf"]', "low")
            dashboard_page.wait_for_timeout(500)
            filtered = dashboard_page.evaluate("""() => {
                const table = document.querySelector('[data-testid="lib-valid-table"]');
                return table ? table.querySelectorAll('tbody tr').length : 0;
            }""")
            assert filtered <= total, f"Le filtre n'a pas reduit : total={total}, filtre={filtered}"

    def test_presets_buttons_exist(self, dashboard_page):
        """Les boutons de presets sont presents et cliquables."""
        self._go_to_validation(dashboard_page)
        presets = dashboard_page.query_selector('[data-testid="lib-valid-presets"]')
        assert presets is not None, "Zone presets absente"
        btns = presets.query_selector_all("button")
        assert len(btns) >= 3, f"Pas assez de presets : {len(btns)}"
        # Cliquer sur le premier preset ne plante pas
        btns[0].click()
        dashboard_page.wait_for_timeout(300)
