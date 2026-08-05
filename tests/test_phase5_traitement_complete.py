"""Tests Phase 5 : vue Traitement complete (spec 08-traitement.md).

Verifie l'implementation native du workflow 5 etapes :
  - Header run actif avec statut/ETA/boutons (pause/resume/save/cancel)
  - Etape 1 Analyse avec drawer scan options + progress + live log
  - Etape 2 Verification avec table dense + filtres
  - Etape 3 Validation avec table dense + bulk approve
  - Etape 4 Doublons inline (import initDoublons)
  - Etape 5 Apply avec dangerConfirmModal countdown 3s
  - CSS classes traitement-* dans components.css
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._jsexec import require_node, run_module_test

_ROOT = Path(__file__).resolve().parents[1]
_TRAITEMENT_JS = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class HeaderRunTests(unittest.TestCase):
    """Spec §2 : header run actif (run_id, statut, ETA, boutons globaux)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_header_run_renders_status(self) -> None:
        self.assertIn("_renderHeaderRun", self.js)
        self.assertIn("STATUS_COLORS", self.js)

    def test_header_run_includes_eta_field(self) -> None:
        self.assertIn("traitement-run-eta", self.js)
        # ETA peut etre derivee depuis eta_s ou calculee depuis progress
        self.assertIn("eta_s", self.js)

    def test_header_run_has_pause_button(self) -> None:
        self.assertIn('data-traitement-action="pause"', self.js)

    def test_header_run_has_resume_button(self) -> None:
        self.assertIn('data-traitement-action="resume"', self.js)

    def test_header_run_has_save_button(self) -> None:
        self.assertIn('data-traitement-action="save"', self.js)

    def test_header_run_has_cancel_button(self) -> None:
        self.assertIn('data-traitement-action="cancel"', self.js)

    def test_cancel_uses_danger_confirm_modal(self) -> None:
        # Le cancel doit ouvrir une dangerConfirmModal
        self.assertIn("dangerConfirmModal", self.js)
        # Recherche dans le contexte du handler cancel : titre + countdown
        self.assertIn("Annuler le run", self.js)

    def test_polling_5s_during_running(self) -> None:
        # Spec §1 demande un poll get_dashboard / run/get_status toutes les 5s pendant RUNNING
        self.assertIn("POLL_INTERVAL_RUNNING", self.js)
        self.assertIn("5000", self.js)

    def test_uses_run_get_status(self) -> None:
        self.assertIn("run/get_status", self.js)


class AnalyseStepTests(unittest.TestCase):
    """Spec §3.1 : etape Analyse avec drawer scan options + progress + live log."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_scan_drawer_renders(self) -> None:
        self.assertIn("traitement-scan-drawer", self.js)

    def test_scan_options_checkboxes(self) -> None:
        # 4 options : perceptual / subtitles / omdb / nfo
        for opt in ("perceptual", "subtitles", "omdb", "nfo"):
            self.assertIn(f'data-scan-opt="{opt}"', self.js, f"option {opt} manquante")

    def test_scan_parallelism_slider(self) -> None:
        self.assertIn('data-scan-opt="parallelism"', self.js)
        self.assertIn('type="range"', self.js)

    def test_scan_start_calls_start_plan(self) -> None:
        self.assertIn("start_plan", self.js)
        self.assertIn('data-traitement-action="start-scan"', self.js)

    def test_scan_progress_bar(self) -> None:
        self.assertIn("traitement-scan-progress-bar", self.js)
        self.assertIn("traitement-scan-progress-fill", self.js)

    def test_scan_live_log_polling(self) -> None:
        # Spec §3.1 : polling 2s pendant scan
        self.assertIn("POLL_INTERVAL_ANALYSE", self.js)
        self.assertIn("2000", self.js)
        self.assertIn("traitement-scan-live-log", self.js)


class VerificationStepTests(unittest.TestCase):
    """Spec §3.2 : etape Verification (table problematiques + filtres rapides)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_verif_table_renders(self) -> None:
        self.assertIn("traitement-verif-table", self.js)

    def test_verif_filters_present(self) -> None:
        # Filtres : all / subs / dups / nfo
        for f in ("all", "subs", "dups", "nfo"):
            self.assertIn(f'data-traitement-verif-filter="{f}"', self.js)

    def test_verif_actions_rescan_rename_ignore(self) -> None:
        for action in ("rescan", "rename", "ignore"):
            self.assertIn(f'data-traitement-verif-action="{action}"', self.js)


