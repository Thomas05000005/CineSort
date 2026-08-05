"""Lot « contrats incoherents entre couches » — issues #805, #699, #472.

Meme famille : deux etages du pipeline ne sont pas d'accord sur la forme ou sur
la definition de la donnee qu'ils s'echangent, et rien ne leve.

* #805 — `apply_support._execute_apply` ecrivait `_r.tmdb_id` sur une `PlanRow`.
  `PlanRow` est un dataclass SANS ce champ et SANS `__slots__` : l'affectation
  reussit, cree un attribut d'instance, et `asdict()` (seule voie de
  serialisation d'une PlanRow) le jette. Ecriture morte de bout en bout.
* #699 (residu) — `_build_pseudo_probe` porte `width` depuis la PR#854, mais
  `classify_resolution` documente explicitement que la hauteur sert de filet
  « quand la largeur manque ». Dans ce cas la classe est MESUREE et le
  comparateur s'en sert pour trancher, alors que la carte A/B restait muette.
* #472 — `premium_count`/`low_count` etaient calcules sur des seuils de score en
  dur (85/55), fossiles de l'echelle de tiers PRE-v1.5.5 (85/68/54/30). Depuis
  la recalibration 70/66/55/40, un film affiche Platinum n'etait pas compte
  premium.

Chaque test part du PRODUCTEUR reel (SQLiteStore, `compute_quality_score`,
`_execute_apply` avec le vrai `apply_core.apply_rows`) : un MagicMock sur le
store aurait fabrique l'attribut `tmdb_id` absent et rendu #805 invisible.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import cinesort.domain.core as core
import cinesort.ui.api.cinesort_api as backend
from cinesort.domain.quality_score import compute_quality_score, default_quality_profile
from cinesort.domain.tiers_helpers import determine_tier, is_premium_tier
from cinesort.infra import state
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import apply_support, dashboard_support, library_actions_support
from cinesort.ui.api.run_flow_support import _build_pseudo_probe, _quality_info_for_row

RUN_ID = "20260805_contrats_couches"


# ---------------------------------------------------------------------------
# #805 — l'overlay d'override TMDb de l'apply
# ---------------------------------------------------------------------------


def _run_paths(state_dir: Path) -> state.RunPaths:
    run_dir = state_dir / "runs" / f"tri_films_{RUN_ID}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=RUN_ID,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


class ApplyTmdbOverlayContractTests(unittest.TestCase):
    """#805 : ce que l'overlay d'apply doit ecrire — et ce qu'il ne doit PAS."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_805_")
        self.tmp = Path(self._tmp)
        self.root = self.tmp / "films"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.tmp / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Store REEL : un MagicMock aurait accepte `store.film_modal.<n'importe
        # quoi>` et surtout aurait rendu l'ecriture fantome indetectable.
        self.store = SQLiteStore(self.state_dir / "cinesort.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _movie(self, folder_name: str, video_name: str) -> Path:
        src = self.root / folder_name
        src.mkdir(parents=True, exist_ok=True)
        (src / video_name).write_bytes(b"x" * 4096)
        return src

    def _row(self, folder: Path, video_name: str) -> core.PlanRow:
        return core.PlanRow(
            row_id="f1",
            kind="single",
            folder=str(folder),
            video=str(folder / video_name),
            proposed_title="Titre Auto",
            proposed_year=1999,
            proposed_source="tmdb",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title="Titre Auto", year=1999, source="tmdb", tmdb_id=111, score=0.9)],
        )

    def _execute(self, rows: List[core.PlanRow]) -> Dict[str, Any]:
        """`_execute_apply` en dry_run avec le VRAI `apply_core.apply_rows`.

        Seuls deux voisins sont neutralises, et aucun ne touche a l'override :
        `find_duplicate_targets` (scan disque des collisions) et
        `migrate_legacy_deletion_marks` (qui exige un objet api complet).
        """
        logs: List[tuple] = []
        with (
            patch.object(apply_support._plan_support_mod, "find_duplicate_targets", return_value=None),
            patch.object(library_actions_support, "migrate_legacy_deletion_marks", return_value=[]),
        ):
            result, _batch_id, _ops = apply_support._execute_apply(
                core.Config(root=self.root),
                rows,
                {"f1": {"ok": True}},
                {"f1"},
                dry_run=True,
                quarantine_unapproved=False,
                log_fn=lambda lvl, msg: logs.append((lvl, msg)),
                run_paths=_run_paths(self.state_dir),
                store=self.store,
                api=SimpleNamespace(_app_version="test"),
                run_id=RUN_ID,
                batch_state=[None, 0],
            )
        return {"logs": logs, "result": result}

    def _seed_override(self, *, tmdb_id: int, title: str, year: int) -> None:
        self.store.film_modal.upsert_tmdb_override(
            run_id=RUN_ID,
            row_id="f1",
            tmdb_id=tmdb_id,
            new_confidence=95,
            proposed_title=title,
            proposed_year=year,
        )

    def test_the_override_title_and_year_reach_the_folder_name(self) -> None:
        """Non-regression du coeur de R7-3 : l'overlay doit rester EFFECTIF.

        C'est la moitie vivante du bloc ; le correctif #805 ne retire que
        l'ecriture morte, il ne doit pas emporter celle-ci.
        """
        src = self._movie("Titre.Auto.1999.BluRay", "Titre.Auto.1999.BluRay.mkv")
        self._seed_override(tmdb_id=438631, title="Le Titre Choisi", year=2021)

        out = self._execute([self._row(src, "Titre.Auto.1999.BluRay.mkv")])

        renames = [msg for lvl, msg in out["logs"] if msg.startswith("RENAME:")]
        self.assertEqual(len(renames), 1, f"une seule ligne RENAME attendue, logs={out['logs']}")
        self.assertTrue(
            renames[0].endswith("Le Titre Choisi (2021)"),
            f"le dossier doit porter le choix manuel de l'utilisateur. Vu : {renames[0]!r}",
        )

    def test_the_overlay_creates_no_field_that_planrow_does_not_declare(self) -> None:
        """#805 : `_r.tmdb_id = ...` etait une ecriture morte.

        L'override porte un `tmdb_id` > 0, donc la ligne supprimee AURAIT tire :
        ce n'est pas un mutant equivalent. Remettre la ligne fait rougir ici.
        """
        src = self._movie("Titre.Auto.1999.BluRay", "Titre.Auto.1999.BluRay.mkv")
        self._seed_override(tmdb_id=438631, title="Le Titre Choisi", year=2021)
        row = self._row(src, "Titre.Auto.1999.BluRay.mkv")

        self._execute([row])

        self.assertNotIn(
            "tmdb_id",
            vars(row),
            "l'overlay d'apply a pose un attribut hors du schema PlanRow : il sera "
            "jete par asdict() et aucun consommateur ne le lira. L'identite d'une "
            "PlanRow vit sur ses `candidates`.",
        )
        self.assertNotIn("tmdb_id", asdict(row), "asdict() ne retient que les champs declares")

    def test_the_identity_of_the_override_never_silently_renames(self) -> None:
        """Un override qui ne change QUE l'identite ne bouge aucun dossier.

        Sur un remake au titre et a l'annee identiques, le nom de destination
        derive de proposed_title/proposed_year : il est inchange. C'est la
        raison pour laquelle propager le `tmdb_id` sur la PlanRow n'aurait rien
        rendu de plus a l'utilisateur — et l'issue #805 surestimait l'impact.
        """
        src = self._movie("Le Titre Choisi (2021)", "Le Titre Choisi (2021).mkv")
        self._seed_override(tmdb_id=999999, title="Le Titre Choisi", year=2021)
        row = self._row(src, "Le Titre Choisi (2021).mkv")
        row.proposed_title = "Le Titre Choisi"
        row.proposed_year = 2021

        out = self._execute([row])

        self.assertEqual(out["result"].renames, 0)
        self.assertEqual([msg for lvl, msg in out["logs"] if msg.startswith("RENAME:")], [])


