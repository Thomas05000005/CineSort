"""Tests des profils de renommage — cinesort/domain/naming.py.

Couvre :
- Chaque preset produit le resultat attendu
- Variables manquantes → nettoyage propre
- Caracteres interdits Windows sanitises
- validate_template : variables connues OK, inconnues → erreur
- Template vide → fallback
- Annee 0 → chaine vide, parentheses nettoyees
- {tmdb_tag} avec et sans tmdb_id
- Longueur path > 240 → warning (pas troncature)
- Unicode, accents, emoji
- build_naming_context : construction complete du contexte
"""

from __future__ import annotations

import unittest

from cinesort.domain.naming import (
    PRESETS,
    PREVIEW_MOCK_CONTEXT,
    build_naming_context,
    check_path_length,
    format_movie_folder,
    format_tv_series_folder,
    validate_template,
)


def _ctx(**overrides) -> dict:
    """Contexte de base (Inception) avec surcharges."""
    base = dict(PREVIEW_MOCK_CONTEXT)
    base.update(overrides)
    return base


class PresetTests(unittest.TestCase):
    """Chaque preset produit le resultat attendu."""

    def test_default_preset(self) -> None:
        result = format_movie_folder(PRESETS["default"].movie_template, _ctx())
        self.assertEqual(result, "Inception (2010)")

    def test_plex_preset(self) -> None:
        result = format_movie_folder(PRESETS["plex"].movie_template, _ctx())
        # Plex veut {tmdb-27205} (accolades literales dans le resultat)
        self.assertEqual(result, "Inception (2010) {tmdb-27205}")

    def test_jellyfin_preset(self) -> None:
        result = format_movie_folder(PRESETS["jellyfin"].movie_template, _ctx())
        self.assertEqual(result, "Inception (2010) [1080p]")

    def test_quality_preset(self) -> None:
        result = format_movie_folder(PRESETS["quality"].movie_template, _ctx())
        self.assertEqual(result, "Inception (2010) [1080p hevc]")

    def test_custom_preset_default(self) -> None:
        result = format_movie_folder(PRESETS["custom"].movie_template, _ctx())
        self.assertEqual(result, "Inception (2010)")

    def test_default_tv_preset(self) -> None:
        ctx = _ctx(series="Breaking Bad", year="2008")
        result = format_tv_series_folder(PRESETS["default"].tv_template, ctx)
        self.assertEqual(result, "Breaking Bad (2008)")


class VariablesManquantesTests(unittest.TestCase):
    """Variables manquantes → nettoyage propre."""

    def test_resolution_manquante_jellyfin(self) -> None:
        """Jellyfin sans resolution → crochets nettoyes."""
        ctx = _ctx(resolution="")
        result = format_movie_folder("{title} ({year}) [{resolution}]", ctx)
        self.assertEqual(result, "Inception (2010)")

    def test_tmdb_id_manquant_plex(self) -> None:
        """Plex sans tmdb_id → segment tmdb_tag supprime."""
        ctx = _ctx(tmdb_id="", tmdb_tag="")
        result = format_movie_folder("{title} ({year}) {tmdb_tag}", ctx)
        self.assertEqual(result, "Inception (2010)")

    def test_codec_et_resolution_manquants(self) -> None:
        ctx = _ctx(resolution="", video_codec="")
        result = format_movie_folder("{title} ({year}) [{resolution} {video_codec}]", ctx)
        self.assertEqual(result, "Inception (2010)")

    def test_toutes_variables_manquantes_sauf_title(self) -> None:
        ctx = _ctx(year="", resolution="", video_codec="", tmdb_tag="")
        result = format_movie_folder("{title} ({year}) [{resolution}]", ctx)
        self.assertEqual(result, "Inception")


class AnneeTests(unittest.TestCase):
    """Gestion de l'annee 0 et vide."""

    def test_annee_zero(self) -> None:
        ctx = _ctx(year="")
        result = format_movie_folder("{title} ({year})", ctx)
        self.assertEqual(result, "Inception")

    def test_annee_zero_avec_resolution(self) -> None:
        ctx = _ctx(year="", resolution="1080p")
        result = format_movie_folder("{title} ({year}) [{resolution}]", ctx)
        self.assertEqual(result, "Inception [1080p]")


