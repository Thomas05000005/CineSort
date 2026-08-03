"""Lot C (verif totale 2026-07) — Sweep runtime Playwright : #/processing + #/historique.

Lancer :
    "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
        tests/e2e_dashboard/test_lotc_sweep_processing_historique.py -q

Regles du sweep (plan Lot C) :
  - navigation par location.hash + attente d'un etat stable par vue ;
  - 0 erreur console / pageerror (liste blanche NOMINATIVE commentee) ;
  - screenshot nominal de chaque vue dans
    docs/internal/verif_totale_2026_07/captures_runtime/<vue>.png ;
  - chaque action SURE (matrice m4_actions_ui.json) est cliquee avec
    verification d'une reaction visible ;
  - les actions DESTRUCTIVES ouvrent leur modale de confirmation puis sont
    ANNULEES — jamais confirmees ;
  - aller-retour x3 entre les vues : pas d'erreur console, pas d'empilement.

GATEs Lot E re-verifies en runtime sur /processing :
  - E5/E5-bis : apply REEL sans film approuve => toast warning + renvoi Review,
    AUCUN appel POST /api/run/apply, AUCUNE modale danger ;
  - E6 : cancel-run => dangerConfirmModal (on ANNULE) et aucun POST
    /api/run/cancel_run tant que l'utilisateur n'a pas confirme ;
  - E7/E7-bis (R8-083) : le poll run/get_status ne survit pas a la navigation
    (aucun tick > 2.5 s apres l'unmount).

FINDING ATTENDU (diagnostique le 2026-07-08, cause racine PROUVEE) :
  LOTC-HISTO-01 — #/historique reste bloque en skeleton `historique-view--loading`
  quand on navigue DES que le shell est visible (sequence exacte des 2 tests
  baseline test_runtime_apply_history_labels / test_runtime_skeleton_lifecycle).
  Chaine causale, verifiee fetch par fetch (instrumentation window.fetch) :
    1. Boot bypass localhost sans token stocke -> `markTokenAbsent({native:true})`
       differe le deblocage des apiPost de 800 ms (console: "deblocage differe 800").
    2. Pendant ce temps, initAccueil a deja enregistre
       POST run/get_dashboard {"run_id":"latest"} dans `_inFlightRequests`
       (dedup in-flight de web/dashboard/core/api.js), porteur du signal de
       navigation d'accueil (core/nav-abort.js).
    3. La navigation vers #/historique appelle abortCurrentNav() -> le signal
       d'accueil est aborte ALORS QUE la requete attend encore awaitToken().
    4. initHistorique appelle apiPost sur LA MEME cle de dedup : `_dedupExec`
       lui rend la promesse d'accueil (le signal du 2e appelant est IGNORE —
       le commentaire de apiPost promet une composition des signaux que
       `_dedupExec` n'implemente pas).
    5. awaitToken se libere -> fetch part avec un signal DEJA aborte
       (observe : 1 seul appel fetch get_dashboard, abortedAtCall=true, aucun
       octet sur le reseau) -> AbortError partage.
    6. historique.js initHistorique attrape AbortError et `return` (suppose
       "navigation annulee") -> le squelette --loading reste a l'ecran pour
       toujours ; aucune requete reseau, aucun retry, aucun etat d'erreur.
  Preuve inverse : la meme navigation apres ~1.8 s (boot settle) rend la vue
  correctement (run/get_dashboard HTTP 200 ok=true, 2 runs).
  Le test test_lotc_historique_navigation_immediate_charge ECHOUE tant que ce
  bug n'est pas corrige et sert de GATE de regression apres correction.

FINDING SECONDAIRE (observe, non bloquant pour ce sweep) :
  LOTC-PROC-01 — step Review de /processing : `_initReviewStep` lit
  `payload.rows` de run/load_validation, or le contrat backend
  (ui/api/history_support.py::load_validation) ne renvoie QUE {ok, decisions}.
  Le tableau de review est donc TOUJOURS l'empty-state "Aucun film a valider",
  meme avec un plan de 15 rows -> les actions data-row-action / data-bulk de la
  matrice m4 sont inatteignables en runtime sur cette vue legacy.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour le sweep runtime Lot C")

from playwright.sync_api import TimeoutError as PWTimeoutError  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPTURES_DIR = _REPO_ROOT / "docs" / "internal" / "verif_totale_2026_07" / "captures_runtime"

# ---------------------------------------------------------------------------
# Liste blanche NOMINATIVE du bruit console connu.
# Chaque entree DOIT etre justifiee par un commentaire. Tout message console
# de type "error" (ou pageerror) non liste ici fait echouer le sweep.
# ---------------------------------------------------------------------------
_CONSOLE_ERROR_WHITELIST: tuple = (
    # (vide au 2026-07-08 : le boot bypass localhost ne produit que du
    #  console.debug/_safeBearer et un warning markTokenAbsent — aucun "error")
)

# Boot bypass localhost : markTokenAbsent({native:true}) differe le deblocage
# des apiPost de 800 ms ; on ajoute une marge pour laisser les fetchs initiaux
# d'accueil se terminer (sinon on retombe sur LOTC-HISTO-01, testee a part).
_BOOT_SETTLE_MS = 1800

_HISTORIQUE_SETTLED_JS = """() => {
    const v = document.querySelector('#view-qij .historique-view');
    if (!v) return false;
    if (v.classList.contains('historique-view--loading')) return false;
    if (v.classList.contains('historique-view--error')) return false;
    return true;
}"""

_PROCESSING_SETTLED_JS = """() => {
    const shell = document.querySelector('#view-processing .v5-processing-shell');
    if (!shell) return false;
    const content = shell.querySelector('[data-v5-processing-panel] .v5-processing-step-content');
    if (!content) return false;
    return content.getAttribute('aria-busy') !== 'true';
}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attach_watch(page):
    """Collecte console errors / pageerrors / requetes /api/ (horodatees)."""
    watch = {"console_errors": [], "console_all": [], "pageerrors": [], "api_requests": []}

    def _on_console(msg):
        text = msg.text
        watch["console_all"].append(f"[{msg.type}] {text}")
        if msg.type == "error" and not any(allowed in text for allowed in _CONSOLE_ERROR_WHITELIST):
            watch["console_errors"].append(text)

    def _on_request(req):
        if "/api/" in req.url:
            watch["api_requests"].append((time.monotonic(), req.method, req.url))

    page.on("console", _on_console)
    page.on("pageerror", lambda err: watch["pageerrors"].append(str(err)))
    page.on("request", _on_request)
    return watch


