# -*- coding: utf-8 -*-
"""Contrat : aucun symbole module-level de `cinesort/` declare et jamais lu.

Pourquoi ce test existe
-----------------------
Les issues #490, #781, #483, #702, #644, #715, #526 sont le MEME defaut, accumule
un par un sur des mois : un symbole est declare (constante, fonction, classe),
puis son unique lecteur disparait — ou n'a jamais existe — et RIEN en CI ne le
signale. Chaque audit suivant repaye le cout de le redecouvrir, et pire : le
symbole mort continue de decrire une intention (ex. `_UPGRADE_ENCODE_FLAGS`
decrivait la detection d'upgrade Radarr pendant que le code faisait, a cote, une
detection par sous-chaine cassee).

Le pendant "reglages" de ce contrat est `tests/test_contract_settings.py` (une
cle de settings persistee sans lecteur backend). Meme forme, meme cliquet.

Comment ca marche
-----------------
Analyse AST, sans rien importer ni executer :

- DECLARATIONS : dans `cinesort/**.py` (hors `cinesort/tests/`), tout `def` /
  `class` / affectation a un `Name` au niveau MODULE (les symboles locaux a une
  fonction ne sont pas concernes).
- LECTURES : sur `cinesort/**.py` + `tests/**.py` + `app.py`, l'union des
  `Name` en contexte Load, des attributs (`x.foo`), des noms importes
  (`from m import foo`), des `global`/`nonlocal` et de TOUTES les chaines
  litterales (couvre `__all__`, `getattr(obj, "foo")` et les tables de
  dispatch par nom). Volontairement genereux : on veut zero faux positif.

Un symbole declare dont le nom n'apparait dans AUCUNE lecture est mort.

Cliquet
-------
`KNOWN_DEAD` fige la dette existante au 2026-08-03. Elle ne peut que RETRECIR :
- un symbole mort HORS liste fait echouer `test_no_new_dead_symbol` ;
- une entree de la liste qui n'est plus morte (supprimee, ou enfin lue) fait
  echouer `test_known_dead_entries_are_still_dead`, ce qui force son retrait.

Statique et rapide : aucune app lancee, aucun reseau, aucune DB.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# Repertoires/fichiers ou l'on CHERCHE des declarations mortes.
DECL_ROOTS = ("cinesort",)
# `cinesort/tests/` contient des TestCase decouverts par nom par pytest : ils
# n'ont, par construction, aucun lecteur dans le depot.
DECL_EXCLUDED_DIRS = ("cinesort/tests",)
# Repertoires/fichiers ou l'on CHERCHE des lectures.
USE_ROOTS = ("cinesort", "tests", "app.py")

# ---------------------------------------------------------------------------
# Dette CONNUE, figee au 2026-08-03. LISTE EN RETRECISSEMENT UNIQUEMENT.
# Cle : "<chemin/relatif.py>::<symbole>".
#
# 2026-08-04 (fusion de main) : le cliquet a fait son travail des la premiere
# resynchronisation. `cleanup._is_cleanable_residual_dir` est sorti de la liste
# (il a gagne un lecteur avec le test des jonctions NTFS, #517), et
# `integrity_check._TS_PACKET_SIZE` — devenu orphelin quand #784 l'a remplace
# par `_TS_LAYOUTS` — a ete recable au lieu d'etre inscrit ici.
# ---------------------------------------------------------------------------
KNOWN_DEAD: Dict[str, str] = {
    "cinesort/app/apply_rollback.py::ROLLBACK_NONE": "constante module-level jamais lue",
    "cinesort/app/duplicate_pipeline.py::compute_fusion_for_pair": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/app/enrichment_facade.py::enrichment_for_film": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/app/enrichment_facade.py::get_enrichment_status": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/app/move_journal.py::safe_move": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/app/plan_support_dedup.py::_augment_candidates_from_name_tags": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/app/quarantine_ttl.py::_purge_target_roots": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/core.py::_COMPAT_SCAN_EXPORTS": "constante module-level jamais lue",
    "cinesort/domain/core.py::_TMDB_BONUS_KEYWORD_RE": "constante module-level jamais lue",
    "cinesort/domain/core.py::_stats_add_ignored_extension": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/duplicate_compare.py::_HDR_RANK": "constante module-level jamais lue",
    "cinesort/domain/duplicate_compare.py::_RESOLUTION_RANK": "constante module-level jamais lue",
    "cinesort/domain/duplicate_compare.py::_WEIGHT_FILE_SIZE": "constante module-level jamais lue",
    "cinesort/domain/film_history.py::film_identity_key": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/mkv_title_check.py::_is_scene_title": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/perceptual/audio_perceptual.py::_RE_OVERALL_BLOCK": "constante module-level jamais lue",
    "cinesort/domain/perceptual/audio_perceptual.py::_RE_OVERALL_LINE": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::BANDING_SEVERE": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::BATCH_PARALLELISM_DEFAULT_WORKERS": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::BATCH_PARALLELISM_MIN_FILMS_FOR_POOL": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::BUDGET_MEDIUM": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::DV_COMPAT_RANKING": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::FRAME_SKIP_PERCENT": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::GRAIN_HEAVY": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::HDR_MAX_CLL_TYPICAL_MIN": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::HDR_MAX_FALL_TYPICAL": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::LPIPS_INFERENCE_TIMEOUT_S": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::LRA_FLAT": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::MEL_SOFT_CLIP_HARMONICS_MIN_PCT": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::NOISE_FLOOR_POOR": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::SHORT_FILM_DURATION_S": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::SSIM_SELF_REF_NATIVE_THRESHOLD": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::TIER_LABELS": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::TIER_V2_COLORS": "constante module-level jamais lue",
    "cinesort/domain/perceptual/constants.py::TIER_V2_LABELS": "constante module-level jamais lue",
    "cinesort/domain/perceptual/models.py::FrameMetrics": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/report_types.py::parse_report_safe": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/vision_embedding.py::aggregate_embeddings": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/vision_embedding.py::embed_frames": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/domain/vision_embedding.py::extract_keyframes": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/db/pragma_profile.py::_VALID_PRAGMA_HISTORY_SOURCES": "constante module-level jamais lue",
    "cinesort/infra/integrations/dinov3_model.py::INPUT_SIZE_DEFAULT": "constante module-level jamais lue",
    "cinesort/infra/integrations/dinov3_model.py::cosine_similarity": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/integrations/dinov3_model.py::load_model": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/integrations/dinov3_model.py::reset_cache": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/integrations/ollama_client.py::ALT_OLLAMA_MODEL": "constante module-level jamais lue",
    "cinesort/infra/jellyfin_client.py::_JELLYFIN_CLIENT_NAME": "constante module-level jamais lue",
    "cinesort/infra/jellyfin_client.py::_JELLYFIN_CLIENT_VERSION": "constante module-level jamais lue",
    "cinesort/infra/jellyfin_client.py::_JELLYFIN_DEVICE_ID": "constante module-level jamais lue",
    "cinesort/infra/jellyfin_client.py::_JELLYFIN_DEVICE_NAME": "constante module-level jamais lue",
    "cinesort/infra/log_context.py::LOG_FIELD_REQUEST_ID": "constante module-level jamais lue",
    "cinesort/infra/log_context.py::LOG_FIELD_RUN_ID": "constante module-level jamais lue",
    "cinesort/infra/log_context.py::reset_request_id": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/notifications.py::NIF_MESSAGE": "constante module-level jamais lue",
    "cinesort/infra/notifications.py::NIIF_NOSOUND": "constante module-level jamais lue",
    "cinesort/infra/probe/_source_circuit_breaker.py::reset_default_breaker": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/probe/disk_cache.py::prune_disk_cache": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/state.py::ensure_dir": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/infra/state.py::write_text_safe": "fonction/classe sans aucun lecteur dans le depot",
    "cinesort/ui/api/quality_audit_support.py::_extract_warnings_from_payload": "fonction/classe sans aucun lecteur dans le depot",
}


# ---------------------------------------------------------------------------
# Collecte
# ---------------------------------------------------------------------------


def _iter_py_files(rels: Tuple[str, ...], excluded_dirs: Tuple[str, ...] = ()) -> List[Path]:
    out: List[Path] = []
    for rel in rels:
        target = REPO_ROOT / rel
        if target.is_file():
            out.append(target)
            continue
        for path in sorted(target.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            posix = path.relative_to(REPO_ROOT).as_posix()
            if any(posix.startswith(d + "/") for d in excluded_dirs):
                continue
            out.append(path)
    return out


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _collect_declarations() -> Dict[str, Tuple[int, str]]:
    """{"<rel>::<nom>": (ligne, kind)} pour tout symbole declare au niveau module."""
    decls: Dict[str, Tuple[int, str]] = {}
    for path in _iter_py_files(DECL_ROOTS, DECL_EXCLUDED_DIRS):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                decls[f"{rel}::{node.name}"] = (node.lineno, "def")
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        decls[f"{rel}::{tgt.id}"] = (node.lineno, "const")
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                decls[f"{rel}::{node.target.id}"] = (node.lineno, "const")
    return decls


def _collect_used_names() -> Set[str]:
    """Tous les noms LUS quelque part (volontairement large : zero faux positif)."""
    used: Set[str] = set()
    for path in _iter_py_files(USE_ROOTS):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    used.add(alias.name)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                used.update(node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.add(node.value)
    return used


def collect_dead_symbols() -> Dict[str, Tuple[int, str]]:
    """{"<rel>::<nom>": (ligne, kind)} pour les symboles declares et jamais lus."""
    used = _collect_used_names()
    dead: Dict[str, Tuple[int, str]] = {}
    for key, (line, kind) in _collect_declarations().items():
        name = key.split("::", 1)[1]
        if name.startswith("__") and name.endswith("__"):
            continue  # dunders : contrat du langage, pas du code mort
        if name in used:
            continue
        dead[key] = (line, kind)
    return dead


class DeadSymbolsContractTests(unittest.TestCase):
    """Contrat : la liste des symboles morts de cinesort/ ne peut que retrecir."""

    declarations: Dict[str, Tuple[int, str]] = {}
    dead: Dict[str, Tuple[int, str]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.declarations = _collect_declarations()
        cls.dead = collect_dead_symbols()

    def test_extraction_is_sane(self) -> None:
        """Garde anti-silence : un extracteur casse rendrait le test vert a tort."""
        self.assertGreaterEqual(
            len(self.declarations),
            2000,
            msg=(
                f"Extraction des declarations suspecte : {len(self.declarations)} symboles "
                f"module-level trouves dans cinesort/ (attendu >= 2000, mesure 2026-08-03 : "
                f"2911). L'arborescence ou l'extracteur ont-ils change ?"
            ),
        )

    def test_no_new_dead_symbol(self) -> None:
        """Un symbole declare et jamais lu, hors dette figee, echoue ici."""
        violations = []
        for key in sorted(self.dead):
            if key in KNOWN_DEAD:
                continue
            line, kind = self.dead[key]
            rel, name = key.split("::", 1)
            violations.append(f"  - {name!r} ({kind}) declare a {rel}:{line}, lu nulle part")
        self.assertEqual(
            violations,
            [],
            msg=(
                f"{len(violations)} symbole(s) module-level de cinesort/ declare(s) et JAMAIS "
                f"lu(s) (ni dans cinesort/, ni dans tests/, ni dans app.py) :\n"
                + "\n".join(violations)
                + "\n\nComment corriger, dans cet ordre : (1) le SUPPRIMER si c'est un residu ; "
                "(2) le CABLER si le symbole decrit une intention que le code applique mal a "
                "cote (cas de _UPGRADE_ENCODE_FLAGS : la constante nommait les flags pendant "
                "que la detection reelle se faisait par sous-chaine, et se trompait) ; "
                "(3) en tout dernier recours, assumer la dette dans KNOWN_DEAD ci-dessus — "
                "deconseille, cette liste doit retrecir."
            ),
        )

    def test_known_dead_entries_are_still_dead(self) -> None:
        """Entree de dette perimee (symbole supprime ou enfin lu) = a retirer."""
        stale = []
        for key in sorted(KNOWN_DEAD):
            if key in self.dead:
                continue
            if key in self.declarations:
                stale.append(f"  - {key} : a maintenant un lecteur -> le symbole est cable")
            else:
                stale.append(f"  - {key} : n'existe plus (symbole supprime ou deplace)")
        self.assertEqual(
            stale,
            [],
            msg=(
                f"{len(stale)} entree(s) KNOWN_DEAD perimee(s) :\n"
                + "\n".join(stale)
                + "\n\nComment corriger : retirer ces entrees de KNOWN_DEAD dans "
                "tests/test_contract_dead_symbols.py (la liste des morts connus ne peut "
                "que retrecir, jamais grossir)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
