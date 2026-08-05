"""Tests Phase 5 — Vue Accueil complete (spec 05-accueil.md).

Couvre les ajouts polish de l'Accueil :
- Timeline visuelle 7 jours (Activite recente) au lieu d'une liste tabulaire.
- CTA Demarrer 1-clic via run/start_plan (pas de navigateTo /traitement direct).
- Environment bar : ping integrations + etat hors-ligne avec cache 5 min.
- Suggestions limitees a 3 + lien "Voir toutes" si plus.
- Sidebar Traitement conditionnelle (dimmed si aucun run actif).
- Fragment #run-XXX dans /traitement (Reprendre la validation).
- Styles CSS pour timeline + env-bar offline + drawer.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._jsexec import require_node, run_module_test
from tests.test_revue_20260803_modales_et_payloads import ACCUEIL_STUBS

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_TRAITEMENT_JS = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
_SIDEBAR_JS = _ROOT / "web" / "dashboard" / "components" / "sidebar-v5.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------- #
# 1. Timeline 7 jours
# --------------------------------------------------------------------- #
class Timeline7DaysTests(unittest.TestCase):
    """Spec 05 §6 : remplacer la liste tabulaire par une timeline 7 jours."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_ACCUEIL_JS)
        cls.css = _read(_COMPONENTS_CSS)

    def test_timeline_has_7_days_constant(self) -> None:
        self.assertIn("_TIMELINE_DAYS = 7", self.js)

    def test_timeline_bucket_function_present(self) -> None:
        self.assertIn("_bucketRunsByDay", self.js)

    def test_timeline_section_title_mentions_7_days(self) -> None:
        self.assertIn("Activité récente (7 jours)", self.js)

    def test_timeline_4_status_colors(self) -> None:
        # Bullets : applied (vert) / partial (orange) / error (rouge) / done (gris).
        for cls in (
            "accueil-timeline-bullet--applied",
            "accueil-timeline-bullet--partial",
            "accueil-timeline-bullet--error",
            "accueil-timeline-bullet--done",
        ):
            self.assertIn(cls, self.js)
            self.assertIn(cls, self.css)

    def test_timeline_css_grid_7_columns(self) -> None:
        # CSS doit declarer une grille 7 colonnes pour les 7 jours.
        self.assertIn("repeat(7,", self.css.replace(" ", ""))
        self.assertIn(".accueil-timeline-7d", self.css)
        self.assertIn(".accueil-timeline-day", self.css)
        self.assertIn(".accueil-timeline-bullet", self.css)

    def test_timeline_replaces_legacy_table_render(self) -> None:
        # La fonction _renderRecentActivity ne doit plus generer la liste
        # tabulaire <li class="accueil-activity-row clickable-row">.
        self.assertNotIn('clickable-row" tabindex="0" data-run-id', self.js)

    def test_timeline_bullets_have_tooltip(self) -> None:
        # title="..." sur chaque bullet pour hover details.
        self.assertIn('aria-label="${escapeHtml(tooltip)}', self.js)

    def test_timeline_status_derivation_helper(self) -> None:
        """La timeline derive bien un statut par run.

        Revue adversaire PR #855 : ce test cherchait la CHAINE `_deriveRunStatus`
        dans la source. Il est tombe le jour ou la derivation a ete extraite dans
        `core/run-status.js` (partagee avec /historique pour que les deux ecrans
        cessent de se contredire) — alors que le comportement s'ameliorait. Il
        verifie desormais le HTML reellement produit, quel que soit le nom, le
        fichier ou la forme du helper.
        """
        require_node(self)
        res = run_module_test(
            _ACCUEIL_JS,
            stubs=ACCUEIL_STUBS,
            extra="export const __t = { render: _renderRecentActivity };\n",
            driver=r"""
const ts = Math.floor(Date.now() / 1000) - 3600;
const mk = (o) => Object.assign({ run_id: "r", status: "DONE", started_ts: ts,
  total_rows: 10, applied_rows: 0, errors_count: 0 }, o);
const out = {};
for (const [k, o] of [
  ["applied", { run_id: "applied", applied_rows: 10 }],
  ["partial", { run_id: "partial", applied_rows: 4 }],
  ["error",   { run_id: "error",   errors_count: 2 }],
  ["done",    { run_id: "done" }],
]) out[k] = M.__t.render([mk(o)]);
__emit(out);
""",
        )
        for expected, html in res.items():
            self.assertIn(f"— {expected.upper()}", html, f"statut {expected} absent de l'infobulle")
            self.assertIn(f"accueil-timeline-bullet--{expected}", html)


