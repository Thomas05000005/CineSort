"""Une REECRITURE de `plan.jsonl` ne doit jamais effacer une ligne illisible.

Audit 2026-08-17, couche `ui-api`.

`load_rows_from_plan_jsonl` refuse depuis #519 un plan ampute : sur un chemin
qui DEPLACE des dossiers de films, une ligne perdue en silence vaut un film qui
reste en place avec `errors: 0`. Deux fonctions relisaient pourtant le meme
fichier avec la politique INVERSE — `continue` muet sur une ligne illisible —
puis le REECRIVAIENT EN ENTIER :

    library_actions_support._rematch_tmdb_and_update_plan  (re-scan d'un film)
    tmdb_support.enrich_tmdb_ids_by_title                  (jaquettes post-scan)

La ligne fautive disparaissait donc du fichier, definitivement. Et avec elle le
seul temoin de la perte : le plan redevenait syntaxiquement parfait, plus rien
ne rougissait, et l'apply s'executait sur N-1 films en annoncant un succes.

Ces tests eprouvent la politique par le CONTENU DU FICHIER avant/apres, seule
grandeur honnete : ce qui compte n'est pas la valeur de retour mais le fait que
le disque n'ait pas bouge.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.ui.api import library_actions_support, run_data_support, tmdb_support
from cinesort.ui.api.run_data_support import PlanCorruptedError, read_plan_rows_as_dicts


def _ligne(row_id: str, titre: str = "Un Film", annee: int = 2001) -> str:
    return json.dumps(
        {
            "row_id": row_id,
            "folder": "C:\\Films\\Un Film (2001)",
            "video": "Un Film (2001).mkv",
            "proposed_title": titre,
            "proposed_year": annee,
            "proposed_source": "nfo",
            "confidence": 88,
        },
        ensure_ascii=False,
    )


class _FakeRunPaths:
    def __init__(self, plan_jsonl: Path) -> None:
        self.plan_jsonl = plan_jsonl


class _FakeResult:
    def __init__(self, ident: int, poster_path: str) -> None:
        self.id = ident
        self.poster_path = poster_path


class _FakeTmdb:
    """Jumeau minimal du client TMDb (meme surface que le harnais R5-H2)."""

    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping

    def search_movie(self, query, year=None, **_kw):
        res = self._mapping.get(str(query).strip().lower())
        return [res] if res else []

    def flush(self) -> None:
        return None


class LecturePourReecritureTests(unittest.TestCase):
    """Le helper partage applique EXACTEMENT la politique de #519."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_plan_rw_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.plan = Path(self._tmp) / "plan.jsonl"

    def test_plan_sain_rend_toutes_les_lignes(self) -> None:
        self.plan.write_text(_ligne("a") + "\n" + _ligne("b") + "\n", encoding="utf-8")
        rows = read_plan_rows_as_dicts(self.plan)
        self.assertEqual([r["row_id"] for r in rows], ["a", "b"])

    def test_json_casse_refuse_le_plan_et_nomme_la_ligne(self) -> None:
        self.plan.write_text(_ligne("a") + "\n{ceci n'est pas du json\n" + _ligne("b") + "\n", encoding="utf-8")
        with self.assertRaises(PlanCorruptedError) as ctx:
            read_plan_rows_as_dicts(self.plan)
        self.assertEqual(ctx.exception.invalid_lines, [2])
        self.assertEqual(ctx.exception.readable_rows, 2)

    def test_json_valide_mais_non_dict_compte_comme_perdu(self) -> None:
        """`null` / `[]` / un nombre : la ligne etait jetee SANS un mot."""
        self.plan.write_text(_ligne("a") + "\nnull\n", encoding="utf-8")
        with self.assertRaises(PlanCorruptedError) as ctx:
            read_plan_rows_as_dicts(self.plan)
        self.assertEqual(ctx.exception.invalid_lines, [2])

    def test_octet_non_utf8_compte_comme_ligne_illisible(self) -> None:
        self.plan.write_bytes(_ligne("a").encode("utf-8") + b"\n\xff\xfe casse\n" + _ligne("b").encode("utf-8") + b"\n")
        with self.assertRaises(PlanCorruptedError) as ctx:
            read_plan_rows_as_dicts(self.plan)
        self.assertEqual(ctx.exception.invalid_lines, [2])

    def test_le_fichier_entier_est_parcouru_avant_de_lever(self) -> None:
        """Le compteur doit etre COMPLET, pas « la premiere ligne qui a casse »."""
        self.plan.write_text("casse1\n" + _ligne("a") + "\ncasse2\ncasse3\n", encoding="utf-8")
        with self.assertRaises(PlanCorruptedError) as ctx:
            read_plan_rows_as_dicts(self.plan)
        self.assertEqual(ctx.exception.invalid_lines, [1, 3, 4])
        self.assertEqual(ctx.exception.invalid_count, 3)

    def test_lignes_vides_restent_tolerees(self) -> None:
        self.plan.write_text(_ligne("a") + "\n\n" + _ligne("b") + "\n", encoding="utf-8")
        self.assertEqual(len(read_plan_rows_as_dicts(self.plan)), 2)

    def test_plan_absent_leve_filenotfound(self) -> None:
        with self.assertRaises(FileNotFoundError):
            read_plan_rows_as_dicts(self.plan)

    def test_reste_un_valueerror_pour_les_appelants_existants(self) -> None:
        """Meme famille que `load_rows_from_plan_jsonl` : aucun `except` existant perdu."""
        self.assertTrue(issubclass(PlanCorruptedError, ValueError))


