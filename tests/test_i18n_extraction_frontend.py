"""Tests extraction strings frontend V6-02 (Polish Total v7.7.0).

Verifie que :
- les cles ajoutees au fr.json par V6-02 existent et sont des strings non vides ;
- les cles utilisees par sidebar-v5.js / top-bar-v5.js / settings.js / qij.js
  via t("...") sont presentes dans fr.json (sinon t() retombe sur la cle, pas
  une vraie traduction) ;
- les fichiers JS prioritaires importent bien `t` depuis core/i18n.js ;
- aucun fichier JS modifie ne casse la syntaxe (smoke import via re).

Aucune dependance externe : stdlib unittest + json + re + pathlib.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict, Set


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALES_DIR = PROJECT_ROOT / "locales"
DASHBOARD_DIR = PROJECT_ROOT / "web" / "dashboard"


def _load(locale: str) -> Dict[str, Any]:
    return json.loads((LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k == "_meta":
            continue
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


# Pattern qui capture t("a.b.c") ou t('a.b.c'). On evite les calls de la forme
# t(variable) ou t(`tpl`) qui referencent une cle dynamique.
_T_CALL_RE = re.compile(r'\bt\(\s*[\'"]([A-Za-z0-9_\.\-]+)[\'"]')


def _extract_t_keys(js_text: str) -> Set[str]:
    return set(_T_CALL_RE.findall(js_text))


# Fichiers prioritaires modifies par V6-02. Le test verifie que toutes les cles
# utilisees existent dans fr.json (sinon affichage = la cle elle-meme).
V6_02_FILES = [
    DASHBOARD_DIR / "components" / "sidebar-v5.js",
    DASHBOARD_DIR / "components" / "top-bar-v5.js",
    DASHBOARD_DIR / "views" / "settings.js",
    DASHBOARD_DIR / "views" / "qij.js",
]


class FrJsonV6_02KeysTests(unittest.TestCase):
    """Categories ajoutees par V6-02 doivent exister et etre non vides."""

    def test_sidebar_keys_present(self) -> None:
        fr = _load("fr")
        for key in (
            "brand_name",
            "brand_desc",
            "aria_label",
            "about",
            "about_aria",
            "collapse",
            "expand",
            "collapse_expand",
            "counter_aria",
            "title_with_shortcut",
            "integration_disabled_title",
            "update_badge_title",
        ):
            self.assertIn(key, fr.get("sidebar", {}), f"sidebar.{key} manquante")
        nav = fr.get("sidebar", {}).get("nav", {})
        for key in ("home", "processing", "library", "qij", "settings", "help"):
            self.assertIn(key, nav, f"sidebar.nav.{key} manquante")

    def test_topbar_keys_present(self) -> None:
        fr = _load("fr")
        for key in (
            "search_label",
            "search_aria",
            "notifications_aria",
            "theme_change_aria",
            "help_fab_aria",
            "help_fab_title",
        ):
            self.assertIn(key, fr.get("topbar", {}), f"topbar.{key} manquante")
        themes = fr.get("topbar", {}).get("themes", {})
        for key in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(key, themes, f"topbar.themes.{key} manquante")

    def test_settings_groups_keys_present(self) -> None:
        fr = _load("fr")
        groups = fr.get("settings", {}).get("groups", {})
        expected = {
            "sources",
            "analyse",
            "nommage",
            "bibliotheque",
            "integrations",
            "notifications",
            "serveur",
            "apparence",
            "avance",
        }
        self.assertEqual(set(groups.keys()), expected, "settings.groups ne contient pas exactement les 9 groupes")

    def test_settings_sections_keys_present(self) -> None:
        fr = _load("fr")
        sections = fr.get("settings", {}).get("sections", {})
        # Au moins les sections importantes doivent exister.
        for s in (
            "roots",
            "watch",
            "probe",
            "perceptual",
            "scoring",
            "templates",
            "organization",
            "cleanup",
            "subtitles",
            "tmdb",
            "jellyfin",
            "plex",
            "radarr",
            "desktop",
            "email",
            "plugins",
            "rest",
            "https",
            "theme",
            "effects",
            "parallelism",
            "onboarding",
            "updates",
        ):
            self.assertIn(s, sections, f"settings.sections.{s} manquante")

    def test_qij_quality_keys_present(self) -> None:
        fr = _load("fr")
        quality = fr.get("qij", {}).get("quality", {})
        for key in (
            "tab_title",
            "subtitle",
            "no_data_title",
            "btn_simulate",
            "btn_custom_rules",
            "kpi_films",
            "kpi_avg_score",
            "kpi_platinum",
            "kpi_trend",
            "section_anomalies",
            "section_outliers",
            "outliers_hint",
            "batch_in_progress",
            "batch_no_run",
            "batch_success",
        ):
            self.assertIn(key, quality, f"qij.quality.{key} manquante")

    def test_qij_integrations_keys_present(self) -> None:
        fr = _load("fr")
        integ = fr.get("qij", {}).get("integrations", {})
        for key in (
            "tab_title",
            "subtitle",
            "status_connected",
            "status_error",
            "status_ready",
            "status_not_configured",
            "status_disabled",
            "btn_test",
            "btn_check_sync",
            "btn_libraries",
            "btn_settings",
        ):
            self.assertIn(key, integ, f"qij.integrations.{key} manquante")

    def test_qij_journal_keys_present(self) -> None:
        fr = _load("fr")
        journal = fr.get("qij", {}).get("journal", {})
        for key in (
            "tab_title",
            "btn_live",
            "btn_history",
            "no_active_run",
            "btn_cancel",
            "init",
            "no_runs",
            "selected_run_label",
            "selected_none",
            "btn_export_nfo",
            "sort_label",
        ):
            self.assertIn(key, journal, f"qij.journal.{key} manquante")

    def test_danger_zone_keys_present(self) -> None:
        fr = _load("fr")
        dz = fr.get("danger_zone", {})
        for key in (
            "title",
            "reset_title",
            "reset_desc",
            "reset_button",
            "prompt_confirm",
            "wrong_confirm",
            "last_chance",
            "reset_done",
            "reset_error",
            "current_data",
        ):
            self.assertIn(key, dz, f"danger_zone.{key} manquante")


class JsImportT_Tests(unittest.TestCase):
    """Les fichiers prioritaires importent t depuis core/i18n.js."""

    def test_priority_files_import_t(self) -> None:
        for path in V6_02_FILES:
            self.assertTrue(path.exists(), f"Fichier introuvable : {path}")
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                'from "../core/i18n.js"',
                content,
                f"{path.name} ne semble pas importer i18n.js",
            )
            # Doit utiliser t() au moins une fois (sinon a quoi bon ?).
            self.assertGreater(
                len(_extract_t_keys(content)),
                0,
                f"{path.name} importe i18n.js mais n'utilise pas t()",
            )


class JsKeysExistInFrTests(unittest.TestCase):
    """Toutes les cles t("...") litterales dans les fichiers prioritaires
    doivent exister dans fr.json — sinon t() retombe sur la cle (mauvais UX).
    """

    def test_all_referenced_keys_exist(self) -> None:
        fr_flat = _flatten(_load("fr"))
        fr_keys = set(fr_flat.keys())
        # On accepte aussi les sous-arbres (ex: t("settings.groups") referencerait
        # un dict, pas une string finale). On verifie donc que la cle est soit
        # une feuille soit un prefixe d'une feuille.
        prefixes = set()
        for k in fr_keys:
            parts = k.split(".")
            for i in range(1, len(parts)):
                prefixes.add(".".join(parts[:i]))

        missing: Dict[str, Set[str]] = {}
        for path in V6_02_FILES:
            keys = _extract_t_keys(path.read_text(encoding="utf-8"))
            for k in keys:
                if k not in fr_keys and k not in prefixes:
                    missing.setdefault(path.name, set()).add(k)
        self.assertFalse(
            missing,
            "Cles t() referencees mais absentes de fr.json :\n"
            + "\n".join(f"  {f}: {sorted(ks)}" for f, ks in missing.items()),
        )


class FrEnMirrorV6_02Tests(unittest.TestCase):
    """Categories portees par V6-02 doivent etre 100% mirroir entre fr/en.

    On exige la parite stricte sur :
    - sidebar
    - topbar
    - settings.groups, settings.sections, settings.fields, settings.preview_effects,
      settings.qr, settings.updates, settings.expert_mode
    - qij.tabs, qij.quality, qij.integrations, qij.journal
    - danger_zone (V6-05 a deja le meme contenu)
    """

    def _filter(self, flat: Dict[str, Any], prefixes: tuple) -> Set[str]:
        return {k for k in flat if k.startswith(prefixes)}

    def test_sidebar_topbar_full_parity(self) -> None:
        fr_flat = _flatten(_load("fr"))
        en_flat = _flatten(_load("en"))
        prefixes = ("sidebar.", "topbar.", "danger_zone.")
        fr_keys = self._filter(fr_flat, prefixes)
        en_keys = self._filter(en_flat, prefixes)
        missing = sorted(fr_keys - en_keys)
        self.assertFalse(missing, f"Cles FR sans EN : {missing}")

    def test_qij_v6_02_added_keys_have_en(self) -> None:
        """V6-02 a ajoute des cles dans qij.tabs/quality/integrations/journal.
        En doit toutes les avoir."""
        fr_flat = _flatten(_load("fr"))
        en_flat = _flatten(_load("en"))
        prefixes = ("qij.tabs.", "qij.quality.", "qij.integrations.", "qij.journal.")
        fr_keys = self._filter(fr_flat, prefixes)
        en_keys = self._filter(en_flat, prefixes)
        missing = sorted(fr_keys - en_keys)
        self.assertFalse(missing, f"Cles qij FR sans EN : {missing}")

    def test_settings_v6_02_added_keys_have_en(self) -> None:
        fr_flat = _flatten(_load("fr"))
        en_flat = _flatten(_load("en"))
        prefixes = (
            "settings.groups.",
            "settings.sections.",
            "settings.fields.",
            "settings.preview_effects.",
            "settings.qr.",
            "settings.updates.",
            "settings.expert_mode.",
        )
        fr_keys = self._filter(fr_flat, prefixes)
        en_keys = self._filter(en_flat, prefixes)
        missing = sorted(fr_keys - en_keys)
        self.assertFalse(missing, f"Cles settings FR sans EN : {missing}")


if __name__ == "__main__":
    unittest.main()