def _api_calls(watch, endpoint: str):
    suffix = f"/api/{endpoint}"
    return [entry for entry in watch["api_requests"] if entry[2].endswith(suffix)]


def _assert_console_clean(watch, view: str) -> None:
    assert not watch["pageerrors"], f"[{view}] pageerror(s) JS pendant le sweep : {watch['pageerrors']}"
    assert not watch["console_errors"], f"[{view}] erreur(s) console non whitelistees : {watch['console_errors']}"


def _screenshot(page, name: str) -> None:
    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_CAPTURES_DIR / name), full_page=True)


def _goto_hash(page, hash_value: str) -> None:
    page.evaluate(f"window.location.hash = '{hash_value}'")


def _historique_diag(page, watch) -> dict:
    """Dump diagnostic LOTC-HISTO-01 : classe d'etat du conteneur, trafic reseau
    de l'endpoint appele par la vue (run/get_dashboard) et reponse directe du
    meme endpoint depuis la page (prouve que le backend, lui, repond)."""
    dom_state = page.evaluate(
        """() => {
            const el = document.getElementById('view-qij');
            const v = el ? el.querySelector('.historique-view') : null;
            const errTitle = el ? el.querySelector('.historique-error-title') : null;
            const errMsg = el ? el.querySelector('.historique-view--error p') : null;
            return {
                container_state_class: v ? v.className : '(aucun .historique-view rendu)',
                error_title: errTitle ? errTitle.textContent : null,
                error_message: errMsg ? errMsg.textContent : null,
                view_html_head: el ? el.innerHTML.slice(0, 300) : null,
            };
        }"""
    )
    direct_fetch = page.evaluate(
        """async () => {
            try {
                const r = await fetch('/api/run/get_dashboard', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({run_id: 'latest'}),
                });
                const txt = await r.text();
                let ok = null, nb_runs = null;
                try {
                    const d = JSON.parse(txt);
                    ok = d.ok;
                    nb_runs = Array.isArray(d.runs_history) ? d.runs_history.length : null;
                } catch (e) { /* body non JSON */ }
                return {status: r.status, ok, nb_runs, body_head: txt.slice(0, 200)};
            } catch (e) {
                return {status: -1, error: String(e)};
            }
        }"""
    )
    return {
        "dom": dom_state,
        # NB : dans le scenario LOTC-HISTO-01, la seule requete observable est
        # celle du boot accueil (dedup), avortee avant reponse ; la vue
        # historique n'emet jamais la sienne et n'obtient jamais de reponse.
        "requetes_run_get_dashboard_observees": len(_api_calls(watch, "run/get_dashboard")),
        "reponse_directe_run_get_dashboard": direct_fetch,
        "console_tail": watch["console_all"][-15:],
        "pageerrors": watch["pageerrors"],
    }


