"""Grappe "sentinelle falsy" : `x or DEFAUT` la ou il faut tester `is None`.

Issues #791, #698, #639, #785 (famille : #440 corrigee puis reintroduite en #611).

Defaut commun : Python evalue le FALSY, pas l'absence. Une valeur metier
legitime valant `0` / `False` / `""` est donc silencieusement remplacee par le
defaut, ou saute un filtre. Consequences observees et testees ici :

- `int(min_confidence_for_call or 90)` : un seuil OMDb regle a 0 par
  l'utilisateur (l'UI clampe [0, 100], parametres.js:210 `min: 0`) redevient 90
  -> OMDb est appele alors qu'il avait ete desactive (#791, 2 sites).
- `if rid and rid not in approved_keys` : une row au `row_id` vide contourne le
  filtre d'approbation et gonfle l'estimation d'espace disque -> faux "espace
  insuffisant" qui BLOQUE l'apply (#698).
- `int(current_weights.get("video", 60) or 60)` : un poids a 0 — explicitement
  autorise par validate_quality_profile (quality_score.py:423) — est ressuscite
  au defaut (#639).
- `str(value or "")` : `to_optional_bool` avale `False` et `0` en `None` (#785).

Correctif : le helper partage `cinesort.domain.conversions.to_int(...)` (deja
canonique : settings_support.py:1555, quality_score.py:423) la ou l'invalide
peut retomber sur le defaut, sinon un test `is None` explicite. Calibration est
dans le second cas : son entree est un `profile_json` arbitraire, donc un poids
present mais illisible reste FAIL-CLOSED (warning + aucune suggestion) au lieu
de retomber en silence sur 60/30/10.

La derniere classe de ce fichier est la regle grep-able de revue qui empeche la
famille de se reconstituer sur ces fichiers.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import tokenize
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple
from unittest import mock
from unittest.mock import MagicMock

import cinesort.domain.core as core
from cinesort.app.disk_space_check import estimate_apply_size
from cinesort.app.omdb_cross_check import cross_check_rows_with_omdb
from cinesort.domain.calibration import suggest_weight_adjustment
from cinesort.domain.conversions import to_optional_bool
from cinesort.ui.api import run_flow_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Les 5 fichiers de la grappe, gardes par la regle de revue ci-dessous.
_GRAPPE_FILES = (
    "cinesort/app/omdb_cross_check.py",
    "cinesort/ui/api/run_flow_support.py",
    "cinesort/app/disk_space_check.py",
    "cinesort/domain/calibration.py",
    "cinesort/domain/conversions.py",
)


@dataclass
class _FakeRow:
    """Stub PlanRow : uniquement les champs lus par cross_check_rows_with_omdb."""

    proposed_title: str
    proposed_year: int
    confidence: int
    warning_flags: List[str] = field(default_factory=list)


class OmdbThresholdSentinelTests(unittest.TestCase):
    """#791 site 1 — cinesort/app/omdb_cross_check.py."""

    def _client(self) -> MagicMock:
        client = MagicMock()
        client.search_by_title.return_value = None
        return client

    def test_threshold_zero_is_preserved_and_disables_all_calls(self) -> None:
        """Seuil 0 = "n'appelle jamais OMDb". Le `or 90` le ressuscitait a 90."""
        rows = [
            _FakeRow("Inception", 2010, confidence=0),
            _FakeRow("The Matrix", 1999, confidence=40),
            _FakeRow("Heat", 1995, confidence=89),
        ]
        client = self._client()
        n = cross_check_rows_with_omdb(rows, client, min_confidence_for_call=0)
        self.assertEqual(
            client.search_by_title.call_count,
            0,
            "seuil 0 : aucune row ne doit etre cross-checkee (confidence >= 0 toujours vrai)",
        )
        self.assertEqual(n, 0)

    def test_threshold_none_falls_back_to_90(self) -> None:
        """Non-regression : seule l'ABSENCE retombe sur le defaut."""
        rows = [_FakeRow("Inception", 2010, confidence=50)]
        client = self._client()
        cross_check_rows_with_omdb(rows, client, min_confidence_for_call=None)
        self.assertEqual(client.search_by_title.call_count, 1)

    def test_threshold_default_90_still_calls(self) -> None:
        """Non-regression : le comportement nominal (seuil 90) est inchange."""
        rows = [
            _FakeRow("Inception", 2010, confidence=50),
            _FakeRow("Heat", 1995, confidence=95),
        ]
        client = self._client()
        cross_check_rows_with_omdb(rows, client)
        self.assertEqual(
            client.search_by_title.call_count,
            1,
            "seuil 90 : la row a 50 est checkee, celle a 95 non",
        )