class ValidationStepTests(unittest.TestCase):
    """Spec §3.3 : etape Validation (table dense + bulk approve + presets)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_validation_table_renders(self) -> None:
        self.assertIn("traitement-validation-table", self.js)

    def test_bulk_approve_sure_button(self) -> None:
        self.assertIn('data-traitement-action="bulk-approve-sure"', self.js)
        # confidence >= 90 (spec dit 85, on tolere 90 plus strict)
        self.assertIn("confidence", self.js)

    def test_presets_no_alert_platinum_gold(self) -> None:
        self.assertIn('data-traitement-action="preset-no-alert"', self.js)
        self.assertIn('data-traitement-action="preset-platinum-gold"', self.js)

    def test_inline_year_edit(self) -> None:
        self.assertIn("traitement-validation-year-input", self.js)
        self.assertIn('type="number"', self.js)

    def test_bulk_approve_offers_an_undo(self) -> None:
        # Historique : ce test exigeait "duration: 5000" + la variable globale
        # "_traitementLastBulkSnapshot". Les deux ancrages sont morts :
        #  - le fix TOAST-1 (2026-05-30) a porte le toast a 10s pour laisser le
        #    temps de cliquer "Annuler" (UX type Gmail Undo Send) ;
        #  - le fix VN-C.2 a remplace la globale par un snapshot de closure
        #    couvrant TOUTES les rows du plan, pas seulement les visibles.
        # Pire, "duration: 5000" continuait de matcher... le toast du dry-run,
        # a l'autre bout du fichier : un vert qui ne prouvait rien.
        # Le comportement reel (toast + undo qui restaure les decisions) est
        # verifie par execution dans BulkApproveUndoRuntimeTests ci-dessous ;
        # on ne garde ici que l'ancrage structurel de l'action de masse.
        self.assertIn("showToast", self.js)
        self.assertIn("_applyBulkApprove", self.js)


# --- Approbation en masse + undo : verifies au RUNTIME --------------------
#
# On execute le vrai _applyBulkApprove sous Node (harnais tests/_jsexec.py) :
# showToast et apiPost sont espionnes, le state de decisions est reel. On
# verifie la sequence complete (mutation -> persistance -> toast -> undo), y
# compris le rollback sur echec API et la preservation des decisions prises
# PENDANT l'await (fix race condition 2026-06-05).

_BULK_STUBS = """
const escapeHtml = (s) => String(s == null ? "" : s);
globalThis.__spy = { toasts: [], api: [] };
globalThis.__apiOk = true;
const apiPost = async (ep, params) => {
  globalThis.__spy.api.push({ ep, params });
  if (!globalThis.__apiOk && ep === "run/save_validation") return { data: { ok: false } };
  return { data: { ok: true } };
};
const fetchConfidenceThresholds = async () => ({});
const getConfidenceThresholdsSync = () => ({ CONF_HIGH: 85, CONF_MID: 60 });
const navigateTo = () => {};
const dangerConfirmModal = () => {};
const showModal = () => {};
const closeModal = () => {};
const showToast = (t) => { globalThis.__spy.toasts.push(t); };
const formatRelative = () => "";
const formatDuration = () => "";
const initDoublons = () => {};
const unmountDoublons = () => {};
const renderFilmDetail = () => {};
"""

# `_loadRunInfo` et `_renderInPlace` sont neutralises : ce sont des dependances
# de rafraichissement (reseau + DOM), pas la fonction sous test. Le corps de
# _applyBulkApprove, lui, tourne tel quel.
_BULK_EXTRA = """
export function __setup(rowIds) {
  _loadRunInfo = async () => {};
  _renderInPlace = () => {};
  _runInfo = { runId: "RUN-TEST" };
  _activeContainer = { querySelectorAll: () => [], querySelector: () => null, innerHTML: "" };
  _validationPlan = { rows: rowIds.map((id) => ({ row_id: id, decision: "PENDING" })) };
  _decisionsState = new Map(rowIds.map((id) => [id, { ok: false, year: null, decided_at: 0 }]));
}
export function __decisions() {
  return Object.fromEntries([..._decisionsState.entries()].map(([k, v]) => [k, !!v.ok]));
}
export function __planDecisions() {
  return Object.fromEntries(_validationPlan.rows.map((r) => [String(r.row_id), r.decision]));
}
export { _applyBulkApprove as __applyBulkApprove };
"""

_BULK_DRIVER = """
const ids = ["r1", "r2", "r3"];

