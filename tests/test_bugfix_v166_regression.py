"""Tests de regression Vague M item M-01 : verifier que les 9 fixes v166
(commit 198a33a, "fix(ui): corrige 9 bugs critiques scan reel (v166)") sont
toujours en place et n'ont pas regresse.

Mapping 1:1 avec les bugs documentes dans le commit message :
- VAL-1 : dashboard kpis exposent validated_count + rejected_count
- VAL-2 : pas de slice(0, 100) ni slice(0, 50) dans la rendu Validation
- VAL-3 : filtres + toggle-reasons present dans traitement.js
- APPLY-1 : _norm_compare NFC casefold dans domain/naming.py
- APPLY-2 : run_state expose apply_running/apply_total/apply_done
- DUP-1 : doublons.js gere une progress bar bulk perceptual
- DUP-2 : run_flow_support.check_duplicates fusionne decisions persistees
- SCAN-1 : VIDEO_EXTS_DEFAULT contient au moins m4v/mov/wmv/flv/ts/webm
- TOAST-1 : toast.js utilise _activeToasts Map + _MAX_STACK + dedup window

Strategie : tests legers qui inspectent le code source / les modules importes
plutot que de mocker un scan complet. Objectif = catcher une regression au
prochain refactor (suppression accidentelle d'un fix), pas re-tester en bout
de chaine la logique deja couverte par les tests dedies (test_apply_progress,
test_apply_skip_identical_rename, test_phase4_doublons_backend).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import cinesort.domain.core as core_mod
import cinesort.domain.naming as naming_mod
import cinesort.ui.api.dashboard_support as dashboard_support

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web" / "dashboard"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class BugfixV166RegressionTests(unittest.TestCase):
    """Verifications statiques : 1 test = 1 bug du commit 198a33a."""

    # ---------------------------------------------------------------- VAL-1
    def test_val1_dashboard_kpis_includes_validated_rejected_counts(self):
        """VAL-1 : compteurs Valides/Rejetes doivent apparaitre dans kpis."""
        src = _read(Path(dashboard_support.__file__))
        # Source de verite : le code initialise et expose les 2 cles dans kpis.
        self.assertIn("validated_count", src, "VAL-1 regression : 'validated_count' absent de dashboard_support.py")
        self.assertIn("rejected_count", src, "VAL-1 regression : 'rejected_count' absent de dashboard_support.py")
        # On verifie que les cles sont bien dans le payload kpis (pas juste un commentaire).
        self.assertRegex(
            src, r'"validated_count"\s*:\s*int\(', "VAL-1 : validated_count doit etre castee en int dans le dict kpis"
        )
        self.assertRegex(
            src, r'"rejected_count"\s*:\s*int\(', "VAL-1 : rejected_count doit etre castee en int dans le dict kpis"
        )

    # ---------------------------------------------------------------- VAL-2
    def test_val2_validation_step_no_slice_100(self):
        """VAL-2 : le rendu Validation ne doit plus avoir de slice(0, 100)."""
        src = _read(WEB_DIR / "views" / "traitement.js")
        # On detecte tout slice(0, 100) ou slice(0,100) actif (hors commentaire).
        # Les commentaires preserves doivent commencer par //.
        active_slices_100 = []
        for i, line in enumerate(src.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if re.search(r"\.slice\(\s*0\s*,\s*100\s*\)", line):
                active_slices_100.append((i, line.strip()))
        self.assertEqual(active_slices_100, [], f"VAL-2 regression : slice(0, 100) reapparu : {active_slices_100}")
        # Aussi : pas de slice(0, 50) sur Verification step.
        active_slices_50 = []
        for i, line in enumerate(src.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if re.search(r"\.slice\(\s*0\s*,\s*50\s*\)", line):
                active_slices_50.append((i, line.strip()))
        self.assertEqual(active_slices_50, [], f"VAL-2 regression : slice(0, 50) reapparu : {active_slices_50}")

    # ---------------------------------------------------------------- VAL-3
    def test_val3_validation_filters_and_toggle_reasons_present(self):
        """VAL-3 : filtre confiance + toggle-reasons doivent etre presents."""
        src = _read(WEB_DIR / "views" / "traitement.js")
        # Filtre par bucket de confiance.
        self.assertIn("_validationFilter", src, "VAL-3 regression : variable _validationFilter absente")
        self.assertIn('data-traitement-validation-filter="all"', src, "VAL-3 regression : chip filter 'all' absent")
        self.assertIn('data-traitement-validation-filter="high"', src, "VAL-3 regression : chip filter 'high' absent")
        self.assertIn('data-traitement-validation-filter="low"', src, "VAL-3 regression : chip filter 'low' absent")
        # Toggle reasons (depliant warning_flags + detected_year_reason).
        self.assertIn(
            'data-traitement-validation-action="toggle-reasons"',
            src,
            "VAL-3 regression : action toggle-reasons absente",
        )
        # aria-sort pour les entetes triables.
        self.assertIn("aria-sort", src, "VAL-3 regression : aria-sort sur les entetes triables absent")

    # --------------------------------------------------------------- APPLY-1
    def test_apply1_norm_compare_uses_nfc_casefold(self):
        """APPLY-1 : _norm_compare doit utiliser NFC + casefold pour equivalence FS."""
        # Lookup direct sur le module (assert que la fonction existe).
        self.assertTrue(hasattr(naming_mod, "_norm_compare"), "APPLY-1 regression : _norm_compare absent de naming.py")
        src = _read(Path(naming_mod.__file__))
        # Doit utiliser unicodedata.normalize("NFC", ...) et casefold().
        self.assertRegex(
            src, r'unicodedata\.normalize\(\s*"NFC"', "APPLY-1 regression : _norm_compare doit normaliser NFC"
        )
        self.assertIn("casefold()", src, "APPLY-1 regression : _norm_compare doit utiliser casefold()")
        # Smoke : equivalences Windows/SMB attendues.
        # NFC/NFD construites via unicodedata pour eviter les soucis d'encodage
        # du source file (un literal NFD/NFC saisi a la main peut etre normalise
        # a la sauvegarde par l'editeur/Git => les 2 formes deviennent egales).
        import unicodedata

        base = "12 Hommes en colère (1957)"  # è = e accent grave precompose
        nfc_form = unicodedata.normalize("NFC", base)
        nfd_form = unicodedata.normalize("NFD", base)
        self.assertNotEqual(nfc_form, nfd_form, "Sanity : NFC et NFD doivent differer au niveau code points")
        self.assertEqual(
            naming_mod._norm_compare(nfd_form.upper()),
            naming_mod._norm_compare(nfc_form.lower()),
            "APPLY-1 : NFD/NFC + case difference doit etre normalisee",
        )

    # --------------------------------------------------------------- APPLY-2
    def test_apply2_run_state_exposes_apply_progress_attrs(self):
        """APPLY-2 : RunState ou status payload doit exposer apply_running/total/done."""
        # On lit cinesort_api.py + _run_state.py pour verifier que la clef
        # 'apply' est ajoutee au status payload (decouple de scan).
        # M-07 (Vague M) : la classe RunState a ete extraite dans
        # cinesort/ui/api/_run_state.py ; les attributs apply_* y vivent
        # desormais. cinesort_api.py reste source de verite pour la cle
        # "apply" du status payload (_get_status_impl).
        api_path = REPO_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py"
        run_state_path = REPO_ROOT / "cinesort" / "ui" / "api" / "_run_state.py"
        self.assertTrue(api_path.exists(), "cinesort_api.py introuvable")
        src_api = _read(api_path)
        # _run_state.py optionnel : si absent, on cherche seulement dans api.
        src_rs = _read(run_state_path) if run_state_path.exists() else ""
        src = src_api + "\n" + src_rs
        # Au moins une des nouvelles cles apply doit etre presente dans payload.
        # Source : commit message "payload _get_status_impl expose cle 'apply'".
        apply_keywords = ["apply_running", "apply_total", "apply_done", '"apply"']
        found = [kw for kw in apply_keywords if kw in src]
        self.assertGreaterEqual(
            len(found),
            1,
            f"APPLY-2 regression : aucune des cles {apply_keywords} dans cinesort_api.py ni _run_state.py",
        )

    # ----------------------------------------------------------------- DUP-1
    def test_dup1_doublons_view_has_bulk_progress(self):
        """DUP-1 : doublons.js doit avoir un indicateur d'avancement bulk."""
        src = _read(WEB_DIR / "views" / "doublons.js")
        # Source de verite : ajout d'une progress bar persistante.
        # On accepte plusieurs marqueurs : classe CSS dediee ou pattern de progress.
        markers = [
            "doublons-bulk-progress",
            "bulk-progress",
            "perceptualProgress",
        ]
        found = [m for m in markers if m in src]
        self.assertGreaterEqual(
            len(found),
            1,
            f"DUP-1 regression : aucun indicateur d'avancement bulk dans doublons.js (cherche : {markers})",
        )

    # ----------------------------------------------------------------- DUP-2
    def test_dup2_run_flow_check_duplicates_merges_persisted_decisions(self):
        """DUP-2 : check_duplicates doit fusionner decisions persistees + incoming."""
        run_flow_path = REPO_ROOT / "cinesort" / "ui" / "api" / "run_flow_support.py"
        self.assertTrue(run_flow_path.exists(), "run_flow_support.py introuvable")
        src = _read(run_flow_path)
        # On cherche le pattern : load decisions depuis validation.json + merge.
        # Markers acceptes (au moins 1) :
        markers = [
            "_load_decisions_from_validation",
            "validation.json",
            "decisions_persisted",
            "persisted_decisions",
        ]
        found = [m for m in markers if m in src]
        self.assertGreaterEqual(
            len(found),
            1,
            f"DUP-2 regression : check_duplicates ne semble plus fusionner les "
            f"decisions persistees (markers cherches : {markers})",
        )

    # ---------------------------------------------------------------- SCAN-1
    def test_scan1_video_exts_default_includes_extended_formats(self):
        """SCAN-1 : VIDEO_EXTS_DEFAULT doit contenir m4v/mov/wmv/flv/ts/webm."""
        exts = core_mod.VIDEO_EXTS_DEFAULT
        # Avant fix : seulement {.mkv, .mp4, .avi, .m2ts} (4 elements).
        # Apres fix : au moins 10 extensions, dont les formats utilisateur courants.
        required = {".m4v", ".mov", ".wmv", ".flv", ".ts", ".webm"}
        missing = required - set(exts)
        self.assertSetEqual(
            missing,
            set(),
            f"SCAN-1 regression : VIDEO_EXTS_DEFAULT a perdu : {missing}. Actuel : {sorted(exts)}",
        )
        # Sanity : taille minimale (10+ apres fix).
        self.assertGreaterEqual(
            len(exts),
            10,
            f"SCAN-1 regression : VIDEO_EXTS_DEFAULT a {len(exts)} elements "
            f"(<10, suspect d'un revert vers les 4 d'origine)",
        )

    # ---------------------------------------------------------------- TOAST-1
    def test_toast1_uses_active_toasts_map_for_dedup(self):
        """TOAST-1 : toast.js doit utiliser _activeToasts Map + max stack + dedup."""
        src = _read(WEB_DIR / "components" / "toast.js")
        # Defense en profondeur : 3 garde-fous documentes dans le commit.
        self.assertIn("_activeToasts", src, "TOAST-1 regression : registre _activeToasts absent")
        self.assertIn("new Map()", src, "TOAST-1 regression : _activeToasts doit etre un Map")
        # Garde-fou (a) : dedup window.
        self.assertIn("_DEDUP_WINDOW_MS", src, "TOAST-1 regression : _DEDUP_WINDOW_MS absent (dedup window)")
        # Garde-fou (b) : max stack.
        self.assertIn("_MAX_STACK", src, "TOAST-1 regression : _MAX_STACK absent (limite empilement)")
        # Garde-fou (c) : safety net persistent.
        self.assertIn("_PERSISTENT_MAX_MS", src, "TOAST-1 regression : _PERSISTENT_MAX_MS absent (safety net)")


class BugfixV166SmokeImportTests(unittest.TestCase):
    """Garde anti-regression supplementaire : les modules touches importent
    proprement (pas de SyntaxError ni d'import cycle reintroduit)."""

    def test_smoke_import_all_touched_python_modules(self):
        # Modules Python touches dans le commit 198a33a.
        import importlib

        modules = [
            "cinesort.app.apply_core",
            "cinesort.app.plan_support",
            "cinesort.domain.core",
            "cinesort.domain.duplicate_support",
            "cinesort.domain.naming",
            "cinesort.domain.scan_helpers",
            "cinesort.ui.api.apply_support",
            "cinesort.ui.api.cinesort_api",
            "cinesort.ui.api.dashboard_support",
            "cinesort.ui.api.run_flow_support",
            "cinesort.ui.api.settings_support",
        ]
        for name in modules:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                self.assertIsNotNone(mod, f"Module {name} importable mais None ?")


if __name__ == "__main__":
    unittest.main(verbosity=2)