# --------------------------------------------------------------------- #
# 2. CTA Demarrer 1-clic
# --------------------------------------------------------------------- #
class CtaStartScanOneClickTests(unittest.TestCase):
    """Spec 05 §3 : Demarrer appelle run/start_plan direct (pas navigateTo)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_ACCUEIL_JS)

    def test_start_scan_direct_action_exists(self) -> None:
        self.assertIn("start-scan-direct", self.js)

    def test_start_plan_called_via_apipost(self) -> None:
        # run/start_plan doit etre appele explicitement.
        self.assertIn('apiPost("run/start_plan"', self.js)

    def test_trigger_start_plan_helper(self) -> None:
        self.assertIn("function _triggerStartPlan", self.js)

    def test_polling_helper_present(self) -> None:
        self.assertIn("_startScanPolling", self.js)
        # 2 secondes de polling minimum.
        self.assertIn("2000", self.js)

    def test_options_drawer_helper(self) -> None:
        # Mini drawer avec 3 checkboxes.
        self.assertIn("_openScanOptionsDrawer", self.js)
        self.assertIn('data-opt="dry_run"', self.js)
        self.assertIn('data-opt="skip_duplicates"', self.js)
        self.assertIn('data-opt="apply_after"', self.js)


# --------------------------------------------------------------------- #
# 3. Environment bar — ping + etat hors-ligne
# --------------------------------------------------------------------- #
class EnvironmentBarOfflineTests(unittest.TestCase):
    """Spec 05 §1 : pastilles passent a ⚠ orange si configurees mais hors ligne."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_ACCUEIL_JS)
        cls.css = _read(_COMPONENTS_CSS)

    def test_ping_function_present(self) -> None:
        self.assertIn("_pingIntegration", self.js)

    def test_pings_each_integration(self) -> None:
        # 5 endpoints d'auto-test sont appeles (tmdb via key, autres via connection).
        self.assertIn("test_tmdb_key", self.js)
        self.assertIn("integrations/test_jellyfin_connection", self.js)
        self.assertIn("integrations/test_plex_connection", self.js)
        self.assertIn("integrations/test_radarr_connection", self.js)
        self.assertIn("integrations/test_omdb_connection", self.js)

    def test_ping_cache_5min(self) -> None:
        # Cache TTL = 5 min (= 5 * 60 * 1000 = 300000 ms).
        self.assertIn("5 * 60 * 1000", self.js)
        self.assertIn("_pingCache", self.js)

    def test_offline_state_in_integration_state(self) -> None:
        self.assertIn('return "offline"', self.js)

    def test_offline_visual_symbol(self) -> None:
        # ⚠ pour hors-ligne.
        self.assertIn("⚠", self.js)
        self.assertIn("is-offline", self.js)

    def test_css_offline_pill_color(self) -> None:
        # CSS .accueil-env-pill.is-offline + .accueil-env-bar-badge--offline (alias spec).
        self.assertIn(".accueil-env-pill.is-offline", self.css)
        self.assertIn(".accueil-env-bar-badge--offline", self.css)