// --- Scenario nominal : approbation + undo -----------------------------
globalThis.__spy = { toasts: [], api: [] };
globalThis.__apiOk = true;
M.__setup(ids);
await M.__applyBulkApprove(new Set(ids), ids.length);
const afterApprove = M.__decisions();
const planAfterApprove = M.__planDecisions();
const toast = globalThis.__spy.toasts[globalThis.__spy.toasts.length - 1] || null;
const savedBeforeToast = globalThis.__spy.api.filter((c) => c.ep === "run/save_validation").length;
let afterUndo = null;
if (toast && toast.action && typeof toast.action.onClick === "function") {
  await toast.action.onClick();
  afterUndo = M.__decisions();
}

// --- Scenario echec API : rollback, pas de faux succes ------------------
globalThis.__spy = { toasts: [], api: [] };
globalThis.__apiOk = false;
M.__setup(ids);
await M.__applyBulkApprove(new Set(ids), ids.length);
const afterFailure = M.__decisions();
const failToasts = globalThis.__spy.toasts.map((t) => t.type);

__emit({
  afterApprove, planAfterApprove, afterUndo, afterFailure, failToasts, savedBeforeToast,
  toast: toast && {
    type: toast.type, text: String(toast.text || ""), duration: toast.duration,
    actionLabel: toast.action ? String(toast.action.label || "") : null,
  },
});
"""


class BulkApproveUndoRuntimeTests(unittest.TestCase):
    """Spec §3.3 : approuver en masse doit rester annulable."""

    _res: dict | None = None

    def _run_or_skip(self) -> dict:
        require_node(self)
        if BulkApproveUndoRuntimeTests._res is None:
            BulkApproveUndoRuntimeTests._res = run_module_test(
                _TRAITEMENT_JS,
                stubs=_BULK_STUBS,
                extra=_BULK_EXTRA,
                driver=_BULK_DRIVER,
            )
        return BulkApproveUndoRuntimeTests._res

    def test_bulk_approve_marks_every_target_and_persists_it(self) -> None:
        res = self._run_or_skip()
        self.assertEqual(res["afterApprove"], {"r1": True, "r2": True, "r3": True})
        self.assertEqual(
            res["planAfterApprove"],
            {"r1": "APPROVED", "r2": "APPROVED", "r3": "APPROVED"},
            "le plan local doit refleter l'approbation (sinon fausse modale 'decisions non enregistrees')",
        )
        self.assertGreaterEqual(res["savedBeforeToast"], 1, "run/save_validation doit etre appele")

    def test_success_toast_stays_long_enough_to_click_undo(self) -> None:
        # Le toast doit annoncer le succes ET rester assez longtemps pour que
        # "Annuler" soit cliquable. Borne par le BAS (>= 5s) : le passage a 10s
        # (fix TOAST-1) est un renforcement, pas une regression.
        res = self._run_or_skip()
        toast = res["toast"]
        self.assertIsNotNone(toast, "aucun toast apres approbation en masse")
        self.assertEqual(toast["type"], "success")
        self.assertIn("3", toast["text"], "le toast doit annoncer le nombre de films approuves")
        self.assertIsNotNone(toast["duration"], "toast persistant interdit (accumulation, cf TOAST-1)")
        self.assertGreaterEqual(toast["duration"], 5000, "trop court pour cliquer Annuler")
        self.assertEqual(toast["actionLabel"], "Annuler")

    def test_undo_restores_the_previous_decisions(self) -> None:
        # Le coeur du contrat : c'est l'undo qui doit VRAIMENT rendre la main,
        # pas la simple presence d'un bouton.
        res = self._run_or_skip()
        self.assertIsNotNone(res["afterUndo"], "le toast n'expose pas d'action Annuler cliquable")
        self.assertEqual(
            res["afterUndo"],
            {"r1": False, "r2": False, "r3": False},
            "apres Annuler, les decisions doivent revenir a leur valeur d'avant le bulk",
        )

    def test_api_failure_rolls_back_and_does_not_claim_success(self) -> None:
        res = self._run_or_skip()
        self.assertEqual(
            res["afterFailure"],
            {"r1": False, "r2": False, "r3": False},
            "echec de save_validation : le state doit etre rollback",
        )
        self.assertIn("error", res["failToasts"], "echec silencieux interdit")
        self.assertNotIn("success", res["failToasts"], "pas de toast de succes sur echec API")


_BULK_HORLOGE_DRIVER = """
// L'HORLOGE AVANCE — c'est tout ce qui change par rapport au pilote nominal.
//
// `_applyBulkApprove` prenait un `snapshot_ts = Date.now()` AVANT d'ecrire, puis
// ses gardes de rollback/undo sautaient toute row dont `decided_at > snapshot_ts`
// pour « preserver les decisions utilisateur posterieures ». Mais le bulk ecrit
// lui aussi APRES ce snapshot : des que l'horloge avait avance d'une seule
// milliseconde entre les deux, la garde prenait les ecritures DU BULK pour des
// decisions utilisateur, et « Annuler » ne faisait plus RIEN, en silence.
//
// Sur un poste rapide tout tient dans la meme milliseconde et le defaut est
// invisible. Sur un runner de CI, non : deux echecs a la signature identique le
// 2026-08-05 sur main, verts en local. Forcer l'horloge rend le defaut
// DETERMINISTE au lieu d'attendre qu'il retombe.
const _vraiNow = Date.now;
let _tic = _vraiNow.call(Date);
Date.now = () => (_tic += 1);