class OmdbThresholdFromSettingsTests(unittest.TestCase):
    """#791 site 2 — cinesort/ui/api/run_flow_support.py:495.

    Traverse la vraie entree publique api.run.start_plan pour prouver que la
    valeur 0 persistee par settings_support survit jusqu'a l'appelant.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_sentinel_omdb_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _create_file(self.root / "Inception.2010.1080p" / "Inception.2010.1080p.mkv")

        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _settings(self, threshold: object, present: bool = True) -> dict:
        s = {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
            "omdb_enabled": True,
            "omdb_api_key": "fake-key",
            "auto_recompute_quality_on_scan": False,
            "subtitle_detection_enabled": False,
            "perceptual_auto_on_scan": False,
        }
        if present:
            s["omdb_min_confidence_for_call"] = threshold
        return s

    def _run_and_capture_threshold(self, settings: dict) -> object:
        api = CineSortApi()
        with mock.patch.object(run_flow_support, "cross_check_rows_with_omdb", return_value=0) as mocked:
            start = api.run.start_plan(settings)
            self.assertTrue(start.get("ok"), start)
            _wait_done(api, start["run_id"], timeout_s=30.0)
        self.assertEqual(mocked.call_count, 1, "le cross-check OMDb doit etre invoque une fois")
        return mocked.call_args.kwargs["min_confidence_for_call"]

    def test_settings_threshold_zero_reaches_cross_check(self) -> None:
        got = self._run_and_capture_threshold(self._settings(0))
        self.assertEqual(got, 0, "un seuil 0 persiste en settings ne doit pas redevenir 90")

    def test_settings_threshold_absent_falls_back_to_90(self) -> None:
        got = self._run_and_capture_threshold(self._settings(None, present=False))
        self.assertEqual(got, 90)

    def test_settings_threshold_normal_value_passthrough(self) -> None:
        """Non-regression : une valeur usuelle traverse inchangee."""
        got = self._run_and_capture_threshold(self._settings(70))
        self.assertEqual(got, 70)


class DiskSpaceEmptyRowIdTests(unittest.TestCase):
    """#698 — cinesort/app/disk_space_check.py:75."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_sentinel_disk_")
        self.tmp = Path(self._tmp)
        self.folder = self.tmp / "Film"
        self.folder.mkdir(parents=True)
        (self.folder / "movie.mkv").write_bytes(b"x" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, row_id: str) -> SimpleNamespace:
        return SimpleNamespace(folder=str(self.folder), video="movie.mkv", row_id=row_id)

    def test_empty_row_id_is_not_counted(self) -> None:
        """Une row au row_id vide n'est JAMAIS dans approved_keys : elle ne doit
        pas etre sommee, sinon l'estimation gonfle et l'apply est bloque a tort."""
        size = estimate_apply_size([self._row("")], approved_keys={"r1"})
        self.assertEqual(size, 0)

    def test_missing_row_id_attribute_is_not_counted(self) -> None:
        row = SimpleNamespace(folder=str(self.folder), video="movie.mkv")
        self.assertEqual(estimate_apply_size([row], approved_keys={"r1"}), 0)

    def test_none_row_id_is_not_counted(self) -> None:
        self.assertEqual(estimate_apply_size([self._row(None)], approved_keys={"r1"}), 0)

    def test_empty_row_id_does_not_inflate_mixed_batch(self) -> None:
        """Le cas utilisateur : 1 film approuve + 1 row sans id -> une seule taille."""
        rows = [self._row("r1"), self._row("")]
        self.assertEqual(estimate_apply_size(rows, approved_keys={"r1"}), 4096)

    def test_approved_row_still_counted(self) -> None:
        """Non-regression : le chemin nominal est inchange."""
        self.assertEqual(estimate_apply_size([self._row("r1")], approved_keys={"r1"}), 4096)

    def test_rejected_row_still_skipped(self) -> None:
        """Non-regression : une row non approuvee reste exclue."""
        self.assertEqual(estimate_apply_size([self._row("r1")], approved_keys=set()), 0)


