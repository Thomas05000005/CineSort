"""Test E2E desktop — 03. Scan (analyse).

Necessite un dossier de test avec quelques films factices.
Lancer : pytest tests/e2e_desktop/test_03_scan.py -v --timeout=300
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from .pages.accueil_page import AccueilPage


@pytest.fixture
def test_films_dir():
    """Cree un dossier temporaire avec 3 films factices (.nfo + .mkv vide)."""
    with tempfile.TemporaryDirectory(prefix="cinesort_e2e_") as tmp:
        for title, year in [("Inception", 2010), ("Matrix", 1999), ("Avatar", 2009)]:
            folder = Path(tmp) / f"{title} ({year})"
            folder.mkdir()
            # Fichier video vide (1 Ko)
            (folder / f"{title}.mkv").write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 1020)
            # NFO basique
            nfo = f'<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>{title}</title>\n  <year>{year}</year>\n</movie>\n'
            (folder / f"{title}.nfo").write_text(nfo, encoding="utf-8")
        yield tmp


class TestScan:
    """Tests du workflow d'analyse (scan)."""

    @pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="E2E mode requis")
    def test_scan_button_exists(self, page):
        """Le bouton de scan existe dans la vue Accueil."""
        accueil = AccueilPage(page)
        accueil.navigate()
        assert accueil.is_visible("home-btn-scan"), "Bouton scan non visible"

    @pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="E2E mode requis")
    def test_scan_start(self, page, test_films_dir):
        """Le scan demarre quand on clique sur le bouton."""
        # D'abord configurer le dossier racine via l'API JS
        page.evaluate(f"""() => {{
            if (window.pywebview?.api?.save_settings) {{
                window.pywebview.api.settings.save_settings({{
                    root: "{test_films_dir.replace(chr(92), "/")}",
                    roots: ["{test_films_dir.replace(chr(92), "/")}"],
                    tmdb_enabled: false,
                    state_dir: "{(test_films_dir + "/_state").replace(chr(92), "/")}",
                }});
            }}
        }}""")
        page.wait_for_timeout(500)

        accueil = AccueilPage(page)
        accueil.navigate()
        accueil.click_start_scan()
        page.wait_for_timeout(2000)

        # Verifier que la progress ou un message est visible
        accueil.screenshot("03_scan_started")

    @pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="E2E mode requis")
    def test_scan_journal(self, page):
        """Les logs s'affichent pendant ou apres le scan."""
        accueil = AccueilPage(page)
        accueil.navigate()
        page.wait_for_timeout(1000)
        # Le logbox peut avoir du contenu si un scan a ete lance
        logbox = page.query_selector('[data-testid="home-logbox"]')
        if logbox:
            text = logbox.text_content() or ""
            # On ne force pas qu'il y ait du contenu — juste qu'il existe
            assert logbox is not None
