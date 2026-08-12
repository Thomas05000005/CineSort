"""Tests de regression - audit 2026-05-24 (v1.5.0).

Couvre les fixes du sprint d'audit qui ont reintroduit silencieusement des
endpoints et sections settings perdus, et corrige des appels API frontend
incoherents avec les facades Python.

Bugs couverts :
- `run_id_or` -> `run_id: "latest"` dans traitement.js / doublons.js
  (parametre `run_id_or` n'existe pas dans la facade run/get_dashboard).
- Sections settings absentes du dispatcher (`_save_section_omdb`,
  `_save_section_naming`, `_save_section_sources`, `_save_section_advanced`)
  qui causaient un drop silencieux de 16+ champs UI a chaque save.
- Endpoint `runtime/open_external_url` manquant cote facade alors qu'il
  etait appele depuis le frontend.
- `analyze_perceptual_single` n'existe pas backend : film-detail.js doit
  utiliser `quality/analyze_perceptual_batch` avec `row_ids: [rowId]`.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from cinesort.ui.api import settings_support
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.facades import runtime_facade

_ROOT = Path(__file__).resolve().parents[1]


class FrontendApiCallsTests(unittest.TestCase):
    """Verifie que le frontend utilise les bons noms de parametres."""

    def _strip_comments(self, src: str) -> str:
        """Retire commentaires // et /* */ pour eviter les faux positifs sur
        les mentions historiques (ex: `Fix audit ... avant run_id_or`).
        """
        import re

        # Bloc /* ... */ (non-greedy, multiline).
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        # Ligne // ... jusqu'au newline.
        src = re.sub(r"//[^\n]*", "", src)
        return src

    def test_run_id_param_in_traitement_js(self):
        path = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
        content = path.read_text(encoding="utf-8")
        code = self._strip_comments(content)
        self.assertNotIn(
            "run_id_or",
            code,
            "traitement.js ne doit plus utiliser `run_id_or` (parametre inexistant) hors commentaires.",
        )
        self.assertIn(
            'run_id: "latest"',
            content,
            'traitement.js doit utiliser `run_id: "latest"` pour run/get_dashboard.',
        )

    def test_run_id_param_in_doublons_js(self):
        path = _ROOT / "web" / "dashboard" / "views" / "doublons.js"
        content = path.read_text(encoding="utf-8")
        code = self._strip_comments(content)
        self.assertNotIn(
            "run_id_or",
            code,
            "doublons.js ne doit plus utiliser `run_id_or` (parametre inexistant) hors commentaires.",
        )
        self.assertIn(
            'run_id: "latest"',
            content,
            'doublons.js doit utiliser `run_id: "latest"` pour run/get_dashboard.',
        )

    def test_film_detail_uses_perceptual_batch(self):
        # R8-053/054/055 (F5, D1) : la vue standalone web/dashboard/views/film-detail.js
        # a été SUPPRIMÉE ; le composant components/film-detail.js est désormais la fiche
        # film canonique. Il délègue le perceptuel à la modale (get_perceptual_details) et
        # ne doit PAS appeler l'endpoint inexistant analyze_perceptual_single comme apiPost.
        # L'ancienne assertion "analyze_perceptual_batch" était propre à l'implémentation
        # de la vue supprimée (design différent du composant) -> retirée.
        path = _ROOT / "web" / "dashboard" / "components" / "film-detail.js"
        content = path.read_text(encoding="utf-8")
        self.assertNotIn(
            '"quality/analyze_perceptual_single"',
            content,
            "film-detail.js ne doit pas appeler l'endpoint inexistant `quality/analyze_perceptual_single`.",
        )


class SettingsDispatcherSectionsTests(unittest.TestCase):
    """Verifie que chaque section settings dispose d'un handler ET est appelee
    dans le dispatcher principal (`build_settings_payload`).
    """

    def _dispatcher_source(self) -> str:
        # Source du dispatcher central qui agrege toutes les sections.
        # Fix lost-update : save_settings_payload est devenu un wrapper qui
        # prend le verrou par state_dir puis delegue a
        # _save_settings_payload_locked (ou vivent les appels _save_section_*).
        # On concatene les deux sources pour que le contrat « la section est
        # appelee dans le flux de save » survive aux refactors wrapper/helper.
        src = inspect.getsource(settings_support.save_settings_payload)
        # La chaine du flux de sauvegarde s'est allongee d'un maillon a chaque
        # refactor : wrapper -> _save_settings_payload_locked -> _appliquer_les_sections
        # (ou vivent desormais les appels _save_section_*). On concatene TOUS les
        # maillons connus pour que le contrat survive.
        #
        # CETTE GARDE LIT UNE CHAINE DE SOURCE, ce que le depot proscrit : elle
        # devient aveugle au prochain maillon que personne ne pensera a ajouter
        # ici. C'est exactement ce qui vient d'arriver. Elle est donc DOUBLEE par
        # `AucuneSectionNEstDroppeeTests` plus bas, qui eprouve l'EFFET — les
        # cles arrivent-elles sur le disque — et ne depend d'aucun nom de
        # fonction intermediaire.
        for nom in ("_save_settings_payload_locked", "_appliquer_les_sections"):
            maillon = getattr(settings_support, nom, None)
            if maillon is not None:
                src += inspect.getsource(maillon)
        return src

    def test_save_section_omdb_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_omdb"),
            "`_save_section_omdb` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_omdb",
            self._dispatcher_source(),
            "`_save_section_omdb` doit etre appele dans save_settings_payload.",
        )

    def test_save_section_naming_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_naming"),
            "`_save_section_naming` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_naming",
            self._dispatcher_source(),
            "`_save_section_naming` doit etre appele dans save_settings_payload.",
        )

    def test_save_section_sources_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_sources"),
            "`_save_section_sources` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_sources",
            self._dispatcher_source(),
            "`_save_section_sources` doit etre appele dans save_settings_payload.",
        )

    def test_save_section_advanced_exists(self):
        self.assertTrue(
            hasattr(settings_support, "_save_section_advanced"),
            "`_save_section_advanced` doit exister dans settings_support.",
        )
        self.assertIn(
            "_save_section_advanced",
            self._dispatcher_source(),
            "`_save_section_advanced` doit etre appele dans save_settings_payload.",
        )


class RuntimeOpenExternalUrlTests(unittest.TestCase):
    """Verifie que l'endpoint `runtime/open_external_url` existe cote API."""

    def test_open_external_url_endpoint_exists(self):
        # Cote CineSortApi : implementation interne `_open_external_url_impl`.
        self.assertTrue(
            hasattr(CineSortApi, "_open_external_url_impl"),
            "CineSortApi doit exposer `_open_external_url_impl`.",
        )
        # Cote facade : methode publique `open_external_url`.
        self.assertTrue(
            hasattr(runtime_facade.RuntimeFacade, "open_external_url"),
            "RuntimeFacade doit exposer `open_external_url`.",
        )


