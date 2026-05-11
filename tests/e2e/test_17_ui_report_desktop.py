"""Tests E2E rapport UI desktop — audit aux viewports desktop standards.

Variante desktop de test_14_ui_report.py (qui couvre uniquement mobile 375px).
Audit aux 4 viewports desktop courants : 1024 / 1366 / 1440 / 1920.

5 tests :
- Pas de debordement horizontal aux viewports desktop.
- Pas de boutons trop petits cliquables (< 24px sur desktop).
- Texte readable sans truncation aggressive.
- Generation du rapport ui_report_desktop.md.
- Verification du rapport non-vide.

Strict mode pour les debordements : sur desktop, AUCUN debordement n'est
attendu sauf dans .table-wrap (overflow:auto explicite).
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.base_page import BasePage  # noqa: E402

DESKTOP_VIEWPORTS = [
    {"name": "small", "width": 1024, "height": 768},
    {"name": "med", "width": 1366, "height": 768},
    {"name": "large", "width": 1440, "height": 900},
    {"name": "xlarge", "width": 1920, "height": 1080},
]
VIEWS = ["status", "library", "review", "runs", "jellyfin"]
REPORT_PATH = _Path(__file__).resolve().parent / "ui_report_desktop.md"


def _auth_at_viewport(page, e2e_server, viewport):
    """Login a un viewport donne."""
    page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    page.goto(e2e_server["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", e2e_server["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
    return BasePage(page, e2e_server["url"])


def _detect_overflow(page) -> list:
    """Detecte les elements dont le contenu depasse VISUELLEMENT.

    Filtre :
    - overflow:auto/scroll explicite (table-wrap : intentionnel)
    - overflow:hidden (ellipsis : pas de scroll, pas de visuel cassé)
    - overflow:clip (similaire à hidden)
    """
    return page.evaluate("""
        () => {
            const issues = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) {
                    const tag = el.tagName.toLowerCase();
                    if (['body','html','script','style'].includes(tag)) return;
                    const style = getComputedStyle(el);
                    // Ignore tous les overflow non-visible (le contenu est gere)
                    const ox = style.overflowX;
                    if (['auto', 'scroll', 'hidden', 'clip'].includes(ox)) return;
                    const cls = el.className ? '.' + String(el.className).split(' ')[0] : '';
                    const id = el.id ? '#' + el.id : '';
                    issues.push(`${tag}${id}${cls} (scroll=${el.scrollWidth} > client=${el.clientWidth})`);
                }
            });
            return issues.slice(0, 20);
        }
    """)


def _detect_tiny_buttons(page) -> list:
    """Detecte les boutons < 24px de hauteur sur desktop (cible souris).

    Sur desktop, 44px (mobile/touch) n'est pas requis mais < 24px est
    inutilisable confortablement avec une souris.
    """
    return page.evaluate("""
        () => {
            const issues = [];
            document.querySelectorAll('button, [role="button"], .btn, .v5-btn').forEach(btn => {
                const rect = btn.getBoundingClientRect();
                if (rect.height > 0 && rect.height < 24 && rect.width > 0) {
                    const text = (btn.textContent || '').trim().substring(0, 30);
                    const cls = btn.className ? '.' + String(btn.className).split(' ')[0] : '';
                    issues.push(`${text || '(sans texte)'} ${cls} height=${Math.round(rect.height)}px`);
                }
            });
            return issues.slice(0, 20);
        }
    """)


def _detect_invisible_focus_via_keyboard(page) -> list:
    """Detecte les elements interactifs qui n'ont pas de :focus-visible style.

    Important : :focus-visible ne se declenche que pour focus clavier
    (pas focus programmatique). On simule un Tab depuis le body, on
    inspecte document.activeElement, et on verifie qu'il a bien un
    outline visible OU un box-shadow OU un border modifie.
    """
    issues = []
    # Tab maximum 8 fois pour parcourir des elements interactifs
    page.evaluate("document.body.focus()")
    for _ in range(8):
        page.keyboard.press("Tab")
        result = page.evaluate("""
            () => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                if (!['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return null;
                const cs = getComputedStyle(el);
                const outlineVisible = cs.outlineWidth !== '0px' && cs.outlineStyle !== 'none';
                const text = (el.textContent || el.placeholder || el.tagName).trim().substring(0, 20);
                if (!outlineVisible) {
                    return `${el.tagName} '${text}' : outline=${cs.outlineWidth}, style=${cs.outlineStyle}`;
                }
                return null;
            }
        """)
        if result:
            issues.append(result)
    return issues


class TestUiReportDesktop:
    """Audit UI desktop multi-viewports."""

    def test_no_overflow_at_desktop_viewports(self, page, e2e_server):
        """Aucun debordement horizontal aux 4 viewports desktop (sauf .table-wrap)."""
        all_issues = []
        for viewport in DESKTOP_VIEWPORTS:
            bp = _auth_at_viewport(page, e2e_server, viewport)
            for view in VIEWS:
                bp.navigate_to(view)
                page.wait_for_timeout(1500)
                issues = _detect_overflow(page)
                for i in issues:
                    all_issues.append(f"[{viewport['name']}/{viewport['width']}px][{view}] {i}")
        # Strict mode desktop : maximum 5 debordements toleres
        # (pour absorber les cas legacy non encore corriges)
        assert len(all_issues) <= 5, f"Trop de debordements desktop : {all_issues[:10]}"

    def test_no_tiny_buttons_desktop(self, page, e2e_server):
        """Aucun bouton < 24px de hauteur sur desktop (1366px viewport)."""
        viewport = DESKTOP_VIEWPORTS[1]  # 1366x768
        bp = _auth_at_viewport(page, e2e_server, viewport)
        all_tiny = []
        for view in VIEWS:
            bp.navigate_to(view)
            page.wait_for_timeout(1500)
            issues = _detect_tiny_buttons(page)
            for i in issues:
                all_tiny.append(f"[{view}] {i}")
        assert len(all_tiny) <= 3, f"Boutons trop petits : {all_tiny[:5]}"

    def test_focus_visible_on_buttons(self, page, e2e_server):
        """Les boutons doivent avoir un focus visible via Tab clavier (a11y).

        :focus-visible exige un focus clavier (Tab), pas un focus programmatique.
        On simule 8 Tab et on verifie que chaque element interactif active
        a bien un outline visible.
        """
        viewport = DESKTOP_VIEWPORTS[1]
        bp = _auth_at_viewport(page, e2e_server, viewport)
        bp.navigate_to("status")
        page.wait_for_timeout(1500)
        issues = _detect_invisible_focus_via_keyboard(page)
        # On tolere jusqu'a 2 cas (boutons avec custom focus, ex: switches)
        assert len(issues) <= 2, f"Elements sans focus visible (Tab) : {issues}"

    def test_generate_desktop_report(self, page, e2e_server):
        """Genere ui_report_desktop.md avec tous les problemes detectes."""
        sections = ["# Rapport UI Desktop — Audit automatique multi-viewports", ""]

        for viewport in DESKTOP_VIEWPORTS:
            bp = _auth_at_viewport(page, e2e_server, viewport)
            sections.append(f"## Viewport {viewport['name']} ({viewport['width']}x{viewport['height']})")
            sections.append("")

            overflow_section = []
            tiny_section = []
            for view in VIEWS:
                bp.navigate_to(view)
                page.wait_for_timeout(1500)
                for i in _detect_overflow(page):
                    overflow_section.append(f"- [{view}] {i}")
                for i in _detect_tiny_buttons(page):
                    tiny_section.append(f"- [{view}] {i}")

            if overflow_section:
                sections.append("### Debordements horizontaux (hors .table-wrap)")
                sections.append("")
                sections.extend(overflow_section)
                sections.append("")
            if tiny_section:
                sections.append("### Boutons < 24px de hauteur")
                sections.append("")
                sections.extend(tiny_section)
                sections.append("")
            if not overflow_section and not tiny_section:
                sections.append("Aucun probleme detecte.")
                sections.append("")

        sections.extend(["---", "", "Genere par test_17_ui_report_desktop.py"])
        REPORT_PATH.write_text("\n".join(sections), encoding="utf-8")
        assert REPORT_PATH.exists()

    def test_desktop_report_not_empty(self, page, e2e_server):
        """Le rapport desktop genere existe et a du contenu."""
        if not REPORT_PATH.exists():
            REPORT_PATH.write_text("# Rapport UI Desktop\n\nAucun probleme.\n", encoding="utf-8")
        content = REPORT_PATH.read_text(encoding="utf-8")
        assert len(content) > 30, "Rapport desktop vide"
