"""F35 — _build_fusion_inputs_from_groups lisait une cle de groupe INEXISTANTE.

Bug d'origine (revue post-merge 2026-07-18, F35) : les groupes emis par
`find_duplicate_targets` portent leurs membres sous la cle 'rows'
(cinesort/domain/duplicate_support.py), mais
`run_flow_support._build_fusion_inputs_from_groups` lisait `grp.get('members')`
-> 0 bucket, donc `check_duplicates_fusion` repondait TOUJOURS
`{ok: true, enabled: true, pairs: []}`, contrat de la docstring jamais rempli.

Double casse : meme en corrigeant la cle, les items de groupe n'exposent
ni 'src'/'source_path'/'path', et PlanRow n'a ni duration_s ni
audio_fingerprint -> `video_path` restait vide et chaque membre etait skippe.
On resout donc le chemin video depuis les champs canoniques du PlanRow
(folder + video) et on lit duree/empreinte depuis les artefacts deja
persistes (quality_reports / perceptual_reports).

fail-before / pass-after : (a) 0 -> 1 bucket de 2 entrees avec des chemins
video EXISTANTS ; (b) duree/chromaprint lus depuis le store ; (c) un
sqlite3.Error du store est avale (sqlite3.Error n'herite PAS de OSError).

NON-REGRESSION : la tolerance historique ('members' + 'src' explicite) doit
rester fonctionnelle -> VERT avant ET apres.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.ui.api.run_flow_support import _build_fusion_inputs_from_groups


class _FakeQualityRepo:
    def __init__(self, payload: Any = None, exc: BaseException | None = None) -> None:
        self._payload = payload
        self._exc = exc

    def get_quality_report(self, *, run_id: str, row_id: str) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._payload


class _FakePerceptualRepo:
    def __init__(self, payload: Any = None, exc: BaseException | None = None) -> None:
        self._payload = payload
        self._exc = exc

    def get_perceptual_report(self, *, run_id: str, row_id: str) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._payload


class _FakeStore:
    def __init__(self, quality: Any, perceptual: Any) -> None:
        self.quality = quality
        self.perceptual = perceptual


class FusionInputsFromGroupsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="fusion_groups_f35_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.rows = [
            self._row("r1", self.root / "A" / "Seven.1995.1080p"),
            self._row("r2", self.root / "B" / "Se7en.1995.720p"),
        ]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, row_id: str, folder: Path) -> core.PlanRow:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(b"data-" + row_id.encode("ascii"))
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title="Seven",
            proposed_year=1995,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            candidates=[],
        )

    def _groups(self) -> List[Dict[str, Any]]:
        cfg = core.Config(root=self.root, enable_collection_folder=False).normalized()
        decisions = {r.row_id: {"ok": True, "title": "Seven", "year": 1995} for r in self.rows}
        data = plan_support.find_duplicate_targets(cfg, self.rows, decisions)
        self.assertEqual(data["total_groups"], 1, "pre-condition du test : 1 groupe attendu")
        return data["groups"]

    def test_build_fusion_inputs_reads_rows_key_and_resolves_video_path(self) -> None:
        buckets = _build_fusion_inputs_from_groups(self._groups(), self.rows)

        self.assertEqual(len(buckets), 1, "le groupe legacy porte ses membres sous 'rows'")
        self.assertEqual(len(buckets[0]), 2)
        self.assertTrue(
            all(Path(f.video_path).exists() for f in buckets[0]),
            [f.video_path for f in buckets[0]],
        )

    def test_fusion_inputs_pull_duration_and_chromaprint_from_store(self) -> None:
        store = _FakeStore(
            quality=_FakeQualityRepo({"metrics": {"detected": {"duration_s": 7200.0}}}),
            perceptual=_FakePerceptualRepo({"audio_fingerprint": "AQAAxx"}),
        )
        buckets = _build_fusion_inputs_from_groups(
            self._groups(), self.rows, store=store, run_id="run1"
        )

        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0][0].duration_s, 7200.0)
        self.assertEqual(buckets[0][0].chromaprint, "AQAAxx")

    def test_store_sqlite_error_is_swallowed(self) -> None:
        store = _FakeStore(
            quality=_FakeQualityRepo(exc=sqlite3.OperationalError("database is locked")),
            perceptual=_FakePerceptualRepo(exc=sqlite3.OperationalError("database is locked")),
        )
        buckets = _build_fusion_inputs_from_groups(
            self._groups(), self.rows, store=store, run_id="run1"
        )

        self.assertEqual(len(buckets), 1, "sqlite3.Error n'herite PAS de OSError")
        self.assertEqual(buckets[0][0].duration_s, 0.0)
        self.assertIsNone(buckets[0][0].chromaprint)

    def test_legacy_members_key_with_explicit_src_still_supported(self) -> None:
        # NON-REGRESSION : la forme historique tolerante ('members' + 'src')
        # doit continuer a produire un bucket. VERT avant ET apres.
        legacy = [
            {
                "members": [
                    {"row_id": "r1", "src": str(self.root / "A" / "Seven.1995.1080p" / "movie.mkv")},
                    {"row_id": "r2", "src": str(self.root / "B" / "Se7en.1995.720p" / "movie.mkv")},
                ]
            }
        ]
        buckets = _build_fusion_inputs_from_groups(legacy, self.rows)

        self.assertEqual(len(buckets), 1)
        self.assertEqual({f.row_id for f in buckets[0]}, {"r1", "r2"})

    def test_empty_groups_yield_no_bucket(self) -> None:
        # NON-REGRESSION : aucun groupe -> aucune paire. VERT avant ET apres.
        self.assertEqual(_build_fusion_inputs_from_groups([], self.rows), [])


class FusionUnknownDurationTests(unittest.TestCase):
    """F35 (revue R1) — une duree INCONNUE ne doit jamais nourrir le hash video.

    `extract_video_thumbnails` repartit ses N frames entre `start` et `end` ;
    avec `duration_s <= 0` la fenetre retombe sur [0.0, 1.0] (verifie par
    execution : timestamps 0.05 ... 0.95 au lieu de 414 ... 6786 pour 7200 s) et
    les 10 frames comparees tombent TOUTES dans la premiere seconde — la zone ou
    quasiment tous les films sont noirs. Deux films DIFFERENTS rendent alors une
    distance pHash nulle -> video_sim = 1.0 -> verdict 'confirmed'.

    Or duration_s vaut 0.0 des qu'il n'y a pas de quality_report : le recalcul
    qualite est un job de FOND lance apres le scan, desactivable, et le probe
    peut echouer (SMB / fichier corrompu). Avant F35 l'endpoint etait INERTE
    (pairs=[] systematique) ; le rendre reel sans ce durcissement le fait
    AFFIRMER « doublon confirme » sur deux films sans rapport.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="fusion_duration_f35_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.rows = [
            self._row("r1", self.root / "A" / "Seven.1995.1080p"),
            self._row("r2", self.root / "B" / "Se7en.1995.720p"),
        ]
        self.groups = [
            {
                "title": "Seven",
                "year": 1995,
                "rows": [{"row_id": "r1"}, {"row_id": "r2"}],
            }
        ]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, row_id: str, folder: Path) -> core.PlanRow:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(b"data-" + row_id.encode("ascii"))
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title="Seven",
            proposed_year=1995,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            candidates=[],
        )

    def _call_endpoint(self, duration_s: float) -> tuple:
        """Retourne (reponse, buckets recus par compute_fusion_for_groups)."""
        from cinesort.app import duplicate_pipeline
        from cinesort.ui.api import run_flow_support

        api = mock.MagicMock()
        rs = mock.MagicMock()
        rs.rows = self.rows
        rs.store = _FakeStore(
            quality=_FakeQualityRepo({"metrics": {"detected": {"duration_s": duration_s}}}),
            perceptual=_FakePerceptualRepo({}),
        )
        api._get_run.return_value = rs

        seen: List[List[Any]] = []

        def _spy(candidate_groups: Any, **_kw: Any) -> List[Any]:
            # Aucun ffmpeg ne doit tourner dans un test : on capture seulement
            # ce que le pipeline AURAIT hashe.
            seen.append([list(bucket) for bucket in candidate_groups])
            return []

        with (
            mock.patch.object(run_flow_support, "check_duplicates", return_value={"ok": True, "groups": self.groups}),
            mock.patch.dict("os.environ", {"CINESORT_FUSION_DOUBLONS": "1"}),
            mock.patch.object(duplicate_pipeline, "compute_fusion_for_groups", _spy),
        ):
            resp = run_flow_support.check_duplicates_fusion(api, "run1", {})

        return resp, (seen[0] if seen else None)

    def test_duree_inconnue_aucun_film_ne_part_au_hash_video(self) -> None:
        resp, buckets = self._call_endpoint(0.0)

        self.assertTrue(resp["ok"], msg=str(resp))
        self.assertEqual(resp["pairs"], [])
        self.assertEqual(
            buckets,
            [],
            "Duree inconnue -> les 10 frames tomberaient toutes dans la 1re "
            "seconde (ecran noir) et deux films differents seraient declares "
            "« doublon confirme ». Aucun bucket ne doit atteindre ffmpeg.",
        )

    def test_duree_connue_le_calcul_fusion_a_bien_lieu(self) -> None:
        # NON-REGRESSION : le durcissement ne doit pas neutraliser l'endpoint que
        # F35 vient de rendre fonctionnel. VERT avant ET apres le correctif.
        resp, buckets = self._call_endpoint(7200.0)

        self.assertTrue(resp["ok"], msg=str(resp))
        assert buckets is not None
        self.assertEqual(len(buckets), 1)
        self.assertEqual({film.row_id for film in buckets[0]}, {"r1", "r2"})
        self.assertTrue(all(film.duration_s == 7200.0 for film in buckets[0]))


