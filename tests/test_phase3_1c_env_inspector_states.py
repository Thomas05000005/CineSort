"""Tests Phase 3.1-C : Accueil — Environment bar + Inspecteur droit + États dynamiques.

Etend les tests Phase 3.1-A et 3.1-B. Couvre la section 1 + l'inspecteur droit
+ l'etat "scan en cours" selon spec 05-accueil.md.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests._jsexec import require_node, run_module_test

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_KEYBOARD_JS = _ROOT / "web" / "dashboard" / "core" / "keyboard.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class EnvironmentBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_render_environment_bar_function(self) -> None:
        # Phase 5 : la signature accepte un 3eme parametre optionnel pingResults
        # pour le statut hors-ligne. On verifie au moins les 2 premiers.
        self.assertIn("function _renderEnvironmentBar(roots, settings", self.js)

    def test_integrations_list_complete(self) -> None:
        # Spec : 5 integrations - TMDb, Jellyfin, Plex, Radarr, OMDb.
        for key in ("tmdb", "jellyfin", "plex", "radarr", "omdb"):
            self.assertIn(f'key: "{key}"', self.js, f"integration {key} manquante")

    def test_roots_truncated_to_2(self) -> None:
        # Spec §2.1 : tronque si > 2 roots, affiche "+N" pour le surplus.
        self.assertIn("rootsList.slice(0, 2)", self.js)
        self.assertIn("accueil-env-more", self.js)

    def test_empty_roots_message(self) -> None:
        self.assertIn("Aucun root configuré", self.js)

    def test_pill_states_ok_and_off(self) -> None:
        self.assertIn("is-ok", self.js)
        self.assertIn("is-off", self.js)

    def test_pills_clickable_to_settings_integrations(self) -> None:
        # Spec §2.1 : clic pastille -> Paramètres > Intégrations > section concernée.
        self.assertIn('data-integration="', self.js)
        self.assertIn("/parametres#integrations-", self.js)

    def test_bar_displayed_at_top(self) -> None:
        # Doit apparaitre dans _renderAccueil AVANT le hero. On cherche les
        # APPELS dans le HTML template (chaque appel est prefixe par ${).
        # Phase 5 : l'appel inclut maintenant un 3eme argument (pingSnapshot).
        import re

        rendered = self.js
        env_pos = -1
        for m in re.finditer(r"\$\{_renderEnvironmentBar\(roots, settings[^}]*\)\}", rendered):
            env_pos = m.start()
            break
        hero_pos = rendered.find("${_renderHero(heroState)}")
        self.assertNotEqual(env_pos, -1, "Environment bar non rendue dans le template _renderAccueil")
        self.assertNotEqual(hero_pos, -1, "Hero non rendu dans le template _renderAccueil")
        self.assertLess(env_pos, hero_pos, "Environment bar doit etre AVANT le Hero dans le template")


class ScanInProgressStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_extract_scan_progress_function(self) -> None:
        self.assertIn("function _extractScanProgress(payload)", self.js)

    def test_render_scan_in_progress_function(self) -> None:
        self.assertIn("function _renderScanInProgress(progress)", self.js)

    def test_progress_bar_with_aria(self) -> None:
        self.assertIn('class="accueil-cta-scan-bar"', self.js)
        self.assertIn('role="progressbar"', self.js)

    def test_cta_branches_on_scan_active(self) -> None:
        # _renderCtaScan retourne _renderScanInProgress si scanProgress.active.
        self.assertIn("if (scanProgress && scanProgress.active)", self.js)

    def test_view_traitement_action_present(self) -> None:
        self.assertIn("open-traitement", self.js)
        self.assertIn("Voir le détail", self.js)


class InspectorContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_import_right_panel(self) -> None:
        self.assertIn('from "../components/right-panel.js"', self.js)
        self.assertIn("import * as rightPanel", self.js)

    def test_build_inspector_sections_function(self) -> None:
        self.assertIn("function _buildInspectorSections(payload, stats, settings)", self.js)

    def test_inspector_has_3_sections(self) -> None:
        # Spec §3 : Contexte / Rappels opérateur / Raccourcis.
        self.assertIn('title: "Contexte"', self.js)
        self.assertIn('title: "Rappels opérateur"', self.js)
        self.assertIn('title: "Raccourcis"', self.js)

    def test_context_section_shows_library_count(self) -> None:
        self.assertIn("Bibliothèque", self.js)
        self.assertIn("Run actif", self.js)
        self.assertIn("Dernier scan", self.js)

    def test_shortcuts_section_lists_keys(self) -> None:
        # Historique : ce test exigeait AUSSI "<kbd>Ctrl</kbd>+<kbd>S</kbd>".
        # L'inspecteur d'Accueil n'annonce (volontairement) qu'un sous-ensemble
        # des raccourcis globaux — la liste exhaustive vit dans la modale d'aide
        # (F1 / ?) et dans /aide. Or Ctrl+S n'a AUCUN effet sur l'Accueil : le
        # handler se contente d'emettre "cinesort:save-request", event qu'aucun
        # module n'ecoute aujourd'hui (verifiable : grep cinesort:save-request
        # ne rend que son emetteur). Exiger son affichage revenait a exiger que
        # l'UI annonce un raccourci mort. On verifie donc les 3 raccourcis
        # reellement pertinents ici, et surtout — cf ShortcutsAreRealRuntimeTests
        # — que TOUT raccourci annonce est effectivement pris en charge.
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>K</kbd>", self.js)
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>,</kbd>", self.js)
        self.assertIn("<kbd>?</kbd>", self.js)

    def test_reminders_logic_for_omdb_not_configured(self) -> None:
        # Spec §3 : alerte "OMDb non configuré".
        self.assertIn("OMDb non configuré", self.js)

    def test_reminders_for_awaiting_validation(self) -> None:
        self.assertIn("AWAITING_VALIDATION", self.js)
        self.assertIn("valider la run", self.js)

    def test_init_calls_right_panel_set_sections(self) -> None:
        self.assertIn("rightPanel.setSections(_buildInspectorSections(", self.js)


# --- Les raccourcis annonces existent-ils VRAIMENT ? ----------------------
#
# Une liste de <kbd> dans le source ne prouve rien : c'est du texte. Le seul
# contrat qui compte pour l'utilisateur est "ce que l'inspecteur annonce, le
# dashboard le fait". On rend donc la section Raccourcis au runtime, on en
# extrait les combinaisons, puis on rejoue chacune contre le VRAI handler de
# core/keyboard.js (initKeyboard) execute sous Node.

_ACCUEIL_STUBS = """
const escapeHtml = (s) => String(s == null ? "" : s);
const apiPost = async () => ({});
const getSettingsEpoch = () => 0;
const getNavSignal = () => null;
const navigateTo = () => {};
const rightPanel = { setSections: () => {}, setTitle: () => {} };
"""

_ACCUEIL_EXTRA = "export { _buildInspectorSections as __buildInspectorSections };\n"

_ACCUEIL_DRIVER = """
const sections = M.__buildInspectorSections({}, {}, {});
const shortcuts = sections.find((s) => s.title === "Raccourcis");
__emit({ titles: sections.map((s) => s.title), html: shortcuts ? shortcuts.html : null });
"""

_KEYBOARD_STUBS = """
globalThis.__fx = { nav: [], modal: 0, sidebar: 0, panel: 0, events: [] };
const navigateTo = (r) => { globalThis.__fx.nav.push(r); };
const showModal = () => { globalThis.__fx.modal += 1; };
const toggleSidebar = () => { globalThis.__fx.sidebar += 1; };
const isRightPanelExpanded = () => false;
const setRightPanelExpanded = () => { globalThis.__fx.panel += 1; };
globalThis.__handlers = [];
globalThis.document = {
  addEventListener: (type, h) => { if (type === "keydown") globalThis.__handlers.push(h); },
  activeElement: { tagName: "BODY" },
  querySelector: () => null,
  getElementById: () => null,
};
// Revue post-merge 2026-08-03 : `initKeyboard()` enregistre desormais un
// auditeur `cinesort:refresh` sur window (F5 + palette Ctrl+K rafraichissent
// reellement la vue). Un objet litteral sans addEventListener ne suffit plus :
// on utilise un vrai EventTarget, en gardant la sonde sur dispatchEvent.
globalThis.window = new EventTarget();
globalThis.window.location = { hash: "#/accueil" };
const _rawDispatch = globalThis.window.dispatchEvent.bind(globalThis.window);
globalThis.window.dispatchEvent = (e) => { globalThis.__fx.events.push(e.type); return _rawDispatch(e); };
"""

_KEYBOARD_EXTRA = ""


def _keyboard_driver(combos: list[dict]) -> str:
    """Rejoue chaque combinaison contre le handler reel et rapporte l'effet."""
    return (
        "M.initKeyboard();\n"
        f"const combos = {json.dumps(combos)};\n"
        """
const out = [];
for (const c of combos) {
  globalThis.__fx = { nav: [], modal: 0, sidebar: 0, panel: 0, events: [] };
  let prevented = false;
  const ev = {
    key: c.key,
    ctrlKey: !!c.ctrl,
    altKey: !!c.alt,
    shiftKey: !!c.shift,
    preventDefault: () => { prevented = true; },
  };
  for (const h of globalThis.__handlers) h(ev);
  const fx = globalThis.__fx;
  out.push({
    label: c.label,
    prevented,
    effects: fx.nav.length + fx.modal + fx.sidebar + fx.panel + fx.events.length,
  });
}
__emit({ handlerCount: globalThis.__handlers.length, results: out });
"""
    )


