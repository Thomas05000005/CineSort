"""Tests Phase 3.1-B : Accueil — CTA Scan + Santé biblio + Suggestions.

Etend les tests Phase 3.1-A. Couvre les sections 3, 4, 5 de la spec
05-accueil.md.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._jsexec import require_node, run_module_test

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class CtaScanSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_cta_scan_section_function_present(self) -> None:
        # Signature etendue en Phase 3.1-C avec parametre scanProgress.
        self.assertIn("function _renderCtaScan(roots, scanProgress)", self.js)

    def test_cta_scan_title(self) -> None:
        self.assertIn("Lancer un nouveau scan", self.js)

    def test_cta_scan_lists_roots(self) -> None:
        # Doit afficher les roots actifs ou un message si aucun.
        self.assertIn("Aucun root configuré", self.js)

    def test_cta_scan_action_buttons(self) -> None:
        self.assertIn('data-accueil-action="start-scan"', self.js)
        self.assertIn('data-accueil-action="open-scan-options"', self.js)
        self.assertIn("▶ Démarrer", self.js)
        self.assertIn("Options", self.js)


class HealthBargraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_health_section_function_present(self) -> None:
        self.assertIn("function _renderHealth(stats)", self.js)

    def test_5_tiers_ordered(self) -> None:
        # Spec : ordre platinum > gold > silver > bronze > reject.
        self.assertIn('_TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject"]', self.js)

    def test_renders_progressbar_aria(self) -> None:
        self.assertIn('role="progressbar"', self.js)
        self.assertIn("aria-valuenow=", self.js)

    def test_empty_state_message(self) -> None:
        # Spec : "Lance ton premier scan pour voir la distribution."
        self.assertIn("Lance ton premier scan pour voir la distribution", self.js)

    def test_action_view_qualite(self) -> None:
        self.assertIn("Audit qualité complet", self.js)
        self.assertIn('data-accueil-action="view-qualite"', self.js)


class SuggestionsSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_suggestions_function_present(self) -> None:
        self.assertIn("function _renderSuggestions(stats)", self.js)

    def test_empty_state_positive_message(self) -> None:
        # Spec §4 : "Aucun point à traiter. Tout va bien."
        self.assertIn("Aucun point à traiter", self.js)

    def test_renders_severity_classes(self) -> None:
        # 3 severites cf spec §4 : danger / warning / info.
        self.assertIn("is-danger", self.js)
        self.assertIn("is-warning", self.js)
        self.assertIn("is-info", self.js)

    def test_renders_severity_emojis(self) -> None:
        # Pour les utilisateurs : 🔴 / 🟡 / 🔵.
        self.assertIn('"🔴"', self.js)
        self.assertIn('"🟡"', self.js)
        self.assertIn('"🔵"', self.js)

    def test_route_map_covers_spec_codes(self) -> None:
        # Spec §4 : 8 codes -> routes connues.
        for code in [
            "duplicates_probable",
            "films_not_identified",
            "films_low_confidence",
            "subs_missing_fr",
            "omdb_disagreements",
            "quality_reject",
            "health_low",
            "sagas_incomplete",
        ]:
            self.assertIn(code, self.js, f"code suggestion {code} non mappe")

    def test_open_insight_action_present(self) -> None:
        self.assertIn('data-accueil-action="open-insight"', self.js)


class IntegrationTests(unittest.TestCase):
    """initAccueil doit charger 3 endpoints en parallele."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_fetches_dashboard_and_stats_and_settings(self) -> None:
        self.assertIn("get_dashboard", self.js)
        self.assertIn("get_global_stats", self.js)
        self.assertIn("settings/get_settings", self.js)

    def test_uses_promise_all(self) -> None:
        self.assertIn("Promise.all([", self.js)

    def test_stats_and_settings_failure_does_not_kill_accueil(self) -> None:
        # On veut .catch(() => null) pour stats + settings : si l'un fail,
        # on ne plante pas tout l'accueil.
        self.assertIn(".catch(() => null)", self.js)

    def test_render_accueil_receives_dashboard_stats_and_settings(self) -> None:
        # Historique : ce test cherchait la chaine exacte
        # "_renderAccueil(dashboardData, stats, settings)". Il est passe au
        # ROUGE le jour ou la vue a gagne un 4e argument (updateInfo) — une
        # EXTENSION, pas une regression. Il n'aurait par ailleurs rien detecte
        # si l'un des 3 payloads avait cesse d'etre exploite par le rendu.
        # On verifie donc le CABLAGE de facon tolerante (les 3 payloads sont
        # passes, dans l'ordre, quel que soit ce qui suit) ; la preuve qu'ils
        # sont reellement CONSOMMES est faite au runtime par
        # RenderAccueilRuntimeTests ci-dessous.
        self.assertRegex(
            self.js,
            r"_renderAccueil\(\s*dashboardData\s*,\s*stats\s*,\s*settings\s*[,)]",
            "initAccueil doit passer dashboardData, stats et settings a _renderAccueil",
        )


# --- Rendu de l'Accueil : verifie au RUNTIME -----------------------------
#
# Complement de test_render_accueil_receives_dashboard_stats_and_settings : on
# execute le vrai _renderAccueil sous Node (harnais tests/_jsexec.py) avec un
# marqueur unique par source de donnees. Si un payload cesse d'etre exploite
# (ou est passe a la mauvaise position), son marqueur disparait du HTML.

