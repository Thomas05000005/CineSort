"""Lot « des cles lues qui n'existent pas » — issues #866, #681, #683, #446.

Meme famille de defaut : une surface d'affichage lit une cle que personne ne
peuple, ou fige une valeur avant de savoir ce qu'elle vaut. Le symptome commun
est une valeur d'apparence normale (vide, 100 %, « mixed », 0) qu'aucun test ne
distinguait d'une mesure reussie.

Chaque test part du PRODUCTEUR reel de la donnee plutot que d'un dict fabrique
a la main, pour que le lien producteur -> lecteur soit ce qui est verifie.
L'issue #699 du meme lot n'a pas de test ici : elle est PERIMEE, corrigee par
la PR#854 (`_build_pseudo_probe` porte `width` depuis le commit 0d3d505) et
deja couverte par
`tests/test_scoring_class_review_2026_08_03.py::test_the_ab_cards_finally_display_the_dimensions`.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import cinesort.domain.core as core
from cinesort.domain.quality_score import compute_quality_score, default_quality_profile
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.ui.api import runtime_support
from cinesort.ui.api.dashboard_support import _build_library_rows as _dashboard_library_rows
from cinesort.ui.api.library_podiums_support import get_library_podiums
from cinesort.ui.api.library_support import _normalize_codec
from cinesort.ui.api.library_timeline_support import get_library_timeline


def _real_metrics(*, width: int, height: int, release_name: str) -> dict:
    """`metrics` produit par le VRAI moteur de scoring, pas un dict fabrique.

    C'est ce qui donne son verdict au test #866 : si le producteur renommait un
    jour sa cle, le test tomberait au lieu de continuer a valider un contrat
    imaginaire.
    """
    probe = {
        "video": {"width": width, "height": height, "codec": "hevc", "bit_depth": 10, "bitrate": 45_000_000},
        "audio_tracks": [{"codec": "dts", "channels": 6, "language": "fre"}],
        "duration_s": 7200,
        "subtitles": [],
    }
    result = compute_quality_score(
        normalized_probe=probe,
        profile=default_quality_profile(),
        release_name=release_name,
    )
    return result["metrics"]


def _plan_row(row_id: str, title: str, year: int) -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="movie",
        folder=f"/lib/{title}",
        video=f"/lib/{title}/{title}.mkv",
        proposed_title=title,
        proposed_year=year,
        proposed_source="tmdb",
        confidence=95,
        confidence_label="haute",
        candidates=[],
    )


class DashboardRowsResolutionTests(unittest.TestCase):
    """#866 : `_build_library_rows` lisait `detected["resolution_label"]`."""

    def test_the_producer_never_writes_resolution_label(self) -> None:
        """Ancrage : la cle que le lecteur cherchait n'est produite nulle part.

        `resolution_label` n'est qu'un nom de variable LOCAL dans le scoring ;
        ce qui atterrit dans `metrics.detected` s'appelle `resolution`.
        """
        detected = _real_metrics(width=3840, height=2160, release_name="Dune.2021.2160p.BluRay.x265-GRP")["detected"]
        self.assertNotIn("resolution_label", detected)
        self.assertEqual(detected["resolution"], "2160p")

    def test_dashboard_row_carries_the_resolution(self) -> None:
        metrics = _real_metrics(width=3840, height=2160, release_name="Dune.2021.2160p.BluRay.x265-GRP")
        row = _plan_row("r1", "Dune", 2021)
        rows = _dashboard_library_rows(
            [row],
            [{"row_id": "r1", "score": 88, "tier": "Gold", "metrics": metrics}],
        )
        self.assertEqual(rows[0]["resolution"], "2160p")

    def test_a_film_without_quality_report_stays_empty(self) -> None:
        """Contrat inchange : pas de rapport = pas de resolution inventee."""
        row = _plan_row("r2", "Sans rapport", 1999)
        rows = _dashboard_library_rows([row], [])
        self.assertEqual(rows[0]["resolution"], "")