# ---------------------------------------------------------------------------
# 1. /processing — sweep actions sures + GATEs Lot E (E5, E6, E7/R8-083)
# ---------------------------------------------------------------------------


@pytest.mark.runtime
def test_lotc_processing_sweep_actions_sures(dashboard_page, e2e_server) -> None:
    page = dashboard_page
    watch = _attach_watch(page)
    page.wait_for_timeout(_BOOT_SETTLE_MS)

    _goto_hash(page, "#/processing")
    page.wait_for_function(_PROCESSING_SETTLED_JS, timeout=10000)

    # Stepper : 3 etapes rendues.
    steps = page.evaluate("() => document.querySelectorAll('#view-processing [data-step-id]').length")
    assert steps == 3, f"Stepper /processing incomplet : {steps} etapes au lieu de 3"

    # Le dernier run du dataset E2E doit etre resolu (run/get_dashboard latest).
    run_info = page.evaluate(
        "() => { const el = document.querySelector('#view-processing .v5-processing-run-info code');"
        " return el ? el.textContent : null; }"
    )
    assert run_info == e2e_server["run_id"], (
        f"/processing n'a pas resolu le dernier run du dataset : vu {run_info!r}, "
        f"attendu {e2e_server['run_id']!r} (si None : la course dedup+abort de "
        f"LOTC-HISTO-01 a probablement mange _fetchLastRunId)"
    )

    # Screenshot nominal de la vue (step Scan charge).
    _screenshot(page, "processing.png")

    # --- Action sure : stepper -> Review (reaction visible = panel Review). ---
    page.click("#view-processing [data-step-id='review']")
    page.wait_for_function(
        """() => {
            const p = document.querySelector('#view-processing [data-v5-processing-panel]');
            return !!(p && p.textContent.includes('Valider les decisions'));
        }""",
        timeout=8000,
    )
    # Attendre l'etat FINAL du body review (table OU empty-state, pas le spinner).
    page.wait_for_function(
        """() => {
            const b = document.querySelector('#processing-review-body');
            if (!b) return false;
            return !!(b.querySelector('.v5-processing-table') || b.querySelector('.empty-state'));
        }""",
        timeout=8000,
    )
    # LOTC-PROC-01 (documente, non bloquant) : run/load_validation ne renvoie
    # jamais de cle `rows` -> le review step montre l'empty-state meme avec un
    # plan de 15 rows. Les actions data-row-action / data-bulk (matrice m4)
    # sont donc inatteignables ici ; on ne les clique pas.
    review_rows = page.evaluate(
        "() => document.querySelectorAll('#processing-review-body .v5-processing-table tbody tr').length"
    )
    assert isinstance(review_rows, int)  # etat observe, trace dans le rapport Lot C

    # --- Action sure : footer -> Apply (reaction visible = cartes recap). ---
    page.click("#view-processing [data-action='goto-apply']")
    page.wait_for_function(
        """() => {
            const p = document.querySelector('#view-processing [data-v5-processing-panel]');
            return !!(p && p.textContent.includes('Appliquer les changements'));
        }""",
        timeout=8000,
    )
    cards = page.evaluate("() => document.querySelectorAll('#view-processing .v5-processing-apply-card').length")
    assert cards == 3, f"Step Apply : {cards} cartes recap au lieu de 3"

    # =======================================================================
    # GATE E5/E5-bis — apply REEL sans film approuve : BLOQUE.
    #   Attendu : toast warning "Aucun film approuvé", renvoi step Review,
    #   AUCUN POST /api/run/apply, AUCUNE modale danger.
    # =======================================================================
    page.uncheck("#view-processing [data-v5-dry-run]")
    assert len(_api_calls(watch, "run/apply")) == 0
    page.click("#view-processing [data-action='run-apply']")
    page.wait_for_selector(".toast--warning", timeout=8000)
    toast_text = page.inner_text("#toast-container")
    assert "Aucun film approuvé" in toast_text, (
        f"GATE E5 : toast warning inattendu pendant l'apply bloque : {toast_text!r}"
    )
    # Renvoi automatique vers Review.
    page.wait_for_function(
        """() => {
            const p = document.querySelector('#view-processing [data-v5-processing-panel]');
            return !!(p && p.textContent.includes('Valider les decisions'));
        }""",
        timeout=8000,
    )
    # Jamais de modale danger dans ce scenario (et si elle apparaissait, on
    # l'ANNULE avant d'echouer — on ne confirme JAMAIS un apply reel en test).
    danger = page.query_selector("#dashDangerModal")
    if danger:
        page.click("#dashDangerModal [data-danger-cancel]")
        pytest.fail(
            "GATE E5 : la modale danger d'apply reel s'est ouverte alors que "
            "0 film est approuve (la garde _approvedCount n'a pas bloque)"
        )
    assert len(_api_calls(watch, "run/apply")) == 0, (
        f"GATE E5 : POST /api/run/apply emis malgre 0 film approuve : {_api_calls(watch, 'run/apply')}"
    )

    # =======================================================================
    # GATE E6 — cancel-run ouvre une modale de confirmation, qu'on ANNULE.
    #   Le bouton n'existe que pendant un scan "running" : on stubbe
    #   run/start_plan + run/get_status via page.route (AUCUNE mutation du
    #   serveur ephemere), ce qui exerce le vrai code UI (_startScan,
    #   _pollStatus, _cancelRun).
    # =======================================================================
    page.click("#view-processing [data-action='goto-scan']")
    page.wait_for_function(
        """() => {
            const p = document.querySelector('#view-processing [data-v5-processing-panel]');
            return !!(p && p.textContent.includes('Lancer un scan'));
        }""",
        timeout=8000,
    )
    page.route(
        "**/api/run/start_plan",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "run_id": "lotc-fake-run"}),
        ),
    )
    page.route(
        "**/api/run/get_status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "status": "running", "progress": 37, "logs": []}),
        ),
    )
    try:
        page.click("#view-processing [data-action='start-scan']")
        page.wait_for_selector("#view-processing [data-action='cancel-run']", timeout=8000)

        page.click("#view-processing [data-action='cancel-run']")
        page.wait_for_selector("#dashDangerModal", timeout=5000)
        modal_title = page.text_content("#dashDangerModalTitle") or ""
        assert "Annuler l'analyse" in modal_title, f"GATE E6 : titre de modale inattendu : {modal_title!r}"
        # ANNULER (jamais confirmer).
        page.click("#dashDangerModal [data-danger-cancel]")
        page.wait_for_selector("#dashDangerModal", state="detached", timeout=5000)
        assert len(_api_calls(watch, "run/cancel_run")) == 0, (
            "GATE E6 : POST /api/run/cancel_run emis alors que la confirmation a ete ANNULEE"
        )

        # ===================================================================
        # GATE E7/E7-bis (R8-083) — navigation ailleurs : le poll get_status
        # (setTimeout recursif 2 s) ne doit PAS survivre a l'unmount. Tolerance
        # 2.5 s pour un dernier tick deja arme au moment de la navigation.
        # ===================================================================
        _goto_hash(page, "#/aide")
        t_nav = time.monotonic()
        page.wait_for_timeout(6000)
        late_polls = [e for e in _api_calls(watch, "run/get_status") if e[0] > t_nav + 2.5]
        assert not late_polls, (
            f"R8-083 REGRESSION : {len(late_polls)} tick(s) run/get_status "
            f"> 2.5 s apres avoir quitte /processing : {late_polls}"
        )
    finally:
        page.unroute("**/api/run/start_plan")
        page.unroute("**/api/run/get_status")

    # Retour /processing : pas d'empilement du shell.
    _goto_hash(page, "#/processing")
    page.wait_for_function(_PROCESSING_SETTLED_JS, timeout=10000)
    shells = page.evaluate("() => document.querySelectorAll('#view-processing .v5-processing-shell').length")
    assert shells == 1, f"Empilement DOM /processing : {shells} .v5-processing-shell"

    _assert_console_clean(watch, "processing")


