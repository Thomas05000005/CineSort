"""#494 — les `message` JSON renvoyes a l'UI passent par l'i18n backend.

Sept sites de `cinesort/ui/api/` composaient leur `message` en francais ECRIT EN
DUR dans le payload JSON. Ces payloads sont lus par le serveur REST, dont les
clients externes choisissent leur locale via `settings/set_locale`, et par le
dashboard livre, qui affiche `data.message` tel quel sur deux d'entre eux
(`web/dashboard/components/duplicate-comparator-modal.js:392` et
`web/dashboard/views/doublons.js:1101`). Un utilisateur en `en` recevait donc du
francais.

Ce que ces tests verrouillent, et pourquoi ils sont ecrits ainsi :

* **Ils passent par les FACADES publiques**, pas par les helpers prives. Un test
  qui n'appellerait que `dashboard_support._empty_dashboard_payload` resterait
  vert si le vrai chemin (`run.get_dashboard`) produisait son message ailleurs.
  Ici c'est le chemin reellement emprunte par l'UI qui est exerce.
* **Ils comparent la chaine EXACTE (`assertEqual`)**, jamais une sous-chaine :
  `assertIn("No data", msg)` passerait sur "No database found".
* **Ils assertent en locale `en` ET en locale `fr`.** L'assertion `en` est celle
  qui detecte la regression (un litteral francais reintroduit dans le code ne
  suit pas la locale). L'assertion `fr` verrouille l'absence d'effet de bord :
  la sortie par defaut doit rester mot pour mot celle d'avant #494 — sinon le
  correctif i18n aurait discretement reformule des messages en production.

Le huitieme site cite par l'issue (`apply_support.py`, le mot "Aucune" du
libelle de familles de nettoyage) est VOLONTAIREMENT laisse en francais : ce
n'est pas un `message` JSON mais un fragment d'un bloc de resume texte de ~60
lignes integralement francais, ecrit dans le rapport d'apply. Le traduire seul
produirait "None" au milieu d'un paragraphe francais.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from cinesort.domain import i18n_messages
from cinesort.ui.api import dashboard_support
from cinesort.ui.api.cinesort_api import CineSortApi

# Messages attendus, mot pour mot. La colonne FR est la chaine qui etait ecrite
# en dur AVANT #494 : elle doit rester identique (aucune reformulation cachee).
FR_NO_RUN_DASHBOARD = "Aucun run disponible pour le dashboard."
EN_NO_RUN_DASHBOARD = "No run available for the dashboard."

FR_HEALTH_NO_DATA = "Pas de donnees"
EN_HEALTH_NO_DATA = "No data"

FR_PERCEPTUAL_NO_ANALYSIS = "Aucune analyse perceptuelle persistee pour ce film. Lancez l'analyse depuis l'inspecteur."
EN_PERCEPTUAL_NO_ANALYSIS = "No perceptual analysis stored for this movie. Start the analysis from the inspector."

FR_NO_ALIGNED_FRAME = "Aucune frame alignee extraite."
EN_NO_ALIGNED_FRAME = "No aligned frame extracted."

FR_NO_VALID_PAIR = "Aucune paire valide. Format attendu : [{run_id, row_a, row_b}, ...]"
EN_NO_VALID_PAIR = "No valid pair. Expected format: [{run_id, row_a, row_b}, ...]"

FR_NO_DB_TO_DELETE = "Aucune DB existante a supprimer."
EN_NO_DB_TO_DELETE = "No existing database to delete."

FR_NO_ROWS_IN_RUN = "Aucune ligne dans le run."
EN_NO_ROWS_IN_RUN = "No row in this run."


class _LocaleAwareTestCase(unittest.TestCase):
    """Restaure l'etat i18n global apres chaque test.

    `i18n_messages` porte un etat de MODULE (locale active + messages charges).
    Sans restauration, un test laissant la locale sur `en` ferait tomber les
    tests qui assertent des messages francais (p. ex.
    `test_perceptual_compare_frames.py::test_perceptual_disabled_returns_error`).
    """

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(i18n_messages.reload_messages)

    def assertLocalized(self, produce, expected_fr: str, expected_en: str) -> None:
        """`produce()` doit rendre `expected_fr` en locale fr et `expected_en` en en."""
        i18n_messages.set_locale("fr")
        self.assertEqual(produce(), expected_fr, "la sortie par defaut (fr) a change")
        i18n_messages.set_locale("en")
        self.assertEqual(
            produce(),
            expected_en,
            "message non localise : la chaine est probablement ecrite en dur dans le code",
        )


def _write_settings(state_dir: Path, **fields: Any) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "settings.json").write_text(json.dumps(fields), encoding="utf-8")


class DashboardMessagesTests(_LocaleAwareTestCase):
    """`run.get_dashboard` et `run.get_global_stats` — chemin reel, store reel."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="cs_i18n_494_dash_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def _seed_run(self, run_id: str) -> None:
        ts = time.time()
        self.store.run.insert_run_pending(
            run_id=run_id, root=str(self.root), state_dir=str(self.state_dir), config={}, created_ts=ts - 1
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)
        self.store.run.mark_run_done(run_id, stats={"planned_rows": 0}, ended_ts=ts + 5)

    def test_dashboard_without_run_localizes_its_message(self) -> None:
        def produce() -> str:
            payload = self.api.run.get_dashboard("latest")
            self.assertTrue(payload.get("ok"), payload)
            return str(payload.get("message"))

        self.assertLocalized(produce, FR_NO_RUN_DASHBOARD, EN_NO_RUN_DASHBOARD)

    def test_global_stats_health_trend_localizes_its_message(self) -> None:
        """Un run sans instantane de sante -> le trend rend "pas de donnees".

        Passe par `run.get_global_stats`, donc par le VRAI appelant de
        `_compute_health_trend` (dashboard_support.py, section "8b").
        """
        self._seed_run("20260805_120000_a")

        def produce() -> str:
            payload = self.api.run.get_global_stats(10)
            self.assertTrue(payload.get("ok"), payload)
            trend = payload.get("health_trend")
            self.assertIsInstance(trend, dict, payload)
            return str(trend.get("message"))

        self.assertLocalized(produce, FR_HEALTH_NO_DATA, EN_HEALTH_NO_DATA)


