"""F12 — arbitrage produit tranche le 2026-08-03 : `.fr.forced.srt` tout seul.

Un sous-titre FORCE ne traduit que les passages en langue etrangere : ce n'est
PAS une piste FR complete. Avant, un dossier ne contenant que
'Film (2020).fr.forced.srt' rendait languages=['fr'] / missing=[] -> AUCUNE
alerte, l'utilisateur croyait avoir un sous-titre FR.

Option ECARTEE : compter le .forced comme absent (missing_languages=['fr']).
Le fichier EST un sous-titre 'fr', donc 'fr' reste dans `languages` et les
reconciliations de lecture (run_read_support / duplicate_support /
library_support / dashboard_support) suppriment tout `subtitle_missing_<lang>`
dont la langue est presente : l'alerte n'aurait jamais atteint un ecran.
`test_option_ecartee_le_flag_missing_serait_efface_par_la_reconciliation` fige
cette raison — c'est elle qui justifie le flag dedie.

Option RETENUE : signal orthogonal `forced_only_languages` -> flag
`subtitle_forced_only_<lang>`, prefixe distinct qui traverse intact les
reconciliations et n'est efface que par une preuve : une piste MUXEE COMPLETE.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.domain.subtitle_helpers import build_subtitle_report
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.ui.api.run_read_support import full_langs_from_embedded, reconcile_subtitle_flags

_ROOT = Path(__file__).resolve().parents[1]


class _Row(SimpleNamespace):
    """PlanRow minimale pour dashboard_support._build_row_payload."""

    def __init__(self, **kw):
        base = dict(
            row_id="row-1",
            kind="single",
            folder="D:/Films/X",
            video="x.mkv",
            proposed_title="X",
            proposed_year=2020,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            nfo_path="",
            subtitle_count=0,
            subtitle_languages=[],
            subtitle_missing_langs=[],
            subtitle_orphans=0,
            notes="",
            warning_flags=[],
        )
        base.update(kw)
        super().__init__(**base)


# ---------------------------------------------------------------------------
# 1. DOMAINE — build_subtitle_report
# ---------------------------------------------------------------------------
class ForcedOnlyReportTests(unittest.TestCase):
    def _report(self, video_name, sub_names, expected, *, embedded=None):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / video_name
            video.write_bytes(b"\x00")
            for sub_name in sub_names:
                (folder / sub_name).write_text("", encoding="utf-8")
            return build_subtitle_report(folder, video, expected, embedded_subtitles=embedded)

    def test_forced_seul_leve_le_signal_sans_mentir_sur_les_langues(self) -> None:
        report = self._report("Film (2020).mkv", ["Film (2020).fr.forced.srt"], ["fr"])
        self.assertEqual(report.forced_only_languages, ["fr"])
        # La langue reste DETECTEE : le fichier existe vraiment.
        self.assertEqual(report.languages, ["fr"])
        # ... et n'est donc PAS "manquante" (les deux signaux sont disjoints).
        self.assertEqual(report.missing_languages, [])

    def test_piste_complete_a_cote_du_forced_ne_leve_rien(self) -> None:
        report = self._report(
            "Film (2020).mkv",
            ["Film (2020).fr.srt", "Film (2020).fr.forced.srt"],
            ["fr"],
        )
        self.assertEqual(report.forced_only_languages, [])
        self.assertEqual(report.missing_languages, [])

    def test_forced_embarque_seul_leve_le_signal(self) -> None:
        report = self._report(
            "Film (2020).mkv",
            [],
            ["fr"],
            embedded=[{"index": 0, "language": "fre", "forced": True}],
        )
        self.assertEqual(report.forced_only_languages, ["fr"])
        self.assertEqual(report.languages, ["fr"])

    def test_piste_muxee_complete_dement_le_forced_externe(self) -> None:
        report = self._report(
            "Film (2020).mkv",
            ["Film (2020).fr.forced.srt"],
            ["fr"],
            embedded=[{"index": 0, "language": "fra", "forced": False}],
        )
        self.assertEqual(report.forced_only_languages, [])

    def test_piste_muxee_sans_clef_forced_est_comptee_complete(self) -> None:
        """On n'invente pas 'forced' a partir d'une info absente."""
        report = self._report(
            "Film (2020).mkv",
            ["Film (2020).fr.forced.srt"],
            ["fr"],
            embedded=[{"index": 0, "language": "fre"}],
        )
        self.assertEqual(report.forced_only_languages, [])

    def test_signal_borne_aux_langues_attendues(self) -> None:
        """Un '.en.forced.srt' sur un film ou l'EN n'est pas attendu ne fait pas de bruit."""
        report = self._report("Film (2020).mkv", ["Film (2020).en.forced.srt"], ["fr"])
        self.assertEqual(report.forced_only_languages, [])
        self.assertEqual(report.missing_languages, ["fr"])
        report_sans_attente = self._report("Film (2020).mkv", ["Film (2020).fr.forced.srt"], [])
        self.assertEqual(report_sans_attente.forced_only_languages, [])

    def test_attente_en_iso639_2_normalisee(self) -> None:
        """'french'/'fra' cote attente doivent matcher comme 'fr' (parite avec missing)."""
        for expected in (["french"], ["fra"], ["FR"]):
            with self.subTest(expected=expected):
                report = self._report("Film (2020).mkv", ["Film (2020).fr.forced.srt"], expected)
                self.assertEqual(report.forced_only_languages, ["fr"])

    def test_sdh_n_est_pas_forced(self) -> None:
        """SDH/CC = piste COMPLETE (+ sons) : aucun signal a lever."""
        report = self._report("Film (2020).mkv", ["Film (2020).fr.sdh.srt"], ["fr"])
        self.assertEqual(report.forced_only_languages, [])

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_langue_reellement_absente_toujours_manquante(self) -> None:
        report = self._report("Film (2020).mkv", ["Film (2020).en.srt"], ["fr"])
        self.assertEqual(report.missing_languages, ["fr"])
        self.assertEqual(report.languages, ["en"])

    def test_piste_complete_seule_reste_muette(self) -> None:
        report = self._report("Film (2020).mkv", ["Film (2020).fr.srt"], ["fr"])
        self.assertEqual(report.missing_languages, [])
        self.assertEqual(report.forced_only_languages, [])
        self.assertEqual(report.duplicate_languages, [])


# ---------------------------------------------------------------------------
# 2. SCAN — le flag arrive bien dans PlanRow.warning_flags (et repart)
# ---------------------------------------------------------------------------
class ForcedOnlyScanFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_forced_f12_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)
        self.folder = self.root / "Film (2020)"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.video = self.folder / "Film (2020).mkv"
        self.video.write_bytes(b"a" * 4096)
        self.forced = self.folder / "Film (2020).fr.forced.srt"
        self.forced.write_text("", encoding="utf-8")
        self.full = self.folder / "Film (2020).fr.srt"

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 - teardown best-effort
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, run_id: str):
        cfg = core.Config(root=self.root, enable_tmdb=False, incremental_scan_enabled=True)
        return plan_support.plan_library(
            cfg,
            tmdb=None,
            log=lambda _lvl, _msg: None,
            progress=lambda _i, _t, _c: None,
            scan_index=self.store.scan,
            run_id=run_id,
            subtitle_expected_languages=["fr"],
        )

    def test_scan_pose_le_flag_et_pas_subtitle_missing(self) -> None:
        rows, _stats = self._scan("scan1")
        self.assertEqual(len(rows), 1)
        self.assertIn("subtitle_forced_only_fr", rows[0].warning_flags)
        self.assertNotIn("subtitle_missing_fr", rows[0].warning_flags)
        self.assertEqual(rows[0].subtitle_languages, ["fr"])

    def test_le_flag_repart_quand_une_piste_complete_est_ajoutee(self) -> None:
        """Garde anti-« on ne fait qu'ajouter » + parite F09 (cache row v2).

        Sans `subtitle_forced_only_` dans `_is_subtitle_flag`, la row servie par le
        cache row garde le flag perime pour toujours.
        """
        rows1, _ = self._scan("scan1")
        self.assertIn("subtitle_forced_only_fr", rows1[0].warning_flags)

        self.full.write_text("", encoding="utf-8")
        rows2, stats2 = self._scan("scan2")
        self.assertEqual(
            int(getattr(stats2, "incremental_cache_row_hits", 0) or 0),
            1,
            "le test doit passer par un HIT row sinon il ne prouve rien",
        )
        self.assertNotIn("subtitle_forced_only_fr", rows2[0].warning_flags)


# ---------------------------------------------------------------------------
# 3. LECTURE — reconciliation (le coeur de l'arbitrage)
# ---------------------------------------------------------------------------
class ForcedOnlyReconcileTests(unittest.TestCase):
    def test_option_ecartee_le_flag_missing_serait_efface_par_la_reconciliation(self) -> None:
        """POURQUOI un flag dedie : `subtitle_missing_fr` ne survit pas ici.

        Avec l'option « compter le .forced comme absent », la row porterait
        `subtitle_missing_fr` ET 'fr' dans ses langues detectees -> la
        reconciliation de lecture le juge perime et le supprime. L'alerte
        n'atteindrait aucun ecran.
        """
        kept = reconcile_subtitle_flags(["subtitle_missing_fr"], {"fr"})
        self.assertEqual(kept, [])

    def test_le_flag_dedie_survit_a_la_langue_presente(self) -> None:
        kept = reconcile_subtitle_flags(["subtitle_forced_only_fr", "not_a_movie"], {"fr"})
        self.assertEqual(kept, ["subtitle_forced_only_fr", "not_a_movie"])

    def test_le_flag_dedie_tombe_devant_une_piste_muxee_complete(self) -> None:
        kept = reconcile_subtitle_flags(["subtitle_forced_only_fr"], {"fr"}, {"fr"})
        self.assertEqual(kept, [])

    def test_une_piste_muxee_forcee_ne_dement_rien(self) -> None:
        embedded = [{"language": "fre", "forced": True}]
        self.assertEqual(full_langs_from_embedded(embedded), set())
        kept = reconcile_subtitle_flags(["subtitle_forced_only_fr"], {"fr"}, full_langs_from_embedded(embedded))
        self.assertEqual(kept, ["subtitle_forced_only_fr"])

    def test_full_langs_from_embedded_normalise_et_ignore_le_bruit(self) -> None:
        embedded = [
            {"language": "fra", "forced": False},
            {"language": "eng", "forced": True},
            {"language": None},
            "pas-un-dict",
            {"language": "zzz"},
        ]
        self.assertEqual(full_langs_from_embedded(embedded), {"fr"})
        self.assertEqual(full_langs_from_embedded(None), set())

    def test_export_conserve_le_flag_forced_only(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(warning_flags=["subtitle_forced_only_fr"], subtitle_languages=["fr"])
        quality = {"tier": "gold", "metrics": {"detected": {}, "subtitles_embedded": []}}
        payload, *_ = _build_row_payload("run-1", row, {}, quality)
        self.assertEqual(payload["warning_flags"], "subtitle_forced_only_fr")

    def test_export_retire_le_flag_devant_une_piste_muxee_complete(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(warning_flags=["subtitle_forced_only_fr", "not_a_movie"], subtitle_languages=["fr"])
        quality = {
            "tier": "gold",
            "metrics": {"detected": {}, "subtitles_embedded": [{"language": "fre", "forced": False}]},
        }
        payload, *_ = _build_row_payload("run-1", row, {}, quality)
        self.assertEqual(payload["warning_flags"], "not_a_movie")

    def test_full_langs_from_payload_ne_lit_que_les_pistes_embarquees(self) -> None:
        """Ecran Verification : la source de verite est `subtitles_embedded`.

        `subtitle_languages` contient deja 'fr' (le fichier FORCE) : le lire ici
        effacerait le flag a tous les coups — l'erreur exacte que l'arbitrage a
        ecartee.
        """
        from cinesort.ui.api.history_support import _full_langs_from_payload

        row = {"row_id": "r1", "subtitle_languages": ["fr"]}
        qr_forced = {"r1": {"metrics": {"subtitles_embedded": [{"language": "fre", "forced": True}]}}}
        self.assertEqual(_full_langs_from_payload(row, qr_forced), set())
        qr_full = {"r1": {"metrics": {"subtitles_embedded": [{"language": "fre", "forced": False}]}}}
        self.assertEqual(_full_langs_from_payload(row, qr_full), {"fr"})
        self.assertEqual(_full_langs_from_payload(row, {}), set())

    def test_badge_sidebar_aligne_sur_l_ecran_verification(self) -> None:
        """HIGH-4 : le badge « Qualite » doit reconcilier comme l'ecran Verification.

        Sans le 3e argument passe a `reconcile_subtitle_flags`, la row dont
        l'unique alerte est un forced_only DEMENTI (piste FR muxee complete)
        compterait dans le badge sans etre visible a l'ecran.
        """
        from cinesort.ui.api.dashboard_support import get_sidebar_counters
        from tests.test_audit_wave2_flags_v77 import _FakeApi, _FakeStore
        from tests.test_audit_wave2_flags_v77 import _Row as _WaveRow

        rows = [
            # a) forced_only DEMENTI par une piste muxee complete -> NE compte PAS
            _WaveRow(row_id="a", proposed_title="A", proposed_year=2001, warning_flags=["subtitle_forced_only_fr"]),
            # b) forced_only CONFIRME (seule piste muxee = forcee elle aussi) -> compte
            _WaveRow(row_id="b", proposed_title="B", proposed_year=2002, warning_flags=["subtitle_forced_only_fr"]),
        ]
        reports = [
            {"row_id": "a", "metrics": {"subtitles_embedded": [{"language": "fre", "forced": False}]}},
            {"row_id": "b", "metrics": {"subtitles_embedded": [{"language": "fre", "forced": True}]}},
        ]
        run_row = {"run_id": "run-1", "state_dir": str(Path.cwd())}
        api = _FakeApi(_FakeStore(run_row, reports, {}), rows)
        self.assertEqual(get_sidebar_counters(api)["quality"], 1)

    # --- NON-REGRESSION -----------------------------------------------------

    def test_subtitle_missing_inchange(self) -> None:
        self.assertEqual(reconcile_subtitle_flags(["subtitle_missing_fr"], set()), ["subtitle_missing_fr"])
        self.assertEqual(reconcile_subtitle_flags(["subtitle_missing_french"], {"fr"}), [])
        self.assertEqual(reconcile_subtitle_flags(["not_a_movie"], {"fr"}), ["not_a_movie"])


# ---------------------------------------------------------------------------
# 4. UI — le flag a un libelle humain (sinon il s'affiche en code brut)
# ---------------------------------------------------------------------------
class ForcedOnlyLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.labels = (_ROOT / "web" / "dashboard" / "core" / "alert-labels.js").read_text(encoding="utf-8")
        cls.traitement = (_ROOT / "web" / "dashboard" / "views" / "traitement.js").read_text(encoding="utf-8")

    def test_libelle_explicite_et_branche_dynamique(self) -> None:
        self.assertIn("subtitle_forced_only_fr:", self.labels)
        self.assertIn('c.startsWith("subtitle_forced_only_")', self.labels)
        self.assertIn("forcés uniquement", self.labels)

    def test_lentille_subs_couvre_le_flag(self) -> None:
        """Le film forced-only est auto-approuvable : sans la puce il est invisible."""
        self.assertIn('s.startsWith("subtitle_forced_only_fr")', self.traitement)


if __name__ == "__main__":
    unittest.main()