class PodiumCodecSentinelTests(unittest.TestCase):
    """#681 : la sentinelle « unknown » comptait comme un codec valide."""

    def setUp(self) -> None:
        self.mock_api = MagicMock()
        self.mock_api.settings.get_settings.return_value = {"state_dir": "/tmp/test"}
        self.mock_store = MagicMock()
        self.mock_api._get_or_create_infra.return_value = (self.mock_store, None)
        self.mock_store.run.get_runs_summary.return_value = [{"run_id": "run-1"}]

    def test_the_producer_emits_a_truthy_sentinel(self) -> None:
        """Ancrage : c'est bien `_normalize_codec` qui fabrique la sentinelle.

        Sans cette assertion, le test suivant pourrait fabriquer lui-meme la
        condition qu'il pretend eprouver.
        """
        self.assertEqual(_normalize_codec(None), "unknown")
        self.assertEqual(_normalize_codec(""), "unknown")
        self.assertTrue(_normalize_codec(None))  # truthy : le piege exact

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_unknown_is_absent_from_the_codec_podium(self, mock_norm, mock_build) -> None:
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/A.2020.1080p.BluRay.x264-RARBG.mkv", "codec": _normalize_codec(None)},
            {"path": "/m/B.2020.1080p.BluRay.x264-RARBG.mkv", "codec": _normalize_codec(None)},
            {"path": "/m/C.2020.1080p.BluRay.x264-RARBG.mkv", "codec": _normalize_codec("hevc")},
        ]
        result = get_library_podiums(self.mock_api, run_id="run-1", limit=5)
        names = [entry["name"] for entry in result["codecs"]]
        self.assertNotIn("unknown", names)
        self.assertEqual(names, ["hevc"])

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_coverage_counts_only_real_codecs(self, mock_norm, mock_build) -> None:
        """1 codec reel sur 4 films = 25 %, et non 100 % comme avant."""
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": f"/m/M{i}.2020.1080p.BluRay.x264-RARBG.mkv", "codec": _normalize_codec(None)} for i in range(3)
        ] + [{"path": "/m/M3.2020.1080p.BluRay.x264-RARBG.mkv", "codec": _normalize_codec("h264")}]
        result = get_library_podiums(self.mock_api, run_id="run-1", limit=5)
        self.assertEqual(result["coverage"]["codecs_pct"], 25.0)

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_a_library_without_any_probe_reports_zero_coverage(self, mock_norm, mock_build) -> None:
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": f"/m/M{i}.2020.1080p.BluRay.x264-RARBG.mkv", "codec": _normalize_codec(None)} for i in range(5)
        ]
        result = get_library_podiums(self.mock_api, run_id="run-1", limit=5)
        self.assertEqual(result["codecs"], [])
        self.assertEqual(result["coverage"]["codecs_pct"], 0.0)


class TimelineSourceBadgeTests(unittest.TestCase):
    """#683 : `using_jellyfin` fige `bool(jelly_dates)` avant l'appariement."""

    def setUp(self) -> None:
        self.mock_api = MagicMock()
        settings = {"state_dir": "/tmp/test", "jellyfin_enabled": True}
        self.mock_api._internal_settings.return_value = settings
        self.mock_api.settings.get_settings.return_value = settings
        self.mock_store = MagicMock()
        self.mock_api._get_or_create_infra.return_value = (self.mock_store, None)
        self.mock_store.run.get_runs_summary.return_value = [{"run_id": "run-1"}]

    @patch("cinesort.ui.api.library_timeline_support._get_jellyfin_date_map")
    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_dates_present_but_zero_match_is_filesystem(self, mock_norm, mock_build, mock_mtime, mock_jelly) -> None:
        """Jellyfin repond, mais sur d'autres films : aucune de ses dates ne sert."""
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Film1.mkv", "tmdb_id": "111"},
            {"path": "/m/Film2.mkv", "tmdb_id": "222"},
        ]
        mock_jelly.return_value = {"999": "2025-03-01T10:00:00Z", "888": "2025-04-01T10:00:00Z"}
        mock_mtime.return_value = "2025-06"

        result = get_library_timeline(self.mock_api, months=6, run_id="run-1")
        self.assertEqual(result["source"], "filesystem")

    @patch("cinesort.ui.api.library_timeline_support._get_jellyfin_date_map")
    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_films_without_tmdb_id_cannot_claim_jellyfin(self, mock_norm, mock_build, mock_mtime, mock_jelly) -> None:
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [{"path": "/m/Film1.mkv", "tmdb_id": None}]
        mock_jelly.return_value = {"111": "2025-03-01T10:00:00Z"}
        mock_mtime.return_value = "2025-06"

        result = get_library_timeline(self.mock_api, months=6, run_id="run-1")
        self.assertEqual(result["source"], "filesystem")

    @patch("cinesort.ui.api.library_timeline_support._get_jellyfin_date_map")
    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_an_unparsable_jellyfin_date_is_not_a_jellyfin_date(
        self, mock_norm, mock_build, mock_mtime, mock_jelly
    ) -> None:
        """Le tmdb_id matche, mais la date est implausible : c'est le mtime qui sert."""
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [{"path": "/m/Film1.mkv", "tmdb_id": "111"}]
        mock_jelly.return_value = {"111": "1899-01-01T00:00:00Z"}
        mock_mtime.return_value = "2025-06"

        result = get_library_timeline(self.mock_api, months=6, run_id="run-1")
        self.assertEqual(result["source"], "filesystem")

    @patch("cinesort.ui.api.library_timeline_support._get_jellyfin_date_map")
    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_a_real_match_still_reports_jellyfin(self, mock_norm, mock_build, mock_mtime, mock_jelly) -> None:
        """Garde-fou symetrique : le correctif ne doit pas eteindre le vrai cas."""
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [{"path": "/m/Film1.mkv", "tmdb_id": "111"}]
        mock_jelly.return_value = {"111": "2025-03-01T10:00:00Z"}
        mock_mtime.return_value = "2025-06"

        result = get_library_timeline(self.mock_api, months=6, run_id="run-1")
        self.assertEqual(result["source"], "jellyfin")
        mock_mtime.assert_not_called()