# Fix audit 2026-05-24 (v1.5.2) : Vague E — flow update manuel
# Ajout bouton "Verifier maintenant" + carte "Nouvelle version disponible" sur
# Accueil + support `force_refresh` cote backend pour reutiliser le meme
# endpoint `runtime/get_update_info`.
class ParametresUpdateSectionTests(unittest.TestCase):
    """Vague E : Parametres > Avance > Mises a jour expose le bouton manuel."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (_ROOT / "web" / "dashboard" / "views" / "parametres.js").read_text(encoding="utf-8")

    def test_parametres_has_update_section(self):
        """La sous-section 'updates' doit exister avec son label 'Mises a jour'."""
        self.assertIn('id: "updates"', self.js, "Sous-section 'updates' absente de parametres.js")
        self.assertIn('"Mises à jour"', self.js, "Label de la sous-section 'updates' absent")

    def test_parametres_has_check_updates_button(self):
        """Le bouton manuel 'Verifier maintenant' doit etre present."""
        self.assertIn(
            'action: "check_updates_now"',
            self.js,
            "Action 'check_updates_now' absente — bouton manuel non declare",
        )
        self.assertIn(
            "Vérifier maintenant",
            self.js,
            "Label du bouton 'Verifier maintenant' absent",
        )

    def test_parametres_check_updates_calls_get_update_info_with_force_refresh(self):
        """Le handler doit appeler runtime/get_update_info avec force_refresh: true."""
        self.assertIn(
            'apiPost("runtime/get_update_info", { force_refresh: true })',
            self.js,
            "Le handler du bouton doit forcer le check via force_refresh=true",
        )

    def test_parametres_check_updates_uses_open_external_url(self):
        """Les boutons 'Voir' / 'Telecharger' doivent ouvrir l'URL via runtime."""
        self.assertIn(
            'apiPost("runtime/open_external_url"',
            self.js,
            "Les boutons Voir/Telecharger doivent passer par runtime/open_external_url",
        )


