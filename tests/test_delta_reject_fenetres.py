"""Une tranche de temps se COMPTE, elle ne se deduit pas par soustraction.

Constat 3 de l'audit du 2026-08-08 (#1010), verifie puis corrige.

`delta_reject` calculait ses deux moities ainsi :

    delta = (depuis_recent - depuis_fin) - (depuis_older - depuis_recent)

ou chaque terme est un `COUNT(DISTINCT row_id)`. Chaque parenthese vaut donc
`|A u B| - |B| = |A \\ B|`, et PAS `|A|` : un film Reject present dans les DEUX
moities — un re-scan, donc un second `run_id` — disparaissait de la moitie
ancienne, et l'insight annoncait une degradation qui n'avait pas eu lieu.

MESURE AVANT CORRECTIF, sur le scenario ci-dessous (verite : delta = 0) :

    moitie recente  calculee : 2   (juste)
    moitie ancienne calculee : 1   <- le film re-scanne a disparu
    delta_reject    calcule  : 1   au lieu de 0

Detail qui a oriente la fixture : `perceptual_reports` porte un
`UNIQUE(run_id, row_id)`. « Re-scanne » ne veut donc pas dire deux lignes du meme
run, mais deux runs — c'est bien le cas de production.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir

_COLONNES = (
    "row_id, run_id, ts, global_tier_v2, global_score_v2, "
    "visual_score, audio_score, global_score, global_tier, metrics_json, settings_json"
)
_VALEURS = "?, ?, ?, 'reject', 10.0, 0.0, 0.0, 10.0, 'reject', '{}', '{}'"


class UneTrancheSeCOMPTETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cs_delta_reject_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        state = self.tmp / "state"
        state.mkdir()
        self.store = SQLiteStore(db_path_for_state_dir(state))
        self.store.initialize()
        self.store.perceptual._ensure_perceptual_tables()

        jour = 86400.0
        self.now = time.time()
        self.fin_recent = self.now
        self.debut_recent = self.now - 7 * jour
        self.debut_older = self.now - 14 * jour

        # 3 films, tous Reject. Verite : ancienne = {stable, ancien} = 2,
        # recente = {stable, neuf} = 2, donc delta = 0.
        lignes = [
            ("film_stable", "run-ancien", self.debut_older + jour),
            ("film_stable", "run-recent", self.debut_recent + jour),
            ("film_ancien", "run-ancien", self.debut_older + 2 * jour),
            ("film_neuf", "run-recent", self.debut_recent + 2 * jour),
        ]
        with self.store._managed_conn() as conn:
            for row_id, run_id, ts in lignes:
                conn.execute(
                    f"INSERT INTO perceptual_reports ({_COLONNES}) VALUES ({_VALEURS})",  # noqa: S608
                    (row_id, run_id, ts),
                )

    def _compter(self, depuis: float, jusqua: float) -> int:
        return self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=depuis, until_ts=jusqua)

    def test_un_film_present_dans_les_DEUX_tranches_compte_dans_les_deux(self) -> None:
        """LE defaut. Le film re-scanne appartient aux deux moities ; le
        soustraire de l'une revient a nier qu'il y etait."""
        ancienne = self._compter(self.debut_older, self.debut_recent)
        recente = self._compter(self.debut_recent, self.fin_recent)

        self.assertEqual(ancienne, 2, "la moitie ancienne perd le film re-scanne")
        self.assertEqual(recente, 2, "la moitie recente est fausse")
        self.assertEqual(recente - ancienne, 0, "delta_reject annonce une degradation inexistante")

    def test_la_borne_haute_est_EXCLUE(self) -> None:
        """Sans exclusion, un rapport pile a la frontiere compterait DEUX fois —
        le defaut inverse, tout aussi faux."""
        frontiere = self.debut_recent
        with self.store._managed_conn() as conn:
            conn.execute(
                f"INSERT INTO perceptual_reports ({_COLONNES}) VALUES ({_VALEURS})",  # noqa: S608
                ("film_frontiere", "run-frontiere", frontiere),
            )

        ancienne = self._compter(self.debut_older, frontiere)
        recente = self._compter(frontiere, self.fin_recent)
        self.assertEqual(ancienne, 2, "le rapport pile a la frontiere a ete compte dans l'ancienne")
        self.assertEqual(recente, 3, "le rapport pile a la frontiere manque a la recente")

    def test_sans_borne_haute_le_comportement_est_INCHANGE(self) -> None:
        """CONTRE-EPREUVE : `until_ts` est optionnel, et tous les autres
        appelants comptent « depuis » sans borne. Ils ne doivent rien voir."""
        depuis_older = self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=self.debut_older)
        self.assertEqual(depuis_older, 3, "le comptage sans borne haute a change")


if __name__ == "__main__":
    unittest.main()
