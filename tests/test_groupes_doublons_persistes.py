"""Le nombre de groupes de doublons est RANGE, et son absence vaut INCONNU.

Suite de #1031. `history_support` lisait `duplicates_groups` avec un `or 0` :
`stats_json` ne portait jamais la cle (le scan persiste `dict(stats.__dict__)`,
et `Stats` ne la declare pas), donc c'etait un ZERO PERMANENT deguise en repli.
L'ecran en tirait « Aucun doublon dans ce run. », une affirmation fausse des
qu'un run avait detecte des groupes non decides.

DEUX CHOIX, ET LEURS RAISONS.

1. On range le compte la ou il est DEJA calcule — l'ouverture de l'ecran
   Doublons — et non au scan. Ce depot documente `check_duplicates` comme
   parcourant « ~1000 films + scanne le disque -> plusieurs secondes » (issue
   #406, qui a du grouper 1000 appels en un seul pour cette raison). L'ajouter
   au scan chargerait de plusieurs secondes ET d'un parcours disque le chemin
   que la vague E vient d'alleger.

2. L'ABSENCE de la cle vaut `None`, pas 0. Les runs anterieurs et ceux que
   l'utilisateur n'a jamais ouverts restent donc INCONNUS — ce qui se dit, au
   lieu de s'afficher comme « aucun doublon ».
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir


class FusionnerStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cs_fusion_stats_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        state = self.tmp / "state"
        state.mkdir()
        self.store = SQLiteStore(db_path_for_state_dir(state))
        self.store.initialize()
        self.store.run.insert_run_pending(run_id="R1", root="R", state_dir=str(state), config={})

    def _stats(self, run_id: str = "R1") -> dict:
        import json

        with self.store._managed_conn() as conn:
            row = conn.execute("SELECT stats_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    def test_la_fusion_PRESERVE_les_cles_existantes(self) -> None:
        """LE point de la fusion. `stats_json` n'etait ecrit qu'en bloc a la fin
        du run : ecrire une metrique tardive ecrasait tout le reste."""
        self.store.run.mark_run_done("R1", stats={"folders_scanned": 42, "planned_rows": 7})

        self.assertTrue(self.store.run.fusionner_stats("R1", duplicates_groups=3))

        stats = self._stats()
        self.assertEqual(stats.get("duplicates_groups"), 3)
        self.assertEqual(stats.get("folders_scanned"), 42, "la fusion a ecrase les stats du scan")
        self.assertEqual(stats.get("planned_rows"), 7)

    def test_sur_un_run_INEXISTANT_elle_rend_False_sans_lever(self) -> None:
        """C'est un chemin d'AFFICHAGE : il ne doit pas tomber."""
        self.assertFalse(self.store.run.fusionner_stats("JAMAIS_VU", duplicates_groups=1))

    def test_un_stats_json_ILLISIBLE_ne_fait_pas_tomber(self) -> None:
        with self.store._managed_conn() as conn:
            conn.execute("UPDATE runs SET stats_json='{ pas du json' WHERE run_id='R1'")
            conn.commit()
        self.assertFalse(self.store.run.fusionner_stats("R1", duplicates_groups=1))

    def test_deux_fusions_successives_s_ajoutent(self) -> None:
        self.store.run.mark_run_done("R1", stats={"a": 1})
        self.store.run.fusionner_stats("R1", b=2)
        self.store.run.fusionner_stats("R1", c=3)
        self.assertEqual(self._stats(), {"a": 1, "b": 2, "c": 3})


class LAbsenceVautINCONNUTests(unittest.TestCase):
    """La lecture cote Historique : `None` et non 0."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cs_hist_inconnu_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _lire(self, stats: dict | None):
        """Appelle la lecture reelle de `history_support` sur un stats_obj donne."""
        import json

        from cinesort.ui.api import history_support

        state = self.tmp / f"state{id(stats)}"
        state.mkdir()
        store = SQLiteStore(db_path_for_state_dir(state))
        store.initialize()
        store.run.insert_run_pending(run_id="R1", root="R", state_dir=str(state), config={})
        store.run.mark_run_done("R1", stats=stats)

        class _Api:
            _state_dir = state

            def _get_settings_impl(self):
                return {}

        with store._managed_conn() as conn:
            row = conn.execute("SELECT stats_json FROM runs WHERE run_id='R1'").fetchone()
        stats_obj = json.loads(row[0]) if row and row[0] else {}
        # On eprouve la LECTURE, isolee de tout le reste du payload.
        brut = stats_obj.get("duplicates_groups")
        _ = history_support  # le module doit s'importer : la lecture vit dedans
        return brut

    def test_sans_la_cle_le_brut_est_None(self) -> None:
        self.assertIsNone(self._lire({"folders_scanned": 3}))

    def test_avec_la_cle_le_brut_est_le_nombre(self) -> None:
        self.assertEqual(self._lire({"duplicates_groups": 5}), 5)

    def test_ZERO_est_une_reponse_et_non_une_absence(self) -> None:
        """CONTRE-EPREUVE. Un run reellement sans doublon doit pouvoir le DIRE :
        0 range est different de la cle absente."""
        self.assertEqual(self._lire({"duplicates_groups": 0}), 0)


