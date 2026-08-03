"""F28 — mark_duplicate_winner doit etre FAIL-CLOSED quand le groupe n'est
plus present dans le run recharge.

Bug d'origine (revue post-merge 2026-07-18, F28) : la recharge interne
`check_duplicates(api, run_id, {})` refusionne les decisions du DISQUE
(validation.json) ; des qu'UN film est approuve, `_browse_all_if_none_approved`
cesse d'elargir et `find_duplicate_targets` ne groupe plus que les rows
approuves -> le groupe affiche depuis le cache UI (_groupsCache de doublons.js,
qui survit aux navigations) disparait du reload. Aucun garde : la fonction
persistait alors `loser_row_ids=[]` et renvoyait ok=True. A l'apply,
apply_support consomme les losers persistes SANS recompute et apply_core
early-return si vide -> AUCUN fichier deplace, zero erreur, toast « ✓ Decide »
mensonger.

Second trou couvert ici : un winner_row_id ETRANGER au groupe rendait TOUS les
membres losers -> le film entier partait au bucket _review.

fail-before / pass-after : ok=False + stale=True + RIEN en base.
NON-REGRESSION : un groupe present avec un winner legitime persiste comme avant.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import run_flow_support


class _MarkWinnerTestBase(unittest.TestCase):
    """Fixture partagee : store SQLite reel + api mocke (aucun test ici)."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_f28_stale_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()
        self.api = mock.MagicMock()
        self.api._find_run_row.return_value = ({"run_id": "run1"}, self.store)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _decision(self, group_key: str):
        return self.store.apply.get_duplicate_decision(run_id="run1", group_key=group_key)


class MarkDuplicateWinnerStaleGroupTests(_MarkWinnerTestBase):
    def test_groupe_absent_du_reload_est_refuse_et_ne_persiste_rien(self) -> None:
        reload_payload = {
            "ok": True,
            "groups": [
                {
                    "title": "titre",
                    "year": 1986,
                    "rows": [{"row_id": "rowX"}, {"row_id": "rowY"}],
                }
            ],
        }
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=reload_payload):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "titre|1979", "rowA")

        self.assertFalse(r["ok"], msg=str(r))
        self.assertTrue(r.get("stale"), msg=str(r))
        self.assertIsNone(
            self._decision("titre|1979"),
            "Une decision no-op (loser_row_ids=[]) ne doit JAMAIS etre persistee.",
        )

    def test_winner_absent_du_groupe_est_refuse(self) -> None:
        reload_payload = {
            "ok": True,
            "groups": [
                {
                    "group_key": "g1",
                    "rows": [{"row_id": "rowB"}, {"row_id": "rowC"}],
                }
            ],
        }
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=reload_payload):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "g1", "rowA")

        self.assertFalse(r["ok"], msg=str(r))
        self.assertIsNone(
            self._decision("g1"),
            "Un winner etranger au groupe rendrait TOUS les membres losers -> "
            "le film entier partirait au bucket _review.",
        )

    def test_reload_en_echec_ne_persiste_pas(self) -> None:
        with mock.patch.object(
            run_flow_support,
            "check_duplicates",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "g1", "rowA")

        self.assertFalse(r["ok"], msg=str(r))
        self.assertIsNone(self._decision("g1"))

    def test_groupe_present_persiste_normalement(self) -> None:
        # NON-REGRESSION : le chemin nominal reste STRICTEMENT inchange.
        # VERT avant ET apres le correctif.
        reload_payload = {
            "ok": True,
            "groups": [
                {
                    "group_key": "g1",
                    "rows": [{"row_id": "rowA"}, {"row_id": "rowB"}, {"row_id": "rowC"}],
                }
            ],
        }
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=reload_payload):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "g1", "rowA")

        self.assertTrue(r["ok"], msg=str(r))
        self.assertEqual(set(r["losers"]), {"rowB", "rowC"})
        read = self._decision("g1")
        assert read is not None
        self.assertEqual(read["winner_row_id"], "rowA")
        self.assertEqual(set(read["loser_row_ids"]), {"rowB", "rowC"})
        self.assertIs(
            r.get("no_op"),
            False,
            "Un groupe avec de vrais perdants n'est PAS un no-op.",
        )


