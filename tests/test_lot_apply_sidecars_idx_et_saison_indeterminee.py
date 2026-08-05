"""Lot « Apply : sidecars perdus et episodes sans numero » — issues #874 et #613.

Les deux defauts vivent sur le CHEMIN DESTRUCTIF (l'apply deplace reellement des
fichiers), donc toutes les assertions lisent le DISQUE apres un apply
`dry_run=False`, jamais un dict de previsualisation.

#874 — `SIDE_EXTS_DEFAULT` listait `.sub` mais pas `.idx`. Or un sous-titre
VobSub est une paire ATOMIQUE : `.sub` porte les images, `.idx` les timings et
les offsets. Un `.sub` prive de son `.idx` est illisible. Les deux sites qui
deplacent des fichiers a partir de `cfg.side_exts` sont couverts ici :
`domain/core.classify_sidecars` (item de collection, episode TV) et
`app/apply_core.is_managed_merge_file` (fusion de dossiers).

#613 — `int(row.tv_season or 0)` confondait « saison indeterminee » (`None`) et
« saison 0 » (les specials, une saison legitime). Un episode a saison inconnue
etait range en silence dans `Saison 00`. Sens restrictif : refus bruyant. Les
tests verrouillent AUSSI les deux cas qu'un correctif trop large casserait —
saison 0 et numero d'episode inconnu doivent continuer a etre ranges.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class _ApplyOnDiskBase(unittest.TestCase):
    """Base : bibliotheque tmpdir + apply REEL (dry_run=False) + lecture disque."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_lot_idx_saison_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs: List[Tuple[str, str]] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _write(self, path: Path, data: bytes = b"X" * 4096) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _cfg(self, **kwargs: Any) -> core.Config:
        kwargs.setdefault("enable_collection_folder", False)
        return core.Config(root=self.root, **kwargs).normalized()

    @staticmethod
    def _disk_names(directory: Path) -> Set[str]:
        return {p.name for p in directory.iterdir()}

    def _all_files(self) -> List[Path]:
        return sorted(p for p in self.root.rglob("*") if p.is_file())

    def _row(
        self,
        row_id: str,
        kind: str,
        folder: Path,
        video: str,
        title: str,
        year: int,
        **extra: Any,
    ) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind=kind,
            folder=str(folder),
            video=video,
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=90,
            confidence_label="high",
            candidates=[],
            **extra,
        )

    def _apply(self, cfg: core.Config, rows: List[core.PlanRow]) -> core.ApplyResult:
        decisions: Dict[str, Dict[str, object]] = {
            r.row_id: {"ok": True, "title": r.proposed_title, "year": r.proposed_year} for r in rows
        }
        return apply_core.apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            decision_presence={r.row_id for r in rows},
        )