const ids = ["r1", "r2", "r3"];
globalThis.__spy = { toasts: [], api: [] };
globalThis.__apiOk = true;
M.__setup(ids);
await M.__applyBulkApprove(new Set(ids), ids.length);
const afterApprove = M.__decisions();

const toast = globalThis.__spy.toasts[globalThis.__spy.toasts.length - 1] || null;
let afterUndo = null;
if (toast && toast.action && typeof toast.action.onClick === "function") {
  await toast.action.onClick();
  afterUndo = M.__decisions();
}

// Meme scenario, mais l'utilisateur RETOUCHE r2 apres le bulk : cette
// decision-la doit survivre a l'annulation.
globalThis.__spy = { toasts: [], api: [] };
M.__setup(ids);
await M.__applyBulkApprove(new Set(ids), ids.length);
M.__retoucher("r2", true);
const toast2 = globalThis.__spy.toasts[globalThis.__spy.toasts.length - 1] || null;
let afterUndoAvecRetouche = null;
if (toast2 && toast2.action && typeof toast2.action.onClick === "function") {
  await toast2.action.onClick();
  afterUndoAvecRetouche = M.__decisions();
}

// --- Horloge FIGEE : la retouche tombe dans la meme milliseconde ---------
// C'est le cas que `decided_at` ne pouvait pas distinguer. Avec un horodatage
// pour identite, `current.decided_at === bulkStamps.get(rid)` restait VRAI et
// « Annuler » ecrasait une decision que l'utilisateur venait de prendre.
Date.now = () => 1000;
globalThis.__spy = { toasts: [], api: [] };
globalThis.__apiOk = true;
M.__setup(ids);
await M.__applyBulkApprove(new Set(ids), ids.length);
M.__retoucher("r2", true);
const toast3 = globalThis.__spy.toasts[globalThis.__spy.toasts.length - 1] || null;
let afterUndoHorlogeFigee = null;
if (toast3 && toast3.action && typeof toast3.action.onClick === "function") {
  await toast3.action.onClick();
  afterUndoHorlogeFigee = M.__decisions();
}

