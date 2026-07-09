"""LOT D (verif totale 2026-07) — chaine 4.1 SCAN -> PLAN bout-en-bout.

Bibliotheque VIRTUELLE JETABLE (tempfile.mkdtemp + fichiers factices), pilotage
CineSortApi direct (pattern tests/test_backend_flow.py), AUCUN binaire externe
(tmdb_enabled=False, omdb_enabled=False, probe_backend="none", perceptuel OFF).

Scenario unique (2 scans consecutifs sur la meme biblio, fixture module) :

  ROOT A                                   ROOT B
  ------                                   ------
  Inception (2010)/  .mkv + .nfo(tmdbid)   Film (2020)/film.mkv   <- collision cross-root
                     + .fr.srt             Show/Show.101..103.mkv <- R8-079 (TV non-standard)
  Film (2020)/film.mkv  <- collision       Interstellar (2014)/   .mkv + sample.mkv (exclu)
  The Matrix (1999)/ .mkv + txt/jpg/xyz
  The Wire/          S01E01 + S01E02.mkv   <- TV standard
  Bruit.Only/        txt + jpg (0 video)

Verifications figees :
  - source_root correct sur chaque row (multi-roots) ;
  - titres/annees parses (nfo + nom) ;
  - exclusions video_exts / nom suspect (sample) / dossiers sans video ;
  - TV standard detectee (kind=tv_episode, enable_tv_detection=True) ;
  - R8-079 : pack TV convention non-standard 'Show.101' planifie comme FILM
    (garde xfail nominative, se re-verifie seule si le bug est corrige) ;
  - GAP NFO : <tmdbid> du NFO NON propage au plan quand le nom matche
    (garde xfail nominative [GAP-NFO-TMDBID], cf plan_support_dedup + R5-H1) ;
  - collision cross-root -> warning_flag duplicate_cross_root des 2 cotes ;
  - plan.jsonl ecrit, relisible ligne a ligne, round-trip plan_row_from_jsonable ;
  - re-scan incremental : run 2 = 100% cache (hits>0, misses=0, rows_reused=n),
    rows run1 == rows run2, metriques lues dans runs.stats_json + summary.txt.

REGLES : rien hors tempdir, pas de port (pas de serveur REST), pas de commit app.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done

INCEPTION_TMDB_ID = 27205


def _write_nfo(path: Path, title: str, year: int, tmdbid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<movie><title>{title}</title><year>{year}</year>"
        f"<tmdbid>{tmdbid}</tmdbid><runtime>148</runtime></movie>",
        encoding="utf-8",
    )


def _build_library(root_a: Path, root_b: Path) -> None:
    # --- ROOT A -----------------------------------------------------------
    inception = root_a / "Inception (2010)"
    _create_file(inception / "Inception.2010.1080p.mkv")
    _write_nfo(inception / "Inception.2010.1080p.nfo", "Inception", 2010, INCEPTION_TMDB_ID)
    (inception / "Inception.2010.1080p.fr.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nBonjour\n", encoding="utf-8"
    )

    _create_file(root_a / "Film (2020)" / "film.mkv")  # collision cross-root

    matrix = root_a / "The Matrix (1999)"
    _create_file(matrix / "The.Matrix.1999.mkv")
    (matrix / "note.txt").write_text("annexe", encoding="utf-8")
    (matrix / "poster.jpg").write_bytes(b"\x00\x01")
    (matrix / "The.Matrix.1999.xyz").write_bytes(b"y" * 4096)  # extension inconnue

    wire = root_a / "The Wire"  # TV standard SxxExx (2 hints -> looks_tv_like)
    _create_file(wire / "The Wire S01E01.mkv")
    _create_file(wire / "The Wire S01E02.mkv")

    noise = root_a / "Bruit.Only"  # aucun fichier video
    noise.mkdir(parents=True, exist_ok=True)
    (noise / "readme.txt").write_text("bruit", encoding="utf-8")
    (noise / "cover.jpg").write_bytes(b"\x00")

    # --- ROOT B -----------------------------------------------------------
    _create_file(root_b / "Film (2020)" / "film.mkv")  # collision cross-root

    show = root_b / "Show"  # R8-079 : convention NxNN collee (101 = S01E01)
    for ep in (1, 2, 3):
        _create_file(show / f"Show.10{ep}.mkv")

    inter = root_b / "Interstellar (2014)"
    _create_file(inter / "Interstellar.2014.mkv", size=8192)
    _create_file(inter / "Interstellar.2014.sample.mkv")  # nom suspect -> exclu


def _settings_payload(root_a: Path, root_b: Path, state_dir: Path) -> dict:
    """Settings degrades proprement : AUCUN binaire externe requis."""
    return {
        "roots": [str(root_a), str(root_b)],
        "root": str(root_a),
        "state_dir": str(state_dir),
        "tmdb_enabled": False,
        "omdb_enabled": False,
        "probe_backend": "none",  # ffprobe/mediainfo absents -> degradation propre
        "incremental_scan_enabled": True,
        "enable_tv_detection": True,
        "collection_folder_enabled": True,
        "auto_recompute_quality_on_scan": False,  # pas de job qualite en arriere-plan
        "perceptual_enabled": False,
        "perceptual_auto_on_scan": False,
        "watch_enabled": False,
        "jellyfin_enabled": False,
        "plex_enabled": False,
        "radarr_enabled": False,
    }


def _run_scan(api: CineSortApi, settings: dict) -> tuple[str, list, dict]:
    """start_plan -> wait done -> (run_id, rows serialisees, status final)."""
    start = api.run.start_plan(dict(settings))
    assert start.get("ok"), f"start_plan KO : {start}"
    run_id = start["run_id"]
    status = _wait_done(api, run_id, timeout_s=60.0)
    assert status.get("error") in (None, ""), f"run {run_id} en erreur : {status}"
    plan = api.run.get_plan(run_id)
    assert plan.get("ok"), f"get_plan KO : {plan}"
    return run_id, list(plan.get("rows") or []), status


def _stats_for_run(api: CineSortApi, state_dir: Path, run_id: str) -> dict:
    store, _runner = api._get_or_create_infra(state_dir)
    run_row = store.run.get_run(run_id)
    assert run_row is not None, f"run {run_id} absent de la table runs"
    raw = run_row.get("stats_json") or "{}"
    stats = json.loads(raw)
    assert isinstance(stats, dict), f"stats_json illisible : {raw!r}"
    return stats


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def _rows_of_folder(rows: list, folder_name: str) -> list:
    return [r for r in rows if Path(str(r.get("folder") or "")).name == folder_name]


@pytest.fixture(scope="module")
def chain():
    """Biblio virtuelle jetable + 2 scans consecutifs via CineSortApi."""
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_lotd_scanplan_"))
    root_a = tmp / "rootA"
    root_b = tmp / "rootB"
    state_dir = tmp / "state"
    for p in (root_a, root_b, state_dir):
        p.mkdir(parents=True, exist_ok=True)
    _build_library(root_a, root_b)

    # Fichiers factices legers : on abaisse le seuil taille video (pattern
    # test_backend_flow.py) au lieu de creer des fichiers de 10 MB.
    patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
    patcher.start()
    api = None
    try:
        api = CineSortApi()
        settings = _settings_payload(root_a, root_b, state_dir)
        saved = api.settings.save_settings(dict(settings))
        assert saved.get("ok"), f"save_settings KO : {saved}"

        rid1, rows1, _st1 = _run_scan(api, settings)
        stats1 = _stats_for_run(api, state_dir, rid1)

        # 2e scan, biblio inchangee -> doit etre servi par le cache incremental.
        rid2, rows2, _st2 = _run_scan(api, settings)
        stats2 = _stats_for_run(api, state_dir, rid2)

        yield SimpleNamespace(
            api=api,
            root_a=root_a,
            root_b=root_b,
            state_dir=state_dir,
            rid1=rid1,
            rows1=rows1,
            stats1=stats1,
            rid2=rid2,
            rows2=rows2,
            stats2=stats2,
        )
    finally:
        patcher.stop()
        # Best-effort : liberer la DB avant rmtree (Windows lock).
        if api is not None:
            for store, runner in list(getattr(api, "_infra_by_state_dir", {}).values()):
                for obj in (runner, store):
                    fn = getattr(obj, "close", None)
                    if callable(fn):
                        try:
                            fn()
                        except Exception:  # noqa: BLE001 - cleanup best-effort
                            pass
        shutil.rmtree(tmp, ignore_errors=True)


class TestLotDChainScanPlan:
    # ------------------------------------------------------------- multi-root
    def test_01_source_root_correct_sur_chaque_row(self, chain):
        assert chain.rows1, "plan vide : la chaine scan->plan n'a rien produit"
        expected_roots = {str(chain.root_a), str(chain.root_b)}
        seen_roots = set()
        for r in chain.rows1:
            sr = str(r.get("source_root") or "")
            assert any(_same_path(sr, er) for er in expected_roots), (
                f"source_root inattendu {sr!r} pour row {r.get('row_id')} ({r.get('folder')})"
            )
            folder = Path(str(r.get("folder") or "")).resolve()
            assert folder.is_relative_to(Path(sr).resolve()), (
                f"folder {folder} hors de son source_root {sr}"
            )
            seen_roots.add(os.path.normcase(os.path.normpath(sr)))
        assert len(seen_roots) == 2, f"les 2 roots doivent etre representes : {seen_roots}"

    # ---------------------------------------------------------- titres/annees
    def test_02_titres_et_annees_parses(self, chain):
        films = {
            (str(r.get("proposed_title") or "").strip().lower(), int(r.get("proposed_year") or 0))
            for r in chain.rows1
            if r.get("kind") in ("single", "collection")
        }
        for expected in (
            ("inception", 2010),
            ("film", 2020),
            ("the matrix", 1999),
            ("interstellar", 2014),
        ):
            assert expected in films, f"{expected} absent du plan ; films parses = {sorted(films)}"

    # ------------------------------------------------------------- exclusions
    def test_03_exclusions_video_exts_et_noms_suspects(self, chain):
        # Aucune row ne doit pointer un fichier non-video.
        for r in chain.rows1:
            video = str(r.get("video") or "").lower()
            assert not video.endswith((".txt", ".jpg", ".srt", ".nfo", ".xyz")), (
                f"fichier non-video planifie : {video} (row {r.get('row_id')})"
            )
        # Dossier sans aucune video -> aucune row.
        assert not _rows_of_folder(chain.rows1, "Bruit.Only"), (
            "le dossier bruit (txt+jpg) ne doit generer aucune row"
        )
        # Le sample est exclu par IGNORE_VIDEO_NAME_RE : 1 seule row Interstellar.
        inter = _rows_of_folder(chain.rows1, "Interstellar (2014)")
        assert len(inter) == 1, f"attendu 1 row Interstellar (sample exclu), obtenu {len(inter)}"
        assert "sample" not in str(inter[0].get("video") or "").lower()
        # L'extension inconnue .xyz cohabite avec le .mkv : 1 seule row Matrix.
        matrix = _rows_of_folder(chain.rows1, "The Matrix (1999)")
        assert len(matrix) == 1, f"attendu 1 row Matrix (.xyz exclu), obtenu {len(matrix)}"
        # Metriques run : rejets par extension comptes + breakdown extensions
        # observees dans le dossier sans video.
        raisons = chain.stats1.get("analyse_ignores_par_raison") or {}
        assert int(raisons.get("ignore_extension") or 0) >= 1, raisons
        assert int(raisons.get("ignore_nom_suspect") or 0) >= 1, raisons
        exts = chain.stats1.get("analyse_ignores_extensions") or {}
        assert ".txt" in exts and ".jpg" in exts, f"breakdown extensions incomplet : {exts}"

    # ------------------------------------------------------------ TV standard
    def test_04_tv_standard_sxxexx_detectee(self, chain):
        wire = _rows_of_folder(chain.rows1, "The Wire")
        assert len(wire) == 2, f"attendu 2 episodes The Wire, obtenu {len(wire)} : {wire}"
        assert all(r.get("kind") == "tv_episode" for r in wire), wire
        assert {int(r.get("tv_episode") or 0) for r in wire} == {1, 2}
        assert all(int(r.get("tv_season") or 0) == 1 for r in wire)

    # -------------------------------------------------- R8-079 (garde xfail)
    def test_05_r8_079_pack_tv_non_standard_planifie_comme_film(self, chain):
        """R8-079 F-H5-03 : pack 'Show.101/.102/.103' (NxNN colle) non detecte TV.

        Garde nominative : tant que looks_tv_like ignore la convention NxNN
        collee, chaque episode est planifie comme un FILM distinct -> xfail.
        Si le bug est corrige (rows tv_episode ou pack ignore), la garde
        redevient passante et verifie le comportement corrige.
        """
        show = _rows_of_folder(chain.rows1, "Show")
        non_tv = [r for r in show if r.get("kind") != "tv_episode"]
        if show and non_tv:
            # Bug present : on FIGE le symptome exact avant de xfail.
            assert len(show) == 3, f"attendu 3 rows film pour le pack Show : {len(show)}"
            assert all(r.get("kind") in ("single", "collection", "extra") for r in show)
            assert all(not r.get("tv_series_name") for r in show)
            pytest.xfail(
                "[R8-079] pack TV convention non-standard 'Show.101..103' : "
                "looks_tv_like (domain/core.py) ne reconnait pas NxNN colle -> "
                f"{len(show)} episodes planifies comme FILMS distincts "
                "(kind=collection) au lieu d'une serie. Baseline R8 confirmee en runtime."
            )
        # Comportement corrige attendu : plus aucune row 'film' issue du pack.
        assert not non_tv, f"rows non-TV residuelles pour le pack Show : {non_tv}"

    # --------------------------------------------- GAP NFO tmdbid (garde xfail)
    def test_06_gap_nfo_tmdb_id_non_propage_au_plan(self, chain):
        """GAP connu (R5-H1) : le <tmdbid> du NFO n'est PAS propage au plan
        quand le nom matche (recherche TMDb court-circuitee, et
        build_candidates_from_nfo ne copie pas NfoInfo.tmdbid sur le Candidate).
        """
        inception = _rows_of_folder(chain.rows1, "Inception (2010)")
        assert len(inception) == 1, f"attendu 1 row Inception, obtenu {inception}"
        row = inception[0]
        # Premisse du GAP : le NFO a bien ete retenu comme source.
        assert str(row.get("proposed_source") or "") == "nfo", (
            f"premisse cassee : NFO non retenu (source={row.get('proposed_source')!r}, "
            f"flags={row.get('warning_flags')})"
        )
        assert row.get("nfo_path"), "nfo_path absent de la row alors que le NFO matche"
        # Le tmdb_id du NFO doit se retrouver quelque part dans la row.
        candidate_ids = {c.get("tmdb_id") for c in (row.get("candidates") or []) if isinstance(c, dict)}
        candidate_ids.discard(None)
        row_level_id = row.get("tmdb_id")  # champ absent du dataclass PlanRow a ce jour
        if INCEPTION_TMDB_ID not in candidate_ids and row_level_id != INCEPTION_TMDB_ID:
            pytest.xfail(
                "[GAP-NFO-TMDBID] <tmdbid>27205</tmdbid> present dans le NFO et NFO "
                "retenu (proposed_source=nfo) mais AUCUN tmdb_id dans la row du plan "
                f"(candidates tmdb_ids={sorted(candidate_ids) or 'aucun'}) : "
                "build_candidates_from_nfo (domain/core.py) ne copie pas NfoInfo.tmdbid "
                "et la recherche TMDb est court-circuitee quand le NFO matche "
                "(cf commentaire R5-H1 run_flow_support.py) -> jaquettes/enrichissement "
                "dependent d'une resolution TMDb differee par titre."
            )
        assert INCEPTION_TMDB_ID in candidate_ids or row_level_id == INCEPTION_TMDB_ID

    # -------------------------------------------------- collision cross-root
    def test_07_collision_cross_root_flaggee(self, chain):
        film_rows = [
            r
            for r in chain.rows1
            if str(r.get("proposed_title") or "").strip().lower() == "film"
            and int(r.get("proposed_year") or 0) == 2020
        ]
        assert len(film_rows) == 2, f"attendu 2 rows 'Film (2020)' (1 par root) : {film_rows}"
        roots = {os.path.normcase(os.path.normpath(str(r.get("source_root") or ""))) for r in film_rows}
        assert len(roots) == 2, f"la collision doit venir de 2 roots distincts : {roots}"
        for r in film_rows:
            flags = r.get("warning_flags") or []
            assert "duplicate_cross_root" in flags, (
                f"flag duplicate_cross_root absent sur {r.get('folder')} : {flags}"
            )

    # ------------------------------------------------------------- plan.jsonl
    def test_08_plan_jsonl_ecrit_et_relisible(self, chain):
        from cinesort.app.plan_support import plan_row_from_jsonable

        plan_path = chain.state_dir / "runs" / f"tri_films_{chain.rid1}" / "plan.jsonl"
        assert plan_path.exists(), f"plan.jsonl absent : {plan_path}"
        lines = [l for l in plan_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == len(chain.rows1), (
            f"plan.jsonl {len(lines)} lignes != {len(chain.rows1)} rows servies par get_plan"
        )
        parsed = []
        for i, line in enumerate(lines, 1):
            data = json.loads(line)  # chaque ligne est un JSON valide
            row = plan_row_from_jsonable(data)
            assert row is not None, f"ligne {i} non deserialisable en PlanRow : {line[:200]}"
            parsed.append(row)
        # Round-trip : source_root et kinds survivent a la (de)serialisation.
        reloaded_roots = {os.path.normcase(os.path.normpath(str(r.source_root or ""))) for r in parsed}
        assert len(reloaded_roots) == 2, f"source_root perdu au round-trip : {reloaded_roots}"
        assert {r.kind for r in parsed} == {str(x.get("kind")) for x in chain.rows1}

    # -------------------------------------------------- re-scan incremental
    def test_09_rescan_incremental_sert_le_cache(self, chain):
        s1, s2 = chain.stats1, chain.stats2
        # Run 1 : cache froid.
        assert int(s1.get("incremental_cache_hits") or 0) == 0, s1
        assert int(s1.get("incremental_cache_misses") or 0) > 0, s1
        # Run 2 : biblio inchangee -> 100% cache dossier. Preuves fiables :
        # - chaque dossier scanne est un hit ;
        # - TOUTES les rows du plan proviennent du cache (rows_reused == n) ;
        # - aucune video n'est repassee par _plan_item (row cache v2 inerte).
        hits2 = int(s2.get("incremental_cache_hits") or 0)
        reused2 = int(s2.get("incremental_cache_rows_reused") or 0)
        folders2 = int(s2.get("folders_scanned") or 0)
        assert hits2 > 0, f"aucun hit cache au re-scan : {s2}"
        assert hits2 == folders2, f"hits={hits2} != folders_scanned={folders2} : {s2}"
        assert reused2 == len(chain.rows2), (
            f"rows_reused={reused2} != {len(chain.rows2)} rows du run 2 (cache partiel)"
        )
        assert int(s2.get("incremental_cache_row_hits") or 0) == 0
        assert int(s2.get("incremental_cache_row_misses") or 0) == 0
        # Les metriques sont aussi exposees dans l'artefact summary.txt du run.
        summary = (chain.state_dir / "runs" / f"tri_films_{chain.rid2}" / "summary.txt").read_text(
            encoding="utf-8"
        )
        assert "Cache incremental (dossiers)" in summary and f"hits={hits2}" in summary

    def test_09b_metrique_misses_fantome_au_rescan(self, chain):
        """[LOTD-41-01] garde nominative : pollution de la metrique misses.

        Dans _filter_dossiers_phase (plan_support_core.py), `stats_before` est
        snapshotte AVANT `_try_apply_folder_cache` qui incremente
        incremental_cache_misses ; le delta par-dossier persiste donc
        `incremental_cache_misses: +1` (la cle figure dans
        stats_snapshot_for_cache, L185-187). Au re-scan, chaque HIT rejoue ce
        delta -> un run servi a 100% par le cache affiche misses == hits
        (cache apparemment inefficace a 50%) dans runs.stats_json ET
        summary.txt. Pollution d'observabilite uniquement (le cache sert bien,
        cf test_09). xfail tant que le bug est present.

        Finding CONNU mais jamais corrige : "Compteurs de cache auto-pollues",
        AUDIT_RELECTURE_2026-06-10.md L724 (R8-060/F5 n'a corrige que les
        champs OMIS du snapshot, pas ce double-comptage). Ici confirme en
        RUNTIME bout-en-bout via la chaine scan->plan reelle.
        """
        s2 = chain.stats2
        hits2 = int(s2.get("incremental_cache_hits") or 0)
        misses2 = int(s2.get("incremental_cache_misses") or 0)
        reused2 = int(s2.get("incremental_cache_rows_reused") or 0)
        # Premisse : le re-scan etait bien 100% cache (prouve par test_09).
        assert hits2 > 0 and reused2 == len(chain.rows2)
        if misses2 > 0:
            # Symptome exact fige : chaque hit rejoue le miss du run 1.
            assert misses2 == hits2, (
                f"symptome différent du connu (misses={misses2}, hits={hits2}) : "
                "a requalifier"
            )
            pytest.xfail(
                "[LOTD-41-01] metrique incremental_cache_misses fantome : re-scan "
                f"100% cache mais stats du run 2 = hits={hits2} misses={misses2} "
                "(le delta par-dossier persiste au run 1 contient misses+1 car "
                "stats_before est snapshotte avant _try_apply_folder_cache, "
                "plan_support_core.py ~L846 ; cle presente dans "
                "stats_snapshot_for_cache L186). Impact : summary.txt/stats_json "
                "sous-estiment l'efficacite du cache de moitie."
            )
        assert misses2 == 0, f"misses={misses2} au re-scan d'une biblio inchangee : {s2}"

    def test_10_rescan_produit_le_meme_plan(self, chain):
        def key(r: dict):
            return (
                str(r.get("kind") or ""),
                str(r.get("proposed_title") or "").strip().lower(),
                int(r.get("proposed_year") or 0),
                os.path.normcase(os.path.normpath(str(r.get("source_root") or ""))),
                str(r.get("video") or "").lower(),
            )

        assert sorted(map(key, chain.rows1)) == sorted(map(key, chain.rows2)), (
            "le re-scan incremental ne reproduit pas le meme plan que le scan a froid"
        )
