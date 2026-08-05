"""Lot C (verif totale 2026-07) — Sweep runtime Playwright de la vue #/parametres.

Test PERMANENT : navigation sous-sections, recherche, toggles (avec restauration
systematique — l'autosave 500 ms POST le settings ENTIER), boutons "Tester la
connexion" (erreur PROPRE attendue sur le serveur mock, jamais de crash),
reveal/masque du token REST (localhost), modale regen token (OUVRIR puis
ANNULER), modale reset (saisie CONFIRMER + countdown, puis ANNULER — on ne
confirme JAMAIS), aller-retour navigation x3 sans empilement.

Lancer :
  "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/e2e_dashboard/test_lotc_sweep_parametres.py -q

Source des actions : docs/internal/verif_totale_2026_07/matrices/m4_actions_ui.json
(14 actions vue "parametres" — les actions reseau lourdes auto_install/update/
reinstall des outils probe sont volontairement exclues : elles telechargent des
binaires ; leur modale de confirmation est couverte par la matrice M4 statique).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_CAPTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "internal" / "verif_totale_2026_07" / "captures_runtime"
)

# Les 10 categories (sous-sections) declarees dans PARAMETRES_GROUPS
# (web/dashboard/views/parametres.js).
_CATEGORIES = [
    "sources",
    "analyse",
    "nommage",
    "bibliotheque",
    "integrations",
    "notifications",
    "serveur",
    "apparence",
    "profils-qualite",
    "avance",
]

# Bruit console connu, tolere (liste blanche NOMINATIVE — tout le reste est un
# finding). Chaque entree est un fragment de message :
_CONSOLE_WHITELIST: List[str] = [
    # favicon absent du bundle dashboard -> 404 systematique, sans impact UI.
    "favicon",
]


def _is_whitelisted(text: str) -> bool:
    low = text.lower()
    return any(frag.lower() in low for frag in _CONSOLE_WHITELIST)


def _attach_error_watch(page) -> Dict[str, List[str]]:
    """Collecte console.error + pageerror (hors liste blanche)."""
    errors: Dict[str, List[str]] = {"console": [], "pageerror": []}

    def _on_console(msg):
        if msg.type == "error" and not _is_whitelisted(msg.text):
            errors["console"].append(msg.text)

    def _on_pageerror(err):
        if not _is_whitelisted(str(err)):
            errors["pageerror"].append(str(err))

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
    return errors


def _assert_no_errors(errors: Dict[str, List[str]], context: str) -> None:
    assert not errors["pageerror"], f"[{context}] pageerror: {errors['pageerror']}"
    assert not errors["console"], f"[{context}] console.error: {errors['console']}"


def _goto_parametres(page) -> None:
    """Navigue vers #/parametres et attend l'etat stable (sidebar rendue).

    FINDING Lot C (boot race, reporte — non corrige ici) : naviguer vers
    #/parametres PENDANT les fetchs de boot de l'accueil aborte le
    settings/get_settings dedup (core/nav-abort.js + dedup in-flight de
    core/api.js) -> la vue affiche le banner "Les paramètres n'ont pas pu se
    charger. signal is aborted without reason" + bouton Réessayer.
    Pour rester stable, le test attend d'abord le calme reseau, et garde un
    retry UNIQUE via le bouton Réessayer si la race se produit quand meme.
    """
    from playwright.sync_api import TimeoutError as PWTimeoutError

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeoutError:
        pass  # polling residuel : on tente la navigation quand meme
    page.evaluate("() => { window.location.hash = '#/parametres'; }")
    try:
        page.wait_for_selector(".parametres-view [data-category]", timeout=15000)
    except PWTimeoutError:
        retry = page.locator("[data-parametres-retry]")
        if retry.count() == 0:
            raise
        retry.click()  # boot race connue (voir docstring) — retry unique
        page.wait_for_selector(".parametres-view [data-category]", timeout=15000)
    # Settings charges => le panneau de la categorie active existe.
    page.wait_for_selector(".parametres-panel", timeout=10000)


def _click_category(page, category: str) -> None:
    page.click(f'[data-category="{category}"]')
    page.wait_for_selector(f'[data-category="{category}"].is-active', timeout=10000)
    page.wait_for_selector(".parametres-panel", timeout=10000)


def _api_get_settings(e2e_server: Dict[str, Any]) -> Dict[str, Any]:
    """GET settings via l'API REST (verite backend, pour verifier la restauration)."""
    req = urllib.request.Request(
        e2e_server["url"] + "/api/settings/get_settings",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {e2e_server['token']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("data") or payload


# ---------------------------------------------------------------------------
# 1) Navigation sous-sections + screenshot + 0 erreur console
# ---------------------------------------------------------------------------


class TestParametresSweep:
    """Sweep runtime de la vue Parametres (Lot C)."""

    def test_navigation_sous_sections(self, dashboard_page, e2e_server):
        """Chaque categorie de la sidebar s'ouvre sans erreur console."""
        errors = _attach_error_watch(dashboard_page)
        _goto_parametres(dashboard_page)

        for cat in _CATEGORIES:
            _click_category(dashboard_page, cat)
            # Reaction visible : le panneau affiche un titre non vide.
            title = dashboard_page.inner_text(".parametres-panel-title")
            assert title.strip(), f"Panneau vide pour la categorie {cat}"

        # Les panneaux 'analyse' (probe tools) et 'profils-qualite' chargent en
        # asynchrone -> petite marge avant le bilan console.
        dashboard_page.wait_for_timeout(1500)

        # Screenshot de la vue (exigence Lot C).
        _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        _click_category(dashboard_page, "integrations")
        dashboard_page.screenshot(path=str(_CAPTURES_DIR / "parametres.png"), full_page=True)

        _assert_no_errors(errors, "navigation sous-sections")

    # -----------------------------------------------------------------------
    # 2) Recherche de parametres
    # -----------------------------------------------------------------------

    def test_recherche_parametres(self, dashboard_page):
        """La recherche filtre les categories et surligne les correspondances."""
        errors = _attach_error_watch(dashboard_page)
        _goto_parametres(dashboard_page)

        # Requete qui matche (jellyfin -> categorie Integrations).
        dashboard_page.fill("[data-parametres-search]", "jellyfin")
        dashboard_page.wait_for_selector("mark.parametres-search-highlight", timeout=5000)
        marks = dashboard_page.locator("mark.parametres-search-highlight").count()
        assert marks > 0, "Aucun surlignage pour la recherche 'jellyfin'"

        # Requete sans resultat -> message vide explicite.
        dashboard_page.fill("[data-parametres-search]", "zzzzaucunresultat")
        dashboard_page.wait_for_timeout(400)  # debounce 150ms + re-render
        empty_msg = dashboard_page.evaluate(
            """() => {
                const t = document.querySelector('.parametres-view')?.innerText || '';
                return t.includes('Aucun') || t.includes('Aucune');
            }"""
        )
        assert empty_msg, "Pas de message 'Aucun resultat' pour une recherche vide"

        # Effacer -> les 10 categories reviennent.
        dashboard_page.fill("[data-parametres-search]", "")
        dashboard_page.wait_for_timeout(400)
        count = dashboard_page.locator("[data-category]").count()
        assert count == len(_CATEGORIES), (
            f"{count} categories apres effacement de la recherche (attendu {len(_CATEGORIES)})"
        )

        _assert_no_errors(errors, "recherche")

    # -----------------------------------------------------------------------
    # 3) Toggles : modifier PUIS RESTAURER (autosave 500ms POST tout le settings)
    # -----------------------------------------------------------------------

    def test_toggle_puis_restauration(self, dashboard_page, e2e_server):
        """Toggle 'Mode expert' + un toggle de settings, puis retour a l'initial.

        L'autosave debounce 500 ms et POST l'objet settings ENTIER : chaque
        valeur touchee est restauree et la restauration est verifiee cote
        backend via get_settings.
        """
        errors = _attach_error_watch(dashboard_page)
        before = _api_get_settings(e2e_server)
        _goto_parametres(dashboard_page)

        try:
            # --- Mode expert (header) : ON -> classe is-expert, puis OFF.
            expert_initial = dashboard_page.is_checked("[data-parametres-expert]")
            has_expert_before = dashboard_page.evaluate("() => !!document.querySelector('.is-expert')")
            dashboard_page.click("[data-parametres-expert]")
            dashboard_page.wait_for_timeout(200)
            has_expert_after = dashboard_page.evaluate("() => !!document.querySelector('.is-expert')")
            assert has_expert_after != has_expert_before, "Le toggle Mode expert n'a pas bascule la classe is-expert"
            # Reaction visible : indicateur '✓ Sauvegardé' apres l'autosave.
            dashboard_page.wait_for_function(
                """() => (document.querySelector('[data-parametres-saved-indicator]')
                          ?.textContent || '').includes('Sauvegard')""",
                timeout=8000,
            )
            # Restauration.
            dashboard_page.click("[data-parametres-expert]")
            dashboard_page.wait_for_timeout(900)  # laisse partir l'autosave

            # --- Toggle de settings : jellyfin_refresh_on_apply (Integrations).
            _click_category(dashboard_page, "integrations")
            sel = "#prm_jellyfin_refresh_on_apply"
            dashboard_page.wait_for_selector(sel, state="attached", timeout=8000)
            initial = dashboard_page.is_checked(sel)
            dashboard_page.locator(sel).click(force=True)  # input dans un <label>
            dashboard_page.wait_for_timeout(200)
            assert dashboard_page.is_checked(sel) != initial, "Le toggle n'a pas bascule"
            dashboard_page.wait_for_timeout(900)  # autosave de la valeur modifiee
            # Restauration a la valeur initiale.
            dashboard_page.locator(sel).click(force=True)
            dashboard_page.wait_for_timeout(900)
            assert dashboard_page.is_checked(sel) == initial, "Toggle non restaure"
        finally:
            # Filet de securite : re-verifier cote backend que rien n'a derive.
            dashboard_page.wait_for_timeout(800)

        after = _api_get_settings(e2e_server)
        for key in ("expert_mode", "jellyfin_refresh_on_apply"):
            assert bool(after.get(key)) == bool(before.get(key)), (
                f"settings[{key}] non restaure : avant={before.get(key)!r} apres={after.get(key)!r}"
            )
        _assert_no_errors(errors, "toggles")

    # -----------------------------------------------------------------------
    # 4) Boutons "Tester la connexion" : erreur PROPRE, pas de crash
    # -----------------------------------------------------------------------

    def test_boutons_tester_connexion(self, dashboard_page):
        """TMDb / Jellyfin / Plex / Radarr : reponse d'erreur propre inline.

        Sur le serveur mock : cle TMDb vide, URLs Plex/Radarr vides (erreur de
        validation immediate), Jellyfin pointe sur un hote inexistant (erreur
        reseau propre). Aucun crash JS tolere.
        """
        errors = _attach_error_watch(dashboard_page)
        _goto_parametres(dashboard_page)
        _click_category(dashboard_page, "integrations")

        cases = [
            ("integrations/test_tmdb_key", "tmdb_api_key"),
            ("integrations/test_plex_connection", "plex_token"),
            ("integrations/test_radarr_connection", "radarr_api_key"),
            ("integrations/test_jellyfin_connection", "jellyfin_api_key"),
        ]
        for method, field_key in cases:
            btn = f'[data-test-method="{method}"]'
            dashboard_page.wait_for_selector(btn, state="attached", timeout=8000)
            dashboard_page.locator(btn).click()
            # Reaction visible : pastille resultat non vide, prefixee ✗ (echec
            # propre attendu : aucune integration reelle sur le serveur mock).
            res_sel = f'[data-test-result-for="{field_key}"]'
            dashboard_page.wait_for_function(
                """(sel) => {
                    const el = document.querySelector(sel);
                    const t = (el?.textContent || '').trim();
                    return t !== '' && t !== 'Test…';
                }""",
                arg=res_sel,
                timeout=30000,
            )
            text = dashboard_page.inner_text(res_sel).strip()
            assert text.startswith("✗"), f"{method} : resultat inattendu sur serveur mock : {text!r}"

        # OMDb : le resultat est reporte dans le panneau d'etat dedie.
        omdb_btn = '[data-test-method="integrations/test_omdb_connection"]'
        dashboard_page.wait_for_selector(omdb_btn, state="attached", timeout=8000)
        dashboard_page.locator(omdb_btn).click()
        dashboard_page.wait_for_timeout(1500)
        assert dashboard_page.locator("[data-omdb-status]").count() == 1, (
            "Panneau de statut OMDb absent apres le test de connexion"
        )

        _assert_no_errors(errors, "tester connexion")

    # -----------------------------------------------------------------------
    # 5) Reveal token REST (localhost) + copie non testee (clipboard headless)
    # -----------------------------------------------------------------------

    def test_reveal_token_rest(self, dashboard_page, e2e_server):
        """Le bouton 👁 revele le token en clair puis le remasque."""
        errors = _attach_error_watch(dashboard_page)
        _goto_parametres(dashboard_page)
        _click_category(dashboard_page, "serveur")

        input_sel = "#prm_rest_api_token"
        toggle_sel = '[data-api-key-toggle="prm_rest_api_token"]'
        dashboard_page.wait_for_selector(input_sel, state="attached", timeout=8000)

        assert dashboard_page.get_attribute(input_sel, "type") == "password", (
            "Le token REST devrait etre masque par defaut"
        )
        dashboard_page.locator(toggle_sel).click()
        # LOTC-B3 (corrige) : le bouton 👁 resout d'abord le VRAI Bearer via
        # settings/reveal_rest_token (appel async, localhost only) puis bascule
        # input.type -> on attend la bascule au lieu d'asserter immediatement.
        dashboard_page.wait_for_function(
            "(sel) => document.querySelector(sel)?.type === 'text'",
            arg=input_sel,
            timeout=5000,
        )
        value = dashboard_page.input_value(input_sel)
        assert value == e2e_server["token"], (
            f"Le bouton 👁 doit reveler le VRAI Bearer, pas le masque SEC-H3 : {value!r}"
        )
        # Re-masquer : type password ET masque restaure (le vrai token ne
        # reste pas dans le DOM).
        dashboard_page.locator(toggle_sel).click()
        dashboard_page.wait_for_function(
            "(sel) => document.querySelector(sel)?.type === 'password'",
            arg=input_sel,
            timeout=5000,
        )
        assert dashboard_page.input_value(input_sel) == "•" * 8, "Le masque SEC-H3 doit etre restaure apres re-masquage"

        _assert_no_errors(errors, "reveal token")

    # -----------------------------------------------------------------------
    # 6) Regen token = action dangereuse : modale OUVERTE puis ANNULEE
    # -----------------------------------------------------------------------

    def test_regen_token_modale_annulee(self, dashboard_page, e2e_server):
        """Le bouton 🔄 ouvre dangerConfirmModal ; on ANNULE (jamais confirmer)."""
        errors = _attach_error_watch(dashboard_page)
        _goto_parametres(dashboard_page)
        _click_category(dashboard_page, "serveur")

        dashboard_page.wait_for_selector("[data-rest-token-regen]", state="attached", timeout=8000)
        # Valeur affichee avant (masque SEC-H3 '••••••••' — voir finding reveal).
        token_before = dashboard_page.input_value("#prm_rest_api_token")
        dashboard_page.locator("[data-rest-token-regen]").click()
        # La modale de confirmation DOIT apparaitre (action dangereuse).
        dashboard_page.wait_for_selector("#dashDangerModal", timeout=5000)
        title = dashboard_page.inner_text("#dashDangerModal .danger-modal-title")
        assert "token" in title.lower(), f"Titre de modale inattendu : {title!r}"
        # ANNULER — ne jamais confirmer.
        dashboard_page.click("#dashDangerModal [data-danger-cancel]")
        dashboard_page.wait_for_selector("#dashDangerModal", state="detached", timeout=5000)
        # Le champ token n'a pas change apres l'annulation.
        assert dashboard_page.input_value("#prm_rest_api_token") == token_before, (
            "Le token a change alors que la regen a ete ANNULEE"
        )
        # Et cote backend, le vrai token est intact : l'appel API suivant
        # (Bearer = token initial) doit toujours passer.
        settings = _api_get_settings(e2e_server)
        assert isinstance(settings, dict) and settings, (
            "get_settings ne repond plus apres la regen annulee (token invalide ?)"
        )

        _assert_no_errors(errors, "regen token (annule)")

    # -----------------------------------------------------------------------
    # 7) Modale reset : saisie CONFIRMER + countdown, puis ANNULER
    # -----------------------------------------------------------------------

    def test_reset_modale_confirmer_countdown_puis_annuler(self, dashboard_page, e2e_server):
        """OUVRIR la modale reset, verifier les garde-fous, ANNULER."""
        errors = _attach_error_watch(dashboard_page)
        before = _api_get_settings(e2e_server)
        _goto_parametres(dashboard_page)

        dashboard_page.click("[data-parametres-action='reset']")
        dashboard_page.wait_for_selector("#parametresResetModal", timeout=5000)

        modal = "#parametresResetModal"
        confirm_btn = f"{modal} [data-parametres-reset-confirm]"
        # 12 scopes proposes.
        scopes = dashboard_page.locator(f"{modal} input[name='parametres-reset-scope']").count()
        assert scopes == 12, f"{scopes} scopes dans la modale reset (attendu 12)"
        # Scope initial = 'all' -> countdown 3s affiche + bouton desactive.
        assert dashboard_page.is_disabled(confirm_btn), "Confirmer devrait etre desactive a l'ouverture (countdown)"
        countdown_txt = dashboard_page.inner_text(f"{modal} [data-parametres-reset-countdown]").strip()
        assert countdown_txt.startswith("("), f"Countdown absent a l'ouverture (scope=all) : {countdown_txt!r}"
        # Saisie incorrecte -> toujours desactive meme apres le countdown.
        dashboard_page.fill(f"{modal} [data-parametres-reset-input]", "confirmer")
        dashboard_page.wait_for_timeout(3500)  # laisser expirer le countdown 3s
        assert dashboard_page.is_disabled(confirm_btn), "Confirmer actif sans la saisie exacte 'CONFIRMER'"
        # Saisie exacte -> le bouton devient actif (countdown deja expire)…
        dashboard_page.fill(f"{modal} [data-parametres-reset-input]", "CONFIRMER")
        dashboard_page.wait_for_function(
            """() => !document.querySelector(
                '#parametresResetModal [data-parametres-reset-confirm]')?.disabled""",
            timeout=5000,
        )
        # … mais on n'appuie JAMAIS dessus : ANNULER.
        dashboard_page.click(f"{modal} [data-parametres-reset-cancel]")
        dashboard_page.wait_for_selector(modal, state="detached", timeout=5000)

        # Aucun reset ne doit etre parti au backend.
        after = _api_get_settings(e2e_server)
        assert after.get("rest_api_token") == before.get("rest_api_token"), (
            "Les settings ont change apres une modale reset ANNULEE"
        )
        assert after.get("jellyfin_url") == before.get("jellyfin_url"), (
            "Les settings ont change apres une modale reset ANNULEE"
        )

        # Reouverture + fermeture Escape (2e chemin d'annulation).
        dashboard_page.click("[data-parametres-action='reset']")
        dashboard_page.wait_for_selector(modal, timeout=5000)
        dashboard_page.keyboard.press("Escape")
        dashboard_page.wait_for_selector(modal, state="detached", timeout=5000)

        _assert_no_errors(errors, "modale reset (annulee)")

    # -----------------------------------------------------------------------
    # 8) Outils probe : re-detection (action sure de la matrice M4)
    # -----------------------------------------------------------------------

    def test_probe_tools_recheck(self, dashboard_page):
        """Action m4 'data-probe-tools-action=recheck' : re-detection sans crash."""
        errors = _attach_error_watch(dashboard_page)
        _goto_parametres(dashboard_page)
        _click_category(dashboard_page, "analyse")

        # Le panneau outils charge en asynchrone (runtime/get_probe_tools_status).
        dashboard_page.wait_for_selector(".parametres-field--probe-tools", state="attached", timeout=10000)
        dashboard_page.wait_for_function(
            """() => {
                const el = document.querySelector('.parametres-field--probe-tools');
                const t = el?.textContent || '';
                return !t.includes('Vérification des outils externes');
            }""",
            timeout=30000,
        )
        btn = dashboard_page.locator('[data-probe-tools-action="recheck"]').first
        if btn.count() == 0:
            # Table deja rendue sans bouton recheck = etat non prevu -> echec.
            raise AssertionError("Bouton recheck absent du panneau outils")
        btn.click()
        # Reaction visible : le panneau repasse en 'Vérification…' puis se stabilise.
        dashboard_page.wait_for_function(
            """() => {
                const el = document.querySelector('.parametres-field--probe-tools');
                const t = el?.textContent || '';
                return !t.includes('Vérification des outils externes');
            }""",
            timeout=30000,
        )
        # La table (ou le placeholder de statut) est bien re-rendue.
        assert dashboard_page.locator(".parametres-field--probe-tools").count() == 1

        _assert_no_errors(errors, "probe tools recheck")

    # -----------------------------------------------------------------------
    # 9) Aller-retour navigation x3 : pas d'erreur, pas d'empilement
    # -----------------------------------------------------------------------

    def test_aller_retour_navigation_x3(self, dashboard_page):
        """3 allers-retours #/parametres <-> #/aide : DOM unique, 0 erreur."""
        errors = _attach_error_watch(dashboard_page)

        for i in range(3):
            _goto_parametres(dashboard_page)
            # Pas d'empilement : une seule instance de la vue et de ses ancres.
            assert dashboard_page.locator(".parametres-view").count() == 1, f"Passe {i + 1} : .parametres-view empilee"
            assert dashboard_page.locator("[data-parametres-search]").count() == 1, (
                f"Passe {i + 1} : champ recherche duplique"
            )
            assert dashboard_page.locator("[data-parametres-action='reset']").count() == 1, (
                f"Passe {i + 1} : bouton reset duplique"
            )

            dashboard_page.evaluate("() => { window.location.hash = '#/aide'; }")
            # Le router bascule la classe .active entre sections ; unmountParametres
            # ne vide pas le DOM (comportement nominal), donc on verifie :
            # aide active, parametres inactive, et JAMAIS plus d'une instance.
            dashboard_page.wait_for_function(
                """() => {
                    const v = document.getElementById('view-help');
                    return !!v && v.classList.contains('active')
                           && v.childElementCount > 0;
                }""",
                timeout=10000,
            )
            settings_active = dashboard_page.evaluate(
                "() => document.getElementById('view-settings')?.classList.contains('active')"
            )
            assert not settings_active, f"Passe {i + 1} : view-settings encore active sur #/aide"
            assert dashboard_page.locator(".parametres-view").count() <= 1, (
                f"Passe {i + 1} : .parametres-view empilee apres depart"
            )

        dashboard_page.wait_for_timeout(800)
        _assert_no_errors(errors, "aller-retour x3")
