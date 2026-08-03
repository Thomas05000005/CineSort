"""Lot C (verif totale 2026-07) — Sweep runtime Playwright : vues #/qualite et #/doublons.

Regles du sweep (permanent) :
- navigation par ``location.hash`` + attente d'un etat stable de la vue ;
- capture ``page.on('console')`` + ``pageerror`` : 0 erreur inattendue
  (liste blanche NOMINATIVE du bruit connu, commentee ci-dessous) ;
- chaque action SURE de la vue est cliquee (source : matrice
  docs/internal/verif_totale_2026_07/matrices/m4_actions_ui.json) avec
  verification d'une reaction visible ;
- actions avec confirmation (recompute, auto-decide-all) : cliquer, VERIFIER
  que la modale ``dangerConfirmModal`` apparait, puis ANNULER — ne JAMAIS
  confirmer ;
- decisions "Garder A/B" : sures et reversibles (run/mark_duplicate_winner
  re-appelable avec l'autre side) — on prouve la reversibilite A -> B ;
- aller-retour navigation x3 : pas d'erreur console ni d'empilement de vues ;
- screenshots dans docs/internal/verif_totale_2026_07/captures_runtime/<vue>.png.

Dataset : fixture e2e_server (conftest) = serveur ephemere + 15 films mock
(create_test_data), dont "Dune Part Two" en double (rows 12/13) -> 1 groupe
de doublons attendu dans #/doublons.

BUGS CONNUS DOCUMENTES PAR CE SWEEP (a reporter, pas a corriger ici) :

[LOTC-F1] Race dedup in-flight + nav-abort -> vue bloquee sur skeleton.
    accueil.js:1334-1337 (init de la route par defaut) lance run/get_dashboard,
    run/get_global_stats, settings/get_settings (+ get_update_info) avec le
    signal de navigation courant. Si on navigue vers #/qualite ou #/doublons
    PENDANT que ce batch est in-flight, le router aborte le signal
    (nav-abort.abortCurrent) mais _dedupExec (core/api.js:88-96) rend au nouvel
    appelant la promesse in-flight du MEME endpoint, liee au signal aborte
    (l'entree n'est purgee qu'au settle, microtask apres l'abort) -> AbortError
    immediat sans AUCUN nouveau fetch. Symptomes observes (probe fetch-log) :
      - #/qualite : initQualite sort en silence -> skeleton --loading permanent ;
      - #/doublons : _loadGroups perd le run_id -> banniere trompeuse
        "Aucun run actif. Lance un scan d'abord.".
    Workaround documente ici : ``_settle()`` avant navigation + RE-NAVIGATION
    (max 3 tentatives) si la vue reste bloquee — a retirer quand le bug sera
    corrige (les retries deviendront des no-ops).

[LOTC-F2] Dataset mock e2e avec tiers legacy pre-migration-011.
    tests/e2e/create_test_data.py::_tier_from_score ecrit Premium/Bon/Moyen/
    Faible dans quality_reports alors que la migration 011 garantit des tiers
    canoniques (Platinum/Gold/Silver/Bronze/Reject) dans toute base migree.
    Consequence : run/get_global_stats.tier_distribution renvoie des cles
    legacy que la vue #/qualite ignore (_TIER_ORDER canonique) -> header
    "0 films classés" + section Distribution en etat vide malgre 15 films
    scores (le Score moyen, lui, est correct). Les asserts distribution
    ci-dessous acceptent donc les DEUX etats (barres OU etat vide explicite).

Lancer :
  .venv/Scripts/python.exe -X utf8 -m pytest tests/e2e_dashboard/test_lotc_sweep_qualite_doublons.py -q
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPTURES_DIR = _REPO_ROOT / "docs" / "internal" / "verif_totale_2026_07" / "captures_runtime"

# ---------------------------------------------------------------------------
# Liste blanche NOMINATIVE du bruit console connu.
# Chaque entree doit etre un fragment exact du message + un commentaire
# expliquant pourquoi ce bruit est tolere. NE PAS ajouter de motif generique.
# ---------------------------------------------------------------------------
_CONSOLE_WHITELIST: tuple = (
    # (aucune entree pour l'instant — le sweep doit etre 100% propre)
)


def _attach_console_capture(page) -> List[str]:
    """Capture les erreurs console + pageerror. A appeler AVANT la navigation."""
    errors: List[str] = []

    def _on_console(msg):
        if msg.type == "error":
            errors.append(f"console.error: {msg.text}")

    page.on("console", _on_console)
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    return errors


def _unexpected(errors: List[str]) -> List[str]:
    return [e for e in errors if not any(w in e for w in _CONSOLE_WHITELIST)]


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------


def _settle(page) -> None:
    """Attend que les fetchs de la vue courante soient termines.

    Contournement documente du bug [LOTC-F1] (cf. docstring module) : naviguer
    pendant qu'un run/get_global_stats ou run/get_dashboard est in-flight
    laisse la vue cible bloquee sur son skeleton (dedup + signal aborte).
    """
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        # Un poller periodique peut empecher le networkidle strict : petit
        # tampon fixe en repli, suffisant pour vider les fetchs de vue.
        page.wait_for_timeout(1500)


def _set_hash(page, route: str) -> None:
    """Change le hash ; si le hash est deja celui-ci, force un re-resolve
    (meme pattern que router.navigateTo) pour re-initialiser la vue."""
    page.evaluate(
        """(h) => {
            if (window.location.hash === h) {
                window.dispatchEvent(new HashChangeEvent('hashchange'));
            } else {
                window.location.hash = h;
            }
        }""",
        f"#{route}",
    )


def _goto_qualite(page) -> None:
    from playwright.sync_api import TimeoutError as PWTimeoutError

    _settle(page)
    # [LOTC-F1] : si la navigation tombe pendant un batch de fetchs in-flight
    # de la vue precedente, initQualite recoit une promesse dedup deja abortee
    # et la vue reste sur son skeleton. On re-navigue (max 3 tentatives) — la
    # re-init repart alors sur un fetch frais.
    for attempt in range(3):
        _set_hash(page, "/qualite")
        try:
            # Vue stable = skeleton --loading remplace par le rendu final (ou l'erreur).
            page.wait_for_selector(".qualite-view:not(.qualite-view--loading)", timeout=10000)
            page.wait_for_timeout(300)
            return
        except PWTimeoutError:
            continue
    raise AssertionError("Vue #/qualite bloquee sur son skeleton apres 3 tentatives (cf. bug LOTC-F1)")


def _goto_doublons(page, timeout: int = 45000) -> None:
    from playwright.sync_api import TimeoutError as PWTimeoutError

    _settle(page)
    # [LOTC-F1] : meme retry que _goto_qualite. Le symptome cote Doublons est
    # une banniere trompeuse "Aucun run actif" (run_id perdu sur AbortError).
    for attempt in range(3):
        _set_hash(page, "/doublons")
        try:
            # check_duplicates peut prendre quelques secondes au 1er scan
            # (cache R6-C ensuite). Etat stable = liste / vide / erreur.
            page.wait_for_selector(
                ".doublons-list, .doublons-empty, .doublons-view--error, .doublons-error",
                timeout=timeout,
            )
            page.wait_for_timeout(300)
        except PWTimeoutError:
            continue
        error_el = page.query_selector(".doublons-error")
        if attempt < 2 and error_el is not None and "Aucun run actif" in (error_el.inner_text() or ""):
            # Symptome LOTC-F1 : le mock a toujours un run -> re-naviguer.
            continue
        return
    raise AssertionError("Vue #/doublons indisponible apres 3 tentatives (cf. bug LOTC-F1)")


def _screenshot(page, name: str) -> None:
    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_CAPTURES_DIR / f"{name}.png"), full_page=True)


def _count(page, selector: str) -> int:
    return page.evaluate("(sel) => document.querySelectorAll(sel).length", selector)


def _active_view_id(page) -> str:
    return page.evaluate("() => { const el = document.querySelector('.main .view.active'); return el ? el.id : ''; }")


# ---------------------------------------------------------------------------
# Vue #/qualite
# ---------------------------------------------------------------------------


class TestQualiteSweep:
    def test_qualite_rendu_kpi_et_screenshot(self, dashboard_page):
        """#/qualite : rendu stable, 6 sections, KPI non-zero, 0 erreur console."""
        errors = _attach_console_capture(dashboard_page)
        _goto_qualite(dashboard_page)

        # Pas de vue en erreur
        assert _count(dashboard_page, ".qualite-view--error") == 0, "Vue Qualite en erreur"

        # Header KPI : "<total> films classés · Score moyen <avg>/100 · Santé <pct>%"
        summary = dashboard_page.inner_text(".qualite-summary")
        m_avg = re.search(r"Score moyen\s*([\d.,]+)\s*/\s*100", summary)
        assert m_avg, f"KPI 'Score moyen' introuvable dans le header: {summary!r}"
        avg_score = float(m_avg.group(1).replace(",", "."))
        # Dataset mock : 15 quality_reports -> le score moyen DOIT etre non-zero.
        assert avg_score > 0, f"KPI 'Score moyen' a zero avec 15 films mock: {summary!r}"

        # Les 6 sections de la spec 10-qualite sont presentes (ni absentes ni dupliquees).
        for sel, label in [
            (".qualite-distribution", "Distribution"),
            (".qualite-reject", "A remplacer"),
            (".qualite-sagas", "Sagas"),
            (".qualite-subs", "Subs FR"),
            (".qualite-decades", "Decennies"),
            (".qualite-evolution", "Evolution"),
        ]:
            assert _count(dashboard_page, sel) == 1, f"Section {label} absente ou dupliquee"

        # Distribution tiers : [LOTC-F2] le mock ecrit des tiers legacy
        # (Premium/Bon/...) que la vue ignore -> etat vide "Aucun film classé"
        # aujourd'hui. On accepte les DEUX etats coherents : des barres non
        # vides (mock corrige) OU l'etat vide EXPLICITE (jamais une section
        # cassee/silencieuse).
        tier_rows = _count(dashboard_page, ".qualite-tier-row")
        if tier_rows == 0:
            dist_text = dashboard_page.inner_text(".qualite-distribution")
            assert "Aucun film classé" in dist_text, (
                f"Distribution sans barre ET sans etat vide explicite: {dist_text!r}"
            )

        # Decennies : le mock couvre 1999..2024 -> au moins 1 barre attendue.
        assert _count(dashboard_page, ".qualite-decade-row") > 0, "Aucune barre decennie"

        _screenshot(dashboard_page, "qualite")

        unexpected = _unexpected(errors)
        assert not unexpected, f"Erreurs console/pageerror sur #/qualite: {unexpected}"

    def test_qualite_actions_sures(self, dashboard_page):
        """#/qualite : clic des actions sures + confirmation ANNULEE du recompute."""
        errors = _attach_console_capture(dashboard_page)
        _goto_qualite(dashboard_page)

        # --- Action "filters" (sure) : ouvre le drawer, reaction = drawer visible.
        dashboard_page.click('[data-qualite-action="filters"]')
        dashboard_page.wait_for_selector(".qualite-drawer", timeout=5000)
        dashboard_page.click("[data-qualite-drawer-close]")
        dashboard_page.wait_for_selector(".qualite-drawer-overlay", state="detached", timeout=5000)

        # --- Switch periode Evolution (sure) : 7j devient actif apres re-render.
        dashboard_page.click('[data-qualite-period="7"]')
        dashboard_page.wait_for_selector('.qualite-period-btn--active[data-qualite-period="7"]', timeout=10000)

        # --- Action "recompute" (avec confirmation) :
        # cliquer -> la modale dangerConfirmModal DOIT apparaitre -> ANNULER.
        dashboard_page.click('[data-qualite-action="recompute"]')
        dashboard_page.wait_for_selector(".danger-modal-overlay", timeout=5000)
        title = dashboard_page.inner_text(".danger-modal-title")
        assert "Re-calculer" in title, f"Titre de confirmation inattendu: {title!r}"
        dashboard_page.click("[data-danger-cancel]")
        dashboard_page.wait_for_selector(".danger-modal-overlay", state="detached", timeout=5000)

        # --- Clic sur une barre tier (sure) : selection inspecteur + navigation
        # vers #/bibliotheque. Conditionnel : aucune barre avec le mock actuel
        # (cf. [LOTC-F2]) — la branche s'activera quand le mock sera corrige.
        if _count(dashboard_page, ".qualite-tier-row") > 0:
            dashboard_page.click(".qualite-tier-row")
            dashboard_page.wait_for_function("() => window.location.hash.includes('/bibliotheque')", timeout=5000)
            _goto_qualite(dashboard_page)

        # --- Clic sur une decennie (sure) : navigation vers #/bibliotheque.
        assert _count(dashboard_page, ".qualite-decade-row") > 0, "Aucune barre decennie"
        dashboard_page.click(".qualite-decade-row")
        dashboard_page.wait_for_function("() => window.location.hash.includes('/bibliotheque')", timeout=5000)
        _goto_qualite(dashboard_page)

        # --- Action "configure-subs" (sure) : navigation vers #/parametres.
        dashboard_page.click('[data-qualite-action="configure-subs"]')
        dashboard_page.wait_for_function("() => window.location.hash.includes('/parametres')", timeout=5000)
        _goto_qualite(dashboard_page)

        unexpected = _unexpected(errors)
        assert not unexpected, f"Erreurs console/pageerror actions #/qualite: {unexpected}"