class VobSubPairSurvitAuDeplacementTests(_ApplyOnDiskBase):
    """#874 : la paire VobSub `.sub` + `.idx` ne doit jamais etre disloquee."""

    FILM = "Le.Cinquieme.Element.1997.1080p.BluRay.x264-GROUP.mkv"
    SUB = "Le.Cinquieme.Element.1997.1080p.BluRay.x264-GROUP.fr.sub"
    IDX = "Le.Cinquieme.Element.1997.1080p.BluRay.x264-GROUP.fr.idx"

    def test_le_defaut_de_config_reconnait_les_deux_moities_de_la_paire(self) -> None:
        """Garde de contrat : la table effective (apres `normalized()`) les a toutes deux."""
        side = self._cfg().side_exts
        self.assertIn(".sub", side)
        self.assertIn(".idx", side, "`.idx` absent de cfg.side_exts : la paire VobSub sera cassee")

    def test_item_de_collection_emporte_la_paire_complete(self) -> None:
        """Site 1 : `domain/core.classify_sidecars` (dossier PARTAGE -> sous-dossier)."""
        folder = self._write(self.root / "A trier" / self.FILM).parent
        self._write(folder / self.SUB, b"vobsub-bitmap")
        self._write(folder / self.IDX, b"# VobSub index\ntimestamp: 00:00:00:000\n")
        # Une 2e video, sinon le dossier n'est pas un dossier de collection credible.
        self._write(folder / "Autre.Film.2001.1080p.mkv")

        cfg = self._cfg()
        rows = [self._row("c1", "collection", folder, self.FILM, "Le Cinquieme Element", 1997)]
        self._apply(cfg, rows)

        target = folder / "Le Cinquieme Element (1997)"
        self.assertTrue(target.is_dir(), f"sous-dossier attendu ; arbo={self._all_files()}")
        self.assertEqual(
            self._disk_names(target),
            {self.FILM, self.SUB, self.IDX},
            "#874 : `.idx` doit suivre la video comme `.sub` — une paire VobSub disloquee est illisible",
        )
        self.assertNotIn(
            self.IDX,
            self._disk_names(folder),
            "#874 : le `.idx` est reste dans le dossier source alors que le `.sub` est parti",
        )

    def test_episode_tv_emporte_la_paire_complete(self) -> None:
        """Site 1 bis : meme helper, chemin TV (`apply_tv_episode`)."""
        ep = "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.mkv"
        ep_sub = "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.fr.sub"
        ep_idx = "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.fr.idx"
        folder = self._write(self.root / "Breaking.Bad.S01" / ep).parent
        self._write(folder / ep_sub, b"vobsub-bitmap")
        self._write(folder / ep_idx, b"# VobSub index\n")

        cfg = self._cfg()
        rows = [
            self._row(
                "tv1",
                "tv_episode",
                folder,
                ep,
                "Breaking Bad",
                2008,
                tv_series_name="Breaking Bad",
                tv_season=1,
                tv_episode=1,
            )
        ]
        self._apply(cfg, rows)

        season_dir = self.root / "Breaking Bad (2008)" / "Saison 01"
        self.assertTrue(season_dir.is_dir(), f"arborescence serie attendue ; arbo={self._all_files()}")
        self.assertEqual(
            self._disk_names(season_dir),
            {ep, ep_sub, ep_idx},
            "#874 : la paire VobSub doit suivre l'episode en entier",
        )

    def test_fusion_de_dossiers_prend_le_idx_en_compte(self) -> None:
        """Site 2 : `apply_core.is_managed_merge_file` (via `merge_dir_safe`).

        Un `.idx` non reconnu n'etait pas un fichier « gere » : la fusion le
        laissait en source (ou l'expediait en `_leftovers`), separe de son `.sub`.
        """
        src_dir = self._write(self.root / "Source" / self.FILM).parent
        self._write(src_dir / self.SUB, b"vobsub-bitmap")
        self._write(src_dir / self.IDX, b"# VobSub index\n")
        dst_dir = self.root / "Le Cinquieme Element (1997)"
        dst_dir.mkdir(parents=True, exist_ok=True)

        review = self.root / "_review"
        res = core.ApplyResult()
        apply_core.merge_dir_safe(
            self._cfg(),
            src_dir,
            dst_dir,
            dry_run=False,
            log=self._log,
            res=res,
            conflicts_root=review / "_conflicts",
            conflicts_sidecars_root=review / "_conflicts_sidecars",
            duplicates_identical_root=review / "_duplicates_identical",
            leftovers_root=review / "_leftovers",
        )

        self.assertIn(
            self.IDX,
            self._disk_names(dst_dir),
            f"#874 : le `.idx` n'a pas suivi la fusion ; arbo={self._all_files()}",
        )
        self.assertIn(self.SUB, self._disk_names(dst_dir))
        leftovers = [p for p in (review / "_leftovers").rglob("*") if p.is_file()]
        self.assertEqual(
            [p.name for p in leftovers],
            [],
            "#874 : le `.idx` a ete traite comme un dechet non gere au lieu d'un sidecar",
        )


