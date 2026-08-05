"""Regressions mesurees en conditions reelles (scan + apply sur bac a sable).

Deux defauts distincts, tous deux constates en faisant tourner CineSort :

1. MUTILATION DE TITRE. Le dossier `Le.Parrain.Trilogie.1972-1990/` contenant
   trois .mkv produisait, avant correctif :
       Le Parrain Trilogie 1972-1990 (1972)
       Le Parrain Trilogie 1972-1990 (1974)
       Le Parrain Trilogie 1972      (1990)   <- « -1990 » AMPUTE
   La borne haute d'une PLAGE d'annees etait lue comme une annee de queue
   redondante et retiree du titre. Comme l'apply DEPLACE, les trois films de la
   meme trilogie finissaient sur disque dans trois dossiers de noms differents,
   dont un FAUX, avec `errors = 0`.

2. DOSSIERS PREFIXES `_` AVALES EN SILENCE. `_A trier`,
   `_Nouveaux telechargements`, `_Films 2026` etaient ecartes du scan sans
   compteur (`scan_diagnostic.folders_rejected_underscore = 0`) et sans aucune
   ligne de journal : leurs films n'etaient jamais tries et rien ne disait
   pourquoi.

Les assertions portent sur le COMPORTEMENT observe (noms de dossiers reellement
crees sur disque, valeur du compteur, contenu du journal), jamais sur une chaine
de code source.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
import cinesort.domain.scan_helpers as scan_helpers
from cinesort.app.apply_core import apply_rows
from cinesort.domain.naming import build_naming_context, format_movie_folder

_DEFAULT_TEMPLATE = "{title} ({year})"


def _folder_name_for(title: str, year: int, template: str = _DEFAULT_TEMPLATE) -> str:
    """Nom de dossier reellement produit par le moteur de nommage."""
    return format_movie_folder(template, build_naming_context(title=title, year=year))


class _LogCollector:
    """Callback de log de plan_library : accumule (niveau, message)."""

    def __init__(self) -> None:
        self.entries: List[Tuple[str, str]] = []

    def __call__(self, level: str, message: str) -> None:
        self.entries.append((str(level), str(message)))

    def messages(self) -> List[str]:
        return [msg for _lvl, msg in self.entries]


def _plan(root: Path, log: Any = None) -> Tuple[List[Any], Any]:
    """Scan reel de *root* via plan_library (TMDb desactive, seuil de taille a 1 octet)."""
    cfg = core.Config(root=root, enable_tmdb=False, min_video_bytes=1).normalized()
    rows, stats = plan_support.plan_library(
        cfg,
        tmdb=None,
        log=log if log is not None else (lambda *_a: None),
        progress=lambda *_a: None,
    )
    return rows, stats


class TitreAvecPlageDAnneesTests(unittest.TestCase):
    """Defaut 1 : une plage d'annees dans le titre ne doit JAMAIS etre amputee."""

    def test_apply_reel_ecrit_trois_dossiers_coherents_pour_une_trilogie(self) -> None:
        """Scan + apply REELS : les 3 soeurs gardent le titre complet et identique.

        C'est la reproduction exacte du constat : avant correctif, la 3e ligne
        atterrissait dans `Le Parrain Trilogie 1972 (1990)`.
        """
        with tempfile.TemporaryDirectory(prefix="cs_trilogie_") as tmp:
            root = Path(tmp)
            source = root / "Le.Parrain.Trilogie.1972-1990"
            source.mkdir()
            videos = [
                "Le.Parrain.1972.1080p.BluRay.x264.mkv",
                "Le.Parrain.2.1974.1080p.BluRay.x264.mkv",
                "Le.Parrain.3.1990.1080p.BluRay.x264.mkv",
            ]
            for name in videos:
                (source / name).write_bytes(b"x" * 8192)

            cfg = core.Config(root=root, enable_tmdb=False, min_video_bytes=1).normalized()
            rows, _stats = plan_support.plan_library(cfg, tmdb=None, log=lambda *_a: None, progress=lambda *_a: None)
            self.assertEqual(len(rows), 3, [r.proposed_title for r in rows])

            decisions: Dict[str, Dict[str, object]] = {
                r.row_id: {"ok": True, "title": r.proposed_title, "year": r.proposed_year} for r in rows
            }
            res = apply_rows(
                cfg,
                rows,
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=lambda *_a: None,
                decision_presence=set(decisions),
            )
            self.assertEqual(int(getattr(res, "errors", 0)), 0)

            # Dossiers de film reellement crees sur disque, sous _Collection/<source>/.
            collection_dir = root / cfg.collection_root_name / source.name
            self.assertTrue(collection_dir.is_dir(), sorted(p.name for p in root.iterdir()))
            crees = sorted(p.name for p in collection_dir.iterdir() if p.is_dir())
            self.assertEqual(
                crees,
                [
                    "Le Parrain Trilogie 1972-1990 (1972)",
                    "Le Parrain Trilogie 1972-1990 (1974)",
                    "Le Parrain Trilogie 1972-1990 (1990)",
                ],
                crees,
            )

            # Coherence entre lignes soeurs : un seul et meme titre avant l'annee.
            titres = {nom.rsplit(" (", 1)[0] for nom in crees}
            self.assertEqual(titres, {"Le Parrain Trilogie 1972-1990"}, titres)

            # Regle inviolable : le fichier video n'est jamais renomme.
            fichiers = sorted(p.name for p in collection_dir.rglob("*.mkv"))
            self.assertEqual(fichiers, sorted(videos), fichiers)

    def test_les_variantes_de_separateur_de_plage_sont_toutes_preservees(self) -> None:
        """Aucun separateur de plage n'ouvre de trou : la garde ne les regarde pas.

        Le correctif ne detecte PAS les plages (chaque separateur oublie rouvrirait
        le defaut) : il refuse tout retrait des qu'un titre porte plus d'un jeton
        d'annee. Ces variantes doivent donc toutes passer intactes.
        """
        cas = [
            ("Le Parrain Trilogie 1972-1990", 1990),
            ("Alien Anthology 1979-1997", 1997),
            ("Star Wars 1977 - 2019", 2019),
            ("Trilogie 1972–1990", 1990),  # en dash
            ("Coffret 1972 a 1990", 1990),
            ("Integrale 1972 1974 1990", 1990),
            ("Retro (1985) Collection 1985", 1985),
        ]
        for titre, annee in cas:
            with self.subTest(titre=titre):
                obtenu = _folder_name_for(titre, annee)
                self.assertEqual(obtenu, f"{titre} ({annee})", obtenu)

    def test_le_titre_complet_survit_quelle_que_soit_l_annee_de_la_ligne(self) -> None:
        """Meme titre + annees differentes -> meme titre en sortie (coherence soeurs).

        C'etait le coeur de l'incoherence mesuree : seule la ligne dont l'annee
        egalait la borne haute de la plage etait mutilee.
        """
        titre = "Le Parrain Trilogie 1972-1990"
        rendus = {annee: _folder_name_for(titre, annee) for annee in (1972, 1974, 1990)}
        self.assertEqual(
            {nom.rsplit(" (", 1)[0] for nom in rendus.values()},
            {titre},
            rendus,
        )

    def test_la_deduplication_d_annee_simple_reste_active(self) -> None:
        """Le correctif ne doit pas reintroduire "Titre 2010 (2010)".

        Un titre a UN SEUL jeton d'annee garde le comportement historique.
        """
        cas = [
            ("Old Name 2010", 2010, "Old Name (2010)"),
            ("Inception 2010", 2010, "Inception (2010)"),
            ("Le Havre 2011", 2011, "Le Havre (2011)"),
            ("Terminator 2 1991", 1991, "Terminator 2 (1991)"),
        ]
        for titre, annee, attendu in cas:
            with self.subTest(titre=titre):
                self.assertEqual(_folder_name_for(titre, annee), attendu)

    def test_les_titres_annee_non_redondants_restent_intacts(self) -> None:
        """Garde-fous historiques conserves (annee != annee de sortie, titre-annee nu)."""
        self.assertEqual(_folder_name_for("Blade Runner 2049", 2017), "Blade Runner 2049 (2017)")
        self.assertEqual(_folder_name_for("1984", 1984), "1984 (1984)")

    def test_un_template_sans_year_conserve_l_annee_du_titre(self) -> None:
        """Backward compat : sans {year} dans le template, rien n'est retire."""
        self.assertEqual(_folder_name_for("Le Havre 2011", 2011, "{title}"), "Le Havre 2011")