// --- Echec API sous horloge qui AVANCE : le rollback doit aussi tenir -----
// Les deux gardes partagent le meme critere ; celle du rollback n'etait
// exercee que sous horloge normale, donc elle pouvait passer par chance.
Date.now = () => (_tic += 1);
globalThis.__spy = { toasts: [], api: [] };
globalThis.__apiOk = false;
M.__setup(ids);
await M.__applyBulkApprove(new Set(ids), ids.length);
const afterFailureHorloge = M.__decisions();
const failToastsHorloge = globalThis.__spy.toasts.map((t) => t.type);

Date.now = _vraiNow;
__emit({
  afterApprove, afterUndo, afterUndoAvecRetouche,
  afterUndoHorlogeFigee, afterFailureHorloge, failToastsHorloge,
});
"""

_BULK_HORLOGE_EXTRA = (
    _BULK_EXTRA
    + """
export function __retoucher(rowId, ok) {
  _setDecisionOk(rowId, ok);
}
"""
)


class BulkUndoHorlogeQuiAvanceTests(unittest.TestCase):
    """L'annulation ne doit pas dependre de la RESOLUTION D'HORLOGE.

    Ce harnais force `Date.now()` a avancer d'une milliseconde a chaque appel,
    ce qui reproduit de facon DETERMINISTE l'echec intermittent observe en CI :
    deux runs de main le 2026-08-05, meme test, meme assertion, memes valeurs
    ({r1: true, r2: true, r3: true} au lieu de false), alors que le meme test
    passait en local.
    """

    _res: dict | None = None

    def _run_or_skip(self) -> dict:
        require_node(self)
        if BulkUndoHorlogeQuiAvanceTests._res is None:
            BulkUndoHorlogeQuiAvanceTests._res = run_module_test(
                _TRAITEMENT_JS,
                stubs=_BULK_STUBS,
                extra=_BULK_HORLOGE_EXTRA,
                driver=_BULK_HORLOGE_DRIVER,
            )
        return BulkUndoHorlogeQuiAvanceTests._res

    def test_l_annulation_marche_meme_quand_l_horloge_a_avance(self) -> None:
        res = self._run_or_skip()
        self.assertEqual(res["afterApprove"], {"r1": True, "r2": True, "r3": True})
        self.assertEqual(
            res["afterUndo"],
            {"r1": False, "r2": False, "r3": False},
            "« Annuler » n'a rien fait : la garde a pris les ecritures DU BULK "
            "pour des decisions utilisateur posterieures",
        )

    def test_une_retouche_utilisateur_SURVIT_a_l_annulation(self) -> None:
        """La garde doit rester protectrice, pas seulement passante.

        Corriger le defaut en supprimant la garde ferait passer le test
        ci-dessus tout en ECRASANT une decision que l'utilisateur vient de
        prendre. C'est ce test-ci qui l'interdit.
        """
        res = self._run_or_skip()
        self.assertEqual(
            res["afterUndoAvecRetouche"],
            {"r1": False, "r2": True, "r3": False},
            "r2 a ete retouchee APRES le bulk : l'annulation doit la respecter",
        )

    def test_une_retouche_DANS_LA_MEME_MILLISECONDE_survit(self) -> None:
        """Le cas qu'un horodatage ne peut pas distinguer.

        Premiere version de ce correctif : l'identite d'ecriture etait
        `decided_at`, un HORODATAGE. Une retouche tombant dans la meme
        milliseconde que le bulk gardait donc l'egalite vraie, et « Annuler »
        ecrasait une decision que l'utilisateur venait de prendre. Fenetre plus
        etroite que le defaut d'origine, meme famille.

        L'identite est desormais un compteur de REVISION monotone : deux
        ecritures distinctes ont toujours des numeros distincts, quelle que
        soit l'horloge.
        """
        res = self._run_or_skip()
        self.assertEqual(
            res["afterUndoHorlogeFigee"],
            {"r1": False, "r2": True, "r3": False},
            "horloge figee : la retouche de r2 a ete ECRASEE par l'annulation",
        )

    def test_le_rollback_d_echec_API_tient_aussi_horloge_qui_avance(self) -> None:
        """La seconde garde partage le meme critere et doit etre exercee AUSSI.

        Elle ne l'etait que sous horloge normale : elle pouvait donc passer par
        chance. Un rollback qui ne rollback pas laisse l'ecran afficher des
        approbations que le serveur n'a jamais enregistrees.
        """
        res = self._run_or_skip()
        self.assertEqual(
            res["afterFailureHorloge"],
            {"r1": False, "r2": False, "r3": False},
            "echec de save_validation : l'etat doit revenir en arriere",
        )
        self.assertIn("error", res["failToastsHorloge"], "echec silencieux interdit")
        self.assertNotIn("success", res["failToastsHorloge"], "pas de toast de succes sur echec")


class DoublonsStepTests(unittest.TestCase):
    """Spec §3.4 : etape Doublons inline (composant initDoublons)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_imports_doublons_view(self) -> None:
        self.assertIn('from "./doublons.js"', self.js)
        self.assertIn("initDoublons", self.js)
        self.assertIn("unmountDoublons", self.js)

    def test_doublons_mount_point(self) -> None:
        self.assertIn("traitement-doublons-mount", self.js)