class CalibrationZeroWeightTests(unittest.TestCase):
    """#639 — cinesort/domain/calibration.py:142-144."""

    def _bias(self, focus: str, direction: str = "underscore") -> dict:
        cats = {"video": 0, "audio": 0, "extras": 0}
        cats[focus] = 5
        return {
            "bias_direction": direction,
            "bias_strength": "moderate",
            "category_bias": cats,
            "total_feedbacks": 5,
        }

    def test_zero_weight_is_not_resurrected_to_default(self) -> None:
        """Un profil qui desactive `extras` (poids 0) doit etre lu tel quel."""
        weights = {"video": 60, "audio": 30, "extras": 0}
        r = suggest_weight_adjustment(self._bias("video", "overscore"), weights)
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r["from"]["extras"], 0, "le poids 0 ne doit pas redevenir 10")
        self.assertEqual(sum(r["from"].values()), 90, "la base de reequilibrage doit valoir 60+30+0")

    def test_zero_weight_sum_invariant_uses_real_profile(self) -> None:
        weights = {"video": 60, "audio": 30, "extras": 0}
        r = suggest_weight_adjustment(self._bias("audio"), weights)
        assert r is not None
        self.assertEqual(sum(r["to"].values()), sum(weights.values()))

    def test_two_zero_weights_read_as_zero(self) -> None:
        weights = {"video": 90, "audio": 0, "extras": 0}
        r = suggest_weight_adjustment(self._bias("video", "overscore"), weights)
        assert r is not None
        self.assertEqual(r["from"], {"video": 90, "audio": 0, "extras": 0})

    def test_absent_key_still_falls_back_to_default(self) -> None:
        """Non-regression : l'ABSENCE (et non le 0) retombe bien sur le defaut."""
        r = suggest_weight_adjustment(self._bias("video", "overscore"), {"video": 60, "audio": 30})
        assert r is not None
        self.assertEqual(r["from"]["extras"], 10)

    def test_nominal_weights_unchanged(self) -> None:
        """Non-regression : le profil par defaut 60/30/10 est inchange."""
        weights = {"video": 60, "audio": 30, "extras": 10}
        r = suggest_weight_adjustment(self._bias("audio"), weights)
        assert r is not None
        self.assertEqual(r["from"], weights)
        self.assertEqual(sum(r["to"].values()), 100)

    def test_unparsable_weight_stays_fail_closed(self) -> None:
        """Un poids PRESENT mais illisible ne doit pas retomber en silence sur 60/30/10.

        `current_weights` vient d'un `profile_json` arbitraire
        (cinesort_api.py:2616-2617). Corriger la sentinelle falsy ne doit pas
        transformer ce chemin fail-closed en repli silencieux : la suggestion
        porterait sur un profil qui n'est PAS celui de l'utilisateur.
        """
        for bad in ("abc", [], {}, object()):
            with self.subTest(bad=bad):
                r = suggest_weight_adjustment(
                    self._bias("video", "overscore"),
                    {"video": bad, "audio": 30, "extras": 10},
                )
                self.assertIsNone(r, f"poids illisible {bad!r} : aucune suggestion ne doit etre emise")

    def test_unparsable_weight_is_logged_not_silent(self) -> None:
        """Le renoncement doit se VOIR : un echec ne devient jamais un succes muet."""
        with self.assertLogs("cinesort.domain.calibration", level="WARNING") as caught:
            r = suggest_weight_adjustment(
                self._bias("video", "overscore"),
                {"video": "abc", "audio": 30, "extras": 10},
            )
        self.assertIsNone(r)
        self.assertTrue(
            any("illisible" in m for m in caught.output),
            f"le poids illisible doit etre journalise en WARNING, obtenu : {caught.output}",
        )

    def test_numeric_string_weight_still_parsed(self) -> None:
        """Non-regression : une valeur LISIBLE (str numerique) reste acceptee."""
        r = suggest_weight_adjustment(
            self._bias("video", "overscore"),
            {"video": "60", "audio": "30", "extras": "0"},
        )
        assert r is not None
        self.assertEqual(r["from"], {"video": 60, "audio": 30, "extras": 0})