class GetUpdateInfoForceRefreshTests(unittest.TestCase):
    """Vague E : `runtime/get_update_info` accepte `force_refresh` (delegate)."""

    def test_facade_signature_accepts_force_refresh(self):
        sig = inspect.signature(runtime_facade.RuntimeFacade.get_update_info)
        self.assertIn(
            "force_refresh",
            sig.parameters,
            "RuntimeFacade.get_update_info doit accepter `force_refresh`",
        )
        # Defaut a False pour preserver la backward-compat (cache only).
        self.assertEqual(
            sig.parameters["force_refresh"].default,
            False,
            "force_refresh doit defaut a False (backward-compat)",
        )

    def test_impl_signature_accepts_force_refresh(self):
        sig = inspect.signature(CineSortApi._get_update_info_impl)
        self.assertIn(
            "force_refresh",
            sig.parameters,
            "_get_update_info_impl doit accepter `force_refresh`",
        )

    def test_get_update_info_supports_force_refresh(self):
        """Avec force_refresh=True, l'impl delegue a _check_for_updates_impl."""
        # On utilise un MagicMock pour eviter le boot complet de CineSortApi.
        from unittest.mock import MagicMock

        api = CineSortApi.__new__(CineSortApi)
        api._check_for_updates_impl = MagicMock(return_value={"ok": True, "data": {"update_available": True}})
        # Appel avec force_refresh -> delegate.
        result = api._get_update_info_impl(force_refresh=True)
        api._check_for_updates_impl.assert_called_once()
        self.assertEqual(result, {"ok": True, "data": {"update_available": True}})


class AccueilUpdateCardTests(unittest.TestCase):
    """Vague E : Accueil affiche une carte discrete si update detectee."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (_ROOT / "web" / "dashboard" / "views" / "accueil.js").read_text(encoding="utf-8")

    def test_accueil_fetches_update_info(self):
        """initAccueil doit recuperer runtime/get_update_info au boot."""
        self.assertIn(
            'apiPost("runtime/get_update_info"',
            self.js,
            "Accueil doit fetcher runtime/get_update_info pour la carte update",
        )

    def test_accueil_render_update_card_helper_present(self):
        self.assertIn(
            "_renderUpdateCard",
            self.js,
            "Helper _renderUpdateCard absent",
        )

    def test_accueil_update_card_only_when_available(self):
        """La carte n'est rendue que si update_available et latest_version."""
        self.assertIn("update_available", self.js)
        self.assertIn("data-accueil-update-url", self.js)