class ApplyStepTests(unittest.TestCase):
    """Spec §3.5 : etape Apply (resume + options + dangerConfirmModal countdown 3s)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_apply_summary_renders(self) -> None:
        self.assertIn("traitement-apply-summary", self.js)
        self.assertIn("renommage", self.js)
        # Le mot apparait avec accent dans le code FR
        self.assertTrue(
            "deplacement" in self.js.lower() or "déplacement" in self.js.lower(),
            "le resume Apply doit mentionner les deplacements",
        )

    def test_apply_preview_renders(self) -> None:
        self.assertIn("traitement-apply-preview", self.js)

    def test_apply_options_checkboxes(self) -> None:
        for opt in ("dry_run", "export_csv", "sync_jellyfin"):
            self.assertIn(f'data-apply-opt="{opt}"', self.js, f"option apply {opt} manquante")

    def test_apply_real_uses_danger_confirm_with_countdown_3s(self) -> None:
        # Recherche la fonction _handleApplyNow et verifie qu'elle ouvre une
        # dangerConfirmModal avec countdownSeconds: 3
        m = re.search(
            r"_handleApplyNow.*?dangerConfirmModal\s*\(\s*\{(.*?)\}\s*\)",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_handleApplyNow doit ouvrir une dangerConfirmModal")
        block = m.group(1)
        self.assertIn("countdownSeconds: 3", block, "countdownSeconds: 3 absent du modal apply")
        self.assertIn("Confirmer", block)

    def test_apply_calls_api_apply(self) -> None:
        self.assertIn('"apply"', self.js)


class CssTests(unittest.TestCase):
    """Spec §1+§3 : classes CSS nouvelles dans components.css."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_header_run_classes(self) -> None:
        for cls in (
            ".traitement-header-run",
            ".traitement-run-status",
            ".traitement-run-eta",
            ".traitement-header-actions",
        ):
            self.assertIn(cls, self.css, f"CSS class manquante : {cls}")

    def test_scan_drawer_classes(self) -> None:
        for cls in (
            ".traitement-scan-drawer",
            ".traitement-scan-progress",
            ".traitement-scan-progress-bar",
            ".traitement-scan-live-log",
        ):
            self.assertIn(cls, self.css)

    def test_table_classes(self) -> None:
        for cls in (
            ".traitement-verif-table",
            ".traitement-validation-table",
            ".traitement-validation-bulk",
        ):
            self.assertIn(cls, self.css)

    def test_apply_classes(self) -> None:
        for cls in (
            ".traitement-apply-summary",
            ".traitement-apply-preview",
            ".traitement-apply-options",
        ):
            self.assertIn(cls, self.css)

    def test_status_color_variants(self) -> None:
        # Statuts : is-running, is-paused, is-done, is-error
        for variant in ("is-running", "is-paused", "is-done", "is-error"):
            self.assertIn(f".traitement-run-status.{variant}", self.css)

    def test_brace_balance(self) -> None:
        # Suppression des commentaires CSS puis comptage des { }
        stripped = re.sub(r"/\*.*?\*/", "", self.css, flags=re.DOTALL)
        opens = stripped.count("{")
        closes = stripped.count("}")
        self.assertEqual(opens, closes, f"Accolades CSS desequilibrees : {opens} ouvrantes, {closes} fermantes")


