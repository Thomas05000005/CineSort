"""Issue #406 — « Auto-decider tous » faisait N allers-retours SEQUENTIELS.

Le cout reel etait bien pire que N requetes HTTP : `mark_duplicate_winner`
appelle `check_duplicates(api, run_id, {})` a CHAQUE decision, et cette recharge
refait la detection de doublons ENTIERE (relecture du plan, refusion des
decisions du disque, `_find_dups` sur toutes les lignes, enrichissement qualite,
annotation depuis la DB — cf run_flow_support.py `check_duplicates`). Decider N
groupes = N recalculs complets.

`mark_duplicate_winners_bulk` fait UNE recharge pour tout le lot.

MESURE (deterministe, deux tailles) : nombre d'appels a `check_duplicates`.
GARDES : chaque decision du lot passe par EXACTEMENT les memes refus que
l'appel unitaire (groupe perime, winner etranger, collision de cle).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import run_flow_support


class _CountingReload:
    """Substitut de `check_duplicates` qui compte ses invocations."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = 0

    def __call__(self, api, run_id, decisions):  # noqa: ARG002 - signature imposee
        self.calls += 1
        return self.payload


def _groups(count: int) -> dict:
    return {
        "ok": True,
        "groups": [
            {
                "group_key": f"g{i}",
                "rows": [{"row_id": f"r{i}a"}, {"row_id": f"r{i}b"}],
            }
            for i in range(count)
        ],
    }


def _decisions(count: int) -> list:
    return [{"group_key": f"g{i}", "winner_row_id": f"r{i}a", "notes": "auto-decide:score_v2"} for i in range(count)]


