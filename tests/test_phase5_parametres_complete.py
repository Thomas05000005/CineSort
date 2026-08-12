"""Tests Phase 5 : Paramètres complète (spec 11 §1..§10).

Verifie que la vue parametres.js implemente bien :
- 10 categories avec contenu reel (champs, pas de placeholder vers /settings)
- Mode expert persiste dans settings.expert_mode (backend)
- Recherche live + highlight + raccourci Ctrl+K
- Reset modale avec scopes (10 + database) + CONFIRMER + countdown 3s
- Profils Qualite : selecteur actif + sliders poids + validation somme ~100
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PARAMETRES_JS = _ROOT / "web" / "dashboard" / "views" / "parametres.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TenCategoriesContentTests(unittest.TestCase):
    """Spec 11 §2 : les 10 categories doivent avoir du contenu reel (pas de placeholder vers /settings)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)

    def test_no_legacy_settings_redirect_in_categories(self) -> None:
        # Aucun lien vers /settings dans les sections (placeholder ancien)
        self.assertNotIn(
            'href="#/settings"', self.js, "Les categories ne doivent plus rediriger vers la vue legacy /settings"
        )

    def test_parametres_groups_schema_exists(self) -> None:
        self.assertIn("PARAMETRES_GROUPS", self.js)

    def test_all_10_categories_in_schema(self) -> None:
        for cat in (
            "sources",
            "analyse",
            "nommage",
            "bibliotheque",
            "integrations",
            "notifications",
            "serveur",
            "apparence",
            "profils-qualite",
            "avance",
        ):
            self.assertIn(f'id: "{cat}"', self.js, f"categorie {cat} manquante")

    def test_sources_has_roots_field(self) -> None:
        self.assertIn('key: "roots"', self.js)
        self.assertIn('type: "multi-path"', self.js)

    def test_analyse_has_perceptual_fields(self) -> None:
        for k in ("perceptual_enabled", "ffprobe", "subtitle_detection_enabled"):
            self.assertIn(k, self.js, f"champ analyse {k} manquant")

    def test_nommage_has_template_fields(self) -> None:
        for k in ("naming_preset", "naming_movie_template", "naming_tv_template"):
            self.assertIn(k, self.js, f"champ nommage {k} manquant")

    def test_bibliotheque_has_organization_fields(self) -> None:
        for k in (
            "collection_folder_enabled",
            "enable_tv_detection",
            "move_empty_folders_enabled",
            "cleanup_residual_folders_enabled",
        ):
            self.assertIn(k, self.js, f"champ bibliotheque {k} manquant")

    def test_integrations_has_5_services(self) -> None:
        for svc in ("tmdb_api_key", "jellyfin_url", "plex_url", "radarr_url", "omdb_api_key"):
            self.assertIn(svc, self.js, f"service {svc} manquant dans integrations")

    def test_integrations_has_test_buttons(self) -> None:
        # 5 testMethod pour les 5 services
        for method in (
            "test_tmdb_key",
            "test_jellyfin_connection",
            "test_plex_connection",
            "test_radarr_connection",
            "test_omdb_connection",
        ):
            self.assertIn(method, self.js, f"testMethod {method} manquant")

    def test_notifications_has_desktop_smtp_hooks(self) -> None:
        for k in (
            "notifications_enabled",
            "notifications_scan_done",
            "email_smtp_host",
            "email_smtp_port",
            "email_smtp_password",
            "plugins_enabled",
        ):
            self.assertIn(k, self.js, f"champ notifications {k} manquant")

    def test_serveur_has_rest_and_qr(self) -> None:
        for k in ("rest_api_enabled", "rest_api_port", "rest_api_token", "__qr_dashboard__", "restart_api"):
            self.assertIn(k, self.js, f"champ serveur {k} manquant")

    def test_apparence_has_theme_select_4_options(self) -> None:
        for theme in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'v:"{theme}"', self.js, f"theme {theme} manquant")

    def test_avance_has_log_level_and_retention(self) -> None:
        for k in (
            "perceptual_parallelism_mode",
            "log_level",
            "onboarding_completed",
            "update_check_enabled",
            "history_retention_days",
        ):
            self.assertIn(k, self.js, f"champ avance {k} manquant")