class _PlanCorrompuBase(unittest.TestCase):
    """Fixture commune : un plan de 3 lignes dont la 2e est illisible."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_plan_rw_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.plan = self.run_dir / "plan.jsonl"

    def _ecrire_plan_corrompu(self) -> bytes:
        brut = (_ligne("S|aaa", "12 Hommes en colere", 1957) + "\n{tronque\n" + _ligne("S|ccc") + "\n").encode("utf-8")
        self.plan.write_bytes(brut)
        return brut

    def _ecrire_plan_sain(self) -> bytes:
        brut = (_ligne("S|aaa", "12 Hommes en colere", 1957) + "\n" + _ligne("S|ccc") + "\n").encode("utf-8")
        self.plan.write_bytes(brut)
        return brut

    def _api(self):
        api = mock.MagicMock()
        api._internal_settings.return_value = {"tmdb_api_key": "abc123", "state_dir": str(self.run_dir)}
        api._run_paths_for.return_value = _FakeRunPaths(self.plan)
        return api


class EnrichissementNeMutilePlusLePlanTests(_PlanCorrompuBase):
    def test_plan_corrompu_refuse_et_fichier_INCHANGE(self) -> None:
        brut_avant = self._ecrire_plan_corrompu()
        tmdb = _FakeTmdb({"12 hommes en colere": _FakeResult(389, "/p389.jpg")})
        api = self._api()

        with mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(tmdb, None)):
            res = tmdb_support.enrich_tmdb_ids_by_title(api, "run1", ["S|aaa"])

        self.assertFalse(res.get("ok"), res)
        # Le SEUL temoin honnete : les octets du plan n'ont pas bouge.
        self.assertEqual(self.plan.read_bytes(), brut_avant)

    def test_plan_sain_reste_enrichi_comme_avant(self) -> None:
        """Contre-test : le correctif ne doit RIEN changer au cas nominal."""
        self._ecrire_plan_sain()
        tmdb = _FakeTmdb({"12 hommes en colere": _FakeResult(389, "/p389.jpg")})
        api = self._api()

        with mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(tmdb, None)):
            res = tmdb_support.enrich_tmdb_ids_by_title(api, "run1", ["S|aaa"])

        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("resolved"), 1)
        rows = {r["row_id"]: r for r in read_plan_rows_as_dicts(self.plan)}
        self.assertEqual(rows["S|aaa"].get("tmdb_id"), 389)
        self.assertEqual(len(rows), 2)


class RematchNeMutilePlusLePlanTests(_PlanCorrompuBase):
    def test_plan_corrompu_abandonne_et_fichier_INCHANGE(self) -> None:
        brut_avant = self._ecrire_plan_corrompu()
        api = self._api()

        with mock.patch.object(run_data_support, "write_plan_jsonl") as ecrivain:
            out = library_actions_support._rematch_tmdb_and_update_plan(api, "run1", "S|aaa")

        self.assertIsNone(out)
        # Le re-match n'a meme pas TENTE d'ecrire : la garde est en amont.
        ecrivain.assert_not_called()
        self.assertEqual(self.plan.read_bytes(), brut_avant)


if __name__ == "__main__":
    unittest.main()
