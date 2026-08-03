"""Le detecteur de rapport qualite perime ne doit pas etre content-blind.

Ultra-audit 2026-08 (N30) : `get_quality_report(reuse_existing=True)` decidait
de reservir un rapport en cache sur le seul triplet
(metrics.engine_version, profile_id, profile_version). Or
`save_quality_profile` fait un `ON CONFLICT(id) DO UPDATE` qui remplace
`profile_json` en GARDANT la version (infra/db/repositories/quality.py:91) :
un utilisateur qui deplace ses seuils sans toucher a la version rendait le
triplet identique, et le rapport PERIME etait servi comme frais.

Correctif : une empreinte du CONTENU du profil est persistee dans
`metrics.profile_fingerprint` et entre dans la comparaison. Fail-closed :
empreinte absente (rapport anterieur) ou profil inserialisable => perime.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

sys.path.insert(0, ".")

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import quality_report_support
from cinesort.ui.api.quality_report_support import profile_fingerprint


def _profile(gold: int) -> Dict[str, Any]:
    return {
        "id": "MonProfil",
        "version": 1,
        "engine_version": "CinemaLux_v1",
        "tiers": {"gold": gold, "silver": 50},
        "weights": {"video": 0.6, "audio": 0.4},
    }


class _FakeRow:
    """PlanRow minimal : seuls ces attributs sont lus par `_probe_and_score`."""

    def __init__(self, *, folder: str, title: str, year: int, video: str) -> None:
        self.folder = folder
        self.proposed_title = title
        self.proposed_year = year
        self.video = video
        self.candidates: List[Any] = []


class _FakeProbeService:
    """Double de `ProbeService` : rend une probe canned, n'appelle pas ffprobe."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def probe_file(self, *, media_path: Any, settings: Any) -> Dict[str, Any]:
        return {
            "probe_quality": "OK",
            "normalized": {
                "height": 1080,
                "width": 1920,
                "video_codec": "h264",
                "bitrate_kbps": 8000,
                "duration_s": 7200.0,
                "container": "mkv",
                "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "fre"}],
                "subtitles": [{"language": "fre", "forced": False}],
            },
        }


class _FakeApi:
    def __init__(self, store: SQLiteStore, state_dir: Path, profile: Dict[str, Any]) -> None:
        self._store = store
        self._state_dir = state_dir
        self._profile = profile

    def _is_valid_run_id(self, run_id: Any) -> bool:
        return bool(str(run_id or "").strip())

    def _find_run_row(self, run_id: str):
        return ({"run_id": run_id, "state_dir": str(self._state_dir)}, self._store)

    def _get_run(self, run_id: str):
        return None

    def _run_paths_for(self, state_dir: Any, run_id: str, ensure_exists: bool = True):
        return {"run_dir": str(self._state_dir)}

    def _ensure_quality_profile(self, store: Any) -> Dict[str, Any]:
        return {
            "id": str(self._profile["id"]),
            "version": int(self._profile["version"]),
            "profile_json": self._profile,
        }

    def _load_rows_from_plan_jsonl(self, run_paths: Any) -> List[Any]:
        # Aucun film : si le cache est REFUSE, on repart en analyse et on
        # tombe sur "Film introuvable dans ce plan" -> preuve du refus.
        return []

    def _effective_probe_settings_for_runtime(self, run_row: Any) -> Dict[str, Any]:
        return {}