class DiagnosticLibraryCountsTests(unittest.TestCase):
    """#446 : `_library_counts` interrogeait une table `library_items` absente."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.state_dir = Path(self._tmp.name)
        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()
        self.run_id = "20260805_120000"
        self.addCleanup(self._tmp.cleanup)

    def _api(self) -> MagicMock:
        api = MagicMock()
        api._state_dir = self.state_dir
        api._infra_by_state_dir = {runtime_support.state_dir_key(self.state_dir): (self.store, None)}
        return api

    def _seed(self, *, n_films: int, n_scored: int) -> None:
        self.store.run.insert_run_pending(
            run_id=self.run_id,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
            created_ts=time.time(),
        )
        run_paths = runtime_support.run_paths_for(self.state_dir, self.run_id, ensure_exists=True)
        run_paths.plan_jsonl.write_text(
            "".join(json.dumps({"row_id": f"r{i}", "proposed_title": f"Film {i}"}) + "\n" for i in range(n_films)),
            encoding="utf-8",
        )
        for i in range(n_scored):
            self.store.quality.upsert_quality_report(
                run_id=self.run_id,
                row_id=f"r{i}",
                score=80,
                tier="Gold",
                reasons=[],
                metrics={},
                profile_id="p",
                profile_version=1,
            )

    def test_the_dead_table_is_really_absent(self) -> None:
        """Ancrage : `library_items` n'existe pas — la requete d'avant NE POUVAIT pas repondre."""
        with self.store._managed_conn() as conn:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("library_items", names)

    def test_counts_reflect_the_real_library(self) -> None:
        self._seed(n_films=7, n_scored=4)
        self.assertEqual(runtime_support._library_counts(self._api()), (7, 4))

    def test_a_fully_scored_library_is_not_reported_as_empty(self) -> None:
        """Le symptome exact remonte par l'issue : « 0 film · 0 classe »."""
        self._seed(n_films=3, n_scored=3)
        total, scored = runtime_support._library_counts(self._api())
        self.assertEqual((total, scored), (3, 3))

    def test_reports_of_other_runs_do_not_leak_into_the_count(self) -> None:
        """Sans filtre par run, `lib_scored` cumulait tout l'historique."""
        self._seed(n_films=3, n_scored=3)
        self.store.run.insert_run_pending(
            run_id="20260101_000000",
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
            created_ts=time.time() - 10_000,
        )
        for i in range(9):
            self.store.quality.upsert_quality_report(
                run_id="20260101_000000",
                row_id=f"old{i}",
                score=50,
                tier="Bronze",
                reasons=[],
                metrics={},
                profile_id="p",
                profile_version=1,
            )
        self.assertEqual(runtime_support._library_counts(self._api()), (3, 3))

    def test_no_run_at_all_yields_zero(self) -> None:
        self.assertEqual(runtime_support._library_counts(self._api()), (0, 0))

    def test_diagnostic_payload_exposes_the_counts(self) -> None:
        """Le site d'appel reel (`get_diagnostic`), pas seulement le helper."""
        self._seed(n_films=5, n_scored=2)
        api = self._api()
        api._app_version = "test"
        with patch.object(runtime_support, "_detect_probe_versions", return_value=("", "")):
            diag = runtime_support.get_diagnostic(api)["diagnostic"]
        self.assertEqual(diag["lib_total"], 5)
        self.assertEqual(diag["lib_scored"], 2)


if __name__ == "__main__":
    unittest.main()