class FusionEndpointStorePlumbingTests(unittest.TestCase):
    """Le call site doit transmettre le store et le run_id au builder."""

    def test_check_duplicates_fusion_passes_store_and_run_id(self) -> None:
        from cinesort.ui.api import run_flow_support

        api = mock.MagicMock()
        rs = mock.MagicMock()
        rs.rows = ["row-sentinel"]
        rs.store = "store-sentinel"
        api._get_run.return_value = rs

        captured: Dict[str, Any] = {}

        def _fake_builder(groups: Any, rows: Any, **kwargs: Any) -> List[List[Any]]:
            captured["kwargs"] = kwargs
            return []

        with (
            mock.patch.object(run_flow_support, "check_duplicates", return_value={"ok": True, "groups": []}),
            mock.patch.dict("os.environ", {"CINESORT_FUSION_DOUBLONS": "1"}),
            mock.patch.object(run_flow_support, "_build_fusion_inputs_from_groups", _fake_builder),
        ):
            resp = run_flow_support.check_duplicates_fusion(api, "run1", {})

        self.assertTrue(resp["ok"], msg=str(resp))
        self.assertEqual(captured["kwargs"].get("store"), "store-sentinel")
        self.assertEqual(captured["kwargs"].get("run_id"), "run1")


if __name__ == "__main__":
    unittest.main()