class QualityReportStaleProfileTests(unittest.TestCase):
    RUN_ID = "run_n30"
    ROW_ID = "R1"

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_n30_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite", busy_timeout_ms=5000)
        self.store.initialize()
        # quality_reports.run_id porte une FK vers runs : le run doit exister.
        self.store.run.insert_run_pending(
            run_id=self.RUN_ID,
            root=str(self._tmp),
            state_dir=str(self._tmp),
            config={},
        )

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 — teardown best effort
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_report(self, profile: Dict[str, Any], *, with_fingerprint: bool = True) -> None:
        metrics: Dict[str, Any] = {"engine_version": "CinemaLux_v1", "probe_quality": "OK"}
        if with_fingerprint:
            metrics["profile_fingerprint"] = profile_fingerprint(profile)
        self.store.quality.upsert_quality_report(
            run_id=self.RUN_ID,
            row_id=self.ROW_ID,
            score=72,
            tier="Gold",
            reasons=[],
            metrics=metrics,
            profile_id=str(profile["id"]),
            profile_version=int(profile["version"]),
        )

    def _get(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        api = _FakeApi(self.store, self._tmp, profile)
        return quality_report_support.get_quality_report(api, self.RUN_ID, self.ROW_ID, {"reuse_existing": True})

    # -- empreinte ----------------------------------------------------------

    def test_fingerprint_changes_when_content_changes(self) -> None:
        self.assertNotEqual(profile_fingerprint(_profile(70)), profile_fingerprint(_profile(95)))

    def test_fingerprint_is_insensitive_to_key_order(self) -> None:
        a = {"id": "P", "version": 1, "tiers": {"gold": 70, "silver": 50}}
        b = {"tiers": {"silver": 50, "gold": 70}, "version": 1, "id": "P"}
        self.assertEqual(profile_fingerprint(a), profile_fingerprint(b))
        self.assertNotEqual(profile_fingerprint(a), "")

    def test_unusable_profile_yields_the_empty_fail_closed_fingerprint(self) -> None:
        """Contrat fail-closed : "" signifie "je ne sais pas", donc "perime".

        Une empreinte non vide rendue ici ferait servir un rapport sur la foi
        d'un profil qu'on n'a pas su lire.
        """
        circulaire: Dict[str, Any] = {"id": "P"}
        circulaire["self"] = circulaire
        for mauvais in (None, "CinemaLux_v1", [], 42, circulaire):
            with self.subTest(profil=type(mauvais).__name__):
                self.assertEqual(profile_fingerprint(mauvais), "")

    def test_unreadable_profile_refuses_the_cache(self) -> None:
        """Consequence de la ligne ci-dessus sur la decision de reutilisation."""
        profile = _profile(70)
        self._seed_report(profile)
        circulaire: Dict[str, Any] = dict(profile)
        circulaire["self"] = circulaire  # json.dumps -> ValueError -> empreinte ""
        out = self._get(circulaire)
        self.assertFalse(out.get("skipped_existing"), out)
        self.assertIn("introuvable dans ce plan", str(out.get("message") or ""))

    # -- decision de reutilisation -----------------------------------------

    def test_unchanged_profile_still_reuses_the_cached_report(self) -> None:
        """Non-regression : sans edition, le cache doit toujours servir."""
        profile = _profile(70)
        self._seed_report(profile)
        out = self._get(profile)
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("skipped_existing"), out)
        self.assertEqual(out.get("status"), "ignored_existing")
        self.assertEqual(out.get("score"), 72)

    def test_edited_profile_same_id_and_version_invalidates_the_cache(self) -> None:
        """Le coeur du finding : seuils modifies, id/version inchanges."""
        self._seed_report(_profile(70))
        out = self._get(_profile(95))  # meme id, meme version, seuil different
        self.assertFalse(out.get("skipped_existing"), out)
        self.assertNotEqual(out.get("status"), "ignored_existing")
        # Le cache ayant ete refuse, on repart en analyse (pas de film ici).
        self.assertFalse(out.get("ok"), out)
        self.assertIn("introuvable dans ce plan", str(out.get("message") or ""))

    def test_legacy_report_without_fingerprint_is_treated_as_stale(self) -> None:
        """Fail-closed : un rapport anterieur au correctif est recalcule."""
        profile = _profile(70)
        self._seed_report(profile, with_fingerprint=False)
        out = self._get(profile)
        self.assertFalse(out.get("skipped_existing"), out)
        self.assertIn("introuvable dans ce plan", str(out.get("message") or ""))

    def test_default_path_never_reuses(self) -> None:
        """Rappel de contrat : sans reuse_existing, aucune reutilisation."""
        profile = _profile(70)
        self._seed_report(profile)
        api = _FakeApi(self.store, self._tmp, profile)
        out = quality_report_support.get_quality_report(api, self.RUN_ID, self.ROW_ID, None)
        self.assertFalse(out.get("skipped_existing"), out)