class SaisonTvIndetermineeTests(_ApplyOnDiskBase):
    """#613 : une saison inconnue ne doit pas fabriquer une destination."""

    EP = "Une.Serie.Episode.12.1080p.mkv"

    def _tv_row(self, row_id: str, folder: Path, video: str, **extra: Any) -> core.PlanRow:
        return self._row(row_id, "tv_episode", folder, video, "Une Serie", 2010, tv_series_name="Une Serie", **extra)

    def test_saison_none_refuse_le_move_et_le_dit(self) -> None:
        """Saison indeterminee : le fichier RESTE en place, avec une raison nommee."""
        folder = self._write(self.root / "Une.Serie" / self.EP).parent

        cfg = self._cfg()
        res = self._apply(cfg, [self._tv_row("tv-none", folder, self.EP, tv_season=None, tv_episode=12)])

        self.assertEqual(
            self._disk_names(folder),
            {self.EP},
            f"#613 : l'episode a bouge alors que sa saison est inconnue ; arbo={self._all_files()}",
        )
        self.assertFalse(
            (self.root / "Une Serie (2010)").exists(),
            "#613 : une arborescence de serie a ete fabriquee sur une saison inconnue",
        )
        self.assertEqual(
            res.skip_reasons.get(core.SKIP_REASON_TV_SAISON_INDETERMINEE),
            1,
            f"#613 : refus non impute a la bonne raison ; skip_reasons={res.skip_reasons}",
        )
        self.assertTrue(
            any("SAISON TV INDETERMINEE" in str(m) for m in res.error_messages),
            f"#613 : refus SILENCIEUX cote UI ; error_messages={res.error_messages}",
        )

    def test_saison_zero_est_une_saison_legitime_et_reste_rangee(self) -> None:
        """Anti-correctif-nuisible : `Saison 00` = specials Kodi/Jellyfin, pas un fallback.

        Une garde ecrite `if not season` (au lieu de `is None`) refuserait les
        specials — c'est-a-dire casserait un rangement correct.
        """
        special = "Une.Serie.S00E03.1080p.mkv"
        folder = self._write(self.root / "Une.Serie.Specials" / special).parent

        cfg = self._cfg()
        res = self._apply(cfg, [self._tv_row("tv-zero", folder, special, tv_season=0, tv_episode=3)])

        season_dir = self.root / "Une Serie (2010)" / "Saison 00"
        self.assertTrue(
            season_dir.is_dir(),
            f"#613 : la saison 0 (specials) doit rester rangeable ; arbo={self._all_files()}",
        )
        self.assertEqual(self._disk_names(season_dir), {special})
        self.assertNotIn(core.SKIP_REASON_TV_SAISON_INDETERMINEE, res.skip_reasons)

    def test_numero_d_episode_inconnu_ne_bloque_pas_le_rangement(self) -> None:
        """Anti-correctif-nuisible : le numero d'episode n'entre dans AUCUN segment du chemin.

        Depuis que le fichier garde son nom source, la cible est
        `Serie (annee)/Saison NN/<nom source>`. Refuser sur `episode is None`
        bloquerait un rangement par ailleurs entierement correct.
        """
        ep = "Une.Serie.Saison.2.1080p.mkv"
        folder = self._write(self.root / "Une.Serie.S02" / ep).parent

        cfg = self._cfg()
        res = self._apply(cfg, [self._tv_row("tv-noep", folder, ep, tv_season=2, tv_episode=None)])

        season_dir = self.root / "Une Serie (2010)" / "Saison 02"
        self.assertTrue(
            season_dir.is_dir(),
            f"#613 : un numero d'episode inconnu ne doit pas bloquer le move ; arbo={self._all_files()}",
        )
        self.assertEqual(self._disk_names(season_dir), {ep})
        self.assertEqual(res.skip_reasons, {}, f"aucun skip attendu ; vu={res.skip_reasons}")

    def test_la_raison_de_skip_a_un_libelle_francais(self) -> None:
        """Sans libelle, le resume d'application afficherait le code brut."""
        self.assertIn(core.SKIP_REASON_TV_SAISON_INDETERMINEE, core.SKIP_REASON_LABELS_FR)


class PlanSignalSaisonInconnueTests(unittest.TestCase):
    """#613 : le refus doit etre annonce AVANT l'apply, par un warning_flag de plan."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_lot_plan_saison_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plan(self, folder_name: str, video_name: str) -> Optional[core.PlanRow]:
        from cinesort.app.plan_support_replan import _plan_tv_episode

        folder = self.root / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        video = folder / video_name
        video.write_bytes(b"X" * 4096)
        cfg = core.Config(root=self.root, enable_tmdb=False).normalized()
        rows = _plan_tv_episode(cfg, folder, video, None, lambda _lvl, _msg: None)
        return rows[0] if rows else None

    def test_episode_sans_saison_porte_le_flag(self) -> None:
        row = self._plan("Une.Serie", "Une.Serie.Episode.12.1080p.mkv")
        self.assertIsNotNone(row, "le pattern « Episode N » doit produire une row TV")
        assert row is not None
        self.assertIsNone(row.tv_season, "pre-condition : ce pattern ne resout pas la saison")
        self.assertIn(
            "tv_season_unknown",
            row.warning_flags,
            f"#613 : aucun signal en amont de l'apply ; flags={row.warning_flags}",
        )

    def test_episode_avec_saison_ne_porte_pas_le_flag(self) -> None:
        row = self._plan("Une.Serie.S02", "Une.Serie.S02E05.1080p.mkv")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.tv_season, 2)
        self.assertNotIn(
            "tv_season_unknown",
            row.warning_flags,
            f"faux positif : la saison est connue ; flags={row.warning_flags}",
        )

    def test_saison_zero_ne_porte_pas_le_flag(self) -> None:
        """Anti-correctif-nuisible cote plan : `not season` flaggerait les specials."""
        row = self._plan("Une.Serie.Specials", "Une.Serie.S00E03.1080p.mkv")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.tv_season, 0, "pre-condition : S00E03 resout bien la saison 0")
        self.assertNotIn(
            "tv_season_unknown",
            row.warning_flags,
            f"la saison 0 (specials) est determinee, pas inconnue ; flags={row.warning_flags}",
        )


if __name__ == "__main__":
    unittest.main()
