"""REGLE INVIOLABLE n1 — le fichier video n'est JAMAIS renomme, seuls les DOSSIERS.

Le nom d'un fichier video doit rester synchrone avec son torrent : le renommer
casse le seeding. Une verification par `apply` REELS a trouve trois violations,
que ce module verrouille par des assertions sur le DISQUE (le nom d'entree lu par
`iterdir()` apres un apply reel, pas un dict de previsualisation) :

1. `lowercase_extensions` reecrivait la casse du suffixe (ACTIF PAR DEFAUT) :
   `Back.To.The.Future.1985.1080p.MKV` -> `....mkv`. Le reglage a ete SUPPRIME.
2. Un episode TV etait renomme integralement :
   `Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.mkv` -> `S01E01.mkv`.
3. Une collision dans un bac `_review` suffixait le FICHIER :
   `Rocky.1976.1080p.mkv` -> `Rocky.1976.1080p_2.mkv`.

Pourquoi lire le disque : sur NTFS, `Path.exists()` est insensible a la casse.
Un test qui se contente de `exists()` ne distingue pas `.MKV` de `.mkv` — donc ne
distingue pas « rien n'a bouge » de « tout a bouge de travers ». Toutes les
assertions de casse passent donc par `_disk_names()`.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest import mock

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class _ApplyOnDiskBase(unittest.TestCase):
    """Base : bibliotheque tmpdir + apply REEL (dry_run=False) + lecture disque."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_never_rename_")
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
        """Noms d'entrees REELS du dossier (casse telle qu'ecrite sur le FS)."""
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

    def _apply(
        self,
        cfg: core.Config,
        rows: List[core.PlanRow],
        *,
        approved: bool = True,
        quarantine_unapproved: bool = False,
        marked_for_deletion_row_ids: Optional[Set[str]] = None,
    ) -> core.ApplyResult:
        decisions: Dict[str, Dict[str, object]] = {
            r.row_id: {"ok": approved, "title": r.proposed_title, "year": r.proposed_year} for r in rows
        }
        return apply_core.apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=False,
            quarantine_unapproved=quarantine_unapproved,
            log=self._log,
            decision_presence={r.row_id for r in rows},
            marked_for_deletion_row_ids=marked_for_deletion_row_ids,
        )


class ExtensionCasePreservedTests(_ApplyOnDiskBase):
    """VIOLATION 1 : la casse de l'extension source doit survivre a l'apply."""

    UPPER = "Back.To.The.Future.1985.1080p.MKV"
    LOWER = "Back.To.The.Future.Part.II.1989.1080p.mkv"
    MIXED = "Back.To.The.Future.Part.III.1990.1080p.MkV"

    def test_collection_item_preserve_la_casse_de_l_extension(self) -> None:
        """apply_collection_item : `.MKV`, `.mkv` et `.MkV` arrivent a l'identique."""
        folder = self._write(self.root / "Retour vers le futur" / self.UPPER).parent
        self._write(folder / self.LOWER)
        self._write(folder / self.MIXED)

        cfg = self._cfg()
        rows = [
            self._row("c1", "collection", folder, self.UPPER, "Retour vers le futur", 1985),
            self._row("c2", "collection", folder, self.LOWER, "Retour vers le futur 2", 1989),
            self._row("c3", "collection", folder, self.MIXED, "Retour vers le futur 3", 1990),
        ]
        self._apply(cfg, rows)

        for sub, expected in (
            ("Retour vers le futur (1985)", self.UPPER),
            ("Retour vers le futur 2 (1989)", self.LOWER),
            ("Retour vers le futur 3 (1990)", self.MIXED),
        ):
            target = folder / sub
            self.assertTrue(target.is_dir(), f"sous-dossier attendu: {target} ; arbo={self._all_files()}")
            self.assertEqual(
                self._disk_names(target),
                {expected},
                f"REGLE n1 : le nom du fichier video (extension comprise) doit etre rendu a l'identique dans {target}",
            )

    def test_quarantine_preserve_la_casse_de_l_extension(self) -> None:
        """quarantine_row : meme garantie sur le chemin de mise en quarantaine."""
        folder = self._write(self.root / "A trier" / self.UPPER).parent
        self._write(folder / self.LOWER)

        cfg = self._cfg()
        rows = [self._row("q1", "collection", folder, self.UPPER, "Retour vers le futur", 1985)]
        self._apply(cfg, rows, approved=False, quarantine_unapproved=True)

        quarantined = [p for p in (self.root / "_review").rglob("*") if p.is_file()]
        self.assertEqual(len(quarantined), 1, f"1 fichier attendu en quarantaine ; vu={quarantined}")
        self.assertEqual(
            self._disk_names(quarantined[0].parent),
            {self.UPPER},
            "REGLE n1 : la quarantaine deplace, elle ne renomme pas",
        )

    def test_le_reglage_lowercase_extensions_n_existe_plus(self) -> None:
        """Le champ Domain a disparu : plus aucun code ne peut le rebrancher.

        Sans cette garde, un `getattr(cfg, "lowercase_extensions", True)` pourrait
        etre reintroduit et retomber sur son defaut `True` sans rien casser.
        """
        self.assertFalse(hasattr(self._cfg(), "lowercase_extensions"))
        self.assertFalse(hasattr(apply_core, "_video_ext"))
        self.assertFalse(hasattr(apply_core, "_video_name_with_ext_case"))