class QualityReportFingerprintPersistenceTests(unittest.TestCase):
    """Cote ECRITURE : l'empreinte doit reellement etre persistee par le
    scoring, sinon la comparaison fail-closed refuse le cache POUR TOUJOURS.

    Sans ces tests, une mutation supprimant la persistance de
    `metrics.profile_fingerprint` laissait la classe ci-dessus verte : elle
    seede les rapports elle-meme. Le symptome reel serait alors silencieux —
    non pas un score faux, mais un cache qui ne sert plus jamais.
    """

    RUN_ID = "run_n30_w"
    ROW_ID = "R1"

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_n30w_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite", busy_timeout_ms=5000)
        self.store.initialize()
        self.store.run.insert_run_pending(
            run_id=self.RUN_ID,
            root=str(self._tmp),
            state_dir=str(self._tmp),
            config={},
        )
        self.media = self._tmp / "Film.2020" / "film.mkv"
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b"\x00" * 16)

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 — teardown best effort
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _score_once(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Execute le VRAI `_probe_and_score` avec une probe canned (pas ffprobe)."""
        api = _FakeApi(self.store, self._tmp, profile)
        row = _FakeRow(folder=str(self.media.parent), title="Film", year=2020, video=self.media.name)
        with mock.patch.object(quality_report_support, "ProbeService", _FakeProbeService):
            _probe_result, out = quality_report_support._probe_and_score(
                api,
                self.store,
                {"run_id": self.RUN_ID, "state_dir": str(self._tmp)},
                self.RUN_ID,
                self.ROW_ID,
                row,
                self.media,
                profile_json=profile,
                active_profile_id=str(profile["id"]),
                active_profile_version=int(profile["version"]),
            )
        return out

    def test_scoring_persists_the_profile_fingerprint(self) -> None:
        profile = _profile(70)
        self._score_once(profile)
        stored = self.store.quality.get_quality_report(run_id=self.RUN_ID, row_id=self.ROW_ID)
        self.assertIsNotNone(stored, "aucun rapport persiste")
        metrics = stored.get("metrics") or {}
        self.assertEqual(
            metrics.get("profile_fingerprint"),
            profile_fingerprint(profile),
            "l'empreinte du profil n'a pas ete persistee avec le rapport",
        )

    def test_report_written_by_scoring_is_reusable_by_the_cache(self) -> None:
        """Boucle fermee : ecrire puis relire doit produire un CACHE HIT.

        C'est la consequence fonctionnelle de la persistance. Si l'empreinte
        n'est pas ecrite, la garde fail-closed refuse le rapport et le film est
        re-score a chaque appel.
        """
        profile = _profile(70)
        self._score_once(profile)
        api = _FakeApi(self.store, self._tmp, profile)
        out = quality_report_support.get_quality_report(api, self.RUN_ID, self.ROW_ID, {"reuse_existing": True})
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("skipped_existing"), f"cache jamais servi apres une ecriture legitime : {out}")
        self.assertEqual(out.get("status"), "ignored_existing")

    def test_report_written_by_scoring_is_refused_after_a_profile_edit(self) -> None:
        """Meme boucle, mais le profil est edite entre l'ecriture et la relecture."""
        self._score_once(_profile(70))
        api = _FakeApi(self.store, self._tmp, _profile(95))
        out = quality_report_support.get_quality_report(api, self.RUN_ID, self.ROW_ID, {"reuse_existing": True})
        self.assertFalse(out.get("skipped_existing"), out)


if __name__ == "__main__":
    unittest.main()
