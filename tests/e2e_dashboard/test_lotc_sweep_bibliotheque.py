"""Lot C (verif totale 2026-07) — Sweep runtime Playwright : vue #/bibliotheque.

Couverture (spec 07-bibliotheque.md, 15 films mock deterministes) :
  - rendu grille + compteur header + fin de liste (15 < PAGE_SIZE=60)
  - toggle grille/tableau + tri (headers triables + select 12 options)
  - filtres tier (7 chips) + chips non-tier (coherence compteur/cartes)
  - recherche debouncee (250 ms)
  - drawer "Filtres avances" : ouverture / fermeture (bouton + backdrop)
  - selection d'un film -> inspecteur droit (film-detail mode A)
  - bulk actions : rescan + analyse perceptuelle (SURES), export (modale
    ANNULEE), marquer pour suppression (dangerConfirmModal -> ANNULER,
    jamais confirmer), annuler selection
  - navigation aller-retour x3 (#/accueil <-> #/bibliotheque) : pas
    d'empilement DOM, pas de residu modale/drawer

Chaque test capture console.error + pageerror : 0 erreur toleree hors
liste blanche nominative (_CONSOLE_WHITELIST, bruit connu commente).

Screenshots -> docs/internal/verif_totale_2026_07/captures_runtime/.

Lancer :
  .venv/Scripts/python.exe -X utf8 -m pytest \
      tests/e2e_dashboard/test_lotc_sweep_bibliotheque.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_CAPTURES_DIR = Path(__file__).resolve().parents[2] / "docs" / "internal" / "verif_totale_2026_07" / "captures_runtime"

# 15 films mock (tests/e2e/create_test_data.py::build_plan_rows)
_TOTAL_FILMS = 15

# Liste blanche NOMINATIVE du bruit console connu (substring match sur
# "texte [url]" — cf _ConsoleWatch qui suffixe l'URL de msg.location).
_CONSOLE_WHITELIST = (
    # R6-H (audit 2026-06-14) : TMDb est desactive dans les settings mock
    # (tmdb_enabled=False) -> le proxy /api/poster repond un corps JSON
    # 404/503 au lieu d'une image. Le navigateur logge alors
    # "Failed to load resource ... 503" pour chaque <img> de jaquette ;
    # l'UI remplace deja l'image cassee par le placeholder (listener
    # 'error' en phase capture, bibliotheque.js). Bruit connu, pas un bug.
    "/api/poster",
    # Echo du MEME bruit par bootstrap-debug.js : son handler window
    # 'error' (phase capture) recoit aussi les erreurs de chargement
    # ressource (<img> jaquette 503), qui n'ont ni message ni filename ->
    # "console.error: [BOOT-DEBUG] window.error {message: undefined, ...}".
    # Une vraie erreur JS aurait message/error_name renseignes et ne
    # matcherait pas ce prefixe (et serait de toute facon dupliquee en
    # pageerror, non whitelistee).
    "[BOOT-DEBUG] window.error {message: undefined",
    # BUG CONNU (Lot C 2026-07, REPORTE, ne pas corriger ici) : handlers
    # inline bloques par la CSP script-src 'self' du rest_server :
    #   - bibliotheque.js L495 : onclick="event.stopPropagation()" sur le
    #     label checkbox des cartes (mort ; mitige par la delegation) ;
    #   - film-detail.js L206/L337 + qualite.js/doublons.js : onerror="..."
    #     de fallback des <img> posters (mort -> icone image cassee dans
    #     l'inspecteur quand le poster 404/503).
    # Chaque clic/echec d'image declenche "Executing inline event handler
    # violates ... script-src 'self'". Whiteliste pour que le sweep reste
    # exploitable ; le bug est trace dans le rapport Lot C.
    "Executing inline event handler violates",
    # Bruit navigateur : pas de favicon.ico servie par le dashboard -> 404.
    "favicon",
)

_TIERS = ["platinum", "gold", "silver", "bronze", "reject", "unknown"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ConsoleWatch:
    """Collecte console.error + pageerror d'une page Playwright."""

    def __init__(self, page) -> None:
        self.entries: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)

    def _on_console(self, msg) -> None:
        if msg.type == "error":
            # msg.location fournit l'URL de la ressource en echec pour les
            # "Failed to load resource" -> permet un whitelist par endpoint.
            try:
                loc = (msg.location or {}).get("url", "")
            except Exception:
                loc = ""
            self.entries.append(f"console.error: {msg.text} [{loc}]")

    def _on_pageerror(self, err) -> None:
        self.entries.append(f"pageerror: {err}")

    def errors(self) -> list[str]:
        """Entrees non couvertes par la liste blanche."""
        return [e for e in self.entries if not any(w in e for w in _CONSOLE_WHITELIST)]