# ---------------------------------------------------------------------------
# Vue #/doublons
# ---------------------------------------------------------------------------


class TestDoublonsSweep:
    def test_doublons_rendu_groupes_et_screenshot(self, dashboard_page):
        """#/doublons : groupes par identite detectes (Dune Part Two x2), 0 erreur."""
        errors = _attach_console_capture(dashboard_page)
        _goto_doublons(dashboard_page)

        assert _count(dashboard_page, ".doublons-view--error") == 0, "Vue Doublons en erreur"
        assert _count(dashboard_page, ".doublons-error") == 0, "Banniere d'erreur Doublons"

        # Dataset mock : "Dune Part Two" (2024) present en 2160p ET 1080p
        # -> au moins 1 groupe par identite attendu.
        cards = _count(dashboard_page, ".doublons-card")
        assert cards >= 1, "Aucun groupe de doublons alors que le mock contient Dune Part Two x2"
        titles = dashboard_page.inner_text(".doublons-list")
        assert "Dune Part Two" in titles, f"Groupe 'Dune Part Two' absent: {titles[:200]!r}"

        # KPI header non-zero : nombre de groupes.
        header = dashboard_page.inner_text(".doublons-summary")
        m_groups = re.search(r"(\d+)\s*groupe", header)
        assert m_groups, f"KPI groupes introuvable: {header!r}"
        assert int(m_groups.group(1)) >= 1, f"KPI groupes a zero: {header!r}"

        _screenshot(dashboard_page, "doublons")

        unexpected = _unexpected(errors)
        assert not unexpected, f"Erreurs console/pageerror sur #/doublons: {unexpected}"

    def test_doublons_actions_sures_et_decisions(self, dashboard_page):
        """#/doublons : refresh, filtre, auto-decide (ANNULE), Garder A puis B, go-apply."""
        errors = _attach_console_capture(dashboard_page)
        _goto_doublons(dashboard_page)

        # --- Action "refresh" (sure) : re-scan force, reaction = etat charge a nouveau.
        dashboard_page.click('[data-doublons-action="refresh"]')
        dashboard_page.wait_for_selector(".doublons-list, .doublons-empty", timeout=45000)
        dashboard_page.wait_for_timeout(300)
        assert _count(dashboard_page, ".doublons-card") >= 1, "Groupes perdus apres refresh"

        # --- Filtre (sure) : "A decider" doit encore montrer le groupe non decide.
        dashboard_page.select_option("[data-doublons-filter]", "pending")
        dashboard_page.wait_for_timeout(300)
        pending_cards = _count(dashboard_page, ".doublons-card")
        dashboard_page.select_option("[data-doublons-filter]", "all")
        dashboard_page.wait_for_timeout(300)
        assert _count(dashboard_page, ".doublons-card") >= pending_cards, (
            "Le filtre 'Tous' montre moins de groupes que 'A decider'"
        )

        # --- Action "auto-decide-all" (avec confirmation) : cliquer -> la modale
        # dangerConfirmModal DOIT apparaitre -> ANNULER (jamais confirmer).
        auto_btn = dashboard_page.query_selector('[data-doublons-action="auto-decide-all"]')
        assert auto_btn is not None, "Bouton auto-decider absent"
        if not auto_btn.is_disabled():
            auto_btn.click()
            dashboard_page.wait_for_selector(".danger-modal-overlay", timeout=5000)
            title = dashboard_page.inner_text(".danger-modal-title")
            assert "Auto-décider" in title, f"Titre confirmation inattendu: {title!r}"
            dashboard_page.click("[data-danger-cancel]")
            dashboard_page.wait_for_selector(".danger-modal-overlay", state="detached", timeout=5000)
            # Annule -> AUCUNE decision ne doit avoir ete posee.
            assert _count(dashboard_page, ".duplicate-decision-badge--decided") == 0, (
                "Une decision a ete posee malgre l'annulation de l'auto-decide"
            )

        # --- Decision "Garder A" (sure et REVERSIBLE) : badge "Décidé : Garder A".
        dashboard_page.click('[data-doublons-card-action="keep"][data-side="a"]')
        dashboard_page.wait_for_selector('.duplicate-decision-badge--decided:has-text("Garder A")', timeout=45000)
        # _decideFromCard resynchronise ensuite via un re-scan force (R6-C) :
        # attendre la fin du cycle avant le clic suivant (DOM re-cree).
        dashboard_page.wait_for_timeout(1500)
        dashboard_page.wait_for_selector(".doublons-list", timeout=45000)

        # --- Reversibilite : "Garder B" re-appelle mark_duplicate_winner.
        dashboard_page.click('[data-doublons-card-action="keep"][data-side="b"]')
        dashboard_page.wait_for_selector('.duplicate-decision-badge--decided:has-text("Garder B")', timeout=45000)
        dashboard_page.wait_for_timeout(1500)
        dashboard_page.wait_for_selector(".doublons-list", timeout=45000)

        # --- Action "go-apply" : tous les groupes decides -> CTA pret. Avec 0
        # groupe pendant, la navigation part vers #/traitement sans modale
        # (la modale go-apply ne se montre que s'il reste des groupes pendants).
        dashboard_page.wait_for_selector(".doublons-apply-cta--ready", timeout=15000)
        dashboard_page.click('[data-doublons-action="go-apply"]')
        dashboard_page.wait_for_function("() => window.location.hash.includes('/traitement')", timeout=5000)
        # Retour sur la vue Doublons (cache R6-C -> restitution instantanee).
        _goto_doublons(dashboard_page)

        unexpected = _unexpected(errors)
        assert not unexpected, f"Erreurs console/pageerror decisions #/doublons: {unexpected}"

    def test_doublons_comparateur_et_overlays(self, dashboard_page):
        """#/doublons : modal comparateur (onglets Frames/Audio), perceptuel, fiche."""
        errors = _attach_console_capture(dashboard_page)
        _goto_doublons(dashboard_page)

        # --- Action "compare" (sure) : ouvre le modal comparateur.
        dashboard_page.click('[data-doublons-card-action="compare"]')
        dashboard_page.wait_for_selector(".duplicate-modal-overlay", timeout=10000)

        # Onglet Frames : le pane change et devient actif (lazy load ; sur le
        # dataset mock les fichiers video n'existent pas -> etat erreur/vide
        # PROPRE attendu, pas de crash).
        dashboard_page.click('[data-duplicate-tab="frames"]')
        dashboard_page.wait_for_selector('.duplicate-modal-tab.is-active[data-duplicate-tab="frames"]', timeout=5000)
        dashboard_page.wait_for_selector('.duplicate-modal-tab-content[data-tab="frames"]', timeout=20000)

        # Onglet Audio : idem.
        dashboard_page.click('[data-duplicate-tab="audio"]')
        dashboard_page.wait_for_selector('.duplicate-modal-tab.is-active[data-duplicate-tab="audio"]', timeout=5000)
        dashboard_page.wait_for_selector('.duplicate-modal-tab-content[data-tab="audio"]', timeout=20000)

        # Fermer SANS decider (les boutons Garder du footer ne sont pas cliques ici).
        dashboard_page.click("[data-duplicate-close]")
        dashboard_page.wait_for_selector(".duplicate-modal-overlay", state="detached", timeout=5000)

        # --- Action "perceptual" (sure) : sur la route /doublons, l'analyse
        # perceptuelle s'ouvre en mode A (inspecteur droit elargi), PAS en
        # overlay (cf. perceptual-modal.js _VIEWS_INSPECTOR). Reaction visible
        # = contenu perceptuel + bouton Fermer dans le right-panel.
        # On NE clique PAS "Lancer l'analyse" (action longue, hors perimetre sweep).
        dashboard_page.click('[data-doublons-card-action="perceptual"]')
        dashboard_page.wait_for_selector("[data-perceptual-close]", timeout=10000)
        dashboard_page.click("[data-perceptual-close]")
        dashboard_page.wait_for_selector("[data-perceptual-close]", state="detached", timeout=5000)

        # --- Action "detail" (sure) : fiche film en overlay mode C, Esc ferme.
        dashboard_page.click('[data-doublons-card-action="detail"]')
        dashboard_page.wait_for_selector(".film-detail-modal-overlay", timeout=10000)
        dashboard_page.keyboard.press("Escape")
        dashboard_page.wait_for_selector(".film-detail-modal-overlay", state="detached", timeout=5000)

        # --- Inspecteur droit : action "compare" (sure) depuis le right panel.
        insp_btn = dashboard_page.query_selector('[data-doublons-inspector-action="compare"]')
        if insp_btn is not None:
            insp_btn.click()
            dashboard_page.wait_for_selector(".duplicate-modal-overlay", timeout=10000)
            dashboard_page.click("[data-duplicate-close]")
            dashboard_page.wait_for_selector(".duplicate-modal-overlay", state="detached", timeout=5000)

        unexpected = _unexpected(errors)
        assert not unexpected, f"Erreurs console/pageerror overlays #/doublons: {unexpected}"