_ACCUEIL_STUBS = """
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const apiPost = async () => ({});
const getSettingsEpoch = () => 0;
const getNavSignal = () => null;
const navigateTo = () => {};
const rightPanel = { setSections: () => {}, setTitle: () => {} };
"""

_ACCUEIL_EXTRA = """
export { _renderAccueil as __renderAccueil };
export { _buildInspectorSections as __buildInspectorSections };
"""

# started_ts = "maintenant" pour que le run tombe dans la timeline 7 jours.
_ACCUEIL_DRIVER = """
const nowTs = Math.floor(Date.now() / 1000);
const payload = {
  runs_history: [{ run_id: "RUN-MARQUEUR-PAYLOAD", started_ts: nowTs, total_rows: 12, status: "DONE" }],
  kpis: { total_rows: 12 },
};
const stats = {
  insights: [{ type: "films_low_confidence", severity: "warning", count: 7, label: "MARQUEUR-STATS a revoir" }],
  v2_tier_distribution: { platinum: 1, gold: 2, silver: 3, bronze: 4, reject: 5, total: 15 },
};
const settings = { roots: ["Z:/MARQUEUR-SETTINGS/films"], omdb_enabled: false };
__emit({
  full: M.__renderAccueil(payload, stats, settings, null),
  noStats: M.__renderAccueil(payload, null, settings, null),
  noSettings: M.__renderAccueil(payload, stats, null, null),
});
"""


class RenderAccueilRuntimeTests(unittest.TestCase):
    """_renderAccueil consomme reellement les 3 payloads (execution Node)."""

    _res: dict | None = None

    def _html(self) -> dict:
        require_node(self)
        if RenderAccueilRuntimeTests._res is None:
            RenderAccueilRuntimeTests._res = run_module_test(
                _ACCUEIL_JS,
                stubs=_ACCUEIL_STUBS,
                extra=_ACCUEIL_EXTRA,
                driver=_ACCUEIL_DRIVER,
            )
        return RenderAccueilRuntimeTests._res

    def test_each_payload_reaches_the_rendered_html(self) -> None:
        html = self._html()["full"]
        self.assertIn("RUN-MARQUEUR-PAYLOAD", html, "le payload get_dashboard n'atteint pas le rendu")
        self.assertIn("MARQUEUR-STATS", html, "les stats get_global_stats n'atteignent pas le rendu")
        self.assertIn("MARQUEUR-SETTINGS", html, "les settings n'atteignent pas le rendu")
        # runs_history alimente la timeline, pas seulement la carte "dernier run".
        self.assertNotIn(
            "Aucune activité pour l'instant",
            html,
            "un run present dans runs_history doit alimenter l'activite recente",
        )

    def test_stats_failure_degrades_without_killing_the_page(self) -> None:
        # Contrepartie du .catch(() => null) : stats a null ne doit ni jeter ni
        # vider la page — les autres sections restent servies.
        html = self._html()["noStats"]
        self.assertIn("RUN-MARQUEUR-PAYLOAD", html)
        self.assertIn("MARQUEUR-SETTINGS", html)
        self.assertIn("Aucun point à traiter", html, "sans stats : etat vide des suggestions attendu")

    def test_settings_failure_degrades_without_killing_the_page(self) -> None:
        html = self._html()["noSettings"]
        self.assertIn("RUN-MARQUEUR-PAYLOAD", html)
        self.assertIn("MARQUEUR-STATS", html)
        self.assertIn("Aucun root configuré", html, "sans settings : etat vide des roots attendu")

    def test_sections_are_rendered_in_spec_order(self) -> None:
        # Spec 05 : barre environnement, puis hero, puis CTA scan, puis
        # suggestions, puis sante, puis activite recente.
        html = self._html()["full"]
        order = [
            "accueil-env-bar",
            "accueil-hero",
            "accueil-cta-scan",
            "accueil-suggestions",
            "accueil-health",
            "accueil-activity",
        ]
        positions = []
        for cls in order:
            pos = html.find(cls)
            self.assertNotEqual(pos, -1, f"section {cls} absente du rendu")
            positions.append(pos)
        self.assertEqual(positions, sorted(positions), f"ordre des sections inattendu : {order}")


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_cta_scan_class(self) -> None:
        self.assertIn(".accueil-cta-scan", self.css)

    def test_health_classes(self) -> None:
        self.assertIn(".accueil-health-bar", self.css)
        self.assertIn(".accueil-health-fill", self.css)

    def test_tier_fill_classes_all_5(self) -> None:
        # Une couleur par tier (mappe sur les tokens tier-*-solid).
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".accueil-health-fill--{tier}", self.css)

    def test_uses_tier_solid_tokens(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"var(--tier-{tier}-solid", self.css)

    def test_suggestion_classes(self) -> None:
        self.assertIn(".accueil-suggestion-list", self.css)
        self.assertIn(".accueil-suggestion-row", self.css)
        self.assertIn(".accueil-suggestion-dot", self.css)

    def test_suggestion_severity_borders(self) -> None:
        # Border-left colore par severite.
        self.assertIn(".accueil-suggestion-row.is-danger", self.css)
        self.assertIn(".accueil-suggestion-row.is-warning", self.css)
        self.assertIn(".accueil-suggestion-row.is-info", self.css)


if __name__ == "__main__":
    unittest.main()