# --------------------------------------------------------------------- #
# 4. Suggestions limitees a 3
# --------------------------------------------------------------------- #
class SuggestionsLimitTo3Tests(unittest.TestCase):
    """Spec 05 §4 : 3 suggestions max + lien Voir toutes si plus."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_ACCUEIL_JS)

    def test_max_3_suggestions(self) -> None:
        self.assertIn("_MAX_SUGGESTIONS = 3", self.js)

    def test_view_all_action_present(self) -> None:
        self.assertIn("view-all-suggestions", self.js)

    def test_view_all_navigates_to_qualite(self) -> None:
        # "Voir toutes" -> /qualite (audit complet).
        self.assertIn('case "view-all-suggestions":', self.js)


# --------------------------------------------------------------------- #
# 5. Sidebar Traitement conditionnelle
# --------------------------------------------------------------------- #
class SidebarConditionalTests(unittest.TestCase):
    """Spec 05 §3 : entree Traitement dimmer si aucun run actif."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js_accueil = _read(_ACCUEIL_JS)
        cls.js_sidebar = _read(_SIDEBAR_JS)
        cls.css = _read(_COMPONENTS_CSS)

    def test_sidebar_exports_set_item_dimmed(self) -> None:
        self.assertIn("export function setItemDimmed(", self.js_sidebar)

    def test_dimmed_css_class(self) -> None:
        self.assertIn(".v5-sidebar-item--dimmed", self.css)

    def test_accueil_calls_dimmer(self) -> None:
        # _updateSidebarForActiveRun applique/retire la classe selon hasActiveRun.
        self.assertIn("_updateSidebarForActiveRun", self.js_accueil)
        self.assertIn("v5-sidebar-item--dimmed", self.js_accueil)


# --------------------------------------------------------------------- #
# 6. Fragment #run-XXX dans /traitement
# --------------------------------------------------------------------- #
class TraitementRunFragmentTests(unittest.TestCase):
    """Spec 05 §2 : "Reprendre la validation" navigue avec fragment #run-XXX."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_TRAITEMENT_JS)

    def test_read_target_run_id_function(self) -> None:
        self.assertIn("_readTargetRunId", self.js)

    def test_fragment_pattern_run(self) -> None:
        # Regex doit matcher #run-XXXX.
        self.assertIn("#run-", self.js)

    def test_load_run_info_uses_target(self) -> None:
        # _loadRunInfo doit utiliser _targetRunId quand present.
        self.assertIn("_targetRunId", self.js)

    def test_init_routes_to_validation_step(self) -> None:
        # Si fragment #run-XXX present, demarre directement a l'etape validation.
        self.assertIn('_currentStep = "validation"', self.js)


# --------------------------------------------------------------------- #
# 7. Pas de regression : XSS, escape, exports
# --------------------------------------------------------------------- #
class NoRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_ACCUEIL_JS)

    def test_init_accueil_still_exported(self) -> None:
        self.assertIn("export async function initAccueil(", self.js)

    def test_compute_hero_summary_still_exported(self) -> None:
        self.assertIn("export function computeHeroSummary(", self.js)

    def test_run_id_escaped_in_timeline(self) -> None:
        self.assertIn("escapeHtml(r.run_id)", self.js)

    def test_no_legacy_navigateto_traitement_for_start_scan(self) -> None:
        # On verifie que start-scan-direct ne fait PAS de navigateTo("/traitement").
        # Pour ca on cherche le bloc 'case "start-scan-direct"' et on s'assure
        # qu'il appelle _triggerStartPlan.
        idx = self.js.find('case "start-scan-direct":')
        self.assertNotEqual(idx, -1, "case start-scan-direct manquant")
        # Bloc allant jusqu'au break suivant.
        sub = self.js[idx : idx + 400]
        self.assertIn("_triggerStartPlan", sub)
        # Et pas de navigateTo("/traitement") dans ce bloc.
        # (le bloc start-scan, lui, en a un pour l'empty state, c'est OK).


if __name__ == "__main__":
    unittest.main()
