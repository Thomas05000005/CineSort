"""Revue post-merge 2026-07-18 — F06 / F07 / F17 (cinesort/ui/api/apply_support.py).

F06 : `_execute_apply` reconstruisait le Config per-root en recopiant les kwargs
      A LA MAIN -> naming_movie_template / naming_tv_template / min_video_bytes /
      scan_max_workers oublies, donc tout root SECONDAIRE retombait sur les
      defaults dataclass "{title} ({year})" / "{series} ({year})" et amputait le
      preset de nommage de l'utilisateur (dossiers uniquement).

F07 : la liste des "perdants" doublons etait l'UNION BRUTE des loser_row_ids de
      TOUTES les decisions du run. La table est upsert-only sur (run_id,
      group_key) et la cle derive de "titre|annee" : editer l'annee cree une
      nouvelle cle, l'ancienne decision survit, et les DEUX copies partaient au
      bucket _review/_duplicates_user_decided/ -> le film quittait entierement
      la bibliotheque.

F17 : le merge multi-root ne fusionnait que les int et `skip_reasons` :
      `error_messages` et `cleanup_residual_diagnostic` des roots 2..N etaient
      jetes -> resume "Erreurs : 1" SANS section "ABANDONNE / EN ERREUR" puis
      "Aucun point d'attention bloquant apres apply."

REVUE ADVERSAIRE R1 — defauts trouves DANS ces correctifs et fermes ici :
  * F06 : aucun test n'exercait le consommateur reel (`_apply_rows_fn` etait
    integralement mocke) -> l'effet utilisateur revendique (nom de dossier
    conforme au preset sur un root secondaire) n'etait demontre nulle part ;
    et `Config.normalized()` reste une SECONDE recopie manuelle champ par champ
    dans le meme pipeline (cleanup.py) -> guard anti-drift ajoute.
  * F07 : REGRESSION — une decision dont `loser_row_ids` est VIDE conferait une
    immunite a son "gagnant" et annulait une decision anterieure legitime :
    plus AUCUN perdant n'etait deplace.
  * F17 : `per_root` perdait l'entree du root 1 quand son diagnostic etait vide,
    le resume affichait un total multi-root sous un unique bucket, et la garde
    anti-drift `bool` de `_merge_apply_results` etait livree sans couverture.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import cinesort.domain.core as core
from cinesort.infra import state
from cinesort.ui.api import apply_support, library_actions_support

RUN_ID = "r_f06_f07_f17"


# ── Harnais commun ───────────────────────────────────────────────────


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


class _StubDuplicateRepo:
    def __init__(self, decisions: Any) -> None:
        self._decisions = decisions

    def list_duplicate_decisions(self, *, run_id: str) -> Any:
        if isinstance(self._decisions, Exception):
            raise self._decisions
        return list(self._decisions)


class _StubFilmModalRepo:
    def get_tmdb_override(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        return None

    def list_marked_for_deletion(self, *, run_id: str) -> List[Dict[str, Any]]:
        return []


class _StubStore:
    def __init__(self, decisions: Any = ()) -> None:
        self.apply = _StubDuplicateRepo(decisions)
        self.film_modal = _StubFilmModalRepo()


def _row(row_id: str, source_root: Optional[str] = None) -> core.PlanRow:
    row = core.PlanRow(
        row_id=row_id,
        kind="single",
        folder="",
        video="movie.mkv",
        proposed_title="Blade Runner",
        proposed_year=1982,
        proposed_source="name",
        confidence=90,
        confidence_label="high",
        candidates=[],
    )
    if source_root is not None:
        row.source_root = source_root
    return row


def _sentinel_config(root: Path) -> core.Config:
    """Config dont CHAQUE champ (sauf `root`) vaut une valeur non-default.

    Sert de guard anti-drift : si un champ de core.Config n'est pas propage
    per-root, l'egalite du test echoue. Un futur champ dont on ne sait pas
    fabriquer de sentinelle fait echouer le test explicitement (volontaire).
    """
    explicit_none_defaults = {
        "video_exts": {".sentinel"},
        "side_exts": {".sentinelsub"},
        "generic_side_files": {"sentinel.nfo"},
        "min_video_bytes": 4242,
    }
    # Champs "coerce-and-default" : `Config.normalized()` remplace toute valeur
    # hors domaine par le default. Une sentinelle "<default>_SENTINEL" y serait
    # donc indiscernable d'un champ PERDU -> on prend une valeur VALIDE et
    # differente du default, ce qui garde le guard normalized() discriminant.
    explicit_valid_domain = {
        "separator": "_",
        "empty_folders_scope": "touched_only",
        "cleanup_residual_folders_scope": "root_all",
    }
    kwargs: Dict[str, Any] = {}
    for f in dataclasses.fields(core.Config):
        if f.name == "root":
            continue
        if f.name in explicit_valid_domain:
            kwargs[f.name] = explicit_valid_domain[f.name]
            continue
        if f.default is not dataclasses.MISSING:
            default = f.default
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            default = f.default_factory()  # type: ignore[misc]
        else:
            default = None
        if isinstance(default, bool):
            kwargs[f.name] = not default
        elif isinstance(default, str):
            kwargs[f.name] = default + "_SENTINEL"
        elif isinstance(default, float):
            kwargs[f.name] = default + 1.5
        elif isinstance(default, int):
            kwargs[f.name] = default + 7
        elif default is None and f.name in explicit_none_defaults:
            kwargs[f.name] = explicit_none_defaults[f.name]
        else:
            raise AssertionError(
                f"champ core.Config non couvert par le guard anti-drift : {f.name!r} "
                "— ajouter une valeur sentinelle dans _sentinel_config()"
            )
    return core.Config(root=root, **kwargs)


def _run_execute_apply(
    cfg: core.Config,
    rows: List[core.PlanRow],
    tmp: Path,
    *,
    decisions: Any = (),
    partial_results: Optional[List[core.ApplyResult]] = None,
) -> Dict[str, Any]:
    """Execute `_execute_apply` en dry_run avec `_apply_rows_fn` mocke.

    Renvoie les cfg et kwargs captures a chaque appel per-root, plus le
    ApplyResult agrege. `partial_results` (optionnel) fournit le resultat rendu
    par chaque appel per-root, dans l'ordre.
    """
    captured_cfgs: List[Any] = []
    captured_kwargs: List[Dict[str, Any]] = []
    logs: List[tuple] = []
    pending = list(partial_results or [])

    def _fake_apply_rows(cfg_arg: Any, rows_arg: Any, decisions_arg: Any, **kwargs: Any) -> Any:
        captured_cfgs.append(cfg_arg)
        captured_kwargs.append(dict(kwargs))
        if pending:
            return pending.pop(0)
        res = core.ApplyResult()
        res.total_rows = len(list(rows_arg))
        return res

    paths = _run_paths(tmp)
    store = _StubStore(decisions)
    with (
        patch.object(apply_support, "_apply_rows_fn", side_effect=_fake_apply_rows),
        patch.object(apply_support._plan_support_mod, "find_duplicate_targets", return_value=None),
        patch.object(library_actions_support, "migrate_legacy_deletion_marks", return_value=[]),
    ):
        result, batch_id, _ops = apply_support._execute_apply(
            cfg,
            rows,
            {},
            None,
            dry_run=True,
            quarantine_unapproved=False,
            log_fn=lambda lvl, msg: logs.append((lvl, msg)),
            run_paths=paths,
            store=store,
            api=SimpleNamespace(_app_version="test"),
            run_id=RUN_ID,
            batch_state=[None, 0],
        )
    return {
        "cfgs": captured_cfgs,
        "kwargs": captured_kwargs,
        "logs": logs,
        "result": result,
        "batch_id": batch_id,
    }


def _skip_counts_zero() -> Dict[str, int]:
    """Toutes les raisons de skip a 0 (`_summarize_apply` les indexe sans `.get`)."""
    return {
        reason: 0
        for reason in (
            core.SKIP_REASON_NON_VALIDE,
            core.SKIP_REASON_VALIDATION_ABSENTE,
            core.SKIP_REASON_NOOP_DEJA_CONFORME,
            core.SKIP_REASON_OPTION_DESACTIVEE,
            core.SKIP_REASON_MERGED,
            core.SKIP_REASON_CONFLIT_QUARANTAINE,
            core.SKIP_REASON_ERREUR_PRECEDENTE,
            core.SKIP_REASON_AUTRE,
        )
    }


def _run_execute_apply_reel(
    cfg: core.Config,
    rows: List[core.PlanRow],
    tmp: Path,
    decisions_map: Dict[str, Any],
) -> Dict[str, Any]:
    """REVUE R1 : meme harnais mais avec le VRAI `apply_core.apply_rows`.

    `_apply_rows_fn` n'est PAS mocke : c'est la seule facon de prouver l'effet
    utilisateur de F06 (le NOM DE DOSSIER produit), et non seulement que l'objet
    Config capture porte les bons attributs. dry_run=True -> aucun fichier
    touche, seule la ligne RENAME de la preview est mesuree.
    """
    logs: List[tuple] = []
    paths = _run_paths(tmp)
    with (
        patch.object(apply_support._plan_support_mod, "find_duplicate_targets", return_value=None),
        patch.object(library_actions_support, "migrate_legacy_deletion_marks", return_value=[]),
    ):
        result, _batch_id, _ops = apply_support._execute_apply(
            cfg,
            rows,
            decisions_map,
            set(decisions_map),
            dry_run=True,
            quarantine_unapproved=False,
            log_fn=lambda lvl, msg: logs.append((lvl, msg)),
            run_paths=paths,
            store=_StubStore(),
            api=SimpleNamespace(_app_version="test"),
            run_id=RUN_ID,
            batch_state=[None, 0],
        )
    return {"logs": logs, "result": result}


# ── F06 ──────────────────────────────────────────────────────────────


class F06PerRootConfigTests(unittest.TestCase):
    def test_per_root_cfg_carries_custom_naming_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            cfg = core.Config(
                root=root1,
                naming_movie_template="{title} ({year}) {edition-tag}",
                naming_tv_template="{series} - saison {year}",
            )
            out = _run_execute_apply(cfg, [_row("f1", str(root2))], tmp)

            self.assertEqual(len(out["cfgs"]), 1)
            cfg_root2 = out["cfgs"][-1]
            self.assertEqual(cfg_root2.root, root2)
            self.assertEqual(
                cfg_root2.naming_movie_template,
                "{title} ({year}) {edition-tag}",
                "le preset de nommage FILM de l'utilisateur doit suivre sur les roots "
                "secondaires, sinon l'apply renomme le dossier au format default et "
                "ampute l'edition-tag",
            )
            self.assertEqual(
                cfg_root2.naming_tv_template,
                "{series} - saison {year}",
                "meme regle pour le template TV (apply_core.py chemin TV)",
            )

    def test_per_root_cfg_is_exhaustive_copy(self) -> None:
        """Guard anti-drift : TOUT champ de core.Config doit etre propage.

        C'est ce test qui aurait attrape les 3 recidives successives
        (lowercase_extensions, separator, puis les templates de nommage).
        """
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            cfg = _sentinel_config(root1)
            out = _run_execute_apply(cfg, [_row("f1", str(root2))], tmp)

            self.assertEqual(
                out["cfgs"][-1],
                dataclasses.replace(cfg, root=root2),
                "un champ ajoute a core.Config doit etre propage per-root — ne pas re-lister les kwargs a la main",
            )

    def test_non_regression_main_root_reuses_cfg_object(self) -> None:
        """NON-REGRESSION (vert des deux cotes de la mutation) : quand le root de
        la row est le root principal, on reutilise l'objet cfg tel quel."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            cfg = core.Config(root=root1, naming_movie_template="{title} [{year}]")
            out = _run_execute_apply(cfg, [_row("f1", str(root1))], tmp)

            self.assertEqual(len(out["cfgs"]), 1)
            self.assertIs(out["cfgs"][-1], cfg)

    def test_non_regression_missing_root_falls_back_to_main_cfg(self) -> None:
        """NON-REGRESSION : un source_root inexistant retombe sur le cfg principal
        (defaut adjacent connu, volontairement NON traite par F06)."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            cfg = core.Config(root=root1)
            out = _run_execute_apply(cfg, [_row("f1", str(tmp / "disparu"))], tmp)

            self.assertIs(out["cfgs"][-1], cfg)


class F06RealApplyEndToEndTests(unittest.TestCase):
    """REVUE R1 : preuve de l'EFFET UTILISATEUR, pas de la propagation d'attributs.

    Les 4 tests ci-dessus mockent integralement `_apply_rows_fn` : ils prouvent
    que le Config capture porte les bons attributs, jamais que le NOM DE DOSSIER
    produit change. Ici on fait tourner le vrai `apply_core.apply_rows` en
    dry_run sur un root secondaire et on mesure le nom de dossier propose.
    """

    def _make_movie(self, root: Path, folder_name: str, video_name: str) -> Path:
        src = root / folder_name
        src.mkdir(parents=True)
        (src / video_name).write_bytes(b"x" * 4096)
        return src

    def test_root_secondaire_renomme_selon_le_preset_utilisateur(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            src = self._make_movie(root2, "Blade.Runner.1982.BluRay.x264", "Blade.Runner.1982.BluRay.x264.mkv")

            row = core.PlanRow(
                row_id="f1",
                kind="single",
                folder=str(src),
                video=str(src / "Blade.Runner.1982.BluRay.x264.mkv"),
                proposed_title="Blade Runner",
                proposed_year=1982,
                proposed_source="name",
                confidence=95,
                confidence_label="high",
                candidates=[],
            )
            row.source_root = str(root2)

            cfg = core.Config(root=root1, naming_movie_template="{title} [{year}]")
            out = _run_execute_apply_reel(cfg, [row], tmp, {"f1": {"ok": True}})

            renames = [msg for lvl, msg in out["logs"] if msg.startswith("RENAME:")]
            self.assertEqual(len(renames), 1, f"une seule ligne RENAME attendue, logs={out['logs']}")
            self.assertTrue(
                renames[0].endswith("Blade Runner [1982]"),
                "le dossier du root SECONDAIRE doit suivre le preset de nommage de "
                f"l'utilisateur ; avant F06 il retombait sur '{{title}} ({{year}})'. Vu : {renames[0]}",
            )
            self.assertEqual(out["result"].renames, 1)

    def test_non_regression_dossier_deja_conforme_est_un_noop(self) -> None:
        """NON-REGRESSION (verte des deux cotes de la mutation partielle) : un
        dossier deja conforme au template DEFAULT sur un root secondaire ne doit
        produire aucun RENAME quand le template configure est le default."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            src = self._make_movie(root2, "Blade Runner (1982)", "Blade Runner (1982).mkv")

            row = core.PlanRow(
                row_id="f1",
                kind="single",
                folder=str(src),
                video=str(src / "Blade Runner (1982).mkv"),
                proposed_title="Blade Runner",
                proposed_year=1982,
                proposed_source="name",
                confidence=95,
                confidence_label="high",
                candidates=[],
            )
            row.source_root = str(root2)

            cfg = core.Config(root=root1)
            out = _run_execute_apply_reel(cfg, [row], tmp, {"f1": {"ok": True}})

            self.assertEqual(out["result"].renames, 0)
            self.assertEqual([msg for lvl, msg in out["logs"] if msg.startswith("RENAME:")], [])


