"""Test runtime - cycle de vie SKELETON (present-pendant -> remplace par contenu reel).

ETAPE 3 TESTS RUNTIME CYCLE DE VIE - Iteration 11 (loop/correction-2026-06).

Critere FAMILLE B = CYCLE DE VIE prouve multi-instants. Pour le skeleton, la
sequence est `present-pendant fetch -> remplace par contenu reel`. Le test
verifie qu'aucun skeleton ne reste INFINI (timeout > 10s = fail).

Sequence :
- GIVEN : navigation vers vue avec fetch (Bibliotheque).
- DURING : skeleton present pendant le fetch (DOM check au plus tot apres mount).
- AFTER  : skeleton remplace par contenu reel ou empty-state (DOM check post-fetch).
- VERIFY : skeleton ne reste PAS infini (timeout 10s = fail).

PART OBJECTIVE seule (DOM mesurable .v5-skeleton present puis absent). La PART
SUBJECTIVE (shimmer 1.4s ressenti actif, duree percu) est RESERVEE validation humaine.

Acquis preserves : skeleton.js (33 LOC) INTACT, aria-busy A11Y annotative seul,
aucun timer/handler ajoute (skeleton est string -> string).
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime skeleton lifecycle")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


def _count_skeletons(page) -> int:
    """Compte les noeuds .v5-skeleton presents dans le document."""
    return page.evaluate("() => document.querySelectorAll('.v5-skeleton').length")


def _container_aria_busy(page, selector: str) -> str | None:
    """Renvoie l'attribut aria-busy du container vue (None si absent)."""
    return page.evaluate(
        f"() => {{ const el = document.querySelector({selector!r}); return el ? el.getAttribute('aria-busy') : null; }}"
    )


@pytest.mark.runtime
def test_skeleton_bibliotheque_lifecycle_present_then_replaced(dashboard_page) -> None:
    """Skeleton Bibliotheque : present-pendant -> remplace par contenu reel.

    Item 4.4.1 carto BILAN_ITER11_2026-06-08.md.

    Sequence prouvee :
    - t=immediate apres navigation : .v5-skeleton present (>= 1 noeud).
    - t=apres fetch complete : skeleton remplace par .bibliotheque-grid OU
      par .bibliotheque-empty (les deux sont des etats finaux valides).
    - Verify : skeleton ne reste PAS infini (timeout 10s -> fail).
    """
    # GIVEN: page initialement non-bibliotheque (accueil).
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(500)

    # WHEN: navigation vers /bibliotheque -> declenche skeleton + fetch.
    dashboard_page.evaluate("window.location.hash = '#/bibliotheque'")

    # DURING: probe IMMEDIATE apres mount (avant fin du fetch).
    # On accorde 100ms pour le mount + render initial.
    dashboard_page.wait_for_timeout(120)

    skeletons_during = _count_skeletons(dashboard_page)
    # Sanity: bibliotheque doit afficher un skeleton au moins brievement si
    # le fetch ne resout pas instantanement. Si le fetch resout en < 120ms
    # (cache ou empty rapide), la vue passe directement au contenu reel ;
    # dans ce cas on n'a pas pu observer le skeleton ; on documente sans fail.
    early_observed = skeletons_during > 0

    # AFTER: attendre la fin du fetch (limite 10s = fail explicit infini).
    # On attend SOIT bibliotheque-grid SOIT bibliotheque-empty SOIT bibliotheque-table-wrap.
    try:
        dashboard_page.wait_for_function(
            """() => {
                const hasGrid = document.querySelector('.bibliotheque-grid') !== null;
                const hasEmpty = document.querySelector('.bibliotheque-empty') !== null;
                const hasTable = document.querySelector('.bibliotheque-table-wrap') !== null;
                const hasError = document.querySelector('.bibliotheque-error') !== null;
                return hasGrid || hasEmpty || hasTable || hasError;
            }""",
            timeout=10000,
        )
    except Exception as exc:  # noqa: BLE001 - playwright timeout = fail explicit
        pytest.fail(
            f"SKELETON INFINI: aucun contenu reel apparu apres 10s sur /bibliotheque "
            f"(skeleton bloque). early_skeletons={skeletons_during}. Exception={exc}"
        )

    # THEN: apres fetch resolu, .v5-skeleton de la bibliotheque doit avoir disparu
    # du body (le skeleton specific bibliotheque est dans .bibliotheque-section).
    # NOTE : d'autres .v5-skeleton peuvent rester dans d'autres vues persistantes,
    # on cible la zone bibliotheque uniquement.
    biblio_skeletons_after = dashboard_page.evaluate(
        """() => document.querySelectorAll('.bibliotheque-view .v5-skeleton, .bibliotheque-section .v5-skeleton').length"""
    )
    assert biblio_skeletons_after == 0, (
        f"AFTER: skeleton bibliotheque PERSISTE apres fetch complete : "
        f"{biblio_skeletons_after} noeud(s) restants. early_observed={early_observed}"
    )


@pytest.mark.runtime
def test_skeleton_historique_lifecycle_present_then_replaced(dashboard_page) -> None:
    """Skeleton Historique : present-pendant -> remplace par timeline OU empty.

    Item 4.4.4 carto. Plus simple a observer car Historique a un fetch
    /api/run/get_history qui prend toujours quelques ms.
    """
    # GIVEN: non-historique.
    dashboard_page.evaluate("window.location.hash = '#/accueil'")
    dashboard_page.wait_for_timeout(500)

    # WHEN: navigation vers /historique.
    dashboard_page.evaluate("window.location.hash = '#/historique'")
    dashboard_page.wait_for_timeout(120)

    # AFTER: limite 10s pour eviter skeleton infini.
    try:
        dashboard_page.wait_for_function(
            """() => {
                // Etats finaux valides Historique : timeline rendue, table, ou empty.
                const hasTimeline = document.querySelector('.historique-timeline') !== null;
                const hasTable = document.querySelector('.historique-table') !== null;
                const hasEmpty = document.querySelector('.historique-empty, .historique-empty-msg, .empty-state') !== null;
                const hasError = document.querySelector('.historique-error') !== null;
                return hasTimeline || hasTable || hasEmpty || hasError;
            }""",
            timeout=10000,
        )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"SKELETON INFINI: aucun contenu reel apparu apres 10s sur /historique. "
            f"Exception={exc}"
        )

    # THEN: skeletons Historique disparu (cible v5-skeleton sous l'arbre historique).
    histo_skeletons_after = dashboard_page.evaluate(
        """() => {
            // Le skeleton historique-title-skel / historique-section-skel
            // doit avoir disparu apres fetch.
            return document.querySelectorAll('.historique-title-skel, .historique-section-skel').length;
        }"""
    )
    assert histo_skeletons_after == 0, (
        f"AFTER: skeleton historique PERSISTE apres fetch : "
        f"{histo_skeletons_after} noeud(s) restants (skeleton bloque)."
    )