# ---------------------------------------------------------------------------
# #699 — la ligne « Resolution » des cartes A/B de l'ecran Doublons
# ---------------------------------------------------------------------------


class DuplicateCardResolutionTests(unittest.TestCase):
    """#699 : la carte doit dire sur quoi le comparateur a tranche."""

    def _detected(self, *, width: int, height: int) -> Dict[str, Any]:
        """`metrics.detected` tel que `compute_quality_score` le PERSISTE.

        On part du producteur reel : fabriquer le dict a la main laisserait
        passer une divergence de cles entre le scoring et le pseudo-probe.
        """
        probe: Dict[str, Any] = {
            "video": {"width": width, "height": height, "codec": "hevc", "bitrate": 55_000_000},
            "audio_tracks": [{"codec": "dts-hd ma", "channels": 6}],
            "duration_s": 7200,
        }
        metrics = compute_quality_score(
            normalized_probe=probe,
            profile=default_quality_profile(),
            folder_name="Film sans indice de resolution dans le nom",
        )["metrics"]
        return metrics["detected"]

    def test_a_probe_with_both_dimensions_still_shows_the_geometry(self) -> None:
        """NON-REGRESSION : le chemin nominal (PR#854) reste `WxH`, plus precis."""
        detected = self._detected(width=3840, height=1600)
        self.assertEqual(detected["resolution_source"], "probe")
        info = _quality_info_for_row(None, RUN_ID, {"row_id": ""}, _build_pseudo_probe(detected))
        self.assertEqual(info.get("resolution"), "3840x1600")

    def test_a_measured_class_without_width_falls_back_on_the_canonical_label(self) -> None:
        """Largeur manquante (probe partiel) : la classe MESUREE reste affichee.

        `classify_resolution` tranche sur la largeur et n'utilise la hauteur
        que « comme filet quand la largeur manque » — cas donc prevu par le
        domaine. Le comparateur classe alors le fichier 2160p ; sans ce repli
        la carte n'affichait rien du critere qui a decide du verdict.
        """
        detected = self._detected(width=0, height=2160)
        self.assertEqual(detected["width"], 0, "pre-requis du scenario : largeur absente")
        self.assertEqual(detected["resolution_source"], "probe", "la classe doit bien etre MESUREE")

        probe = _build_pseudo_probe(detected)
        info = _quality_info_for_row(None, RUN_ID, {"row_id": ""}, probe)
        self.assertEqual(info.get("resolution"), "2160p")

    def test_a_name_derived_class_is_never_displayed_as_a_measurement(self) -> None:
        """Garde anti-fabrication : sans mesure, la carte reste muette.

        `_build_pseudo_probe` ne propage l'etiquette que si
        `resolution_source == "probe"`. Un repli sur `f"{height}p"` aurait ecrit
        « 1600p » pour un UHD scope, et un repli sur l'etiquette non mesuree
        aurait laisse le NOM de release decider a la place de ffprobe.
        """
        detected = self._detected(width=0, height=0)
        detected["resolution"] = "1080p"
        detected["resolution_source"] = "name_fallback"

        info = _quality_info_for_row(None, RUN_ID, {"row_id": ""}, _build_pseudo_probe(detected))
        self.assertIsNone(info.get("resolution"))


