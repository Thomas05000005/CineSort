"""Test E2E dashboard — 06. Resilience API et cas limites.

Lancer : pytest tests/e2e_dashboard/test_dash_06_api_resilience.py -v

Teste le comportement du dashboard face aux erreurs reseau,
rate limiting, et les interactions avancees.
"""

from __future__ import annotations


class TestDashApiResilience:
    """Tests de resilience du dashboard face aux erreurs."""

    def test_api_health_returns_valid_json(self, page, e2e_server):
        """L'endpoint /api/health retourne un JSON valide."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(500)
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('{e2e_server["url"]}/api/health');
            return await resp.json();
        }}""")
        assert result["ok"] is True
        assert "version" in result
        assert "ts" in result

    def test_unauthorized_api_returns_401(self, page, e2e_server):
        """Les endpoints proteges retournent 401 sans token."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(500)
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('{e2e_server["url"]}/api/get_settings', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: '{{}}'
            }});
            return resp.status;
        }}""")
        assert result == 401

    def test_invalid_endpoint_returns_404(self, page, e2e_server):
        """Un endpoint inexistant retourne 404."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(500)
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('{e2e_server["url"]}/api/nonexistent_method', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer {e2e_server["token"]}'
                }},
                body: '{{}}'
            }});
            return resp.status;
        }}""")
        assert result == 404

    def test_themes_css_served_correctly(self, page, e2e_server):
        """Le fichier themes.css est servi correctement (fix ../themes.css)."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(500)
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('{e2e_server["url"]}/themes.css');
            return {{ status: resp.status, type: resp.headers.get('content-type') }};
        }}""")
        assert result["status"] == 200
        assert "text/css" in result["type"]

    def test_dashboard_static_files_served(self, page, e2e_server):
        """Les fichiers statiques du dashboard sont servis avec le bon MIME type."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(500)
        files = {
            "/dashboard/": "text/html",
            "/dashboard/app.js": "text/javascript",
            "/dashboard/styles.css": "text/css",
        }
        for path, expected_mime in files.items():
            result = page.evaluate(f"""async () => {{
                const resp = await fetch('{e2e_server["url"]}{path}');
                return {{ status: resp.status, type: resp.headers.get('content-type') }};
            }}""")
            assert result["status"] == 200, f"{path} a retourne {result['status']}"
            assert expected_mime in result["type"], f"{path}: attendu {expected_mime}, obtenu {result['type']}"

    def test_path_traversal_blocked(self, page, e2e_server):
        """La traversee de chemin dans /dashboard/ est bloquee."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(500)
        result = page.evaluate(f"""async () => {{
            const resp = await fetch('{e2e_server["url"]}/dashboard/../../../etc/passwd');
            return resp.status;
        }}""")
        # Doit retourner 403 ou 404, jamais 200
        assert result in (403, 404, 400), f"Path traversal non bloque : status {result}"


class TestDashSettingsIntegration:
    """Tests d'integration des parametres du dashboard."""

    def test_settings_loads_all_sections(self, dashboard_page):
        """La vue parametres charge toutes les sections attendues."""
        dashboard_page.click('[data-testid="nav-settings"]')
        dashboard_page.wait_for_timeout(1500)

        # Verifier les sections presentes
        sections = dashboard_page.evaluate("""() => {
            const el = document.getElementById('settingsContent');
            if (!el) return [];
            return Array.from(el.querySelectorAll('.card__eyebrow'))
                .map(h => h.textContent.trim());
        }""")
        assert len(sections) >= 10, f"Pas assez de sections parametres : {sections}"

    def test_settings_save_button_exists(self, dashboard_page):
        """Le bouton sauvegarder est present et cliquable."""
        dashboard_page.click('[data-testid="nav-settings"]')
        dashboard_page.wait_for_timeout(1500)
        save_btn = dashboard_page.query_selector('[data-testid="settings-btn-save"]')
        assert save_btn is not None, "Bouton sauvegarder absent"

    def test_settings_theme_selector_has_4_options(self, dashboard_page):
        """Le selecteur de theme a 4 options (studio, cinema, luxe, neon)."""
        dashboard_page.click('[data-testid="nav-settings"]')
        dashboard_page.wait_for_timeout(1500)
        options = dashboard_page.evaluate("""() => {
            const sel = document.getElementById('dSelTheme');
            if (!sel) return [];
            return Array.from(sel.options).map(o => o.value);
        }""")
        assert len(options) >= 4, f"Pas assez d'options de theme : {options}"
        for expected in ["studio", "cinema", "luxe", "neon"]:
            assert expected in options, f"Theme '{expected}' absent des options"

    def test_settings_animation_selector_exists(self, dashboard_page):
        """Le selecteur d'animation existe avec les 3 niveaux."""
        dashboard_page.click('[data-testid="nav-settings"]')
        dashboard_page.wait_for_timeout(1500)
        options = dashboard_page.evaluate("""() => {
            const sel = document.getElementById('dSelAnimation');
            if (!sel) return [];
            return Array.from(sel.options).map(o => o.value);
        }""")
        assert len(options) >= 3, f"Pas assez de niveaux d'animation : {options}"
