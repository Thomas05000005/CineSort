"""GATE — les deux reglages qui BORNENT le pipeline destructif bornent vraiment.

Constat mesure le 2026-08-03 sur un bac a sable de 5 films (application lancee,
API REST exercee, apply reel + undo) :

  (1) « Patterns d'exclusion » : reglage affiche, saisi, persiste... et sans
      AUCUN lecteur backend. Deux patterns designant deux dossiers -> plan a
      5 lignes (comme sans patterns) et apply dry-run a 5 renommages de dossier.
  (2) « Extensions video acceptees » : ADDITIF au lieu de RESTRICTIF, car
      `build_cfg_from_settings` faisait l'union avec `VIDEO_EXTS_ALL` meme quand
      l'utilisateur avait fourni sa propre liste. `.avi` retire de la liste ->
      les deux dossiers `.avi` restaient planifies et renommes.

Un reglage de perimetre qui ne borne rien est pire qu'absent : il donne une
fausse securite. Ces tests verrouillent le cablage ET ses garde-fous — le
reglage n'ayant jamais eu d'effet, aucune saisie utilisateur existante n'a
jamais ete validee, donc le cablage ne doit pas pouvoir vider une bibliotheque.

Tout passe par le VRAI systeme de fichiers, le VRAI `Config` et la VRAIE chaine
`plan_library` : aucune assertion sur du texte source.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.app._local_candidate import extract_local_candidate
from cinesort.ui.api import settings_support


def _build(root: Path, files: list[str]) -> None:
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 4096)


def _cfg(root: Path, **kwargs) -> core.Config:
    return core.Config(root=root, enable_tmdb=False, **kwargs).normalized()


def _iter(cfg: core.Config, folder: Path, stats=None) -> list[str]:
    videos = core.iter_videos(cfg, folder, min_video_bytes=1, stats=stats)
    return sorted(v.name for v in videos)


def _plan_videos(cfg: core.Config) -> list[str]:
    with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
        rows, _stats = plan_support.plan_library(
            cfg,
            tmdb=None,
            log=lambda *_a: None,
            progress=lambda *_a: None,
        )
    return sorted(row.video for row in rows)


class _LocalStatsStub:
    """Meme forme que `app/_local_candidate._LocalStats` (bucket de worker)."""

    def __init__(self) -> None:
        self.analyse_ignores_par_raison: dict[str, int] = {}


# ---------------------------------------------------------------------------
# (1) Patterns d'exclusion — cablage
# ---------------------------------------------------------------------------


class ExclusionPatternsWiringTests(unittest.TestCase):
    def test_sans_pattern_le_scan_est_inchange(self) -> None:
        """Non-regression : le defaut (aucun pattern) ne filtre rien."""
        with tempfile.TemporaryDirectory(prefix="excl_none_") as tmp:
            root = Path(tmp)
            _build(root, ["Inception (2010)/Inception.mkv", "Sauvegarde/Old (1988)/Old.avi"])
            cfg = _cfg(root)
            self.assertEqual(cfg.excluded_patterns, ())
            self.assertEqual(_plan_videos(cfg), ["Inception.mkv", "Old.avi"])

    def test_video_matchee_par_pattern_sort_du_plan(self) -> None:
        """LE defaut mesure : un dossier exclu ne produit plus aucune ligne."""
        with tempfile.TemporaryDirectory(prefix="excl_plan_") as tmp:
            root = Path(tmp)
            _build(
                root,
                [
                    "Inception (2010)/Inception.mkv",
                    "Sauvegarde/Old (1988)/Old.avi",
                    "perso/Home (2015)/Home.mkv",
                ],
            )
            cfg = _cfg(root, excluded_patterns=["Sauvegarde/*", "perso/*"])
            self.assertEqual(_plan_videos(cfg), ["Inception.mkv"])

    def test_pattern_sur_le_nom_de_fichier(self) -> None:
        with tempfile.TemporaryDirectory(prefix="excl_name_") as tmp:
            root = Path(tmp)
            _build(root, ["Film (2010)/Film.mkv", "Film (2010)/Film.partiel.tmp.mkv"])
            folder = root / "Film (2010)"
            self.assertEqual(_iter(_cfg(root), folder), ["Film.mkv", "Film.partiel.tmp.mkv"])
            self.assertEqual(_iter(_cfg(root, excluded_patterns=["*.tmp.mkv"]), folder), ["Film.mkv"])

    def test_prefixe_any_depth_matche_aussi_la_profondeur_zero(self) -> None:
        """`**/x.*` doit matcher a la racine ET en profondeur.

        `fnmatch` seul exigerait un separateur avant `x.*`, et `PurePath.match`
        ne traite `**` comme recursif qu'a partir de `full_match()` (3.13) : la
        prod tourne aussi en 3.12, on ne depend donc d'aucun des deux.
        """
        with tempfile.TemporaryDirectory(prefix="excl_depth_") as tmp:
            root = Path(tmp)
            _build(root, ["extra.mkv", "Film (2010)/extra.mkv", "Film (2010)/Film.mkv"])
            cfg = _cfg(root, excluded_patterns=["**/extra.*"])
            self.assertTrue(core.path_is_excluded(cfg, root / "extra.mkv"))
            self.assertTrue(core.path_is_excluded(cfg, root / "Film (2010)" / "extra.mkv"))
            self.assertFalse(core.path_is_excluded(cfg, root / "Film (2010)" / "Film.mkv"))

    def test_nom_de_dossier_nu_exclut_tout_son_contenu(self) -> None:
        with tempfile.TemporaryDirectory(prefix="excl_dir_") as tmp:
            root = Path(tmp)
            _build(root, ["Sauvegarde/a/b/Old.mkv", "Films/Inception.mkv"])
            cfg = _cfg(root, excluded_patterns=["Sauvegarde"])
            self.assertTrue(core.path_is_excluded(cfg, root / "Sauvegarde" / "a" / "b" / "Old.mkv"))
            self.assertFalse(core.path_is_excluded(cfg, root / "Films" / "Inception.mkv"))

    def test_pattern_absolu_fonctionne(self) -> None:
        with tempfile.TemporaryDirectory(prefix="excl_abs_") as tmp:
            root = Path(tmp)
            _build(root, ["perso/Home.mkv", "Inception.mkv"])
            absolu = str(root / "perso") + "/*"
            cfg = _cfg(root, excluded_patterns=[absolu])
            self.assertEqual(cfg.excluded_patterns, (absolu.replace("\\", "/").lower(),))
            self.assertTrue(core.path_is_excluded(cfg, root / "perso" / "Home.mkv"))
            self.assertFalse(core.path_is_excluded(cfg, root / "Inception.mkv"))

    def test_pas_de_sur_matching_sur_un_prefixe_de_nom(self) -> None:
        """`Sauvegarde` ne doit pas emporter `Sauvegardes` ni `Sauvegarde2`."""
        with tempfile.TemporaryDirectory(prefix="excl_prefix_") as tmp:
            root = Path(tmp)
            _build(root, ["Sauvegarde/A.mkv", "Sauvegardes/B.mkv", "Sauvegarde2/C.mkv"])
            cfg = _cfg(root, excluded_patterns=["Sauvegarde"])
            self.assertTrue(core.path_is_excluded(cfg, root / "Sauvegarde" / "A.mkv"))
            self.assertFalse(core.path_is_excluded(cfg, root / "Sauvegardes" / "B.mkv"))
            self.assertFalse(core.path_is_excluded(cfg, root / "Sauvegarde2" / "C.mkv"))

    def test_casse_et_antislash_indifferents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="excl_case_") as tmp:
            root = Path(tmp)
            _build(root, ["Perso/Sous/Home.mkv"])
            cfg = _cfg(root, excluded_patterns=["PERSO\\SOUS\\*"])
            self.assertTrue(core.path_is_excluded(cfg, root / "Perso" / "Sous" / "Home.mkv"))

    def test_rejet_compte_dans_les_stats_de_scan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="excl_stats_") as tmp:
            root = Path(tmp)
            _build(root, ["Film (2010)/Film.mkv", "Film (2010)/Film.tmp.mkv"])
            stats = core.Stats()
            kept = _iter(_cfg(root, excluded_patterns=["*.tmp.mkv"]), root / "Film (2010)", stats=stats)
            self.assertEqual(kept, ["Film.mkv"])
            self.assertEqual(stats.analyse_ignores_par_raison.get(core.EXCLUDE_PATTERN_REASON), 1)

    def test_chemin_parallele_applique_le_meme_filtre(self) -> None:
        """Phase 1 parallele (`extract_local_candidate`) passe par le meme point."""
        with tempfile.TemporaryDirectory(prefix="excl_par_") as tmp:
            root = Path(tmp)
            _build(root, ["Sauvegarde/Old.mkv"])
            cfg = _cfg(root, excluded_patterns=["Sauvegarde/*"], min_video_bytes=1)
            result = extract_local_candidate(root / "Sauvegarde", cfg)
            self.assertEqual(result.videos, [])
            self.assertEqual(result.ignores_par_raison.get(core.EXCLUDE_PATTERN_REASON), 1)


# ---------------------------------------------------------------------------
# (1bis) Patterns d'exclusion — garde-fous « ne pas vider la bibliotheque »
# ---------------------------------------------------------------------------


class ExclusionPatternsSafetyTests(unittest.TestCase):
    def test_patterns_non_discriminants_refuses(self) -> None:
        """Refus 1 : un pattern fait uniquement de jokers matcherait TOUT."""
        for pattern in ("*", "**", "**/*", "*/*", "*.*", ".", "..", "/", "   ", "./*"):
            with self.subTest(pattern=pattern):
                self.assertEqual(core.normalize_excluded_patterns([pattern]), ())

    def test_pattern_designant_la_racine_refuse(self) -> None:
        """Refus 2 et 3 : exclure la racine reviendrait a ne rien scanner."""
        with tempfile.TemporaryDirectory(prefix="excl_root_") as tmp:
            root = Path(tmp)
            _build(root, ["Inception (2010)/Inception.mkv"])
            racine = str(root).replace("\\", "/")
            parent_glob = str(root.parent).replace("\\", "/") + "/*"
            for pattern in (racine, racine + "/*", racine + "/**/*", parent_glob):
                with self.subTest(pattern=pattern):
                    cfg = _cfg(root, excluded_patterns=[pattern])
                    self.assertFalse(core.path_is_excluded(cfg, root / "Inception (2010)" / "Inception.mkv"))
                    self.assertEqual(_plan_videos(cfg), ["Inception.mkv"])

    def test_un_pattern_refuse_ne_desarme_pas_les_autres(self) -> None:
        with tempfile.TemporaryDirectory(prefix="excl_mix_") as tmp:
            root = Path(tmp)
            _build(root, ["Inception (2010)/Inception.mkv", "perso/Home.mkv"])
            cfg = _cfg(root, excluded_patterns=["*", "perso/*"])
            self.assertEqual(cfg.excluded_patterns, ("perso/*",))
            self.assertEqual(_plan_videos(cfg), ["Inception.mkv"])

    def test_normalisation_canonique_et_dedoublonnage(self) -> None:
        self.assertEqual(
            core.normalize_excluded_patterns(["  _Review\\*  ", "_review/*", "", None, '"perso/*"']),
            ("_review/*", "perso/*"),
        )
        self.assertEqual(core.normalize_excluded_patterns("a/*; b/* , c/*"), ("a/*", "b/*", "c/*"))
        self.assertEqual(core.normalize_excluded_patterns(None), ())
        self.assertEqual(core.normalize_excluded_patterns(42), ())


# ---------------------------------------------------------------------------
# (2) Extensions video acceptees — RESTRICTIF, pas additif
# ---------------------------------------------------------------------------


class VideoExtensionsRestrictiveTests(unittest.TestCase):
    def test_defaut_conserve_l_union_historique(self) -> None:
        """Aucune saisie -> DEFAULT | ALL (parite apply_core, `.iso` compris)."""
        attendu = set(core.VIDEO_EXTS_DEFAULT) | set(core.VIDEO_EXTS_ALL)
        self.assertEqual(settings_support.resolve_video_exts(None), attendu)
        self.assertIn(".iso", settings_support.resolve_video_exts(None))

    def test_saisie_explicite_fait_autorite_sans_union(self) -> None:
        effectif = settings_support.resolve_video_exts([".mkv", ".mp4"])
        self.assertEqual(effectif, {".mkv", ".mp4"})
        self.assertNotIn(".avi", effectif)
        self.assertNotIn(".iso", effectif)

    def test_saisie_toleree_en_chaine_et_sans_point(self) -> None:
        self.assertEqual(settings_support.resolve_video_exts("MKV; .Mp4"), {".mkv", ".mp4"})

    def test_saisie_vide_ou_illisible_retombe_sur_le_defaut(self) -> None:
        """Garde anti-bibliotheque-vide : jamais « aucune extension acceptee »."""
        attendu = set(core.VIDEO_EXTS_DEFAULT) | set(core.VIDEO_EXTS_ALL)
        for raw in ([], "", ";;;", ["", "  ", "."], {}, 7):
            with self.subTest(raw=raw):
                self.assertEqual(settings_support.resolve_video_exts(raw), attendu)

    def test_extension_retiree_sort_du_plan(self) -> None:
        """LE defaut mesure : `.avi` retire -> plus aucune ligne pour le `.avi`."""
        with tempfile.TemporaryDirectory(prefix="ext_plan_") as tmp:
            root = Path(tmp)
            _build(root, ["Inception (2010)/Inception.mkv", "Amelie (2001)/Amelie.avi"])
            self.assertEqual(_plan_videos(_cfg(root)), ["Amelie.avi", "Inception.mkv"])
            restreint = _cfg(root, video_exts=settings_support.resolve_video_exts([".mkv"]))
            self.assertEqual(_plan_videos(restreint), ["Inception.mkv"])


# ---------------------------------------------------------------------------
# (3) Assemblage : build_cfg_from_settings et le save
# ---------------------------------------------------------------------------


class BuildCfgPerimeterTests(unittest.TestCase):
    def _build_cfg(self, **settings) -> core.Config:
        return settings_support.build_cfg_from_settings(
            dict(settings),
            root=Path("D:/Films"),
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Dossier Nettoyage",
        )

    def test_reglages_transportes_jusqu_au_config(self) -> None:
        cfg = self._build_cfg(video_exts=[".mkv"], excluded_patterns=["perso/*"])
        self.assertEqual(cfg.video_exts, {".mkv"})
        self.assertEqual(cfg.excluded_patterns, ("perso/*",))

    def test_defauts_inchanges(self) -> None:
        cfg = self._build_cfg()
        self.assertEqual(cfg.video_exts, set(core.VIDEO_EXTS_DEFAULT) | set(core.VIDEO_EXTS_ALL))
        self.assertEqual(cfg.excluded_patterns, ())

    def test_cache_incremental_desarme_quand_des_patterns_sont_actifs(self) -> None:
        """Le cache DOSSIER rejouerait des lignes d'AVANT l'exclusion.

        `cfg_signature_for_incremental` ne signe pas les patterns : sur cache
        HIT, `_try_apply_folder_cache` renvoie les rows persistees et le
        perimetre redeviendrait muet.
        """
        self.assertTrue(self._build_cfg(incremental_scan_enabled=True).incremental_scan_enabled)
        self.assertFalse(
            self._build_cfg(incremental_scan_enabled=True, excluded_patterns=["perso/*"]).incremental_scan_enabled
        )

    def test_helper_incremental_isole(self) -> None:
        self.assertTrue(settings_support.resolve_incremental_scan_enabled(True, ()))
        self.assertFalse(settings_support.resolve_incremental_scan_enabled(True, ("perso/*",)))
        self.assertFalse(settings_support.resolve_incremental_scan_enabled(False, ("perso/*",)))

    def test_save_persiste_la_forme_canonique_et_refuse_les_catch_all(self) -> None:
        saved = settings_support._save_section_sources(
            {"excluded_patterns": ["  Perso\\*  ", "*", "perso/*", "**/sample.*"]}
        )
        self.assertEqual(saved["excluded_patterns"], ["perso/*", "**/sample.*"])

    def test_save_persiste_toujours_le_miroir_video_exts(self) -> None:
        saved = settings_support._save_section_sources({"file_extensions": ".mkv;.mp4"})
        self.assertEqual(saved["file_extensions"], ["mkv", "mp4"])
        self.assertEqual(saved["video_exts"], [".mkv", ".mp4"])


if __name__ == "__main__":
    unittest.main()
