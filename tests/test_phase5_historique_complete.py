"""Tests Phase 5 : Historique completed (spec 09-historique.md).

Couvre les 12 deliverables : onglets detailles, page standalone /run/:id,
undo-apply cable, delete-run cable, scroll infini batch 30, filtres avances
(Undone/Undo/Custom/recherche film), banner retention, CSS.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._jsexec import require_node, run_module_test

_ROOT = Path(__file__).resolve().parents[1]
_HISTORIQUE_JS = _ROOT / "web" / "dashboard" / "views" / "historique.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FilmsTabDetailTests(unittest.TestCase):
    """Onglet Films : liste detaillee + lien /film/:id (spec 09 §3)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_calls_get_history_stats(self) -> None:
        self.assertIn("run/get_history_stats", self.js)

    def test_films_list_render(self) -> None:
        self.assertIn("_renderFilmsList", self.js)

    def test_films_status_labels(self) -> None:
        # 4 statuts : Approuve / Rejete / Doublon / Suppression.
        self.assertIn("Approuvé", self.js)
        self.assertIn("Rejeté", self.js)
        self.assertIn("Doublon", self.js)
        self.assertIn("Suppression", self.js)

    def test_films_link_to_film_detail(self) -> None:
        self.assertIn("#/film/", self.js)


class ApplyTabDetailTests(unittest.TestCase):
    """Onglet Apply : liste operations + compteurs par type."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_apply_ops_render(self) -> None:
        self.assertIn("_renderApplyOps", self.js)

    def test_apply_counters(self) -> None:
        self.assertIn("historique-apply-counter", self.js)


# --- Libelles d'operations : teste au RUNTIME -----------------------------
#
# Historique : ce test comparait 4 chaines litterales ("Renommé", "Déplacé"...)
# au source de historique.js. Il est passe au ROUGE quand le fix d'audit
# 2026-05-25 (v1.5.3, Vague F) a reformule les libelles pour ne plus laisser
# croire que le fichier video est renomme ("Dossier renommé : ... (fichier
# conservé)"). Le test punissait donc une CORRECTION, et n'aurait rien detecte
# si la logique de _opLabel s'etait inversee tout en gardant les mots.
#
# Il est reecrit ici en test de COMPORTEMENT : on execute le vrai _opLabel sous
# Node (harnais tests/_jsexec.py) et on verifie l'invariant produit, pas la
# forme du source. L'invariant central vient de la regle projet "ne jamais
# renommer le fichier video" : seul le DOSSIER est renomme, et un deplacement
# de fichier a nom identique doit le dire explicitement.

_OPLABEL_STUBS = """
const escapeHtml = (s) => String(s);
const apiPost = async () => ({});
const getNavSignal = () => null;
const navigateTo = () => {};
const rightPanel = { setSections: () => {}, setTitle: () => {} };
const dangerConfirmModal = () => {};
const showModal = () => {};
const closeModal = () => {};
const showToast = () => {};
const buildEmptyState = () => "";
"""

_OPLABEL_EXTRA = "export { _opLabel as __opLabel };\n"

_OPLABEL_DRIVER = """
const cases = {
  rename: { op_type: "rename", src_path: "/m/Ancien Dossier", dst_path: "/m/Nouveau Dossier (2011)" },
  move_dir: { op_type: "move_dir", src_path: "/m/A", dst_path: "/m/B (2011)" },
  move_same: { op_type: "move", src_path: "/a/film.mkv", dst_path: "/b/film.mkv" },
  move_renamed: { op_type: "move", src_path: "/a/s01e01.mkv", dst_path: "/b/S01E02.mkv" },
  quarantine: { op_type: "quarantine", src_path: "/m/douteux.mkv", dst_path: "" },
  delete_mark: { op_type: "delete_mark", src_path: "/m/apvirer.mkv", dst_path: "" },
  unknown: { op_type: "hardlink", src_path: "/m/x.mkv", dst_path: "/m/y.mkv" },
};
const out = {};
for (const [name, op] of Object.entries(cases)) out[name] = M.__opLabel(op);
__emit(out);
"""


class ApplyOpLabelRuntimeTests(unittest.TestCase):
    """_opLabel : un libelle par type d'operation, execute pour de vrai."""

    _labels: dict | None = None

    def _labels_or_skip(self) -> dict:
        require_node(self)
        if ApplyOpLabelRuntimeTests._labels is None:
            ApplyOpLabelRuntimeTests._labels = run_module_test(
                _HISTORIQUE_JS,
                stubs=_OPLABEL_STUBS,
                extra=_OPLABEL_EXTRA,
                driver=_OPLABEL_DRIVER,
            )
        return ApplyOpLabelRuntimeTests._labels

    def test_each_op_type_gets_a_distinct_non_empty_label(self) -> None:
        labels = self._labels_or_skip()
        # Les 4 familles de la spec + le fallback doivent produire un libelle
        # non vide, avec une icone, et rester distinguables entre elles.
        seen: dict[str, str] = {}
        for name in ("rename", "move_same", "quarantine", "delete_mark", "unknown"):
            lbl = labels[name]
            self.assertTrue(lbl["text"].strip(), f"{name} : libelle vide")
            self.assertTrue(lbl["icon"].strip(), f"{name} : icone vide")
            self.assertNotIn(lbl["text"], seen, f"{name} : libelle identique a {seen.get(lbl['text'])}")
            seen[lbl["text"]] = name

    def test_rename_says_folder_and_never_claims_the_video_was_renamed(self) -> None:
        # Invariant produit (fix Vague F + regle projet) : apply_core ne renomme
        # QUE le dossier parent. Le libelle doit donc nommer le dossier et
        # rassurer sur le fichier ; il ne doit pas parler de fichier renomme.
        labels = self._labels_or_skip()
        for name in ("rename", "move_dir"):
            text = labels[name]["text"].lower()
            self.assertIn("dossier", text, f"{name} : le libelle doit dire que c'est le DOSSIER")
            self.assertIn("conserv", text, f"{name} : le libelle doit dire que le fichier est conserve")
            self.assertNotIn("fichier renomm", text, f"{name} : ne doit pas annoncer un renommage de fichier")
            self.assertNotIn("vidéo renomm", text, f"{name} : ne doit pas annoncer un renommage de video")

    def test_move_distinguishes_same_name_from_real_rename(self) -> None:
        # Un move a basename identique = deplacement pur : le libelle doit le
        # dire. Un move a basename different (episodes TV) doit au contraire
        # afficher les DEUX noms pour que l'operateur voie le renommage.
        labels = self._labels_or_skip()
        same = labels["move_same"]["text"]
        self.assertIn("conserv", same.lower(), "move a nom identique : doit dire 'nom conservé'")
        self.assertIn("film.mkv", same)

        renamed = labels["move_renamed"]["text"]
        self.assertIn("s01e01.mkv", renamed.lower())
        self.assertIn("s01e02.mkv", renamed.lower())
        self.assertNotEqual(same, renamed, "les deux cas de move doivent etre distingues")

    def test_quarantine_and_delete_mark_name_their_destination(self) -> None:
        labels = self._labels_or_skip()
        self.assertIn("_review", labels["quarantine"]["text"])
        self.assertIn("douteux.mkv", labels["quarantine"]["text"])
        self.assertIn("suppression", labels["delete_mark"]["text"].lower())
        self.assertIn("apvirer.mkv", labels["delete_mark"]["text"])

    def test_unknown_op_type_is_translated_not_raw_english(self) -> None:
        # Fallback FR (iter11) : jamais l'op_type brut seul en tete de libelle.
        labels = self._labels_or_skip()
        text = labels["unknown"]["text"]
        self.assertTrue(text[0].isupper(), f"fallback non capitalise : {text}")
        self.assertIn("x.mkv", text)
        self.assertIn("y.mkv", text)