class TvEpisodeMovedNotRenamedTests(_ApplyOnDiskBase):
    """VIOLATION 2 : un episode TV est RANGE, jamais RENOMME."""

    EP = "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.mkv"
    SUB = "Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.fr.srt"

    def test_episode_et_sidecar_gardent_leur_nom_source(self) -> None:
        folder = self._write(self.root / "Breaking.Bad.S01.COMPLETE" / self.EP).parent
        self._write(folder / self.SUB, b"1\n00:00:01,000 --> 00:00:02,000\nok\n")

        cfg = self._cfg()
        rows = [
            self._row(
                "tv1",
                "tv_episode",
                folder,
                self.EP,
                "Breaking Bad",
                2008,
                tv_series_name="Breaking Bad",
                tv_season=1,
                tv_episode=1,
                tv_episode_title="Pilot",
            )
        ]
        self._apply(cfg, rows)

        season_dir = self.root / "Breaking Bad (2008)" / "Saison 01"
        self.assertTrue(season_dir.is_dir(), f"arborescence serie attendue ; arbo={self._all_files()}")
        self.assertEqual(
            self._disk_names(season_dir),
            {self.EP, self.SUB},
            "REGLE n1 : le template TV nomme le DOSSIER (Serie (annee)/Saison NN), "
            "jamais le fichier — `S01E01 - Pilot.mkv` etait un renommage",
        )

        # Aucun fichier de la bibliotheque ne porte le nom fabrique par l'ancien code.
        fabricated = [p for p in self._all_files() if p.name.startswith("S01E01")]
        self.assertEqual(fabricated, [], f"nom d'episode fabrique detecte : {fabricated}")

    def test_episode_sans_titre_d_episode_garde_aussi_son_nom(self) -> None:
        """Branche `sans titre` de l'ancien code (`S01E01.ext`) : meme garantie."""
        folder = self._write(self.root / "Breaking.Bad.S01" / self.EP).parent

        cfg = self._cfg()
        rows = [
            self._row(
                "tv2",
                "tv_episode",
                folder,
                self.EP,
                "Breaking Bad",
                2008,
                tv_series_name="Breaking Bad",
                tv_season=1,
                tv_episode=1,
                tv_episode_title="",
            )
        ]
        self._apply(cfg, rows)

        season_dir = self.root / "Breaking Bad (2008)" / "Saison 01"
        self.assertEqual(self._disk_names(season_dir), {self.EP})

    def test_re_apply_sur_une_serie_deja_rangee_est_un_noop(self) -> None:
        """Idempotence : `src == dst` doit etre un NOOP, pas un « doublon identique ».

        La cible etant desormais `Saison NN/<nom source>`, un 2e apply retombe
        exactement sur le fichier deja range. Sans garde NOOP, la politique de
        collision comparerait le fichier a LUI-MEME, conclurait « identique » et
        l'expedierait dans `_review/_duplicates_identical` : perte de la
        bibliotheque a chaque re-apply.
        """
        season_dir = self.root / "Breaking Bad (2008)" / "Saison 01"
        self._write(season_dir / self.EP)
        self._write(season_dir / self.SUB, b"sub")

        cfg = self._cfg()
        rows = [
            self._row(
                "tv3",
                "tv_episode",
                season_dir,
                self.EP,
                "Breaking Bad",
                2008,
                tv_series_name="Breaking Bad",
                tv_season=1,
                tv_episode=1,
                tv_episode_title="Pilot",
            )
        ]
        res = self._apply(cfg, rows)

        self.assertEqual(self._disk_names(season_dir), {self.EP, self.SUB})
        self.assertEqual(res.moves, 0, "aucun deplacement ne doit avoir lieu")
        self.assertEqual(res.duplicates_identical_moved_count, 0, "l'episode n'est pas son propre doublon")
        review = self.root / "_review"
        stray = [p for p in review.rglob("*") if p.is_file()] if review.exists() else []
        self.assertEqual(stray, [], f"rien ne doit atterrir dans _review ; vu={stray}")