class F06NormalizedDriftGuardTests(unittest.TestCase):
    """REVUE R1 : `Config.normalized()` est la SECONDE recopie manuelle du pipeline.

    `cleanup.preview_cleanup_residual_folders` fait `cfg = cfg.normalized()` et
    est appele par apply_core avec le `cfg_for_root` que F06 vient de securiser :
    un champ oublie dans `normalized()` y reapparaitrait a son default, a
    l'INTERIEUR meme du chemin per-root. Elle est exhaustive a HEAD ; ce guard
    rougit automatiquement au prochain champ ajoute a core.Config, sans avoir a
    modifier core.py.
    """

    def test_normalized_ne_perd_aucun_champ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            root = Path(tmp_s) / "films"
            root.mkdir()
            cfg = _sentinel_config(root)
            normalized = cfg.normalized()
            defaults = core.Config(root=root)

            for f in dataclasses.fields(core.Config):
                if f.name == "root":
                    continue
                with self.subTest(champ=f.name):
                    self.assertNotEqual(
                        getattr(normalized, f.name),
                        getattr(defaults, f.name),
                        f"{f.name} est retombe a son default en traversant Config.normalized() "
                        "— re-lister les kwargs a la main a deja derive 3 fois dans ce pipeline",
                    )


# ── F07 ──────────────────────────────────────────────────────────────


