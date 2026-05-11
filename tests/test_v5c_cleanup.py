"""V5C-01 — Verifie que les vues v4 dashboard RESTAUREES sont preservees.

CONTEXTE (V1-05 Polish Total v7.7.0) :
Initialement, V5C-01 (3 mai 2026) supprimait les vues v4 dashboard apres
activation v5 (V5B). Toutefois, un incident dashboard a montre que la v5
perdait trop de fonctionnalites par rapport aux vues v4 originales.

Decision actee post-incident : RESTAURER les vues v4 dashboard et faire
pointer les routes principales vers ces vues. Cf commentaire dans
`web/dashboard/app.js` :

    "// === Vues v4 RESTAUREES (post-fix : la v5 perdait trop de
    fonctionnalites) ==="

Ce module a donc ete inverse en V1-05 : on verifie maintenant que les vues
v4 EXISTENT BIEN et que `app.js` les IMPORTE BIEN, plutot que l'inverse.

Selecteurs CSS sidebar v4 statique (`.sidebar-group`, `.sidebar-name`,
`.sidebar-desc`) restent supprimes : la sidebar est mountee dynamiquement
par `sidebar-v5.js` et le DOM statique legacy n'est plus utilise.
"""

from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]


# V1-05 : ces vues v4 ont ete RESTAUREES post-incident V5. Elles doivent
# exister et etre importees par app.js. La liste reflete l'etat reel du
# repo apres le revert.
RESTORED_V4_VIEWS = [
    "web/dashboard/views/quality.js",
    "web/dashboard/views/settings.js",
    "web/dashboard/views/status.js",
    "web/dashboard/views/help.js",
    "web/dashboard/views/library/library.js",
    "web/dashboard/views/library/lib-analyse.js",
    "web/dashboard/views/library/lib-apply.js",
    "web/dashboard/views/library/lib-duplicates.js",
    "web/dashboard/views/library/lib-validation.js",
    "web/dashboard/views/library/lib-verification.js",
]

# Vues v4 supprimees pour de vrai et NON restaurees (consolidation V7-fusion
# Phase 3 : leurs fonctionnalites sont integrees dans QIJ ou Library workflow).
# Garde-fou : on s'assure qu'elles ne reapparaissent pas accidentellement et
# que app.js ne les importe plus.
TRULY_REMOVED_VIEWS = [
    "web/dashboard/views/review.js",  # FIX-4 CRIT-5 : section /review supprimee
    "web/dashboard/views/runs.js",    # FIX-4 CRIT-5 : section /runs supprimee
]


REMOVED_CSS_SELECTORS = [
    ".sidebar-group",
    ".sidebar-name",
    ".sidebar-desc",
]


KEPT_FILES = [
    # Conserves : dependances actives qui n'ont pas (encore) ete portees en v5.
    "web/dashboard/views/about.js",
    "web/dashboard/views/demo-wizard.js",
    "web/dashboard/views/library.js",
]


class V5CCleanupTests(unittest.TestCase):
    """Garde-fou V1-05 : verifie l'etat post-revert des vues v4 RESTAUREES."""

    def test_v4_views_restored_exist(self) -> None:
        """Les vues v4 dashboard RESTAUREES doivent exister sur disque.

        Decision actee post-incident V5 : v4 plus complete que v5 sur
        plusieurs vues, donc on les a remises en place. Cf app.js
        commentaire "Vues v4 RESTAUREES".
        """
        for rel in RESTORED_V4_VIEWS:
            with self.subTest(file=rel):
                self.assertTrue(
                    (_ROOT / rel).exists(),
                    f"V1-05 : la vue v4 RESTAUREE {rel} doit exister "
                    f"(decision post-incident V5)",
                )

    def test_v4_library_folder_restored(self) -> None:
        """Le dossier library/ (orchestrateur v4) doit etre restaure."""
        self.assertTrue(
            (_ROOT / "web" / "dashboard" / "views" / "library").exists(),
            "V1-05 : web/dashboard/views/library/ doit exister "
            "(restaure post-incident V5)",
        )

    def test_kept_files_still_exist(self) -> None:
        """Les fichiers volontairement conserves ne doivent pas etre touches."""
        for rel in KEPT_FILES:
            with self.subTest(file=rel):
                self.assertTrue(
                    (_ROOT / rel).exists(),
                    f"V5C-01 : le fichier {rel} ne doit pas etre supprime (encore reference)",
                )

    def test_v4_css_selectors_removed(self) -> None:
        """Les selecteurs sidebar v4 (statique) sont retires de styles.css."""
        css = (_ROOT / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        for sel in REMOVED_CSS_SELECTORS:
            with self.subTest(selector=sel):
                # Les commentaires de cleanup peuvent mentionner les classes ; on
                # cherche les usages reels (regle CSS) avec accolade ouvrante.
                self.assertNotIn(f"{sel} {{", css, f"Selecteur CSS encore present : {sel} {{")
                self.assertNotIn(f"{sel}{{", css, f"Selecteur CSS encore present : {sel}{{")

    def test_app_imports_restored_v4_views(self) -> None:
        """app.js doit importer les vues v4 RESTAUREES.

        Garde-fou anti-regression : si quelqu'un re-supprime un import sans
        re-porter la fonctionnalite vers v5, ce test echoue.
        """
        app = (_ROOT / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        # Ne couvre que les vues effectivement importees par app.js (top-level).
        # Les fichiers internes au dossier library/ sont importes par
        # library/library.js et n'apparaissent donc pas dans app.js.
        expected_imports = [
            "./views/status.js",
            "./views/quality.js",
            "./views/settings.js",
            "./views/help.js",
            "./views/library/library.js",
        ]
        for imp in expected_imports:
            with self.subTest(import_path=imp):
                self.assertIn(
                    f'"{imp}"',
                    app,
                    f"app.js doit importer la vue v4 RESTAUREE : {imp}",
                )

    def test_app_does_not_import_truly_removed_views(self) -> None:
        """Les vues v4 reellement supprimees (review.js, runs.js) ne doivent
        plus etre importees par app.js."""
        app = (_ROOT / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        for rel in TRULY_REMOVED_VIEWS:
            basename = rel.rsplit("/", 1)[-1]
            with self.subTest(view=basename):
                self.assertNotIn(
                    f'"./views/{basename}"',
                    app,
                    f"app.js importe encore la vue v4 supprimee : {basename}",
                )


if __name__ == "__main__":
    unittest.main()