class HealthTrendBranchesTests(_LocaleAwareTestCase):
    """Les QUATRE autres branches de `_compute_health_trend`.

    L'issue ne citait que "Pas de donnees", mais les cinq messages de cette
    fonction repartent dans le meme champ `health_trend.message`. N'en traduire
    qu'un aurait produit un payload bilingue selon le nombre de runs. La branche
    "pas de donnees" est deja couverte via la facade ci-dessus : cette
    fonction est donc prouvee SUR le chemin reel, et on peut y injecter ici les
    timelines que la facade ne sait pas fabriquer sans instantanes de sante.
    """

    @staticmethod
    def _timeline(*scores: int) -> List[Dict[str, Any]]:
        # `_compute_health_trend` parcourt la timeline a l'ENVERS : le dernier
        # element est le run le plus recent.
        return [{"health_score": s} for s in scores]

    def test_single_snapshot_reports_current_health(self) -> None:
        self.assertLocalized(
            lambda: str(dashboard_support._compute_health_trend(self._timeline(72))["message"]),
            "Sante : 72%",
            "Health: 72%",
        )

    def test_improvement_is_localized(self) -> None:
        self.assertLocalized(
            lambda: str(dashboard_support._compute_health_trend(self._timeline(60, 68))["message"]),
            "↑ +8% depuis le dernier run",
            "↑ +8% since the last run",
        )

    def test_regression_is_localized(self) -> None:
        self.assertLocalized(
            lambda: str(dashboard_support._compute_health_trend(self._timeline(70, 65))["message"]),
            "↓ -5% depuis le dernier run",
            "↓ -5% since the last run",
        )

    def test_stable_is_localized(self) -> None:
        # La traduction EN dit "No change" et non "Stable" : sans cet ecart, un
        # retour au litteral francais "→ Stable" laisserait le test VERT — la
        # mutation ne serait pas detectable et le test serait vacant.
        self.assertLocalized(
            lambda: str(dashboard_support._compute_health_trend(self._timeline(70, 70))["message"]),
            "→ Stable",
            "→ No change",
        )