# ---------------------------------------------------------------------------
# Aller-retour navigation x3
# ---------------------------------------------------------------------------


class TestNavigationAllerRetour:
    def test_navigation_qualite_doublons_x3(self, dashboard_page):
        """3 allers-retours #/qualite <-> #/doublons : 0 erreur, pas d'empilement.

        NB : le router masque les containers de vue sans les vider — un
        `.qualite-view` cache peut legitimement rester dans le DOM apres avoir
        quitte la vue. L'empilement se mesure donc par le NOMBRE d'instances
        (<= 1 par vue) + le container actif attendu.
        """
        errors = _attach_console_capture(dashboard_page)

        for i in range(3):
            _goto_qualite(dashboard_page)
            assert _count(dashboard_page, ".qualite-view") == 1, f"Empilement vue Qualite au tour {i + 1}"
            assert _active_view_id(dashboard_page) == "view-qij", (
                f"Container actif inattendu apres #/qualite au tour {i + 1}"
            )

            _goto_doublons(dashboard_page)
            assert _count(dashboard_page, ".doublons-view") == 1, f"Empilement vue Doublons au tour {i + 1}"
            assert _active_view_id(dashboard_page) == "view-library", (
                f"Container actif inattendu apres #/doublons au tour {i + 1}"
            )
            # Aucun overlay residuel ne doit s'empiler pendant les allers-retours.
            assert _count(dashboard_page, ".danger-modal-overlay") == 0
            assert _count(dashboard_page, ".duplicate-modal-overlay") == 0

        unexpected = _unexpected(errors)
        assert not unexpected, f"Erreurs console/pageerror navigation x3: {unexpected}"