class DoublonsTabDetailTests(unittest.TestCase):
    """Onglet Doublons : groupes decides + skipped."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_doublons_list_render(self) -> None:
        self.assertIn("_renderDoublonsList", self.js)

    def test_doublons_decided_skipped(self) -> None:
        self.assertIn("Décidés", self.js)
        self.assertIn("Ignorés", self.js)


class LogTabDetailTests(unittest.TestCase):
    """Onglet Log : viewer monospace + bouton recharger."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_log_viewer_render(self) -> None:
        self.assertIn("_renderLogViewer", self.js)
        self.assertIn("historique-log-viewer", self.js)

    def test_log_reload_action(self) -> None:
        self.assertIn('data-historique-action="reload-log"', self.js)


class StandalonePageTests(unittest.TestCase):
    """Page standalone /run/:id (Phase 5)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")
        cls.app = _APP_JS.read_text(encoding="utf-8")

    def test_exports_init_run_detail_page(self) -> None:
        self.assertIn("export async function initRunDetailPage(", self.js)

    def test_exports_unmount_run_detail_page(self) -> None:
        self.assertIn("export function unmountRunDetailPage(", self.js)

    def test_route_run_id_registered(self) -> None:
        self.assertIn('registerRoute("/run/:id"', self.app)
        line_start = self.app.find('registerRoute("/run/:id"')
        line_end = self.app.find("\n", line_start)
        snippet = self.app[line_start:line_end]
        self.assertIn("initRunDetailPage", snippet)

    def test_back_button_to_historique(self) -> None:
        self.assertIn("data-historique-back", self.js)
        self.assertIn('"/historique"', self.js)


class UndoApplyWiredTests(unittest.TestCase):
    """Action undo-apply : appel reel a undo_last_apply."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_undo_calls_backend(self) -> None:
        # PR #84 : undo_last_apply migre vers la facade run (run/undo_last_apply).
        self.assertIn('apiPost("run/undo_last_apply"', self.js)

    def test_undo_uses_danger_modal(self) -> None:
        # Verifie que undo-apply est dans un onConfirm callback de dangerConfirmModal.
        self.assertIn("dangerConfirmModal", self.js)
        self.assertIn("_doUndoApply", self.js)

    def test_undo_success_toast(self) -> None:
        self.assertIn("Apply annulé", self.js)


