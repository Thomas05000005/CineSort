# -*- coding: utf-8 -*-
"""Lot D (verif totale 2026-07) — Chaine 4.4 QUALITE/SCORING bout-en-bout.

Chaine metier verifiee sur une bibliotheque VIRTUELLE JETABLE (tempdir,
fichiers .mkv factices de quelques Ko, AUCUN chemin hors tempdir, aucun
port reseau) :

    api.run.start_plan (scan) -> plan rows
      -> api.quality.get_quality_report (ProbeService probe_backend='none'
         -> probe_quality=FAILED -> fallback release_name_parser)
      -> compute_quality_score (subscores + compensation nom + cap Silver)
      -> tiers_helpers.determine_tier / cap_tier (seuils defaults 70/66/55/40)
      -> store.quality.upsert_quality_report (SQLite du state_dir tempdir)
      -> custom_rules crees via api.quality.save_quality_profile (API cablee)
      -> api.run.get_global_stats -> tier_distribution canonique (lowercase)

LIMITES (documentees, PAS simulees) :
  - ffprobe / mediainfo / ffmpeg absents de l'environnement de test :
    probe_backend='none' est force, donc les branches probe FULL/PARTIAL
    (bitrate mesure, HDR probe, upscale/4K-light sur donnees mesurees) et
    tout le pipeline perceptuel V2 (composite_score_v2, extraction frames)
    ne sont PAS exercables ici. Le scoring teste est le fallback nom-de-
    release, qui est precisement le chemin de prod sans binaires.
  - Seuils BLUR_* non touches (R8-096 differe).

BUGS APP CONSTATES le 2026-07-08 (REPORTES, pas corriges — les tests
concernes font pytest.xfail() nominatif tant que le bug est present et
redeviendront passants d'eux-memes une fois corrige) :

  [BUG-TITLE-CHANNEL-RESIDUE] (collateral chaine titres, constate pendant le
      scan de cette chaine) : parse_scene_title laisse un residu de canaux
      audio dans proposed_title quand les canaux precedent le release group
      colle — pattern scene ultra-courant "...TrueHD.Atmos.7.1-GRP" ->
      "Interstellar 2014 7" (idem "5.1-GRP" -> "... 5", "2.0-GRP" -> "... 2").
      Cause : pipeline scene_parser.parse_scene_title strip le residu audio
      "7 1" (etape 4) AVANT le strip du release group "-GRP$" (etape 6) ; or
      apres separation des points le token est "7 1-GRP", qui ne matche pas
      le residu, et apres strip du groupe le residu n'est pas re-applique.
      Adjacent au finding AUDIT_RELECTURE_2026-06-10 sur _RELEASE_GROUP_RE.

  [BUG-EXPLAIN-BASELINE-CAP] (CORRIGE 2026-07-08, vague Lot D : baseline
      raisonne desormais depuis le tier affiche ; garde xfail redevenue
      passante) explain_score._compute_baseline calculait
      next_tier/distance_to_next_tier depuis le SCORE seulement et ignore le
      cap de tier securite (probe FAILED -> Silver max) : un film cape Silver
      avec score 74 (>= seuil Platinum 70) affiche next_tier=null /
      distance=null ("aucun tier superieur") alors que le tier affiche est
      Silver — l'explication est incoherente avec le tier montre a l'user.

Lancer :
  "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/test_lotd_chain_scoring.py -q
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest

import cinesort.domain.core as core
from cinesort.domain import tiers_helpers as th
from cinesort.domain.quality_score import compute_quality_score, default_quality_profile
from cinesort.domain.title_helpers import clean_title_guess
from cinesort.ui.api.cinesort_api import CineSortApi

# ---------------------------------------------------------------------------
# Bibliotheque virtuelle : 3 releases scene deterministes (nom-seul).
# ---------------------------------------------------------------------------

_NAMES = {
    # 2160p REMUX HDR10 x265 TrueHD Atmos 7.1 : haut de gamme nom-seul
    "uhd": "Interstellar.2014.2160p.UHD.BluRay.REMUX.HDR10.x265.TrueHD.Atmos.7.1-LOTD",
    # 1080p BluRay x264 DTS 5.1 : milieu de gamme
    "fhd": "The.Matrix.1999.1080p.BluRay.x264.DTS.5.1-LOTD",
    # 720p HDTV XviD AC3 2.0 : bas de gamme
    "hd": "Old.Boy.2003.720p.HDTV.XviD.AC3.2.0-LOTD",
}

_CANONICAL_TIERS_V1 = {"Platinum", "Gold", "Silver", "Bronze", "Reject"}
_CANONICAL_TIERS_V2 = {"platinum", "gold", "silver", "bronze", "reject"}
_DEFAULT_THRESHOLDS = {"platinum": 70, "gold": 66, "silver": 55, "bronze": 40}

_RULE_ID = "lotd_uhd_bonus"
_RULE_DELTA = 5


def _wait_done(api: CineSortApi, run_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        last = api.run.get_status(run_id, 0) or {}
        if last.get("done"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"Timeout {timeout_s}s en attendant run_id={run_id}. Dernier status={last}")


@pytest.fixture(scope="module")
def chain() -> Dict[str, Any]:
    """Joue la chaine 4.4 UNE fois (module scope) et capture tous les etats.

    Tout est jetable : tempdir mkdtemp + rmtree(ignore_errors) en teardown
    (le store SQLite peut garder un handle sous Windows). Aucun port, aucun
    binaire externe, probe_backend='none' partout.
    """
    tmp = tempfile.mkdtemp(prefix="cinesort_lotd_scoring_")
    tmp_path = Path(tmp)
    root = tmp_path / "root"
    state_dir = tmp_path / "state"
    root.mkdir()
    state_dir.mkdir()

    # Mini fichiers factices : .mkv (magic EBML + padding), .srt sidecar.
    for folder in _NAMES.values():
        d = root / folder
        d.mkdir()
        (d / f"{folder}.mkv").write_bytes(b"\x1aE\xdf\xa3" + b"x" * 4096)
        (d / f"{folder}.fr.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nBonjour\n", encoding="utf-8")

    patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
    patcher.start()
    data: Dict[str, Any] = {}
    try:
        api = CineSortApi()
        saved_settings = api.settings.save_settings(
            {
                "root": str(root),
                "state_dir": str(state_dir),
                "tmdb_enabled": False,
                "probe_backend": "none",
                "rest_api_enabled": False,
                "watch_enabled": False,
                "plugins_enabled": False,
                "perceptual_enabled": False,
                "jellyfin_enabled": False,
                "plex_enabled": False,
            }
        )
        assert saved_settings.get("ok"), f"save_settings KO: {saved_settings}"
        effective = api.settings.get_settings()
        # Garde-fou memoire 'biblio virtuelle jetable' : le state_dir effectif
        # DOIT etre le tempdir (aucune ecriture hors tempdir ensuite).
        assert str(state_dir) in str(effective.get("state_dir")), effective.get("state_dir")

        start = api.run.start_plan(
            {
                "root": str(root),
                "state_dir": str(state_dir),
                "tmdb_enabled": False,
                "probe_backend": "none",
            }
        )
        assert start.get("ok"), f"start_plan KO: {start}"
        run_id = start["run_id"]
        status = _wait_done(api, run_id)
        assert status.get("error") is None, status

        plan = api.run.get_plan(run_id)
        assert plan.get("ok"), plan
        rows = plan.get("rows", [])
        by_key: Dict[str, dict] = {}
        for row in rows:
            video = str(row.get("video") or "")
            for key, name in _NAMES.items():
                if name in video:
                    by_key[key] = row

        # --- Scoring nom-seul (probe none -> FAILED -> release_name_parser) ---
        reports: Dict[str, dict] = {}
        for key, row in by_key.items():
            reports[key] = api.quality.get_quality_report(run_id, row["row_id"])

        stats_before_rule = api.run.get_global_stats()

        # --- Custom rule simple creee via l'API (chemin cable save_quality_profile) ---
        prof_res = api.quality.get_quality_profile()
        profile = dict(prof_res.get("profile_json") or {})
        profile["custom_rules"] = [
            {
                "id": _RULE_ID,
                "name": "LotD bonus UHD",
                "priority": 1,
                "enabled": True,
                "match": "all",
                "conditions": [{"field": "resolution", "op": "=", "value": "2160p"}],
                "action": {"type": "score_delta", "value": _RULE_DELTA, "reason": "Bonus UHD LotD"},
            }
        ]
        rule_saved = api.quality.save_quality_profile(profile)

        reports_after_rule = {
            "uhd": api.quality.get_quality_report(run_id, by_key["uhd"]["row_id"]),
            "hd": api.quality.get_quality_report(run_id, by_key["hd"]["row_id"]),
        }
        stats_after_rule = api.run.get_global_stats()

        data.update(
            {
                "rows": rows,
                "by_key": by_key,
                "run_id": run_id,
                "profile_res": prof_res,
                "rule_saved": rule_saved,
                "reports": reports,
                "reports_after_rule": reports_after_rule,
                "stats_before_rule": stats_before_rule,
                "stats_after_rule": stats_after_rule,
            }
        )
        yield data
    finally:
        patcher.stop()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. Scan -> plan
# ---------------------------------------------------------------------------


class TestScanToPlan:
    def test_plan_contient_les_3_releases(self, chain):
        assert len(chain["rows"]) == 3, chain["rows"]
        assert set(chain["by_key"].keys()) == {"uhd", "fhd", "hd"}


# ---------------------------------------------------------------------------
# 2. Scoring nom-seul via l'API (probe degradee proprement, pas de binaire)
# ---------------------------------------------------------------------------


class TestScoringNameFallback:
    def test_rapports_ok_et_fallback_nom_actif(self, chain):
        """Sans binaires (probe_backend=none) : probe FAILED, specs deduites du nom."""
        for key, rep in chain["reports"].items():
            assert rep.get("ok"), f"[{key}] rapport KO: {rep}"
            score = rep.get("score")
            assert isinstance(score, int) and 0 <= score <= 100, f"[{key}] score={score!r}"
            assert rep.get("probe_quality") == "FAILED", f"[{key}] {rep.get('probe_quality')}"
            metrics = rep.get("metrics") or {}
            assert metrics.get("engine_version") == "CinemaLux_v1", metrics.get("engine_version")
            reasons = rep.get("reasons") or []
            assert any("Specs deduites du nom" in r for r in reasons), (
                f"[{key}] fallback release_name_parser non trace dans reasons: {reasons[:6]}"
            )

    def test_scores_monotones_par_resolution(self, chain):
        """Coherence nom-seul : 2160p REMUX > 1080p BluRay > 720p HDTV."""
        s = {k: int(chain["reports"][k]["score"]) for k in ("uhd", "fhd", "hd")}
        assert s["uhd"] > s["hd"], f"2160p ({s['uhd']}) doit battre 720p ({s['hd']})"
        assert s["uhd"] > s["fhd"] > s["hd"], f"ordre attendu uhd > fhd > hd, obtenu {s}"

    def test_tier_coherent_avec_determine_tier_et_cap_failed(self, chain):
        """tier API == tiers_helpers.determine_tier(score) plafonne Silver (probe FAILED)."""
        for key, rep in chain["reports"].items():
            score = int(rep["score"])
            raw_tier = th.determine_tier(score)
            expected = th.cap_tier(raw_tier, "Silver") if rep.get("probe_quality") == "FAILED" else raw_tier
            assert rep.get("tier") == expected, (
                f"[{key}] score={score} determine_tier={raw_tier} attendu={expected} obtenu={rep.get('tier')}"
            )
            assert rep.get("tier") in _CANONICAL_TIERS_V1, rep.get("tier")


# ---------------------------------------------------------------------------
# 3. Domaine pur : compute_quality_score sans probe du tout (pas de cap)
# ---------------------------------------------------------------------------


class TestDomainScoringNoProbe:
    def test_probe_absent_unknown_tier_non_cape(self):
        """probe={} -> probe_quality=UNKNOWN (permissif) : tier == determine_tier(score)."""
        prof = default_quality_profile()
        scores = {}
        for key, name in _NAMES.items():
            res = compute_quality_score(
                normalized_probe={},
                profile=prof,
                folder_name=name,
                release_name=f"{name}.mkv",
            )
            scores[key] = int(res["score"])
            assert res["metrics"].get("probe_quality") == "UNKNOWN", res["metrics"].get("probe_quality")
            assert res["tier"] == th.determine_tier(res["score"]), (
                f"[{key}] tier {res['tier']} != determine_tier({res['score']})="
                f"{th.determine_tier(res['score'])} (aucun cap attendu en UNKNOWN)"
            )
        assert scores["uhd"] > scores["hd"], f"2160p > 720p attendu aussi en domaine pur: {scores}"


# ---------------------------------------------------------------------------
# 4. tiers_helpers : normalize_tiers + determine_tier (seuils defaults)
# ---------------------------------------------------------------------------


class TestTiersHelpers:
    def test_normalize_tiers_defaults_et_legacy(self):
        assert th.normalize_tiers({}) == _DEFAULT_THRESHOLDS
        assert th.normalize_tiers(None) == _DEFAULT_THRESHOLDS
        # Alias legacy pre-v1.5.5
        assert th.normalize_tiers({"premium": 85, "bon": 70, "moyen": 50, "faible": 30}) == {
            "platinum": 85,
            "gold": 70,
            "silver": 50,
            "bronze": 30,
        }
        # Clamp [0,100] + coercion : valeurs hors bornes / non numeriques
        out = th.normalize_tiers({"platinum": 150, "gold": -5, "silver": "abc", "bronze": "41"})
        assert out == {"platinum": 100, "gold": 0, "silver": 55, "bronze": 41}, out

    def test_determine_tier_bornes_defaults(self):
        expected = [
            (100, "Platinum"),
            (70, "Platinum"),
            (69, "Gold"),
            (66, "Gold"),
            (65, "Silver"),
            (55, "Silver"),
            (54, "Bronze"),
            (40, "Bronze"),
            (39, "Reject"),
            (0, "Reject"),
        ]
        got = [(s, th.determine_tier(s)) for s, _ in expected]
        assert got == expected, got
        # Entree ininterpretable -> Reject (safe default)
        assert th.determine_tier("abc") == "Reject"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. explain_score : coherence explication <-> score
# ---------------------------------------------------------------------------


class TestExplainScore:
    def test_narrative_et_seuils_coherents(self, chain):
        for key, rep in chain["reports"].items():
            expl = rep.get("explanation") or {}
            score, tier = int(rep["score"]), str(rep["tier"])
            narrative = str(expl.get("narrative") or "")
            assert narrative.startswith(f"Score {score}/100 ({tier})."), (
                f"[{key}] narrative incoherente avec score/tier: {narrative[:80]!r}"
            )
            baseline = expl.get("baseline") or {}
            assert baseline.get("tier_thresholds") == {
                "Platinum": 70,
                "Gold": 66,
                "Silver": 55,
                "Bronze": 40,
            }, f"[{key}] seuils baseline non canoniques: {baseline.get('tier_thresholds')}"

    def test_distance_au_tier_suivant_coherente_avec_le_tier_affiche(self, chain):
        """Contrat post-fix BUG-EXPLAIN-BASELINE-CAP : next_tier = tier
        immediatement au-dessus du tier AFFICHE (cape inclus) ; distance =
        max(0, seuil(next) - score). Avant : contrat score-seul, incoherent
        des que le cap Silver (probe FAILED) abaissait le tier."""
        order = ["Reject", "Bronze", "Silver", "Gold", "Platinum"]
        thresholds = {"Reject": 0, "Bronze": 40, "Silver": 55, "Gold": 66, "Platinum": 70}
        for key, rep in chain["reports"].items():
            score, tier = int(rep["score"]), str(rep["tier"])
            baseline = (rep.get("explanation") or {}).get("baseline") or {}
            idx = order.index(tier)
            expected_next = order[idx + 1] if idx + 1 < len(order) else None
            assert baseline.get("next_tier") == expected_next, (
                f"[{key}] score={score} tier={tier} next_tier attendu={expected_next} "
                f"obtenu={baseline.get('next_tier')}"
            )
            if expected_next is not None:
                expected_dist = max(0, thresholds[expected_next] - score)
                assert baseline.get("distance_to_next_tier") == expected_dist, baseline

    def test_baseline_vs_tier_cape_guard(self, chain):
        """Garde xfail nominative [BUG-EXPLAIN-BASELINE-CAP].

        Le film uhd est cape Silver (probe FAILED) avec un score >= seuil
        Platinum : l'explication devrait proposer une progression coherente
        avec le tier AFFICHE (Silver), pas conclure "aucun tier superieur".
        """
        rep = chain["reports"]["uhd"]
        score, tier = int(rep["score"]), str(rep["tier"])
        if not (tier == "Silver" and score >= 70):
            pytest.skip(
                f"Precondition non reunie (score={score}, tier={tier}) : "
                "le scenario cap-Silver-avec-score-Platinum ne s'est pas produit."
            )
        baseline = (rep.get("explanation") or {}).get("baseline") or {}
        if baseline.get("next_tier") is None:
            pytest.xfail(
                "[BUG-EXPLAIN-BASELINE-CAP] tier affiche Silver (cap probe FAILED) mais "
                f"baseline.next_tier=null / distance=null pour score={score} : "
                "explain_score._compute_baseline ignore le cap et raisonne sur le "
                "score seul -> explication incoherente avec le tier montre."
            )
        assert baseline.get("next_tier") in ("Gold", "Platinum"), baseline


# ---------------------------------------------------------------------------
# 6. Custom rules creees via l'API (save_quality_profile -> scoring)
# ---------------------------------------------------------------------------


class TestCustomRulesViaApi:
    def test_sauvegarde_profil_avec_regle_ok(self, chain):
        assert chain["rule_saved"].get("ok"), chain["rule_saved"]

    def test_regle_appliquee_sur_2160p(self, chain):
        before = int(chain["reports"]["uhd"]["score"])
        after_rep = chain["reports_after_rule"]["uhd"]
        after = int(after_rep["score"])
        assert after == min(100, before + _RULE_DELTA), f"score_delta +{_RULE_DELTA} attendu: {before} -> {after}"
        metrics = after_rep.get("metrics") or {}
        assert metrics.get("applied_rule_ids") == [_RULE_ID], metrics.get("applied_rule_ids")
        assert any("Bonus UHD LotD" in r for r in (after_rep.get("reasons") or []))
        # Le tier reste coherent : redetermine puis cap Silver (probe FAILED).
        expected_tier = th.cap_tier(th.determine_tier(after), "Silver")
        assert after_rep.get("tier") == expected_tier, (after_rep.get("tier"), expected_tier)

    def test_regle_non_appliquee_sur_720p(self, chain):
        before = int(chain["reports"]["hd"]["score"])
        after_rep = chain["reports_after_rule"]["hd"]
        assert int(after_rep["score"]) == before, (before, after_rep["score"])
        assert (after_rep.get("metrics") or {}).get("applied_rule_ids") == []


# ---------------------------------------------------------------------------
# 7. get_global_stats : distribution de tiers canonique
# ---------------------------------------------------------------------------


class TestGlobalStats:
    @pytest.mark.parametrize("stats_key", ["stats_before_rule", "stats_after_rule"])
    def test_tier_distribution_canonique(self, chain, stats_key):
        stats = chain[stats_key]
        assert stats.get("ok"), stats
        dist = stats.get("tier_distribution") or {}
        assert dist, f"tier_distribution vide: {stats}"
        rogue = set(dist) - _CANONICAL_TIERS_V2
        assert not rogue, (
            f"cles non canoniques dans tier_distribution ({stats_key}): {rogue} — "
            f"attendu sous-ensemble de {_CANONICAL_TIERS_V2}, obtenu {dist}"
        )
        assert sum(dist.values()) == stats.get("total_scored") == 3, (dist, stats.get("total_scored"))

    def test_distribution_reflete_les_tiers_stockes(self, chain):
        """La distribution finale correspond aux tiers persistes (upsert final)."""
        final_tiers = {
            "uhd": chain["reports_after_rule"]["uhd"]["tier"],
            "fhd": chain["reports"]["fhd"]["tier"],
            "hd": chain["reports_after_rule"]["hd"]["tier"],
        }
        expected = Counter(str(t).lower() for t in final_tiers.values())
        dist = chain["stats_after_rule"].get("tier_distribution") or {}
        assert dist == dict(expected), (dist, dict(expected))

    def test_summary_kpis_du_dernier_run(self, chain):
        summary = chain["stats_after_rule"].get("summary") or {}
        assert summary.get("total_films") == 3, summary
        assert summary.get("unscored_films") == 0, summary


# ---------------------------------------------------------------------------
# 8. Collateral constate pendant le scan : residu de canaux dans le titre
# ---------------------------------------------------------------------------


class TestCollateralTitleResidue:
    @pytest.mark.parametrize(
        "release,expected_clean",
        [
            (
                "Interstellar.2014.2160p.UHD.BluRay.REMUX.HDR10.x265.TrueHD.Atmos.7.1-LOTD",
                "Interstellar 2014",
            ),
            ("The.Matrix.1999.1080p.BluRay.x264.DTS.5.1-LOTD", "The Matrix 1999"),
            ("Old.Boy.2003.720p.HDTV.XviD.AC3.2.0-LOTD", "Old Boy 2003"),
        ],
    )
    def test_channel_residue_guard(self, release, expected_clean):
        """Garde xfail nominative [BUG-TITLE-CHANNEL-RESIDUE].

        NB : l'annee reste dans le titre PAR DESIGN (docstring parse_scene_title,
        films-annee type '2001', 'Blade Runner 2049'). Seul le residu de canaux
        final ('7'/'5'/'2' issus de 7.1/5.1/2.0 colles au groupe) est un bug.
        """
        got = clean_title_guess(release)
        if re.search(r"\b[2579]$", got) and got != expected_clean:
            pytest.xfail(
                f"[BUG-TITLE-CHANNEL-RESIDUE] {release!r} -> {got!r} : residu de canaux "
                "audio dans proposed_title (strip residu audio AVANT strip release "
                f"group dans parse_scene_title). Attendu {expected_clean!r}."
            )
        assert got == expected_clean, f"{release!r} -> {got!r}, attendu {expected_clean!r}"
