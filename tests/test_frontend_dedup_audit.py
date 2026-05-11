"""Phase 9 v7.8.0 - audit fige de la duplication composants desktop / dashboard.

CONTEXTE
--------
Le frontend porte deux arborescences de composants :
- `web/components/` (legacy desktop, format IIFE charge par index.html)
- `web/dashboard/components/` (dashboard distant, format ESM)

L'audit v7.7.0 a denonce "22 composants dupliques". L'analyse pixel-par-pixel
confirme cependant : **les 22 noms partages ne sont PLUS identiques en
contenu**. Chacun a evolue independamment (IIFE vs ESM, features dashboard-
specifiques, etc.). Une dedup naive casserait l'une des deux UIs.

Ce test ne FIXE pas la dedup (chantier session dediee : creer
`web/shared/components/` ESM puis adapter desktop pour les consommer via
un loader). Il FIGE l'inventaire actuel pour :

1. Detecter toute NOUVELLE divergence (e.g., un composant `foo.js` qui
   serait ajoute aux deux endroits avec contenu different — implique
   double maintenance et bug fixes oublies dans une copie).
2. Mesurer le poids economisable (~140 KB cumules en v7.8.0) une fois
   la dedup faite.

Si le test echoue parce que la liste a evolue : c'est OK, mettre a jour
les ensembles ci-dessous. Si le test echoue parce qu'un composant DEJA
divergent est devenu identique : c'est mieux, le supprimer de la liste.
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DESKTOP_COMPONENTS = _REPO / "web" / "components"
_DASHBOARD_COMPONENTS = _REPO / "web" / "dashboard" / "components"

# Snapshot 2026-05-11 : 22 noms partages, tous divergents en contenu.
# Cette liste est figee. Toute deviation -> regression a investiguer.
_KNOWN_DIVERGENT_PAIRS = frozenset({
    "auto-tooltip.js",
    "badge.js",
    "breadcrumb.js",
    "command-palette.js",
    "confetti.js",
    "copy-to-clipboard.js",
    "empty-state.js",
    "home-charts.js",
    "home-widgets.js",
    "kpi-card.js",
    "library-components.js",
    "modal.js",
    "notification-center.js",
    "score-v2.js",
    "scraping-status.js",
    "sidebar-v5.js",
    "skeleton.js",
    "sparkline.js",
    "table.js",
    "toast.js",
    "top-bar-v5.js",
    "virtual-table.js",
})


def _shared_names() -> set[str]:
    desktop = {p.name for p in _DESKTOP_COMPONENTS.glob("*.js")}
    dashboard = {p.name for p in _DASHBOARD_COMPONENTS.glob("*.js")}
    return desktop & dashboard


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FrontendDedupInventoryTests(unittest.TestCase):
    def test_shared_names_match_inventory(self) -> None:
        """Detecte les nouveaux composants ajoutes aux deux arborescences."""
        shared = _shared_names()
        unexpected = shared - _KNOWN_DIVERGENT_PAIRS
        gone = _KNOWN_DIVERGENT_PAIRS - shared
        self.assertFalse(
            unexpected,
            f"Nouveaux composants partages (a ajouter a _KNOWN_DIVERGENT_PAIRS si intentionnel): {unexpected}",
        )
        self.assertFalse(
            gone,
            f"Composants dans _KNOWN_DIVERGENT_PAIRS mais absents: {gone}. Retirer de la liste.",
        )

    def test_known_pairs_still_diverge(self) -> None:
        """Verifie que les divergences listees subsistent.

        Si une paire devient identique, le retirer de _KNOWN_DIVERGENT_PAIRS
        (gain dedup acquis).
        """
        identical_now = []
        for name in _KNOWN_DIVERGENT_PAIRS:
            desk = _DESKTOP_COMPONENTS / name
            dash = _DASHBOARD_COMPONENTS / name
            if not (desk.exists() and dash.exists()):
                continue
            if _sha(desk) == _sha(dash):
                identical_now.append(name)
        if identical_now:
            self.fail(
                f"Bonne nouvelle : les paires suivantes ont converge — retirer de "
                f"_KNOWN_DIVERGENT_PAIRS: {identical_now}"
            )

    def test_dedup_savings_potential_measured(self) -> None:
        """Documente le poids dedup potentiel (informatif, pas d'assertion)."""
        total_dashboard = 0
        for name in _KNOWN_DIVERGENT_PAIRS:
            dash = _DASHBOARD_COMPONENTS / name
            if dash.exists():
                total_dashboard += dash.stat().st_size
        # On garde une borne basse pour eviter qu'elle ne disparaisse par erreur
        # si tout le dossier dashboard se vidait silencieusement.
        self.assertGreater(
            total_dashboard,
            50_000,
            "Le total dashboard est anormalement faible — composants supprimes par erreur ?",
        )


if __name__ == "__main__":
    unittest.main()