class F07DuplicateStaleDecisionTests(unittest.TestCase):
    def test_resolve_losers_protege_le_gagnant_dune_decision_plus_recente(self) -> None:
        logs: List[tuple] = []
        decisions = [
            {
                "group_key": "titre|1986",
                "winner_row_id": "B",
                "loser_row_ids": ["A"],
                "decided_ts": 200.0,
            },
            {
                "group_key": "titre|1979",
                "winner_row_id": "A",
                "loser_row_ids": ["B"],
                "decided_ts": 100.0,
            },
        ]
        losers = apply_support._resolve_duplicate_loser_row_ids(decisions, lambda lvl, msg: logs.append((lvl, msg)))
        self.assertEqual(
            losers,
            {"A"},
            "l'union brute donnait {'A','B'} : les DEUX copies partaient au bucket "
            "et le film quittait entierement la bibliotheque",
        )
        self.assertTrue(
            any("B" in msg and lvl == "WARN" for lvl, msg in logs),
            "un WARN doit tracer la decision perimee ignoree",
        )

    def test_execute_apply_ne_deplace_pas_le_gagnant_courant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            cfg = core.Config(root=root1)
            decisions = [
                # Repo reel : ORDER BY decided_ts DESC.
                {
                    "group_key": "le grand voyage|2006",
                    "winner_row_id": "B",
                    "loser_row_ids": ["A"],
                    "decided_ts": 200.0,
                },
                {
                    "group_key": "le grand voyage|2005",
                    "winner_row_id": "A",
                    "loser_row_ids": ["B"],
                    "decided_ts": 100.0,
                },
            ]
            out = _run_execute_apply(
                cfg,
                [_row("A", str(root1)), _row("B", str(root1))],
                tmp,
                decisions=decisions,
            )
            self.assertEqual(
                out["kwargs"][-1]["duplicate_loser_row_ids"],
                {"A"},
                "apply_rows ne doit recevoir QUE le perdant de la decision la plus "
                "recente ; avant le fix il recevait {'A','B'}",
            )

    def test_non_regression_decision_unique_inchangee(self) -> None:
        """NON-REGRESSION (vert des deux cotes de la mutation) : le cas nominal
        (une seule decision) doit continuer a designer tous ses perdants.
        Passe par `_execute_apply` (present des deux cotes) et non par le helper,
        pour que l'assertion reste evaluable quand le correctif est retire."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            cfg = core.Config(root=root1)
            out = _run_execute_apply(
                cfg,
                [_row("A", str(root1))],
                tmp,
                decisions=[
                    {
                        "group_key": "titre|1979",
                        "winner_row_id": "A",
                        "loser_row_ids": ["B", "C", ""],
                        "decided_ts": 100.0,
                    }
                ],
            )
            self.assertEqual(out["kwargs"][-1]["duplicate_loser_row_ids"], {"B", "C"})

    def test_decision_sans_perdant_narbitre_rien(self) -> None:
        """REVUE R1 — REGRESSION introduite par F07.

        Le role "winner" etait pose pour TOUTE decision, meme sans perdant. Une
        decision recente sans perdant conferait donc une immunite a son gagnant
        et ANNULAIT une decision anterieure legitime : plus aucun perdant n'etait
        deplace, alors que l'union brute d'avant deplacait bien celui choisi par
        l'utilisateur.

        Atteignable en 2 clics : un groupe doublons a UNE SEULE row est emis des
        qu'une copie existe deja sur disque (duplicate_support.py) ;
        `mark_duplicate_winner` (run_flow_support.py) y calcule alors losers=[]
        et persiste la decision avec un `decided_ts` FRAIS.
        """
        logs: List[tuple] = []
        decisions = [
            {"group_key": "titre|1986", "winner_row_id": "B", "loser_row_ids": [], "decided_ts": 200.0},
            {"group_key": "titre|1979", "winner_row_id": "A", "loser_row_ids": ["B"], "decided_ts": 100.0},
        ]
        losers = apply_support._resolve_duplicate_loser_row_ids(decisions, lambda lvl, msg: logs.append((lvl, msg)))
        self.assertEqual(
            losers,
            {"B"},
            "une decision SANS perdant n'arbitre rien : elle ne doit pas neutraliser "
            "la decision 'Garder A' de l'utilisateur (sinon l'apply ne deplace plus RIEN)",
        )
        self.assertEqual(logs, [], "aucun conflit reel ici : pas de WARN a l'envers")

    def test_decision_sans_perdant_ne_bloque_pas_lapply_reel(self) -> None:
        """Meme scenario, via `_execute_apply` : le perdant doit bien etre transmis."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            out = _run_execute_apply(
                core.Config(root=root1),
                [_row("A", str(root1)), _row("B", str(root1))],
                tmp,
                decisions=[
                    {"group_key": "titre|1986", "winner_row_id": "B", "loser_row_ids": [], "decided_ts": 200.0},
                    {"group_key": "titre|1979", "winner_row_id": "A", "loser_row_ids": ["B"], "decided_ts": 100.0},
                ],
            )
            self.assertEqual(out["kwargs"][-1]["duplicate_loser_row_ids"], {"B"})

    def test_non_regression_decision_sans_perdant_seule_ne_deplace_rien(self) -> None:
        """NON-REGRESSION (verte des deux cotes de la mutation) : une decision sans
        perdant, seule, ne doit designer AUCUN perdant."""
        losers = apply_support._resolve_duplicate_loser_row_ids(
            [{"group_key": "titre|1986", "winner_row_id": "B", "loser_row_ids": [], "decided_ts": 200.0}],
            lambda _lvl, _msg: None,
        )
        self.assertEqual(losers, set())

    def test_db_verrouillee_ne_fait_pas_crasher_lapply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            cfg = core.Config(root=root1)
            out = _run_execute_apply(
                cfg,
                [_row("A", str(root1))],
                tmp,
                decisions=sqlite3.OperationalError("database is locked"),
            )
            self.assertIsNone(out["kwargs"][-1]["duplicate_loser_row_ids"])
            self.assertTrue(
                any(lvl == "WARN" and "duplicate_decisions" in msg for lvl, msg in out["logs"]),
                "sqlite3.Error n'herite PAS d'OSError : sans son ajout a l'except, "
                "une DB verrouillee faisait crasher tout l'apply",
            )


