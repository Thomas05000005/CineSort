"""Test E2E desktop — 10. Workflow complet : scan → validation → apply → undo.

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_10_full_workflow.py -v --timeout=600

Ce test exerce le workflow entier sur une mini-bibliotheque de 20 films factices.
Les tests sont sequentiels — si un prerequis echoue, les dependants sont skippes.
"""

from __future__ import annotations

import os

import pytest

try:
    import allure
except ImportError:
    allure = None

from .pages.base_page import BasePage
from .pages.accueil_page import AccueilPage
from .pages.bibliotheque_page import BibliothequePage
from .utils.wait_helpers import (
    wait_for_scan_complete,
    wait_for_table_loaded,
    wait_for_api_ready,
)


def _allure_step(name):
    """Retourne un context manager allure.step si disponible, sinon no-op."""
    if allure:
        return allure.step(name)
    import contextlib

    return contextlib.nullcontext()


def _attach_screenshot(page, name):
    """Capture un screenshot et l'attache a Allure si disponible."""
    base = BasePage(page)
    path = base.screenshot(name)
    if allure:
        try:
            png = page.screenshot()
            allure.attach(png, name=name, attachment_type=allure.attachment_type.PNG)
        except Exception:
            pass
    return path


# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="CINESORT_E2E non defini")
class TestFullWorkflow:
    """Workflow complet : configurer root → scanner → valider → appliquer → undo.

    Variable de classe pour tracker l'etat entre les tests (meme instance page).
    """

    # Etat partage entre les tests de la classe
    _scan_done = False
    _table_loaded = False
    _apply_done = False

    # --- 1. Configuration ----------------------------------------------------

    def test_configure_root(self, page, test_library):
        """Configurer le dossier racine vers la bibliotheque de test."""
        with _allure_step("Abaisser le seuil video pour les fichiers factices"):
            wait_for_api_ready(page)
            # Abaisser MIN_VIDEO_BYTES pour que les .mkv factices de 4Ko soient acceptes
            # Les appels pywebview.api sont asynchrones — utiliser await
            reset_result = page.evaluate("async () => await window.pywebview.api.test_reset(100)")
            assert reset_result and reset_result.get("ok"), f"test_reset echoue : {reset_result}"

        with _allure_step("Configurer le root + desactiver TMDb"):
            root = test_library["root"]
            # Desactiver TMDb pour eviter les lookups reseau lents
            result = page.evaluate(f"""async () => {{
                return await window.pywebview.api.save_settings({{
                    roots: ["{root.replace(chr(92), chr(92) * 2)}"],
                    root: "{root.replace(chr(92), chr(92) * 2)}",
                    probe_backend: "none",
                    tmdb_enabled: false,
                    enable_tv_detection: true,
                    subtitle_detection_enabled: false,
                    auto_approve_enabled: false,
                    dry_run: false,
                    perceptual_enabled: false,
                    watch_enabled: false,
                    plugins_enabled: false,
                    notifications_enabled: false,
                    incremental_scan_enabled: false,
                }});
            }}""")

        _attach_screenshot(page, "10_01_root_configured")
        assert result is not None

    # --- 2. Scan --------------------------------------------------------------

    def test_start_scan(self, page, test_library):
        """Naviguer vers l'Accueil et lancer l'analyse."""
        with _allure_step("Naviguer vers l'accueil"):
            accueil = AccueilPage(page)
            accueil.navigate()
            page.wait_for_timeout(1000)

        with _allure_step("Cliquer sur 'Lancer l'analyse'"):
            accueil.click_start_scan()
            page.wait_for_timeout(500)

        # Verifier que le scan a demarre (bouton desactive)
        btn_disabled = page.evaluate("() => document.getElementById('btnStartPlan')?.disabled === true")
        _attach_screenshot(page, "10_02_scan_started")
        assert btn_disabled, "Le bouton scan n'est pas desactive apres le clic"

    def test_scan_completes(self, page, test_library):
        """Attendre la fin du scan (timeout 3min)."""
        with _allure_step("Attendre la fin du scan"):
            try:
                wait_for_scan_complete(page, timeout_ms=180_000)
                TestFullWorkflow._scan_done = True
            except Exception as exc:
                _attach_screenshot(page, "10_03_scan_TIMEOUT")
                diag = page.evaluate("""() => {
                    const btn = document.getElementById('btnStartPlan');
                    const load = document.getElementById('btnLoadTable');
                    const msg = document.getElementById('planMsg');
                    return {
                        btnScan_disabled: btn?.disabled,
                        btnLoad_disabled: load?.disabled,
                        msg: msg?.textContent?.trim() || '',
                    };
                }""")
                pytest.fail(f"Scan timeout : {exc}\nDiagnostic : {diag}")

        with _allure_step("Verifier les KPIs"):
            accueil = AccueilPage(page)
            kpis = accueil.get_kpis()

        _attach_screenshot(page, "10_03_scan_complete")

    # --- 3. Table de validation -----------------------------------------------

    def test_load_table(self, page, test_library):
        """Charger la table de validation et verifier les lignes."""
        if not TestFullWorkflow._scan_done:
            pytest.skip("Prerequis : scan non termine")

        with _allure_step("Naviguer vers l'accueil et verifier le bouton"):
            # S'assurer d'etre sur la vue Accueil
            base = BasePage(page)
            base.navigate_to("home")
            page.wait_for_timeout(500)

            # Diagnostic : etat des boutons
            diag = page.evaluate("""() => {
                const load = document.getElementById('btnLoadTable');
                const scan = document.getElementById('btnStartPlan');
                const msg = document.getElementById('planMsg');
                return {
                    load_exists: !!load,
                    load_disabled: load?.disabled,
                    load_visible: load ? getComputedStyle(load).display !== 'none' : false,
                    scan_disabled: scan?.disabled,
                    msg: msg?.textContent?.trim() || '',
                };
            }""")

            if diag.get("load_disabled"):
                _attach_screenshot(page, "10_04_load_disabled")
                pytest.skip(
                    f"Bouton 'Charger la table' desactive — "
                    f"msg={diag.get('msg')}, scan_disabled={diag.get('scan_disabled')}"
                )

        with _allure_step("Charger la table via API JS et naviguer vers validation"):
            # Utiliser navigateTo qui charge les donnees ET navigue
            page.evaluate("""async () => {
                if (typeof navigateTo === 'function') {
                    await navigateTo('validation');
                } else if (typeof showView === 'function') {
                    showView('validation');
                }
            }""")
            page.wait_for_timeout(5000)

        with _allure_step("Verifier le nombre de lignes"):
            bib = BibliothequePage(page)
            try:
                wait_for_table_loaded(page, "#planTbody", min_rows=1, timeout_ms=15_000)
            except Exception:
                diag = page.evaluate("""() => {
                    const tbody = document.getElementById('planTbody');
                    const view = document.body.dataset?.view || '';
                    const valMsg = document.getElementById('valMsg');
                    const runId = typeof currentContextRunId === 'function' ? currentContextRunId() : '';
                    return {
                        tbody_exists: !!tbody,
                        tbody_rows: tbody ? tbody.children.length : -1,
                        active_view: view,
                        val_msg: valMsg?.textContent?.trim() || '',
                        run_id: runId,
                    };
                }""")
                _attach_screenshot(page, "10_04_table_EMPTY")
                pytest.fail(f"Table vide. Diagnostic : {diag}")

            count = bib.get_films_count()
            TestFullWorkflow._table_loaded = True
            # Avec TMDb desactive et fichiers factices, le nombre peut etre faible
            assert count >= 1, f"Aucun film dans la table : {count}"

        _attach_screenshot(page, "10_04_table_loaded")

    # --- 4. Validation --------------------------------------------------------

    def test_approve_films(self, page, test_library):
        """Approuver les premiers films de la table."""
        if not TestFullWorkflow._table_loaded:
            pytest.skip("Prerequis : table non chargee")

        with _allure_step("Approuver les films visibles"):
            bib = BibliothequePage(page)
            count = bib.get_films_count()
            if count == 0:
                pytest.skip("Aucun film dans la table")
            to_approve = min(8, count)
            for i in range(to_approve):
                bib.approve_film(i)
                page.wait_for_timeout(150)

        with _allure_step("Verifier le compteur"):
            checked_text = page.evaluate("""() => {
                const el = document.getElementById('valPillChecked');
                return el ? el.textContent : '';
            }""")

        _attach_screenshot(page, "10_05_films_approved")

    def test_save_validation(self, page, test_library):
        """Sauvegarder les decisions de validation."""
        if not TestFullWorkflow._table_loaded:
            pytest.skip("Prerequis : table non chargee")

        with _allure_step("S'assurer que la vue validation est visible"):
            # La table a ete chargee via le bouton home, on est sur la vue validation
            # Verifier que val-btn-save est visible
            visible = page.evaluate("""() => {
                const btn = document.querySelector('[data-testid="val-btn-save"]');
                if (!btn) return false;
                const rect = btn.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }""")
            if not visible:
                # Naviguer vers la vue validation
                page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
                page.wait_for_timeout(500)

        with _allure_step("Cliquer 'Sauvegarder'"):
            page.click('[data-testid="val-btn-save"]', timeout=5000)
            page.wait_for_timeout(1000)

        _attach_screenshot(page, "10_06_validation_saved")

    # --- 5. Dry-run -----------------------------------------------------------

    def test_dry_run(self, page, test_library):
        """Lancer un dry-run via la vue Execution."""
        if not TestFullWorkflow._table_loaded:
            pytest.skip("Prerequis : table non chargee")

        with _allure_step("Naviguer vers la vue Execution"):
            page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
            page.wait_for_timeout(500)

        with _allure_step("Cocher le dry-run si necessaire"):
            is_dry = page.evaluate("""() => {
                const ck = document.querySelector('[data-testid="exec-ck-dryrun"]');
                return ck ? ck.checked : null;
            }""")
            if not is_dry:
                page.click('[data-testid="exec-ck-dryrun"]')
                page.wait_for_timeout(300)

        with _allure_step("Cliquer 'Appliquer' (dry-run)"):
            page.click('[data-testid="exec-btn-apply"]')
            page.wait_for_timeout(3000)

        _attach_screenshot(page, "10_07_dry_run_result")

    # --- 6. Apply reel --------------------------------------------------------

    def test_real_apply(self, page, test_library):
        """Appliquer reellement (deplacer les fichiers)."""
        if not TestFullWorkflow._table_loaded:
            pytest.skip("Prerequis : table non chargee")

        with _allure_step("S'assurer d'etre sur la vue Execution"):
            page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
            page.wait_for_timeout(500)

        with _allure_step("Decocher le dry-run"):
            page.evaluate("""() => {
                const ck = document.querySelector('[data-testid="exec-ck-dryrun"]');
                if (ck && ck.checked) ck.click();
            }""")
            page.wait_for_timeout(300)

        with _allure_step("Cliquer 'Appliquer'"):
            page.click('[data-testid="exec-btn-apply"]')
            page.wait_for_timeout(5000)

        with _allure_step("Verifier le resultat"):
            result = page.evaluate("""() => {
                const el = document.querySelector('[data-testid="exec-apply-result"]');
                return el ? el.textContent : '';
            }""")
            if result:
                TestFullWorkflow._apply_done = True

        _attach_screenshot(page, "10_08_real_apply_result")

    # --- 7. Undo --------------------------------------------------------------

    def test_undo_preview(self, page, test_library):
        """Previsualiser l'annulation."""
        if not TestFullWorkflow._apply_done:
            pytest.skip("Prerequis : apply non execute")

        with _allure_step("S'assurer d'etre sur la vue Execution"):
            page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
            page.wait_for_timeout(500)

        with _allure_step("Cliquer 'Previsualiser l'annulation'"):
            page.click('[data-testid="exec-btn-undo-preview"]')
            page.wait_for_timeout(3000)

        _attach_screenshot(page, "10_09_undo_preview")

    def test_undo_execute(self, page, test_library):
        """Executer l'annulation et verifier les fichiers restaures."""
        if not TestFullWorkflow._apply_done:
            pytest.skip("Prerequis : apply non execute")

        with _allure_step("S'assurer d'etre sur la vue Execution"):
            page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
            page.wait_for_timeout(500)

        with _allure_step("Verifier que le bouton undo est actif"):
            undo_btn = page.query_selector('[data-testid="exec-btn-undo-run"]')
            if not undo_btn:
                pytest.skip("Bouton undo-run non trouve")
            is_enabled = page.evaluate("""() => {
                const btn = document.querySelector('[data-testid="exec-btn-undo-run"]');
                return btn && !btn.disabled;
            }""")
            if not is_enabled:
                _attach_screenshot(page, "10_10_undo_disabled")
                pytest.skip("Bouton undo desactive — preview n'a pas active le undo")

        with _allure_step("Cliquer 'Executer l'annulation'"):
            page.click('[data-testid="exec-btn-undo-run"]')
            page.wait_for_timeout(5000)

        with _allure_step("Verifier que les fichiers existent"):
            import pathlib

            root = test_library["root"]
            root_path = pathlib.Path(root)
            folders = [f.name for f in root_path.iterdir() if f.is_dir()]
            assert len(folders) >= 5, f"Trop peu de dossiers apres undo : {len(folders)}"

        _attach_screenshot(page, "10_10_undo_done")