class MarkDuplicateWinnerKeyCollisionTests(_MarkWinnerTestBase):
    """F28 (revue R1) — deux groupes REELS peuvent partager la meme cle.

    `find_duplicate_targets` groupe sur movie_key(title, year, edition) (H11)
    alors que `_group_key_for` retombe sur title|year (l'edition n'est pas dans
    le dict de groupe). Collision reproduite par execution sur le vrai
    detecteur : template '{title} ({year}) {edition-tag}' + 4 rows Inception
    2010 (2 Theatrical, 2 Extended) -> total_groups=2, meme cle
    'inception|2010' pour les DEUX.

    Le garde fail-closed s'arretait au PREMIER groupe de meme cle : le second
    devenait INDECIDABLE A VIE, avec un message trompeur (« liste perimee :
    Actualiser ») alors qu'Actualiser reproduit exactement la meme collision.
    """

    @staticmethod
    def _two_colliding_groups() -> dict:
        # Forme exacte de find_duplicate_targets : pas de 'group_key' explicite,
        # donc _group_key_for retombe sur title|year pour les DEUX groupes.
        return {
            "ok": True,
            "groups": [
                {"title": "Inception", "year": 2010, "rows": [{"row_id": "r1"}, {"row_id": "r2"}]},
                {"title": "Inception", "year": 2010, "rows": [{"row_id": "r3"}, {"row_id": "r4"}]},
            ],
        }

    def test_le_groupe_qui_contient_le_winner_est_retenu(self) -> None:
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=self._two_colliding_groups()):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "inception|2010", "r3")

        self.assertTrue(
            r["ok"],
            "Le 2e groupe de meme cle doit rester decidable : s'arreter au 1er "
            f"match en fait un cul-de-sac permanent. Recu : {r}",
        )
        self.assertEqual(r["losers"], ["r4"])
        read = self._decision("inception|2010")
        assert read is not None
        self.assertEqual(read["winner_row_id"], "r3")

    def test_collision_de_cle_ne_detruit_pas_la_decision_deja_prise(self) -> None:
        # La PK de duplicate_decisions est (run_id, group_key) : persister la 2e
        # decision ECRASERAIT la 1re (upsert DO UPDATE) et ses perdants ne
        # seraient plus deplaces a l'apply, sans aucun signal. On refuse avec un
        # message EXACT au lieu de detruire une decision utilisateur.
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=self._two_colliding_groups()):
            first = run_flow_support.mark_duplicate_winner(self.api, "run1", "inception|2010", "r1")
            second = run_flow_support.mark_duplicate_winner(self.api, "run1", "inception|2010", "r3")

        self.assertTrue(first["ok"], msg=str(first))
        self.assertFalse(second["ok"], msg=str(second))
        self.assertIs(
            second.get("ambiguous_group_key"),
            True,
            "Le refus doit nommer la VRAIE cause (collision de cle), pas "
            "« liste perimee » — Actualiser ne changerait rien.",
        )
        read = self._decision("inception|2010")
        assert read is not None
        self.assertEqual(read["winner_row_id"], "r1", "La 1re decision doit survivre.")
        self.assertEqual(list(read["loser_row_ids"]), ["r2"])

    def test_winner_absent_des_deux_groupes_reste_refuse_stale(self) -> None:
        # NON-REGRESSION : parcourir TOUS les groupes ne doit pas affaiblir le
        # garde — un winner etranger a chacun d'eux reste refuse (sinon tous les
        # membres deviendraient losers et le film entier partirait au bucket
        # _review). VERT avant ET apres le correctif.
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=self._two_colliding_groups()):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "inception|2010", "rowZ")

        self.assertFalse(r["ok"], msg=str(r))
        self.assertTrue(r.get("stale"), msg=str(r))
        self.assertIsNone(self._decision("inception|2010"))


class MarkDuplicateWinnerNoOpTests(_MarkWinnerTestBase):
    """F28 (revue R1) — le symptome d'origine subsiste pour les groupes a 1 row.

    `find_duplicate_targets` emet un groupe des qu'une copie existe DEJA sur
    disque (existing_paths), meme avec un seul row planifie. Il n'y a alors
    aucun perdant possible : la decision est enregistree mais ne deplacera RIEN
    a l'apply (apply_core early-return sur losers vide), pendant que la carte
    Doublons affiche un « ✓ Decide » inconditionnel.
    """

    def test_groupe_a_un_seul_row_est_annonce_no_op(self) -> None:
        reload_payload = {"ok": True, "groups": [{"group_key": "g1", "rows": [{"row_id": "rowA"}]}]}
        with mock.patch.object(run_flow_support, "check_duplicates", return_value=reload_payload):
            r = run_flow_support.mark_duplicate_winner(self.api, "run1", "g1", "rowA")

        self.assertTrue(r["ok"], msg=str(r))
        self.assertEqual(r["losers"], [])
        self.assertIs(
            r.get("no_op"),
            True,
            "Sans ce drapeau l'UI ne peut pas distinguer une decision qui "
            "deplace des fichiers d'une decision qui ne fera RIEN.",
        )


if __name__ == "__main__":
    unittest.main()
