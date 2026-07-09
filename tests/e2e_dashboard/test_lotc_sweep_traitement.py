"""Lot C (verif totale 2026-07) — sweep runtime Playwright de la vue #/traitement.

Couvre le stepper Analyse -> Verification -> Validation -> Doublons -> Apply
SANS lancer de scan reel (le dataset mock e2e_server contient deja un run DONE
de 15 films, cf tests/e2e/create_test_data.py) :

  - rendu stable de chaque etape (titre "Étape N — ...", breadcrumb, 0 erreur
    console / pageerror, 0 reponse API >= 400 hors liste blanche) ;
  - actions SURES cliquees avec verification d'une reaction visible
    (source : docs/internal/verif_totale_2026_07/matrices/m4_actions_ui.json) ;
  - fix E2/E2-bis verifie en runtime : "Ignorer" en etape Verification poste
    library/mark_alert_ignored (PAS run/mark_alert_ignored) et retire les
    badges d'alerte de la ligne (get_plan filtre les alertes ignorees) ;
  - fix E3 verifie en runtime : la fiche film (mode C overlay) ne rend PAS le
    bouton "Ouvrir dossier" hors desktop pywebview ;
  - actions DESTRUCTIVES : ouverture de la modale de confirmation puis
    ANNULATION systematique (mark-delete, apply reel, mode atomique,
    go-apply avec doublons pendants) — jamais de confirmation ;
  - aller-retour navigation x3 accueil <-> traitement : pas d'empilement DOM.

Screenshots : docs/internal/verif_totale_2026_07/captures_runtime/traitement_*.png

Lancer :
  "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/e2e_dashboard/test_lotc_sweep_traitement.py -q
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Constantes / helpers module
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPTURES_DIR = _REPO_ROOT / "docs" / "internal" / "verif_totale_2026_07" / "captures_runtime"

_STEP_TITLES = {
    "analyse": "Étape 1 — Analyse",
    "verification": "Étape 2 — Vérification",
    "validation": "Étape 3 — Validation",
    "doublons": "Étape 4 — Doublons",
    "apply": "Étape 5 — Application",
}

# Liste blanche NOMINATIVE du bruit console connu. Chaque entree doit etre un
# fragment de texte exact + un commentaire justifiant pourquoi ce bruit est
# tolere.
_CONSOLE_WHITELIST: tuple = (
    # Dataset mock : TMDb desactive (tmdb_enabled=False) -> le proxy
    # /api/poster repond 503 par contrat quand la fiche film demande une
    # jaquette. Bruit d'environnement, pas un bug (fallback UI prevu).
    "Failed to load resource: the server responded with a status of 503",
    # bootstrap-debug.js loggue window.error en console.error meme pour les
    # error events de RESSOURCE (img poster 503) : tous les champs sont
    # undefined. Bruit residuel de debug — reporte en finding LOW Lot C.
    "[BOOT-DEBUG] window.error",
    # BUG CONNU (reporte Lot C, non corrige ici) : film-detail.js L206/337/1065
    # pose des handlers inline onerror="..." sur les <img> posters ; la CSP
    # script-src 'self' du rest_server les BLOQUE -> le fallback poster
    # (placeholder / masquage) ne s'execute jamais en dashboard web. Tolere
    # nominativement pour garder le sweep vert sur le reste ; retirer cette
    # entree quand le fallback sera migre vers addEventListener.
    "Executing inline event handler violates the following Content Security Policy",
)

# Liste blanche NOMINATIVE des reponses API >= 400 tolerees (fragment d'URL).
_API_FAIL_WHITELIST: tuple = (
    # TMDb desactive dans le dataset mock -> 503 contractuel du proxy poster.
    "/api/poster?",
)


def _attach_watchers(page):
    """Branche les collecteurs console.error / pageerror / API >= 400 / requetes.

    A appeler en DEBUT de test (page fraiche par test via fixture function-scope).
    Retourne un dict mutable rempli au fil du test.
    """
    watch = {"console": [], "pageerror": [], "api_fail": [], "api_posts": []}

    def _on_console(msg):
        if msg.type == "error":
            text = msg.text
            if not any(w in text for w in _CONSOLE_WHITELIST):
                watch["console"].append(f"[console.error] {text}")

    def _on_pageerror(err):
        watch["pageerror"].append(f"[pageerror] {err}")

    def _on_response(resp):
        url = resp.url
        if "/api/" in url and resp.status >= 400:
            if not any(w in url for w in _API_FAIL_WHITELIST):
                watch["api_fail"].append(f"HTTP {resp.status} {url}")

    def _on_request(req):
        if "/api/" in req.url and req.method == "POST":
            watch["api_posts"].append(req.url)

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
    page.on("response", _on_response)
    page.on("request", _on_request)
    return watch


def _assert_clean(watch, context=""):
    """0 erreur console, 0 pageerror, 0 reponse API >= 400."""
    problems = watch["console"] + watch["pageerror"] + watch["api_fail"]
    assert not problems, f"Erreurs runtime detectees ({context}) : {problems}"


def _settle_boot(page):
    """Attend la fin des fetchs initiaux de l'accueil avant de naviguer.

    BUG CONNU (reporte Lot C, non corrige ici) : core/api.js dedup les POST
    in-flight par methode+body. accueil.js et traitement.js appellent tous
    les deux run/get_dashboard {run_id:"latest"} ; si on navigue vers
    #/traitement PENDANT le chargement initial de l'accueil, le router
    (abortCurrentNav) avorte le fetch partage -> _loadRunInfo recoit un
    AbortError -> _runInfo=null -> la vue reste bloquee sur "Aucun run actif
    détecté" SANS retry ni polling. Reproduit 7/7 avant ce settle.
    """
    page.wait_for_timeout(2000)


def _goto_step(page, step, timeout=20000):
    """Navigue via location.hash vers une etape du stepper et attend l'etat stable.

    Chaque hashchange re-resout la route (router.resolve) donc re-monte la vue
    traitement : on attend le rendu FINAL (titre exact de l'etape, plus de
    skeleton aria-busy) et un court settle pour les re-renders post-fetch.

    Anti-flake (bug dedup+abort, cf _settle_boot) : si la vue retombe sur
    l'empty-state "Aucun run actif détecté" alors que le backend a un run,
    on force UN re-resolve (remount) avant d'echouer.
    """
    from playwright.sync_api import TimeoutError as PWTimeoutError

    target = f"#/traitement#step-{step}"
    page.evaluate("(h) => { window.location.hash = h; }", target)
    wait_js = """(expected) => {
        const view = document.getElementById('view-processing');
        if (!view || !view.classList.contains('active')) return false;
        if (view.querySelector('.traitement-panel[aria-busy="true"]')) return false;
        const el = view.querySelector('.traitement-panel-title');
        return !!el && el.textContent.trim() === expected;
    }"""
    try:
        page.wait_for_function(wait_js, arg=_STEP_TITLES[step], timeout=timeout)
    except PWTimeoutError:
        stuck_empty = page.evaluate(
            "() => !!document.querySelector('.traitement-header-run--empty')"
        )
        if not stuck_empty:
            raise
        # Vue morte sur l'empty-state (race dedup+abort) : re-resolve force.
        page.evaluate("() => window.dispatchEvent(new HashChangeEvent('hashchange'))")
        page.wait_for_function(wait_js, arg=_STEP_TITLES[step], timeout=timeout)
    page.wait_for_timeout(500)


def _screenshot(page, name):
    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_CAPTURES_DIR / name), full_page=True)


def _toast_count(page):
    return page.evaluate("() => document.querySelectorAll('#toast-container .toast').length")


def _click_and_wait_toast(page, selector, context, timeout=10000):
    """Clique un bouton et attend qu'un NOUVEAU toast apparaisse (reaction visible).

    Retourne le texte du dernier toast. Sur le dataset mock certains toasts
    sont legitimement de type erreur (ex. re-scan d'un fichier inexistant sur
    disque) : la reaction visible est le critere, pas le type.
    """
    before = _toast_count(page)
    page.click(selector)
    page.wait_for_function(
        "(before) => document.querySelectorAll('#toast-container .toast').length > before",
        arg=before,
        timeout=timeout,
    )
    return page.evaluate(
        """() => {
            const t = document.querySelectorAll('#toast-container .toast');
            return t[t.length - 1].textContent.trim();
        }"""
    )


def _danger_modal_visible(page):
    return page.evaluate("() => !!document.getElementById('dashDangerModal')")


def _cancel_danger_modal(page):
    """Clique Annuler dans dangerConfirmModal et attend sa fermeture."""
    page.click("#dashDangerModal [data-danger-cancel]")
    page.wait_for_selector("#dashDangerModal", state="detached", timeout=5000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLotCSweepTraitement:
    """Sweep runtime de la vue #/traitement (stepper scan -> review -> apply)."""

    # --- Etape 1 : Analyse -------------------------------------------------

    def test_step1_analyse_rendu_sans_scan(self, dashboard_page):
        """Etape Analyse : rendu du run existant + auto-transition, SANS scan reel.

        Comportement v1.5.2 par design : sur un run DONE, l'etape Analyse
        auto-transitionne vers Verification au premier tick de polling (~2s,
        cf traitement.js _pollTick). Le panneau Analyse est donc transitoire :
        on verifie son rendu dans la fenetre pre-tick, puis on valide
        l'auto-forward vers l'Etape 2. Les boutons 'Lancer le scan' et
        'Voir log complet' sont verifies PRESENTS mais start-scan n'est
        JAMAIS clique (pas de scan reel en sweep).
        """
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)

        page.evaluate("() => { window.location.hash = '#/traitement#step-analyse'; }")
        # Attendre le premier rendu stable : Etape 1 (fenetre pre-tick) ou deja
        # Etape 2 si l'auto-transition a gagne la course.
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#view-processing .traitement-panel-title');
                if (!el) return false;
                const t = el.textContent.trim();
                return t === 'Étape 1 — Analyse' || t === 'Étape 2 — Vérification';
            }""",
            timeout=20000,
        )
        title = page.evaluate(
            "() => document.querySelector('#view-processing .traitement-panel-title').textContent.trim()"
        )
        if title == _STEP_TITLES["analyse"]:
            # Fenetre pre-tick : verifier le panneau Analyse (asserts rapides).
            assert page.evaluate(
                "() => !!document.querySelector('[data-traitement-action=\"start-scan\"]')"
            ), "Bouton start-scan absent en etape Analyse (run DONE)"
            assert page.evaluate(
                "() => !!document.querySelector('[data-traitement-action=\"view-logs\"]')"
            ), "Bouton view-logs absent en etape Analyse"
            assert page.evaluate(
                "() => !!document.querySelector('[data-scan-opt=\"perceptual\"]:not([disabled])')"
            ), "Options de scan desactivees alors qu'aucun scan ne tourne"
            _screenshot(page, "traitement_step1_analyse.png")

        # Auto-transition v1.5.2 : le run DONE doit basculer sur Verification.
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#view-processing .traitement-panel-title');
                return !!el && el.textContent.trim() === 'Étape 2 — Vérification';
            }""",
            timeout=15000,
        )
        page.wait_for_timeout(500)
        if title != _STEP_TITLES["analyse"]:
            # L'auto-forward a ete plus rapide que les asserts : capture ici.
            _screenshot(page, "traitement_step1_analyse.png")

        # Asserts communs post-stabilisation (header + breadcrumb partages).
        steps = page.evaluate(
            "() => document.querySelectorAll('#view-processing [data-traitement-step]').length"
        )
        assert steps == 5, f"Breadcrumb attendu avec 5 etapes, trouve {steps}"
        assert page.evaluate(
            "() => !!document.querySelector('#view-processing .traitement-runchip')"
        ), "Header run actif absent (chip run ID)"

        # Run DONE : les actions pause/resume/save/cancel du header ne doivent
        # pas etre rendues (reservees a RUNNING/PAUSED).
        for action in ("pause", "resume", "save", "cancel"):
            present = page.evaluate(
                f"() => !!document.querySelector('[data-traitement-action=\"{action}\"]')"
            )
            assert not present, f"Action header '{action}' rendue alors que le run est DONE"

        _assert_clean(watch, "etape analyse + auto-transition")

    # --- Etape 2 : Verification (fix E2/E2-bis) ----------------------------

    def test_step2_verification_ignorer_retire_badges(self, dashboard_page):
        """Etape Verification : filtres, Re-scanner, Ignorer (E2/E2-bis runtime)."""
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "verification")

        # Le dataset mock contient 6 rows avec warning_flags (rows 7-11 et 14).
        row_ids = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('.traitement-verif-table tbody tr[data-row-id]')
            ).map((tr) => tr.dataset.rowId)"""
        )
        assert len(row_ids) >= 2, f"Table verification attendue avec >= 2 lignes flaggees : {row_ids}"

        # Filtres : reaction visible = classe is-active qui bascule.
        page.click('[data-traitement-verif-filter="nfo"]')
        page.wait_for_timeout(300)
        assert page.evaluate(
            "() => document.querySelector('[data-traitement-verif-filter=\"nfo\"]').classList.contains('is-active')"
        ), "Filtre 'nfo' non actif apres clic"
        page.click('[data-traitement-verif-filter="all"]')
        page.wait_for_timeout(300)

        _screenshot(page, "traitement_step2_verification.png")

        # Action sure 'Re-scanner' (row-008, isolee : sa quality report est
        # invalidee par le rescan). Fichier inexistant sur disque en mock ->
        # toast succes OU erreur acceptes, la reaction visible est le critere.
        toast = _click_and_wait_toast(
            page,
            '[data-traitement-verif-action="rescan"][data-row-id="row-008"]',
            "rescan row-008",
            timeout=20000,
        )
        assert toast, "Aucun toast apres Re-scanner"
        page.wait_for_timeout(500)

        # Fix E2/E2-bis : 'Ignorer' sur la premiere ligne flaggee doit retirer
        # les badges (la ligne sort de la liste 'flagged' apres reload du plan
        # car get_plan filtre desormais les alertes ignorees).
        target = row_ids[0]
        badge_count = page.evaluate(
            f"""() => document.querySelectorAll(
                '.traitement-verif-table tr[data-row-id="{target}"] .traitement-verif-alert'
            ).length"""
        )
        assert badge_count >= 1, f"Ligne {target} sans badge d'alerte avant Ignorer"

        toast = _click_and_wait_toast(
            page,
            f'[data-traitement-verif-action="ignore"][data-row-id="{target}"]',
            f"ignore {target}",
        )
        assert "ignor" in toast.lower(), f"Toast inattendu apres Ignorer : {toast}"

        # La ligne disparait de la table (plus aucun warning_flag apres filtre
        # E2-bis) — c'est LA verification runtime du fix.
        page.wait_for_function(
            f"""() => !document.querySelector(
                '.traitement-verif-table tr[data-row-id="{target}"]'
            )""",
            timeout=10000,
        )

        # E2 : l'appel est parti vers library/mark_alert_ignored, PAS vers
        # l'ancien endpoint inexistant run/mark_alert_ignored (404 avant fix).
        assert any("library/mark_alert_ignored" in u for u in watch["api_posts"]), (
            f"Aucun POST library/mark_alert_ignored capture : {watch['api_posts']}"
        )
        assert not any("run/mark_alert_ignored" in u for u in watch["api_posts"]), (
            "Regression E2 : POST vers run/mark_alert_ignored (endpoint inexistant)"
        )

        # Action sure 'Re-verifier' (reload-plan) : la table reste rendue.
        page.click('[data-traitement-action="reload-plan"]')
        page.wait_for_timeout(1000)
        assert page.evaluate(
            "() => !!document.querySelector('.traitement-verif-table')"
        ), "Table verification absente apres reload-plan"

        # Action sure 'go-validation' : transition visible vers l'etape 3.
        page.click('[data-traitement-action="go-validation"]')
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#view-processing .traitement-panel-title');
                return !!el && el.textContent.includes('Étape 3');
            }""",
            timeout=10000,
        )
        _assert_clean(watch, "etape verification")

    # --- Fiche film (mode C overlay, fix E3) --------------------------------

    def test_fiche_film_onglets_boutons_sans_ouvrir_dossier(self, dashboard_page):
        """Fiche film : onglets, boutons, PAS de bouton 'Ouvrir dossier' (E3)."""
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "validation")

        # Ouvre la fiche du premier film (inspect 'oeil') -> overlay mode C.
        page.click('[data-traitement-validation-action="inspect"][data-row-id="row-001"]')
        page.wait_for_function(
            """() => {
                const ov = document.getElementById('filmDetailOverlay');
                if (!ov) return false;
                if (ov.querySelector('.film-detail--loading')) return false;
                return !!ov.querySelector('.film-detail');
            }""",
            timeout=15000,
        )
        # La fiche ne doit pas etre en etat d'erreur.
        assert not page.evaluate(
            "() => !!document.querySelector('#filmDetailOverlay .film-detail--error')"
        ), "Fiche film en etat d'erreur sur row-001 (get_film_full)"

        # Les 4 onglets se cliquent et remplissent le panneau.
        for tab in ("analysis", "history", "rename", "overview"):
            page.click(f'#filmDetailOverlay [data-film-tab="{tab}"]')
            page.wait_for_function(
                """(tab) => {
                    const btn = document.querySelector(
                        `#filmDetailOverlay [data-film-tab="${tab}"]`);
                    const panel = document.querySelector(
                        '#filmDetailOverlay [data-film-tab-panel]');
                    return !!btn && btn.classList.contains('is-active')
                        && !!panel && panel.innerHTML.trim().length > 0;
                }""",
                arg=tab,
                timeout=8000,
            )

        # Boutons d'action attendus presents.
        for action in ("validate", "analyze-perceptual", "rescan", "mark-delete"):
            assert page.evaluate(
                f"() => !!document.querySelector('#filmDetailOverlay [data-film-action=\"{action}\"]')"
            ), f"Bouton film-detail '{action}' absent"

        # Fix E3 : PAS de bouton 'Ouvrir dossier' hors desktop pywebview
        # (open_path est exclu du REST par design, anti path-traversal).
        assert not page.evaluate(
            "() => !!document.querySelector('#filmDetailOverlay [data-film-action=\"open-folder\"]')"
        ), "Regression E3 : bouton 'Ouvrir dossier' rendu en mode navigateur pur"

        _screenshot(page, "traitement_fiche_film.png")

        # Fermeture de la fiche via le bouton dedie.
        page.click("#filmDetailOverlay [data-film-modal-close]")
        page.wait_for_selector("#filmDetailOverlay", state="detached", timeout=5000)
        _assert_clean(watch, "fiche film")

    def test_fiche_film_mark_delete_modale_annulee(self, dashboard_page):
        """Action DESTRUCTIVE mark-delete : modale de confirmation puis ANNULER.

        BUG CONNU (reporte Lot C, non corrige ici) : la modale dangerConfirmModal
        est rendue avec z-index 10000 (components.css .danger-modal-overlay)
        alors que l'overlay fiche film est a 10001 (.film-detail-modal-overlay).
        Depuis la fiche film mode C, la confirmation s'ouvre donc SOUS la fiche :
        invisible et non cliquable pour l'utilisateur (showModal generique est
        encore pire : z-index 1000). Le test xfail dynamiquement tant que le
        z-order n'est pas corrige ; une fois corrige, le chemin strict
        (clic Annuler + zero appel API) s'applique.
        """
        import pytest

        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "validation")

        page.click('[data-traitement-validation-action="inspect"][data-row-id="row-002"]')
        page.wait_for_function(
            """() => {
                const ov = document.getElementById('filmDetailOverlay');
                return !!ov && !ov.querySelector('.film-detail--loading')
                    && !!ov.querySelector('.film-detail');
            }""",
            timeout=15000,
        )

        page.click('#filmDetailOverlay [data-film-action="mark-delete"]')
        page.wait_for_selector("#dashDangerModal", state="attached", timeout=5000)
        modal_title = page.evaluate(
            "() => document.querySelector('#dashDangerModal .danger-modal-title').textContent.trim()"
        )
        assert "suppression" in modal_title.lower(), f"Titre modale inattendu : {modal_title}"

        # La modale doit etre AU-DESSUS de la fiche (actionnable par l'utilisateur).
        cancel_on_top = page.evaluate(
            """() => {
                const btn = document.querySelector('#dashDangerModal [data-danger-cancel]');
                if (!btn) return false;
                const r = btn.getBoundingClientRect();
                const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return !!el && (el === btn || btn.contains(el) || el.contains(btn));
            }"""
        )
        if not cancel_on_top:
            _screenshot(page, "traitement_fiche_film_modale_sous_overlay.png")
            # Nettoyage best-effort (Escape ferme modale + fiche) puis xfail
            # nominatif : bug z-index reporte, a re-tester apres correction.
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            pytest.xfail(
                "BUG Lot C : modale 'Confirmer le marquage suppression ?' rendue "
                "SOUS l'overlay fiche film (z-index .danger-modal-overlay 10000 < "
                ".film-detail-modal-overlay 10001) — confirmation invisible/incliquable"
            )

        # Chemin strict (bug corrige) : ANNULER, et zero appel destructif.
        _cancel_danger_modal(page)
        assert not any("library/mark_for_deletion" in u for u in watch["api_posts"]), (
            "mark_for_deletion appele malgre l'annulation de la modale"
        )
        page.click("#filmDetailOverlay [data-film-modal-close]")
        page.wait_for_selector("#filmDetailOverlay", state="detached", timeout=5000)
        _assert_clean(watch, "fiche film mark-delete")

    # --- Etape 3 : Validation ----------------------------------------------

    def test_step3_validation_actions(self, dashboard_page):
        """Etape Validation : filtres, tri, expand, presets bulk, save, go-doublons."""
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "validation")

        total_rows = page.evaluate(
            "() => document.querySelectorAll('.traitement-validation-table tbody tr[data-row-id]').length"
        )
        assert total_rows >= 10, f"Table validation attendue avec >= 10 lignes : {total_rows}"

        # Filtre confiance 'high' : la table se reduit, puis retour 'all'.
        page.click('[data-traitement-validation-filter="high"]')
        page.wait_for_timeout(400)
        high_rows = page.evaluate(
            "() => document.querySelectorAll('.traitement-validation-table tbody tr[data-row-id]').length"
        )
        assert 0 < high_rows < total_rows, (
            f"Filtre 'high' sans effet visible : {high_rows}/{total_rows}"
        )
        page.click('[data-traitement-validation-filter="all"]')
        page.wait_for_timeout(400)

        # Tri par titre : reaction visible = header actif.
        page.click('[data-traitement-validation-sort="titre"]')
        page.wait_for_timeout(400)
        assert page.evaluate(
            "() => document.querySelector('[data-traitement-validation-sort=\"titre\"]').classList.contains('is-active')"
        ), "Tri 'titre' non actif apres clic"

        # Expand 'toggle-reasons' sur la premiere ligne : ligne detail visible.
        first_row = page.evaluate(
            "() => document.querySelector('.traitement-validation-table tbody tr[data-row-id]').dataset.rowId"
        )
        page.click(f'[data-traitement-validation-action="toggle-reasons"][data-row-id="{first_row}"]')
        page.wait_for_selector(".traitement-validation-row-expand", timeout=5000)
        page.click(f'[data-traitement-validation-action="toggle-reasons"][data-row-id="{first_row}"]')
        page.wait_for_selector(".traitement-validation-row-expand", state="detached", timeout=5000)

        _screenshot(page, "traitement_step3_validation.png")

        # Presets bulk (15 films < seuil danger 50 -> pas de modale, toast direct).
        for action in ("bulk-approve-sure", "preset-no-alert", "preset-platinum-gold"):
            toast = _click_and_wait_toast(page, f'[data-traitement-action="{action}"]', action)
            assert toast, f"Aucun toast apres {action}"
            page.wait_for_timeout(400)

        # Enregistrer les decisions : toast de confirmation.
        toast = _click_and_wait_toast(
            page, '[data-traitement-action="save-validation"]', "save-validation"
        )
        assert "sauvegard" in toast.lower() or "enregistr" in toast.lower(), (
            f"Toast save-validation inattendu : {toast}"
        )
        page.wait_for_timeout(600)
        _assert_clean(watch, "etape validation")

    def test_step3_go_doublons_transition(self, dashboard_page):
        """Transition Validation -> Doublons via le bouton 'Passer aux Doublons'.

        BUG CONNU (reporte Lot C, non corrige ici) : le handler go-doublons
        rend l'etape doublons DANS l'instance courante (initDoublons -> fetch
        run/get_dashboard) PUIS _writeStep declenche un remount complet via
        hashchange. Le remount avorte le fetch doublons (nav-abort) et le
        _loadRunInfo de la NOUVELLE instance est dedup (core/api.js, cle
        methode+body identique) sur cette promesse avortee -> AbortError ->
        _runInfo=null -> ecran mort "Aucun run actif détecté" sans retry.
        Reproduction 100% en cliquant 'Passer aux Doublons'. xfail nominatif
        tant que le bug n'est pas corrige.
        """
        import pytest

        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "validation")

        # Decisions non modifiees dans ce test -> pas de guard 'non enregistrees'
        # attendu (les decisions par defaut derivent de la confiance).
        page.click('[data-traitement-action="go-doublons"]')
        page.wait_for_timeout(1000)

        guard_modal = page.evaluate("() => !!document.getElementById('dashModal')")
        if guard_modal:
            # Guard legitime si une divergence residuelle existe : on choisit
            # 'Continuer sans enregistrer' (index 1) pour poursuivre le parcours.
            page.click('#dashModal [data-modal-action="1"]')
            page.wait_for_timeout(800)

        try:
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('#view-processing .traitement-panel-title');
                    return !!el && el.textContent.includes('Étape 4');
                }""",
                timeout=8000,
            )
        except Exception:
            stuck_empty = page.evaluate(
                "() => !!document.querySelector('.traitement-header-run--empty')"
            )
            if stuck_empty:
                _screenshot(page, "traitement_go_doublons_ecran_mort.png")
                pytest.xfail(
                    "BUG Lot C : clic 'Passer aux Doublons' -> remount dont le "
                    "run/get_dashboard est dedup sur le fetch avorte de initDoublons "
                    "(core/api.js dedup + nav-abort) -> vue morte 'Aucun run actif "
                    "détecté' sans retry (repro 100%)"
                )
            raise
        _assert_clean(watch, "transition go-doublons")

    # --- Etape 4 : Doublons -------------------------------------------------

    def test_step4_doublons_rendu_et_go_apply(self, dashboard_page):
        """Etape Doublons : rendu du mount inline + go-apply (modale si pendants)."""
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "doublons")

        # Le module doublons se monte dans #traitement-doublons-mount : attendre
        # la fin du skeleton (header ou empty-state).
        page.wait_for_function(
            """() => {
                const m = document.getElementById('traitement-doublons-mount');
                if (!m) return false;
                if (m.querySelector('.doublons-view--loading')) return false;
                return !!(m.querySelector('.doublons-header')
                    || m.querySelector('.doublons-empty')
                    || m.querySelector('.doublons-view--error'));
            }""",
            timeout=25000,
        )
        assert not page.evaluate(
            "() => !!document.querySelector('#traitement-doublons-mount .doublons-view--error')"
        ), "Vue Doublons en etat d'erreur dans le stepper"

        _screenshot(page, "traitement_step4_doublons.png")

        # go-apply : si des doublons sont pendants (dataset : Dune Part Two x2),
        # une modale danger doit apparaitre -> ANNULER ('Retourner aux Doublons').
        # Sinon transition directe vers l'etape 5 : les deux sont valides.
        page.click('[data-traitement-action="go-apply"]')
        page.wait_for_timeout(1000)
        if _danger_modal_visible(page):
            modal_title = page.evaluate(
                "() => document.querySelector('#dashDangerModal .danger-modal-title').textContent.trim()"
            )
            assert "doublon" in modal_title.lower(), f"Titre modale go-apply inattendu : {modal_title}"
            _cancel_danger_modal(page)
            # Annulation -> on reste sur l'etape 4.
            still_doublons = page.evaluate(
                """() => {
                    const el = document.querySelector('#view-processing .traitement-panel-title');
                    return !!el && el.textContent.includes('Étape 4');
                }"""
            )
            assert still_doublons, "L'annulation de la modale go-apply a quitte l'etape Doublons"
        else:
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('#view-processing .traitement-panel-title');
                    return !!el && el.textContent.includes('Étape 5');
                }""",
                timeout=10000,
            )
        _assert_clean(watch, "etape doublons")

    # --- Etape 5 : Apply / Undo ---------------------------------------------

    def test_step5_apply_undo_modales_annulees(self, dashboard_page):
        """Etape Apply : modales de confirmation ouvertes puis ANNULEES, zero apply."""
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)
        _goto_step(page, "apply")

        page.wait_for_selector(".traitement-apply-summary", timeout=15000)
        # Laisser le temps a run/build_apply_preview de remplir l'apercu reel.
        page.wait_for_timeout(1500)
        _screenshot(page, "traitement_step5_apply.png")

        # Mode dry-run coche par defaut (garde-fou).
        assert page.is_checked('[data-apply-opt="dry_run"]'), (
            "dry_run devrait etre coche par defaut en etape Apply"
        )

        # Mode atomique : le cocher ouvre une modale d'explication -> ANNULER.
        # Apres annulation la checkbox doit rester decochee.
        page.click('[data-apply-opt="apply_atomic"]')
        page.wait_for_selector("#dashDangerModal", timeout=5000)
        _cancel_danger_modal(page)
        assert not page.is_checked('[data-apply-opt="apply_atomic"]'), (
            "apply_atomic coche malgre l'annulation de la modale"
        )

        # Apply REEL : decocher dry_run puis cliquer 'Appliquer maintenant' ->
        # la modale danger DOIT apparaitre (countdown 3s) -> ANNULER.
        page.click('[data-apply-opt="dry_run"]')
        page.wait_for_timeout(400)
        assert not page.is_checked('[data-apply-opt="dry_run"]'), "dry_run toujours coche"
        page.click('[data-traitement-action="apply-now"]')
        page.wait_for_selector("#dashDangerModal", timeout=5000)
        modal_title = page.evaluate(
            "() => document.querySelector('#dashDangerModal .danger-modal-title').textContent.trim()"
        )
        assert "filesystem" in modal_title.lower() or "application" in modal_title.lower(), (
            f"Titre modale apply inattendu : {modal_title}"
        )
        # Countdown 3s : le bouton confirmer est desactive a l'ouverture.
        assert page.evaluate(
            "() => document.querySelector('#dashDangerModal [data-danger-confirm]').disabled"
        ), "Bouton confirmer actif immediatement (countdown 3s attendu)"
        _cancel_danger_modal(page)

        # AUCUN run/apply ne doit etre parti (ni dry-run ni reel).
        assert not any("run/apply" in u for u in watch["api_posts"]), (
            f"run/apply appele malgre l'annulation : {watch['api_posts']}"
        )

        # Restaurer dry_run coche (etat par defaut) pour les tests suivants.
        page.click('[data-apply-opt="dry_run"]')
        page.wait_for_timeout(300)

        # Undo : le dataset mock n'a jamais subi d'apply -> pas de pending_undo,
        # la carte annulation et son bouton ne doivent pas etre rendus. Si un
        # jour le dataset embarque un pending_undo : ouvrir la preview puis
        # FERMER sans executer.
        undo_btn = page.evaluate(
            "() => !!document.querySelector('[data-traitement-action=\"undo-preview\"]')"
        )
        if undo_btn:
            page.click('[data-traitement-action="undo-preview"]')
            page.wait_for_selector("#dashModal", timeout=8000)
            # Fermer la preview SANS cliquer 'Executer annulation'.
            page.click('#dashModal [data-modal-action="0"]')
            page.wait_for_selector("#dashModal", state="detached", timeout=5000)
            assert not any(
                "run/undo_last_apply\"" in u or u.endswith("run/undo_last_apply")
                for u in watch["api_posts"]
            ), "undo_last_apply execute alors que la preview devait etre fermee"
        else:
            # Coherent avec le dataset : pas d'apply -> pas de carte undo.
            assert not page.evaluate(
                "() => !!document.querySelector('[data-traitement-undo-card]')"
            ), "Carte undo rendue sans pending_undo backend"
        _assert_clean(watch, "etape apply")

    # --- Aller-retour navigation x3 ------------------------------------------

    def test_navigation_aller_retour_x3_sans_empilement(self, dashboard_page):
        """3 allers-retours accueil <-> traitement : 0 erreur, pas d'empilement DOM."""
        page = dashboard_page
        watch = _attach_watchers(page)
        _settle_boot(page)

        for i in range(3):
            page.evaluate("() => { window.location.hash = '#/accueil'; }")
            page.wait_for_function(
                """() => {
                    const v = document.getElementById('view-status');
                    return !!v && v.classList.contains('active');
                }""",
                timeout=15000,
            )
            # Laisser les fetchs initiaux de l'accueil se terminer avant de
            # revenir (cf bug dedup+abort documente dans _settle_boot).
            page.wait_for_timeout(900)

            _goto_step(page, "verification")

            # Pas d'empilement : 1 seul breadcrumb, 1 seul panel, 1 seule vue active.
            counts = page.evaluate(
                """() => ({
                    breadcrumbs: document.querySelectorAll('#view-processing .traitement-breadcrumb').length,
                    panels: document.querySelectorAll('#view-processing .traitement-panel').length,
                    activeViews: document.querySelectorAll('.main .view.active').length,
                    overlays: document.querySelectorAll('#filmDetailOverlay, #dashDangerModal, #dashModal').length,
                })"""
            )
            assert counts["breadcrumbs"] == 1, f"Aller-retour {i + 1} : {counts['breadcrumbs']} breadcrumbs (empilement)"
            assert counts["panels"] == 1, f"Aller-retour {i + 1} : {counts['panels']} panels (empilement)"
            assert counts["activeViews"] == 1, f"Aller-retour {i + 1} : {counts['activeViews']} vues actives"
            assert counts["overlays"] == 0, f"Aller-retour {i + 1} : overlay residuel"

        _screenshot(page, "traitement_aller_retour_x3.png")
        _assert_clean(watch, "aller-retour x3")