class AucuneSectionNEstDroppeeTests(unittest.TestCase):
    """AUCUNE cle connue d'une section ne doit disparaitre a la sauvegarde.

    POURQUOI CETTE GARDE EXISTE, ET POURQUOI ELLE NE LIT PAS DE SOURCE.
    `save_settings` construit ce qu'il ecrit : une cle qu'aucune section ne
    reclame n'est jamais recopiee, et la sauvegarde rend quand meme `ok: True`.
    Ce defaut s'est produit AU MOINS DEUX FOIS :

      - 2026-05-24 : 16 champs UI silencieusement droppes (sections naming,
        sources, advanced manquantes) ;
      - plus tard : `custom_quality_profiles` et `active_quality_profile_id`,
        dont la disparition rendait `save_profile` sans effet et faisait
        detruire le profil de l'utilisateur par `reset_database`.

    `SettingsDispatcherSectionsTests` ci-dessus cherche les noms de fonctions
    dans une CHAINE DE SOURCE. Elle est devenue aveugle des qu'un maillon
    intermediaire a ete ajoute a la chaine d'appel — c'est arrive, et elle a
    rougi pour cette raison-la, pas parce qu'une section manquait.

    Cette garde-ci ne cite aucun nom de fonction : elle DEMANDE a chaque section
    quelles cles elle produit, puis verifie qu'elles arrivent bien dans le
    fichier ecrit. Elle survit donc a n'importe quel refactor de la chaine, et
    une section ajoutee sans etre branchee la fait rougir immediatement.
    """

    #: Les trois sections qui exigent un parametre en plus de la charge utile.
    #: Elles sont couvertes par les MEMES assertions, avec leurs defauts.
    _EXTRAS = {
        "_save_section_cleanup": {
            "default_collection_folder_name": "Collections",
            "default_empty_folders_folder_name": "Vides",
            "default_residual_cleanup_folder_name": "Residus",
        },
        "_save_section_probe": {"default_probe_backend": "ffprobe"},
        "_save_section_appearance": {"debug_enabled": False},
    }

    def _sections(self) -> dict:
        return {n: getattr(settings_support, n) for n in dir(settings_support) if n.startswith("_save_section_")}

    def test_toutes_les_cles_de_toutes_les_sections_sont_ecrites(self) -> None:
        import shutil
        import tempfile

        from cinesort.ui.api.cinesort_api import CineSortApi

        sections = self._sections()
        self.assertGreater(len(sections), 15, "l'introspection n'a trouve presque aucune section : elle est cassee")

        attendues: dict[str, str] = {}
        for nom, fonction in sections.items():
            for cle in fonction({}, **self._EXTRAS.get(nom, {})):
                attendues[cle] = nom

        tmp = Path(tempfile.mkdtemp(prefix="cinesort_sections_"))
        try:
            api = CineSortApi()
            api._state_dir = tmp / "state"  # type: ignore[attr-defined]
            api._state_dir.mkdir(parents=True, exist_ok=True)
            api.settings.save_settings(api.settings.get_settings() or {})
            ecrites = set(api.settings.get_settings() or {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        manquantes = sorted(k for k in attendues if k not in ecrites)
        self.assertEqual(
            manquantes,
            [],
            "des cles produites par une section n'arrivent pas dans les reglages sauvegardes — "
            "la section n'est pas branchee dans le flux de save : "
            + ", ".join(f"{k} ({attendues[k]})" for k in manquantes),
        )

    def test_la_section_des_profils_qualite_est_branchee(self) -> None:
        """Le cas nomme, pour que l'echec soit lisible s'il revient."""
        import shutil
        import tempfile

        from cinesort.ui.api.cinesort_api import CineSortApi

        tmp = Path(tempfile.mkdtemp(prefix="cinesort_sections_qp_"))
        try:
            api = CineSortApi()
            api._state_dir = tmp / "state"  # type: ignore[attr-defined]
            api._state_dir.mkdir(parents=True, exist_ok=True)
            reglages = api.settings.get_settings() or {}
            reglages["custom_quality_profiles"] = [{"id": "temoin"}]
            reglages["active_quality_profile_id"] = "temoin"
            api.settings.save_settings(reglages)
            relu = api.settings.get_settings() or {}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertEqual([e.get("id") for e in (relu.get("custom_quality_profiles") or [])], ["temoin"])
        self.assertEqual(relu.get("active_quality_profile_id"), "temoin")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