# ---------------------------------------------------------------------------
# 2. /historique — sweep actions sures (navigation APRES boot settle)
# ---------------------------------------------------------------------------


@pytest.mark.runtime
def test_lotc_historique_sweep_actions_sures(dashboard_page, e2e_server) -> None:
    page = dashboard_page
    watch = _attach_watch(page)
    page.wait_for_timeout(_BOOT_SETTLE_MS)

    _goto_hash(page, "#/historique")
    try:
        page.wait_for_function(_HISTORIQUE_SETTLED_JS, timeout=10000)
    except PWTimeoutError:
        diag = _historique_diag(page, watch)
        _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(_CAPTURES_DIR / "historique_sweep_stuck.png"))
        pytest.fail(
            "/historique ne se stabilise pas MEME apres boot settle (etat plus "
            "grave que LOTC-HISTO-01). Diagnostic :\n" + json.dumps(diag, ensure_ascii=False, indent=2)
        )

    # --- Action sure : filtre Periode -> "Tout" (les runs E2E datent de 2024,
    #     le defaut 30 jours les masque). Reaction visible : 2 runs listes. ---
    page.select_option("#view-qij [data-historique-filter='period']", "all")
    page.wait_for_function(
        "() => document.querySelectorAll('#view-qij [data-run-id]').length >= 2",
        timeout=8000,
    )

    # --- Action sure : toggle Tableau puis retour Timeline. ---
    page.click("#view-qij [data-historique-view='table']")
    page.wait_for_selector("#view-qij .historique-table", timeout=5000)
    page.click("#view-qij [data-historique-view='timeline']")
    page.wait_for_selector("#view-qij .historique-runs-list", timeout=5000)

    # --- Action sure : selection du run principal -> inspecteur droit peuple. ---
    run_id = e2e_server["run_id"]
    page.click(f"#view-qij [data-run-id='{run_id}']")
    # L'inspecteur est peuple dans [data-v5-right-panel-body] mais le panneau
    # demarre replie (is-collapsed) dans ce contexte E2E : on le deplie via son
    # toggle (action sure supplementaire, reaction visible = classe retiree).
    page.wait_for_selector(
        "[data-v5-right-panel-body] [data-historique-action='view-report']",
        state="attached",
        timeout=8000,
    )
    collapsed = page.evaluate(
        "() => { const p = document.querySelector('[data-v5-right-panel]');"
        " return p ? p.classList.contains('is-collapsed') : null; }"
    )
    if collapsed:
        # NB observe (hors perimetre du groupe, composant shell) : le panneau
        # replie a une largeur de 0 px, son toggle est donc insaisissable a la
        # souris (actionability Playwright echoue) -> clic JS assume ici.
        page.evaluate("() => { const t = document.querySelector('[data-v5-right-panel-toggle]'); if (t) t.click(); }")
        page.wait_for_function(
            "() => { const p = document.querySelector('[data-v5-right-panel]');"
            " return !!p && !p.classList.contains('is-collapsed'); }",
            timeout=5000,
        )
    page.wait_for_selector(
        "[data-v5-right-panel-body] [data-historique-action='view-report']",
        timeout=8000,
    )

    # Labels FR de la timeline (complement runtime de la baseline iter11).
    labels = page.evaluate(
        "() => Array.from(document.querySelectorAll('#view-qij .historique-run-type'))"
        ".map(n => (n.textContent || '').trim())"
    )
    assert labels and all(lbl in {"Application", "Annulation", "Plan"} for lbl in labels), (
        f"Labels run non FR dans la timeline : {labels}"
    )

    # Screenshot nominal de la vue (runs visibles + inspecteur peuple).
    _screenshot(page, "historique.png")

    # undo-apply : legitimement ABSENT (le dataset E2E n'a aucun apply,
    # applied_rows=0 -> le bouton n'est rendu que pour un run apply).
    n_undo = page.evaluate("() => document.querySelectorAll(\"[data-historique-action='undo-apply']\").length")
    assert n_undo == 0, "Bouton undo-apply rendu alors que le run n'a aucun apply"

    # --- Action sure : onglet Log + reload-log (reaction = refetch + rendu). ---
    page.click("[data-v5-right-panel-body] [data-historique-inspector-tab='log']")
    page.wait_for_selector("[data-v5-right-panel-body] [data-historique-action='reload-log']", timeout=5000)
    n_stats_before = len(_api_calls(watch, "run/get_history_stats"))
    page.click("[data-v5-right-panel-body] [data-historique-action='reload-log']")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(_api_calls(watch, "run/get_history_stats")) <= n_stats_before:
        page.wait_for_timeout(100)
    assert len(_api_calls(watch, "run/get_history_stats")) > n_stats_before, (
        "reload-log n'a declenche aucun refetch run/get_history_stats"
    )
    page.wait_for_function(
        """() => {
            const b = document.querySelector('[data-v5-right-panel-body]');
            return !!(b && (b.querySelector('.historique-log-viewer')
                || b.textContent.includes('Aucun log')));
        }""",
        timeout=5000,
    )

    # =======================================================================
    # Action DESTRUCTIVE : delete-run -> modale de confirmation, ANNULEE.
    #   Regle actions dangereuses : compte a rebours 3 s => bouton Confirmer
    #   initialement desactive. On clique ANNULER, jamais Confirmer.
    # =======================================================================
    page.click("[data-v5-right-panel-body] [data-historique-action='delete-run']")
    page.wait_for_selector("#dashDangerModal", timeout=5000)
    modal_title = page.text_content("#dashDangerModalTitle") or ""
    assert "Supprimer le run" in modal_title, f"Titre modale delete-run : {modal_title!r}"
    confirm_disabled = page.evaluate(
        "() => { const b = document.querySelector('#dashDangerModal [data-danger-confirm]');"
        " return b ? b.disabled : null; }"
    )
    assert confirm_disabled is True, (
        "delete-run : le bouton Confirmer devrait etre desactive pendant le "
        "compte a rebours 3 s (regle actions dangereuses)"
    )
    page.click("#dashDangerModal [data-danger-cancel]")
    page.wait_for_selector("#dashDangerModal", state="detached", timeout=5000)
    assert len(_api_calls(watch, "run/delete_run")) == 0, (
        "POST /api/run/delete_run emis alors que la modale a ete ANNULEE"
    )
    remaining = page.evaluate("() => document.querySelectorAll('#view-qij [data-run-id]').length")
    assert remaining >= 2, f"Des runs ont disparu apres l'annulation du delete : {remaining}"

    # --- Action sure : view-report -> page standalone /run/:id puis retour. ---
    page.click("[data-v5-right-panel-body] [data-historique-action='view-report']")
    page.wait_for_selector("#view-qij .historique-run-detail-page", timeout=8000)
    assert "/run/" in page.evaluate("() => window.location.hash")
    page.click("#view-qij [data-historique-back]")
    page.wait_for_function(_HISTORIQUE_SETTLED_JS, timeout=10000)

    # --- Action sure : resume -> route /traitement (reaction = hash + vue). ---
    page.wait_for_selector("[data-v5-right-panel-body] [data-historique-action='resume']", timeout=8000)
    page.click("[data-v5-right-panel-body] [data-historique-action='resume']")
    page.wait_for_function("() => window.location.hash.startsWith('#/traitement')", timeout=8000)

    _assert_console_clean(watch, "historique")