class _BulkTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_406_bulk_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()
        self.api = mock.MagicMock()
        self.api._find_run_row.return_value = ({"run_id": "run1"}, self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _decision(self, group_key: str):
        return self.store.apply.get_duplicate_decision(run_id="run1", group_key=group_key)


class BulkReloadCountTests(_BulkTestBase):
    def test_une_seule_recharge_quel_que_soit_le_nombre_de_decisions(self) -> None:
        """MESURE : appels a check_duplicates. AVANT : N. APRES : 1."""
        for count in (3, 40):
            with self.subTest(decisions=count):
                self.setUp()
                try:
                    reload_probe = _CountingReload(_groups(count))
                    with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
                        res = run_flow_support.mark_duplicate_winners_bulk(self.api, "run1", _decisions(count))
                    self.assertTrue(res["ok"], msg=str(res))
                    self.assertEqual(res["decided"], count, msg=str(res))
                    self.assertEqual(res["failed"], 0, msg=str(res))
                    self.assertEqual(
                        reload_probe.calls,
                        1,
                        f"{count} decisions doivent tenir en UNE recharge de doublons (observe : {reload_probe.calls})",
                    )
                finally:
                    self.tearDown()

    def test_reference_le_chemin_unitaire_recharge_a_chaque_appel(self) -> None:
        """Point de comparaison : l'appel unitaire recharge, lui, une fois par
        decision. C'est ce cout que le lot supprime (il reste correct et
        inchange pour une decision isolee)."""
        reload_probe = _CountingReload(_groups(5))
        with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
            for d in _decisions(5):
                run_flow_support.mark_duplicate_winner(self.api, "run1", d["group_key"], d["winner_row_id"])
        self.assertEqual(reload_probe.calls, 5)

    def test_toutes_les_decisions_sont_persistees(self) -> None:
        reload_probe = _CountingReload(_groups(3))
        with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
            run_flow_support.mark_duplicate_winners_bulk(self.api, "run1", _decisions(3))
        for i in range(3):
            read = self._decision(f"g{i}")
            assert read is not None, f"g{i} non persiste"
            self.assertEqual(read["winner_row_id"], f"r{i}a")
            self.assertEqual(list(read["loser_row_ids"]), [f"r{i}b"])


class BulkGuardsTests(_BulkTestBase):
    """Les gardes F28 doivent survivre au passage en lot."""

    def test_groupe_perime_est_refuse_sans_bloquer_le_reste(self) -> None:
        reload_probe = _CountingReload(_groups(2))  # g0, g1 seulement
        decisions = _decisions(2) + [{"group_key": "g_absent", "winner_row_id": "rXa"}]
        with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
            res = run_flow_support.mark_duplicate_winners_bulk(self.api, "run1", decisions)

        self.assertEqual(res["decided"], 2, msg=str(res))
        self.assertEqual(res["failed"], 1, msg=str(res))
        entry = next(r for r in res["results"] if r["group_key"] == "g_absent")
        self.assertFalse(entry["ok"])
        self.assertTrue(entry.get("stale"), msg=str(entry))
        self.assertIsNone(
            self._decision("g_absent"),
            "Une decision no-op (loser_row_ids=[]) ne doit JAMAIS etre persistee.",
        )

    def test_winner_etranger_au_groupe_est_refuse(self) -> None:
        reload_probe = _CountingReload(_groups(1))
        with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
            res = run_flow_support.mark_duplicate_winners_bulk(
                self.api, "run1", [{"group_key": "g0", "winner_row_id": "etranger"}]
            )
        self.assertEqual(res["failed"], 1, msg=str(res))
        self.assertIsNone(
            self._decision("g0"),
            "Un winner etranger rendrait TOUS les membres losers -> le film entier partirait au bucket _review.",
        )

    def test_collision_de_cle_ne_detruit_pas_la_decision_deja_prise(self) -> None:
        colliding = {
            "ok": True,
            "groups": [
                {"title": "Inception", "year": 2010, "rows": [{"row_id": "r1"}, {"row_id": "r2"}]},
                {"title": "Inception", "year": 2010, "rows": [{"row_id": "r3"}, {"row_id": "r4"}]},
            ],
        }
        reload_probe = _CountingReload(colliding)
        with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
            res = run_flow_support.mark_duplicate_winners_bulk(
                self.api,
                "run1",
                [
                    {"group_key": "inception|2010", "winner_row_id": "r1"},
                    {"group_key": "inception|2010", "winner_row_id": "r3"},
                ],
            )
        self.assertEqual(res["decided"], 1, msg=str(res))
        self.assertEqual(res["failed"], 1, msg=str(res))
        second = res["results"][1]
        self.assertIs(second.get("ambiguous_group_key"), True, msg=str(second))
        read = self._decision("inception|2010")
        assert read is not None
        self.assertEqual(read["winner_row_id"], "r1", "La 1re decision doit survivre.")

    def test_reload_en_echec_refuse_tout_le_lot_sans_rien_persister(self) -> None:
        with mock.patch.object(
            run_flow_support,
            "check_duplicates",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            res = run_flow_support.mark_duplicate_winners_bulk(self.api, "run1", _decisions(3))
        self.assertEqual(res["decided"], 0, msg=str(res))
        self.assertEqual(res["failed"], 3, msg=str(res))
        for i in range(3):
            self.assertIsNone(self._decision(f"g{i}"))

    def test_entrees_invalides_comptent_en_echec(self) -> None:
        reload_probe = _CountingReload(_groups(1))
        with mock.patch.object(run_flow_support, "check_duplicates", reload_probe):
            res = run_flow_support.mark_duplicate_winners_bulk(
                self.api,
                "run1",
                [{"group_key": "g0", "winner_row_id": "r0a"}, {"group_key": "", "winner_row_id": "x"}, "pas un dict"],
            )
        self.assertEqual(res["decided"], 1, msg=str(res))
        self.assertEqual(res["failed"], 2, msg=str(res))

    def test_run_inconnu_est_refuse(self) -> None:
        self.api._find_run_row.return_value = None
        res = run_flow_support.mark_duplicate_winners_bulk(self.api, "run-inconnu", _decisions(1))
        self.assertFalse(res["ok"], msg=str(res))

    def test_decisions_non_liste_est_refuse(self) -> None:
        res = run_flow_support.mark_duplicate_winners_bulk(self.api, "run1", {"g0": "r0a"})
        self.assertFalse(res["ok"], msg=str(res))


class BulkParityWithSingleTests(_BulkTestBase):
    """Le lot doit produire EXACTEMENT ce que produirait la boucle unitaire."""

    def test_meme_resultat_que_n_appels_unitaires(self) -> None:
        payload = _groups(4)
        decisions = _decisions(4)

        with mock.patch.object(run_flow_support, "check_duplicates", _CountingReload(payload)):
            bulk = run_flow_support.mark_duplicate_winners_bulk(self.api, "run1", decisions)
        from_bulk = {
            d["group_key"]: self._decision(d["group_key"])
            for d in decisions  # noqa: PERF102 - lisibilite
        }

        # Meme scenario, store neuf, chemin unitaire.
        self.tearDown()
        self.setUp()
        with mock.patch.object(run_flow_support, "check_duplicates", _CountingReload(payload)):
            singles = [
                run_flow_support.mark_duplicate_winner(self.api, "run1", d["group_key"], d["winner_row_id"], "x")
                for d in decisions
            ]
        from_single = {d["group_key"]: self._decision(d["group_key"]) for d in decisions}

        self.assertTrue(all(s["ok"] for s in singles))
        self.assertEqual(bulk["decided"], len(decisions))
        for key in from_bulk:
            self.assertEqual(
                (from_bulk[key] or {}).get("winner_row_id"),
                (from_single[key] or {}).get("winner_row_id"),
                f"divergence sur {key}",
            )
            self.assertEqual(
                list((from_bulk[key] or {}).get("loser_row_ids") or []),
                list((from_single[key] or {}).get("loser_row_ids") or []),
                f"divergence sur les perdants de {key}",
            )


if __name__ == "__main__":
    unittest.main()