class PerceptualMessagesTests(_LocaleAwareTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_i18n_494_perc_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def test_details_without_stored_analysis_localizes_its_message(self) -> None:
        def produce() -> str:
            payload = self.api.quality.get_perceptual_details("20260805_120000_a", "row-1")
            self.assertFalse(payload.get("ok"), payload)
            self.assertTrue(payload.get("missing"), payload)
            return str(payload.get("message"))

        self.assertLocalized(produce, FR_PERCEPTUAL_NO_ANALYSIS, EN_PERCEPTUAL_NO_ANALYSIS)

    def test_empty_pair_list_localizes_its_message(self) -> None:
        def produce() -> str:
            payload = self.api.quality.queue_perceptual_analyses([])
            self.assertFalse(payload.get("ok"), payload)
            return str(payload.get("message"))

        self.assertLocalized(produce, FR_NO_VALID_PAIR, EN_NO_VALID_PAIR)

    def test_no_aligned_frame_localizes_its_message(self) -> None:
        """Extraction de frames qui ne rend rien -> message localise.

        Les mocks posent la PRECONDITION (aucun media reel, aucun ffmpeg,
        extraction vide) ; ils ne fabriquent pas le message teste, qui est
        construit par le code de production apres leur retour.
        """
        _write_settings(self._tmp, perceptual_enabled=True, ffprobe_path="/fake/ffprobe")
        row_a = mock.MagicMock(row_id="a", proposed_year=2020)
        row_b = mock.MagicMock(row_id="b", proposed_year=2020)
        patches = [
            mock.patch.object(
                self.api, "_find_run_row", return_value=({"state_dir": str(self._tmp)}, mock.MagicMock())
            ),
            mock.patch.object(
                self.api, "_get_run", return_value=mock.MagicMock(rows=[row_a, row_b], cfg=mock.MagicMock())
            ),
            mock.patch.object(self.api, "_run_paths_for", return_value=mock.MagicMock()),
            mock.patch.object(self.api, "_resolve_media_path_for_row", side_effect=lambda *_a, **_k: Path("/m/a.mkv")),
            mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/fake/ffmpeg"),
            mock.patch(
                "cinesort.ui.api.perceptual_support._load_probe",
                return_value={"normalized": {"duration_s": 100.0, "video": {"width": 4, "height": 4}}},
            ),
            mock.patch("cinesort.domain.perceptual.comparison.extract_aligned_frames", return_value=[]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        def produce() -> str:
            payload = self.api.quality.get_perceptual_compare_frames("20260805_120000_a", "a", "b")
            self.assertFalse(payload.get("ok"), payload)
            return str(payload.get("message"))

        self.assertLocalized(produce, FR_NO_ALIGNED_FRAME, EN_NO_ALIGNED_FRAME)


class ResetDatabaseMessageTests(_LocaleAwareTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_i18n_494_reset_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp
        _write_settings(self._tmp, tmdb_enabled=False)
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def test_no_database_message_is_localized(self) -> None:
        def produce() -> str:
            payload = self.api.settings.reset_database()
            # Rien a supprimer n'est pas une erreur : le contrat reste ok=True.
            self.assertTrue(payload.get("ok"), payload)
            return str(payload.get("message"))

        self.assertLocalized(produce, FR_NO_DB_TO_DELETE, EN_NO_DB_TO_DELETE)


class ExportNfoMessageTests(_LocaleAwareTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_i18n_494_nfo_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def test_run_without_row_localizes_its_message(self) -> None:
        """Rapport de run valide mais sans aucune ligne -> message localise.

        Le rapport est stubbe parce que fabriquer un run reel a ZERO ligne
        demande un plan.jsonl vide ET une base coherente ; le stub porte la
        precondition (`rows == []`), tout le reste — validation du run_id,
        branchement, construction du message — reste du code de production.
        """
        stub_report: Dict[str, Any] = {"ok": True, "report": {"rows": []}}
        with mock.patch.object(dashboard_support, "build_run_report_payload", return_value=(stub_report, None)):

            def produce() -> str:
                payload = self.api.run.export_run_nfo("20260805_120000_a")
                self.assertFalse(payload.get("ok"), payload)
                return str(payload.get("message"))

            self.assertLocalized(produce, FR_NO_ROWS_IN_RUN, EN_NO_ROWS_IN_RUN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