class ReviewBucketCollisionTests(_ApplyOnDiskBase):
    """VIOLATION 3 : une collision de bac desambiguise le DOSSIER, pas le fichier."""

    VIDEO = "Rocky.1976.1080p.mkv"

    def _two_homonym_folders(self) -> Tuple[Path, Path]:
        """Deux dossiers HOMONYMES sous des parents differents (cause racine).

        Le bac est indexe par `folder.name` seul : les deux visent le meme
        sous-dossier de destination, d'ou la collision.
        """
        first = self._write(self.root / "Collection A" / "Rocky" / self.VIDEO, b"A" * 4096).parent
        second = self._write(self.root / "Collection B" / "Rocky" / self.VIDEO, b"B" * 4096).parent
        return first, second

    def test_collision_suffixe_le_dossier_et_jamais_le_fichier(self) -> None:
        first, second = self._two_homonym_folders()
        cfg = self._cfg()
        rows = [
            self._row("m1", "extra", first, self.VIDEO, "Rocky", 1976),
            self._row("m2", "extra", second, self.VIDEO, "Rocky", 1976),
        ]
        res = self._apply(cfg, rows, marked_for_deletion_row_ids={"m1", "m2"})

        bucket = self.root / "_review" / "_user_marked_for_deletion"
        moved = sorted(p for p in bucket.rglob("*") if p.is_file())
        self.assertEqual(len(moved), 2, f"les 2 videos doivent etre dans le bac ; vu={moved}")

        # (a) AUCUN fichier n'a recu de suffixe : les deux gardent leur nom source.
        self.assertEqual(
            {p.name for p in moved},
            {self.VIDEO},
            "REGLE n1 : un fichier ne recoit JAMAIS de suffixe de collision "
            f"(`Rocky.1976.1080p_2.mkv`) ; vu={[p.name for p in moved]}",
        )

        # (b) C'est le DOSSIER qui porte l'index -> 2 dossiers distincts.
        parents = {p.parent.name for p in moved}
        self.assertEqual(len(parents), 2, f"la desambiguisation doit porter sur le dossier ; vu={parents}")
        self.assertIn("Rocky", parents)

        # (c) Aucun ECRASEMENT silencieux : les deux contenus survivent.
        self.assertEqual({p.read_bytes()[:1] for p in moved}, {b"A", b"B"})
        self.assertEqual(res.marked_for_deletion_moved_count, 2)
        self.assertFalse((first / self.VIDEO).exists())
        self.assertFalse((second / self.VIDEO).exists())

    def test_sans_desambiguisation_possible_on_abandonne_au_lieu_d_ecraser(self) -> None:
        """Cap d'essais epuise : la source reste en place, l'echec est BRUYANT.

        Sens restrictif exige sur un chemin destructif : un echec ne doit jamais
        devenir un succes silencieux, et surtout jamais un ecrasement.
        """
        first, second = self._two_homonym_folders()
        cfg = self._cfg()
        rows = [
            self._row("m1", "extra", first, self.VIDEO, "Rocky", 1976),
            self._row("m2", "extra", second, self.VIDEO, "Rocky", 1976),
        ]
        with mock.patch.object(apply_core, "_UNIQUE_PATH_MAX_ATTEMPTS", 0):
            res = self._apply(cfg, rows, marked_for_deletion_row_ids={"m1", "m2"})

        bucket = self.root / "_review" / "_user_marked_for_deletion"
        moved = sorted(p for p in bucket.rglob("*") if p.is_file())
        self.assertEqual(len(moved), 1, f"une seule video peut entrer dans le bac ; vu={moved}")
        self.assertEqual(moved[0].name, self.VIDEO)

        # La 2e source est INTACTE (ni deplacee, ni ecrasee par/ecrasant la 1ere).
        survivors = [p for p in (first / self.VIDEO, second / self.VIDEO) if p.exists()]
        self.assertEqual(len(survivors), 1, "exactement une source doit rester en place")
        self.assertEqual({moved[0].read_bytes()[:1], survivors[0].read_bytes()[:1]}, {b"A", b"B"})

        # Echec BRUYANT : compte comme erreur, message remonte a l'UI, log ERROR.
        self.assertGreaterEqual(res.errors, 1)
        self.assertTrue(any("ABANDON" in str(m) for m in res.error_messages), res.error_messages)
        self.assertTrue(any(lvl == "ERROR" and "ABANDON" in msg for lvl, msg in self.logs))
        # Pas de succes silencieux : un seul film compte comme deplace.
        self.assertEqual(res.marked_for_deletion_moved_count, 1)


