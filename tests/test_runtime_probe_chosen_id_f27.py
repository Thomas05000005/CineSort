"""AUDIT F27 — _get_chosen_tmdb_id vs titre sanitize Windows.

`row.proposed_title` est produit par `windows_safe(chosen.title)`
(plan_support_replan.py:331) : ':', '?', '"' etc. sont retires. Or
`_get_chosen_tmdb_id` comparait ce titre sanitize au titre BRUT des candidats
-> le match exact echouait pour TOUT titre a caractere interdit NTFS, y compris
le chosen lui-meme, et l'ancien repli "premier candidate avec un tmdb_id"
rendait l'id du MAUVAIS film (ordre d'insertion != ordre de pick_best_candidate).

Consequence : get_movie_runtime(mauvais film) -> flag runtime_mismatch -25 a
tort (ou bonus indu) sur une row pourtant correcte.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

from cinesort.app.runtime_probe_check import _get_chosen_tmdb_id, cross_check_rows_with_probe
from cinesort.domain.runtime_matching import WARN_RUNTIME_MISMATCH


@dataclass
class _FakeCandidate:
    title: str
    year: Optional[int]
    tmdb_id: Optional[int]


@dataclass
class _FakeRow:
    proposed_title: str
    proposed_year: Optional[int]
    candidates: List[_FakeCandidate] = field(default_factory=list)


@dataclass
class _ProbeRow:
    """Stub PlanRow complet pour cross_check_rows_with_probe."""

    proposed_title: str
    proposed_year: Optional[int]
    confidence: int
    folder: str
    video: str
    candidates: List[_FakeCandidate] = field(default_factory=list)
    nfo_runtime: Optional[int] = None
    edition: Optional[str] = None
    warning_flags: List[str] = field(default_factory=list)


class ChosenTmdbIdSanitizedTitleTests(unittest.TestCase):
    def test_colon_title_matches_sanitized_proposed_title(self) -> None:
        """ROUGE avant : rend 955 (Mission: Impossible II) au lieu de 954."""
        row = _FakeRow(
            "Mission Impossible",  # windows_safe("Mission: Impossible")
            1996,
            candidates=[
                _FakeCandidate("Mission: Impossible II", 2000, 955),
                _FakeCandidate("Mission: Impossible", 1996, 954),
                _FakeCandidate("Mission Impossible", 1996, None),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 954)

    def test_question_mark_title(self) -> None:
        """ROUGE avant : un autre candidat idente precede -> son id est rendu."""
        row = _FakeRow(
            "Who Framed Roger Rabbit",  # windows_safe("Who Framed Roger Rabbit?")
            1988,
            candidates=[
                _FakeCandidate("Roger Rabbit Shorts", 1989, 111),
                _FakeCandidate("Who Framed Roger Rabbit?", 1988, 856),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 856)

    def test_ambiguous_ids_return_none(self) -> None:
        """ROUGE avant : devine 111. Un id faux vaut -25 a tort ; None ne coute qu'un bonus."""
        row = _FakeRow(
            "C",
            1996,
            candidates=[
                _FakeCandidate("A", 1996, 111),
                _FakeCandidate("B", 1996, 222),
            ],
        )
        self.assertIsNone(_get_chosen_tmdb_id(row))

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_exact_match_title_year_inchange(self) -> None:
        row = _FakeRow(
            "Inception",
            2010,
            candidates=[
                _FakeCandidate("Other", 2010, 999),
                _FakeCandidate("Inception", 2010, 27205),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 27205)

    def test_repli_candidat_unique_inchange(self) -> None:
        """Contrat historique conserve : un seul candidat idente -> c'est lui."""
        row = _FakeRow(
            "Inception (Director's Cut)",
            2010,
            candidates=[_FakeCandidate("Inception", 2010, 27205)],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 27205)

    def test_no_candidates_inchange(self) -> None:
        self.assertIsNone(_get_chosen_tmdb_id(_FakeRow("X", 2020, candidates=[])))

    def test_candidate_without_tmdb_inchange(self) -> None:
        row = _FakeRow("X", 2020, candidates=[_FakeCandidate("X", 2020, None)])
        self.assertIsNone(_get_chosen_tmdb_id(row))


class SanitizeBrancheSeuleTests(unittest.TestCase):
    """REVUE R1 — cas ou SEULE la comparaison `windows_safe(c_title) == title`
    peut trancher.

    Les 3 tests "ROUGE avant" ci-dessus etaient en realite rattrapes par les
    replis 2/3 ajoutes dans le MEME correctif (un seul tmdb_id distinct sur
    l'annee) : neutraliser la branche sanitize les laissait tous VERTS. Ici les
    deux candidats partagent l'annee ET portent des ids DIFFERENTS, donc les
    replis rendent None : seule la comparaison sanitize donne le bon id.
    """

    def test_deux_candidats_meme_annee_seul_le_sanitize_tranche(self) -> None:
        row = _FakeRow(
            "Mission Impossible",  # windows_safe("Mission: Impossible")
            1996,
            candidates=[
                _FakeCandidate("Mission: Impossible", 1996, 954),
                _FakeCandidate("Mission Impossible Fanedit", 1996, 999),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 954)

    def test_point_dinterrogation_deux_candidats_meme_annee(self) -> None:
        row = _FakeRow(
            "Who Framed Roger Rabbit",  # windows_safe("Who Framed Roger Rabbit?")
            1988,
            candidates=[
                _FakeCandidate("Who Framed Roger Rabbit Bonus Disc", 1988, 999),
                _FakeCandidate("Who Framed Roger Rabbit?", 1988, 856),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 856)

    def test_guillemets_deux_candidats_meme_annee(self) -> None:
        row = _FakeRow(
            "Good Morning Vietnam",  # windows_safe('Good Morning, "Vietnam"') garde la virgule
            1987,
            candidates=[
                _FakeCandidate("Good Morning Vietnam Redux", 1987, 999),
                _FakeCandidate('Good Morning "Vietnam"', 1987, 783),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 783)

    # ---- non-regression (VERT des deux cotes de la mutation sanitize) ----

    def test_titre_sans_caractere_interdit_toujours_matche(self) -> None:
        row = _FakeRow(
            "Dune",
            2021,
            candidates=[
                _FakeCandidate("Dune Part Two", 2021, 999),
                _FakeCandidate("Dune", 2021, 438631),
            ],
        )
        self.assertEqual(_get_chosen_tmdb_id(row), 438631)

    def test_aucun_titre_ne_matche_reste_none(self) -> None:
        row = _FakeRow(
            "Un Film Absent",
            1996,
            candidates=[
                _FakeCandidate("A", 1996, 111),
                _FakeCandidate("B", 1996, 222),
            ],
        )
        self.assertIsNone(_get_chosen_tmdb_id(row))


class AmbiguiteDetectionConserveeTests(unittest.TestCase):
    """REVUE R1 — le `return None` sur ambiguite fermait AUSSI la detection.

    `runtime_mismatch_likely_wrong_film` appartient a `_CONFLICT_FLAGS` donc a
    `_AUTO_BLOCKING` (run_read_support) : ne plus jamais le poser rend
    auto-approuvable (et donc deplacable par l'apply) une row MAL identifiee qui
    etait bloquee avant. On retablit la detection SANS deviner : verdict
    uniquement si la duree mesuree diverge de TOUS les candidats concurrents.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="f27_r1_")
        (Path(self._tmp) / "Film.mkv").write_bytes(b"\x00" * 1024)
        self.store = MagicMock()
        self.tmdb = MagicMock()
        self.settings = {"probe_backend": "auto"}

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, candidates: List[_FakeCandidate]) -> _ProbeRow:
        return _ProbeRow(
            proposed_title="Le Voyage",
            proposed_year=2005,
            confidence=70,
            folder=self._tmp,
            video="Film.mkv",
            candidates=candidates,
        )

    @staticmethod
    def _probe(mock_probe: Any, minutes: int) -> None:
        mock_probe.return_value.probe_file.return_value = {
            "ok": True,
            "normalized": {"duration_s": minutes * 60},
        }

    def _runtimes(self, mapping: dict) -> None:
        self.tmdb.get_movie_runtime.side_effect = lambda mid: mapping.get(int(mid))

    _AMBIGU = [
        _FakeCandidate("Le Grand Voyage", 2005, 111),
        _FakeCandidate("Voyage au bout", 2005, 222),
    ]

    # ---- preuve : la detection revient ----

    @patch("cinesort.infra.probe.ProbeService")
    def test_mismatch_pose_quand_tous_les_candidats_divergent(self, mock_probe: Any) -> None:
        """ROUGE avant : aucun cross-check du tout, la row perd son flag bloquant."""
        self._probe(mock_probe, 90)
        self._runtimes({111: 140, 222: 145})
        rows = [self._row(self._AMBIGU)]

        n = cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.assertEqual(n, 1)
        self.assertIn(WARN_RUNTIME_MISMATCH, rows[0].warning_flags)
        self.assertEqual(rows[0].confidence, 45)  # 70 - 25

    # ---- garde-fous : on ne devine toujours pas ----

    @patch("cinesort.infra.probe.ProbeService")
    def test_aucun_verdict_si_un_seul_candidat_colle(self, mock_probe: Any) -> None:
        self._probe(mock_probe, 90)
        self._runtimes({111: 140, 222: 91})
        rows = [self._row(self._AMBIGU)]

        cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.assertEqual(rows[0].warning_flags, [])
        self.assertEqual(rows[0].confidence, 70)

    @patch("cinesort.infra.probe.ProbeService")
    def test_aucun_bonus_en_mode_ambigu(self, mock_probe: Any) -> None:
        """Asymetrie VOLONTAIRE : remonter la confidence d'une row ambigue
        elargirait l'auto-approbation (le "bonus indu" que F27 fermait)."""
        self._probe(mock_probe, 140)
        self._runtimes({111: 140, 222: 140})
        rows = [self._row(self._AMBIGU)]

        cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.assertEqual(rows[0].confidence, 70)
        self.assertEqual(rows[0].warning_flags, [])

    @patch("cinesort.infra.probe.ProbeService")
    def test_aucun_verdict_si_un_concurrent_na_pas_de_runtime(self, mock_probe: Any) -> None:
        """Impossible de prouver que la duree diverge de TOUS -> fail-closed."""
        self._probe(mock_probe, 90)
        self._runtimes({111: 140, 222: None})
        rows = [self._row(self._AMBIGU)]

        cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.assertEqual(rows[0].warning_flags, [])
        self.assertEqual(rows[0].confidence, 70)

    @patch("cinesort.infra.probe.ProbeService")
    def test_trop_de_candidats_on_renonce(self, mock_probe: Any) -> None:
        """Au-dela de _MAX_AMBIGUOUS_IDS : ni requetes TMDb, ni verdict."""
        self._probe(mock_probe, 90)
        self._runtimes({i: 140 for i in range(101, 110)})
        rows = [self._row([_FakeCandidate(f"T{i}", 2005, 100 + i) for i in range(1, 6)])]

        cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.tmdb.get_movie_runtime.assert_not_called()
        self.assertEqual(rows[0].warning_flags, [])
        self.assertEqual(rows[0].confidence, 70)

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    @patch("cinesort.infra.probe.ProbeService")
    def test_chosen_resolu_une_seule_requete_tmdb(self, mock_probe: Any) -> None:
        """Le chemin nominal (chosen identifie) est inchange : 1 seul id interroge."""
        self._probe(mock_probe, 148)
        self._runtimes({27205: 148, 999: 90})
        rows = [
            self._row(
                [
                    _FakeCandidate("Autre", 2005, 999),
                    _FakeCandidate("Le Voyage", 2005, 27205),
                ]
            )
        ]

        n = cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.assertEqual(n, 1)
        self.assertEqual(rows[0].confidence, 90)  # 70 + 20
        self.assertEqual(self.tmdb.get_movie_runtime.call_count, 1)

    @patch("cinesort.infra.probe.ProbeService")
    def test_aucun_candidat_idente_reste_skippe(self, mock_probe: Any) -> None:
        rows = [self._row([_FakeCandidate("X", 2005, None)])]

        cross_check_rows_with_probe(rows, self.store, self.settings, self.tmdb)

        self.tmdb.get_movie_runtime.assert_not_called()
        self.assertEqual(rows[0].confidence, 70)


if __name__ == "__main__":
    unittest.main()