# ---------------------------------------------------------------------------
# #472 — les compteurs premium / low
# ---------------------------------------------------------------------------

# Score choisi POUR CHAQUE BANDE en fonction du profil par defaut recalibre
# (Platinum 70 / Gold 66 / Silver 55 / Bronze 40). Le cas discriminant est
# `platinum_sous_l_ancien_seuil` : tier Platinum, mais score < 85, donc invisible
# du compteur tant qu'il s'appuyait sur le fossile `score >= 85`.
_FILMS: Dict[str, int] = {
    "platinum_franc": 92,
    "platinum_sous_l_ancien_seuil": 75,
    "gold": 67,
    "silver": 60,
    "bronze": 45,
    "reject": 20,
}


class QualityCountsFollowTheTierTests(unittest.TestCase):
    """#472 : les agregats doivent dire la meme chose que le tier affiche."""

    def _declare_run(self, run_id: str) -> None:
        """`quality_reports.run_id` porte une FK vers `runs` (migration 021)."""
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(Path(self._tmp) / "root"),
            state_dir=str(Path(self._tmp) / "state"),
            config={},
            created_ts=time.time(),
        )

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_472_")
        self.store = SQLiteStore(Path(self._tmp) / "cinesort.sqlite")
        self.store.initialize()
        self._declare_run(RUN_ID)
        self.profile = default_quality_profile()
        self.tiers: Dict[str, str] = {}
        for row_id, score in _FILMS.items():
            tier = determine_tier(score, self.profile.get("tiers"))
            self.tiers[row_id] = tier
            self.store.quality.upsert_quality_report(
                run_id=RUN_ID,
                row_id=row_id,
                score=score,
                tier=tier,
                reasons=[],
                metrics={},
                profile_id=str(self.profile.get("id") or "CinemaLux_v1"),
                profile_version=int(self.profile.get("version") or 1),
            )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_the_fixture_really_contains_the_discriminating_case(self) -> None:
        """Garde-fou du garde-fou : sans ce film, les deux formules coincident."""
        self.assertEqual(self.tiers["platinum_sous_l_ancien_seuil"], "Platinum")
        self.assertLess(_FILMS["platinum_sous_l_ancien_seuil"], 85)

    def test_premium_count_matches_the_tiers_actually_persisted(self) -> None:
        counts = self.store.quality.get_quality_counts_for_runs([RUN_ID])[RUN_ID]
        expected = sum(1 for tier in self.tiers.values() if is_premium_tier(tier))
        self.assertEqual(expected, 3, "Platinum x2 + Gold x1 attendus dans la fixture")
        self.assertEqual(
            counts["premium_count"],
            expected,
            "le KPI premium doit compter les films dont le TIER est premium ; "
            "avec le fossile `score >= 85` il n'en voyait qu'un seul",
        )

    def test_low_count_matches_the_tiers_actually_persisted(self) -> None:
        counts = self.store.quality.get_quality_counts_for_runs([RUN_ID])[RUN_ID]
        expected = sum(1 for tier in self.tiers.values() if tier in ("Bronze", "Reject"))
        self.assertEqual(counts["low_count"], expected)

    def test_a_stricter_profile_no_longer_desynchronises_the_counters(self) -> None:
        """`remux_strict` (90/76/60/40) : c'est la que les seuils fossiles mentent.

        Un film a 80 y est Silver — ni premium, ni low. Le fossile `score >= 85`
        le laissait deja dehors du premium, mais un film a 88 y est Gold alors
        que 88 < 90 : il etait compte premium par l'ancien seuil de score...
        pour le mauvais motif. On verifie l'invariant, pas la coincidence :
        compteur == comptage direct des tiers persistes.
        """
        run_strict = f"{RUN_ID}_strict"
        self._declare_run(run_strict)
        strict_tiers = {"platinum": 90, "gold": 76, "silver": 60, "bronze": 40}
        persisted: Dict[str, str] = {}
        for row_id, score in {"a": 95, "b": 88, "c": 80, "d": 57, "e": 30}.items():
            tier = determine_tier(score, strict_tiers)
            persisted[row_id] = tier
            self.store.quality.upsert_quality_report(
                run_id=run_strict,
                row_id=row_id,
                score=score,
                tier=tier,
                reasons=[],
                metrics={},
                profile_id="CinemaLux_RemuxStrict_v1",
                profile_version=1,
            )

        counts = self.store.quality.get_quality_counts_for_runs([run_strict])[run_strict]
        self.assertEqual(counts["premium_count"], sum(1 for t in persisted.values() if is_premium_tier(t)))
        self.assertEqual(counts["low_count"], sum(1 for t in persisted.values() if t in ("Bronze", "Reject")))
        # Le film a 57 est BRONZE sous ce profil (silver=60) alors que le
        # fossile `score < 55` ne le comptait pas comme low.
        self.assertEqual(persisted["d"], "Bronze")
        self.assertEqual(counts["low_count"], 2)

    def test_legacy_tier_labels_are_not_silently_dropped(self) -> None:
        """Une base ou la migration 011 n'aurait pas tourne garde ses films.

        `Premium`/`Bon` -> premium, `Faible`/`Mauvais` -> low. Sans les alias,
        ces lignes disparaitraient des DEUX compteurs sans le moindre signal.
        """
        run_legacy = f"{RUN_ID}_legacy"
        self._declare_run(run_legacy)
        for row_id, (score, tier) in {
            "a": (95, "Premium"),
            "b": (70, "Bon"),
            "c": (30, "Faible"),
            "d": (10, "Mauvais"),
        }.items():
            self.store.quality.upsert_quality_report(
                run_id=run_legacy,
                row_id=row_id,
                score=score,
                tier=tier,
                reasons=[],
                metrics={},
                profile_id="legacy",
                profile_version=1,
            )
        counts = self.store.quality.get_quality_counts_for_runs([run_legacy])[run_legacy]
        self.assertEqual(counts["premium_count"], 2)
        self.assertEqual(counts["low_count"], 2)

    def test_a_run_without_any_report_is_absent_from_the_result(self) -> None:
        """Contrat documente : `GROUP BY` ne produit pas de ligne vide."""
        out = self.store.quality.get_quality_counts_for_runs([RUN_ID, "run_sans_rapport"])
        self.assertIn(RUN_ID, out)
        self.assertNotIn("run_sans_rapport", out)
        self.assertEqual(self.store.quality.get_quality_counts_for_runs([]), {})


