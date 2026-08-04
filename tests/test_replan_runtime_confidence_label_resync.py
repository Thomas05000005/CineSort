"""Le cross-check runtime (Phase 6.1) doit resynchroniser `confidence_label`.

`_build_resolved_row` applique un bonus/malus runtime a `confidence`
(score_runtime_delta : +20 / +10 / 0 / -25) puis reconstruit la note. Avant ce
fix, le label n'etait recale que par deux gardes etroites :

    if bonus >= 10:  label = "high" if confidence >= 85 else label
    elif bonus < 0:  label = "low"  if confidence < 60  else label

soit uniquement les sauts vers les EXTREMES. La zone med (60..84) restait
perimee dans les deux sens :
  - 97/'high' penalise a 72 -> badge 'high' mensonger, sur la ligne meme qui
    porte `runtime_mismatch_likely_wrong_film` ;
  - 59/'low' remonte a 79 -> badge 'low' sous-evalue.

`confidence_label` et `notes` sont des champs STOCKES : le front recalcule son
bucket depuis la valeur numerique et n'utilise jamais `confidence_label`, qui
part tel quel dans plan.jsonl, l'export HTML/CSV/JSON et le resume de run.

Fail-before / pass-after : sans le fix, les deux tests de zone med echouent
(label 'high'/'low' au lieu de 'med', et la note dit "Confiance HIGH (72/100).").
Les trois tests de non-regression (zone grise, penalite vers low, bonus vers
high) passent des DEUX cotes : ils verrouillent le comportement deja correct.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.plan_support_replan import _build_resolved_row

_NFO_STATE = {
    "nfo_ok": True,
    "nfo_cov": 1.0,
    "nfo_seq": 1.0,
    "nfo_reject_reason": "",
    "year_delta_reject": False,
    "nfo_partial_match": False,
}


def _noop_log(_level: str, _msg: str) -> None:
    return None


class _StubTmdb:
    """Stub minimal : seul le client TMDb est simule, le code teste est reel."""

    def __init__(self, runtime_min: int) -> None:
        self._runtime = runtime_min

    def get_movie_runtime(self, _tmdb_id):
        return self._runtime

    def get_movie_collection(self, _tmdb_id):
        return None, None


class RuntimeCrossCheckLabelResyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="replan_conf_label_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, *, cand, folder_name: str, nfo_runtime: int, tmdb_runtime: int):
        cfg = core.Config(root=self.root).normalized()
        nfo = core.NfoInfo(
            title=cand.title,
            originaltitle=None,
            year=cand.year,
            tmdbid=str(cand.tmdb_id or ""),
            imdbid=None,
            runtime=nfo_runtime,
        )
        folder = self.root / folder_name
        return _build_resolved_row(
            cfg,
            folder,
            Path("movie.mkv"),
            cand,
            row_id="r1",
            kind="single",
            is_collection=False,
            folder_name=folder_name,
            cands=[cand],
            nfo=nfo,
            nfo_path=folder / "movie.nfo",
            nfo_state=dict(_NFO_STATE),
            name_year=cand.year,
            name_year_reason="folder",
            remaster_hint=False,
            tmdb_used=True,
            title_ambiguous=False,
            detected_edition=None,
            tmdb=_StubTmdb(tmdb_runtime),
            log=_noop_log,
        )

    @staticmethod
    def _strong_candidate():
        # base = 97 / 'high' (source tmdb, score 0.95, dY=0, sim=0.97)
        return core.Candidate(title="Film X", year=2000, source="tmdb", tmdb_id=42, score=0.95, note="dY=0, sim=0.97")

    @staticmethod
    def _weak_candidate():
        # base = 59 / 'low' (cap similarite < 0.60 de compute_confidence)
        return core.Candidate(title="Film Y", year=2010, source="tmdb", tmdb_id=7, score=0.10, note="dY=0, sim=0.50")

    # ---- (a) penalite -25 depuis high, atterrissage en zone med --------------
    def test_penalty_landing_in_med_zone_downgrades_label_and_note(self) -> None:
        row = self._row(
            cand=self._strong_candidate(),
            folder_name="Film X (2000)",
            nfo_runtime=90,
            tmdb_runtime=160,
        )
        self.assertEqual(row.confidence, 72, "97 - 25 = 72 (zone med)")
        self.assertEqual(row.confidence_label, "med")
        self.assertTrue(
            row.notes.startswith("Confiance MED (72/100)."),
            f"note desynchronisee du label : {row.notes!r}",
        )
        # La ligne reste bien celle marquee comme suspecte.
        self.assertIn("runtime_mismatch_likely_wrong_film", row.warning_flags)

    # ---- (b) bonus +20 depuis low, atterrissage en zone med ------------------
    def test_bonus_landing_in_med_zone_upgrades_label_and_note(self) -> None:
        row = self._row(
            cand=self._weak_candidate(),
            # Dossier NON conforme : evite le rehaussement `is_already_conform`
            # qui forcerait 90/'high' avant le cross-check runtime.
            folder_name="film.y.2010.bluray.x264",
            nfo_runtime=100,
            tmdb_runtime=101,
        )
        self.assertEqual(row.confidence, 79, "59 + 20 = 79 (zone med)")
        self.assertEqual(row.confidence_label, "med")
        self.assertTrue(
            row.notes.startswith("Confiance MED (79/100)."),
            f"note desynchronisee du label : {row.notes!r}",
        )

    # ---- (c) non-regressions : vertes AVANT comme APRES le fix ---------------
    def test_grey_zone_leaves_confidence_and_label_untouched(self) -> None:
        # delta 10 min : ni match (< 5) ni mismatch (>= 30) -> bonus 0.
        row = self._row(
            cand=self._strong_candidate(),
            folder_name="Film X (2000)",
            nfo_runtime=100,
            tmdb_runtime=110,
        )
        self.assertEqual(row.confidence, 97)
        self.assertEqual(row.confidence_label, "high")
        self.assertNotIn("runtime_mismatch_likely_wrong_film", row.warning_flags)

    def test_penalty_landing_below_medium_still_labelled_low(self) -> None:
        row = self._row(
            cand=self._weak_candidate(),
            folder_name="film.y.2010.bluray.x264",
            nfo_runtime=90,
            tmdb_runtime=160,
        )
        self.assertEqual(row.confidence, 34, "59 - 25 = 34")
        self.assertEqual(row.confidence_label, "low")

    def test_bonus_landing_above_high_still_labelled_high(self) -> None:
        row = self._row(
            cand=self._strong_candidate(),
            folder_name="Film X (2000)",
            nfo_runtime=100,
            tmdb_runtime=101,
        )
        self.assertEqual(row.confidence, 100, "97 + 20 clampe a 100")
        self.assertEqual(row.confidence_label, "high")


if __name__ == "__main__":
    unittest.main()