class TmdbTagTests(unittest.TestCase):
    """{tmdb_tag} avec et sans tmdb_id."""

    def test_tmdb_tag_avec_id(self) -> None:
        ctx = _ctx(tmdb_tag="{tmdb-27205}")
        result = format_movie_folder("{title} ({year}) {tmdb_tag}", ctx)
        self.assertIn("{tmdb-27205}", result)

    def test_tmdb_tag_sans_id(self) -> None:
        ctx = _ctx(tmdb_tag="")
        result = format_movie_folder("{title} ({year}) {tmdb_tag}", ctx)
        self.assertEqual(result, "Inception (2010)")


class WindowsSafeTests(unittest.TestCase):
    """Caracteres interdits Windows sanitises."""

    def test_caracteres_interdits_dans_titre(self) -> None:
        ctx = _ctx(title='Film: "Subtitle" <test>')
        result = format_movie_folder("{title} ({year})", ctx)
        # Les caracteres <>:"" sont supprimes par windows_safe
        self.assertNotIn(":", result)
        self.assertNotIn('"', result)
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

    def test_unicode_accents(self) -> None:
        ctx = _ctx(title="Les Misérables")
        result = format_movie_folder("{title} ({year})", ctx)
        self.assertEqual(result, "Les Misérables (2010)")

    def test_emoji_dans_titre(self) -> None:
        ctx = _ctx(title="Film 🎬 Test")
        result = format_movie_folder("{title} ({year})", ctx)
        self.assertIn("Film", result)
        self.assertIn("Test", result)


class ValidateTemplateTests(unittest.TestCase):
    """validate_template : variables connues/inconnues, structure."""

    def test_template_valide(self) -> None:
        ok, errors = validate_template("{title} ({year})")
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_template_valide_complexe(self) -> None:
        ok, errors = validate_template("{title} ({year}) [{resolution} {video_codec}] {tmdb_tag}")
        self.assertTrue(ok)

    def test_variable_inconnue(self) -> None:
        ok, errors = validate_template("{title} ({year}) {foobar}")
        self.assertFalse(ok)
        self.assertTrue(any("foobar" in e for e in errors))

    def test_template_vide(self) -> None:
        ok, errors = validate_template("")
        self.assertFalse(ok)
        self.assertTrue(any("vide" in e for e in errors))

    def test_accolade_non_fermee(self) -> None:
        ok, errors = validate_template("{title ({year})")
        self.assertFalse(ok)

    def test_sans_title_ni_series(self) -> None:
        ok, errors = validate_template("{year} [{resolution}]")
        self.assertFalse(ok)
        self.assertTrue(any("title" in e or "series" in e for e in errors))

    def test_avec_series(self) -> None:
        ok, errors = validate_template("{series} ({year})")
        self.assertTrue(ok)

    def test_toutes_variables_connues(self) -> None:
        """Chaque variable connue est acceptee."""
        from cinesort.domain.naming import _KNOWN_VARS

        # Construire un template avec toutes les variables
        tpl = "{title} " + " ".join(f"{{{v}}}" for v in sorted(_KNOWN_VARS) if v != "title")
        ok, errors = validate_template(tpl)
        self.assertTrue(ok, f"Erreurs inattendues : {errors}")


class FallbackTests(unittest.TestCase):
    """Template vide ou resultat vide → fallback."""

    def test_template_vide_fallback(self) -> None:
        result = format_movie_folder("", _ctx())
        self.assertEqual(result, "Inception (2010)")

    def test_template_none_fallback(self) -> None:
        result = format_movie_folder(None, _ctx())
        self.assertEqual(result, "Inception (2010)")

    def test_resultat_vide_apres_substitution(self) -> None:
        """Si toutes les variables sont vides, fallback sur le titre."""
        ctx = {"title": "Inception", "year": "2010"}
        result = format_movie_folder("{resolution}", ctx)
        # resolution vide → resultat vide → fallback
        self.assertEqual(result, "Inception (2010)")