class ToOptionalBoolSentinelTests(unittest.TestCase):
    """#785 — cinesort/domain/conversions.py:139."""

    def test_false_stays_false(self) -> None:
        self.assertIs(to_optional_bool(False), False)

    def test_zero_int_is_false_not_none(self) -> None:
        self.assertIs(to_optional_bool(0), False)

    def test_zero_float_is_false_not_none(self) -> None:
        self.assertIs(to_optional_bool(0.0), False)

    def test_true_and_nonzero_stay_true(self) -> None:
        self.assertIs(to_optional_bool(True), True)
        self.assertIs(to_optional_bool(1), True)
        self.assertIs(to_optional_bool(2.5), True)

    def test_none_and_empty_remain_none(self) -> None:
        """Non-regression : l'absence reste None."""
        self.assertIsNone(to_optional_bool(None))
        self.assertIsNone(to_optional_bool(""))
        self.assertIsNone(to_optional_bool("   "))
        self.assertIsNone(to_optional_bool("peut-etre"))

    def test_string_forms_unchanged(self) -> None:
        """Non-regression : les callers reels (ffprobe/MediaInfo) passent des str."""
        self.assertIs(to_optional_bool("0"), False)
        self.assertIs(to_optional_bool("false"), False)
        self.assertIs(to_optional_bool("non"), False)
        self.assertIs(to_optional_bool("1"), True)
        self.assertIs(to_optional_bool("True"), True)
        self.assertIs(to_optional_bool("oui"), True)


# Types de tokens blanchis par `_code_lines`.
#
# Depuis Python 3.12 (PEP 701) une f-string n'est PLUS un token `STRING`
# unique : le tokenizer la decoupe en FSTRING_START / FSTRING_MIDDLE /
# FSTRING_END, et seul FSTRING_MIDDLE porte le texte litteral. Sans ces types,
# le litteral d'une f-string n'etait pas blanchi et un simple
# `logger.info(f"seuil {x} or 90 applique")` faisait rougir la regle sur du
# code parfaitement innocent — le seul remede aurait alors ete un
# `# sentinel-ok:` mensonger. Les expressions entre accolades restent, elles,
# du VRAI code et doivent continuer a declencher la regle (`f"{v or 90}"`).
#
# `getattr` : tolerance si le tokenizer n'expose pas ces types (Python <= 3.11,
# ou l'ancien token STRING unique couvrait deja les f-strings).
_BLANKED_TOKEN_TYPES = frozenset(
    t
    for t in (
        tokenize.COMMENT,
        tokenize.STRING,
        getattr(tokenize, "FSTRING_START", None),
        getattr(tokenize, "FSTRING_MIDDLE", None),
        getattr(tokenize, "FSTRING_END", None),
    )
    if t is not None
)


def _code_lines(path: Path) -> List[Tuple[int, str, str]]:
    """Retourne [(lineno, code_sans_commentaire_ni_str, ligne_brute)] pour *path*.

    Les commentaires et litteraux chaine — f-strings COMPRISES, cf
    `_BLANKED_TOKEN_TYPES` — sont blanchis (remplaces par des espaces, donc les
    colonnes sont conservees) : la regle ne doit pas se declencher sur un
    commentaire ou un docstring qui CITE l'idiome interdit (`... or 90`) pour
    l'expliquer.
    """
    raw = path.read_text(encoding="utf-8").splitlines()
    blanked = list(raw)
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type not in _BLANKED_TOKEN_TYPES:
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            for row in range(r1, r2 + 1):
                idx = row - 1
                if idx >= len(blanked):
                    continue
                line = blanked[idx]
                start = c1 if row == r1 else 0
                end = min(c2 if row == r2 else len(line), len(line))
                if end > start:
                    blanked[idx] = line[:start] + " " * (end - start) + line[end:]
    return [(i, blanked[i - 1], raw[i - 1]) for i in range(1, len(raw) + 1)]