# ---------------------------------------------------------------------------
# 3. /historique — navigation IMMEDIATE apres apparition du shell.
#    GATE de regression LOTC-HISTO-01 (voir docstring module) : ECHOUE tant
#    que la dedup in-flight de core/api.js sert au 2e appelant une promesse
#    portant le signal de navigation (aborte) du 1er appelant.
# ---------------------------------------------------------------------------


@pytest.mark.runtime
def test_lotc_historique_navigation_immediate_charge(dashboard_page) -> None:
    page = dashboard_page
    watch = _attach_watch(page)

    # PAS de boot settle : reproduire la sequence des tests baseline
    # (test_runtime_apply_history_labels / test_runtime_skeleton_lifecycle),
    # navigation dans la fenetre des 800 ms de deblocage token differe.
    _goto_hash(page, "#/historique")
    try:
        page.wait_for_function(_HISTORIQUE_SETTLED_JS, timeout=10000)
    except PWTimeoutError:
        diag = _historique_diag(page, watch)
        _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(_CAPTURES_DIR / "historique_nav_immediate_bug.png"))
        pytest.fail(
            "LOTC-HISTO-01 — #/historique bloque apres navigation immediate "
            "(cause racine : dedup in-flight core/api.js x abort de navigation, "
            "cf docstring module ; preuve : la vue n'obtient JAMAIS de reponse "
            "run/get_dashboard — l'unique fetch, herite du boot accueil via la "
            "dedup, part avec un signal deja aborte — alors que le meme endpoint "
            "repond 200 ok en direct). Diagnostic runtime :\n" + json.dumps(diag, ensure_ascii=False, indent=2)
        )

    # Bug corrige : la vue doit etre rendue proprement, sans erreur console.
    _assert_console_clean(watch, "historique (navigation immediate)")