class BuildNamingContextTests(unittest.TestCase):
    """Construction du contexte a partir des donnees brutes."""

    def test_contexte_minimal(self) -> None:
        ctx = build_naming_context(title="Inception", year=2010)
        self.assertEqual(ctx["title"], "Inception")
        self.assertEqual(ctx["year"], "2010")
        self.assertEqual(ctx["tmdb_tag"], "")

    def test_contexte_avec_tmdb(self) -> None:
        ctx = build_naming_context(title="Inception", year=2010, tmdb_id=27205)
        self.assertEqual(ctx["tmdb_id"], "27205")
        self.assertEqual(ctx["tmdb_tag"], "{tmdb-27205}")

    def test_contexte_avec_probe(self) -> None:
        probe = {
            "video": {"height": 1080, "codec": "hevc", "hdr10": False, "hdr_dolby_vision": False, "hdr10_plus": False},
            "audio_tracks": [{"codec": "truehd", "channels": 8}],
            "container": "mkv",
        }
        ctx = build_naming_context(title="Film", year=2020, probe_data=probe)
        self.assertEqual(ctx["resolution"], "1080p")
        self.assertEqual(ctx["video_codec"], "hevc")
        self.assertEqual(ctx["audio_codec"], "truehd")
        self.assertEqual(ctx["channels"], "7.1")
        self.assertEqual(ctx["container"], "mkv")

    def test_contexte_sans_probe(self) -> None:
        ctx = build_naming_context(title="Film", year=2020)
        self.assertEqual(ctx["resolution"], "")
        self.assertEqual(ctx["video_codec"], "")

    def test_contexte_avec_qualite(self) -> None:
        ctx = build_naming_context(title="Film", year=2020, quality_data={"tier": "Premium", "score": 92})
        self.assertEqual(ctx["quality"], "Premium")
        self.assertEqual(ctx["score"], "92")

    def test_contexte_tv(self) -> None:
        ctx = build_naming_context(
            title="Ozymandias",
            year=2013,
            tv_series_name="Breaking Bad",
            tv_season=5,
            tv_episode=14,
            tv_episode_title="Ozymandias",
        )
        self.assertEqual(ctx["series"], "Breaking Bad")
        self.assertEqual(ctx["season"], "05")
        self.assertEqual(ctx["episode"], "14")
        self.assertEqual(ctx["ep_title"], "Ozymandias")

    def test_annee_zero_donne_vide(self) -> None:
        ctx = build_naming_context(title="Film", year=0)
        self.assertEqual(ctx["year"], "")

    def test_resolution_2160(self) -> None:
        probe = {"video": {"height": 2160}}
        ctx = build_naming_context(title="Film", year=2020, probe_data=probe)
        self.assertEqual(ctx["resolution"], "2160p")

    def test_resolution_720(self) -> None:
        probe = {"video": {"height": 720}}
        ctx = build_naming_context(title="Film", year=2020, probe_data=probe)
        self.assertEqual(ctx["resolution"], "720p")

    def test_hdr_dolby_vision(self) -> None:
        probe = {"video": {"hdr_dolby_vision": True}}
        ctx = build_naming_context(title="Film", year=2020, probe_data=probe)
        self.assertEqual(ctx["hdr"], "DV")

    def test_channels_2(self) -> None:
        probe = {"audio_tracks": [{"codec": "aac", "channels": 2}]}
        ctx = build_naming_context(title="Film", year=2020, probe_data=probe)
        self.assertEqual(ctx["channels"], "2.0")


class PathLengthTests(unittest.TestCase):
    """Warning si path > 240 chars."""

    def test_path_court_pas_de_warning(self) -> None:
        result = check_path_length("D:\\Films", "Inception (2010)")
        self.assertIsNone(result)

    def test_path_long_warning(self) -> None:
        long_name = "A" * 250
        result = check_path_length("D:\\Films", long_name)
        self.assertIsNotNone(result)
        self.assertIn("240", result)

    def test_path_exact_240_pas_de_warning(self) -> None:
        root = "D:\\Films"
        # root + \\ + name = 240
        name = "A" * (240 - len(root) - 1)
        result = check_path_length(root, name)
        self.assertIsNone(result)


class PreviewMockTests(unittest.TestCase):
    """Le mock hardcode est toujours disponible."""

    def test_mock_context_has_all_vars(self) -> None:
        from cinesort.domain.naming import _KNOWN_VARS

        for var in _KNOWN_VARS:
            self.assertIn(var, PREVIEW_MOCK_CONTEXT, f"Variable {var} manquante dans PREVIEW_MOCK_CONTEXT")

    def test_mock_produces_correct_default(self) -> None:
        result = format_movie_folder("{title} ({year})", PREVIEW_MOCK_CONTEXT)
        self.assertEqual(result, "Inception (2010)")


# ====================================================================
# Phase C — Conformance check
# ====================================================================