class ExpertModeBackendTests(unittest.TestCase):
    """Spec 11 §3 : Mode expert persiste dans settings.expert_mode (backend)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)

    def test_expert_mode_reads_settings(self) -> None:
        # On lit settings.expert_mode (pas localStorage)
        self.assertIn("_state.settings.expert_mode", self.js)

    def test_expert_mode_saves_via_save_settings(self) -> None:
        # _scheduleSave est appele dans le handler change du toggle
        self.assertIn("_state.settings.expert_mode = v", self.js)
        self.assertIn("_scheduleSave()", self.js)


class SearchLiveTests(unittest.TestCase):
    """Spec 11 §4 : recherche live + highlight + Ctrl+K."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)
        cls.css = _read(_COMPONENTS_CSS)

    def test_search_input_present(self) -> None:
        self.assertIn("data-parametres-search", self.js)

    def test_ctrl_k_shortcut(self) -> None:
        self.assertIn("Ctrl+K", self.js)
        self.assertIn("_installCtrlK", self.js)
        # Le handler verifie ctrlKey ou metaKey + key 'k'
        self.assertIn("ctrlKey", self.js)
        self.assertIn('"k"', self.js)

    def test_highlight_helper(self) -> None:
        self.assertIn("_highlightLabel", self.js)
        self.assertIn("parametres-search-highlight", self.js)

    def test_auto_switch_category_on_search(self) -> None:
        # Si la categorie active ne matche pas la recherche, on bascule sur la 1ere
        self.assertIn("_groupMatches", self.js)

    def test_css_highlight_class(self) -> None:
        self.assertIn(".parametres-search-highlight", self.css)


class ResetModaleTests(unittest.TestCase):
    """Spec 11 §6 : reset modale avec scopes + CONFIRMER + countdown."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)
        cls.css = _read(_COMPONENTS_CSS)

    def test_reset_modal_function(self) -> None:
        self.assertIn("_openResetModal", self.js)

    def test_reset_scopes_list(self) -> None:
        # 10 categories + "all" + "__database__" = 12 scopes
        self.assertIn("_RESET_SCOPES", self.js)
        for scope in (
            "all",
            "sources",
            "analyse",
            "nommage",
            "bibliotheque",
            "integrations",
            "notifications",
            "serveur",
            "apparence",
            "profils-qualite",
            "avance",
            "__database__",
        ):
            self.assertIn(f'"{scope}"', self.js, f"scope {scope} manquant dans _RESET_SCOPES")

    def test_confirmer_text_validation(self) -> None:
        # Le bouton confirm n'est actif que si l'input = "CONFIRMER"
        self.assertIn("CONFIRMER", self.js)
        self.assertIn("data-parametres-reset-input", self.js)
        self.assertIn("data-parametres-reset-confirm", self.js)

    def test_countdown_3s_for_all_scope(self) -> None:
        # Countdown de 3s pour scope=all ou __database__
        self.assertIn("startCountdown(3)", self.js)

    def test_calls_reset_settings_endpoint(self) -> None:
        self.assertIn("settings/reset_settings", self.js)

    def test_calls_reset_database_endpoint(self) -> None:
        self.assertIn("settings/reset_database", self.js)

    def test_css_modal_styles(self) -> None:
        self.assertIn(".parametres-reset-modal-overlay", self.css)
        self.assertIn(".parametres-reset-modal-confirm", self.css)
        self.assertIn(".parametres-reset-modal-warning", self.css)


class ProfilsQualiteTests(unittest.TestCase):
    """Spec 11 §2.9 : profils qualite complets (selecteur + tiers + sliders poids + validation)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)
        cls.css = _read(_COMPONENTS_CSS)

    def test_profile_selector_active(self) -> None:
        self.assertIn("data-parametres-profile-select", self.js)
        self.assertIn("settings/get_profiles", self.js)
        self.assertIn("settings/set_active_profile", self.js)

    def test_4_tier_inputs(self) -> None:
        # Les rows tiers sont generes en mappant sur [platinum, gold, silver, bronze]
        # via "data-tier-input=${name}" — on verifie les attributs binders cote events.
        self.assertIn("data-tier-input", self.js)
        for tier in ("platinum", "gold", "silver", "bronze"):
            self.assertIn(tier, self.js, f"tier {tier} manquant")

    def test_6_weight_sliders(self) -> None:
        # 6 composantes du Score V2 (spec 11 §2.9) listees dans _DEFAULT_WEIGHTS
        self.assertIn("data-weight-input", self.js)
        for w in ("resolution", "bitrate", "codec", "audio_bitrate", "audio_channels", "subtitles_fr"):
            self.assertIn(w, self.js, f"composante {w} manquante")

    def test_les_poids_par_defaut_sont_ceux_du_SCORING(self) -> None:
        """CE TEST COMPARAIT UNE CHAINE DE CODE SOURCE, et c'est ce qui l'a rendu
        inutile.

        Il exigeait `resolution: 0.25`, `bitrate: 0.20`, `codec: 0.15` — six
        poids qu'aucune ligne du moteur de scoring ne lit. Il est reste vert
        pendant tout ce temps, pendant que bouger les curseurs correspondants
        REMETTAIT les vrais poids (video/audio/extras) aux valeurs d'usine. Un
        test de chaine ne detecte rien quand le code casse, et tombe quand il
        s'ameliore : les deux se sont produits ici.

        Il porte desormais sur les VALEURS, comparees a la source de verite —
        `default_quality_profile()["weights"]` du backend. Le contrat complet de
        l'ecran vit dans `tests/test_poids_profil_qualite_ecran.py`.
        """
        from cinesort.domain.quality_score import default_quality_profile

        attendus = default_quality_profile()["weights"]
        self.assertEqual(set(attendus), {"video", "audio", "extras"})
        for cle, valeur in attendus.items():
            self.assertIn(
                f"{cle}: {valeur}",
                self.js,
                f"le poids par defaut « {cle} » de l'ecran ne vaut pas celui du backend ({valeur})",
            )

    def test_save_profile_new(self) -> None:
        self.assertIn("settings/save_profile", self.js)
        self.assertIn('data-parametres-profils-action="save"', self.js)

    def test_recompute_button(self) -> None:
        self.assertIn('data-parametres-profils-action="recompute"', self.js)
        self.assertIn("quality/recompute_all_scores", self.js)

    def test_la_somme_des_poids_est_validee_dans_la_forme_du_backend(self) -> None:
        """La forme canonique est en POINTS DE POURCENTAGE (somme 100).

        L'ancienne assertion exigeait les bornes 0.95/1.05 — la validation en
        fraction — qui aurait refuse tout profil reel, `default_quality_profile()`
        rendant {video: 60, audio: 30, extras: 10}.
        """
        self.assertIn("_SOMME_POIDS = 100", self.js)
        self.assertIn("_TOLERANCE_POIDS", self.js)
        self.assertNotIn("total < 0.95", self.js, "la validation en fraction subsiste")

    def test_tier_strict_decreasing_validation(self) -> None:
        # platinum > gold > silver > bronze
        self.assertIn("t.platinum > t.gold", self.js)
        self.assertIn("t.silver > t.bronze", self.js)

    def test_css_profil_classes(self) -> None:
        for cls in (
            ".parametres-profils-qualite",
            ".parametres-tier-row",
            ".parametres-weight-row",
            ".parametres-weight-total",
        ):
            self.assertIn(cls, self.css, f"classe CSS {cls} manquante")