def _assert_console_clean(watch: _ConsoleWatch, context: str) -> None:
    errs = watch.errors()
    assert not errs, f"Erreurs console/JS pendant {context} : {errs}"


def _install_toast_recorder(page) -> None:
    """Enregistre chaque toast ajoute au DOM dans window.__lotc_toasts.

    Les toasts s'auto-ferment (~3.5 s) : un MutationObserver evite les
    courses entre l'action et la lecture du DOM.
    """
    page.evaluate(
        """() => {
            if (window.__lotc_toast_observer) return;
            window.__lotc_toasts = [];
            const obs = new MutationObserver((muts) => {
                for (const m of muts) {
                    for (const n of m.addedNodes) {
                        if (n.nodeType === 1 && n.classList &&
                            n.classList.contains('toast')) {
                            const t = n.querySelector('.toast__text');
                            window.__lotc_toasts.push({
                                cls: String(n.className || ''),
                                text: t ? String(t.textContent || '') : '',
                            });
                        }
                    }
                }
            });
            obs.observe(document.body, { childList: true, subtree: true });
            window.__lotc_toast_observer = obs;
        }"""
    )


def _toasts(page) -> list:
    return page.evaluate("() => window.__lotc_toasts || []")


def _wait_toast(page, pattern: str, timeout: int = 15000) -> dict:
    """Attend un toast dont le texte matche `pattern` (regex JS, i)."""
    page.wait_for_function(
        f"""() => (window.__lotc_toasts || []).some(
            (t) => new RegExp({pattern!r}, 'i').test(t.text))""",
        timeout=timeout,
    )
    for t in _toasts(page):
        if re.search(pattern, t["text"], re.IGNORECASE):
            return t
    raise AssertionError(f"Toast /{pattern}/i introuvable")  # pragma: no cover


def _wait_stable(page, timeout: int = 15000) -> None:
    """Attend l'etat stable de la vue bibliotheque (ni busy ni skeleton)."""
    page.wait_for_function(
        """() => {
            const v = document.querySelector('.bibliotheque-view');
            if (!v) return false;
            if (v.getAttribute('aria-busy') === 'true') return false;
            if (v.querySelector('.bibliotheque-loading-header')) return false;
            if (v.querySelector('.v5-skeleton')) return false;
            return !!v.querySelector(
                '.bibliotheque-grid, .bibliotheque-table-wrap, .bibliotheque-empty');
        }""",
        timeout=timeout,
    )
    # Laisser passer le re-render differe des counters (fetch post-rows).
    page.wait_for_timeout(400)


def _goto_bibliotheque(page) -> None:
    """Navigation par hash (consigne Lot C : location.hash, pas de click nav)."""
    page.evaluate("() => { window.location.hash = '#/bibliotheque'; }")
    _wait_stable(page)


def _cards_count(page) -> int:
    return page.locator(".bibliotheque-card").count()


def _screenshot(page, name: str) -> None:
    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_CAPTURES_DIR / name), full_page=True)


