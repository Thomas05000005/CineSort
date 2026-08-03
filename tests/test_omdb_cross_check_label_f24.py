"""AUDIT F24 — OMDb cross-check doit resynchroniser confidence_label.

`omdb_cross_check` mutait `row.confidence` sans jamais toucher
`confidence_label`, qui est un champ STOCKE (domain/core.py) jamais recompute en
aval : serialise verbatim dans plan.jsonl puis expose verbatim au dashboard.
Consequence : une row 72/'med' boostee a 92 gardait le badge 'med' et restait
comptee dans "Cas a verifier" (annulant le benefice du boost), et une row
88/'high' penalisee a 63 gardait un badge 'high' mensonger.

Le jumeau runtime_probe_check.py:249-252 resynchronise deja, omdb_cross_check
etait le seul mutateur de confidence sans resync.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

from cinesort.app.omdb_cross_check import cross_check_rows_with_omdb
from cinesort.app.runtime_probe_check import cross_check_rows_with_probe
from cinesort.domain import core
from cinesort.domain.runtime_matching import WARN_RUNTIME_MISMATCH
from cinesort.infra.omdb_client import OmdbResult


@dataclass
class _FakeRowWithLabel:
    """Stub PlanRow AVEC confidence_label (comme le vrai domain/core.py PlanRow)."""

    proposed_title: str
    proposed_year: Optional[int]
    confidence: int
    confidence_label: str
    warning_flags: List[str] = field(default_factory=list)


@dataclass
class _FakeRowNoLabel:
    """Stub sans le champ — comme tests/test_omdb_cross_check.py::_FakeRow."""

    proposed_title: str
    proposed_year: Optional[int]
    confidence: int
    warning_flags: List[str] = field(default_factory=list)


class _FakeOmdbClient:
    def __init__(self, result: Optional[OmdbResult]) -> None:
        self._result = result
        self.calls: List[Any] = []

    def search_by_title(self, title: str, year: int) -> Optional[OmdbResult]:
        self.calls.append((title, year))
        return self._result


def _omdb(title: str, year: Optional[int]) -> OmdbResult:
    return OmdbResult(
        imdb_id="tt0000000",
        title=title,
        year=year,
        runtime_min=120,
        genre="",
        imdb_rating=None,
        imdb_votes=None,
        awards="",
        plot="",
    )


class OmdbConfidenceLabelTests(unittest.TestCase):
    def test_convergence_resyncs_label_to_high(self) -> None:
        """ROUGE avant : confidence 92 mais label reste 'med' (row bloquee en 'a verifier')."""
        row = _FakeRowWithLabel("Inception", 2010, 72, "med")
        client = _FakeOmdbClient(_omdb("Inception", 2010))

        n = cross_check_rows_with_omdb([row], client)

        self.assertEqual(n, 1)
        self.assertEqual(row.confidence, 92)
        self.assertEqual(row.confidence_label, "high")

    def test_divergence_resyncs_label_down(self) -> None:
        """ROUGE avant : confidence 63 mais badge 'high' persiste dans plan.jsonl + dashboard."""
        row = _FakeRowWithLabel("Inception", 2010, 88, "high")
        client = _FakeOmdbClient(_omdb("Un Tout Autre Film", 1950))

        n = cross_check_rows_with_omdb([row], client)

        self.assertEqual(n, 1)
        self.assertEqual(row.confidence, 63)
        self.assertEqual(row.confidence_label, "med")
        self.assertIn("omdb_disagree", row.warning_flags)

    def test_convergence_partielle_resyncs_label(self) -> None:
        """Annee exacte + titre different -> +5 : 58/'low' passe a 63/'med'."""
        row = _FakeRowWithLabel("Inception", 2010, 58, "low")
        client = _FakeOmdbClient(_omdb("Le Commencement", 2010))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence, 63)
        self.assertEqual(row.confidence_label, "med")

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_confidence_numerique_toujours_ajustee(self) -> None:
        """Le comportement historique (mutation de row.confidence) reste intact."""
        row = _FakeRowWithLabel("Inception", 2010, 40, "low")
        client = _FakeOmdbClient(_omdb("Inception", 2010))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence, 60)

    def test_row_without_label_attribute_does_not_crash(self) -> None:
        """Les stubs sans confidence_label ne doivent pas lever AttributeError."""
        row = _FakeRowNoLabel("Inception", 2010, 72)
        client = _FakeOmdbClient(_omdb("Inception", 2010))

        n = cross_check_rows_with_omdb([row], client)

        self.assertEqual(n, 1)
        self.assertEqual(row.confidence, 92)
        self.assertFalse(hasattr(row, "confidence_label"))

    def test_noop_when_no_omdb_year_keeps_label(self) -> None:
        """OMDb sans annee -> bonus 0 : on ne reecrit PAS le label (garde `bonus`)."""
        row = _FakeRowWithLabel("Inception", 2010, 72, "high")  # label volontairement incoherent
        client = _FakeOmdbClient(_omdb("Inception", None))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence, 72)
        self.assertEqual(row.confidence_label, "high")


@dataclass
class _FakeRowWithNotes:
    """Stub PlanRow avec les TROIS champs derives du couple confidence/label."""

    proposed_title: str
    proposed_year: Optional[int]
    confidence: int
    confidence_label: str
    notes: str = ""
    warning_flags: List[str] = field(default_factory=list)


def _real_note(confidence: int, label: str) -> str:
    """Note produite par le VRAI core.build_plan_note (format authoritatif)."""
    chosen = core.Candidate(title="Inception", year=2010, score=0.9, source="tmdb", tmdb_id=27205)
    return core.build_plan_note(
        confidence=confidence,
        label=label,
        chosen=chosen,
        name_year=2010,
        name_year_reason="annee du nom",
        remaster_hint=False,
        nfo_present=False,
        nfo_ok=False,
        nfo_cov=0.0,
        nfo_seq=0.0,
        nfo_reject_reason="",
        tmdb_used=True,
    )


class OmdbConfidenceNotesTests(unittest.TestCase):
    """REVUE R1 — `notes` porte le MEME couple label/score en toutes lettres.

    core.build_plan_note ouvre la note par "Confiance MED (72/100)." ; ce champ
    est stocke, serialise verbatim dans plan.jsonl, expose par dashboard_support
    et AFFICHE tel quel ("Notes :" dans traitement.js). Resynchroniser le seul
    badge faisait dire "high" au badge et "MED (72/100)" a la note juste a cote.
    """

    def test_convergence_resynchronise_la_note(self) -> None:
        """ROUGE avant : badge 'high' mais note "Confiance MED (72/100)."."""
        row = _FakeRowWithNotes("Inception", 2010, 72, "med", _real_note(72, "med"))
        tail = row.notes.split(". ", 1)[1]
        client = _FakeOmdbClient(_omdb("Inception", 2010))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence, 92)
        self.assertEqual(row.confidence_label, "high")
        self.assertTrue(
            row.notes.startswith("Confiance HIGH (92/100)."),
            f"note perimee: {row.notes!r}",
        )
        self.assertTrue(row.notes.endswith(tail), "le reste de la note doit etre preserve verbatim")

    def test_divergence_resynchronise_la_note_vers_le_bas(self) -> None:
        row = _FakeRowWithNotes("Inception", 2010, 88, "high", _real_note(88, "high"))
        client = _FakeOmdbClient(_omdb("Un Tout Autre Film", 1950))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence, 63)
        self.assertTrue(row.notes.startswith("Confiance MED (63/100)."), f"note perimee: {row.notes!r}")

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_note_absente_ne_leve_pas(self) -> None:
        row = _FakeRowWithLabel("Inception", 2010, 72, "med")  # pas de champ notes
        client = _FakeOmdbClient(_omdb("Inception", 2010))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence_label, "high")
        self.assertFalse(hasattr(row, "notes"))

    def test_note_au_format_inconnu_laissee_intacte(self) -> None:
        """On ne mutile jamais un texte qu'on n'a pas produit."""
        row = _FakeRowWithNotes("Inception", 2010, 72, "med", "Note libre de l'utilisateur.")
        client = _FakeOmdbClient(_omdb("Inception", 2010))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.confidence_label, "high")
        self.assertEqual(row.notes, "Note libre de l'utilisateur.")

    def test_noop_sans_annee_omdb_laisse_la_note(self) -> None:
        row = _FakeRowWithNotes("Inception", 2010, 72, "med", _real_note(72, "med"))
        before = row.notes
        client = _FakeOmdbClient(_omdb("Inception", None))

        cross_check_rows_with_omdb([row], client)

        self.assertEqual(row.notes, before)


@dataclass
class _ProbeRowWithNotes:
    proposed_title: str
    proposed_year: Optional[int]
    confidence: int
    confidence_label: str
    folder: str
    video: str
    notes: str = ""
    candidates: List[Any] = field(default_factory=list)
    nfo_runtime: Optional[int] = None
    edition: Optional[str] = None
    warning_flags: List[str] = field(default_factory=list)


class RuntimeProbeJumeauNotesTests(unittest.TestCase):
    """REVUE R1 — le jumeau runtime_probe_check avait exactement le meme trou.

    Il resynchronisait `confidence_label` mais laissait `notes` perimee dans ses
    DEUX branches (reconciliation d'un faux mismatch NFO, et bonus/malus probe).
    Les deux consomment desormais le meme helper partage.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="f24_jumeau_")
        (Path(self._tmp) / "Film.mkv").write_bytes(b"\x00" * 1024)
        self.store = MagicMock()
        self.tmdb = MagicMock()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, confidence: int, label: str, **overrides: Any) -> _ProbeRowWithNotes:
        params: dict = {
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "confidence": confidence,
            "confidence_label": label,
            "folder": self._tmp,
            "video": "Film.mkv",
            "notes": _real_note(confidence, label),
            "candidates": [core.Candidate(title="Inception", year=2010, score=0.9, source="tmdb", tmdb_id=27205)],
        }
        params.update(overrides)
        return _ProbeRowWithNotes(**params)

    @patch("cinesort.infra.probe.ProbeService")
    def test_bonus_probe_resynchronise_la_note(self, mock_probe: Any) -> None:
        """ROUGE avant : confidence 90/'high' mais note "Confiance MED (70/100)."."""
        mock_probe.return_value.probe_file.return_value = {"ok": True, "normalized": {"duration_s": 148 * 60}}
        self.tmdb.get_movie_runtime.return_value = 148
        row = self._row(70, "med")

        cross_check_rows_with_probe([row], self.store, {"probe_backend": "auto"}, self.tmdb)

        self.assertEqual(row.confidence, 90)
        self.assertEqual(row.confidence_label, "high")
        self.assertTrue(row.notes.startswith("Confiance HIGH (90/100)."), f"note perimee: {row.notes!r}")

    @patch("cinesort.infra.probe.ProbeService")
    def test_reconciliation_nfo_resynchronise_la_note(self, mock_probe: Any) -> None:
        """Branche reconciliation (faux mismatch NFO) : meme resynchro."""
        mock_probe.return_value.probe_file.return_value = {"ok": True, "normalized": {"duration_s": 148 * 60}}
        self.tmdb.get_movie_runtime.return_value = 148
        row = self._row(
            50,
            "low",
            nfo_runtime=95,
            warning_flags=[WARN_RUNTIME_MISMATCH],
        )

        cross_check_rows_with_probe([row], self.store, {"probe_backend": "auto"}, self.tmdb)

        self.assertEqual(row.confidence, 95)  # 50 + 25 (penalite annulee) + 20
        self.assertEqual(row.confidence_label, "high")
        self.assertTrue(row.notes.startswith("Confiance HIGH (95/100)."), f"note perimee: {row.notes!r}")

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    @patch("cinesort.infra.probe.ProbeService")
    def test_zone_grise_ne_touche_a_rien(self, mock_probe: Any) -> None:
        mock_probe.return_value.probe_file.return_value = {"ok": True, "normalized": {"duration_s": 138 * 60}}
        self.tmdb.get_movie_runtime.return_value = 148  # delta 10 : ni bonus ni malus
        row = self._row(70, "med")
        before = row.notes

        cross_check_rows_with_probe([row], self.store, {"probe_backend": "auto"}, self.tmdb)

        self.assertEqual(row.confidence, 70)
        self.assertEqual(row.notes, before)


if __name__ == "__main__":
    unittest.main()