class SaveAndIndicatorTests(unittest.TestCase):
    """Spec 11 §5 : save debounce 500ms + indicateur 'Sauvegardé'."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)

    def test_debounce_500ms(self) -> None:
        self.assertIn("setTimeout", self.js)
        self.assertIn("500", self.js)

    def test_saved_indicator(self) -> None:
        self.assertIn("data-parametres-saved-indicator", self.js)
        self.assertIn("Sauvegard", self.js)

    def test_save_settings_endpoint(self) -> None:
        self.assertIn("settings/save_settings", self.js)


class CssExtensionTests(unittest.TestCase):
    """Verifie que les nouvelles classes CSS phase 5 sont presentes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(_COMPONENTS_CSS)

    def test_field_classes(self) -> None:
        for cls in (
            ".parametres-field",
            ".parametres-field-label",
            ".parametres-field-hint",
            ".parametres-input",
            ".parametres-select",
            ".parametres-textarea",
            ".parametres-checkbox",
        ):
            self.assertIn(cls, self.css, f"classe CSS {cls} manquante")

    def test_section_classes(self) -> None:
        for cls in (
            ".parametres-section",
            ".parametres-section-header",
            ".parametres-section-title",
            ".parametres-section-badge",
        ):
            self.assertIn(cls, self.css, f"classe CSS {cls} manquante")

    def test_brace_balance(self) -> None:
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"accolades CSS desequilibrees : {opens} open vs {closes} close")


if __name__ == "__main__":
    unittest.main()