@pytest.fixture()
def biblio(dashboard_page):
    """Page connectee au shell, console surveillee, vue #/bibliotheque montee."""
    watch = _ConsoleWatch(dashboard_page)
    _install_toast_recorder(dashboard_page)
    _goto_bibliotheque(dashboard_page)
    return dashboard_page, watch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLotCSweepBibliotheque:
    """Sweep runtime de la vue #/bibliotheque (Lot C verif totale 2026-07)."""

    def test_01_rendu_grille_initial(self, biblio):
        """La grille rend les 15 films mock, header + fin de liste coherents."""
        page, watch = biblio

        assert "/bibliotheque" in page.evaluate("() => window.location.hash")
        # Vue montee dans #view-library (route /bibliotheque, cf app.js)
        assert page.locator("#view-library .bibliotheque-view").count() == 1

        assert _cards_count(page) == _TOTAL_FILMS, f"Grille attendue avec {_TOTAL_FILMS} cartes"
        summary = page.locator(".bibliotheque-summary").inner_text()
        assert str(_TOTAL_FILMS) in summary, f"Header summary inattendu : {summary!r}"

        # 15 < PAGE_SIZE (60) : pas de sentinel de scroll infini, marqueur de fin.
        assert page.locator("[data-bibliotheque-sentinel]").count() == 0
        end = page.locator(".bibliotheque-infinite-end").inner_text()
        assert str(_TOTAL_FILMS) in end, f"Marqueur fin de liste inattendu : {end!r}"

        # Scroll jusqu'en bas : aucune erreur attendue (pas de page 2).
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(500)
        assert _cards_count(page) == _TOTAL_FILMS

        _screenshot(page, "bibliotheque.png")
        _assert_console_clean(watch, "rendu grille initial")

    def test_02_toggle_tableau_et_tri(self, biblio):
        """Toggle grille/tableau, tri par header (annee asc/desc) et select (score)."""
        page, watch = biblio

        # -- Passage en tableau dense
        page.click('[data-bibliotheque-view="table"]')
        page.wait_for_selector(".bibliotheque-table-row", timeout=10000)
        assert page.locator(".bibliotheque-table-row").count() == _TOTAL_FILMS

        def col_values(idx: int) -> list[str]:
            return page.evaluate(
                f"""() => Array.from(
                    document.querySelectorAll('.bibliotheque-table-row'))
                    .map((tr) => tr.children[{idx}].textContent.trim())"""
            )

        # -- Tri header "Annee" : 1er clic = asc, 2e clic = desc (col idx 2)
        page.click('[data-bibliotheque-thsort="year"]')
        _wait_stable(page)
        years = [int(y) for y in col_values(2) if y.isdigit()]
        assert len(years) == _TOTAL_FILMS
        assert years == sorted(years), f"Tri annee ascendant casse : {years}"

        page.click('[data-bibliotheque-thsort="year"]')
        _wait_stable(page)
        years = [int(y) for y in col_values(2) if y.isdigit()]
        assert years == sorted(years, reverse=True), f"Tri annee descendant casse : {years}"

        # -- Tri via le select (score meilleur -> pire, col idx 5 "NN/100")
        page.select_option("[data-bibliotheque-sort]", "score_desc")
        _wait_stable(page)
        scores = [int(m.group(1)) for m in (re.match(r"(\d+)/100", s) for s in col_values(5)) if m]
        assert len(scores) >= 2, "Colonne Score illisible (aucun 'NN/100')"
        assert scores == sorted(scores, reverse=True), f"Tri score desc casse : {scores}"

        # -- Retour grille
        page.click('[data-bibliotheque-view="grid"]')
        page.wait_for_selector(".bibliotheque-grid", timeout=10000)
        assert _cards_count(page) == _TOTAL_FILMS
        _screenshot(page, "bibliotheque_table_tri.png")
        _assert_console_clean(watch, "toggle tableau + tri")

    def test_03_filtres_tier_et_chips(self, biblio):
        """Chaque chip tier filtre la grille ; compteur chip == cartes rendues."""
        page, watch = biblio

        def chip_count(selector: str) -> int:
            txt = page.locator(f"{selector} .bibliotheque-chip-count").inner_text()
            return int(txt.strip())

        # Les compteurs arrivent par un 2e fetch (get_library_counters_by_chip)
        # qui re-rend les chips APRES la grille : attendre qu'ils soient peuples.
        page.wait_for_function(
            """() => {
                const c = document.querySelector(
                    '[data-bibliotheque-tier="all"] .bibliotheque-chip-count');
                return !!c && parseInt(c.textContent, 10) > 0;
            }""",
            timeout=10000,
        )

        # Coherence globale : "Tous" == somme des 6 tiers == 15.
        assert chip_count('[data-bibliotheque-tier="all"]') == _TOTAL_FILMS
        tier_counts = {t: chip_count(f'[data-bibliotheque-tier="{t}"]') for t in _TIERS}
        assert sum(tier_counts.values()) == _TOTAL_FILMS, f"Somme des compteurs tier != {_TOTAL_FILMS} : {tier_counts}"

        for tier, expected in tier_counts.items():
            page.click(f'[data-bibliotheque-tier="{tier}"]')
            _wait_stable(page)
            assert "is-active" in (page.locator(f'[data-bibliotheque-tier="{tier}"]').get_attribute("class") or ""), (
                f"Chip tier {tier} pas active apres clic"
            )
            got = _cards_count(page)
            assert got == expected, f"Tier {tier} : {got} cartes rendues vs compteur chip {expected}"
            if expected == 0:
                # Reaction visible attendue : empty state "Aucun resultat".
                assert page.locator(".bibliotheque-empty").count() == 1, f"Tier {tier} vide sans empty state"
            else:
                # Toutes les cartes portent le badge du tier filtre.
                badges = page.evaluate(
                    """() => Array.from(
                        document.querySelectorAll('.bibliotheque-tier-badge'))
                        .map((b) => b.className)"""
                )
                assert all(f"--{tier}" in c for c in badges), f"Tier {tier} : badge etranger dans la grille : {badges}"

        # Retour "Tous"
        page.click('[data-bibliotheque-tier="all"]')
        _wait_stable(page)
        assert _cards_count(page) == _TOTAL_FILMS

        # Chip non-tier "Sans subs FR" : toggle ON puis OFF.
        n_subs = chip_count('[data-bibliotheque-chip="subs_missing_fr"]')
        page.click('[data-bibliotheque-chip="subs_missing_fr"]')
        _wait_stable(page)
        got = _cards_count(page)
        assert got == n_subs, f"Chip subs_missing_fr : {got} cartes vs compteur {n_subs}"
        page.click('[data-bibliotheque-chip="subs_missing_fr"]')
        _wait_stable(page)
        assert _cards_count(page) == _TOTAL_FILMS, "Untoggle chip ne restaure pas la grille"

        _assert_console_clean(watch, "filtres tier + chips")

    def test_04_recherche(self, biblio):
        """La recherche debouncee filtre par titre (2 x 'Dune Part Two' en mock)."""
        page, watch = biblio

        page.fill("[data-bibliotheque-search]", "Dune")
        # Debounce 250 ms + fetch : attendre le resultat exact.
        page.wait_for_function(
            "() => document.querySelectorAll('.bibliotheque-card').length === 2",
            timeout=10000,
        )
        titles = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('.bibliotheque-card-title'))
                .map((t) => t.textContent.trim())"""
        )
        assert len(titles) == 2 and all("Dune" in t for t in titles), (
            f"Recherche 'Dune' devrait rendre les 2 versions Dune : {titles}"
        )

        page.fill("[data-bibliotheque-search]", "")
        page.wait_for_function(
            f"() => document.querySelectorAll('.bibliotheque-card').length === {_TOTAL_FILMS}",
            timeout=10000,
        )
        _assert_console_clean(watch, "recherche")

    def test_05_selection_film_inspecteur(self, biblio):
        """Clic sur une carte -> inspecteur droit rend film-detail (mode A)."""
        page, watch = biblio

        first_title = page.locator(".bibliotheque-card-title").first.inner_text().strip()
        # Clic sur le bloc info (evite la checkbox en coin de poster).
        page.locator(".bibliotheque-card .bibliotheque-card-info").first.click()

        panel = "[data-v5-right-panel-body]"
        page.wait_for_selector(f"{panel} .film-detail", state="attached", timeout=15000)
        # Le mode A ne doit PAS finir en etat d'erreur.
        page.wait_for_function(
            """() => {
                const b = document.querySelector('[data-v5-right-panel-body]');
                if (!b) return false;
                if (b.querySelector('.film-detail--loading')) return false;
                return !!b.querySelector('.film-detail');
            }""",
            timeout=15000,
        )
        assert page.locator(f"{panel} .film-detail--error").count() == 0, (
            "Inspecteur : film-detail en etat d'erreur apres selection"
        )
        panel_text = page.locator(panel).inner_text()
        assert first_title in panel_text, f"Inspecteur : titre {first_title!r} absent du panneau : {panel_text[:200]!r}"
        _screenshot(page, "bibliotheque_inspecteur.png")
        _assert_console_clean(watch, "selection film -> inspecteur")

    def test_06_drawer_filtres_avances(self, biblio):
        """Drawer 'Avance' : ouverture, fermeture (Echap, bouton x, backdrop).

        Garde anti-regression pointeur : si le backdrop (rendu APRES l'aside,
        deux position:absolute freres sans z-index -> peint AU-DESSUS du
        panneau, components.css L7311/L7323) intercepte les clics DANS le
        drawer, le test est marque xfail avec le bug ; une fois le z-index
        corrige, le chemin nominal (clic sur x) s'executera et devra passer.
        """
        page, watch = biblio

        def open_drawer():
            page.click('[data-bibliotheque-action="filters"]')
            page.wait_for_selector(
                "#libraryAdvancedDrawer.is-open .bibliotheque-drawer-advanced",
                timeout=10000,
            )

        # Ouverture (action m4 : data-bibliotheque-action="filters")
        open_drawer()
        assert page.locator("#libraryAdvancedDrawer .bibliotheque-drawer-advanced").get_attribute("role") == "dialog"
        page.wait_for_timeout(300)  # fin de la transition translateX (0.22s)
        _screenshot(page, "bibliotheque_drawer_avance.png")

        # Fermeture via Echap (toujours fonctionnelle, handler document keydown)
        page.keyboard.press("Escape")
        page.wait_for_selector("#libraryAdvancedDrawer", state="detached", timeout=10000)

        # Re-ouverture + probe runtime : qui recoit les clics au centre du
        # bouton x et du bouton Appliquer ?
        open_drawer()
        page.wait_for_timeout(300)
        intercepted = page.evaluate(
            """() => {
                const hits = [];
                for (const sel of ['.bibliotheque-drawer-close',
                                   '[data-drawer-action="apply"]']) {
                    const el = document.querySelector(sel);
                    if (!el) continue;
                    const r = el.getBoundingClientRect();
                    const top = document.elementFromPoint(
                        r.left + r.width / 2, r.top + r.height / 2);
                    hits.push({
                        sel,
                        interceptedByBackdrop: !!(top &&
                            top.hasAttribute('data-drawer-backdrop')),
                    });
                }
                return hits;
            }"""
        )
        blocked = [h["sel"] for h in intercepted if h["interceptedByBackdrop"]]
        if blocked:
            # Le backdrop couvre le panneau : tout clic dans le drawer ferme
            # le tiroir (formulaire inutilisable a la souris). On verifie que
            # la fermeture backdrop marche puis on marque le bug.
            page.click("#libraryAdvancedDrawer [data-drawer-backdrop]")
            page.wait_for_selector("#libraryAdvancedDrawer", state="detached", timeout=10000)
            assert _cards_count(page) == _TOTAL_FILMS
            _assert_console_clean(watch, "drawer filtres avances (bug backdrop)")
            pytest.xfail(
                "BUG Lot C (REPORTE) : le backdrop du drawer avance est peint "
                f"au-dessus du panneau et intercepte les clics sur {blocked} "
                "-> tout clic dans le drawer le ferme (components.css "
                "L7311-7343, aucun z-index sur .bibliotheque-drawer-advanced)"
            )

        # Chemin nominal (attendu apres correction du z-index) :
        page.click("#libraryAdvancedDrawer .bibliotheque-drawer-close")
        page.wait_for_selector("#libraryAdvancedDrawer", state="detached", timeout=10000)
        open_drawer()
        page.click("#libraryAdvancedDrawer [data-drawer-backdrop]")
        page.wait_for_selector("#libraryAdvancedDrawer", state="detached", timeout=10000)

        # La grille est intacte apres le cycle drawer.
        assert _cards_count(page) == _TOTAL_FILMS
        _assert_console_clean(watch, "drawer filtres avances")

    def test_07_navigation_aller_retour_x3(self, biblio):
        """3 allers-retours #/accueil <-> #/bibliotheque : ni erreur ni empilement."""
        page, watch = biblio

        for i in range(3):
            page.evaluate("() => { window.location.hash = '#/accueil'; }")
            page.wait_for_selector("#view-status.active", timeout=10000)
            page.wait_for_timeout(400)

            _goto_bibliotheque(page)

            # Pas d'empilement : 1 seule instance de la vue, du panneau droit,
            # aucune modale/drawer residuelle.
            counts = page.evaluate(
                """() => ({
                    views: document.querySelectorAll('.bibliotheque-view').length,
                    grids: document.querySelectorAll('.bibliotheque-grid').length,
                    panels: document.querySelectorAll('.v5-right-panel').length,
                    drawers: document.querySelectorAll('#libraryAdvancedDrawer').length,
                    modals: document.querySelectorAll('#dashModal, #dashDangerModal').length,
                })"""
            )
            assert counts["views"] == 1, f"A/R {i + 1} : empilement de vues : {counts}"
            assert counts["grids"] == 1, f"A/R {i + 1} : empilement de grilles : {counts}"
            assert counts["panels"] == 1, f"A/R {i + 1} : empilement right-panel : {counts}"
            assert counts["drawers"] == 0 and counts["modals"] == 0, f"A/R {i + 1} : overlay residuel : {counts}"
            assert _cards_count(page) == _TOTAL_FILMS, f"A/R {i + 1} : grille incomplete apres retour"

        _assert_console_clean(watch, "navigation aller-retour x3")

    def test_08_bulk_actions(self, biblio):
        """Selection multiple : export/suppression(ANNULEES), rescan/perceptuel.

        VOLONTAIREMENT EN DERNIER : le bulk "Re-scanner" cree un run parasite
        cote backend (JobRunner.start_job -> nouveau run 'latest' sans plan)
        qui vide la bibliotheque pour le reste de la session serveur
        (session-scoped). Tout test de ce fichier ajoute APRES celui-ci
        heriterait d'une bibliotheque vide.
        """
        page, watch = biblio

        ids = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('.bibliotheque-card'))
                .slice(0, 2).map((c) => c.dataset.rowId)"""
        )
        assert len(ids) == 2

        # -- Selection multiple via checkboxes
        page.check(f'input[data-bibliotheque-select="{ids[0]}"]')
        page.check(f'input[data-bibliotheque-select="{ids[1]}"]')
        page.wait_for_selector(".bibliotheque-bulk-toolbar", timeout=10000)
        assert "2 films" in page.locator(".bibliotheque-bulk-count").inner_text()
        # Inspecteur droit : recap multi-selection + actions suggerees.
        # NB : comparaison casefold (le titre de section subit un
        # text-transform: uppercase cote CSS, inner_text() le restitue).
        panel_text = page.locator("[data-v5-right-panel-body]").inner_text()
        assert "2 films sélectionnés".casefold() in panel_text.casefold(), (
            f"Inspecteur multi-selection absent : {panel_text[:200]!r}"
        )
        _screenshot(page, "bibliotheque_bulk_toolbar.png")

        # -- Action SURE : Exporter -> modale de format, ANNULEE (pas d'ecriture)
        page.click('[data-bibliotheque-bulk="export"]')
        page.wait_for_selector("#dashModal .modal-card", timeout=10000)
        assert "Exporter" in page.locator("#dashModal .modal-header h3").inner_text()
        page.click('#dashModal [data-modal-action="0"]')  # bouton Annuler
        page.wait_for_selector("#dashModal", state="detached", timeout=10000)

        # -- Action DESTRUCTIVE : Marquer pour suppression -> modale, puis ANNULER
        page.click('[data-bibliotheque-bulk="delete"]')
        page.wait_for_selector("#dashDangerModal", timeout=10000)
        title = page.locator("#dashDangerModal .danger-modal-title").inner_text()
        assert "suppression de 2 film" in title, f"Titre modale danger inattendu : {title!r}"
        assert page.locator("#dashDangerModal .danger-modal-items li").count() >= 2
        # Anti-clic-reflexe : bouton Confirmer desactive pendant le countdown 3 s.
        assert page.locator("#dashDangerModal [data-danger-confirm]").is_disabled(), (
            "Bouton Confirmer actif immediatement (countdown 3s attendu)"
        )
        _screenshot(page, "bibliotheque_modale_suppression_annulee.png")
        page.click("#dashDangerModal [data-danger-cancel]")  # ANNULER — jamais confirmer
        page.wait_for_selector("#dashDangerModal", state="detached", timeout=10000)
        # Aucun marquage ne doit avoir eu lieu.
        assert not any("marqué" in t["text"] for t in _toasts(page)), (
            "Toast de marquage apres ANNULATION de la modale de suppression"
        )
        # Le verrou bulkInFlight doit etre relache apres annulation (fix 2026-06-07).
        assert page.locator('[data-bibliotheque-bulk="delete"]').is_enabled(), (
            "Boutons bulk restes disabled apres annulation de la modale"
        )

        # -- Action SURE (mais qui contamine le backend, cf docstring) :
        #    Re-scanner -> toast (succes attendu : "Re-scan lancé (job ...)")
        page.click('[data-bibliotheque-bulk="rescan"]')
        toast = _wait_toast(page, r"scan")
        assert "toast--error" not in toast["cls"], f"Re-scan bulk en erreur : {toast['text']!r}"

        # -- Action SURE : Analyser perceptuel (job async, en dernier car il
        #    disable perceptuel/rescan le temps du job)
        page.click('[data-bibliotheque-bulk="perceptual"]')
        _wait_toast(page, r"perceptuel")
        # Attendre la fin du job (fichiers mock inexistants -> echec rapide
        # attendu et TOLERE : le contrat teste est "reaction visible + recap
        # honnete", pas la reussite de l'analyse sans ffmpeg/fichiers).
        page.wait_for_function(
            """() => (window.__lotc_toasts || []).some((t) =>
                /perceptuelle (terminée|échouée|interrompue)/i.test(t.text))""",
            timeout=120000,
        )
        final = [
            t["text"]
            for t in _toasts(page)
            if re.search(r"perceptuelle (terminée|échouée|interrompue)", t["text"], re.IGNORECASE)
        ]
        assert final, "Pas de toast de fin d'analyse perceptuelle"
        assert not any("interrompue" in t for t in final), (
            f"Statut du job perceptuel indisponible (poll casse) : {final}"
        )
        page.wait_for_selector("[data-perc-progress-fill]", state="detached", timeout=15000)
        _wait_stable(page)

        # -- Annuler la selection : la toolbar disparait
        page.click('[data-bibliotheque-bulk="clear"]')
        page.wait_for_selector(".bibliotheque-bulk-toolbar", state="detached", timeout=10000)

        _screenshot(page, "bibliotheque_apres_bulk.png")
        _assert_console_clean(watch, "bulk actions")

        # Garde anti-regression : apres le refresh post-perceptuel, la grille
        # doit toujours contenir les 15 films. AUJOURD'HUI elle est VIDE :
        # run/rescan_rows_bulk lance JobRunner.start_job() qui insere un
        # NOUVEAU run en base ; _resolve_run_id (library_support.py L778,
        # list_runs(limit=1)) resout ensuite ce run parasite SANS plan ->
        # get_library_filtered retourne 0 film et la vue affiche "Aucun film
        # importé" + tous les compteurs a 0. Une fois corrige (ex : exclure
        # les runs de rescan de la resolution "latest"), ce xfail redeviendra
        # un pass.
        remaining = _cards_count(page)
        if remaining == 0 and page.locator(".bibliotheque-empty").count() == 1:
            pytest.xfail(
                "BUG Lot C (REPORTE) : le bulk 'Re-scanner' vide la "
                "bibliotheque — rescan_rows_bulk cree un run 'latest' sans "
                "plan que _resolve_run_id selectionne ensuite "
                "(library_actions_support.py L632 / library_support.py L778)"
            )
        assert remaining == _TOTAL_FILMS, "Grille alteree apres le cycle bulk"