class DashboardPremiumPctAgreesWithTheRepositoryTests(unittest.TestCase):
    """#472 : les DEUX definitions du KPI premium doivent coincider.

    `score_premium_pct` (stats d'un run, dashboard_support) et `premium_count`
    (SQL, quality repository) portaient le meme litteral fossile 85 chacun de
    leur cote. Ce test les confronte sur les MEMES rapports.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_472_dash_")
        self.tmp = Path(self._tmp)
        self.root = self.tmp / "root"
        self.state_dir = self.tmp / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)
        self.profile = default_quality_profile()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plan_row(self, rid: str) -> Dict[str, Any]:
        return {
            "row_id": rid,
            "kind": "single",
            "folder": str(self.root / rid),
            "video": str(self.root / rid / f"{rid}.mkv"),
            "proposed_title": rid,
            "proposed_year": 2020,
            "proposed_source": "name",
            "confidence": 70,
            "confidence_label": "med",
            "candidates": [],
            "notes": "",
        }

    def _seed(self, run_id: str) -> Optional[Dict[str, Any]]:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        rows = [self._plan_row(rid) for rid in _FILMS]
        (run_dir / "plan.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        ts = time.time()
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=ts - 1,
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)
        self.store.run.mark_run_done(run_id, stats={"planned_rows": len(rows)}, ended_ts=ts + 5)
        for rid, score in _FILMS.items():
            self.store.quality.upsert_quality_report(
                run_id=run_id,
                row_id=rid,
                score=score,
                tier=determine_tier(score, self.profile.get("tiers")),
                reasons=[],
                metrics={},
                profile_id=str(self.profile.get("id") or "CinemaLux_v1"),
                profile_version=int(self.profile.get("version") or 1),
            )
        run_row, _store = self.api._find_run_row(run_id)
        return run_row

    def test_both_kpi_producers_agree_on_the_same_reports(self) -> None:
        run_id = "20260805_dash_premium"
        run_row = self._seed(run_id)
        self.assertIsNotNone(run_row, "run introuvable — harnais casse")
        run_paths = self.api._run_paths_for(self.state_dir, run_id, ensure_exists=False)
        rows = self.api._load_rows_from_plan_jsonl(run_paths)
        self.assertEqual(len(rows), len(_FILMS), "harnais casse : plan.jsonl non relu")

        section = dashboard_support._build_dashboard_section(
            self.api,
            run_id=run_id,
            run_row=run_row,
            run_paths=run_paths,
            store=self.store,
            rows=rows,
        )
        repo_counts = self.store.quality.get_quality_counts_for_runs([run_id])[run_id]
        expected_pct = round(repo_counts["premium_count"] * 100.0 / len(_FILMS), 1)

        self.assertEqual(repo_counts["premium_count"], 3)
        self.assertEqual(
            section["kpis"]["score_premium_pct"],
            expected_pct,
            "les deux producteurs du KPI premium doivent repondre la meme chose sur les memes rapports qualite",
        )


if __name__ == "__main__":
    unittest.main()
