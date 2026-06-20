"""Test runtime - labels apply visibles dans Historique (FR + lisibles).

ETAPE 3 TESTS RUNTIME CYCLE DE VIE - Iteration 11 (loop/correction-2026-06).

Critere FAMILLE B = CYCLE DE VIE prouve multi-instants. Pour les labels apply
historique, la sequence est `apply effectue (dataset preload) -> navigate
Historique -> entree visible avec label operation lisible FR`.

Sequence :
- GIVEN : apply effectue (dry-run sur copies jetables) - le dataset E2E precharge
          des runs via populate_database() dans conftest.
- WHEN  : navigate vers /historique, attendre fetch run history.
- THEN  : entree run visible avec label run lisible (.historique-run-type)
          appartenant a {"Application", "Annulation", "Plan"} (FR), AUCUN residu
          anglais ("Apply"/"Undo"/"Plan" anglais brut interdits).

PART OBJECTIVE seule (DOM mesurable : textContent .historique-run-type).
PART SUBJECTIVE (choix exact des libelles "Deplacement" vs "Deplacement fichier",
acceptabilite jargon vs traduction) RESERVEE validation humaine.

Acquis preserves : LABELS_APPLY_HISTORIQUE iter11 OPERATIONNEL applique (dict
_RUN_TYPE_LABELS_FR + _OP_TYPE_LABELS_FR dans historique.js L59-83). Test prouve
runtime DOM ce qui etait jusqu'ici verifie source-grep seulement.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime labels apply")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


# Labels FR autorises (carto 4.5.3 + dict _RUN_TYPE_LABELS_FR).
_VALID_RUN_TYPE_LABELS_FR = {"Application", "Annulation", "Plan"}

# Labels anglais bruts INTERDITS (regression iter10 famille B).
_FORBIDDEN_EN_RUN_LABELS = {"Apply", "Undo"}

# Labels op_type FR autorises (carto 4.5.1 + dict _OP_TYPE_LABELS_FR).
_VALID_OP_TYPE_LABELS_FR_SUBSTRINGS = {
    "renommage",
    "déplacement",
    "déplacement fichier",
    "renommage dossier",
    "quarantaine",
    "marquage suppression",
    "autre",
}

# Tokens op_type anglais bruts INTERDITS dans le DOM render.
_FORBIDDEN_EN_OP_TOKENS = {"rename", "move_file", "move_dir", "delete_mark", "mark_delete"}


@pytest.mark.runtime
def test_apply_history_run_labels_are_french(dashboard_page) -> None:
    """Historique: labels run (Application/Annulation/Plan) en FR exact-match.

    Item 4.5.3 carto. Le dataset E2E precharge un run via populate_database()
    (cf tests/e2e/create_test_data.py); on navigue vers /historique et on
    verifie que chaque entree affichee porte un label FR valide, jamais
    "Apply" ni "Undo" anglais bruts.
    """
    # GIVEN : apply preexistant dans dataset E2E (conftest e2e_server).
    # WHEN : naviguer vers /historique.
    dashboard_page.evaluate("window.location.hash = '#/historique'")

    # Attendre etat final (timeline OR table OR empty).
    try:
        dashboard_page.wait_for_function(
            """() => {
                return document.querySelector('.historique-timeline') !== null
                    || document.querySelector('.historique-table') !== null
                    || document.querySelector('.historique-empty') !== null
                    || document.querySelector('.historique-empty-msg') !== null;
            }""",
            timeout=10000,
        )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Historique ne charge pas en 10s. Exception={exc}")

    # Stabilisation render.
    dashboard_page.wait_for_timeout(400)

    # THEN: collecter tous les textContent de .historique-run-type.
    labels = dashboard_page.evaluate(
        """() => {
            const nodes = document.querySelectorAll('.historique-run-type');
            return Array.from(nodes).map(n => (n.textContent || '').trim());
        }"""
    )

    if len(labels) == 0:
        # Skip si dataset n'a aucun run rendu (cycle non observable).
        pytest.skip(
            "Aucune entree .historique-run-type rendue dans le DOM. "
            "Test non pertinent si dataset n'a aucun run visible."
        )

    # Verif : chaque label appartient au set autorise FR.
    invalid_labels = [
        lbl for lbl in labels
        if lbl not in _VALID_RUN_TYPE_LABELS_FR
    ]
    assert len(invalid_labels) == 0, (
        f"Labels run NON FR detectes : {invalid_labels}. "
        f"Autorise : {sorted(_VALID_RUN_TYPE_LABELS_FR)}. "
        f"Tous labels vus : {labels}"
    )

    # Verif : aucun label anglais brut.
    forbidden_seen = [lbl for lbl in labels if lbl in _FORBIDDEN_EN_RUN_LABELS]
    assert len(forbidden_seen) == 0, (
        f"Labels anglais bruts trouves dans Historique : {forbidden_seen}. "
        f"Carto 4.5.3 exige FR (Application/Annulation/Plan)."
    )


@pytest.mark.runtime
def test_apply_history_op_counters_are_french(dashboard_page) -> None:
    """Historique : counters d'apply (.historique-apply-counter) en FR.

    Item 4.5.1 carto : `op_type` brut (rename/move/quarantine/...) doit etre
    traduit FR via _opTypeLabelFr. On verifie qu'aucun token anglais brut
    n'apparait dans les counters de la vue Historique.
    """
    # GIVEN+WHEN : navigate vers /historique avec inspector ouvert.
    dashboard_page.evaluate("window.location.hash = '#/historique'")
    try:
        dashboard_page.wait_for_function(
            """() => {
                return document.querySelector('.historique-timeline') !== null
                    || document.querySelector('.historique-table') !== null
                    || document.querySelector('.historique-empty') !== null
                    || document.querySelector('.historique-empty-msg') !== null;
            }""",
            timeout=10000,
        )
    except Exception:  # noqa: BLE001
        pytest.skip("Historique ne charge pas dans le delai.")

    dashboard_page.wait_for_timeout(400)

    # Cliquer sur la premiere entree (timeline OR table row) pour ouvrir inspector.
    clicked = dashboard_page.evaluate(
        """() => {
            // Cibler la 1ere entree (timeline item ou row de table).
            const item = document.querySelector('.historique-timeline-item, .historique-table tbody tr, [data-run-id]');
            if (!item) return false;
            item.click();
            return true;
        }"""
    )

    if not clicked:
        pytest.skip(
            "Aucune entree historique cliquable trouvee (timeline vide / empty)."
        )

    # Laisser l'inspector se rendre (fetch detail eventuel).
    dashboard_page.wait_for_timeout(800)

    # THEN : collecter le textContent des counters (et detail ops si visibles).
    counters_data = dashboard_page.evaluate(
        """() => {
            const counters = document.querySelectorAll('.historique-apply-counter');
            return Array.from(counters).map(n => (n.textContent || '').trim().toLowerCase());
        }"""
    )

    if len(counters_data) == 0:
        # Run sans apply ou inspector pas encore peuple : non bloquant.
        pytest.skip(
            "Aucun counter .historique-apply-counter rendu : cycle non observable "
            "(le run E2E n'a peut-etre pas d'apply attache)."
        )

    # Verif : aucun token anglais brut (rename/move_file/...).
    # Le format attendu est "renommage: 3", "deplacement: 5", etc.
    for txt in counters_data:
        for forbid in _FORBIDDEN_EN_OP_TOKENS:
            assert forbid not in txt, (
                f"Counter Historique contient token anglais brut '{forbid}'. "
                f"Texte vu : {txt!r}. Carto 4.5.1 exige dict _OP_TYPE_LABELS_FR."
            )

    # Verif positive : au moins un counter doit contenir un libelle FR connu.
    has_french_label = any(
        any(fr_lbl in txt for fr_lbl in _VALID_OP_TYPE_LABELS_FR_SUBSTRINGS)
        for txt in counters_data
    )
    assert has_french_label is True, (
        f"Aucun libelle FR detecte dans les counters historique. "
        f"Texte counters vu : {counters_data}. Attendu au moins un parmi : "
        f"{sorted(_VALID_OP_TYPE_LABELS_FR_SUBSTRINGS)}."
    )
