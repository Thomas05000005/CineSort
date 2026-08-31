"""Lot C (verif totale 2026-07) — Sweep runtime Playwright : groupe Accueil.

Vues couvertes :
  - #/accueil  (env bar, hero, KPI dernier run, CTA scan, suggestions, sante, activite)
  - #/aide     (recherche doc, diagnostic, logs, drawer documentation)
  - /about     : PAS une route. Aucun registerRoute("/about") dans web/dashboard/app.js ;
                 "A propos" est une MODALE (#dashModal) ouverte par le bouton footer de la
                 sidebar [data-v5-about-btn] (app.js _openAboutModal -> views/about.js
                 openAboutModal). test_07 le prouve en runtime (le hash #/about est
                 rejete par le router) puis exerce la modale a la place.

Regles du sweep :
  - 0 erreur console / pageerror par vue (liste blanche nominative _KNOWN_CONSOLE_NOISE).
  - Chaque action SURE est cliquee et doit produire une reaction visible.
    Source des actions : docs/internal/verif_totale_2026_07/matrices/m4_actions_ui.json
    (familles data-accueil-action et data-aide-action). Les actions exclues sont
    documentees dans _EXCLUDED_ACTIONS ci-dessous.
  - Aller-retour navigation x3 sans erreur ni empilement DOM visible.
  - Screenshots dans docs/internal/verif_totale_2026_07/captures_runtime/<vue>.png.

BUGS APP CONNUS (constates par ce sweep le 2026-07-08 — REPORTES, pas corriges ;
les tests concernes font pytest.xfail() tant que le bug est present et
redeviendront passants d'eux-memes une fois le bug corrige) :
  [BUG-ACCUEIL-BOOT]   Au boot loopback (bypass auth), hash '#/accueil' mais la vue
                       Accueil reste VIDE : le batch initial (run/get_dashboard...)
                       est avorte avant le reseau et une re-init dans la meme fenetre
                       se dedup sur le fetch avorte (core/api.js dedup in-flight) ->
                       AbortError silencieux, ni skeleton ni erreur. Contourne ici
                       par _wait_stable_with_retry (re-clic sidebar simule).
  [BUG-INSIGHT-QUERY]  CORRIGE 2026-07-08 (LOTC-R1) : le router strippe la query
                       au resolve et la transmet a init() via opts.query. Le
                       xfail dynamique de test_03 est redevenu passant.
  [BUG-DRAWER-ZINDEX]  Le drawer documentation de l'Aide s'affiche SOUS la topbar :
                       son bouton Fermer (croix) est recouvert par l'icone theme de la
                       topbar (pointer events interceptes) -> fermeture souris
                       impossible, seul Escape/backdrop fonctionne.
  [BUG-ABOUT-VERSION]  La modale About affiche toujours 'version indisponible' en
                       supervision web : views/about.js _readAppInfo (L58-66) lit
                       res.version sur l'ENVELOPPE apiPost {status, data} au lieu
                       de res.data.version.
  [BUG-SUGGESTION-HINT] CORRIGE 2026-07-08 (LOTC-M2) : accueil.js rend un libelle
                       lisible "cle : valeur" via _formatFilterHint (masque si
                       inexploitable). Constat visuel, pas de xfail dedie.

Lancer :
  "C:/Users/<utilisateur>/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/e2e_dashboard/test_lotc_sweep_accueil.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPTURES_DIR = _REPO_ROOT / "docs" / "internal" / "verif_totale_2026_07" / "captures_runtime"

# ---------------------------------------------------------------------------
# Liste blanche NOMINATIVE du bruit console connu.
# Chaque entree doit etre un extrait litteral du message, avec justification.
# ---------------------------------------------------------------------------
_KNOWN_CONSOLE_NOISE: list[str] = [
    # LOTC-R1 (fix 2026-07-08) : open-insight atteint desormais REELLEMENT
    # #/bibliotheque ; le dataset mock a TMDb desactive -> le proxy /api/poster
    # repond 503 par CONTRAT pour chaque jaquette demandee (fallback UI prevu).
    # Bruit reseau emis par le navigateur lui-meme, deja whiteliste
    # nominativement par test_lotc_sweep_traitement.py (meme justification).
    "Failed to load resource: the server responded with a status of 503",
]

# Actions VOLONTAIREMENT exclues du sweep (documentation, ne pas cliquer) :
_EXCLUDED_ACTIONS = {
    # accueil
    "start-scan-direct": "POST run/start_plan -> lance un VRAI run sur le serveur mock "
    "partage (scope session) : mutation d'etat, pas une action sure.",
    # aide
    "open-logs": "POST runtime/open_logs_folder -> ouvre un Explorer REEL sur la machine hote.",
    "report-bug": "window.open vers github.com (reseau externe, onglet popup) : hors sandbox test.",
    "drawer-expand": "navigue vers #/aide/doc/<id>, route NON enregistree dans le router "
    "(commentaire aide.js L549-551) -> rebond routeur, pas de reaction stable.",
}

# Actions sures de #/accueil : action -> prefixe de hash attendu apres clic.
# (Toutes sont des navigateTo() purs, cf. views/accueil.js _bindEvents L1188-1238.)
_ACCUEIL_SAFE_NAV_ACTIONS = {
    "start-scan": "#/traitement",  # empty state uniquement (aucun run)
    "resume-validation": "#/traitement",  # uniquement si run AWAITING_VALIDATION
    "view-run-detail": "#/historique",
    "open-traitement": "#/traitement",
    "view-history": "#/historique",
    "view-qualite": "#/qualite",
    "view-all-suggestions": "#/qualite",
}

# --- Etats "stables" des vues (skeleton remplace + aria-busy relache) -------

_ACCUEIL_STABLE_JS = """
() => {
  const v = document.querySelector('#view-status .accueil-view');
  if (!v) return false;
  if (v.classList.contains('accueil-view--loading')) return false;
  if (v.getAttribute('aria-busy') === 'true') return false;
  if (v.querySelector('.v5-skeleton')) return false;
  return true;
}
"""

_AIDE_STABLE_JS = """
() => {
  const v = document.querySelector('#view-help .aide-view');
  if (!v) return false;
  if (v.classList.contains('aide-view--loading')) return false;
  if (v.getAttribute('aria-busy') === 'true') return false;
  if (v.querySelector('.v5-skeleton')) return false;
  return true;
}
"""


class _ConsoleWatcher:
    """Collecte console.error + pageerror ; filtre par la liste blanche."""

    def __init__(self, page):
        self.raw: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)

    def _on_console(self, msg):
        if msg.type == "error":
            self.raw.append(f"console.error: {msg.text}")

    def _on_pageerror(self, err):
        self.raw.append(f"pageerror: {err}")

    @property
    def errors(self) -> list[str]:
        return [e for e in self.raw if not any(noise in e for noise in _KNOWN_CONSOLE_NOISE)]


@pytest.fixture()
def swept_page(page, e2e_server):
    """Page connectee au shell AVEC watcher console attache AVANT le boot.

    On n'utilise pas dashboard_page (conftest) car son goto() a deja eu lieu
    quand le test recoit la page : les erreurs du boot seraient perdues.
    Meme logique de connexion : bypass auth localhost -> shell direct,
    fallback saisie token si le bypass est desactive.
    """
    from playwright.sync_api import TimeoutError as PWTimeoutError

    watcher = _ConsoleWatcher(page)
    page.goto(e2e_server["dashboard_url"])
    try:
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=8000)
    except PWTimeoutError:
        page.wait_for_selector("#loginToken", timeout=8000)
        page.fill("#loginToken", e2e_server["token"])
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
    return page, watcher


def _goto(page, route: str) -> None:
    """Navigation par hash, memes semantiques que router.navigateTo() :
    si le hash est deja la cible, on force un resolve via un HashChangeEvent
    manuel (= clic sidebar sur l'entree deja active).

    Indispensable au boot : le shell demarre avec hash '#/accueil' mais la vue
    est vide ([BUG-ACCUEIL-BOOT]) et une assignation hash identique ne
    declencherait aucun hashchange.
    """
    page.evaluate(
        """(route) => {
          const target = '#' + route;
          if (window.location.hash === target) {
            window.dispatchEvent(new HashChangeEvent('hashchange'));
          } else {
            window.location.hash = target;
          }
        }""",
        route,
    )


def _wait_stable_with_retry(page, route: str, stable_js: str, attempts: int = 3) -> None:
    """Force la navigation puis attend l'etat stable, avec retry borne.

    Le retry modelise un utilisateur qui re-clique l'entree sidebar : au boot,
    la 1re init de l'Accueil meurt en silence et une init relancee dans la
    meme fenetre se dedup sur le fetch avorte -> AbortError -> vue vide sans
    erreur ni skeleton ([BUG-ACCUEIL-BOOT], cf. docstring module).
    """
    from playwright.sync_api import TimeoutError as PWTimeoutError

    last_exc = None
    for _ in range(attempts):
        _goto(page, route)
        try:
            page.wait_for_function(stable_js, timeout=6000)
            return
        except PWTimeoutError as exc:
            last_exc = exc
            # Laisser retomber la fenetre de dedup/abort avant de re-cliquer.
            page.wait_for_timeout(500)
    raise AssertionError(f"Vue {route} jamais stable apres {attempts} tentatives") from last_exc


def _wait_accueil_stable(page) -> None:
    _wait_stable_with_retry(page, "/accueil", _ACCUEIL_STABLE_JS)
    # L'etat stable ne doit pas etre l'etat d'erreur.
    err = page.query_selector("#view-status .accueil-view--error")
    if err:
        msg = (err.text_content() or "").strip()
        raise AssertionError(f"Accueil rendu en etat ERREUR : {msg!r}")


def _wait_aide_stable(page) -> None:
    _wait_stable_with_retry(page, "/aide", _AIDE_STABLE_JS)


def _save_capture(page, name: str) -> None:
    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_CAPTURES_DIR / name), full_page=True)


class TestLotCSweepAccueil:
    """Sweep runtime du groupe Accueil (#/accueil, #/aide, modale About)."""

    # ------------------------------------------------------------------ #/accueil

    def test_01_accueil_stable_sections_et_console(self, swept_page):
        """#/accueil : skeleton remplace, aria-busy relache, sections presentes, 0 erreur."""
        page, watcher = swept_page
        _wait_accueil_stable(page)

        # Skeletons remplaces par du contenu (pas de squelette permanent).
        assert page.evaluate("() => document.querySelectorAll('#view-status .v5-skeleton').length") == 0
        # aria-busy relache partout dans la vue active.
        assert page.evaluate("() => document.querySelectorAll('#view-status [aria-busy=\"true\"]').length") == 0

        # Widgets / sections de la spec 05 (cf. accueil.js _renderAccueil L909-921).
        # Sante et Suggestions ont des variantes --empty selon les donnees : on
        # accepte les deux (le sweep valide le rendu, pas le contenu metier).
        for selector, label in [
            ("#view-status .accueil-env-bar", "barre environnement/integrations"),
            ("#view-status .accueil-hero", "hero editorial"),
            ("#view-status .accueil-hero-summary", "resume hero"),
            ("#view-status .accueil-last-run", "carte Dernier run (KPI)"),
            ("#view-status .accueil-cta-scan", "CTA scan"),
            ("#view-status .accueil-suggestions", "suggestions / points a traiter"),
            ("#view-status .accueil-health", "sante bibliotheque"),
        ]:
            assert page.query_selector(selector), f"Section accueil absente : {label} ({selector})"

        # KPI du dernier run : les 3 <dd> (Films / Score moyen / Confiance moyenne)
        # doivent etre rendus et non vides (les donnees mock ont un run termine).
        kpi_dd = page.evaluate(
            """() => Array.from(
                 document.querySelectorAll('#view-status .accueil-last-run-stats dd')
               ).map((el) => (el.textContent || '').trim())"""
        )
        if kpi_dd:  # carte non-empty : 3 KPI attendus
            assert len(kpi_dd) == 3, f"KPI dernier run : 3 valeurs attendues, obtenu {kpi_dd}"
            assert all(v for v in kpi_dd), f"KPI dernier run vide(s) : {kpi_dd}"

        _save_capture(page, "accueil.png")
        assert watcher.errors == [], f"Erreurs console sur #/accueil : {watcher.errors}"

    def test_02_accueil_actions_sures(self, swept_page):
        """Chaque action sure presente est cliquee -> reaction visible (navigation/drawer)."""
        page, watcher = swept_page
        clicked = []
        absent = []

        # 1) Actions de navigation pures (cf. _ACCUEIL_SAFE_NAV_ACTIONS).
        for action, expected_prefix in _ACCUEIL_SAFE_NAV_ACTIONS.items():
            _wait_accueil_stable(page)
            btn = page.query_selector(f'#view-status [data-accueil-action="{action}"]')
            if not btn:
                # Presence dependante de l'etat des donnees (empty state, run en
                # attente de validation...) : absence = normal, pas un echec.
                absent.append(action)
                continue
            btn.click()
            page.wait_for_function(f"() => window.location.hash.startsWith('{expected_prefix}')", timeout=5000)
            # Laisser la vue cible s'initialiser (ses erreurs comptent aussi).
            page.wait_for_timeout(400)
            clicked.append(action)

        # 2) open-scan-options : ouvre le drawer options -> ANNULER (jamais lancer).
        _wait_accueil_stable(page)
        btn = page.query_selector('#view-status [data-accueil-action="open-scan-options"]')
        if btn:
            btn.click()
            page.wait_for_selector("[data-accueil-scan-drawer]", timeout=3000)
            page.click("[data-accueil-scan-drawer-cancel]")
            page.wait_for_function("() => !document.querySelector('[data-accueil-scan-drawer]')", timeout=3000)
            clicked.append("open-scan-options")
        else:
            absent.append("open-scan-options")

        # Garde anti-test-vide : les donnees mock (2 runs termines, 15 films)
        # garantissent au minimum view-run-detail, view-history, view-qualite
        # et le CTA scan idle.
        assert len(clicked) >= 3, f"Sweep vide : seulement {clicked} cliquees (absentes : {absent})"
        assert watcher.errors == [], f"Erreurs console pendant les actions accueil {clicked} : {watcher.errors}"

    def test_03_accueil_open_insight(self, swept_page):
        """Clic sur une suggestion (open-insight) -> doit atteindre sa route cible.

        xfail tant que [BUG-INSIGHT-QUERY] est present : le router ne gere pas
        '?query' dans le hash -> rebond #/accueil, l'action est sans effet.
        """
        page, watcher = swept_page
        _wait_accueil_stable(page)
        insight = page.query_selector('#view-status [data-accueil-action="open-insight"][data-target-route]')
        if not insight:
            pytest.skip("Aucune suggestion open-insight avec data-target-route (etat des donnees)")

        target = insight.get_attribute("data-target-route") or ""
        insight.click()
        page.wait_for_timeout(900)
        final_hash = page.evaluate("() => window.location.hash")
        base = "#" + target.split("?")[0].split("#")[0]

        if "?" in target and final_hash == "#/accueil":
            pytest.xfail(
                f"[BUG-INSIGHT-QUERY] open-insight cible {target!r} : le router ne strippe pas "
                f"la query (router.js resolve() L111) -> route inconnue -> rebond #/accueil. "
                "Suggestion cliquee = aucune reaction pour l'utilisateur."
            )
        assert final_hash.startswith(base), (
            f"open-insight (cible {target!r}) n'a pas abouti : hash final {final_hash!r}"
        )
        assert watcher.errors == [], f"Erreurs console pendant open-insight : {watcher.errors}"

    # ------------------------------------------------------------------ #/aide

    def test_04_aide_stable_sections_et_console(self, swept_page):
        """#/aide : skeleton remplace, aria-busy relache, sections presentes, 0 erreur."""
        page, watcher = swept_page
        _wait_aide_stable(page)

        assert page.evaluate("() => document.querySelectorAll('#view-help .v5-skeleton').length") == 0
        assert page.evaluate("() => document.querySelectorAll('#view-help [aria-busy=\"true\"]').length") == 0

        for selector, label in [
            ("#view-help [data-aide-search]", "barre de recherche documentation"),
            ("#view-help [data-aide-topic]", "topics documentation"),
            ("#view-help #aide-diagnostic-title", "section Diagnostic"),
            ("#view-help #aide-logs-title", "section Logs"),
            ('#view-help [data-aide-action="copy-diagnostic"]', "bouton copier diagnostic"),
            ('#view-help [data-aide-action="copy-recent-logs"]', "bouton copier logs"),
        ]:
            assert page.query_selector(selector), f"Element aide absent : {label} ({selector})"

        _save_capture(page, "aide.png")
        assert watcher.errors == [], f"Erreurs console sur #/aide : {watcher.errors}"

    def test_05_aide_actions_copie(self, swept_page):
        """#/aide : copy-diagnostic et copy-recent-logs -> statut visible."""
        page, watcher = swept_page
        # Clipboard headless : sans grant, writeText echoue -> statut 'x' non
        # deterministe. On accorde la permission pour tester le chemin nominal.
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        _wait_aide_stable(page)

        # copy-diagnostic -> message de statut visible dans [data-aide-status].
        page.click('#view-help [data-aide-action="copy-diagnostic"]')
        page.wait_for_function(
            "() => (document.querySelector('#view-help [data-aide-status]')?.textContent || '').trim() !== ''",
            timeout=4000,
        )
        status = page.evaluate("() => document.querySelector('#view-help [data-aide-status]').textContent.trim()")
        assert "copi" in status.lower(), f"copy-diagnostic : statut inattendu {status!r}"

        # copy-recent-logs -> message de statut visible dans [data-aide-logs-status].
        page.click('#view-help [data-aide-action="copy-recent-logs"]')
        page.wait_for_function(
            "() => (document.querySelector('#view-help [data-aide-logs-status]')?.textContent || '').trim() !== ''",
            timeout=4000,
        )
        logs_status = page.evaluate(
            "() => document.querySelector('#view-help [data-aide-logs-status]').textContent.trim()"
        )
        assert "copi" in logs_status.lower(), f"copy-recent-logs : statut inattendu {logs_status!r}"

        # Voir _EXCLUDED_ACTIONS pour open-logs / report-bug.
        assert watcher.errors == [], f"Erreurs console pendant les actions aide : {watcher.errors}"

    def test_06_aide_drawer_documentation(self, swept_page):
        """#/aide : ouvrir un topic -> drawer + contenu, fermer au clic sur la croix.

        xfail tant que [BUG-DRAWER-ZINDEX] est present : le bouton Fermer du
        drawer est recouvert par la topbar (icone theme) -> clic intercepte.
        """
        from playwright.sync_api import TimeoutError as PWTimeoutError

        page, watcher = swept_page
        _wait_aide_stable(page)

        page.click("#view-help [data-aide-topic]")
        page.wait_for_selector(".aide-doc-drawer", timeout=4000)
        page.wait_for_function(
            """() => {
              const c = document.querySelector('[data-aide-drawer-content]');
              return c && !(c.textContent || '').includes('Chargement de la documentation');
            }""",
            timeout=6000,
        )
        drawer_text = page.evaluate(
            "() => (document.querySelector('[data-aide-drawer-content]').textContent || '').trim()"
        )
        assert drawer_text, "Drawer documentation ouvert mais contenu vide"
        assert "indisponible" not in drawer_text.lower(), (
            f"Drawer documentation : document indisponible ({drawer_text[:120]!r})"
        )
        assert watcher.errors == [], f"Erreurs console a l'ouverture du drawer : {watcher.errors}"

        # Fermeture au CLIC sur la croix (chemin utilisateur nominal).
        try:
            page.click(".aide-doc-drawer-close", timeout=3000)
        except PWTimeoutError:
            # Nettoyage (Escape marche : handler document) puis xfail documente.
            page.keyboard.press("Escape")
            page.wait_for_function("() => !document.querySelector('.aide-doc-drawer-overlay')", timeout=3000)
            pytest.xfail(
                "[BUG-DRAWER-ZINDEX] bouton Fermer du drawer documentation recouvert par "
                "la topbar (icone theme intercepte les pointer events) : fermeture souris "
                "impossible, seul Escape/backdrop fonctionne."
            )
        page.wait_for_function("() => !document.querySelector('.aide-doc-drawer-overlay')", timeout=3000)

    # ------------------------------------------------------------------ About

    def test_07_about_non_route_et_modale(self, swept_page):
        """/about n'est pas une route (preuve runtime) ; la modale About fonctionne."""
        page, watcher = swept_page
        _wait_accueil_stable(page)

        # Preuve runtime : #/about est inconnu du router. En mode natif/loopback
        # (hostname 127.0.0.1 -> _isNativeMode()), le router rebondit sur /accueil
        # (router.js resolve() L124-129). NOTE : /about n'est PAS routee ; l'ecran
        # "A propos" du dashboard est une modale (voir docstring module).
        _goto(page, "/about")
        page.wait_for_timeout(700)
        final_hash = page.evaluate("() => window.location.hash")
        assert final_hash != "#/about", (
            "ATTENTION : #/about semble routee desormais — mettre a jour ce sweep pour la traiter comme une vraie vue."
        )
        assert final_hash == "#/accueil", (
            f"Rebond route inconnue inattendu : {final_hash!r} (attendu #/accueil en mode loopback)"
        )

        # Modale About via le bouton footer sidebar.
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.click("[data-v5-about-btn]")
        page.wait_for_selector("#dashModal", timeout=4000)
        title = page.evaluate("() => (document.querySelector('#dashModal #dashModalTitle')?.textContent || '').trim()")
        assert "propos" in title.lower(), f"Titre modale About inattendu : {title!r}"
        # Laisser le fetch runtime/get_app_version aboutir avant la capture.
        page.wait_for_timeout(1200)
        _save_capture(page, "about_modal.png")

        # Action sure : copier le chemin des logs -> feedback texte sur le bouton.
        page.click('#dashModal [data-testid="about-btn-copy-logs"]')
        page.wait_for_function(
            """() => {
              const b = document.querySelector('#dashModal [data-testid="about-btn-copy-logs"]');
              return b && (b.textContent || '').trim() !== 'Copier le chemin';
            }""",
            timeout=3000,
        )
        copy_feedback = page.evaluate(
            "() => document.querySelector('#dashModal [data-testid=\"about-btn-copy-logs\"]').textContent.trim()"
        )
        assert copy_feedback == "Copie !", f"Copie chemin logs : feedback {copy_feedback!r}"

        # Fermer via le bouton "Fermer" de la modale -> #dashModal retire.
        page.click("#dashModal .modal-actions button")
        page.wait_for_function("() => !document.querySelector('#dashModal')", timeout=3000)
        assert watcher.errors == [], f"Erreurs console sur About : {watcher.errors}"

    def test_08_about_version_remplie(self, swept_page):
        """La modale About doit afficher la vraie version (serveur UP).

        xfail tant que [BUG-ABOUT-VERSION] est present : about.js _readAppInfo
        lit res.version sur l'enveloppe apiPost {status, data} au lieu de
        res.data.version -> 'version indisponible' systematique en web.
        """
        page, watcher = swept_page
        _wait_accueil_stable(page)
        page.click("[data-v5-about-btn]")
        page.wait_for_selector("#dashModal", timeout=4000)
        page.wait_for_timeout(1500)  # laisse runtime/get_app_version aboutir + re-render

        version_txt = page.evaluate(
            "() => (document.querySelector('#dashModal [data-testid=\"about-version\"]')?.textContent || '').trim()"
        )
        assert version_txt.startswith("CineSort"), f"Bloc version absent/malforme : {version_txt!r}"
        if "indisponible" in version_txt.lower():
            pytest.xfail(
                "[BUG-ABOUT-VERSION] modale About : 'version indisponible' alors que "
                "runtime/get_app_version repond 200 — views/about.js _readAppInfo (L58-66) "
                "lit res.version au lieu de res.data.version (enveloppe apiPost)."
            )
        assert watcher.errors == [], f"Erreurs console sur About/version : {watcher.errors}"

    # ------------------------------------------------------------------ Aller-retour x3

    def test_09_navigation_aller_retour_x3(self, swept_page):
        """3 allers-retours accueil <-> aide : 0 erreur, pas d'empilement DOM."""
        page, watcher = swept_page
        for i in range(3):
            _wait_accueil_stable(page)
            _wait_aide_stable(page)

            counts = page.evaluate(
                """() => ({
                  accueil: document.querySelectorAll('.accueil-view').length,
                  aide: document.querySelectorAll('.aide-view').length,
                  drawers: document.querySelectorAll('.aide-doc-drawer-overlay').length,
                  scan_drawers: document.querySelectorAll('[data-accueil-scan-drawer]').length,
                  modals: document.querySelectorAll('#dashModal').length,
                  busy: document.querySelectorAll('#view-help [aria-busy="true"]').length,
                })"""
            )
            assert counts["accueil"] == 1, f"Passe {i + 1} : empilement .accueil-view = {counts}"
            assert counts["aide"] == 1, f"Passe {i + 1} : empilement .aide-view = {counts}"
            assert counts["drawers"] == 0, f"Passe {i + 1} : drawer doc zombie = {counts}"
            assert counts["scan_drawers"] == 0, f"Passe {i + 1} : drawer scan zombie = {counts}"
            assert counts["modals"] == 0, f"Passe {i + 1} : modale zombie = {counts}"
            assert counts["busy"] == 0, f"Passe {i + 1} : aria-busy non relache = {counts}"

        # Retour final sur l'accueil : toujours 1 seule vue rendue.
        _wait_accueil_stable(page)
        assert page.evaluate("() => document.querySelectorAll('.accueil-view').length") == 1
        assert watcher.errors == [], f"Erreurs console pendant les allers-retours : {watcher.errors}"