class EndpointsConsumedTests(unittest.TestCase):
    """Verifie que la vue appelle bien les endpoints attendus."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_consumes_get_dashboard(self) -> None:
        self.assertIn("get_dashboard", self.js)

    def test_consumes_get_status(self) -> None:
        self.assertIn("run/get_status", self.js)

    def test_consumes_start_plan(self) -> None:
        self.assertIn("start_plan", self.js)

    def test_consumes_cancel_run(self) -> None:
        self.assertIn("run/cancel_run", self.js)

    def test_consumes_pause_run(self) -> None:
        # Peut etre stubbe si endpoint absent backend
        self.assertIn("run/pause_run", self.js)

    def test_consumes_resume_run(self) -> None:
        self.assertIn("run/resume_run", self.js)

    def test_consumes_save_for_later(self) -> None:
        self.assertIn("run/save_for_later", self.js)

    def test_consumes_save_validation(self) -> None:
        self.assertIn("save_validation", self.js)

    def test_consumes_apply(self) -> None:
        # Le mot apply apparait beaucoup, on cible l'apiPost
        # PR #84 : apply migre vers la facade run (run/apply).
        self.assertRegex(self.js, r'apiPost\(\s*"run/apply"')


class LifecycleTests(unittest.TestCase):
    """Verifie le cycle init/unmount et le cleanup du polling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_init_exports(self) -> None:
        self.assertIn("export async function initTraitement(", self.js)

    def test_unmount_exports(self) -> None:
        self.assertIn("export function unmountTraitement(", self.js)

    def _extract_unmount_traitement_body(self) -> str:
        # Fix oracle iter10 (2026-06-09) : l'ancien regex non-greedy
        # r'export function unmountTraitement\(.*?\}\s*$' s'arretait au PREMIER
        # } rencontre (celui du if _hasUnsavedValidationDecisions L2537-2539)
        # avant _stopPolling/unmountDoublons -> faux negatifs.
        # On parse maintenant la balance d'accolades pour extraire le vrai
        # corps complet de la fonction.
        m = re.search(r"export\s+function\s+unmountTraitement\s*\([^)]*\)\s*\{", self.js)
        assert m is not None, "declaration unmountTraitement introuvable"
        start = m.end() - 1  # index du { ouvrant
        depth = 0
        i = start
        n = len(self.js)
        while i < n:
            ch = self.js[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.js[m.start() : i + 1]
            i += 1
        raise AssertionError("Accolade fermante non trouvee pour unmountTraitement")

    def test_unmount_cleans_polling(self) -> None:
        # unmountTraitement doit appeler _stopPolling
        block = self._extract_unmount_traitement_body()
        self.assertIn("_stopPolling", block)

    def test_unmount_cleans_doublons(self) -> None:
        block = self._extract_unmount_traitement_body()
        self.assertIn("unmountDoublons", block)


if __name__ == "__main__":
    unittest.main()