# ---------------------------------------------------------------------------
# 4. Aller-retour x3 processing <-> historique : ni erreur, ni empilement.
# ---------------------------------------------------------------------------


@pytest.mark.runtime
def test_lotc_aller_retour_x3_sans_empilement(dashboard_page) -> None:
    page = dashboard_page
    watch = _attach_watch(page)
    page.wait_for_timeout(_BOOT_SETTLE_MS)

    for _ in range(3):
        _goto_hash(page, "#/processing")
        page.wait_for_function(_PROCESSING_SETTLED_JS, timeout=10000)
        _goto_hash(page, "#/historique")
        page.wait_for_function(_HISTORIQUE_SETTLED_JS, timeout=10000)

    counts = page.evaluate(
        """() => ({
            processing_shells: document.querySelectorAll('#view-processing .v5-processing-shell').length,
            processing_steppers: document.querySelectorAll('#view-processing .v5-processing-stepper').length,
            historique_views: document.querySelectorAll('#view-qij .historique-view').length,
        })"""
    )
    assert counts["processing_shells"] <= 1, f"Empilement .v5-processing-shell : {counts}"
    assert counts["processing_steppers"] <= 1, f"Empilement stepper : {counts}"
    assert counts["historique_views"] <= 1, f"Empilement .historique-view : {counts}"

    # Fenetre de silence : aucun poll run/get_status residuel (aucun scan
    # n'a ete lance dans ce test — un tick residuel = timer zombie).
    t_quiet = time.monotonic()
    page.wait_for_timeout(3000)
    zombie_polls = [e for e in _api_calls(watch, "run/get_status") if e[0] > t_quiet]
    assert not zombie_polls, f"Poll run/get_status zombie apres navigation : {zombie_polls}"

    _assert_console_clean(watch, "aller-retour x3 processing/historique")