class SentinelFalsyReviewRuleTests(unittest.TestCase):
    """Regle de revue grep-able : interdit `x or <defaut non nul>`.

    Le motif dangereux est le defaut NON NUL : il signifie qu'un `0` legitime
    serait ecrase. `x or 0` reste tolere (coalescence vers l'element neutre).

    Equivalent shell, documente dans le docstring de
    cinesort/domain/conversions.py :

        grep -rnE "\\bor [1-9][0-9]*(\\.[0-9]+)?\\b" cinesort/ --include=*.py | grep -vE "\\bor 0"

    Echappatoire explicite : un site ou `0` n'est pas une valeur atteignable
    porte le marqueur `# sentinel-ok: <raison>` sur sa ligne. Le marqueur est
    la justification exigee par la revue, pas un silencieux.
    """

    PATTERN = re.compile(r"\bor\s+[1-9][0-9]*(?:\.[0-9]+)?\b")
    WAIVER = "# sentinel-ok:"

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_sentinel_rule_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_grappe_files_have_no_nonzero_or_default(self) -> None:
        offenders = []
        for rel in _GRAPPE_FILES:
            path = _REPO_ROOT / rel
            self.assertTrue(path.is_file(), f"fichier de la grappe introuvable : {rel}")
            for lineno, code, raw in _code_lines(path):
                match = self.PATTERN.search(code)
                if match is None or self.WAIVER in raw:
                    continue
                offenders.append(f"{rel}:{lineno}: {code.strip()}")
        self.assertEqual(
            offenders,
            [],
            "Idiome sentinelle falsy reintroduit (`x or <defaut non nul>`) : utiliser "
            "to_int/to_float(value, default) ou un `is None` explicite (cf le docstring de "
            "cinesort/domain/conversions.py). Si le 0 est impossible a cet endroit, "
            f"documenter avec `{self.WAIVER} <raison>`. Sites : {offenders}",
        )

    def test_waiver_marker_requires_a_reason(self) -> None:
        """Un `# sentinel-ok:` nu (sans justification) n'est pas acceptable."""
        for rel in _GRAPPE_FILES:
            for lineno, _code, raw in _code_lines(_REPO_ROOT / rel):
                if self.WAIVER not in raw:
                    continue
                reason = raw.split(self.WAIVER, 1)[1].strip()
                self.assertGreaterEqual(
                    len(reason),
                    20,
                    f"{rel}:{lineno} : `# sentinel-ok:` doit etre suivi d'une raison explicite",
                )

    def test_rule_detects_the_original_idioms(self) -> None:
        """La regle doit ROUGIR sur les 5 idiomes d'origine (auto-test du garde)."""
        originals = [
            "threshold = max(0, min(100, int(min_confidence_for_call or 90)))",
            'threshold = int(settings.get("omdb_min_confidence_for_call") or 90)',
            'w_video = int(current_weights.get("video", 60) or 60)',
            'w_audio = int(current_weights.get("audio", 30) or 30)',
            'w_extras = int(current_weights.get("extras", 10) or 10)',
        ]
        for src in originals:
            with self.subTest(src=src):
                self.assertIsNotNone(self.PATTERN.search(src))

    def test_rule_tolerates_neutral_zero_coalescing(self) -> None:
        """`x or 0` / `x or 0.0` restent autorises (element neutre, pas un defaut)."""
        for src in ("idx = int(row.get('idx') or 0)", "ts = float(d.get('ts') or 0.0)"):
            with self.subTest(src=src):
                self.assertIsNone(self.PATTERN.search(src))

    def test_code_lines_blanks_comments_strings_and_fstrings(self) -> None:
        """`_code_lines` blanchit commentaire, chaine ET f-string — et rien d'autre.

        Ce test APPELLE le helper reellement utilise par la regle. Sa version
        precedente reimplementait le blanchiment en ligne avec `generate_tokens`
        et ne prouvait donc rien sur `_code_lines` : c'est exactement ainsi que
        le trou f-string (PEP 701, Python 3.12+) etait passe inapercu.
        """
        src = (
            "x = to_int(v, 90)\n"  # L1 : le correctif -> aucun hit
            "# on n'ecrit surtout pas `x or 90` ici\n"  # L2 : commentaire -> blanchi
            's = "documentation : x or 90"\n'  # L3 : chaine simple -> blanchie
            'msg = f"seuil {x} or 90 applique"\n'  # L4 : litteral de f-string -> blanchi
            "y = x or 90\n"  # L5 : VRAI idiome -> hit attendu
            'msg2 = f"valeur {v or 90}"\n'  # L6 : vrai code DANS une f-string -> hit attendu
        )
        sample = Path(self._tmp) / "sample_code_lines.py"
        sample.write_text(src, encoding="utf-8")

        hits = {lineno: self.PATTERN.search(code) is not None for lineno, code, _raw in _code_lines(sample)}

        self.assertFalse(hits[1], "le correctif `to_int(v, 90)` ne doit pas declencher la regle")
        self.assertFalse(hits[2], "un COMMENTAIRE qui cite l'idiome ne doit pas declencher la regle")
        self.assertFalse(hits[3], "un litteral CHAINE qui cite l'idiome ne doit pas declencher la regle")
        self.assertFalse(
            hits[4],
            "le texte litteral d'une F-STRING doit etre blanchi (FSTRING_MIDDLE, PEP 701) : "
            "sinon un simple log f-string fait rougir la CI sur du code innocent",
        )
        self.assertTrue(hits[5], "auto-test : le VRAI idiome `x or 90` doit etre detecte")
        self.assertTrue(
            hits[6],
            "auto-test : une EXPRESSION `v or 90` dans une f-string est du vrai code "
            "et doit rester detectee (ne pas blanchir tout le token f-string)",
        )


if __name__ == "__main__":
    unittest.main()