class DeleteRunWiredTests(unittest.TestCase):
    """Action delete-run : appel reel a run/delete_run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_delete_calls_backend(self) -> None:
        self.assertIn('apiPost("run/delete_run"', self.js)

    def test_delete_uses_danger_modal(self) -> None:
        self.assertIn("_doDeleteRun", self.js)

    def test_delete_removes_from_local_runs(self) -> None:
        # splice du tableau local sans refetch (perf : pas de fetch reseau).
        self.assertIn("_runs = _runs.filter", self.js)


class InfiniteScrollTests(unittest.TestCase):
    """Scroll infini batch 30 + IntersectionObserver."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_batch_size_constant(self) -> None:
        self.assertIn("BATCH_SIZE = 30", self.js)

    def test_intersection_observer_used(self) -> None:
        self.assertIn("IntersectionObserver", self.js)

    def test_visible_count_increments(self) -> None:
        self.assertIn("_visibleCount += BATCH_SIZE", self.js)

    def test_loading_more_indicator(self) -> None:
        self.assertIn("historique-loading-more", self.js)


class AdvancedFiltersTests(unittest.TestCase):
    """Filtres supplementaires : Custom date, recherche par film.

    Revue post-merge 2026-08-03 — les deux tests « Undone » / « Undo » qui
    vivaient ici etaient des FAUX VERTS : ils verifiaient la presence de la
    chaine `value="undone"` dans le TEXTE SOURCE du JS, jamais son effet. Les
    deux options etaient mortes par construction (un undo n'insere aucune ligne
    dans la table `runs`, et le payload de run/get_dashboard ne porte ni
    `undone`, ni `is_undo`, ni `type`), donc les filtres repondaient toujours
    « Aucun run ne correspond aux filtres actuels ». Les options ont ete
    retirees ; on verifie desormais qu'elles ne reviennent pas, et le
    comportement des filtres VIVANTS est teste au runtime dans
    tests/test_revue_20260803_historique_statuts.py.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_pas_doption_de_filtre_morte(self) -> None:
        self.assertNotIn('value="undone"', self.js)
        self.assertNotIn('value="undo"', self.js)

    def test_custom_period_picker(self) -> None:
        self.assertIn('value="custom"', self.js)
        self.assertIn("data-historique-custom-from", self.js)
        self.assertIn("data-historique-custom-to", self.js)

    def test_search_matches_film_name(self) -> None:
        # _matchesSearchQuery doit explorer _filmsCacheByRun (recherche par titre).
        self.assertIn("_filmsCacheByRun", self.js)
        self.assertIn("nom de film", self.js)


class RetentionBannerTests(unittest.TestCase):
    """Banner retention 90j auto en haut de la vue (spec §5)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_renders_retention_banner(self) -> None:
        self.assertIn("_renderRetentionBanner", self.js)

    def test_banner_mentions_90_days(self) -> None:
        # rétention par defaut 90j (settable via history_retention_days).
        self.assertIn("rétention", self.js)
        self.assertIn("history_retention_days", self.js)


class CssCompleteTests(unittest.TestCase):
    """CSS Phase 5 : nouvelles classes obligatoires + balance accolades."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_standalone_page_class(self) -> None:
        self.assertIn(".historique-run-detail-page", self.css)

    def test_films_list_class(self) -> None:
        self.assertIn(".historique-films-list", self.css)

    def test_apply_ops_class(self) -> None:
        self.assertIn(".historique-apply-ops", self.css)

    def test_doublons_list_class(self) -> None:
        self.assertIn(".historique-doublons-list", self.css)

    def test_log_viewer_class(self) -> None:
        self.assertIn(".historique-log-viewer", self.css)

    def test_retention_banner_class(self) -> None:
        self.assertIn(".historique-retention-banner", self.css)

    def test_brace_balance(self) -> None:
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"CSS desequilibre : open={opens} close={closes}")


if __name__ == "__main__":
    unittest.main()