_KBD_RE = re.compile(r"<kbd>(.*?)</kbd>", re.S)
_DT_RE = re.compile(r"<dt>(.*?)</dt>", re.S)
_MODIFIERS = {"ctrl", "alt", "shift", "cmd", "meta"}


def _parse_shortcuts(html: str) -> list[dict]:
    """<dt><kbd>Ctrl</kbd>+<kbd>K</kbd></dt> -> {key: 'K', ctrl: True}."""
    combos: list[dict] = []
    for dt in _DT_RE.findall(html):
        tokens = [t.strip() for t in _KBD_RE.findall(dt)]
        mods = {t.lower() for t in tokens if t.lower() in _MODIFIERS}
        keys = [t for t in tokens if t.lower() not in _MODIFIERS]
        for key in keys:
            combos.append(
                {
                    "label": "+".join(sorted(mods) + [key]),
                    "key": key,
                    "ctrl": "ctrl" in mods,
                    "alt": "alt" in mods,
                    "shift": "shift" in mods,
                }
            )
    return combos


class ShortcutsAreRealRuntimeTests(unittest.TestCase):
    """Aucun raccourci annonce sur l'Accueil ne doit etre decoratif."""

    _inspector: dict | None = None

    def _inspector_or_skip(self) -> dict:
        require_node(self)
        if ShortcutsAreRealRuntimeTests._inspector is None:
            ShortcutsAreRealRuntimeTests._inspector = run_module_test(
                _ACCUEIL_JS,
                stubs=_ACCUEIL_STUBS,
                extra=_ACCUEIL_EXTRA,
                driver=_ACCUEIL_DRIVER,
            )
        return ShortcutsAreRealRuntimeTests._inspector

    def test_shortcuts_section_is_rendered_and_not_empty(self) -> None:
        data = self._inspector_or_skip()
        self.assertIn("Raccourcis", data["titles"])
        self.assertIsNotNone(data["html"], "section Raccourcis absente du rendu")
        combos = _parse_shortcuts(data["html"])
        self.assertGreaterEqual(len(combos), 4, f"liste de raccourcis trop maigre : {combos}")

    def test_every_advertised_shortcut_is_handled_by_keyboard_js(self) -> None:
        data = self._inspector_or_skip()
        combos = _parse_shortcuts(data["html"])
        res = run_module_test(
            _KEYBOARD_JS,
            stubs=_KEYBOARD_STUBS,
            extra=_KEYBOARD_EXTRA,
            driver=_keyboard_driver(combos),
        )
        self.assertEqual(res["handlerCount"], 1, "initKeyboard doit poser un handler keydown")
        dead = [r["label"] for r in res["results"] if not r["prevented"] or r["effects"] == 0]
        self.assertEqual(
            dead,
            [],
            "raccourcis annonces sur l'Accueil mais sans effet dans core/keyboard.js : "
            f"{dead} (detail : {res['results']})",
        )

    def test_palette_settings_and_help_are_among_them(self) -> None:
        # Les 3 raccourcis que la spec 05 §3 veut a portee de main.
        data = self._inspector_or_skip()
        labels = {c["label"] for c in _parse_shortcuts(data["html"])}
        for expected in ("ctrl+K", "ctrl+,", "?"):
            self.assertIn(expected, labels, f"raccourci {expected} non annonce ({sorted(labels)})")


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_env_bar_height_32(self) -> None:
        self.assertIn(".accueil-env-bar", self.css)
        self.assertIn("height: 32px", self.css)

    def test_env_pill_classes(self) -> None:
        self.assertIn(".accueil-env-pill", self.css)
        self.assertIn(".accueil-env-pill.is-ok", self.css)
        self.assertIn(".accueil-env-pill.is-off", self.css)

    def test_scan_progress_classes(self) -> None:
        self.assertIn(".accueil-cta-scan--running", self.css)
        self.assertIn(".accueil-cta-scan-bar", self.css)
        self.assertIn(".accueil-cta-scan-fill", self.css)

    def test_inspector_classes(self) -> None:
        self.assertIn(".accueil-inspector-dl", self.css)
        self.assertIn(".accueil-inspector-shortcuts", self.css)
        self.assertIn(".accueil-inspector-list", self.css)


if __name__ == "__main__":
    unittest.main()