class SingleMovieStillFiledTests(_ApplyOnDiskBase):
    """NON-REGRESSION : un film seul dans son dossier est toujours range."""

    VIDEO = "Inception.2010.1080p.BluRay.x264-GROUP.MKV"

    def test_dossier_renomme_fichier_intact(self) -> None:
        folder = self._write(self.root / "inception.2010.1080p" / self.VIDEO).parent
        self._write(folder / "Inception.2010.1080p.BluRay.x264-GROUP.fr.srt", b"sub")

        cfg = self._cfg()
        rows = [self._row("s1", "single", folder, self.VIDEO, "Inception", 2010)]
        res = self._apply(cfg, rows)

        target = self.root / "Inception (2010)"
        self.assertTrue(target.is_dir(), f"le DOSSIER doit etre renomme ; arbo={self._all_files()}")
        self.assertFalse(folder.exists(), "le dossier source ne doit plus exister")
        self.assertEqual(
            self._disk_names(target),
            {self.VIDEO, "Inception.2010.1080p.BluRay.x264-GROUP.fr.srt"},
            "le renommage porte sur le DOSSIER, les fichiers sont transportes tels quels",
        )
        self.assertEqual(res.renames, 1)
        self.assertEqual(res.errors, 0)

    def test_template_custom_s_applique_au_dossier_pas_au_fichier(self) -> None:
        """Garde anti-fork : un template custom nomme le dossier, jamais la video."""
        folder = self._write(self.root / "inception.2010.1080p" / self.VIDEO).parent

        cfg = self._cfg(naming_movie_template="{title}__{year}")
        rows = [self._row("s2", "single", folder, self.VIDEO, "Inception", 2010)]
        self._apply(cfg, rows)

        target = self.root / "Inception__2010"
        self.assertTrue(target.is_dir(), f"template custom non applique ; arbo={self._all_files()}")
        self.assertEqual(self._disk_names(target), {self.VIDEO})


class LegacySettingsKeyToleratedTests(unittest.TestCase):
    """Un settings.json PRE-EXISTANT contenant `lowercase_extensions` reste lisible.

    Le retrait du reglage ne doit ni faire echouer le chargement, ni faire perdre
    les autres reglages persistes (la sauvegarde est un merge read-modify-write :
    une cle inconnue est conservee telle quelle, simplement inerte).
    """

    OTHERS = {
        # `naming_preset` doit rester "custom", sinon le save reapplique les
        # templates du preset (comportement anterieur, sans rapport avec ce fix).
        "naming_preset": "custom",
        "naming_movie_template": "{title} - {year}",
        "naming_tv_template": "{series} - {year}",
        "separator": "-",
        "collection_folder_name": "_MesSagas",
        "subtitle_expected_languages": ["fr", "en"],
        "tmdb_enabled": False,
    }

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_legacy_settings_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        payload: Dict[str, Any] = {
            "root": str(self.root),
            "roots": [str(self.root)],
            "state_dir": str(self.state_dir),
            # La cle retiree, telle qu'elle existe deja chez les utilisateurs.
            "lowercase_extensions": False,
        }
        payload.update(self.OTHERS)
        (self.state_dir / "settings.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _api(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        api._state_dir = self.state_dir
        return api

    def test_get_settings_ne_perd_aucun_autre_reglage(self) -> None:
        got = self._api().settings.get_settings()
        for key, value in self.OTHERS.items():
            self.assertEqual(got.get(key), value, f"reglage perdu au chargement : {key}")
        # La cle retiree survit telle quelle (aucune purge destructive) mais
        # n'est plus alimentee par les defaults : elle est simplement inerte.
        self.assertIs(got.get("lowercase_extensions"), False)

    def test_save_settings_ne_perd_aucun_autre_reglage(self) -> None:
        api = self._api()
        got = api.settings.get_settings()
        saved = api.settings.save_settings(got)
        self.assertTrue(saved.get("ok"), saved)

        on_disk = json.loads((self.state_dir / "settings.json").read_text(encoding="utf-8-sig"))
        for key, value in self.OTHERS.items():
            self.assertEqual(on_disk.get(key), value, f"reglage perdu a la sauvegarde : {key}")
        # La cle desormais INCONNUE du backend n'est preservee que par le merge
        # read-modify-write de `_save_settings_payload_locked`. Si ce merge
        # disparaissait, toute cle non couverte par un `_save_section_*` (dont
        # les preferences UI annexes et les blobs `_orig_*`) serait effacee.
        self.assertIs(on_disk.get("lowercase_extensions"), False, "le merge read-modify-write a saute")

    def test_build_cfg_from_settings_ignore_la_cle_retiree(self) -> None:
        from cinesort.ui.api.settings_support import build_cfg_from_settings, read_settings

        cfg = build_cfg_from_settings(
            read_settings(self.state_dir),
            root=self.root,
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Dossier Nettoyage",
            state_dir=self.state_dir,
        )
        self.assertEqual(cfg.naming_movie_template, self.OTHERS["naming_movie_template"])
        self.assertEqual(cfg.separator, self.OTHERS["separator"])
        self.assertFalse(hasattr(cfg, "lowercase_extensions"))


if __name__ == "__main__":
    unittest.main()