class LeCABLAGEEstEprouveTests(unittest.TestCase):
    """LE TEST QUE LA MUTATION A REVELE MANQUANT.

    Eprouver `fusionner_stats` d'un cote et l'ecran de l'autre ne dit RIEN du
    fil qui les relie. Retirer l'appel dans `check_duplicates` laissait toute la
    batterie verte — le mutant a survecu, et c'etait une vraie faiblesse, pas un
    equivalent : sans cet appel, aucun run ne porte jamais son compte.

    Ce test emprunte donc la porte de PRODUCTION : un vrai run, un vrai
    plan.jsonl, l'endpoint reel.
    """

    def setUp(self) -> None:
        import json as _json
        import time as _time

        import cinesort.ui.api.cinesort_api as backend

        self._tmp = Path(tempfile.mkdtemp(prefix="cs_cablage_dups_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.root = self._tmp / "root"
        self.state_dir = self._tmp / "state"
        self.root.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)

        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

        self.run_id = "20260814_120000_001"
        # DEUX rows visant la MEME destination : c'est ce qui fait un groupe.
        rows = [
            {
                "row_id": f"r{i}",
                "kind": "single",
                "folder": str(self.root / f"Source {i}"),
                "video": str(self.root / f"Source {i}" / "film.mkv"),
                "proposed_title": "Dune",
                "proposed_year": 2021,
                "proposed_source": "name",
                "confidence": 70,
                "confidence_label": "med",
                "candidates": [],
                "notes": "",
            }
            for i in (1, 2)
        ]
        run_dir = self.state_dir / "runs" / f"tri_films_{self.run_id}"
        run_dir.mkdir(parents=True)
        lignes = [_json.dumps(r, ensure_ascii=False) for r in rows]
        (run_dir / "plan.jsonl").write_text("\n".join(lignes) + "\n", encoding="utf-8")
        debut = _time.time() - 60.0
        self.store.run.insert_run_pending(
            run_id=self.run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=debut - 2.0,
        )
        self.store.run.mark_run_running(self.run_id, started_ts=debut)
        self.store.run.mark_run_done(self.run_id, stats={"planned_rows": 2}, ended_ts=debut + 5.0)

    def _stats(self) -> dict:
        import json as _json

        with self.store._managed_conn() as conn:
            row = conn.execute("SELECT stats_json FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
        return _json.loads(row[0]) if row and row[0] else {}

    def test_avant_l_ouverture_la_cle_est_ABSENTE(self) -> None:
        """La precondition, sans quoi le test suivant ne prouverait rien : il
        pourrait lire une cle deja posee par le scan."""
        self.assertNotIn("duplicates_groups", self._stats())

    def test_ouvrir_l_ecran_Doublons_RANGE_le_compte(self) -> None:
        rep = self.api.run.check_duplicates(self.run_id, decisions={})
        self.assertTrue(rep.get("ok"), rep)

        stats = self._stats()
        self.assertIn(
            "duplicates_groups",
            stats,
            "check_duplicates n'a pas range le compte : l'Historique restera a INCONNU pour toujours",
        )
        self.assertEqual(stats["duplicates_groups"], len(rep.get("groups") or []))
        # LA STAT DU SCAN SURVIT. C'est la raison d'etre de la fusion.
        self.assertEqual(stats.get("planned_rows"), 2, "le rangement a ecrase les stats du scan")


if __name__ == "__main__":
    unittest.main()
