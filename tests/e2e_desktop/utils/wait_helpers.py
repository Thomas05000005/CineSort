"""Helpers d'attente robustes pour les tests E2E desktop.

Aucun time.sleep() — uniquement page.wait_for_function() et page.evaluate().
"""

from __future__ import annotations


def wait_for_scan_complete(page, timeout_ms: int = 180_000) -> dict:
    """Attend la fin du scan.

    Signal fiable : le bouton "Charger la table" (btnLoadTable) passe de
    disabled a enabled quand le scan est termine avec succes.
    Fallback : le bouton "Lancer l'analyse" (btnStartPlan) redevient actif.
    """
    page.wait_for_function(
        """() => {
            try {
                // Signal primaire : bouton "Charger la table" active
                const btnLoad = document.getElementById('btnLoadTable');
                if (btnLoad && !btnLoad.disabled) return true;
                // Signal secondaire : bouton scan re-active ET section progress visible
                // (indique que le scan est passe par la et s'est termine)
                const btnScan = document.getElementById('btnStartPlan');
                const progress = document.getElementById('homeScanProgress');
                if (btnScan && !btnScan.disabled && progress && !progress.classList.contains('hidden'))
                    return true;
                return false;
            } catch { return false; }
        }""",
        timeout=timeout_ms,
    )
    return {}


def wait_for_table_loaded(page, selector: str = "#planTbody", min_rows: int = 1, timeout_ms: int = 30_000):
    """Attend qu'un tableau contienne au moins *min_rows* lignes <tr>."""
    page.wait_for_function(
        f"() => document.querySelectorAll('{selector} tr').length >= {min_rows}",
        timeout=timeout_ms,
    )


def wait_for_element_text(page, testid: str, timeout_ms: int = 10_000) -> str:
    """Attend qu'un element [data-testid] ait du texte non-vide.

    Retourne le texte.
    """
    page.wait_for_function(
        f"""() => {{
            const el = document.querySelector('[data-testid="{testid}"]');
            return el && (el.textContent || '').trim().length > 0;
        }}""",
        timeout=timeout_ms,
    )
    return page.evaluate(f"() => document.querySelector('[data-testid=\"{testid}\"]')?.textContent?.trim() || ''")


def wait_for_element_visible(page, selector: str, timeout_ms: int = 10_000):
    """Attend qu'un element soit visible dans le DOM."""
    page.wait_for_selector(selector, state="visible", timeout=timeout_ms)


def wait_for_api_ready(page, timeout_ms: int = 10_000):
    """Attend que pywebview.api soit disponible."""
    page.wait_for_function(
        "() => typeof window.pywebview !== 'undefined' && window.pywebview.api",
        timeout=timeout_ms,
    )


def evaluate_api(page, method: str, kwargs: str = "{}"):
    """Appelle une methode pywebview.api et retourne le resultat (synchrone)."""
    return page.evaluate(f"() => window.pywebview.api.{method}({kwargs})")