# ── F17 ──────────────────────────────────────────────────────────────


class F17MultiRootResultMergeTests(unittest.TestCase):
    def test_merge_keeps_error_messages_of_secondary_roots(self) -> None:
        r1 = core.ApplyResult()
        r2 = core.ApplyResult(errors=1)
        r2.error_messages = ["FICHIER VERROUILLE : 'Film.mkv' est ouvert dans VLC"]

        merged = apply_support._merge_apply_results(r1, r2, root_label="D:/Films2")

        self.assertEqual(merged.errors, 1)
        self.assertEqual(
            merged.error_messages,
            ["FICHIER VERROUILLE : 'Film.mkv' est ouvert dans VLC"],
            "les messages d'erreur des roots 2..N ne doivent pas etre jetes : sinon "
            "_summarize_apply affiche 'Erreurs : 1' sans section ABANDONNE / EN ERREUR",
        )

    def test_merge_aggregates_cleanup_residual_diagnostic(self) -> None:
        r1 = core.ApplyResult()
        r1.cleanup_residual_diagnostic = {
            "enabled": True,
            "moved_count": 0,
            "has_video_count": 1,
            "status": "no_action_likely",
            "status_post": "executed_no_move",
            "sample_eligible_dirs": ["A"],
        }
        r2 = core.ApplyResult()
        r2.cleanup_residual_diagnostic = {
            "enabled": True,
            "moved_count": 3,
            "has_video_count": 2,
            "status": "ready",
            "status_post": "executed",
            "sample_eligible_dirs": ["B"],
        }

        merged = apply_support._merge_apply_results(r1, r2, root_label="D:/Films2", base_root_label="C:/Films1")
        diag = merged.cleanup_residual_diagnostic

        self.assertEqual(diag["moved_count"], 3)
        self.assertEqual(diag["has_video_count"], 3)
        self.assertIs(diag["enabled"], True)  # piege bool/int : surtout pas 2
        self.assertEqual(diag["status_post"], "executed")
        self.assertEqual(diag["status"], "ready")
        self.assertEqual(set(diag["sample_eligible_dirs"]), {"A", "B"})
        self.assertIn("D:/Films2", diag["per_root"])
        self.assertIn("C:/Films1", diag["per_root"])
        self.assertEqual(diag["per_root"]["D:/Films2"]["moved_count"], 3)

    def test_per_root_conserve_le_root_de_base_meme_sans_diagnostic(self) -> None:
        """REVUE R1 : le detail par root etait incomplet exactement quand on en a besoin.

        Quand le diagnostic du root 1 etait vide, la fonction sortait par le
        raccourci `if not base_d` et l'entree du root 1 n'apparaissait JAMAIS
        dans `per_root` : impossible de savoir si ce root avait ete traite.
        """
        r1 = core.ApplyResult()
        r1.cleanup_residual_diagnostic = {}
        r2 = core.ApplyResult()
        r2.cleanup_residual_diagnostic = {"enabled": True, "moved_count": 2, "target_folder_path": "R2/_bucket"}

        merged = apply_support._merge_apply_results(r1, r2, root_label="R2", base_root_label="R1")
        per_root = merged.cleanup_residual_diagnostic["per_root"]

        self.assertEqual(sorted(per_root), ["R1", "R2"])
        self.assertEqual(per_root["R1"], {}, "root 1 sans diagnostic doit rester TRACE, pas efface")
        self.assertEqual(per_root["R2"]["moved_count"], 2)

    def test_non_regression_aucun_root_avec_diagnostic_reste_vide(self) -> None:
        """NON-REGRESSION (verte des deux cotes de la mutation) : si AUCUN root n'a
        de diagnostic, le champ reste falsy — sinon `_summarize_apply` imprimerait
        un bloc "DETAIL NETTOYAGE RESIDUEL" entierement a zero."""
        r1 = core.ApplyResult()
        r2 = core.ApplyResult()
        merged = apply_support._merge_apply_results(r1, r2, root_label="R2", base_root_label="R1")
        self.assertFalse(merged.cleanup_residual_diagnostic)

    def test_le_resume_enumere_un_bucket_par_root(self) -> None:
        """REVUE R1 : total multi-root imprime sous un unique bucket mono-root.

        Les compteurs sont SOMMES sur tous les roots mais `target_folder_*` reste
        celui du root 1 : "Dossiers deplaces : 3" sous un seul dossier cible est
        trompeur quand 2 des 3 sont dans le bucket d'un autre root.
        """
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            paths = _run_paths(tmp)
            cfg = core.Config(root=root1)

            r1 = core.ApplyResult()
            r1.cleanup_residual_diagnostic = {
                "enabled": True,
                "moved_count": 1,
                "target_folder_name": "_Dossier Nettoyage",
                "target_folder_path": r"R1\_Dossier Nettoyage",
                "status_post": "executed",
            }
            r2 = core.ApplyResult()
            r2.cleanup_residual_diagnostic = {
                "enabled": True,
                "moved_count": 2,
                "target_folder_name": "_Dossier Nettoyage",
                "target_folder_path": r"R2\_Dossier Nettoyage",
                "status_post": "executed",
            }
            out = _run_execute_apply(
                cfg,
                [_row("f1", str(root1)), _row("f2", str(root2))],
                tmp,
                partial_results=[r1, r2],
            )

            apply_support._summarize_apply(
                out["result"],
                _skip_counts_zero(),
                0,
                2,
                out["result"].cleanup_residual_diagnostic,
                cfg=cfg,
                run_paths=paths,
                log_fn=lambda _lvl, _msg: None,
                dry_run=False,
                rows=[_row("f1", str(root1))],
                cleanup_scope_label=lambda scope: str(scope),
                cleanup_status_label=lambda status, **_kw: str(status),
                cleanup_reason_label=lambda reason: str(reason),
            )
            text = paths.summary_txt.read_text(encoding="utf-8")

            self.assertIn("Dossiers cibles par root", text)
            self.assertIn(r"R1\_Dossier Nettoyage : 1 dossier(s)", text)
            self.assertIn(r"R2\_Dossier Nettoyage : 2 dossier(s)", text)
            # NON-REGRESSION : le total agrege reste affiche.
            self.assertIn("- Dossiers deplaces : 3", text)

    def test_non_regression_mono_root_garde_la_ligne_dossier_cible(self) -> None:
        """NON-REGRESSION (verte des deux cotes de la mutation) : sans `per_root`
        (cas mono-root, l'ecrasante majorite), le resume garde sa ligne unique."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root1.mkdir()
            paths = _run_paths(tmp)
            cfg = core.Config(root=root1)

            result = core.ApplyResult()
            result.cleanup_residual_diagnostic = {
                "enabled": True,
                "moved_count": 1,
                "target_folder_name": "_Dossier Nettoyage",
            }
            apply_support._summarize_apply(
                result,
                _skip_counts_zero(),
                0,
                1,
                result.cleanup_residual_diagnostic,
                cfg=cfg,
                run_paths=paths,
                log_fn=lambda _lvl, _msg: None,
                dry_run=False,
                rows=[_row("f1", str(root1))],
                cleanup_scope_label=lambda scope: str(scope),
                cleanup_status_label=lambda status, **_kw: str(status),
                cleanup_reason_label=lambda reason: str(reason),
            )
            text = paths.summary_txt.read_text(encoding="utf-8")

            self.assertIn("- Dossier cible : _Dossier Nettoyage", text)
            self.assertNotIn("Dossiers cibles par root", text)

    def test_la_garde_anti_drift_bool_est_bien_active(self) -> None:
        """REVUE R1 : la branche `bool` de `_merge_apply_results` etait MORTE.

        `core.ApplyResult` n'a aucun champ bool a ce jour, et le test cense la
        couvrir passait en realite par `_merge_cleanup_residual_diagnostic`. Sans
        cette branche AVANT celle des int, un futur champ bool serait somme a 2
        (bool est une sous-classe de int). On l'exerce ici sur une dataclass
        jetable pour que la garde rougisse si on la retire.
        """

        @dataclasses.dataclass
        class _ResultAvecBool:
            flag: bool = False
            compteur: int = 0

        base = _ResultAvecBool(flag=True, compteur=1)
        extra = _ResultAvecBool(flag=True, compteur=2)

        merged = apply_support._merge_apply_results(base, extra, root_label="R2")

        self.assertIs(merged.flag, True, "True + True == 2 : le bool doit etre un OR, pas une somme")
        self.assertEqual(merged.compteur, 3, "les int, eux, restent bien sommes")

    def test_non_regression_merge_sums_ints_and_skip_reasons(self) -> None:
        """NON-REGRESSION (vert des deux cotes de la mutation) : le merge
        historique des int et du dict skip_reasons ne doit pas bouger. Passe par
        `_execute_apply` (present des deux cotes) pour rester evaluable quand le
        correctif est retire."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            r1 = core.ApplyResult(renames=2, moves=1)
            r1.skip_reasons = {core.SKIP_REASON_AUTRE: 1}
            r2 = core.ApplyResult(renames=3, moves=4)
            r2.skip_reasons = {core.SKIP_REASON_AUTRE: 2, core.SKIP_REASON_MERGED: 5}

            out = _run_execute_apply(
                core.Config(root=root1),
                [_row("f1", str(root1)), _row("f2", str(root2))],
                tmp,
                partial_results=[r1, r2],
            )
            merged = out["result"]

            self.assertEqual(merged.renames, 5)
            self.assertEqual(merged.moves, 5)
            self.assertEqual(
                merged.skip_reasons,
                {core.SKIP_REASON_AUTRE: 3, core.SKIP_REASON_MERGED: 5},
            )

    def test_summary_shows_abandoned_section_in_multi_root(self) -> None:
        """Surface utilisateur : le merge multi-root doit alimenter le resume."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root1 = tmp / "films1"
            root2 = tmp / "films2"
            root1.mkdir()
            root2.mkdir()
            paths = _run_paths(tmp)
            cfg = core.Config(root=root1)

            r1 = core.ApplyResult()
            r2 = core.ApplyResult(errors=1)
            r2.error_messages = ["FICHIER VERROUILLE : 'Film.mkv' est ouvert dans VLC"]
            out = _run_execute_apply(
                cfg,
                [_row("f1", str(root1)), _row("f2", str(root2))],
                tmp,
                partial_results=[r1, r2],
            )
            result = out["result"]

            skip_counts = {
                reason: 0
                for reason in (
                    core.SKIP_REASON_NON_VALIDE,
                    core.SKIP_REASON_VALIDATION_ABSENTE,
                    core.SKIP_REASON_NOOP_DEJA_CONFORME,
                    core.SKIP_REASON_OPTION_DESACTIVEE,
                    core.SKIP_REASON_MERGED,
                    core.SKIP_REASON_CONFLIT_QUARANTAINE,
                    core.SKIP_REASON_ERREUR_PRECEDENTE,
                    core.SKIP_REASON_AUTRE,
                )
            }
            apply_support._summarize_apply(
                result,
                skip_counts,
                0,
                1,
                {},
                cfg=cfg,
                run_paths=paths,
                log_fn=lambda _lvl, _msg: None,
                dry_run=False,
                rows=[_row("f1", str(root1))],
                cleanup_scope_label=lambda scope: str(scope),
                cleanup_status_label=lambda status, **_kw: str(status),
                cleanup_reason_label=lambda reason: str(reason),
            )
            text = paths.summary_txt.read_text(encoding="utf-8")

            self.assertIn("ABANDONNE / EN ERREUR", text)
            self.assertIn("FICHIER VERROUILLE", text)
            self.assertNotIn("Aucun point d'attention bloquant apres apply.", text)
            # NON-REGRESSION : le squelette du resume reste intact.
            self.assertIn("=== RESUME APPLICATION ===", text)
            self.assertIn("- Erreurs : 1", text)


if __name__ == "__main__":
    unittest.main()