class DossiersPrefixesUnderscoreTests(unittest.TestCase):
    """Defaut 2 : le compteur doit compter et le journal doit NOMMER les ecartes."""

    _UNDERSCORE = ("_A trier", "_Nouveaux telechargements", "_Films 2026")

    def _sandbox(self, tmp: str) -> Path:
        root = Path(tmp)
        for nom in self._UNDERSCORE:
            d = root / nom
            d.mkdir()
            (d / "Le.Fabuleux.Destin.2001.1080p.mkv").write_bytes(b"x" * 8192)
        temoin = root / "Inception (2010)"
        temoin.mkdir()
        (temoin / "Inception.2010.1080p.mkv").write_bytes(b"x" * 8192)
        return root

    def test_le_compteur_de_diagnostic_compte_vraiment(self) -> None:
        """`folders_rejected_underscore` valait 0 alors que 3 dossiers etaient avales."""
        with tempfile.TemporaryDirectory(prefix="cs_underscore_") as tmp:
            root = self._sandbox(tmp)
            _rows, stats = _plan(root)
            self.assertEqual(int(stats.folders_rejected_underscore), 3)
            self.assertEqual(
                int((stats.analyse_ignores_par_raison or {}).get("ignore_prefix_underscore", 0)),
                3,
            )

    def test_le_journal_nomme_chaque_dossier_ecarte(self) -> None:
        """Aucun log ne contenait « ignor »/« rejet »/« exclu » : les films disparaissaient."""
        with tempfile.TemporaryDirectory(prefix="cs_underscore_log_") as tmp:
            root = self._sandbox(tmp)
            log = _LogCollector()
            _plan(root, log=log)

            explicites = [
                msg
                for msg in log.messages()
                if any(marqueur in msg.lower() for marqueur in ("ignor", "rejet", "exclu"))
            ]
            self.assertTrue(explicites, log.messages())
            joint = " | ".join(explicites)
            for nom in self._UNDERSCORE:
                self.assertIn(nom, joint, joint)

    def test_l_ensemble_des_dossiers_reellement_scannes_est_inchange(self) -> None:
        """L'exception de COMPTAGE ne doit ecarter (ni reintegrer) aucun dossier.

        `empty_folders_folder_name` est configurable : renomme SANS `_`, il n'a
        jamais ete un nom reserve pour le scan et doit rester analyse comme
        n'importe quel dossier utilisateur. Un correctif qui filtrerait sur le
        nom AVANT le test du prefixe le ferait disparaitre en silence — soit
        exactement le defaut qu'on corrige, deplace ailleurs.
        """
        with tempfile.TemporaryDirectory(prefix="cs_perimetre_") as tmp:
            root = Path(tmp)
            for nom in ("Vide", "Corbeille"):
                d = root / nom
                d.mkdir()
                (d / "Le.Fabuleux.Destin.2001.1080p.mkv").write_bytes(b"x" * 8192)

            cfg = core.Config(
                root=root,
                enable_tmdb=False,
                min_video_bytes=1,
                empty_folders_folder_name="Vide",
            ).normalized()
            candidats = {Path(p).name for p in scan_helpers.discover_candidate_folders(cfg)}
            self.assertIn("Vide", candidats, candidats)
            self.assertIn("Corbeille", candidats, candidats)

    def test_les_dossiers_de_travail_de_cinesort_ne_sont_ni_comptes_ni_nommes(self) -> None:
        """`_Collection` / `_Vide` / `_review` ne sont pas des dossiers de l'utilisateur.

        Les compter rendrait le compteur menteur dans l'autre sens et le journal
        accuserait CineSort d'avoir ignore ses propres dossiers de travail.
        """
        with tempfile.TemporaryDirectory(prefix="cs_internes_") as tmp:
            root = Path(tmp)
            cfg_ref = core.Config(root=root).normalized()
            internes = (cfg_ref.collection_root_name, cfg_ref.empty_folders_folder_name, "_review")
            for nom in (*internes, "_A trier"):
                d = root / nom
                d.mkdir()
                (d / "Film.2001.1080p.mkv").write_bytes(b"x" * 8192)

            log = _LogCollector()
            _rows, stats = _plan(root, log=log)

            self.assertEqual(int(stats.folders_rejected_underscore), 1)
            joint = " | ".join(log.messages())
            self.assertIn("_A trier", joint, joint)
            for interne in internes:
                self.assertNotIn(interne, joint, joint)

    def test_aucun_faux_positif_sans_dossier_underscore(self) -> None:
        """Bibliotheque propre : compteur a 0 et aucune ligne alarmiste."""
        with tempfile.TemporaryDirectory(prefix="cs_propre_") as tmp:
            root = Path(tmp)
            f = root / "Inception (2010)"
            f.mkdir()
            (f / "Inception.2010.1080p.mkv").write_bytes(b"x" * 8192)

            log = _LogCollector()
            _rows, stats = _plan(root, log=log)
            self.assertEqual(int(stats.folders_rejected_underscore), 0)
            self.assertFalse(
                [msg for msg in log.messages() if "préfixé" in msg],
                log.messages(),
            )

    def test_discover_candidate_folders_alimente_le_dict_de_chemins(self) -> None:
        """Contrat de `rejected_paths` : chemins COMPLETS, pas seulement des noms."""
        with tempfile.TemporaryDirectory(prefix="cs_rejected_paths_") as tmp:
            root = self._sandbox(tmp)
            cfg = core.Config(root=root, enable_tmdb=False, min_video_bytes=1).normalized()
            rejected: Dict[str, List[str]] = {}
            stats = core.Stats()
            scan_helpers.discover_candidate_folders(cfg, stats=stats, rejected_paths=rejected)

            chemins = rejected.get("ignore_prefix_underscore") or []
            self.assertEqual(
                sorted(Path(p).name for p in chemins),
                sorted(self._UNDERSCORE),
                chemins,
            )
            for p in chemins:
                self.assertTrue(Path(p).is_absolute(), p)

    def test_l_echantillon_de_chemins_est_borne_mais_le_compteur_reste_exact(self) -> None:
        """Une racine pathologique ne doit ni gonfler la memoire ni fausser le compte."""
        total = scan_helpers._REJECT_PATH_SAMPLE_MAX + 7
        with tempfile.TemporaryDirectory(prefix="cs_borne_") as tmp:
            root = Path(tmp)
            for idx in range(total):
                d = root / f"_transit {idx:03d}"
                d.mkdir()
                (d / "Film.2001.1080p.mkv").write_bytes(b"x" * 8192)

            cfg = core.Config(root=root, enable_tmdb=False, min_video_bytes=1).normalized()
            rejected: Dict[str, List[str]] = {}
            stats = core.Stats()
            scan_helpers.discover_candidate_folders(cfg, stats=stats, rejected_paths=rejected)

            self.assertEqual(
                int(stats.analyse_ignores_par_raison.get("ignore_prefix_underscore", 0)),
                total,
            )
            self.assertEqual(
                len(rejected.get("ignore_prefix_underscore") or []),
                scan_helpers._REJECT_PATH_SAMPLE_MAX,
            )

    def test_le_journal_annonce_les_dossiers_non_nommes_au_dela_de_l_echantillon(self) -> None:
        """Le log ne doit pas laisser croire qu'il a tout liste."""
        total = scan_helpers._REJECT_PATH_SAMPLE_MAX + 7
        with tempfile.TemporaryDirectory(prefix="cs_borne_log_") as tmp:
            root = Path(tmp)
            for idx in range(total):
                d = root / f"_transit {idx:03d}"
                d.mkdir()
                (d / "Film.2001.1080p.mkv").write_bytes(b"x" * 8192)

            log = _LogCollector()
            _rows, stats = _plan(root, log=log)
            self.assertEqual(int(stats.folders_rejected_underscore), total)
            joint = " | ".join(log.messages())
            self.assertIn(str(total), joint, joint)
            self.assertIn("autre", joint, joint)


if __name__ == "__main__":
    unittest.main()