class FolderMatchesTemplateTests(unittest.TestCase):
    """folder_matches_template : verification de conformance avec le template actif."""

    def test_default_template_match(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        self.assertTrue(folder_matches_template("Inception (2010)", "{title} ({year})", "Inception", 2010))

    def test_default_template_no_match(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        self.assertFalse(folder_matches_template("DivX_Inception", "{title} ({year})", "Inception", 2010))

    def test_plex_template_match_without_tmdb(self) -> None:
        """Plex sans tmdb_id : le dossier 'Title (Year)' est conforme (tmdb_tag vide → nettoye)."""
        from cinesort.domain.naming import folder_matches_template

        # Sans tmdb_id dans le contexte minimal, le template produit "Inception (2010)"
        self.assertTrue(
            folder_matches_template(
                "Inception (2010)",
                "{title} ({year}) {tmdb_tag}",
                "Inception",
                2010,
            )
        )

    def test_jellyfin_template_match_no_probe(self) -> None:
        """Jellyfin sans probe → le dossier est juste 'Title (Year)' (resolution vide)."""
        from cinesort.domain.naming import folder_matches_template

        # Sans probe, format_movie_folder produit "Inception (2010)" car [] nettoye
        self.assertTrue(
            folder_matches_template(
                "Inception (2010)",
                "{title} ({year}) [{resolution}]",
                "Inception",
                2010,
            )
        )

    def test_quality_template_match_no_probe(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        self.assertTrue(
            folder_matches_template(
                "Inception (2010)",
                "{title} ({year}) [{resolution} {video_codec}]",
                "Inception",
                2010,
            )
        )

    def test_titre_avec_caracteres_speciaux(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        self.assertTrue(
            folder_matches_template(
                "Les Miserables (2012)",
                "{title} ({year})",
                "Les Miserables",
                2012,
            )
        )

    def test_annee_manquante(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        # Annee 0 → format produit "Inception" (sans parentheses)
        self.assertTrue(folder_matches_template("Inception", "{title} ({year})", "Inception", 0))

    def test_old_format_avec_nouveau_template(self) -> None:
        """Un dossier ancien format matche toujours car le template default produit le meme resultat."""
        from cinesort.domain.naming import folder_matches_template

        # Le template plex produirait "Inception (2010) {tmdb-}" → nettoye en "Inception (2010)"
        # car tmdb_tag vide → resultat identique au format historique
        self.assertTrue(
            folder_matches_template(
                "Inception (2010)",
                "{title} ({year}) {tmdb_tag}",
                "Inception",
                2010,
            )
        )

    def test_case_insensitive(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        self.assertTrue(
            folder_matches_template(
                "inception (2010)",
                "{title} ({year})",
                "Inception",
                2010,
            )
        )

    def test_empty_title(self) -> None:
        from cinesort.domain.naming import folder_matches_template

        self.assertFalse(folder_matches_template("Some Folder", "{title} ({year})", "", 2010))


class SingleFolderIsConformWithTemplateTests(unittest.TestCase):
    """single_folder_is_conform avec naming_template."""

    def test_conform_with_default_template(self) -> None:
        from cinesort.domain.duplicate_support import single_folder_is_conform, movie_dir_title_year

        # Cf issue #83 phase 2 : _norm_for_tokens depuis l'origine (title_helpers)
        from cinesort.domain.core import windows_safe
        from cinesort.domain.title_helpers import _norm_for_tokens

        result = single_folder_is_conform(
            "Inception (2010)",
            "Inception",
            2010,
            windows_safe=windows_safe,
            norm_for_tokens=_norm_for_tokens,
            movie_dir_title_year=movie_dir_title_year,
            naming_template="{title} ({year})",
        )
        self.assertTrue(result)

    def test_conform_fallback_without_template(self) -> None:
        """Sans template, le fallback historique fonctionne."""
        from cinesort.domain.duplicate_support import single_folder_is_conform, movie_dir_title_year

        # Cf issue #83 phase 2 : _norm_for_tokens depuis l'origine (title_helpers)
        from cinesort.domain.core import windows_safe
        from cinesort.domain.title_helpers import _norm_for_tokens

        result = single_folder_is_conform(
            "Inception (2010)",
            "Inception",
            2010,
            windows_safe=windows_safe,
            norm_for_tokens=_norm_for_tokens,
            movie_dir_title_year=movie_dir_title_year,
        )
        self.assertTrue(result)


# ====================================================================
# Phase D — Settings naming
# ====================================================================


class NamingSettingsTests(unittest.TestCase):
    """Tests du round-trip settings pour les profils de renommage."""

    def _make_api(self):
        import tempfile
        from pathlib import Path
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_naming_")
        root = Path(tmp) / "root"
        state = Path(tmp) / "state"
        root.mkdir()
        state.mkdir()
        api = backend.CineSortApi()
        api.settings.save_settings({"root": str(root), "state_dir": str(state), "tmdb_enabled": False})
        return api, tmp

    def test_default_naming_settings(self) -> None:
        api, tmp = self._make_api()
        try:
            s = api.settings.get_settings()
            self.assertEqual(s.get("naming_preset"), "default")
            self.assertEqual(s.get("naming_movie_template"), "{title} ({year})")
            self.assertEqual(s.get("naming_tv_template"), "{series} ({year})")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_save_plex_preset(self) -> None:
        api, tmp = self._make_api()
        try:
            s = api.settings.get_settings()
            s["naming_preset"] = "plex"
            api.settings.save_settings(s)
            reloaded = api.settings.get_settings()
            self.assertEqual(reloaded["naming_preset"], "plex")
            self.assertIn("tmdb_tag", reloaded["naming_movie_template"])
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_custom_template_preserved(self) -> None:
        api, tmp = self._make_api()
        try:
            s = api.settings.get_settings()
            s["naming_preset"] = "custom"
            s["naming_movie_template"] = "{title} [{resolution}]"
            api.settings.save_settings(s)
            reloaded = api.settings.get_settings()
            self.assertEqual(reloaded["naming_preset"], "custom")
            self.assertEqual(reloaded["naming_movie_template"], "{title} [{resolution}]")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_custom_template_fallback(self) -> None:
        api, tmp = self._make_api()
        try:
            s = api.settings.get_settings()
            s["naming_preset"] = "custom"
            s["naming_movie_template"] = "{foobar} [{badvar}]"
            api.settings.save_settings(s)
            reloaded = api.settings.get_settings()
            # Template invalide → fallback
            self.assertEqual(reloaded["naming_movie_template"], "{title} ({year})")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_preset_fallback(self) -> None:
        api, tmp = self._make_api()
        try:
            s = api.settings.get_settings()
            s["naming_preset"] = "nonexistent"
            api.settings.save_settings(s)
            reloaded = api.settings.get_settings()
            self.assertEqual(reloaded["naming_preset"], "default")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================
# Phase F — Endpoint preview
# ====================================================================


class PreviewNamingEndpointTests(unittest.TestCase):
    """Tests de l'endpoint preview_naming_template."""

    def _make_api(self):
        import tempfile
        from pathlib import Path
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_naming_prev_")
        root = Path(tmp) / "root"
        state = Path(tmp) / "state"
        root.mkdir()
        state.mkdir()
        api = backend.CineSortApi()
        api.settings.save_settings({"root": str(root), "state_dir": str(state), "tmdb_enabled": False})
        return api, tmp

    def test_preview_default_template(self) -> None:
        api, tmp = self._make_api()
        try:
            result = api.preview_naming_template(template="{title} ({year})")
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"], "Inception (2010)")
            self.assertIn("variables", result)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_plex_template(self) -> None:
        api, tmp = self._make_api()
        try:
            result = api.preview_naming_template(template="{title} ({year}) {tmdb_tag}")
            self.assertTrue(result["ok"])
            self.assertIn("{tmdb-27205}", result["result"])
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_jellyfin_template(self) -> None:
        api, tmp = self._make_api()
        try:
            result = api.preview_naming_template(template="{title} ({year}) [{resolution}]")
            self.assertTrue(result["ok"])
            self.assertIn("1080p", result["result"])
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_invalid_template(self) -> None:
        api, tmp = self._make_api()
        try:
            result = api.preview_naming_template(template="{badvar} ({year})")
            self.assertFalse(result["ok"])
            self.assertIn("errors", result)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_empty_template_uses_default(self) -> None:
        api, tmp = self._make_api()
        try:
            result = api.preview_naming_template(template="")
            # Template vide → le parametre default "{title} ({year})" est utilise
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"], "Inception (2010)")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_naming_presets(self) -> None:
        api, tmp = self._make_api()
        try:
            result = api.get_naming_presets()
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["presets"]), 5)
            ids = {p["id"] for p in result["presets"]}
            self.assertEqual(ids, {"default", "plex", "jellyfin", "quality", "custom"})
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
